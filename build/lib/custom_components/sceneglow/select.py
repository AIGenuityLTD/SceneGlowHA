"""Capability-driven SceneGlow fixture selects."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
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
    """Set up dynamically advertised select controls."""
    manager = SceneGlowFixturePlatformManager(
        hass,
        entry,
        async_add_entities,
        {SceneGlowFixtureControlType.SELECT},
        SceneGlowFixtureSelect,
    )
    async_add_entities(manager.initial_entities())
    entry.async_on_unload(manager.start())


class SceneGlowFixtureSelect(SceneGlowFixtureControlEntity, SelectEntity):
    """One server-described fixture option."""

    def __init__(
        self,
        runtime: SceneGlowRuntimeData,
        fixture: SceneGlowFixture,
        control: SceneGlowFixtureControl,
    ) -> None:
        super().__init__(runtime, fixture, control)
        self._attr_options = list(control.options)

    @property
    def current_option(self) -> str | None:
        """Return the latest authoritative selected option."""
        control = self.control
        return control.value if control and isinstance(control.value, str) else None

    async def async_select_option(self, option: str) -> None:
        """Select one advertised option."""
        await self.async_set_control_value(option)
