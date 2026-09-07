"""Shared fixture-control entities and dynamic platform management."""

from __future__ import annotations

from collections.abc import Callable

from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SceneGlowConfigEntry, SceneGlowRuntimeData
from .api import (
    SceneGlowApiError,
    SceneGlowConflictError,
    SceneGlowControlNotFoundError,
    SceneGlowControlUnavailableError,
    SceneGlowInvalidConfigurationError,
)
from .const import DOMAIN, MANUFACTURER
from .entity import SceneGlowEntity
from .models import (
    SceneGlowFixture,
    SceneGlowFixtureControl,
    SceneGlowFixtureControlType,
    SceneGlowFixtureType,
)

LIGHTING_USE_NAMES = {
    "screen_glow": "ScreenGlow",
    "cabinet_glow": "CabinetGlow",
    "skirting_glow": "SkirtingGlow",
    "lamp_glow": "LampGlow",
    "spot_glow": "SpotGlow",
}


def fixture_device_name(fixture: SceneGlowFixture) -> str:
    """Append authoritative WLED Lighting Use when it is advertised."""
    profile = next(
        (control for control in fixture.controls if control.key == "profile_type"),
        None,
    )
    if profile is None or not isinstance(profile.value, str):
        return fixture.name
    lighting_use = LIGHTING_USE_NAMES.get(
        profile.value,
        profile.value.replace("_", " ").title(),
    )
    return f"{fixture.name} — {lighting_use}"


def fixture_device_info(
    runtime: SceneGlowRuntimeData, fixture: SceneGlowFixture
) -> DeviceInfo:
    """Build consistent child-device metadata for one fixture."""
    installation_id = runtime.info.installation_id
    model = (
        "SceneGlow WLED fixture"
        if fixture.fixture_type is SceneGlowFixtureType.WLED
        else "SceneGlow Home Assistant fixture"
    )
    return DeviceInfo(
        identifiers={(DOMAIN, f"{installation_id}:{fixture.fixture_uuid}")},
        name=fixture_device_name(fixture),
        manufacturer=MANUFACTURER,
        model=model,
        via_device=(DOMAIN, installation_id),
    )


class SceneGlowFixtureControlEntity(SceneGlowEntity):
    """Base for one server-described fixture configuration entity."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        runtime: SceneGlowRuntimeData,
        fixture: SceneGlowFixture,
        control: SceneGlowFixtureControl,
    ) -> None:
        super().__init__(runtime, f"{fixture.fixture_uuid}_{control.key}")
        self.fixture_uuid = fixture.fixture_uuid
        self.control_key = control.key
        self._attr_name = control.name
        self._attr_device_info = fixture_device_info(runtime, fixture)

    @property
    def fixture(self) -> SceneGlowFixture | None:
        """Return the fixture from the latest authoritative snapshot."""
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
    def control(self) -> SceneGlowFixtureControl | None:
        """Return the control from the latest authoritative fixture."""
        fixture = self.fixture
        if fixture is None:
            return None
        return next(
            (
                control
                for control in fixture.controls
                if control.key == self.control_key
            ),
            None,
        )

    @property
    def available(self) -> bool:
        """Require server availability and block read-only writes."""
        control = self.control
        return (
            super().available
            and control is not None
            and control.available
            and not control.read_only
        )

    @property
    def extra_state_attributes(self) -> dict[str, str | bool] | None:
        """Expose authoritative application timing and mutability metadata."""
        control = self.control
        if control is None:
            return None
        return {
            "apply_behavior": control.apply_behavior.value,
            "read_only": control.read_only,
        }

    async def async_set_control_value(self, value: bool | str | int | float) -> None:
        """Write one value using the latest shared settings revision."""
        control = self.control
        if control is None:
            raise fixture_control_error("fixture_control_failed")
        if control.read_only or not control.available:
            raise fixture_control_error("control_unavailable")
        try:
            await self.coordinator.async_set_fixture_control_value(
                self.fixture_uuid, self.control_key, value
            )
        except SceneGlowApiError as err:
            raise translated_fixture_control_error(err) from err


class SceneGlowFixturePlatformManager:
    """Dynamically add/remove one platform's fixture control entities."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: SceneGlowConfigEntry,
        async_add_entities: AddEntitiesCallback,
        control_types: set[SceneGlowFixtureControlType],
        factory: Callable[
            [SceneGlowRuntimeData, SceneGlowFixture, SceneGlowFixtureControl],
            SceneGlowFixtureControlEntity,
        ],
    ) -> None:
        self.hass = hass
        self.entry = entry
        self.runtime = entry.runtime_data
        self.async_add_entities = async_add_entities
        self.control_types = control_types
        self.factory = factory
        self.entities: dict[tuple[str, str], SceneGlowFixtureControlEntity] = {}
        self.retired_fixture_uuids: set[str] = set()
        self._last_collection = self.runtime.coordinator.data.fixtures

    def initial_entities(self) -> list[SceneGlowFixtureControlEntity]:
        """Build this platform's initial authoritative entity set."""
        return self._new_entities()

    def start(self) -> Callable[[], None]:
        """Register for dynamic fixture/control changes."""
        return self.runtime.coordinator.async_add_listener(self._controls_updated)

    def _advertised_controls(
        self,
    ) -> dict[tuple[str, str], tuple[SceneGlowFixture, SceneGlowFixtureControl]]:
        collection = self.runtime.coordinator.data.fixtures
        if collection is None:
            return {}
        return {
            (fixture.fixture_uuid, control.key): (fixture, control)
            for fixture in collection.fixtures
            for control in fixture.controls
            if fixture.fixture_uuid not in self.retired_fixture_uuids
            and control.control_type in self.control_types
            and control.key != "enabled"
        }

    def _new_entities(self) -> list[SceneGlowFixtureControlEntity]:
        result: list[SceneGlowFixtureControlEntity] = []
        for identity, (fixture, control) in self._advertised_controls().items():
            if identity in self.entities:
                continue
            entity = self.factory(self.runtime, fixture, control)
            self.entities[identity] = entity
            result.append(entity)
        return result

    def _controls_updated(self) -> None:
        collection = self.runtime.coordinator.data.fixtures
        if collection is self._last_collection:
            return
        self._last_collection = collection
        current_fixture_uuids = (
            {fixture.fixture_uuid for fixture in collection.fixtures}
            if collection is not None
            else set()
        )
        self.retired_fixture_uuids.update(
            fixture_uuid
            for fixture_uuid, _key in self.entities
            if fixture_uuid not in current_fixture_uuids
        )
        new_entities = self._new_entities()
        if new_entities:
            self.async_add_entities(new_entities)
        current = set(self._advertised_controls())
        for identity in set(self.entities) - current:
            entity = self.entities.pop(identity)
            if entity.hass is not None:
                entity.async_write_ha_state()
            self.hass.async_create_task(
                self._async_remove_entity(entity),
                f"sceneglow-remove-control-{identity[0]}-{identity[1]}",
            )

    async def _async_remove_entity(self, entity: Entity) -> None:
        """Remove one control no longer present in an authoritative collection."""
        entity_id = entity.entity_id
        if entity.hass is not None:
            await entity.async_remove(force_remove=True)
        if entity_id is not None:
            registry = er.async_get(self.hass)
            if registry.async_get(entity_id) is not None:
                registry.async_remove(entity_id)


def fixture_control_error(translation_key: str) -> HomeAssistantError:
    """Create a translated fixture-control service error."""
    return HomeAssistantError(
        translation_domain=DOMAIN,
        translation_key=translation_key,
    )


def translated_fixture_control_error(error: SceneGlowApiError) -> HomeAssistantError:
    """Map protocol control errors to actionable Home Assistant errors."""
    if isinstance(error, SceneGlowConflictError):
        return fixture_control_error("revision_conflict")
    if isinstance(error, SceneGlowControlUnavailableError):
        return fixture_control_error("control_unavailable")
    if isinstance(error, SceneGlowInvalidConfigurationError):
        return fixture_control_error("invalid_configuration")
    if isinstance(error, SceneGlowControlNotFoundError):
        return fixture_control_error("fixture_control_failed")
    return fixture_control_error("fixture_control_failed")
