"""Typed SceneGlow control protocol v1 models.

The canonical schema is owned by the SceneGlow application repository at
``docs/protocol/sceneglow-control-v1``. These models deliberately reject
missing identity/state fields so protocol drift fails visibly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from math import isfinite
from re import fullmatch
from typing import Any, Self
from uuid import UUID


class ModelError(ValueError):
    """Raised when a SceneGlow protocol payload is invalid."""


class CaptureState(StrEnum):
    """Actual SceneGlow capture service state."""

    STOPPED = "stopped"
    STARTING = "starting"
    AWAITING_CAPTURE_PERMISSION = "awaiting_capture_permission"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPING = "stopping"
    ERROR = "error"


class SceneGlowFixtureType(StrEnum):
    """Fixture kinds exposed by the SceneGlow control API."""

    WLED = "wled"
    HOME_ASSISTANT_LIGHT = "home_assistant_light"


class SceneGlowApplyBehavior(StrEnum):
    """When a saved SceneGlow setting affects capture runtime."""

    IMMEDIATE = "immediate"
    NEXT_CAPTURE = "next_capture"


class SceneGlowFixtureControlType(StrEnum):
    """Home Assistant entity shape advertised for a fixture control."""

    BOOLEAN = "boolean"
    INTEGER = "integer"
    NUMBER = "number"
    TEXT = "text"
    SELECT = "select"


def _string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        msg = f"{key} must be a non-empty string"
        raise ModelError(msg)
    return value


def _integer(payload: dict[str, Any], key: str, *, minimum: int = 0) -> int:
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        msg = f"{key} must be an integer >= {minimum}"
        raise ModelError(msg)
    return value


def _boolean(payload: dict[str, Any], key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        msg = f"{key} must be a boolean"
        raise ModelError(msg)
    return value


def _uuid(payload: dict[str, Any], key: str) -> str:
    value = _string(payload, key)
    try:
        return str(UUID(value))
    except ValueError as err:
        msg = f"{key} must be a UUID"
        raise ModelError(msg) from err


def _fingerprint(payload: dict[str, Any], key: str) -> str:
    value = _string(payload, key).lower()
    prefix = "sha256:"
    digest = value.removeprefix(prefix)
    if not value.startswith(prefix) or len(digest) != 64:
        msg = f"{key} must be a SHA-256 fingerprint"
        raise ModelError(msg)
    try:
        bytes.fromhex(digest)
    except ValueError as err:
        msg = f"{key} must be a SHA-256 fingerprint"
        raise ModelError(msg) from err
    return value


def _number(payload: dict[str, Any], key: str) -> int | float:
    """Parse one finite JSON number without accepting booleans."""
    value = payload.get(key)
    if (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or not isfinite(value)
    ):
        raise ModelError(f"{key} must be a finite number")
    return value


@dataclass(frozen=True, slots=True)
class SceneGlowInfo:
    """Unauthenticated/authenticated installation information."""

    installation_id: str
    name: str
    app_version: str
    platform: str
    api_min: int
    api_max: int
    pairing: bool

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Self:
        """Parse an info payload."""
        pairing = payload.get("pairing")
        if not isinstance(pairing, bool):
            msg = "pairing must be a boolean"
            raise ModelError(msg)
        info = cls(
            installation_id=_uuid(payload, "installation_id"),
            name=_string(payload, "name"),
            app_version=_string(payload, "app_version"),
            platform=_string(payload, "platform"),
            api_min=_integer(payload, "api_min", minimum=1),
            api_max=_integer(payload, "api_max", minimum=1),
            pairing=pairing,
        )
        if info.api_min > info.api_max:
            msg = "api_min must not exceed api_max"
            raise ModelError(msg)
        return info

    @property
    def protocol_version(self) -> int:
        """Return the negotiated protocol used by this v1 client."""
        return 1

    @property
    def pairing_enabled(self) -> bool:
        """Return whether the TV currently accepts its displayed pairing code."""
        return self.pairing


@dataclass(frozen=True, slots=True)
class PairingResult:
    """Credential returned after TV-authorized pairing."""

    client_id: str
    client_name: str
    credential: str
    server_fingerprint: str
    api_version: int

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Self:
        """Parse a pairing response."""
        return cls(
            client_id=_uuid(payload, "client_id"),
            client_name=_string(payload, "client_name"),
            credential=_string(payload, "credential"),
            server_fingerprint=_fingerprint(payload, "server_fingerprint"),
            api_version=_integer(payload, "api_version", minimum=1),
        )

    @property
    def client_credential(self) -> str:
        """Return the credential using the config-entry field terminology."""
        return self.credential

    @property
    def server_identity(self) -> str:
        """Return the canonical pinned TLS server identity."""
        return self.server_fingerprint

    @property
    def protocol_version(self) -> int:
        """Return the negotiated API version."""
        return self.api_version


@dataclass(frozen=True, slots=True)
class SceneGlowDiagnostics:
    """Non-sensitive live capture diagnostics."""

    output_fps: float | None = None
    processing_ms: float | None = None
    capture_resolution: str | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> Self:
        """Parse optional diagnostics against the canonical protocol schema."""
        if payload is None:
            return cls()
        output_fps = _number(payload, "output_fps")
        processing_ms = _number(payload, "processing_ms")
        resolution = _string(payload, "capture_resolution")
        if output_fps < 0:
            raise ModelError("output_fps must be non-negative")
        if processing_ms < 0:
            raise ModelError("processing_ms must be non-negative")
        if fullmatch(r"[1-9][0-9]*x[1-9][0-9]*", resolution) is None:
            raise ModelError("capture_resolution must be WIDTHxHEIGHT")
        return cls(
            output_fps=float(output_fps),
            processing_ms=float(processing_ms),
            capture_resolution=resolution,
        )


@dataclass(frozen=True, slots=True)
class SceneGlowState:
    """Authoritative service snapshot."""

    requested_running: bool
    capture_state: CaptureState
    error_category: str | None = None
    diagnostics: SceneGlowDiagnostics = field(default_factory=SceneGlowDiagnostics)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Self:
        """Parse a service state payload."""
        requested_running = payload.get("requested_running")
        if not isinstance(requested_running, bool):
            msg = "requested_running must be a boolean"
            raise ModelError(msg)
        try:
            capture_state = CaptureState(_string(payload, "capture_state"))
        except ValueError as err:
            msg = "capture_state is unsupported"
            raise ModelError(msg) from err
        error_category = payload.get("error_category")
        if error_category is not None and not isinstance(error_category, str):
            msg = "error_category must be a string or null"
            raise ModelError(msg)
        diagnostics = payload.get("diagnostics")
        if diagnostics is not None and not isinstance(diagnostics, dict):
            msg = "diagnostics must be an object or null"
            raise ModelError(msg)
        return cls(
            requested_running=requested_running,
            capture_state=capture_state,
            error_category=error_category,
            diagnostics=SceneGlowDiagnostics.from_dict(diagnostics),
        )

    @property
    def reason(self) -> str | None:
        """Return the canonical error category for legacy entity diagnostics."""
        return self.error_category


@dataclass(frozen=True, slots=True)
class SceneGlowCapabilities:
    """Capabilities advertised by one installation."""

    service_control: bool = True
    capture_pause: bool = False
    fixtures: bool = False
    configuration: bool = False
    ha_light_broker: bool = False

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Self:
        """Parse known capabilities and ignore future fields."""
        return cls(
            service_control=_boolean(payload, "service_control"),
            capture_pause=_boolean(payload, "capture_pause"),
            fixtures=_boolean(payload, "fixtures"),
            configuration=_boolean(payload, "configuration"),
            ha_light_broker=_boolean(payload, "ha_light_broker"),
        )


@dataclass(frozen=True, slots=True)
class SceneGlowFixtureControl:
    """One capability-driven fixture setting."""

    key: str
    name: str
    value: bool | str | int | float
    control_type: SceneGlowFixtureControlType
    read_only: bool
    available: bool
    apply_behavior: SceneGlowApplyBehavior
    minimum: int | float | None = None
    maximum: int | float | None = None
    step: int | float | None = None
    maximum_length: int | None = None
    options: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Self:
        """Parse and cross-check type-specific control metadata."""
        try:
            control_type = SceneGlowFixtureControlType(_string(payload, "type"))
        except ValueError as err:
            raise ModelError("fixture control type is unsupported") from err
        try:
            apply_behavior = SceneGlowApplyBehavior(_string(payload, "apply_behavior"))
        except ValueError as err:
            raise ModelError("apply_behavior is unsupported") from err

        value = payload.get("value")
        minimum: int | float | None = None
        maximum: int | float | None = None
        step: int | float | None = None
        numeric_value: int | float | None = None
        maximum_length: int | None = None
        options: tuple[str, ...] = ()
        if control_type is SceneGlowFixtureControlType.BOOLEAN:
            if not isinstance(value, bool):
                raise ModelError("boolean control value must be a boolean")
        elif control_type is SceneGlowFixtureControlType.INTEGER:
            if not isinstance(value, int) or isinstance(value, bool):
                raise ModelError("integer control value must be an integer")
            minimum = _number(payload, "minimum")
            maximum = _number(payload, "maximum")
            step = _number(payload, "step")
            if any(not isinstance(item, int) for item in (minimum, maximum, step)):
                raise ModelError("integer control bounds must be integers")
            numeric_value = value
        elif control_type is SceneGlowFixtureControlType.NUMBER:
            if (
                isinstance(value, bool)
                or not isinstance(value, int | float)
                or not isfinite(value)
            ):
                raise ModelError("number control value must be a finite number")
            minimum = _number(payload, "minimum")
            maximum = _number(payload, "maximum")
            step = _number(payload, "step")
            numeric_value = value
        elif control_type is SceneGlowFixtureControlType.TEXT:
            if not isinstance(value, str):
                raise ModelError("text control value must be text")
            maximum_length = _integer(payload, "maximum_length", minimum=1)
            if len(value) > maximum_length:
                raise ModelError("text control value exceeds maximum_length")
        else:
            if not isinstance(value, str):
                raise ModelError("select control value must be text")
            raw_options = payload.get("options")
            if not isinstance(raw_options, list) or not raw_options:
                raise ModelError("select control options must be a non-empty array")
            if any(not isinstance(option, str) or not option for option in raw_options):
                raise ModelError("select control options must contain text")
            options = tuple(raw_options)
            if len(set(options)) != len(options):
                raise ModelError("select control options must be unique")
            if value not in options:
                raise ModelError("select control value must be an advertised option")

        if minimum is not None and maximum is not None and minimum > maximum:
            raise ModelError("fixture control minimum must not exceed maximum")
        if step is not None and step <= 0:
            raise ModelError("fixture control step must be positive")
        if (
            minimum is not None
            and maximum is not None
            and numeric_value is not None
            and not minimum <= numeric_value <= maximum
        ):
            raise ModelError("fixture control value is outside its advertised range")

        return cls(
            key=_string(payload, "key"),
            name=_string(payload, "name"),
            value=value,
            control_type=control_type,
            read_only=_boolean(payload, "read_only"),
            available=_boolean(payload, "available"),
            apply_behavior=apply_behavior,
            minimum=minimum,
            maximum=maximum,
            step=step,
            maximum_length=maximum_length,
            options=options,
        )


@dataclass(frozen=True, slots=True)
class SceneGlowFixture:
    """One fixture participating in SceneGlow capture output."""

    fixture_uuid: str
    fixture_type: SceneGlowFixtureType
    name: str
    enabled: bool
    available: bool
    controls: tuple[SceneGlowFixtureControl, ...] = ()

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Self:
        """Parse an authoritative fixture."""
        try:
            fixture_type = SceneGlowFixtureType(_string(payload, "fixture_type"))
        except ValueError as err:
            raise ModelError("fixture_type is unsupported") from err
        raw_controls = payload.get("controls", [])
        if not isinstance(raw_controls, list):
            raise ModelError("controls must be an array")
        controls: list[SceneGlowFixtureControl] = []
        for item in raw_controls:
            if not isinstance(item, dict):
                raise ModelError("controls must contain objects")
            controls.append(SceneGlowFixtureControl.from_dict(item))
        if len({control.key for control in controls}) != len(controls):
            raise ModelError("fixture control keys must be unique")
        enabled_control = next(
            (control for control in controls if control.key == "enabled"), None
        )
        enabled = _boolean(payload, "enabled")
        if enabled_control is not None and (
            enabled_control.control_type is not SceneGlowFixtureControlType.BOOLEAN
            or enabled_control.value is not enabled
        ):
            raise ModelError("enabled control must match fixture enabled state")
        return cls(
            fixture_uuid=_uuid(payload, "fixture_uuid"),
            fixture_type=fixture_type,
            name=_string(payload, "name"),
            enabled=enabled,
            available=_boolean(payload, "available"),
            controls=tuple(controls),
        )


@dataclass(frozen=True, slots=True)
class SceneGlowFixtureCollection:
    """Authoritative fixture snapshot at one shared settings revision."""

    revision: int
    fixtures: tuple[SceneGlowFixture, ...]

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Self:
        """Parse a fixture collection."""
        raw_fixtures = payload.get("fixtures")
        if not isinstance(raw_fixtures, list):
            raise ModelError("fixtures must be an array")
        fixtures: list[SceneGlowFixture] = []
        for item in raw_fixtures:
            if not isinstance(item, dict):
                raise ModelError("fixtures must contain objects")
            fixtures.append(SceneGlowFixture.from_dict(item))
        if len({fixture.fixture_uuid for fixture in fixtures}) != len(fixtures):
            raise ModelError("fixture_uuid values must be unique")
        return cls(
            revision=_integer(payload, "revision"),
            fixtures=tuple(fixtures),
        )


@dataclass(frozen=True, slots=True)
class SceneGlowConfigurationSwitch:
    """One remotely controllable SceneGlow application setting."""

    key: str
    name: str
    enabled: bool
    available: bool
    apply_behavior: SceneGlowApplyBehavior

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Self:
        """Parse an authoritative configuration switch."""
        try:
            apply_behavior = SceneGlowApplyBehavior(_string(payload, "apply_behavior"))
        except ValueError as err:
            raise ModelError("apply_behavior is unsupported") from err
        return cls(
            key=_string(payload, "key"),
            name=_string(payload, "name"),
            enabled=_boolean(payload, "enabled"),
            available=_boolean(payload, "available"),
            apply_behavior=apply_behavior,
        )


@dataclass(frozen=True, slots=True)
class SceneGlowConfigurationCollection:
    """Authoritative configuration controls at one settings revision."""

    revision: int
    switches: tuple[SceneGlowConfigurationSwitch, ...]

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Self:
        """Parse a configuration-switch collection."""
        raw_switches = payload.get("switches")
        if not isinstance(raw_switches, list):
            raise ModelError("switches must be an array")
        switches: list[SceneGlowConfigurationSwitch] = []
        for item in raw_switches:
            if not isinstance(item, dict):
                raise ModelError("switches must contain objects")
            switches.append(SceneGlowConfigurationSwitch.from_dict(item))
        if len({item.key for item in switches}) != len(switches):
            raise ModelError("configuration switch keys must be unique")
        return cls(
            revision=_integer(payload, "revision"),
            switches=tuple(switches),
        )


@dataclass(frozen=True, slots=True)
class SceneGlowSnapshot:
    """Complete coordinator view of one SceneGlow installation."""

    state: SceneGlowState
    fixtures: SceneGlowFixtureCollection | None = None
    configuration: SceneGlowConfigurationCollection | None = None


@dataclass(frozen=True, slots=True)
class SceneGlowEvent:
    """One event-channel message."""

    event_type: str
    api_version: int
    stream_epoch: str
    sequence: int
    state: SceneGlowState | None = None
    paired: bool | None = None
    key: str | None = None
    fixture_uuid: str | None = None
    revision: int | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> Self:
        """Parse an event envelope."""
        event_type = _string(value, "type")
        api_version = _integer(value, "api_version", minimum=1)
        state: SceneGlowState | None = None
        paired: bool | None = None
        key: str | None = None
        fixture_uuid: str | None = None
        revision: int | None = None
        if event_type in {"subscribed", "service_state_changed"}:
            state_payload = value.get("state")
            if not isinstance(state_payload, dict):
                msg = "state event must contain a state object"
                raise ModelError(msg)
            state = SceneGlowState.from_dict(state_payload)
        elif event_type == "authentication_changed":
            paired = _boolean(value, "paired")
        elif event_type == "configuration_changed":
            key = _string(value, "key")
            revision = _integer(value, "revision")
        elif event_type == "fixture_changed":
            fixture_uuid = _uuid(value, "fixture_uuid")
            revision = _integer(value, "revision")
        return cls(
            event_type=event_type,
            api_version=api_version,
            stream_epoch=_uuid(value, "stream_epoch"),
            sequence=_integer(value, "sequence"),
            state=state,
            paired=paired,
            key=key,
            fixture_uuid=fixture_uuid,
            revision=revision,
        )
