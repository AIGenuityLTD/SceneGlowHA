"""Privacy-preserving diagnostics for SceneGlow."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from . import SceneGlowConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: SceneGlowConfigEntry,
) -> dict[str, Any]:
    """Return useful state without credentials, host data, or screen content."""
    runtime = entry.runtime_data
    coordinator = runtime.coordinator
    snapshot = coordinator.data
    state = snapshot.state
    fixtures = snapshot.fixtures
    configuration = snapshot.configuration
    return {
        "entry": {
            "installation_id": runtime.info.installation_id,
            "app_version": runtime.info.app_version,
            "platform": runtime.info.platform,
            "protocol_version": runtime.info.protocol_version,
        },
        "connection": {
            "connected": coordinator.connected,
            "events_received": coordinator.events_received,
            "event_reconnects": coordinator.event_reconnects,
            "last_error_category": coordinator.last_error_category,
            "last_update_success": coordinator.last_update_success,
        },
        "capabilities": {
            "service_control": runtime.capabilities.service_control,
            "capture_pause": runtime.capabilities.capture_pause,
            "fixtures": runtime.capabilities.fixtures,
            "configuration": runtime.capabilities.configuration,
            "ha_light_broker": runtime.capabilities.ha_light_broker,
        },
        "state": {
            "requested_running": state.requested_running,
            "capture_state": state.capture_state,
            "error_category": state.error_category,
            "performance": {
                "output_fps": state.diagnostics.output_fps,
                "processing_ms": state.diagnostics.processing_ms,
                "capture_resolution": state.diagnostics.capture_resolution,
            },
        },
        "controls": {
            "fixture_count": len(fixtures.fixtures) if fixtures else 0,
            "available_fixture_count": (
                sum(fixture.available for fixture in fixtures.fixtures)
                if fixtures
                else 0
            ),
            "fixture_revision": fixtures.revision if fixtures else None,
            "configuration_revision": (
                configuration.revision if configuration else None
            ),
            "configuration_switch_count": (
                len(configuration.switches) if configuration else 0
            ),
        },
    }
