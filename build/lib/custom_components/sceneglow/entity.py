"""Base entities for SceneGlow."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import SceneGlowRuntimeData
from .const import DOMAIN, MANUFACTURER, MODEL
from .coordinator import SceneGlowCoordinator


class SceneGlowEntity(CoordinatorEntity[SceneGlowCoordinator]):
    """Base class for entities tied to one SceneGlow installation."""

    _attr_has_entity_name = True

    def __init__(self, runtime: SceneGlowRuntimeData, key: str) -> None:
        """Initialize common identity and parent-device metadata."""
        super().__init__(runtime.coordinator)
        info = runtime.info
        self._attr_unique_id = f"{info.installation_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, info.installation_id)},
            name=f"SceneGlow - {info.name}",
            manufacturer=MANUFACTURER,
            model=MODEL,
            sw_version=info.app_version,
        )

    @property
    def available(self) -> bool:
        """Return availability for SceneGlow-dependent entities."""
        return super().available and self.coordinator.connected
