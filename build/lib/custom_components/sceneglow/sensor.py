"""Sensors for SceneGlow."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import SceneGlowConfigEntry, SceneGlowRuntimeData
from .entity import SceneGlowEntity
from .models import CaptureState, SceneGlowState


@dataclass(frozen=True, kw_only=True)
class SceneGlowSensorDescription(SensorEntityDescription):
    """Describe a SceneGlow sensor."""

    value_fn: Callable[[SceneGlowState], Any]


SENSORS: tuple[SceneGlowSensorDescription, ...] = (
    SceneGlowSensorDescription(
        key="service_state",
        translation_key="service_state",
        device_class=SensorDeviceClass.ENUM,
        options=[state.value for state in CaptureState],
        value_fn=lambda state: state.capture_state.value,
    ),
    SceneGlowSensorDescription(
        key="output_fps",
        translation_key="output_fps",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="fps",
        value_fn=lambda state: state.diagnostics.output_fps,
    ),
    SceneGlowSensorDescription(
        key="processing_time",
        translation_key="processing_time",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTime.MILLISECONDS,
        value_fn=lambda state: state.diagnostics.processing_ms,
    ),
    SceneGlowSensorDescription(
        key="capture_resolution",
        translation_key="capture_resolution",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda state: state.diagnostics.capture_resolution,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SceneGlowConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up SceneGlow sensors."""
    async_add_entities(
        SceneGlowSensor(entry.runtime_data, description) for description in SENSORS
    )


class SceneGlowSensor(SceneGlowEntity, SensorEntity):
    """A capability-independent SceneGlow state sensor."""

    entity_description: SceneGlowSensorDescription

    def __init__(
        self,
        runtime: SceneGlowRuntimeData,
        description: SceneGlowSensorDescription,
    ) -> None:
        """Initialize a described sensor."""
        super().__init__(runtime, description.key)
        self.entity_description = description

    async def async_added_to_hass(self) -> None:
        """Subscribe performance sensors to diagnostics-only updates."""
        await super().async_added_to_hass()
        if self.entity_description.key != "service_state":
            self.async_on_remove(
                self.coordinator.async_add_diagnostics_listener(
                    self.async_write_ha_state
                )
            )

    @property
    def available(self) -> bool:
        """Require a live value for optional performance measurements."""
        return super().available and (
            self.entity_description.key == "service_state"
            or self.native_value is not None
        )

    @property
    def native_value(self) -> Any:
        """Return the value from the latest authoritative snapshot."""
        return self.entity_description.value_fn(self.coordinator.data.state)
