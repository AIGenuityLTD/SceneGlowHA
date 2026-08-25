"""Protocol client tests against the real fake HTTP/WebSocket server."""

from __future__ import annotations

import asyncio
import hashlib
from unittest.mock import AsyncMock, Mock, patch

import aiohttp
import pytest

from custom_components.sceneglow.api import (
    SceneGlowApiClient,
    SceneGlowAuthenticationError,
    SceneGlowCannotConnect,
    SceneGlowConflictError,
    SceneGlowControlNotFoundError,
    SceneGlowControlUnavailableError,
    SceneGlowEndpoint,
    SceneGlowIdentityMismatch,
    SceneGlowInvalidConfigurationError,
    SceneGlowPairingError,
    SceneGlowProtocolError,
)
from custom_components.sceneglow.models import CaptureState
from tests.fake_sceneglow import (
    CLIENT_CREDENTIAL,
    CLIENT_ID,
    PAIRING_CODE,
    WLED_FIXTURE_ID,
    FakeSceneGlowServer,
)


async def test_first_contact_captures_canonical_tls_fingerprint() -> None:
    """The unpaired client pins the exact certificate presented by the TV."""
    certificate = b"SceneGlow test certificate"
    ssl_object = Mock()
    ssl_object.getpeercert.return_value = certificate
    writer = Mock()
    writer.get_extra_info.return_value = ssl_object
    writer.wait_closed = AsyncMock()

    client = SceneGlowApiClient(
        Mock(), SceneGlowEndpoint("192.0.2.10", 47_990), request_timeout=1
    )
    with patch(
        "custom_components.sceneglow.api.open_connection",
        new=AsyncMock(return_value=(Mock(), writer)),
    ):
        identity = await client.async_discover_server_identity()

    expected = f"sha256:{hashlib.sha256(certificate).hexdigest()}"
    assert identity == expected
    assert client.endpoint.server_identity == expected
    writer.close.assert_called_once()


async def test_pair_state_control_and_event(aiohttp_server, socket_enabled) -> None:
    """Exercise the first-release vertical slice over actual sockets."""
    fake = FakeSceneGlowServer()
    server = await aiohttp_server(fake.create_app())
    endpoint = SceneGlowEndpoint(
        server.host,
        server.port,
        use_tls=False,
        server_identity=fake.server_fingerprint,
    )
    async with aiohttp.ClientSession() as session:
        client = SceneGlowApiClient(session, endpoint)
        info = await client.async_get_info()
        pairing = await client.async_pair(PAIRING_CODE, client_name="HA test")
        assert pairing.server_fingerprint == fake.server_fingerprint
        assert info.api_min <= pairing.api_version <= info.api_max

        authenticated = SceneGlowApiClient(
            session,
            endpoint,
            client_id=pairing.client_id,
            client_credential=pairing.client_credential,
        )
        assert (
            await authenticated.async_get_state()
        ).capture_state is CaptureState.STOPPED

        event_iterator = authenticated.async_events()
        subscribed = await anext(event_iterator)
        assert subscribed.event_type == "subscribed"
        event_task = asyncio.create_task(anext(event_iterator))
        for _ in range(100):
            if fake.sockets:
                break
            await asyncio.sleep(0.01)
        assert fake.sockets
        started = await authenticated.async_start_service()
        event = await event_task
        await event_iterator.aclose()

        assert started.requested_running is True
        assert started.capture_state is CaptureState.AWAITING_CAPTURE_PERMISSION
        assert event.event_type == "service_state_changed"
        assert event.state == started


async def test_pause_resume_paths_authentication_and_idempotency(
    aiohttp_server, socket_enabled
) -> None:
    """Pause/resume use their authenticated POST routes and return snapshots."""
    fake = FakeSceneGlowServer(
        clients={CLIENT_ID: CLIENT_CREDENTIAL},
        requested_running=True,
        capture_state="running",
    )
    server = await aiohttp_server(fake.create_app())
    async with aiohttp.ClientSession() as session:
        client = SceneGlowApiClient(
            session,
            SceneGlowEndpoint(server.host, server.port, use_tls=False),
            client_id=CLIENT_ID,
            client_credential=CLIENT_CREDENTIAL,
        )

        paused = await client.async_pause_service()
        paused_again = await client.async_pause_service()
        resumed = await client.async_resume_service()
        resumed_again = await client.async_resume_service()

        assert paused == paused_again
        assert paused.requested_running is True
        assert paused.capture_state is CaptureState.PAUSED
        assert resumed == resumed_again
        assert resumed.capture_state is CaptureState.RUNNING
        assert fake.service_calls == ["pause", "pause", "resume", "resume"]

        stopped = await client.async_stop_service()
        pause_stopped = await client.async_pause_service()
        resume_stopped = await client.async_resume_service()
        assert stopped == pause_stopped == resume_stopped
        assert stopped.capture_state is CaptureState.STOPPED
        assert stopped.requested_running is False
        assert fake.service_calls[-3:] == ["stop", "pause", "resume"]

        unauthenticated = SceneGlowApiClient(
            session,
            SceneGlowEndpoint(server.host, server.port, use_tls=False),
        )
        with pytest.raises(SceneGlowAuthenticationError):
            await unauthenticated.async_pause_service()
        with pytest.raises(SceneGlowAuthenticationError):
            await unauthenticated.async_resume_service()


@pytest.mark.parametrize(
    ("operation", "path"),
    [
        ("async_start_service", "/service/start"),
        ("async_stop_service", "/service/stop"),
        ("async_pause_service", "/service/pause"),
        ("async_resume_service", "/service/resume"),
    ],
)
async def test_service_operations_reject_invalid_immediate_snapshots(
    operation: str, path: str
) -> None:
    """Every service POST applies the same strict state response parsing."""
    client = SceneGlowApiClient(
        Mock(), SceneGlowEndpoint("192.0.2.10", 47_990, use_tls=False)
    )
    client._request = AsyncMock(
        return_value={
            "requested_running": True,
            "capture_state": "invalid",
        }
    )

    with pytest.raises(SceneGlowProtocolError, match="invalid state"):
        await getattr(client, operation)()
    client._request.assert_awaited_once_with("POST", path, body={})


async def test_pairing_error_is_distinct(aiohttp_server, socket_enabled) -> None:
    """A wrong TV code is actionable and not a generic connection failure."""
    fake = FakeSceneGlowServer()
    server = await aiohttp_server(fake.create_app())
    async with aiohttp.ClientSession() as session:
        client = SceneGlowApiClient(
            session,
            SceneGlowEndpoint(
                server.host,
                server.port,
                use_tls=False,
                server_identity=fake.server_fingerprint,
            ),
        )
        with pytest.raises(SceneGlowPairingError):
            await client.async_pair("wrong", client_name="HA test")


async def test_revoked_credential_maps_to_auth_error(
    aiohttp_server, socket_enabled
) -> None:
    """Revocation maps to the exception that triggers HA reauthentication."""
    fake = FakeSceneGlowServer(clients={CLIENT_ID: CLIENT_CREDENTIAL})
    server = await aiohttp_server(fake.create_app())
    async with aiohttp.ClientSession() as session:
        client = SceneGlowApiClient(
            session,
            SceneGlowEndpoint(server.host, server.port, use_tls=False),
            client_id=CLIENT_ID,
            client_credential="revoked",
        )
        with pytest.raises(SceneGlowAuthenticationError):
            await client.async_get_state()


async def test_pairing_cannot_replace_pinned_identity(
    aiohttp_server, socket_enabled
) -> None:
    """The PIN cannot authorize a certificate other than the probed identity."""
    fake = FakeSceneGlowServer(clients={CLIENT_ID: CLIENT_CREDENTIAL})
    server = await aiohttp_server(fake.create_app())
    async with aiohttp.ClientSession() as session:
        client = SceneGlowApiClient(
            session,
            SceneGlowEndpoint(
                server.host,
                server.port,
                use_tls=False,
                server_identity="00" * 32,
            ),
            client_id=CLIENT_ID,
            client_credential=CLIENT_CREDENTIAL,
        )
        with pytest.raises(SceneGlowIdentityMismatch):
            await client.async_pair(PAIRING_CODE, client_name="HA test")


async def test_authenticated_capabilities_and_control_get_patch(
    aiohttp_server, socket_enabled
) -> None:
    """All control routes authenticate and return complete parsed collections."""
    fake = FakeSceneGlowServer(clients={CLIENT_ID: CLIENT_CREDENTIAL})
    server = await aiohttp_server(fake.create_app())
    async with aiohttp.ClientSession() as session:
        client = SceneGlowApiClient(
            session,
            SceneGlowEndpoint(server.host, server.port, use_tls=False),
            client_id=CLIENT_ID,
            client_credential=CLIENT_CREDENTIAL,
        )
        capabilities = await client.async_get_capabilities()
        assert capabilities.fixtures is True
        assert capabilities.configuration is True

        fixtures = await client.async_get_fixtures()
        fixtures = await client.async_set_fixture_enabled(
            WLED_FIXTURE_ID, fixtures.revision, False
        )
        assert fixtures.revision == 8
        assert fixtures.fixtures[0].enabled is False

        configuration = await client.async_get_configuration()
        configuration = await client.async_set_configuration_enabled(
            "detect_black_bars", configuration.revision, False
        )
        assert configuration.revision == 9
        assert configuration.switches[1].enabled is False


async def test_performance_diagnostics_patch_immediately_exposes_live_state_metrics(
    aiohttp_server, socket_enabled
) -> None:
    """The app's immediate diagnostics control feeds the existing state model."""
    fake = FakeSceneGlowServer(
        clients={CLIENT_ID: CLIENT_CREDENTIAL},
        requested_running=True,
        capture_state="running",
    )
    server = await aiohttp_server(fake.create_app())
    async with aiohttp.ClientSession() as session:
        client = SceneGlowApiClient(
            session,
            SceneGlowEndpoint(server.host, server.port, use_tls=False),
            client_id=CLIENT_ID,
            client_credential=CLIENT_CREDENTIAL,
        )
        configuration = await client.async_get_configuration()
        performance = next(
            control
            for control in configuration.switches
            if control.key == "performance_diagnostics"
        )
        assert performance.apply_behavior.value == "immediate"

        updated = await client.async_set_configuration_enabled(
            performance.key, configuration.revision, True
        )
        state = await client.async_get_state()

        assert (
            next(
                control
                for control in updated.switches
                if control.key == performance.key
            ).enabled
            is True
        )
        assert state.diagnostics.output_fps == 29.8
        assert state.diagnostics.processing_ms == 4.2
        assert state.diagnostics.capture_resolution == "320x180"


async def test_control_error_mapping_and_revision_preservation(
    aiohttp_server, socket_enabled
) -> None:
    """Conflicts, unavailable controls, invalid values, and stale IDs stay distinct."""
    fake = FakeSceneGlowServer(
        clients={CLIENT_ID: CLIENT_CREDENTIAL},
        amazon_build=True,
        invalid_configuration_keys={"performance_diagnostics"},
    )
    server = await aiohttp_server(fake.create_app())
    async with aiohttp.ClientSession() as session:
        client = SceneGlowApiClient(
            session,
            SceneGlowEndpoint(server.host, server.port, use_tls=False),
            client_id=CLIENT_ID,
            client_credential=CLIENT_CREDENTIAL,
        )
        with pytest.raises(SceneGlowConflictError) as conflict:
            await client.async_set_fixture_enabled(WLED_FIXTURE_ID, 6, False)
        assert conflict.value.current_revision == 7

        with pytest.raises(SceneGlowControlUnavailableError):
            await client.async_set_configuration_enabled(
                "capture_indicator_exclusion", 7, True
            )
        with pytest.raises(SceneGlowInvalidConfigurationError):
            await client.async_set_configuration_enabled(
                "performance_diagnostics", 7, True
            )
        with pytest.raises(SceneGlowControlNotFoundError):
            await client.async_set_configuration_enabled("missing key", 7, True)
        assert fake.last_raw_path is not None
        assert "missing%20key" in fake.last_raw_path


async def test_fixture_key_value_and_atomic_patch_forms(
    aiohttp_server, socket_enabled
) -> None:
    """Typed single settings and coupled settings return complete snapshots."""
    fake = FakeSceneGlowServer(clients={CLIENT_ID: CLIENT_CREDENTIAL})
    server = await aiohttp_server(fake.create_app())
    async with aiohttp.ClientSession() as session:
        client = SceneGlowApiClient(
            session,
            SceneGlowEndpoint(server.host, server.port, use_tls=False),
            client_id=CLIENT_ID,
            client_credential=CLIENT_CREDENTIAL,
        )
        fixtures = await client.async_set_fixture_value(
            WLED_FIXTURE_ID, 7, "profile_type", "cabinet_glow"
        )
        wled = fixtures.fixtures[0]
        assert fixtures.revision == 8
        assert (
            next(
                control for control in wled.controls if control.key == "profile_type"
            ).value
            == "cabinet_glow"
        )

        fixtures = await client.async_set_fixture_values(
            WLED_FIXTURE_ID,
            8,
            {
                "left_leds": 13,
                "top_leds": 22,
                "right_leds": 13,
                "bottom_leds": 22,
                "led_count": 70,
            },
        )
        assert fixtures.revision == 9
        assert (
            next(
                control
                for control in fixtures.fixtures[0].controls
                if control.key == "led_count"
            ).value
            == 70
        )


async def test_fixture_patch_rejects_invalid_unavailable_and_unknown_controls(
    aiohttp_server, socket_enabled
) -> None:
    """Fixture failures retain their distinct actionable API exceptions."""
    fake = FakeSceneGlowServer(clients={CLIENT_ID: CLIENT_CREDENTIAL})
    controls = {item["key"]: item for item in fake.fixtures[0]["controls"]}
    controls["send_black_on_stop"]["available"] = False
    server = await aiohttp_server(fake.create_app())
    async with aiohttp.ClientSession() as session:
        client = SceneGlowApiClient(
            session,
            SceneGlowEndpoint(server.host, server.port, use_tls=False),
            client_id=CLIENT_ID,
            client_credential=CLIENT_CREDENTIAL,
        )
        with pytest.raises(SceneGlowControlUnavailableError):
            await client.async_set_fixture_value(
                WLED_FIXTURE_ID, 7, "send_black_on_stop", False
            )
        with pytest.raises(SceneGlowInvalidConfigurationError):
            await client.async_set_fixture_value(
                WLED_FIXTURE_ID, 7, "brightness_percent", 12
            )
        with pytest.raises(SceneGlowControlNotFoundError):
            await client.async_set_fixture_value(
                WLED_FIXTURE_ID, 7, "future setting", True
            )


async def test_control_routes_reject_revoked_credentials(
    aiohttp_server, socket_enabled
) -> None:
    """Capabilities and collections cannot be read without current pairing."""
    fake = FakeSceneGlowServer(clients={CLIENT_ID: CLIENT_CREDENTIAL})
    server = await aiohttp_server(fake.create_app())
    async with aiohttp.ClientSession() as session:
        client = SceneGlowApiClient(
            session,
            SceneGlowEndpoint(server.host, server.port, use_tls=False),
            client_id=CLIENT_ID,
            client_credential="revoked",
        )
        with pytest.raises(SceneGlowAuthenticationError):
            await client.async_get_capabilities()


@pytest.mark.parametrize(
    ("status", "error_type"),
    [
        (401, SceneGlowAuthenticationError),
        (403, SceneGlowAuthenticationError),
        (503, SceneGlowCannotConnect),
    ],
)
async def test_websocket_handshake_errors_map_to_integration_exceptions(
    status: int, error_type: type[Exception]
) -> None:
    """HTTP event-stream failures follow reauth and reconnect handling."""
    session = Mock()
    session.ws_connect = AsyncMock(
        side_effect=aiohttp.WSServerHandshakeError(
            Mock(),
            (),
            status=status,
            message="rejected",
        )
    )
    client = SceneGlowApiClient(
        session,
        SceneGlowEndpoint("192.0.2.10", 47_990, use_tls=False),
        client_id=CLIENT_ID,
        client_credential=CLIENT_CREDENTIAL,
    )

    with pytest.raises(error_type):
        await client._open_websocket()
