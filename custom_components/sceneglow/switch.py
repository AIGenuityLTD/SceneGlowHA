"""Service, fixture, and configuration switches for SceneGlow."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SceneGlowConfigEntry, SceneGlowRuntimeData
from .api import (
    SceneGlowApiError,
    SceneGlowConflictError,
    SceneGlowControlNotFoundError,
    SceneGlowControlUnavailableError,
    SceneGlowInvalidConfigurationError,
)
from .const import DOMAIN
from .entity import SceneGlowEntity
from .fixture import (
    SceneGlowFixtureControlEntity,
    fixture_device_info,
    fixture_device_name,
)
from .models import (
    CaptureState,
    SceneGlowFixture,
    SceneGlowFixtureControl,
    SceneGlowFixtureControlType,
)
from .models import (
    SceneGlowConfigurationSwitch as SceneGlowConfigurationControl,
)

CONFIGURATION_TRANSLATION_KEYS = {
    "home_assistant_ambience",
    "detect_black_bars",
    "capture_indicator_exclusion",
    "performance_diagnostics",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SceneGlowConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up SceneGlow switches."""
    entities: list[SwitchEntity] = []
    if entry.runtime_data.capabilities.service_control:
        entities.append(SceneGlowCaptureSwitch(entry.runtime_data))
    if entry.runtime_data.capabilities.capture_pause:
        entities.append(SceneGlowCaptureProcessingSwitch(entry.runtime_data))
    manager = SceneGlowSwitchManager(hass, entry, async_add_entities)
    entities.extend(manager.initial_entities())
    async_add_entities(entities)
    entry.async_on_unload(manager.start())


class SceneGlowCaptureSwitch(SceneGlowEntity, SwitchEntity):
    """Requested-running target, distinct from actual capture state."""

    _attr_translation_key = "capture"
    _unrecorded_attributes = frozenset({"permission"})

    def __init__(self, runtime: SceneGlowRuntimeData) -> None:
        """Initialize the capture switch."""
        super().__init__(runtime, "capture")

    @property
    def is_on(self) -> bool:
        """Return the requested target, including while consent is pending."""
        return self.coordinator.data.state.requested_running

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        """Explain that a new session requires device-side permission."""
        return {
            "permission": (
                "Starting a stopped capture session requires confirmation "
                "on the SceneGlow device."
            )
        }

    async def async_turn_on(self, **kwargs: object) -> None:
        """Request startup without implying MediaProjection consent."""
        try:
            await self.coordinator.async_start_service()
        except SceneGlowApiError as err:
            raise HomeAssistantError(
                translation_domain="sceneglow",
                translation_key="service_control_failed",
            ) from err

    async def async_turn_off(self, **kwargs: object) -> None:
        """Request capture shutdown."""
        try:
            await self.coordinator.async_stop_service()
        except SceneGlowApiError as err:
            raise HomeAssistantError(
                translation_domain="sceneglow",
                translation_key="service_control_failed",
            ) from err


class SceneGlowCaptureProcessingSwitch(SceneGlowEntity, SwitchEntity):
    """Pause or resume processing without releasing capture permission."""

    _attr_translation_key = "capture_processing"

    def __init__(self, runtime: SceneGlowRuntimeData) -> None:
        """Initialize the independently capability-gated processing switch."""
        super().__init__(runtime, "capture_processing")

    @property
    def available(self) -> bool:
        """Allow processing changes only in running or paused states."""
        return (
            super().available
            and self.coordinator.capabilities.capture_pause
            and self.coordinator.data.state.capture_state
            in {CaptureState.RUNNING, CaptureState.PAUSED}
        )

    @property
    def is_on(self) -> bool:
        """Return whether frames are currently being processed."""
        return self.coordinator.data.state.capture_state is CaptureState.RUNNING

    async def async_turn_on(self, **kwargs: object) -> None:
        """Resume frame processing."""
        try:
            await self.coordinator.async_resume_service()
        except SceneGlowApiError as err:
            raise HomeAssistantError(
                translation_domain="sceneglow",
                translation_key="service_control_failed",
            ) from err

    async def async_turn_off(self, **kwargs: object) -> None:
        """Pause frame processing while retaining capture permission."""
        try:
            await self.coordinator.async_pause_service()
        except SceneGlowApiError as err:
            raise HomeAssistantError(
                translation_domain="sceneglow",
                translation_key="service_control_failed",
            ) from err


class SceneGlowFixtureSwitch(SceneGlowEntity, SwitchEntity):
    """Whether one fixture participates in the current SceneGlow capture."""

    _attr_translation_key = "fixture_capture_enabled"

    def __init__(
        self, runtime: SceneGlowRuntimeData, fixture: SceneGlowFixture
    ) -> None:
        """Initialize a stable child-device fixture switch."""
        super().__init__(runtime, f"{fixture.fixture_uuid}_capture_enabled")
        self.fixture_uuid = fixture.fixture_uuid
        self._attr_device_info = fixture_device_info(runtime, fixture)

    @property
    def fixture(self) -> SceneGlowFixture | None:
        """Return this fixture from the latest authoritative collection."""
        collection = self.coordinator.data.fixtures
        if collection is None:
            return None
        return next(
            (
                fixture
                for fixture in collection.fixtures
                if fixture.fixture_uuid == self.fixture_uuid
            ),
            None,
        )

    @property
    def available(self) -> bool:
        """Require both installation and fixture-level availability."""
        fixture = self.fixture
        return super().available and fixture is not None and fixture.available

    @property
    def is_on(self) -> bool | None:
        """Return current capture participation."""
        fixture = self.fixture
        return fixture.enabled if fixture is not None else None

    async def async_turn_on(self, **kwargs: object) -> None:
        """Include this fixture in capture output."""
        await self._async_set_enabled(True)

    async def async_turn_off(self, **kwargs: object) -> None:
        """Stop and black/off this fixture through the SceneGlow app."""
        await self._async_set_enabled(False)

    async def _async_set_enabled(self, enabled: bool) -> None:
        fixture = self.fixture
        if fixture is None:
            raise _control_error("fixture_control_failed")
        if not fixture.available:
            raise _control_error("control_unavailable")
        try:
            await self.coordinator.async_set_fixture_enabled(self.fixture_uuid, enabled)
        except SceneGlowApiError as err:
            raise _translated_control_error(err, "fixture_control_failed") from err


class SceneGlowFixtureBooleanControlSwitch(SceneGlowFixtureControlEntity, SwitchEntity):
    """One advertised boolean fixture setting other than participation."""

    def __init__(
        self,
        runtime: SceneGlowRuntimeData,
        fixture: SceneGlowFixture,
        control: SceneGlowFixtureControl,
    ) -> None:
        super().__init__(runtime, fixture, control)

    @property
    def is_on(self) -> bool | None:
        """Return the latest authoritative boolean value."""
        control = self.control
        return control.value if control and isinstance(control.value, bool) else None

    async def async_turn_on(self, **kwargs: object) -> None:
        """Enable this fixture setting."""
        await self.async_set_control_value(True)

    async def async_turn_off(self, **kwargs: object) -> None:
        """Disable this fixture setting."""
        await self.async_set_control_value(False)


class SceneGlowConfigurationSwitchEntity(SceneGlowEntity, SwitchEntity):
    """One parent-device application configuration control."""

    def __init__(
        self,
        runtime: SceneGlowRuntimeData,
        control: SceneGlowConfigurationControl,
    ) -> None:
        """Initialize a stable configuration switch."""
        super().__init__(runtime, f"config_{control.key}")
        self.key = control.key
        if control.key in CONFIGURATION_TRANSLATION_KEYS:
            self._attr_translation_key = control.key
        else:
            self._attr_name = control.name
        if control.key == "performance_diagnostics":
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def control(self) -> SceneGlowConfigurationControl | None:
        """Return this control from the latest authoritative collection."""
        collection = self.coordinator.data.configuration
        if collection is None:
            return None
        return next(
            (item for item in collection.switches if item.key == self.key), None
        )

    @property
    def available(self) -> bool:
        """Prevent writes to controls unavailable on this app variant."""
        control = self.control
        return super().available and control is not None and control.available

    @property
    def is_on(self) -> bool | None:
        """Return the saved setting, independent of its runtime apply timing."""
        control = self.control
        return control.enabled if control is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, str] | None:
        """Expose when SceneGlow applies the saved setting to capture."""
        control = self.control
        if control is None:
            return None
        return {"apply_behavior": control.apply_behavior.value}

    async def async_turn_on(self, **kwargs: object) -> None:
        """Enable the saved SceneGlow setting."""
        await self._async_set_enabled(True)

    async def async_turn_off(self, **kwargs: object) -> None:
        """Disable the saved SceneGlow setting."""
        await self._async_set_enabled(False)

    async def _async_set_enabled(self, enabled: bool) -> None:
        control = self.control
        if control is None:
            raise _control_error("configuration_control_failed")
        if not control.available:
            raise _control_error("control_unavailable")
        try:
            await self.coordinator.async_set_configuration_enabled(self.key, enabled)
        except SceneGlowApiError as err:
            raise _translated_control_error(
                err, "configuration_control_failed"
            ) from err


class SceneGlowSwitchManager:
    """Add and retire switches as authoritative collections change."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: SceneGlowConfigEntry,
        async_add_entities: AddEntitiesCallback,
    ) -> None:
        self.hass = hass
        self.entry = entry
        self.runtime = entry.runtime_data
        self.async_add_entities = async_add_entities
        self.fixture_entities: dict[str, SceneGlowFixtureSwitch] = {}
        self.fixture_control_entities: dict[
            tuple[str, str], SceneGlowFixtureBooleanControlSwitch
        ] = {}
        self.configuration_entities: dict[str, SceneGlowConfigurationSwitchEntity] = {}
        self.retired_fixture_uuids: set[str] = set()
        snapshot = self.runtime.coordinator.data
        self._last_fixtures = snapshot.fixtures
        self._last_configuration = snapshot.configuration

    def initial_entities(self) -> list[SwitchEntity]:
        """Build entities from the first authoritative coordinator snapshot."""
        return self._new_entities()

    def start(self) -> Callable[[], None]:
        """Listen for future authoritative collection updates."""
        return self.runtime.coordinator.async_add_listener(self._collections_updated)

    def _collections_updated(self) -> None:
        snapshot = self.runtime.coordinator.data
        if (
            snapshot.fixtures is self._last_fixtures
            and snapshot.configuration is self._last_configuration
        ):
            return
        self._last_fixtures = snapshot.fixtures
        self._last_configuration = snapshot.configuration
        new_entities = self._new_entities()
        if new_entities:
            self.async_add_entities(new_entities)

        self._update_fixture_device_names()

        collection = self.runtime.coordinator.data.fixtures
        current = (
            {fixture.fixture_uuid for fixture in collection.fixtures}
            if collection is not None
            else set()
        )
        for fixture_uuid in set(self.fixture_entities) - current:
            entity = self.fixture_entities.pop(fixture_uuid)
            self.retired_fixture_uuids.add(fixture_uuid)
            if entity.hass is not None:
                entity.async_write_ha_state()
            self.hass.async_create_task(
                self._async_remove_fixture(entity),
                f"sceneglow-remove-fixture-{fixture_uuid}",
            )

        current_controls = (
            {
                (fixture.fixture_uuid, control.key)
                for fixture in collection.fixtures
                for control in fixture.controls
                if control.control_type is SceneGlowFixtureControlType.BOOLEAN
                and control.key != "enabled"
            }
            if collection is not None
            else set()
        )
        for identity in set(self.fixture_control_entities) - current_controls:
            entity = self.fixture_control_entities.pop(identity)
            if entity.hass is not None:
                entity.async_write_ha_state()
            self.hass.async_create_task(
                self._async_remove_entity(entity),
                f"sceneglow-remove-switch-control-{identity[0]}-{identity[1]}",
            )

    def _new_entities(self) -> list[SwitchEntity]:
        result: list[SwitchEntity] = []
        snapshot = self.runtime.coordinator.data
        if self.runtime.capabilities.fixtures and snapshot.fixtures is not None:
            for fixture in snapshot.fixtures.fixtures:
                if fixture.fixture_uuid in self.retired_fixture_uuids:
                    continue
                if fixture.fixture_uuid not in self.fixture_entities:
                    entity = SceneGlowFixtureSwitch(self.runtime, fixture)
                    self.fixture_entities[fixture.fixture_uuid] = entity
                    result.append(entity)
                for control in fixture.controls:
                    identity = (fixture.fixture_uuid, control.key)
                    if (
                        control.control_type is not SceneGlowFixtureControlType.BOOLEAN
                        or control.key == "enabled"
                        or identity in self.fixture_control_entities
                    ):
                        continue
                    control_entity = SceneGlowFixtureBooleanControlSwitch(
                        self.runtime, fixture, control
                    )
                    self.fixture_control_entities[identity] = control_entity
                    result.append(control_entity)
        if (
            self.runtime.capabilities.configuration
            and snapshot.configuration is not None
        ):
            for control in snapshot.configuration.switches:
                if control.key in self.configuration_entities:
                    continue
                entity = SceneGlowConfigurationSwitchEntity(self.runtime, control)
                self.configuration_entities[control.key] = entity
                result.append(entity)
        return result

    async def _async_remove_fixture(self, entity: SceneGlowFixtureSwitch) -> None:
        """Remove a confirmed-deleted fixture entity and child device."""
        entity_id = entity.entity_id
        if entity.hass is not None:
            await entity.async_remove(force_remove=True)
        if entity_id is not None:
            registry = er.async_get(self.hass)
            if registry.async_get(entity_id) is not None:
                registry.async_remove(entity_id)
        await asyncio.sleep(0)
        identifier = (
            DOMAIN,
            f"{self.runtime.info.installation_id}:{entity.fixture_uuid}",
        )
        devices = dr.async_get(self.hass)
        device = devices.async_get_device(identifiers={identifier})
        if device is not None:
            devices.async_remove_device(device.id)

    async def _async_remove_entity(self, entity: SceneGlowFixtureControlEntity) -> None:
        """Remove one boolean control no longer advertised by the fixture."""
        entity_id = entity.entity_id
        if entity.hass is not None:
            await entity.async_remove(force_remove=True)
        if entity_id is not None:
            registry = er.async_get(self.hass)
            if registry.async_get(entity_id) is not None:
                registry.async_remove(entity_id)

    def _update_fixture_device_names(self) -> None:
        """Follow authoritative Lighting Use changes in the device registry."""
        collection = self.runtime.coordinator.data.fixtures
        if collection is None:
            return
        devices = dr.async_get(self.hass)
        installation_id = self.runtime.info.installation_id
        for fixture in collection.fixtures:
            device = devices.async_get_device(
                identifiers={(DOMAIN, f"{installation_id}:{fixture.fixture_uuid}")}
            )
            name = fixture_device_name(fixture)
            if device is not None and device.name != name:
                devices.async_update_device(device.id, name=name)


def _control_error(translation_key: str) -> HomeAssistantError:
    return HomeAssistantError(
        translation_domain="sceneglow",
        translation_key=translation_key,
    )


def _translated_control_error(
    error: SceneGlowApiError, fallback: str
) -> HomeAssistantError:
    if isinstance(error, SceneGlowConflictError):
        return _control_error("revision_conflict")
    if isinstance(error, SceneGlowControlUnavailableError):
        return _control_error("control_unavailable")
    if isinstance(error, SceneGlowInvalidConfigurationError):
        return _control_error("invalid_configuration")
    if isinstance(error, SceneGlowControlNotFoundError):
        return _control_error(fallback)
    return _control_error(fallback)
