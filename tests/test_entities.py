"""Entity behavior tests for requested-versus-actual state."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from custom_components.sceneglow import SceneGlowRuntimeData
from custom_components.sceneglow.api import SceneGlowApiError
from custom_components.sceneglow.binary_sensor import SceneGlowConnectedBinarySensor
from custom_components.sceneglow.diagnostics import async_get_config_entry_diagnostics
from custom_components.sceneglow.fixture import SceneGlowFixturePlatformManager
from custom_components.sceneglow.models import (
    CaptureState,
    SceneGlowCapabilities,
    SceneGlowConfigurationCollection,
    SceneGlowDiagnostics,
    SceneGlowFixtureCollection,
    SceneGlowFixtureControlType,
    SceneGlowInfo,
    SceneGlowSnapshot,
    SceneGlowState,
)
from custom_components.sceneglow.number import SceneGlowFixtureNumber
from custom_components.sceneglow.select import SceneGlowFixtureSelect
from custom_components.sceneglow.sensor import SENSORS, SceneGlowSensor
from custom_components.sceneglow.switch import (
    SceneGlowCaptureProcessingSwitch,
    SceneGlowCaptureSwitch,
    SceneGlowConfigurationSwitchEntity,
    SceneGlowFixtureBooleanControlSwitch,
    SceneGlowFixtureSwitch,
    SceneGlowSwitchManager,
)
from custom_components.sceneglow.switch import (
    async_setup_entry as async_setup_switches,
)
from custom_components.sceneglow.text import SceneGlowFixtureText
from tests.fake_sceneglow import HA_FIXTURE_ID, WLED_FIXTURE_ID, FakeSceneGlowServer


def _runtime(
    *,
    connected: bool = False,
    amazon_build: bool = False,
    capture_pause: bool = True,
    capture_state: CaptureState = CaptureState.AWAITING_CAPTURE_PERMISSION,
    requested_running: bool = True,
) -> SceneGlowRuntimeData:
    fake = FakeSceneGlowServer(amazon_build=amazon_build)
    coordinator = Mock()
    coordinator.connected = connected
    coordinator.last_update_success = True
    coordinator.data = SceneGlowSnapshot(
        state=SceneGlowState(
            requested_running=requested_running,
            capture_state=capture_state,
        ),
        fixtures=SceneGlowFixtureCollection.from_dict(fake.fixtures_payload()),
        configuration=SceneGlowConfigurationCollection.from_dict(
            fake.configuration_payload()
        ),
    )
    coordinator.async_add_listener.return_value = Mock()
    coordinator.async_start_service = AsyncMock()
    coordinator.async_stop_service = AsyncMock()
    coordinator.async_pause_service = AsyncMock()
    coordinator.async_resume_service = AsyncMock()
    capabilities = SceneGlowCapabilities(
        service_control=True,
        capture_pause=capture_pause,
        fixtures=True,
        configuration=True,
        ha_light_broker=True,
    )
    coordinator.capabilities = capabilities
    return SceneGlowRuntimeData(
        client=Mock(),
        coordinator=coordinator,
        info=SceneGlowInfo.from_dict(fake.info_payload()),
        capabilities=capabilities,
    )


def test_connectivity_sensor_stays_available_when_disconnected() -> None:
    """The deliberate availability exception can report an offline TV."""
    entity = SceneGlowConnectedBinarySensor(_runtime())
    assert entity.available is True
    assert entity.is_on is False


def test_capture_switch_uses_requested_target() -> None:
    """Consent-pending is on by request while actual state remains separate."""
    entity = SceneGlowCaptureSwitch(_runtime())
    assert entity.is_on is True
    assert entity.entity_category is None
    assert entity.device_info["manufacturer"] == "AIGenuity LTD"
    assert entity.extra_state_attributes == {
        "permission": (
            "Starting a stopped capture session requires confirmation "
            "on the SceneGlow device."
        )
    }
    assert entity.coordinator.data.state.capture_state is (
        CaptureState.AWAITING_CAPTURE_PERMISSION
    )


def test_current_capture_remains_on_while_paused() -> None:
    """Pause retains the requested-running target used by Capture session."""
    runtime = _runtime(
        connected=True,
        capture_state=CaptureState.PAUSED,
        requested_running=True,
    )
    assert SceneGlowCaptureSwitch(runtime).is_on is True


def test_capture_state_sensor_reports_paused() -> None:
    """The enum sensor exposes paused independently of the requested target."""
    runtime = _runtime(
        connected=True,
        capture_state=CaptureState.PAUSED,
        requested_running=True,
    )
    description = next(item for item in SENSORS if item.key == "service_state")
    entity = SceneGlowSensor(runtime, description)
    assert entity.native_value == "paused"
    assert "paused" in entity.entity_description.options


def test_performance_sensors_follow_live_diagnostic_availability() -> None:
    """Metric entities are enabled by default and available only with samples."""
    runtime = _runtime(
        connected=True,
        capture_state=CaptureState.RUNNING,
        requested_running=True,
    )
    entities = {
        description.key: SceneGlowSensor(runtime, description)
        for description in SENSORS
        if description.key != "service_state"
    }

    assert all(
        description.entity_registry_enabled_default
        for description in SENSORS
        if description.key != "service_state"
    )
    assert all(not entity.available for entity in entities.values())

    runtime.coordinator.data = replace(
        runtime.coordinator.data,
        state=replace(
            runtime.coordinator.data.state,
            diagnostics=SceneGlowDiagnostics(
                output_fps=29.8,
                processing_ms=4.2,
                capture_resolution="320x180",
            ),
        ),
    )

    assert entities["output_fps"].native_value == 29.8
    assert entities["processing_time"].native_value == 4.2
    assert entities["capture_resolution"].native_value == "320x180"
    assert all(entity.available for entity in entities.values())


@pytest.mark.parametrize(
    ("capture_state", "available", "is_on"),
    [
        (CaptureState.RUNNING, True, True),
        (CaptureState.PAUSED, True, False),
        (CaptureState.STOPPED, False, False),
        (CaptureState.STARTING, False, False),
        (CaptureState.AWAITING_CAPTURE_PERMISSION, False, False),
        (CaptureState.STOPPING, False, False),
        (CaptureState.ERROR, False, False),
    ],
)
def test_capture_processing_state_matrix(
    capture_state: CaptureState, available: bool, is_on: bool
) -> None:
    """Processing is writable only while capture permission is retained."""
    runtime = _runtime(
        connected=True,
        capture_state=capture_state,
        requested_running=capture_state is not CaptureState.STOPPED,
    )
    entity = SceneGlowCaptureProcessingSwitch(runtime)
    assert entity.available is available
    assert entity.is_on is is_on
    assert entity.unique_id == (f"{runtime.info.installation_id}_capture_processing")
    assert entity.device_info["identifiers"] == {
        ("sceneglow", runtime.info.installation_id)
    }


async def test_capture_processing_and_stop_call_only_their_own_operations() -> None:
    """Run, Pause, and Stop remain independent non-retried commands."""
    runtime = _runtime(
        connected=True,
        capture_state=CaptureState.PAUSED,
        requested_running=True,
    )
    processing = SceneGlowCaptureProcessingSwitch(runtime)
    current = SceneGlowCaptureSwitch(runtime)

    await processing.async_turn_on()
    runtime.coordinator.async_resume_service.assert_awaited_once_with()
    runtime.coordinator.async_pause_service.assert_not_awaited()
    runtime.coordinator.async_start_service.assert_not_awaited()
    runtime.coordinator.async_stop_service.assert_not_awaited()

    runtime.coordinator.data = replace(
        runtime.coordinator.data,
        state=SceneGlowState(True, CaptureState.RUNNING),
    )
    await processing.async_turn_off()
    runtime.coordinator.async_pause_service.assert_awaited_once_with()
    runtime.coordinator.async_resume_service.assert_awaited_once_with()

    runtime.coordinator.data = replace(
        runtime.coordinator.data,
        state=SceneGlowState(True, CaptureState.PAUSED),
    )
    await current.async_turn_off()
    runtime.coordinator.async_stop_service.assert_awaited_once_with()
    runtime.coordinator.async_start_service.assert_not_awaited()


async def test_capture_processing_maps_api_failures_to_service_error() -> None:
    """Pause/resume failures use the existing translated service exception."""
    runtime = _runtime(
        connected=True,
        capture_state=CaptureState.RUNNING,
    )
    runtime.coordinator.async_pause_service.side_effect = SceneGlowApiError("failed")
    entity = SceneGlowCaptureProcessingSwitch(runtime)

    with pytest.raises(HomeAssistantError) as error:
        await entity.async_turn_off()
    assert error.value.translation_key == "service_control_failed"


@pytest.mark.parametrize("capture_pause", [True, False])
async def test_capture_processing_entity_is_capability_gated(
    capture_pause: bool,
) -> None:
    """Setup exposes processing only from the required capability flag."""
    runtime = _runtime(connected=True, capture_pause=capture_pause)
    entry = SimpleNamespace(runtime_data=runtime, async_on_unload=Mock())
    add_entities = Mock()

    await async_setup_switches(Mock(), entry, add_entities)

    entities = add_entities.call_args.args[0]
    assert any(isinstance(entity, SceneGlowCaptureSwitch) for entity in entities)
    assert (
        any(isinstance(entity, SceneGlowCaptureProcessingSwitch) for entity in entities)
        is capture_pause
    )


def test_fixture_switch_has_stable_identity_and_child_device_hierarchy() -> None:
    """Fixtures are switches on SceneGlow child devices, never duplicate lights."""
    runtime = _runtime(connected=True)
    fixture = runtime.coordinator.data.fixtures.fixtures[0]
    entity = SceneGlowFixtureSwitch(runtime, fixture)

    assert isinstance(entity, SwitchEntity)
    assert entity.unique_id == (
        f"{runtime.info.installation_id}_{WLED_FIXTURE_ID}_capture_enabled"
    )
    assert entity.device_info["identifiers"] == {
        ("sceneglow", f"{runtime.info.installation_id}:{WLED_FIXTURE_ID}")
    }
    assert entity.device_info["via_device"] == (
        "sceneglow",
        runtime.info.installation_id,
    )
    assert entity.device_info["model"] == "SceneGlow WLED fixture"
    assert entity.device_info["name"] == "TV backlight — ScreenGlow"
    assert entity.icon is None
    assert entity.is_on is True
    assert entity.available is True

    ha_fixture = runtime.coordinator.data.fixtures.fixtures[1]
    ha_entity = SceneGlowFixtureSwitch(runtime, ha_fixture)
    assert ha_entity.unique_id == (
        f"{runtime.info.installation_id}_{HA_FIXTURE_ID}_capture_enabled"
    )
    assert ha_entity.icon is None


def test_typed_fixture_entities_use_stable_ids_and_server_metadata() -> None:
    """Every dynamic domain is driven by the advertised control contract."""
    runtime = _runtime(connected=True)
    fixture = runtime.coordinator.data.fixtures.fixtures[0]
    controls = {control.key: control for control in fixture.controls}
    entities = [
        SceneGlowFixtureBooleanControlSwitch(
            runtime, fixture, controls["send_black_on_stop"]
        ),
        SceneGlowFixtureNumber(runtime, fixture, controls["gamma"]),
        SceneGlowFixtureSelect(runtime, fixture, controls["profile_type"]),
        SceneGlowFixtureText(runtime, fixture, controls["host"]),
    ]

    assert [entity.unique_id for entity in entities] == [
        f"{runtime.info.installation_id}_{WLED_FIXTURE_ID}_{key}"
        for key in ("send_black_on_stop", "gamma", "profile_type", "host")
    ]
    assert entities[0].is_on is True
    assert entities[1].native_value == 1.0
    assert entities[1].native_min_value == 0.1
    assert entities[1].native_max_value == 3.0
    assert entities[1].native_step == 0.01
    assert entities[2].current_option == "screen_glow"
    assert "cabinet_glow" in entities[2].options
    assert entities[3].native_value == "192.0.2.70"
    assert entities[3].native_max == 15
    assert all(entity.icon is None for entity in entities)
    assert all(
        entity.extra_state_attributes
        == {"apply_behavior": "next_capture", "read_only": False}
        for entity in entities
    )


def test_enabled_control_is_not_duplicated_as_dynamic_boolean_switch() -> None:
    """The legacy fixture participant remains the only enabled entity."""
    runtime = _runtime(connected=True)
    entry = SimpleNamespace(runtime_data=runtime)
    manager = SceneGlowSwitchManager(Mock(), entry, Mock())
    entities = manager.initial_entities()
    fixture_entities = [
        entity for entity in entities if getattr(entity, "fixture_uuid", None)
    ]
    assert (
        sum(isinstance(entity, SceneGlowFixtureSwitch) for entity in fixture_entities)
        == 2
    )
    assert not any(
        getattr(entity, "control_key", None) == "enabled" for entity in fixture_entities
    )


async def test_typed_control_writes_and_unavailable_guard() -> None:
    """Entity writes use key/value and unavailable metadata prevents a PATCH."""
    runtime = _runtime(connected=True)
    fixture = runtime.coordinator.data.fixtures.fixtures[0]
    profile = next(
        control for control in fixture.controls if control.key == "profile_type"
    )
    entity = SceneGlowFixtureSelect(runtime, fixture, profile)
    runtime.coordinator.async_set_fixture_control_value = AsyncMock()
    await entity.async_select_option("cabinet_glow")
    runtime.coordinator.async_set_fixture_control_value.assert_awaited_once_with(
        WLED_FIXTURE_ID, "profile_type", "cabinet_glow"
    )

    unavailable = replace(profile, available=False)
    controls = tuple(
        unavailable if control.key == profile.key else control
        for control in fixture.controls
    )
    runtime.coordinator.data = replace(
        runtime.coordinator.data,
        fixtures=replace(
            runtime.coordinator.data.fixtures,
            fixtures=(
                replace(fixture, controls=controls),
                *runtime.coordinator.data.fixtures.fixtures[1:],
            ),
        ),
    )
    assert entity.available is False
    with pytest.raises(HomeAssistantError):
        await entity.async_select_option("screen_glow")
    assert runtime.coordinator.async_set_fixture_control_value.await_count == 1


async def test_fixture_switch_updates_from_patch_cache_immediately() -> None:
    """The switch reflects the coordinator's returned PATCH snapshot without polling."""
    runtime = _runtime(connected=True)
    fixture = runtime.coordinator.data.fixtures.fixtures[0]
    entity = SceneGlowFixtureSwitch(runtime, fixture)

    async def set_enabled(fixture_uuid: str, enabled: bool) -> None:
        assert fixture_uuid == fixture.fixture_uuid
        collection = runtime.coordinator.data.fixtures
        runtime.coordinator.data = replace(
            runtime.coordinator.data,
            fixtures=replace(
                collection,
                revision=collection.revision + 1,
                fixtures=(
                    replace(fixture, enabled=enabled),
                    *collection.fixtures[1:],
                ),
            ),
        )

    runtime.coordinator.async_set_fixture_enabled = set_enabled
    await entity.async_turn_off()
    assert entity.is_on is False


def test_fixture_availability_requires_connection_and_fixture_availability() -> None:
    """Offline installations and unavailable individual outputs are unavailable."""
    offline = _runtime(connected=False)
    fixture = offline.coordinator.data.fixtures.fixtures[0]
    assert SceneGlowFixtureSwitch(offline, fixture).available is False

    runtime = _runtime(connected=True)
    unavailable = replace(
        runtime.coordinator.data.fixtures.fixtures[0], available=False
    )
    runtime.coordinator.data = replace(
        runtime.coordinator.data,
        fixtures=replace(
            runtime.coordinator.data.fixtures,
            fixtures=(
                unavailable,
                *runtime.coordinator.data.fixtures.fixtures[1:],
            ),
        ),
    )
    assert SceneGlowFixtureSwitch(runtime, unavailable).available is False


def test_all_configuration_switches_and_amazon_unavailability() -> None:
    """All four parent controls exist and Amazon's indicator remains read-only."""
    runtime = _runtime(connected=True, amazon_build=True)
    entities = [
        SceneGlowConfigurationSwitchEntity(runtime, control)
        for control in runtime.coordinator.data.configuration.switches
    ]
    assert {entity.key for entity in entities} == {
        "home_assistant_ambience",
        "detect_black_bars",
        "capture_indicator_exclusion",
        "performance_diagnostics",
    }
    indicator = next(
        entity for entity in entities if entity.key == "capture_indicator_exclusion"
    )
    performance = next(
        entity for entity in entities if entity.key == "performance_diagnostics"
    )
    assert indicator.available is False
    assert indicator.extra_state_attributes == {"apply_behavior": "immediate"}
    assert performance.entity_category is EntityCategory.DIAGNOSTIC
    assert all(
        entity.entity_category is None
        for entity in entities
        if entity is not performance
    )


async def test_unavailable_amazon_control_never_issues_patch() -> None:
    """Even direct service calls cannot write an app-variant unavailable control."""
    runtime = _runtime(connected=True, amazon_build=True)
    runtime.coordinator.async_set_configuration_enabled = AsyncMock()
    control = next(
        control
        for control in runtime.coordinator.data.configuration.switches
        if control.key == "capture_indicator_exclusion"
    )
    entity = SceneGlowConfigurationSwitchEntity(runtime, control)
    with pytest.raises(HomeAssistantError):
        await entity.async_turn_on()
    runtime.coordinator.async_set_configuration_enabled.assert_not_awaited()


async def test_configuration_switch_reflects_patch_cache_immediately() -> None:
    """Saved configuration state updates from the PATCH result without a poll."""
    runtime = _runtime(connected=True)
    control = runtime.coordinator.data.configuration.switches[1]
    entity = SceneGlowConfigurationSwitchEntity(runtime, control)

    async def set_enabled(key: str, enabled: bool) -> None:
        assert key == control.key
        collection = runtime.coordinator.data.configuration
        runtime.coordinator.data = replace(
            runtime.coordinator.data,
            configuration=replace(
                collection,
                revision=collection.revision + 1,
                switches=(
                    collection.switches[0],
                    replace(control, enabled=enabled),
                    *collection.switches[2:],
                ),
            ),
        )

    runtime.coordinator.async_set_configuration_enabled = set_enabled
    await entity.async_turn_off()
    assert entity.is_on is False


async def test_switch_manager_adds_and_retires_dynamic_fixture_uuids(
    hass: HomeAssistant,
) -> None:
    """Authoritative additions deduplicate and confirmed deletions retire identity."""
    runtime = _runtime(connected=True)
    entry = SimpleNamespace(runtime_data=runtime)
    add_entities = Mock()
    manager = SceneGlowSwitchManager(hass, entry, add_entities)
    assert len(manager.initial_entities()) == 8

    new_fixture = replace(
        runtime.coordinator.data.fixtures.fixtures[0],
        fixture_uuid="692c6ed8-25d1-4209-833d-ce279755a80d",
        name="New strip",
    )
    runtime.coordinator.data = replace(
        runtime.coordinator.data,
        fixtures=replace(
            runtime.coordinator.data.fixtures,
            fixtures=(*runtime.coordinator.data.fixtures.fixtures, new_fixture),
        ),
    )
    manager._collections_updated()
    assert len(add_entities.call_args.args[0]) == 3
    manager._collections_updated()
    assert add_entities.call_count == 1

    runtime.coordinator.data = replace(
        runtime.coordinator.data,
        fixtures=replace(
            runtime.coordinator.data.fixtures,
            fixtures=tuple(
                fixture
                for fixture in runtime.coordinator.data.fixtures.fixtures
                if fixture.fixture_uuid != new_fixture.fixture_uuid
            ),
        ),
    )
    manager._collections_updated()
    await hass.async_block_till_done()
    assert new_fixture.fixture_uuid in manager.retired_fixture_uuids


async def test_typed_platform_retires_deleted_fixture_identity(
    hass: HomeAssistant,
) -> None:
    """Typed control managers do not reuse identities after fixture deletion."""
    runtime = _runtime(connected=True)
    entry = SimpleNamespace(runtime_data=runtime)
    add_entities = Mock()
    manager = SceneGlowFixturePlatformManager(
        hass,
        entry,
        add_entities,
        {SceneGlowFixtureControlType.SELECT},
        SceneGlowFixtureSelect,
    )
    assert len(manager.initial_entities()) == 14
    removed = runtime.coordinator.data.fixtures.fixtures[0]
    runtime.coordinator.data = replace(
        runtime.coordinator.data,
        fixtures=replace(
            runtime.coordinator.data.fixtures,
            fixtures=runtime.coordinator.data.fixtures.fixtures[1:],
        ),
    )
    manager._controls_updated()
    await hass.async_block_till_done()
    assert removed.fixture_uuid in manager.retired_fixture_uuids

    runtime.coordinator.data = replace(
        runtime.coordinator.data,
        fixtures=replace(
            runtime.coordinator.data.fixtures,
            fixtures=(removed, *runtime.coordinator.data.fixtures.fixtures),
        ),
    )
    manager._controls_updated()
    assert add_entities.call_count == 0


async def test_diagnostics_report_control_counts_without_fixture_details(
    hass: HomeAssistant,
) -> None:
    """Control diagnostics expose useful counts and revisions, not target metadata."""
    runtime = _runtime(connected=True)
    runtime.coordinator.events_received = 3
    runtime.coordinator.event_reconnects = 1
    runtime.coordinator.last_error_category = None
    entry = SimpleNamespace(runtime_data=runtime)

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    assert diagnostics["capabilities"]["capture_pause"] is True
    assert diagnostics["capabilities"]["configuration"] is True
    assert diagnostics["state"]["performance"] == {
        "output_fps": None,
        "processing_ms": None,
        "capture_resolution": None,
    }
    assert diagnostics["controls"] == {
        "fixture_count": 2,
        "available_fixture_count": 2,
        "fixture_revision": 7,
        "configuration_revision": 7,
        "configuration_switch_count": 4,
    }
    encoded = repr(diagnostics)
    assert "TV backlight" not in encoded
    assert "Living room lamp" not in encoded
    assert "entity_id" not in encoded
    assert "broker_reference" not in encoded.lower()
