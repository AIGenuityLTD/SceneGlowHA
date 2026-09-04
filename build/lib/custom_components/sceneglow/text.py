"""Capability-driven SceneGlow fixture text controls."""

from __future__ import annotations

from homeassistant.components.text import TextEntity, TextMode
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
    """Set up dynamically advertised text controls."""
    manager = SceneGlowFixturePlatformManager(
        hass,
        entry,
        async_add_entities,
        {SceneGlowFixtureControlType.TEXT},
        SceneGlowFixtureText,
    )
    async_add_entities(manager.initial_entities())
    entry.async_on_unload(manager.start())


class SceneGlowFixtureText(SceneGlowFixtureControlEntity, TextEntity):
    """One server-described fixture text setting."""

    _attr_mode = TextMode.TEXT

    def __init__(
        self,
        runtime: SceneGlowRuntimeData,
        fixture: SceneGlowFixture,
        control: SceneGlowFixtureControl,
    ) -> None:
        super().__init__(runtime, fixture, control)
        if control.maximum_length is None:
            raise ValueError("Text fixture controls require maximum_length")
        self._attr_native_max = control.maximum_length

    @property
    def native_value(self) -> str | None:
        """Return the latest authoritative text value."""
        control = self.control
        return control.value if control and isinstance(control.value, str) else None

    async def async_set_value(self, value: str) -> None:
        """Set the text value."""
        await self.async_set_control_value(value)
