"""Small in-process SceneGlow protocol v1 server for tests and development."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from aiohttp import web

INSTALLATION_ID = "8d359ff8-7ad9-4c80-ad9f-e7ca46e13b79"
STREAM_EPOCH = "a331a84d-cb87-49db-82f2-ab32c06972a5"
PAIRING_CODE = "123456"
CLIENT_ID = "41ebf0ea-5448-48f1-93a2-d483d99a67c4"
CLIENT_CREDENTIAL = "fake-scene-glow-credential"
WLED_FIXTURE_ID = "80d4ac95-0eeb-4d9c-9c6d-23237dd5dd2c"
HA_FIXTURE_ID = "323dcfcb-c4de-4126-8d7c-3060a8974db3"


def _control(
    key: str,
    value: bool | str | int | float,
    control_type: str,
    **metadata: Any,
) -> dict[str, Any]:
    """Create one app-shaped fixture control for protocol tests."""
    return {
        "key": key,
        "name": key.replace("_", " ").title(),
        "value": value,
        "type": control_type,
        "read_only": False,
        "available": True,
        "apply_behavior": "immediate" if key == "enabled" else "next_capture",
        **metadata,
    }


def _integer(
    key: str, value: int, minimum: int, maximum: int, step: int = 1
) -> dict[str, Any]:
    return _control(
        key,
        value,
        "integer",
        minimum=minimum,
        maximum=maximum,
        step=step,
    )


def _select(key: str, value: str, *options: str) -> dict[str, Any]:
    return _control(key, value, "select", options=list(options))


def _wled_controls() -> list[dict[str, Any]]:
    """Return all 47 WLED controls advertised by the current app contract."""
    return [
        _control("enabled", True, "boolean"),
        _control("host", "192.0.2.70", "text", maximum_length=15),
        _integer("port", 21324, 1, 65_535),
        _integer("first_led", 0, 0, 65_535),
        _integer("led_count", 66, 1, 1_024),
        _integer("max_fps", 30, 1, 60),
        _integer("max_payload_bytes", 1_200, 3, 65_535),
        _control("send_black_on_stop", True, "boolean"),
        _select(
            "profile_type",
            "screen_glow",
            "screen_glow",
            "cabinet_glow",
            "skirting_glow",
            "lamp_glow",
            "spot_glow",
        ),
        _integer("brightness_percent", 100, 0, 100, 5),
        _integer("saturation_percent", 100, 0, 250),
        _control("gamma", 1.0, "number", minimum=0.1, maximum=3.0, step=0.01),
        _integer("white_suppression_threshold_percent", 100, 0, 100, 5),
        _integer("motion_sensitivity_percent", 100, 25, 200, 5),
        _integer("smoothing_percent", 50, 0, 95),
        _integer("black_threshold", 4, 0, 255),
        _integer("sync_delay_ms", 0, 0, 250, 5),
        _integer("edge_depth_percent", 10, 1, 50),
        _integer("left_leds", 12, 0, 1_024),
        _integer("top_leds", 21, 0, 1_024),
        _integer("right_leds", 12, 0, 1_024),
        _integer("bottom_leds", 21, 0, 1_024),
        _select(
            "start_corner",
            "top_left",
            "top_left",
            "top_right",
            "bottom_left",
            "bottom_right",
        ),
        _select("direction", "clockwise", "clockwise", "counter_clockwise"),
        _integer("led_offset", 0, -1_024, 1_024),
        _select(
            "relative_position",
            "centre",
            "top_left",
            "top",
            "top_right",
            "left",
            "centre",
            "right",
            "bottom_left",
            "bottom",
            "bottom_right",
        ),
        _select("orientation", "horizontal", "horizontal", "vertical"),
        _integer("span_percent", 100, 5, 100),
        _control("reversed", False, "boolean"),
        _select(
            "fixture_layout",
            "screen_perimeter",
            "screen_perimeter",
            "straight",
            "l_shape",
            "rectangle",
            "ring",
            "cluster",
        ),
        _select(
            "fixture_placement",
            "around_screen",
            "around_screen",
            "above_left",
            "above_centre",
            "above_right",
            "right_upper",
            "right_centre",
            "right_lower",
            "below_right",
            "below_centre",
            "below_left",
            "left_lower",
            "left_centre",
            "left_upper",
        ),
        _select(
            "fixture_direction",
            "right",
            "right",
            "down_right",
            "down",
            "down_left",
            "left",
            "up_left",
            "up",
            "up_right",
        ),
        _integer("fixture_width_percent", 100, 5, 200),
        _integer("fixture_height_percent", 100, 5, 200),
        _select("l_shape_turn", "clockwise", "clockwise", "counter_clockwise"),
        _select(
            "l_shape_anchor", "fixture_centre", "fixture_centre", "led_zero", "bend"
        ),
        _select("ring_start", "top", "top", "bottom", "left", "right"),
        _select(
            "cluster_flow_mode",
            "whole_fixture",
            "whole_fixture",
            "led_zero_to_last",
            "last_to_led_zero",
        ),
        _select(
            "motion_effect",
            "off",
            "off",
            "motion_continuation",
            "motion_pulse",
            "colour_flow",
            "ambient_drift",
            "viscous_motion",
            "scene_aura",
            "edge_echo",
            "ambient_wash",
        ),
        _integer("motion_strength_percent", 75, 0, 100, 5),
        _integer("motion_trail_ms", 750, 250, 1_500, 50),
        _integer("continuation_delay_ms", 0, 0, 500, 10),
        _integer("motion_viscosity_percent", 60, 0, 100, 5),
        _integer("motion_colour_persistence_percent", 65, 0, 100, 5),
        _integer("ambient_coverage_percent", 100, 0, 100, 5),
        _integer("ambient_fade_percent", 20, 0, 100, 5),
        _integer("scene_change_protection_ms", 250, 0, 500, 25),
    ]


def _ha_controls() -> list[dict[str, Any]]:
    return [
        _control("enabled", True, "boolean"),
        _select(
            "position",
            "left",
            "top_left",
            "top",
            "top_right",
            "left",
            "centre",
            "right",
            "bottom_left",
            "bottom",
            "bottom_right",
            "ambient",
        ),
        _integer("minimum_brightness_percent", 10, 0, 100, 5),
        _integer("maximum_brightness_percent", 100, 0, 100, 5),
    ]


def _fixtures() -> list[dict[str, Any]]:
    return [
        {
            "fixture_uuid": WLED_FIXTURE_ID,
            "fixture_type": "wled",
            "name": "TV backlight",
            "enabled": True,
            "available": True,
            "controls": _wled_controls(),
        },
        {
            "fixture_uuid": HA_FIXTURE_ID,
            "fixture_type": "home_assistant_light",
            "name": "Living room lamp",
            "enabled": True,
            "available": True,
            "controls": _ha_controls(),
        },
    ]


def _configuration() -> list[dict[str, Any]]:
    return [
        {
            "key": "home_assistant_ambience",
            "name": "Home Assistant Ambience",
            "enabled": True,
            "available": True,
            "apply_behavior": "next_capture",
        },
        {
            "key": "detect_black_bars",
            "name": "Detect Black Bars",
            "enabled": True,
            "available": True,
            "apply_behavior": "immediate",
        },
        {
            "key": "capture_indicator_exclusion",
            "name": "Ignore Screen Capture Indicator",
            "enabled": True,
            "available": True,
            "apply_behavior": "immediate",
        },
        {
            "key": "performance_diagnostics",
            "name": "Performance Diagnostics",
            "enabled": False,
            "available": True,
            "apply_behavior": "immediate",
        },
    ]


@dataclass(slots=True)
class FakeSceneGlowServer:
    """Stateful fake covering the alpha release's vertical protocol slice."""

    installation_id: str = INSTALLATION_ID
    name: str = "Living Room"
    app_version: str = "1.0.0-dev"
    platform: str = "android_tv"
    protocol_version: int = 1
    pairing: bool = True
    pairing_code: str = PAIRING_CODE
    sequence: int = 0
    requested_running: bool = False
    capture_state: str = "stopped"
    error_category: str | None = None
    revision: int = 7
    capture_pause_enabled: bool = True
    fixtures_enabled: bool = True
    configuration_enabled: bool = True
    ha_light_broker_enabled: bool = True
    amazon_build: bool = False
    server_fingerprint: str = field(init=False)
    clients: dict[str, str] = field(default_factory=dict)
    sockets: set[web.WebSocketResponse] = field(default_factory=set)
    fixtures: list[dict[str, Any]] = field(default_factory=_fixtures)
    configuration: list[dict[str, Any]] = field(default_factory=_configuration)
    invalid_configuration_keys: set[str] = field(default_factory=set)
    last_raw_path: str | None = None
    service_calls: list[str] = field(default_factory=list)
    diagnostics_output_fps: float = 29.8
    diagnostics_processing_ms: float = 4.2
    diagnostics_capture_resolution: str = "320x180"

    def __post_init__(self) -> None:
        """Validate test identity and initialize deterministic fingerprint."""
        UUID(self.installation_id)
        digest = hashlib.sha256(self.installation_id.encode()).hexdigest()
        self.server_fingerprint = f"sha256:{digest}"
        if self.amazon_build:
            indicator = next(
                item
                for item in self.configuration
                if item["key"] == "capture_indicator_exclusion"
            )
            indicator["enabled"] = False
            indicator["available"] = False

    @property
    def server_identity(self) -> str:
        """Return the canonical fingerprint using the persisted-entry terminology."""
        return self.server_fingerprint

    def create_app(self) -> web.Application:
        """Create an aiohttp application without starting a socket."""
        app = web.Application()
        app.add_routes(
            [
                web.get("/api/v1/info", self.handle_info),
                web.post("/api/v1/pair", self.handle_pair),
                web.post("/api/v1/unpair", self.handle_unpair),
                web.get("/api/v1/capabilities", self.handle_capabilities),
                web.get("/api/v1/fixtures", self.handle_fixtures),
                web.patch("/api/v1/fixtures/{fixture_uuid}", self.handle_fixture_patch),
                web.get("/api/v1/config", self.handle_configuration),
                web.patch("/api/v1/config/{key}", self.handle_configuration_patch),
                web.get("/api/v1/state", self.handle_state),
                web.post("/api/v1/service/start", self.handle_start),
                web.post("/api/v1/service/stop", self.handle_stop),
                web.post("/api/v1/service/pause", self.handle_pause),
                web.post("/api/v1/service/resume", self.handle_resume),
                web.get("/api/v1/events", self.handle_events),
                web.post("/dev/capture/grant", self.handle_grant),
                web.post("/dev/auth/revoke", self.handle_revoke),
            ]
        )
        return app

    def info_payload(self) -> dict[str, Any]:
        """Return the protocol identity document."""
        return {
            "installation_id": self.installation_id,
            "name": self.name,
            "app_version": self.app_version,
            "platform": self.platform,
            "api_min": self.protocol_version,
            "api_max": self.protocol_version,
            "pairing": self.pairing,
        }

    def state_payload(self) -> dict[str, Any]:
        """Return the authoritative service state document."""
        performance_diagnostics = next(
            item
            for item in self.configuration
            if item["key"] == "performance_diagnostics"
        )
        return {
            "requested_running": self.requested_running,
            "capture_state": self.capture_state,
            **(
                {"error_category": self.error_category}
                if self.error_category is not None
                else {}
            ),
            **(
                {
                    "diagnostics": {
                        "output_fps": self.diagnostics_output_fps,
                        "processing_ms": self.diagnostics_processing_ms,
                        "capture_resolution": self.diagnostics_capture_resolution,
                    }
                }
                if self.capture_state == "running"
                and performance_diagnostics["enabled"]
                else {}
            ),
        }

    def _authorized(self, request: web.Request) -> bool:
        authorization = request.headers.get("Authorization", "")
        credential = authorization.removeprefix("Bearer ")
        return credential in self.clients.values()

    def _require_auth(self, request: web.Request) -> web.Response | None:
        if self._authorized(request):
            return None
        return web.json_response(
            {
                "error": {
                    "code": "authentication_required",
                    "message": "A valid credential is required.",
                }
            },
            status=401,
        )

    async def handle_info(self, request: web.Request) -> web.Response:
        """Serve public identity, or validate auth when supplied."""
        if request.headers.get("Authorization") and not self._authorized(request):
            return self._require_auth(request)
        return web.json_response(self.info_payload())

    async def handle_pair(self, request: web.Request) -> web.Response:
        """Issue one fake client credential for the current short-lived code."""
        payload = await request.json()
        if not self.pairing:
            return web.json_response(
                {
                    "error": {
                        "code": "pairing_closed",
                        "message": "Pairing is not active.",
                    }
                },
                status=409,
            )
        if payload.get("server_fingerprint") != self.server_fingerprint:
            return web.json_response(
                {
                    "error": {
                        "code": "server_identity_mismatch",
                        "message": "The confirmed server identity does not match.",
                    }
                },
                status=401,
            )
        if payload.get("code") != self.pairing_code:
            return web.json_response(
                {
                    "error": {
                        "code": "invalid_pairing_code",
                        "message": "The pairing code is invalid.",
                    }
                },
                status=401,
            )
        self.clients[CLIENT_ID] = CLIENT_CREDENTIAL
        return web.json_response(
            {
                "client_id": CLIENT_ID,
                "client_name": payload["client_name"],
                "credential": CLIENT_CREDENTIAL,
                "server_fingerprint": self.server_fingerprint,
                "api_version": self.protocol_version,
            },
            status=201,
        )

    async def handle_unpair(self, request: web.Request) -> web.Response:
        """Revoke the calling client."""
        if (response := self._require_auth(request)) is not None:
            return response
        self.clients.clear()
        return web.json_response({"paired": False})

    async def handle_capabilities(self, request: web.Request) -> web.Response:
        """Advertise authenticated optional controls."""
        if (response := self._require_auth(request)) is not None:
            return response
        return web.json_response(
            {
                "service_control": True,
                "capture_pause": self.capture_pause_enabled,
                "fixtures": self.fixtures_enabled,
                "configuration": self.configuration_enabled,
                "ha_light_broker": self.ha_light_broker_enabled,
            }
        )

    def fixtures_payload(self) -> dict[str, Any]:
        """Return the complete authoritative fixture collection."""
        return {"revision": self.revision, "fixtures": self.fixtures}

    def configuration_payload(self) -> dict[str, Any]:
        """Return the complete authoritative configuration collection."""
        return {"revision": self.revision, "switches": self.configuration}

    async def handle_fixtures(self, request: web.Request) -> web.Response:
        """Return all configured WLED and HA-backed fixtures."""
        if (response := self._require_auth(request)) is not None:
            return response
        return web.json_response(self.fixtures_payload())

    async def handle_configuration(self, request: web.Request) -> web.Response:
        """Return all application configuration switches."""
        if (response := self._require_auth(request)) is not None:
            return response
        return web.json_response(self.configuration_payload())

    async def _mutation_or_error(
        self, request: web.Request
    ) -> tuple[int, bool] | web.Response:
        try:
            payload = await request.json()
        except Exception:
            return self._control_error(400, "invalid_json", "Invalid JSON body.")
        if not isinstance(payload, dict) or set(payload) != {
            "expected_revision",
            "enabled",
        }:
            return self._control_error(
                400,
                "invalid_request",
                "expected_revision and enabled are required.",
            )
        revision = payload["expected_revision"]
        enabled = payload["enabled"]
        if (
            not isinstance(revision, int)
            or isinstance(revision, bool)
            or revision < 0
            or not isinstance(enabled, bool)
        ):
            return self._control_error(400, "invalid_request", "Invalid mutation.")
        if revision != self.revision:
            return web.json_response(
                {
                    "error": {
                        "code": "revision_conflict",
                        "message": "The control snapshot has changed.",
                    },
                    "current_revision": self.revision,
                },
                status=409,
            )
        return revision, enabled

    async def _fixture_mutation_or_error(
        self, request: web.Request
    ) -> dict[str, bool | str | int | float] | web.Response:
        """Parse all three fixture PATCH forms and check the shared revision."""
        try:
            payload = await request.json()
        except Exception:
            return self._control_error(400, "invalid_json", "Invalid JSON body.")
        if not isinstance(payload, dict):
            return self._control_error(400, "invalid_request", "Invalid mutation.")
        revision = payload.get("expected_revision")
        if not isinstance(revision, int) or isinstance(revision, bool) or revision < 0:
            return self._control_error(400, "invalid_request", "Invalid revision.")
        if revision != self.revision:
            return web.json_response(
                {
                    "error": {
                        "code": "revision_conflict",
                        "message": "The control snapshot has changed.",
                    },
                    "current_revision": self.revision,
                },
                status=409,
            )
        keys = set(payload)
        if keys == {"expected_revision", "enabled"}:
            values: Any = {"enabled": payload["enabled"]}
        elif keys == {"expected_revision", "key", "value"}:
            key = payload["key"]
            if not isinstance(key, str) or not key:
                return self._control_error(400, "invalid_request", "Invalid key.")
            values = {key: payload["value"]}
        elif keys == {"expected_revision", "values"}:
            values = payload["values"]
            if not isinstance(values, dict) or not values:
                return self._control_error(
                    400, "invalid_request", "values must be a non-empty object."
                )
        else:
            return self._control_error(400, "invalid_request", "Invalid mutation form.")
        if any(
            not isinstance(key, str)
            or not key
            or isinstance(value, (dict, list))
            or value is None
            for key, value in values.items()
        ):
            return self._control_error(400, "invalid_request", "Invalid values.")
        return values

    @staticmethod
    def _fixture_value_valid(control: dict[str, Any], value: Any) -> bool:
        """Validate a primitive against advertised control metadata."""
        control_type = control["type"]
        if control_type == "boolean":
            return isinstance(value, bool)
        if control_type == "text":
            return isinstance(value, str) and len(value) <= control["maximum_length"]
        if control_type == "select":
            return isinstance(value, str) and value in control["options"]
        if control_type == "integer":
            if not isinstance(value, int) or isinstance(value, bool):
                return False
        elif control_type == "number":
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                return False
        else:
            return False
        if (
            not math.isfinite(value)
            or not control["minimum"] <= value <= control["maximum"]
        ):
            return False
        steps = (value - control["minimum"]) / control["step"]
        return math.isclose(steps, round(steps), abs_tol=0.000_001)

    @staticmethod
    def _control_error(status: int, code: str, message: str) -> web.Response:
        return web.json_response(
            {"error": {"code": code, "message": message}}, status=status
        )

    async def handle_fixture_patch(self, request: web.Request) -> web.Response:
        """Update one fixture using the shared settings revision."""
        self.last_raw_path = request.raw_path
        if (response := self._require_auth(request)) is not None:
            return response
        mutation = await self._fixture_mutation_or_error(request)
        if isinstance(mutation, web.Response):
            return mutation
        fixture_uuid = request.match_info["fixture_uuid"]
        fixture = next(
            (item for item in self.fixtures if item["fixture_uuid"] == fixture_uuid),
            None,
        )
        if fixture is None:
            return self._control_error(404, "control_not_found", "Unknown fixture.")
        controls = {control["key"]: control for control in fixture["controls"]}
        unknown = next((key for key in mutation if key not in controls), None)
        if unknown is not None:
            return self._control_error(404, "control_not_found", "Unknown control.")
        if any(
            controls[key]["read_only"] or not controls[key]["available"]
            for key in mutation
        ):
            return self._control_error(
                409, "control_unavailable", "Control is unavailable."
            )
        if any(
            not self._fixture_value_valid(controls[key], value)
            for key, value in mutation.items()
        ):
            return self._control_error(
                422, "invalid_configuration", "Fixture configuration is invalid."
            )
        candidate = {
            key: mutation.get(key, control["value"])
            for key, control in controls.items()
        }
        if (
            candidate.get("first_led", 0) + candidate.get("led_count", 0) > 65_536
            or (
                candidate.get("fixture_layout") in {"screen_perimeter", "rectangle"}
                and sum(
                    candidate[key]
                    for key in ("left_leds", "top_leds", "right_leds", "bottom_leds")
                )
                != candidate["led_count"]
            )
            or candidate.get("minimum_brightness_percent", 0)
            > candidate.get("maximum_brightness_percent", 100)
        ):
            return self._control_error(
                422, "invalid_configuration", "Fixture configuration is invalid."
            )
        for key, value in mutation.items():
            controls[key]["value"] = value
        fixture["enabled"] = controls["enabled"]["value"]
        self.revision += 1
        await self._control_changed("fixture_changed", fixture_uuid)
        return web.json_response(self.fixtures_payload())

    async def handle_configuration_patch(self, request: web.Request) -> web.Response:
        """Update one application switch using the shared settings revision."""
        self.last_raw_path = request.raw_path
        if (response := self._require_auth(request)) is not None:
            return response
        mutation = await self._mutation_or_error(request)
        if isinstance(mutation, web.Response):
            return mutation
        key = request.match_info["key"]
        control = next(
            (item for item in self.configuration if item["key"] == key), None
        )
        if control is None:
            return self._control_error(404, "control_not_found", "Unknown control.")
        if not control["available"]:
            return self._control_error(
                409, "control_unavailable", "Control is unavailable."
            )
        if key in self.invalid_configuration_keys:
            return self._control_error(
                422, "invalid_configuration", "Configuration is invalid."
            )
        control["enabled"] = mutation[1]
        self.revision += 1
        await self._control_changed("configuration_changed", "*")
        if key == "performance_diagnostics" and self.capture_state == "running":
            await self._changed()
        return web.json_response(self.configuration_payload())

    async def handle_state(self, request: web.Request) -> web.Response:
        """Return the current service state."""
        if (response := self._require_auth(request)) is not None:
            return response
        return web.json_response(self.state_payload())

    async def handle_start(self, request: web.Request) -> web.Response:
        """Model Android consent instead of pretending remote start bypasses it."""
        if (response := self._require_auth(request)) is not None:
            return response
        self.service_calls.append("start")
        self.requested_running = True
        self.capture_state = "awaiting_capture_permission"
        self.error_category = None
        await self._changed()
        return web.json_response(self.state_payload(), status=202)

    async def handle_stop(self, request: web.Request) -> web.Response:
        """Stop capture and clear the requested target."""
        if (response := self._require_auth(request)) is not None:
            return response
        self.service_calls.append("stop")
        self.requested_running = False
        self.capture_state = "stopped"
        self.error_category = None
        await self._changed()
        return web.json_response(self.state_payload(), status=202)

    async def handle_pause(self, request: web.Request) -> web.Response:
        """Pause processing without changing the requested-running target."""
        if (response := self._require_auth(request)) is not None:
            return response
        self.service_calls.append("pause")
        if self.capture_state == "running":
            self.requested_running = True
            self.capture_state = "paused"
            self.error_category = None
            await self._changed()
        return web.json_response(self.state_payload(), status=202)

    async def handle_resume(self, request: web.Request) -> web.Response:
        """Resume a paused capture without starting a new permission flow."""
        if (response := self._require_auth(request)) is not None:
            return response
        self.service_calls.append("resume")
        if self.capture_state == "paused":
            self.requested_running = True
            self.capture_state = "running"
            self.error_category = None
            await self._changed()
        return web.json_response(self.state_payload(), status=202)

    async def handle_grant(self, request: web.Request) -> web.Response:
        """Development-only endpoint simulating TV consent."""
        self.requested_running = True
        self.capture_state = "running"
        self.error_category = None
        await self._changed()
        return web.json_response(self.state_payload())

    async def handle_revoke(self, request: web.Request) -> web.Response:
        """Development-only endpoint simulating credential revocation."""
        self.clients.clear()
        for socket in tuple(self.sockets):
            await socket.close(code=4001, message=b"credential revoked")
        return web.json_response({"ok": True})

    async def handle_events(self, request: web.Request) -> web.StreamResponse:
        """Keep an authenticated event channel open."""
        if (response := self._require_auth(request)) is not None:
            return response
        socket = web.WebSocketResponse(heartbeat=30)
        await socket.prepare(request)
        self.sockets.add(socket)
        await socket.send_json(
            {
                "type": "subscribed",
                "api_version": self.protocol_version,
                "stream_epoch": STREAM_EPOCH,
                "sequence": self.sequence,
                "state": self.state_payload(),
            }
        )
        try:
            async for _message in socket:
                pass
        finally:
            self.sockets.discard(socket)
        return socket

    async def _changed(self) -> None:
        """Increment revision/sequence and emit a complete service-state event."""
        self.sequence += 1
        event = {
            "type": "service_state_changed",
            "api_version": self.protocol_version,
            "stream_epoch": STREAM_EPOCH,
            "sequence": self.sequence,
            "state": self.state_payload(),
        }
        for socket in tuple(self.sockets):
            await socket.send_json(event)

    async def _control_changed(self, event_type: str, identifier: str) -> None:
        """Emit a fixture/configuration event after a settings save."""
        self.sequence += 1
        event = {
            "type": event_type,
            "api_version": self.protocol_version,
            "stream_epoch": STREAM_EPOCH,
            "sequence": self.sequence,
            "revision": self.revision,
        }
        if event_type == "fixture_changed":
            event["fixture_uuid"] = identifier
        else:
            event["key"] = identifier
        for socket in tuple(self.sockets):
            await socket.send_json(event)
