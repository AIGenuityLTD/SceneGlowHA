"""Coordinator snapshot, revision, and event reconciliation tests."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.core import HomeAssistant

from custom_components.sceneglow.api import SceneGlowConflictError
from custom_components.sceneglow.coordinator import SceneGlowCoordinator
from custom_components.sceneglow.models import (
    CaptureState,
    SceneGlowCapabilities,
    SceneGlowConfigurationCollection,
    SceneGlowDiagnostics,
    SceneGlowEvent,
    SceneGlowFixtureCollection,
    SceneGlowSnapshot,
    SceneGlowState,
)
from tests.fake_sceneglow import STREAM_EPOCH, WLED_FIXTURE_ID, FakeSceneGlowServer


def _client(fake: FakeSceneGlowServer) -> Mock:
    client = Mock()
    client.async_get_state = AsyncMock(
        return_value=SceneGlowState(False, CaptureState.STOPPED)
    )
    client.async_get_fixtures = AsyncMock(
        return_value=SceneGlowFixtureCollection.from_dict(fake.fixtures_payload())
    )
    client.async_get_configuration = AsyncMock(
        return_value=SceneGlowConfigurationCollection.from_dict(
            fake.configuration_payload()
        )
    )
    client.async_pause_service = AsyncMock(
        return_value=SceneGlowState(True, CaptureState.PAUSED)
    )
    client.async_resume_service = AsyncMock(
        return_value=SceneGlowState(True, CaptureState.RUNNING)
    )
    return client


def _coordinator(hass: HomeAssistant, client: Mock) -> SceneGlowCoordinator:
    entry = SimpleNamespace(
        unique_id=FakeSceneGlowServer().installation_id,
        entry_id="controls-test",
        async_start_reauth=Mock(),
        async_on_unload=Mock(),
    )
    return SceneGlowCoordinator(
        hass,
        entry,
        client,
        SceneGlowCapabilities(
            service_control=True,
            capture_pause=True,
            fixtures=True,
            configuration=True,
            ha_light_broker=True,
        ),
    )


async def test_initial_coordinator_sync_fetches_all_supported_controls(
    hass: HomeAssistant,
) -> None:
    """The initial snapshot is complete rather than state-only."""
    fake = FakeSceneGlowServer()
    client = _client(fake)
    coordinator = _coordinator(hass, client)

    snapshot = await coordinator._async_update_data()

    assert len(snapshot.fixtures.fixtures) == 2
    assert len(snapshot.configuration.switches) == 4
    client.async_get_state.assert_awaited_once()
    client.async_get_fixtures.assert_awaited_once()
    client.async_get_configuration.assert_awaited_once()


async def test_periodic_reconcile_requests_a_complete_refresh(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The independent reconciliation timer still drives full coordinator sync."""
    coordinator = _coordinator(hass, _client(FakeSceneGlowServer()))
    coordinator.async_refresh = AsyncMock(side_effect=asyncio.CancelledError)

    async def no_delay(_seconds: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", no_delay)
    with pytest.raises(asyncio.CancelledError):
        await coordinator._async_reconcile_loop()
    coordinator.async_refresh.assert_awaited_once()


async def test_pause_resume_cache_immediate_response_snapshots(
    hass: HomeAssistant,
) -> None:
    """Commands install each 202 response without retrying or awaiting an event."""
    client = _client(FakeSceneGlowServer())
    coordinator = _coordinator(hass, client)
    coordinator.data = SceneGlowSnapshot(
        state=SceneGlowState(True, CaptureState.RUNNING)
    )

    await coordinator.async_pause_service()
    assert coordinator.data.state.capture_state is CaptureState.PAUSED
    client.async_pause_service.assert_awaited_once_with()

    await coordinator.async_resume_service()
    assert coordinator.data.state.capture_state is CaptureState.RUNNING
    client.async_resume_service.assert_awaited_once_with()


async def test_paused_service_event_updates_snapshot_without_refresh(
    hass: HomeAssistant,
) -> None:
    """An ordered paused event remains paused and preserves requested-running."""
    coordinator = _coordinator(hass, _client(FakeSceneGlowServer()))
    coordinator.data = SceneGlowSnapshot(
        state=SceneGlowState(True, CaptureState.RUNNING)
    )
    coordinator._stream_epoch = STREAM_EPOCH
    coordinator._sequence = 3
    coordinator.async_refresh = AsyncMock()

    await coordinator._async_handle_event(
        SceneGlowEvent.from_dict(
            {
                "type": "service_state_changed",
                "api_version": 1,
                "stream_epoch": STREAM_EPOCH,
                "sequence": 4,
                "state": {
                    "requested_running": True,
                    "capture_state": "paused",
                },
            }
        )
    )

    assert coordinator.data.state == SceneGlowState(True, CaptureState.PAUSED)
    coordinator.async_refresh.assert_not_awaited()


async def test_live_diagnostics_event_updates_cached_performance_samples(
    hass: HomeAssistant,
) -> None:
    """Ordered service events publish app performance samples without polling."""
    coordinator = _coordinator(hass, _client(FakeSceneGlowServer()))
    coordinator.data = SceneGlowSnapshot(
        state=SceneGlowState(True, CaptureState.RUNNING)
    )
    coordinator._stream_epoch = STREAM_EPOCH
    coordinator._sequence = 3
    coordinator.async_update_listeners = Mock()
    diagnostics_listener = Mock()
    remove_listener = coordinator.async_add_diagnostics_listener(diagnostics_listener)

    await coordinator._async_handle_event(
        SceneGlowEvent.from_dict(
            {
                "type": "service_state_changed",
                "api_version": 1,
                "stream_epoch": STREAM_EPOCH,
                "sequence": 4,
                "state": {
                    "requested_running": True,
                    "capture_state": "running",
                    "diagnostics": {
                        "output_fps": 29.8,
                        "processing_ms": 4.2,
                        "capture_resolution": "320x180",
                    },
                },
            }
        )
    )

    assert coordinator.data.state.diagnostics == SceneGlowDiagnostics(
        output_fps=29.8,
        processing_ms=4.2,
        capture_resolution="320x180",
    )
    diagnostics_listener.assert_called_once_with()
    coordinator.async_update_listeners.assert_not_called()

    remove_listener()
    assert not coordinator._diagnostics_listeners


async def test_wildcard_control_event_refreshes_both_collections(
    hass: HomeAssistant,
) -> None:
    """The app's wildcard settings event reconciles fixtures and configuration."""
    fake = FakeSceneGlowServer()
    client = _client(fake)
    coordinator = _coordinator(hass, client)
    coordinator.data = await coordinator._async_update_data()
    client.reset_mock()
    fake.revision = 8
    client.async_get_fixtures.return_value = SceneGlowFixtureCollection.from_dict(
        fake.fixtures_payload()
    )
    client.async_get_configuration.return_value = (
        SceneGlowConfigurationCollection.from_dict(fake.configuration_payload())
    )
    coordinator._stream_epoch = STREAM_EPOCH
    coordinator._sequence = 3

    await coordinator._async_handle_event(
        SceneGlowEvent.from_dict(
            {
                "type": "configuration_changed",
                "api_version": 1,
                "stream_epoch": STREAM_EPOCH,
                "sequence": 4,
                "key": "*",
                "revision": 8,
            }
        )
    )

    client.async_get_fixtures.assert_awaited_once()
    client.async_get_configuration.assert_awaited_once()
    assert coordinator.data.fixtures.revision == 8
    assert coordinator.data.configuration.revision == 8


@pytest.mark.parametrize(
    ("epoch", "sequence"),
    [(STREAM_EPOCH, 5), ("93d637c7-4586-4225-b060-fd17cead4b5f", 4)],
)
async def test_sequence_gap_and_epoch_change_force_full_refresh(
    hass: HomeAssistant, epoch: str, sequence: int
) -> None:
    """Unordered streams are repaired using complete state/control reconciliation."""
    coordinator = _coordinator(hass, _client(FakeSceneGlowServer()))
    coordinator.data = SceneGlowSnapshot(
        state=SceneGlowState(False, CaptureState.STOPPED)
    )
    coordinator._stream_epoch = STREAM_EPOCH
    coordinator._sequence = 3
    coordinator.async_refresh = AsyncMock()
    await coordinator._async_handle_event(
        SceneGlowEvent.from_dict(
            {
                "type": "configuration_changed",
                "api_version": 1,
                "stream_epoch": epoch,
                "sequence": sequence,
                "key": "*",
                "revision": 8,
            }
        )
    )
    coordinator.async_refresh.assert_awaited_once()


async def test_subscribed_reconnect_forces_complete_refresh(
    hass: HomeAssistant,
) -> None:
    """Every new socket subscription reconciles controls as well as event state."""
    coordinator = _coordinator(hass, _client(FakeSceneGlowServer()))
    coordinator.data = SceneGlowSnapshot(
        state=SceneGlowState(False, CaptureState.STOPPED)
    )
    coordinator.async_refresh = AsyncMock()
    await coordinator._async_handle_event(
        SceneGlowEvent.from_dict(
            {
                "type": "subscribed",
                "api_version": 1,
                "stream_epoch": STREAM_EPOCH,
                "sequence": 10,
                "state": {
                    "requested_running": True,
                    "capture_state": "running",
                },
            }
        )
    )
    assert coordinator.data.state.capture_state is CaptureState.RUNNING
    coordinator.async_refresh.assert_awaited_once()


async def test_fixture_write_retries_once_after_shared_revision_conflict(
    hass: HomeAssistant,
) -> None:
    """An explicit boolean write safely retries from freshly reconciled revision."""
    fake = FakeSceneGlowServer()
    client = _client(fake)
    coordinator = _coordinator(hass, client)
    coordinator.data = await coordinator._async_update_data()
    fresh_fixtures = replace(coordinator.data.fixtures, revision=8)
    fresh_configuration = replace(coordinator.data.configuration, revision=8)
    client.async_get_fixtures.return_value = fresh_fixtures
    client.async_get_configuration.return_value = fresh_configuration
    updated = replace(
        fresh_fixtures,
        revision=9,
        fixtures=(
            replace(fresh_fixtures.fixtures[0], enabled=False),
            *fresh_fixtures.fixtures[1:],
        ),
    )
    client.async_set_fixture_enabled = AsyncMock(
        side_effect=[SceneGlowConflictError("stale", current_revision=8), updated]
    )

    await coordinator.async_set_fixture_enabled(WLED_FIXTURE_ID, False)

    assert [
        call.args[1] for call in client.async_set_fixture_enabled.await_args_list
    ] == [
        7,
        8,
    ]
    assert coordinator.data.fixtures.revision == 9
    assert coordinator.data.configuration.revision == 9
    assert coordinator.data.fixtures.fixtures[0].enabled is False


async def test_configuration_write_retries_once_after_shared_revision_conflict(
    hass: HomeAssistant,
) -> None:
    """Configuration writes retry from the authoritative aggregate revision."""
    fake = FakeSceneGlowServer()
    client = _client(fake)
    coordinator = _coordinator(hass, client)
    coordinator.data = await coordinator._async_update_data()
    fresh_fixtures = replace(coordinator.data.fixtures, revision=8)
    fresh_configuration = replace(coordinator.data.configuration, revision=8)
    enabled_configuration = replace(
        fresh_configuration,
        revision=9,
        switches=tuple(
            replace(control, enabled=True)
            if control.key == "performance_diagnostics"
            else control
            for control in fresh_configuration.switches
        ),
    )
    client.async_get_fixtures.return_value = fresh_fixtures
    client.async_get_configuration.return_value = fresh_configuration
    client.async_set_configuration_enabled = AsyncMock(
        side_effect=[
            SceneGlowConflictError("stale", current_revision=8),
            enabled_configuration,
        ]
    )

    await coordinator.async_set_configuration_enabled("performance_diagnostics", True)

    assert [
        call.args[1] for call in client.async_set_configuration_enabled.await_args_list
    ] == [7, 8]
    assert coordinator.data.configuration.revision == 9
    assert (
        next(
            control
            for control in coordinator.data.configuration.switches
            if control.key == "performance_diagnostics"
        ).enabled
        is True
    )


async def test_configuration_conflict_does_not_retry_an_already_applied_state(
    hass: HomeAssistant,
) -> None:
    """An event-winning write race does not issue a redundant second PATCH."""
    fake = FakeSceneGlowServer()
    client = _client(fake)
    coordinator = _coordinator(hass, client)
    coordinator.data = await coordinator._async_update_data()
    fresh_fixtures = replace(coordinator.data.fixtures, revision=8)
    fresh_configuration = replace(
        coordinator.data.configuration,
        revision=8,
        switches=tuple(
            replace(control, enabled=True)
            if control.key == "performance_diagnostics"
            else control
            for control in coordinator.data.configuration.switches
        ),
    )
    client.async_get_fixtures.return_value = fresh_fixtures
    client.async_get_configuration.return_value = fresh_configuration
    client.async_set_configuration_enabled = AsyncMock(
        side_effect=SceneGlowConflictError("stale", current_revision=8)
    )

    await coordinator.async_set_configuration_enabled("performance_diagnostics", True)

    client.async_set_configuration_enabled.assert_awaited_once_with(
        "performance_diagnostics", 7, True
    )
    assert coordinator.data.configuration == fresh_configuration


def test_stale_configuration_response_cannot_overwrite_a_newer_event_snapshot(
    hass: HomeAssistant,
) -> None:
    """A delayed PATCH response never rolls the shared settings revision back."""
    fake = FakeSceneGlowServer()
    coordinator = _coordinator(hass, _client(fake))
    fixtures = replace(
        SceneGlowFixtureCollection.from_dict(fake.fixtures_payload()), revision=10
    )
    configuration = replace(
        SceneGlowConfigurationCollection.from_dict(fake.configuration_payload()),
        revision=10,
    )
    coordinator.data = SceneGlowSnapshot(
        state=SceneGlowState(False, CaptureState.STOPPED),
        fixtures=fixtures,
        configuration=configuration,
    )
    stale = replace(configuration, revision=9)

    coordinator._install_configuration_collection(stale)

    assert coordinator.data.configuration is configuration
    assert coordinator.data.fixtures is fixtures


async def test_fixture_control_uses_single_value_patch_and_updates_snapshot(
    hass: HomeAssistant,
) -> None:
    """An uncoupled control uses the key/value form and installs its response."""
    fake = FakeSceneGlowServer()
    client = _client(fake)
    coordinator = _coordinator(hass, client)
    coordinator.data = await coordinator._async_update_data()
    fixtures = coordinator.data.fixtures
    fixture = fixtures.fixtures[0]
    controls = tuple(
        replace(control, value="cabinet_glow")
        if control.key == "profile_type"
        else control
        for control in fixture.controls
    )
    updated = replace(
        fixtures,
        revision=8,
        fixtures=(replace(fixture, controls=controls), *fixtures.fixtures[1:]),
    )
    client.async_set_fixture_value = AsyncMock(return_value=updated)

    await coordinator.async_set_fixture_control_value(
        WLED_FIXTURE_ID, "profile_type", "cabinet_glow"
    )

    client.async_set_fixture_value.assert_awaited_once_with(
        WLED_FIXTURE_ID, 7, "profile_type", "cabinet_glow"
    )
    assert coordinator.data.fixtures.revision == 8
    assert coordinator.data.configuration.revision == 8


async def test_coupled_edge_control_uses_one_atomic_patch(
    hass: HomeAssistant,
) -> None:
    """An edge-count edit sends all counts and their recomputed total together."""
    fake = FakeSceneGlowServer()
    client = _client(fake)
    coordinator = _coordinator(hass, client)
    coordinator.data = await coordinator._async_update_data()
    client.async_set_fixture_values = AsyncMock(
        return_value=replace(coordinator.data.fixtures, revision=8)
    )

    await coordinator.async_set_fixture_control_value(WLED_FIXTURE_ID, "left_leds", 13)

    client.async_set_fixture_values.assert_awaited_once_with(
        WLED_FIXTURE_ID,
        7,
        {
            "left_leds": 13,
            "top_leds": 21,
            "right_leds": 12,
            "bottom_leds": 21,
            "led_count": 67,
        },
    )


async def test_typed_control_retries_once_after_revision_conflict(
    hass: HomeAssistant,
) -> None:
    """A key/value write refreshes both collections and retries from revision 8."""
    fake = FakeSceneGlowServer()
    client = _client(fake)
    coordinator = _coordinator(hass, client)
    coordinator.data = await coordinator._async_update_data()
    fresh_fixtures = replace(coordinator.data.fixtures, revision=8)
    client.async_get_fixtures.return_value = fresh_fixtures
    client.async_get_configuration.return_value = replace(
        coordinator.data.configuration, revision=8
    )
    client.async_set_fixture_value = AsyncMock(
        side_effect=[
            SceneGlowConflictError("stale", current_revision=8),
            replace(fresh_fixtures, revision=9),
        ]
    )

    await coordinator.async_set_fixture_control_value(
        WLED_FIXTURE_ID, "profile_type", "cabinet_glow"
    )

    assert [
        call.args[1] for call in client.async_set_fixture_value.await_args_list
    ] == [7, 8]
    assert coordinator.data.fixtures.revision == 9
    assert coordinator.data.configuration.revision == 9
