"""SceneGlow state coordinator and event-stream lifecycle."""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import replace
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_RGB_COLOR,
    ATTR_SUPPORTED_COLOR_MODES,
    ATTR_TRANSITION,
)
from homeassistant.components.light.const import COLOR_MODES_COLOR, LightEntityFeature
from homeassistant.components.light.const import DOMAIN as LIGHT_DOMAIN
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID, SERVICE_TURN_OFF, SERVICE_TURN_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .api import (
    SceneGlowApiClient,
    SceneGlowApiError,
    SceneGlowAuthenticationError,
    SceneGlowCannotConnect,
    SceneGlowConflictError,
    SceneGlowControlNotFoundError,
    SceneGlowControlUnavailableError,
)
from .const import (
    DOMAIN,
    PROTOCOL_VERSION,
    RECONCILE_INTERVAL,
)
from .models import (
    SceneGlowCapabilities,
    SceneGlowConfigurationCollection,
    SceneGlowEvent,
    SceneGlowFixture,
    SceneGlowFixtureCollection,
    SceneGlowSnapshot,
)

_LOGGER = logging.getLogger(__name__)
_COLOR_MODE_VALUES = frozenset(mode.value for mode in COLOR_MODES_COLOR)


class SceneGlowCoordinator(DataUpdateCoordinator[SceneGlowSnapshot]):
    """Keep an authoritative snapshot current with push plus reconciliation."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: SceneGlowApiClient,
        capabilities: SceneGlowCapabilities | None = None,
    ) -> None:
        """Initialize a coordinator for one config entry."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"SceneGlow {entry.unique_id}",
        )
        self.client = client
        self.entry = entry
        self.capabilities = capabilities or SceneGlowCapabilities()
        self.connected = False
        self.event_reconnects = 0
        self.events_received = 0
        self.last_error_category: str | None = None
        self._stream_epoch: str | None = None
        self._sequence: int | None = None
        self._event_task: asyncio.Task[None] | None = None
        self._reconcile_task: asyncio.Task[None] | None = None
        self._write_lock = asyncio.Lock()
        self._control_refresh_task: asyncio.Task[None] | None = None
        self._diagnostics_listeners: set[Callable[[], None]] = set()

    def async_add_diagnostics_listener(
        self, update_callback: Callable[[], None]
    ) -> Callable[[], None]:
        """Listen for high-frequency diagnostics-only state changes."""
        self._diagnostics_listeners.add(update_callback)

        def remove_listener() -> None:
            self._diagnostics_listeners.discard(update_callback)

        return remove_listener

    async def _async_update_data(self) -> SceneGlowSnapshot:
        """Fetch a full service and supported-control snapshot."""
        try:
            state = await self.client.async_get_state()
            fixtures = (
                await self.client.async_get_fixtures()
                if self.capabilities.fixtures
                else None
            )
            configuration = (
                await self.client.async_get_configuration()
                if self.capabilities.configuration
                else None
            )
        except SceneGlowAuthenticationError as err:
            self._set_connected(False, "authentication")
            self.entry.async_start_reauth(self.hass)
            raise UpdateFailed(str(err)) from err
        except SceneGlowApiError as err:
            self._set_connected(False, type(err).__name__)
            raise UpdateFailed(str(err)) from err
        self._set_connected(True)
        return SceneGlowSnapshot(
            state=state,
            fixtures=fixtures,
            configuration=configuration,
        )

    async def async_start(self) -> None:
        """Perform initial sync and start background synchronization."""
        await self.async_config_entry_first_refresh()
        self._event_task = self.entry.async_create_background_task(
            self.hass,
            self._async_event_loop(),
            f"sceneglow-events-{self.entry.entry_id}",
        )
        self._reconcile_task = self.entry.async_create_background_task(
            self.hass,
            self._async_reconcile_loop(),
            f"sceneglow-reconcile-{self.entry.entry_id}",
        )

    async def async_stop(self) -> None:
        """Stop all config-entry-owned background tasks."""
        tasks = [task for task in (self._event_task, self._reconcile_task) if task]
        for task in tasks:
            task.cancel()
        for task in tasks:
            with suppress(asyncio.CancelledError):
                await task
        self._event_task = None
        self._reconcile_task = None
        if self._control_refresh_task is not None:
            self._control_refresh_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._control_refresh_task
            self._control_refresh_task = None
        self._set_connected(False)

    async def async_start_service(self) -> None:
        """Request the running target and publish the returned state."""
        state = await self.client.async_start_service()
        self._set_connected(True)
        self.async_set_updated_data(replace(self.data, state=state))

    async def async_stop_service(self) -> None:
        """Clear the running target and publish the returned state."""
        state = await self.client.async_stop_service()
        self._set_connected(True)
        self.async_set_updated_data(replace(self.data, state=state))

    async def async_pause_service(self) -> None:
        """Pause processing and publish the immediate returned snapshot."""
        state = await self.client.async_pause_service()
        self._set_connected(True)
        self.async_set_updated_data(replace(self.data, state=state))

    async def async_resume_service(self) -> None:
        """Resume processing and publish the immediate returned snapshot."""
        state = await self.client.async_resume_service()
        self._set_connected(True)
        self.async_set_updated_data(replace(self.data, state=state))

    async def async_set_fixture_enabled(self, fixture_uuid: str, enabled: bool) -> None:
        """Set fixture participation with one bounded conflict retry."""
        async with self._write_lock:
            for attempt in range(2):
                fixtures = self.data.fixtures
                if fixtures is None:
                    raise SceneGlowControlNotFoundError(
                        "Fixture controls are not available"
                    )
                try:
                    updated = await self.client.async_set_fixture_enabled(
                        fixture_uuid, fixtures.revision, enabled
                    )
                except SceneGlowConflictError:
                    await self._async_request_control_refresh()
                    if attempt == 0:
                        continue
                    raise
                except SceneGlowControlNotFoundError:
                    await self._async_request_control_refresh()
                    raise
                self._install_fixture_collection(updated)
                return

    async def async_set_fixture_control_value(
        self,
        fixture_uuid: str,
        key: str,
        value: bool | str | int | float,
    ) -> None:
        """Set one fixture control, atomically including coupled values."""
        async with self._write_lock:
            for attempt in range(2):
                fixture = self._fixture(fixture_uuid)
                control = next(
                    (item for item in fixture.controls if item.key == key), None
                )
                if control is None:
                    raise SceneGlowControlNotFoundError(
                        f"Fixture control {key} is not available"
                    )
                if control.read_only or not control.available:
                    raise SceneGlowControlUnavailableError(
                        f"Fixture control {key} cannot be changed"
                    )
                fixtures = self.data.fixtures
                if fixtures is None:
                    raise SceneGlowControlNotFoundError(
                        "Fixture controls are not available"
                    )
                try:
                    values = self._coupled_fixture_values(fixture, key, value)
                    if values is None:
                        updated = await self.client.async_set_fixture_value(
                            fixture_uuid, fixtures.revision, key, value
                        )
                    else:
                        updated = await self.client.async_set_fixture_values(
                            fixture_uuid, fixtures.revision, values
                        )
                except SceneGlowConflictError:
                    await self._async_request_control_refresh()
                    if attempt == 0:
                        continue
                    raise
                except SceneGlowControlNotFoundError:
                    await self._async_request_control_refresh()
                    raise
                self._install_fixture_collection(updated)
                return

    async def async_set_fixture_control_values(
        self,
        fixture_uuid: str,
        values: Mapping[str, bool | str | int | float],
    ) -> None:
        """Set an explicit group of fixture controls atomically."""
        if not values:
            raise ValueError("Fixture values must not be empty")
        async with self._write_lock:
            for attempt in range(2):
                fixture = self._fixture(fixture_uuid)
                controls = {control.key: control for control in fixture.controls}
                if any(key not in controls for key in values):
                    raise SceneGlowControlNotFoundError(
                        "One or more fixture controls do not exist"
                    )
                if any(
                    controls[key].read_only or not controls[key].available
                    for key in values
                ):
                    raise SceneGlowControlUnavailableError(
                        "One or more fixture controls cannot be changed"
                    )
                fixtures = self.data.fixtures
                if fixtures is None:
                    raise SceneGlowControlNotFoundError(
                        "Fixture controls are not available"
                    )
                try:
                    updated = await self.client.async_set_fixture_values(
                        fixture_uuid, fixtures.revision, values
                    )
                except SceneGlowConflictError:
                    await self._async_request_control_refresh()
                    if attempt == 0:
                        continue
                    raise
                except SceneGlowControlNotFoundError:
                    await self._async_request_control_refresh()
                    raise
                self._install_fixture_collection(updated)
                return

    def _fixture(self, fixture_uuid: str) -> SceneGlowFixture:
        fixtures = self.data.fixtures
        if fixtures is not None:
            fixture = next(
                (
                    item
                    for item in fixtures.fixtures
                    if item.fixture_uuid == fixture_uuid
                ),
                None,
            )
            if fixture is not None:
                return fixture
        raise SceneGlowControlNotFoundError("Fixture is not available")

    @staticmethod
    def _coupled_fixture_values(
        fixture: SceneGlowFixture,
        key: str,
        value: bool | str | int | float,
    ) -> dict[str, bool | str | int | float] | None:
        """Build atomic mutations for server-validated coupled controls."""
        current = {control.key: control.value for control in fixture.controls}
        edge_keys = ("left_leds", "top_leds", "right_leds", "bottom_leds")
        if key in edge_keys:
            if not all(item in current for item in edge_keys):
                return None
            values = {item: current[item] for item in edge_keys}
            values[key] = value
            values["led_count"] = sum(int(values[item]) for item in edge_keys)
            return values
        if key in {"led_count", "fixture_layout"}:
            keys: tuple[str, ...] = ("fixture_layout", "led_count", *edge_keys)
            if not all(item in current for item in (*keys, "first_led")):
                return None
            values = {item: current[item] for item in keys}
            values["first_led"] = current["first_led"]
            values[key] = value
            if (
                key == "led_count"
                and isinstance(value, int)
                and not isinstance(value, bool)
            ):
                fixed_edges = sum(int(values[item]) for item in edge_keys[:-1])
                adjusted_bottom = value - fixed_edges
                if 0 <= adjusted_bottom <= 1_024:
                    values["bottom_leds"] = adjusted_bottom
            return values
        if key == "first_led":
            if "led_count" not in current:
                return None
            return {
                "first_led": value,
                "led_count": current["led_count"],
            }
        if key in {"minimum_brightness_percent", "maximum_brightness_percent"}:
            keys = ("minimum_brightness_percent", "maximum_brightness_percent")
            if not all(item in current for item in keys):
                return None
            values = {item: current[item] for item in keys}
            values[key] = value
            return values
        return None

    async def async_set_configuration_enabled(self, key: str, enabled: bool) -> None:
        """Set an application control with one bounded conflict retry."""
        async with self._write_lock:
            for attempt in range(2):
                configuration = self.data.configuration
                if configuration is None:
                    raise SceneGlowControlNotFoundError(
                        "Configuration controls are not available"
                    )
                try:
                    updated = await self.client.async_set_configuration_enabled(
                        key, configuration.revision, enabled
                    )
                except SceneGlowConflictError:
                    await self._async_request_control_refresh()
                    refreshed = self.data.configuration
                    refreshed_control = (
                        next(
                            (
                                control
                                for control in refreshed.switches
                                if control.key == key
                            ),
                            None,
                        )
                        if refreshed is not None
                        else None
                    )
                    if (
                        refreshed_control is not None
                        and refreshed_control.enabled is enabled
                    ):
                        return
                    if attempt == 0:
                        continue
                    raise
                except SceneGlowControlNotFoundError:
                    await self._async_request_control_refresh()
                    raise
                self._install_configuration_collection(updated)
                return

    def _install_fixture_collection(self, fixtures: SceneGlowFixtureCollection) -> None:
        """Publish a PATCH response and advance the shared sibling revision."""
        if fixtures.revision < self._latest_control_revision():
            return
        configuration = self.data.configuration
        if configuration is not None and configuration.revision != fixtures.revision:
            configuration = replace(configuration, revision=fixtures.revision)
        self._set_connected(True)
        self.async_set_updated_data(
            replace(self.data, fixtures=fixtures, configuration=configuration)
        )

    def _install_configuration_collection(
        self, configuration: SceneGlowConfigurationCollection
    ) -> None:
        """Publish a PATCH response and advance the shared sibling revision."""
        if configuration.revision < self._latest_control_revision():
            return
        fixtures = self.data.fixtures
        if fixtures is not None and fixtures.revision != configuration.revision:
            fixtures = replace(fixtures, revision=configuration.revision)
        self._set_connected(True)
        self.async_set_updated_data(
            replace(self.data, fixtures=fixtures, configuration=configuration)
        )

    def _latest_control_revision(self) -> int:
        """Return the newest aggregate settings revision currently installed."""
        return max(
            (
                collection.revision
                for collection in (self.data.fixtures, self.data.configuration)
                if collection is not None
            ),
            default=-1,
        )

    async def _async_request_control_refresh(self) -> None:
        """Coalesce overlapping authoritative control refreshes."""
        existing_task = self._control_refresh_task
        if existing_task is None or existing_task.done():
            task = self.hass.async_create_task(
                self._async_refresh_control_collections(),
                f"sceneglow-controls-{self.entry.entry_id}",
            )
            self._control_refresh_task = task
        else:
            task = existing_task
        try:
            await asyncio.shield(task)
        finally:
            if self._control_refresh_task is task and task.done():
                self._control_refresh_task = None

    async def _async_refresh_control_collections(self) -> None:
        """Refresh every supported collection sharing the settings revision."""
        try:
            fixtures = (
                await self.client.async_get_fixtures()
                if self.capabilities.fixtures
                else None
            )
            configuration = (
                await self.client.async_get_configuration()
                if self.capabilities.configuration
                else None
            )
        except SceneGlowAuthenticationError:
            self._set_connected(False, "authentication")
            self.entry.async_start_reauth(self.hass)
            raise
        except SceneGlowApiError as err:
            self._set_connected(False, type(err).__name__)
            raise
        self._set_connected(True)
        self.async_set_updated_data(
            replace(
                self.data,
                fixtures=fixtures,
                configuration=configuration,
            )
        )

    def _set_connected(self, connected: bool, error: str | None = None) -> None:
        changed = connected != self.connected
        self.connected = connected
        self.last_error_category = error
        if changed:
            self.async_update_listeners()

    async def _async_reconcile_loop(self) -> None:
        """Refresh on an independent timer that push updates cannot postpone."""
        while True:
            await asyncio.sleep(RECONCILE_INTERVAL.total_seconds())
            await self.async_refresh()

    async def _async_event_loop(self) -> None:
        """Reconnect to the event channel with bounded exponential backoff."""
        attempt = 0
        while True:
            try:
                async for event in self.client.async_events(
                    self._async_handle_broker_request
                ):
                    attempt = 0
                    self._set_connected(True)
                    await self._async_handle_event(event)
                raise SceneGlowCannotConnect("SceneGlow event stream closed")
            except asyncio.CancelledError:
                raise
            except SceneGlowAuthenticationError:
                self._set_connected(False, "authentication")
                self.entry.async_start_reauth(self.hass)
                return
            except (SceneGlowApiError, OSError) as err:
                self._set_connected(False, type(err).__name__)
                attempt += 1
                self.event_reconnects += 1
                delay = min(60.0, 2 ** min(attempt, 5)) + random.uniform(0, 1)
                _LOGGER.debug("SceneGlow event reconnect in %.1fs: %s", delay, err)
                await asyncio.sleep(delay)
                await self.async_refresh()

    async def _async_handle_event(self, event: SceneGlowEvent) -> None:
        """Apply one ordered event or reconcile after any stream gap."""
        self.events_received += 1
        if event.event_type == "subscribed":
            self._stream_epoch = event.stream_epoch
            self._sequence = event.sequence
            if event.state is not None:
                self.async_set_updated_data(replace(self.data, state=event.state))
            await self.async_refresh()
            return

        if (
            self._stream_epoch != event.stream_epoch
            or self._sequence is None
            or event.sequence != self._sequence + 1
        ):
            self._stream_epoch = event.stream_epoch
            self._sequence = event.sequence
            await self.async_refresh()
            return
        self._sequence = event.sequence

        if event.event_type == "service_state_changed" and event.state is not None:
            current = self.data.state
            state = event.state
            if (
                state.requested_running == current.requested_running
                and state.capture_state is current.capture_state
                and state.error_category == current.error_category
            ):
                if state.diagnostics != current.diagnostics:
                    self.data = replace(self.data, state=state)
                    for update_callback in tuple(self._diagnostics_listeners):
                        update_callback()
            else:
                self.async_set_updated_data(replace(self.data, state=state))
            return

        if event.event_type in {"configuration_changed", "fixture_changed"}:
            await self._async_request_control_refresh()
            return

        if event.event_type == "authentication_changed" and event.paired is False:
            self._set_connected(False, "authentication")
            self.entry.async_start_reauth(self.hass)

    async def _async_handle_broker_request(
        self,
        request: dict[str, Any],
    ) -> dict[str, Any]:
        """Perform one constrained, compatibility-checked light broker operation."""
        request_type = request.get("type")
        request_id = request.get("request_id")
        response_type = (
            {
                "ha.light.area.catalog.request": "ha.light.area.catalog.response",
                "ha.light.catalog.request": "ha.light.catalog.response",
                "ha.light.apply.request": "ha.light.apply.result",
            }.get(request_type, "ha.light.error")
            if isinstance(request_type, str)
            else "ha.light.error"
        )
        response: dict[str, Any] = {
            "type": response_type,
            "api_version": PROTOCOL_VERSION,
            "request_id": request_id if isinstance(request_id, str) else "",
        }
        try:
            if request_type == "ha.light.area.catalog.request":
                response.update(self._light_area_catalogue_response())
            elif request_type == "ha.light.catalog.request":
                requested_area = request.get("area_id")
                if requested_area is not None and not isinstance(requested_area, str):
                    raise ValueError("invalid_area_id")
                response.update(self._light_catalogue_response(requested_area))
            elif request_type == "ha.light.apply.request":
                await self._async_apply_light(request)
                response["status"] = "applied"
            else:
                response["error"] = "unsupported_broker_request"
        except ValueError as err:
            response["error"] = str(err)
        except Exception:
            _LOGGER.exception("SceneGlow Home Assistant light broker request failed")
            response["error"] = "service_call_failed"
        return response

    def _compatible_registry_entries(self) -> list[er.RegistryEntry]:
        """Return enabled HA light entries eligible for constrained control."""
        registry = er.async_get(self.hass)
        return [
            entry
            for entry in registry.entities.values()
            if entry.domain == LIGHT_DOMAIN and entry.disabled_by is None
        ]

    def _light_area_catalogue_response(self) -> dict[str, Any]:
        """Build compact Area metadata before a selected-Area light request."""
        counts: dict[str, tuple[str, int]] = {}
        for light in self._light_catalogue():
            area_id = light["area_id"]
            area_name, count = counts.get(area_id, (light["area_name"], 0))
            counts[area_id] = (area_name, count + 1)
        default_area_id, default_area_name = self._default_area()
        return {
            "areas": sorted(
                (
                    {
                        "area_id": area_id,
                        "area_name": area_name,
                        "compatible_light_count": count,
                    }
                    for area_id, (area_name, count) in counts.items()
                ),
                key=lambda area: area["area_name"].lower(),
            ),
            "default_area_id": default_area_id,
            "default_area_name": default_area_name,
        }

    def _light_catalogue_response(
        self, requested_area_id: str | None = None
    ) -> dict[str, Any]:
        """Build a compatible catalogue, optionally scoped to one HA Area."""
        default_area_id, default_area_name = self._default_area()
        return {
            "lights": self._light_catalogue(requested_area_id),
            "default_area_id": default_area_id,
            "default_area_name": default_area_name,
        }

    def _default_area(self) -> tuple[str, str]:
        """Return the HA Area assigned to the SceneGlow parent device."""
        devices = dr.async_get(self.hass)
        device = devices.async_get_device(identifiers={(DOMAIN, self.entry.unique_id)})
        if device is None or device.area_id is None:
            return "", ""
        area = ar.async_get(self.hass).async_get_area(device.area_id)
        return device.area_id, area.name if area else device.area_id

    def _light_catalogue(
        self, requested_area_id: str | None = None
    ) -> list[dict[str, Any]]:
        """Build compatible HA lights, optionally for only one Area."""
        areas = ar.async_get(self.hass)
        devices = dr.async_get(self.hass)
        result: list[dict[str, Any]] = []
        for entry in self._compatible_registry_entries():
            state = self.hass.states.get(entry.entity_id)
            if state is None or not self._supports_color(state.attributes):
                continue
            color_modes = state.attributes.get(ATTR_SUPPORTED_COLOR_MODES, [])
            area_id = entry.area_id
            if not area_id and entry.device_id:
                device = devices.async_get(entry.device_id)
                area_id = device.area_id if device else None
            resolved_area_id = area_id or ""
            if requested_area_id is not None and resolved_area_id != requested_area_id:
                continue
            area = areas.async_get_area(resolved_area_id) if resolved_area_id else None
            result.append(
                {
                    "reference": entry.id,
                    "entity_id": entry.entity_id,
                    "name": entry.name or entry.original_name or state.name,
                    "area_id": resolved_area_id,
                    "area_name": area.name if area else "Unassigned",
                    "supported_color_modes": sorted(str(mode) for mode in color_modes),
                    "supports_transition": bool(
                        state.attributes.get("supported_features", 0)
                        & LightEntityFeature.TRANSITION
                    ),
                }
            )
        return sorted(result, key=lambda light: light["name"].lower())

    async def _async_apply_light(self, request: dict[str, Any]) -> None:
        reference = request.get("reference")
        if not isinstance(reference, str):
            raise ValueError("invalid_reference")
        entry = next(
            (
                candidate
                for candidate in self._compatible_registry_entries()
                if candidate.id == reference
            ),
            None,
        )
        if entry is None:
            raise ValueError("unknown_reference")
        state = self.hass.states.get(entry.entity_id)
        if state is None:
            raise ValueError("unavailable_reference")
        if not self._supports_color(state.attributes):
            raise ValueError("unsupported_reference")
        brightness = request.get("brightness")
        if (
            not isinstance(brightness, int)
            or isinstance(brightness, bool)
            or brightness not in range(256)
        ):
            raise ValueError("invalid_brightness")
        service_data: dict[str, Any] = {ATTR_ENTITY_ID: entry.entity_id}
        if brightness == 0:
            service = SERVICE_TURN_OFF
        else:
            rgb = (request.get("red"), request.get("green"), request.get("blue"))
            if any(
                not isinstance(value, int)
                or isinstance(value, bool)
                or value not in range(256)
                for value in rgb
            ):
                raise ValueError("invalid_rgb")
            transition_ms = request.get("transition_ms", 0)
            if (
                not isinstance(transition_ms, int)
                or isinstance(transition_ms, bool)
                or transition_ms not in range(10_001)
            ):
                raise ValueError("invalid_transition")
            service = SERVICE_TURN_ON
            service_data.update(
                {
                    ATTR_RGB_COLOR: rgb,
                    ATTR_BRIGHTNESS: brightness,
                }
            )
            if (
                state.attributes.get("supported_features", 0)
                & LightEntityFeature.TRANSITION
            ):
                service_data[ATTR_TRANSITION] = transition_ms / 1000
        await self.hass.services.async_call(
            LIGHT_DOMAIN,
            service,
            service_data,
            blocking=True,
        )

    @staticmethod
    def _supports_color(attributes: Mapping[str, Any]) -> bool:
        color_modes = attributes.get(ATTR_SUPPORTED_COLOR_MODES, [])
        return isinstance(color_modes, (list, tuple, set)) and bool(
            set(color_modes) & _COLOR_MODE_VALUES
        )
