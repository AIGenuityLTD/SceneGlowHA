"""Tests for strict protocol models."""

from __future__ import annotations

import pytest

from custom_components.sceneglow.models import (
    CaptureState,
    ModelError,
    SceneGlowCapabilities,
    SceneGlowConfigurationCollection,
    SceneGlowEvent,
    SceneGlowFixtureCollection,
    SceneGlowFixtureControlType,
    SceneGlowInfo,
    SceneGlowState,
)
from tests.fake_sceneglow import STREAM_EPOCH, FakeSceneGlowServer


def test_info_parses_stable_installation_uuid() -> None:
    """The installation UUID, not an address, is retained as identity."""
    fake = FakeSceneGlowServer()
    info = SceneGlowInfo.from_dict(fake.info_payload())
    assert info.installation_id == fake.installation_id
    assert info.api_min == 1
    assert info.api_max == 1


def test_state_keeps_requested_and_actual_state_separate() -> None:
    """Requested-running can be true while platform consent is pending."""
    fake = FakeSceneGlowServer(
        requested_running=True,
        capture_state="awaiting_capture_permission",
    )
    state = SceneGlowState.from_dict(fake.state_payload())
    assert state.requested_running is True
    assert state.capture_state is CaptureState.AWAITING_CAPTURE_PERMISSION


def test_paused_state_keeps_requested_capture_on() -> None:
    """Paused is an actual state distinct from a stopped capture target."""
    state = SceneGlowState.from_dict(
        {"requested_running": True, "capture_state": "paused"}
    )
    assert state.requested_running is True
    assert state.capture_state is CaptureState.PAUSED


def test_running_state_parses_live_performance_diagnostics() -> None:
    """Protocol v1 performance samples retain all supported metric values."""
    fake = FakeSceneGlowServer(requested_running=True, capture_state="running")
    next(
        item for item in fake.configuration if item["key"] == "performance_diagnostics"
    )["enabled"] = True

    state = SceneGlowState.from_dict(fake.state_payload())

    assert state.diagnostics.output_fps == 29.8
    assert state.diagnostics.processing_ms == 4.2
    assert state.diagnostics.capture_resolution == "320x180"


def test_performance_diagnostics_are_omitted_when_not_running_or_enabled() -> None:
    """Absent optional samples safely parse as unavailable measurements."""
    state = SceneGlowState.from_dict(FakeSceneGlowServer().state_payload())

    assert state.diagnostics.output_fps is None
    assert state.diagnostics.processing_ms is None
    assert state.diagnostics.capture_resolution is None


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("output_fps", None),
        ("output_fps", True),
        ("output_fps", -0.1),
        ("output_fps", float("nan")),
        ("processing_ms", None),
        ("processing_ms", -1),
        ("capture_resolution", None),
        ("capture_resolution", "0x180"),
        ("capture_resolution", "320 by 180"),
    ],
)
def test_performance_diagnostics_strictly_validate_canonical_fields(
    field: str, invalid: object
) -> None:
    """Present diagnostics must be complete and schema-valid."""
    payload = {
        "requested_running": True,
        "capture_state": "running",
        "diagnostics": {
            "output_fps": 29.8,
            "processing_ms": 4.2,
            "capture_resolution": "320x180",
        },
    }
    payload["diagnostics"][field] = invalid

    with pytest.raises(ModelError):
        SceneGlowState.from_dict(payload)


def test_info_rejects_non_uuid_identity() -> None:
    """Mutable names and addresses cannot become installation identities."""
    payload = FakeSceneGlowServer().info_payload()
    payload["installation_id"] = "living-room-tv"
    with pytest.raises(ModelError, match="must be a UUID"):
        SceneGlowInfo.from_dict(payload)


def test_state_rejects_unknown_capture_state() -> None:
    """An unknown actual state fails visibly until compatibility is designed."""
    payload = FakeSceneGlowServer().state_payload()
    payload["capture_state"] = "magically_running"
    with pytest.raises(ModelError, match="unsupported"):
        SceneGlowState.from_dict(payload)


def test_info_rejects_invalid_api_range() -> None:
    """Protocol ranges must be internally consistent before negotiation."""
    payload = FakeSceneGlowServer().info_payload()
    payload["api_min"] = 2
    with pytest.raises(ModelError, match="api_min"):
        SceneGlowInfo.from_dict(payload)


def test_capabilities_require_strict_booleans_and_ignore_extensions() -> None:
    """All advertised capability flags are typed, while extensions remain safe."""
    payload = {
        "service_control": True,
        "capture_pause": True,
        "fixtures": True,
        "configuration": True,
        "ha_light_broker": True,
        "future_capability": {"enabled": True},
    }
    capabilities = SceneGlowCapabilities.from_dict(payload)
    assert capabilities.capture_pause is True
    assert capabilities.configuration is True
    payload["fixtures"] = 1
    with pytest.raises(ModelError, match="fixtures must be a boolean"):
        SceneGlowCapabilities.from_dict(payload)


@pytest.mark.parametrize("capture_pause", [None, 1, "true"])
def test_capabilities_require_capture_pause_boolean(capture_pause: object) -> None:
    """Pause support is a required strict flag and is never inferred."""
    payload = {
        "service_control": True,
        "capture_pause": capture_pause,
        "fixtures": True,
        "configuration": True,
        "ha_light_broker": True,
    }
    if capture_pause is None:
        payload.pop("capture_pause")
    with pytest.raises(ModelError, match="capture_pause must be a boolean"):
        SceneGlowCapabilities.from_dict(payload)


@pytest.mark.parametrize(
    ("payload_name", "field", "invalid"),
    [
        ("fixtures", "revision", True),
        ("fixtures", "enabled", "false"),
        ("fixtures", "fixture_uuid", "wled-primary"),
        ("configuration", "revision", -1),
        ("configuration", "available", 1),
        ("configuration", "apply_behavior", "eventually"),
    ],
)
def test_control_collections_strictly_validate_contract_fields(
    payload_name: str, field: str, invalid: object
) -> None:
    """Malformed UUIDs, booleans, revisions, and enums fail visibly."""
    fake = FakeSceneGlowServer()
    if payload_name == "fixtures":
        payload = fake.fixtures_payload()
        if field == "revision":
            payload[field] = invalid
        else:
            payload["fixtures"][0][field] = invalid
        parser = SceneGlowFixtureCollection.from_dict
    else:
        payload = fake.configuration_payload()
        if field == "revision":
            payload[field] = invalid
        else:
            payload["switches"][0][field] = invalid
        parser = SceneGlowConfigurationCollection.from_dict
    with pytest.raises(ModelError):
        parser(payload)


def test_control_collections_parse_and_ignore_optional_extensions() -> None:
    """Known data is retained without rejecting future optional properties."""
    fake = FakeSceneGlowServer()
    fixture_payload = fake.fixtures_payload()
    fixture_payload["future"] = True
    fixture_payload["fixtures"][0]["target"] = "ignored"
    configuration_payload = fake.configuration_payload()
    configuration_payload["switches"][0]["explanation"] = "ignored"

    fixtures = SceneGlowFixtureCollection.from_dict(fixture_payload)
    configuration = SceneGlowConfigurationCollection.from_dict(configuration_payload)

    assert len(fixtures.fixtures) == 2
    assert len(fixtures.fixtures[0].controls) == 47
    assert len(fixtures.fixtures[1].controls) == 4
    gamma = next(
        control for control in fixtures.fixtures[0].controls if control.key == "gamma"
    )
    assert gamma.control_type is SceneGlowFixtureControlType.NUMBER
    assert (gamma.minimum, gamma.maximum, gamma.step) == (0.1, 3.0, 0.01)
    assert next(
        control
        for control in fixtures.fixtures[0].controls
        if control.key == "profile_type"
    ).options == (
        "screen_glow",
        "cabinet_glow",
        "skirting_glow",
        "lamp_glow",
        "spot_glow",
    )
    assert len(configuration.switches) == 4


@pytest.mark.parametrize(
    ("key", "field", "invalid"),
    [
        ("enabled", "value", 1),
        ("port", "value", True),
        ("port", "minimum", 1.5),
        ("gamma", "value", float("inf")),
        ("gamma", "step", 0),
        ("host", "maximum_length", True),
        ("profile_type", "options", ["screen_glow", "screen_glow"]),
        ("profile_type", "value", "unknown"),
        ("enabled", "read_only", 0),
        ("enabled", "apply_behavior", "later"),
    ],
)
def test_fixture_controls_strictly_reject_malformed_metadata(
    key: str, field: str, invalid: object
) -> None:
    """Controls reject coercible primitives and inconsistent metadata."""
    payload = FakeSceneGlowServer().fixtures_payload()
    control = next(
        item for item in payload["fixtures"][0]["controls"] if item["key"] == key
    )
    control[field] = invalid
    with pytest.raises(ModelError):
        SceneGlowFixtureCollection.from_dict(payload)


def test_fixture_enabled_control_must_match_legacy_summary() -> None:
    """The compatibility summary cannot disagree with its canonical control."""
    payload = FakeSceneGlowServer().fixtures_payload()
    payload["fixtures"][0]["controls"][0]["value"] = False
    with pytest.raises(ModelError, match="must match"):
        SceneGlowFixtureCollection.from_dict(payload)


def test_control_events_parse_revision_and_identity() -> None:
    """Fixture and wildcard configuration events retain revision metadata."""
    fixture = SceneGlowEvent.from_dict(
        {
            "type": "fixture_changed",
            "api_version": 1,
            "stream_epoch": STREAM_EPOCH,
            "sequence": 4,
            "fixture_uuid": "80d4ac95-0eeb-4d9c-9c6d-23237dd5dd2c",
            "revision": 8,
            "future": "ignored",
        }
    )
    configuration = SceneGlowEvent.from_dict(
        {
            "type": "configuration_changed",
            "api_version": 1,
            "stream_epoch": STREAM_EPOCH,
            "sequence": 5,
            "key": "*",
            "revision": 8,
        }
    )
    assert fixture.fixture_uuid is not None
    assert fixture.revision == configuration.revision == 8
    assert configuration.key == "*"


@pytest.mark.parametrize(
    ("field", "invalid"),
    [("fixture_uuid", "bad"), ("revision", True), ("stream_epoch", "bad")],
)
def test_fixture_event_rejects_malformed_control_fields(
    field: str, invalid: object
) -> None:
    """Event identity and revision fields use the same strict validation."""
    payload = {
        "type": "fixture_changed",
        "api_version": 1,
        "stream_epoch": STREAM_EPOCH,
        "sequence": 4,
        "fixture_uuid": "80d4ac95-0eeb-4d9c-9c6d-23237dd5dd2c",
        "revision": 8,
    }
    payload[field] = invalid
    with pytest.raises(ModelError):
        SceneGlowEvent.from_dict(payload)
