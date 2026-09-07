"""Binary sensors for SceneGlow."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SceneGlowConfigEntry, SceneGlowRuntimeData
from .entity import SceneGlowEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SceneGlowConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up SceneGlow binary sensors."""
    async_add_entities([SceneGlowConnectedBinarySensor(entry.runtime_data)])


class SceneGlowConnectedBinarySensor(SceneGlowEntity, BinarySensorEntity):
    """Connectivity sensor that deliberately remains available offline."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_translation_key = "connected"

    def __init__(self, runtime: SceneGlowRuntimeData) -> None:
        """Initialize the connectivity sensor."""
        super().__init__(runtime, "connected")

    @property
    def available(self) -> bool:
        """Remain available so disconnection can be represented as off."""
        return True

    @property
    def is_on(self) -> bool:
        """Return whether authenticated SceneGlow communication is current."""
        return self.coordinator.connected
