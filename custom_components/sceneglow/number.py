"""Capability-driven numeric SceneGlow fixture controls."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SceneGlowConfigEntry, SceneGlowRuntimeData
from .fixture import SceneGlowFixtureControlEntity, SceneGlowFixturePlatformManager
from .models import (
    SceneGlowFixture,
    SceneGlowFixtureControl,
    SceneGlowFixtureControlType,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SceneGlowConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up dynamically advertised numeric controls."""
    manager = SceneGlowFixturePlatformManager(
        hass,
        entry,
        async_add_entities,
        {
            SceneGlowFixtureControlType.INTEGER,
            SceneGlowFixtureControlType.NUMBER,
        },
        SceneGlowFixtureNumber,
    )
    async_add_entities(manager.initial_entities())
    entry.async_on_unload(manager.start())


class SceneGlowFixtureNumber(SceneGlowFixtureControlEntity, NumberEntity):
    """One integer or decimal fixture setting."""

    _attr_mode = NumberMode.BOX

    def __init__(
        self,
        runtime: SceneGlowRuntimeData,
        fixture: SceneGlowFixture,
        control: SceneGlowFixtureControl,
    ) -> None:
        super().__init__(runtime, fixture, control)
        if control.minimum is None or control.maximum is None or control.step is None:
            raise ValueError("Numeric fixture controls require range metadata")
        self._attr_native_min_value = float(control.minimum)
        self._attr_native_max_value = float(control.maximum)
        self._attr_native_step = float(control.step)
        self.integer_control = (
            control.control_type is SceneGlowFixtureControlType.INTEGER
        )

    @property
    def native_value(self) -> float | int | None:
        """Return the latest authoritative numeric value."""
        control = self.control
        if control is None or isinstance(control.value, bool | str):
            return None
        return control.value

    async def async_set_native_value(self, value: float) -> None:
        """Set the numeric value with server-side range/coupling validation."""
        await self.async_set_control_value(
            int(value) if self.integer_control else value
        )
