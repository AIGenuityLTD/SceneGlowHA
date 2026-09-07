"""Async client for the SceneGlow LAN control protocol v1."""

from __future__ import annotations

import json
import ssl
from asyncio import open_connection, timeout
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass, replace
from hashlib import sha256
from typing import Any, Final
from urllib.parse import quote

from aiohttp import (
    ClientConnectionError,
    ClientResponse,
    ClientSession,
    ClientWebSocketResponse,
    ClientWSTimeout,
    Fingerprint,
    ServerFingerprintMismatch,
    WSMsgType,
    WSServerHandshakeError,
)

from .const import DEFAULT_REQUEST_TIMEOUT, PROTOCOL_VERSION
from .models import (
    ModelError,
    PairingResult,
    SceneGlowCapabilities,
    SceneGlowConfigurationCollection,
    SceneGlowEvent,
    SceneGlowFixtureCollection,
    SceneGlowInfo,
    SceneGlowState,
)

API_PREFIX: Final = "/api/v1"


class SceneGlowApiError(Exception):
    """Base SceneGlow client error."""


class SceneGlowCannotConnect(SceneGlowApiError):
    """SceneGlow could not be reached."""


class SceneGlowAuthenticationError(SceneGlowApiError):
    """SceneGlow rejected the client credential."""


class SceneGlowPairingError(SceneGlowApiError):
    """SceneGlow rejected or could not complete pairing."""


class SceneGlowProtocolError(SceneGlowApiError):
    """SceneGlow returned an invalid or incompatible response."""


class SceneGlowIdentityMismatch(SceneGlowApiError):
    """The endpoint did not present the pinned SceneGlow identity."""


class SceneGlowConflictError(SceneGlowApiError):
    """A write used an obsolete remote revision."""

    def __init__(self, message: str, *, current_revision: int | None = None) -> None:
        """Initialize an error while retaining the server's current revision."""
        super().__init__(message)
        self.current_revision = current_revision


class SceneGlowControlUnavailableError(SceneGlowApiError):
    """A known control cannot be changed on this app variant."""


class SceneGlowInvalidConfigurationError(SceneGlowApiError):
    """A control value would make the stored configuration invalid."""


class SceneGlowControlNotFoundError(SceneGlowApiError):
    """A requested fixture or configuration control no longer exists."""


@dataclass(frozen=True, slots=True)
class SceneGlowEndpoint:
    """Connection details for one SceneGlow server."""

    host: str
    port: int
    use_tls: bool = True
    server_identity: str | None = None

    @property
    def base_url(self) -> str:
        """Return the HTTP origin."""
        scheme = "https" if self.use_tls else "http"
        host = f"[{self.host}]" if ":" in self.host else self.host
        return f"{scheme}://{host}:{self.port}"

    def with_identity(self, server_identity: str) -> SceneGlowEndpoint:
        """Return an endpoint pinned to a SHA-256 certificate fingerprint."""
        identity = server_identity.lower()
        if not identity.startswith("sha256:"):
            identity = f"sha256:{identity.replace(':', '')}"
        return replace(self, server_identity=identity)


class SceneGlowApiClient:
    """One independently testable SceneGlow protocol client."""

    def __init__(
        self,
        session: ClientSession,
        endpoint: SceneGlowEndpoint,
        *,
        client_id: str | None = None,
        client_credential: str | None = None,
        request_timeout: float = DEFAULT_REQUEST_TIMEOUT,
    ) -> None:
        """Initialize a client using a caller-owned session."""
        self._session = session
        self.endpoint = endpoint
        self.client_id = client_id
        self.client_credential = client_credential
        self._request_timeout = request_timeout

    @property
    def authenticated(self) -> bool:
        """Return whether complete credentials are configured."""
        return bool(self.client_id and self.client_credential)

    def _headers(self, *, authenticated: bool) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "X-SceneGlow-Protocol": str(PROTOCOL_VERSION),
        }
        if authenticated:
            if not self.authenticated:
                msg = "Authenticated request requires SceneGlow credentials"
                raise SceneGlowAuthenticationError(msg)
            headers["Authorization"] = f"Bearer {self.client_credential}"
        return headers

    def _ssl_parameter(self) -> bool | Fingerprint:
        if not self.endpoint.use_tls:
            return False
        if self.endpoint.server_identity is None:
            return True
        try:
            digest = bytes.fromhex(
                self.endpoint.server_identity.removeprefix("sha256:").replace(":", "")
            )
        except ValueError as err:
            msg = "Stored SceneGlow server identity is not hexadecimal"
            raise SceneGlowIdentityMismatch(msg) from err
        if len(digest) != 32:
            msg = "Stored SceneGlow server identity is not a SHA-256 fingerprint"
            raise SceneGlowIdentityMismatch(msg)
        return Fingerprint(digest)

    async def async_discover_server_identity(self) -> str:
        """Pin the certificate presented by an unpaired SceneGlow endpoint.

        The returned fingerprint is sent back with the TV-displayed one-time code,
        which binds first contact to the certificate identity confirmed by SceneGlow.
        """
        if not self.endpoint.use_tls:
            if self.endpoint.server_identity is None:
                raise SceneGlowIdentityMismatch(
                    "Plain HTTP test endpoints require an explicit server identity"
                )
            return self.endpoint.server_identity
        if self.endpoint.server_identity is not None:
            return self.endpoint.server_identity

        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        writer = None
        certificate: bytes | None = None
        try:
            async with timeout(self._request_timeout):
                _reader, writer = await open_connection(
                    self.endpoint.host,
                    self.endpoint.port,
                    ssl=context,
                    server_hostname=self.endpoint.host,
                )
                ssl_object = writer.get_extra_info("ssl_object")
                certificate = (
                    ssl_object.getpeercert(binary_form=True) if ssl_object else None
                )
                if not certificate:
                    raise SceneGlowIdentityMismatch(
                        "SceneGlow did not present a TLS certificate"
                    )
        except TimeoutError as err:
            raise SceneGlowCannotConnect(
                "Timed out while connecting to SceneGlow"
            ) from err
        except (OSError, ssl.SSLError) as err:
            raise SceneGlowCannotConnect("Could not establish SceneGlow TLS") from err
        finally:
            if writer is not None:
                writer.close()
                with suppress(OSError, TimeoutError):
                    await writer.wait_closed()

        identity = f"sha256:{sha256(certificate).hexdigest()}"
        self.endpoint = self.endpoint.with_identity(identity)
        return identity

    async def async_probe_info(self) -> SceneGlowInfo:
        """Discover and pin TLS identity, then fetch canonical public info."""
        await self.async_discover_server_identity()
        return await self.async_get_info()

    async def _decode_response(self, response: ClientResponse) -> dict[str, Any]:
        try:
            value = await response.json(content_type=None)
        except (json.JSONDecodeError, UnicodeDecodeError) as err:
            msg = "SceneGlow returned invalid JSON"
            raise SceneGlowProtocolError(msg) from err
        if not isinstance(value, dict):
            msg = "SceneGlow response must be a JSON object"
            raise SceneGlowProtocolError(msg)
        return value

    async def _request(
        self,
        method: str,
        path: str,
        *,
        authenticated: bool = True,
        body: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            async with timeout(self._request_timeout):
                response = await self._session.request(
                    method,
                    f"{self.endpoint.base_url}{API_PREFIX}{path}",
                    headers=self._headers(authenticated=authenticated),
                    json=body,
                    ssl=self._ssl_parameter(),
                )
                async with response:
                    payload = await self._decode_response(response)
                    self._raise_for_status(response.status, payload)
                    return payload
        except ServerFingerprintMismatch as err:
            raise SceneGlowIdentityMismatch(
                "SceneGlow TLS certificate does not match the stored identity"
            ) from err
        except TimeoutError as err:
            msg = "Timed out while contacting SceneGlow"
            raise SceneGlowCannotConnect(msg) from err
        except ClientConnectionError as err:
            msg = "Could not connect to SceneGlow"
            raise SceneGlowCannotConnect(msg) from err

    @staticmethod
    def _raise_for_status(status: int, payload: Mapping[str, Any]) -> None:
        if status < 400:
            return
        error = payload.get("error")
        if not isinstance(error, Mapping):
            error = payload
        code = error.get("code", "unknown_error")
        message = error.get("message", "SceneGlow request failed")
        detail = f"{code}: {message}"
        if status in (401, 403):
            if code == "server_identity_mismatch":
                raise SceneGlowIdentityMismatch(detail)
            if code in {
                "invalid_pairing_code",
                "pairing_code_invalid",
                "pairing_disabled",
                "pairing_expired",
            }:
                raise SceneGlowPairingError(detail)
            raise SceneGlowAuthenticationError(detail)
        if status == 429:
            raise SceneGlowPairingError(detail)
        if status == 409 and code == "pairing_closed":
            raise SceneGlowPairingError(detail)
        if status == 409 and code == "control_unavailable":
            raise SceneGlowControlUnavailableError(detail)
        if status in {409, 412} and code == "revision_conflict":
            current_revision = payload.get("current_revision")
            if (
                not isinstance(current_revision, int)
                or isinstance(current_revision, bool)
                or current_revision < 0
            ):
                current_revision = None
            raise SceneGlowConflictError(detail, current_revision=current_revision)
        if status == 404 and code == "control_not_found":
            raise SceneGlowControlNotFoundError(detail)
        if status == 422 and code == "invalid_configuration":
            raise SceneGlowInvalidConfigurationError(detail)
        if status == 409 or status == 412:
            raise SceneGlowConflictError(detail)
        if status == 426 or code == "protocol_incompatible":
            raise SceneGlowProtocolError(detail)
        raise SceneGlowApiError(detail)

    async def async_get_info(self, *, authenticated: bool = False) -> SceneGlowInfo:
        """Fetch installation identity and negotiate v1 compatibility."""
        try:
            info = SceneGlowInfo.from_dict(
                await self._request("GET", "/info", authenticated=authenticated)
            )
        except ModelError as err:
            raise SceneGlowProtocolError("SceneGlow returned invalid info") from err
        if not info.api_min <= PROTOCOL_VERSION <= info.api_max:
            msg = (
                f"SceneGlow protocols {info.api_min}-{info.api_max} are incompatible "
                f"with client protocol {PROTOCOL_VERSION}"
            )
            raise SceneGlowProtocolError(msg)
        return info

    async def async_pair(
        self,
        pairing_code: str,
        *,
        client_name: str,
    ) -> PairingResult:
        """Pair this Home Assistant instance with SceneGlow."""
        server_fingerprint = self.endpoint.server_identity
        if server_fingerprint is None:
            raise SceneGlowIdentityMismatch(
                "Pairing requires the probed SceneGlow certificate fingerprint"
            )
        try:
            result = PairingResult.from_dict(
                await self._request(
                    "POST",
                    "/pair",
                    authenticated=False,
                    body={
                        "code": pairing_code,
                        "client_name": client_name,
                        "server_fingerprint": server_fingerprint,
                    },
                )
            )
        except ModelError as err:
            raise SceneGlowProtocolError(
                "SceneGlow returned invalid pairing data"
            ) from err
        if result.api_version != PROTOCOL_VERSION:
            msg = "SceneGlow paired with an incompatible protocol version"
            raise SceneGlowProtocolError(msg)
        if result.server_fingerprint != server_fingerprint:
            raise SceneGlowIdentityMismatch(
                "Pairing response fingerprint differs from the probed certificate"
            )
        return result

    async def async_get_state(self) -> SceneGlowState:
        """Fetch an authoritative service snapshot."""
        try:
            return SceneGlowState.from_dict(await self._request("GET", "/state"))
        except ModelError as err:
            raise SceneGlowProtocolError("SceneGlow returned invalid state") from err

    async def async_get_capabilities(self) -> SceneGlowCapabilities:
        """Fetch authenticated optional-control capabilities."""
        try:
            return SceneGlowCapabilities.from_dict(
                await self._request("GET", "/capabilities")
            )
        except ModelError as err:
            raise SceneGlowProtocolError(
                "SceneGlow returned invalid capabilities"
            ) from err

    async def async_get_fixtures(self) -> SceneGlowFixtureCollection:
        """Fetch the authoritative fixture collection."""
        try:
            return SceneGlowFixtureCollection.from_dict(
                await self._request("GET", "/fixtures")
            )
        except ModelError as err:
            raise SceneGlowProtocolError("SceneGlow returned invalid fixtures") from err

    async def async_set_fixture_enabled(
        self,
        fixture_uuid: str,
        expected_revision: int,
        enabled: bool,
    ) -> SceneGlowFixtureCollection:
        """Set fixture capture participation using optimistic concurrency."""
        try:
            return SceneGlowFixtureCollection.from_dict(
                await self._request(
                    "PATCH",
                    f"/fixtures/{quote(fixture_uuid, safe='')}",
                    body={
                        "expected_revision": expected_revision,
                        "enabled": enabled,
                    },
                )
            )
        except ModelError as err:
            raise SceneGlowProtocolError("SceneGlow returned invalid fixtures") from err

    async def async_set_fixture_value(
        self,
        fixture_uuid: str,
        expected_revision: int,
        key: str,
        value: bool | str | int | float,
    ) -> SceneGlowFixtureCollection:
        """Set one advertised fixture control."""
        return await self._async_update_fixture(
            fixture_uuid,
            {
                "expected_revision": expected_revision,
                "key": key,
                "value": value,
            },
        )

    async def async_set_fixture_values(
        self,
        fixture_uuid: str,
        expected_revision: int,
        values: Mapping[str, bool | str | int | float],
    ) -> SceneGlowFixtureCollection:
        """Set coupled fixture controls atomically."""
        if not values:
            raise ValueError("Fixture values must not be empty")
        return await self._async_update_fixture(
            fixture_uuid,
            {
                "expected_revision": expected_revision,
                "values": dict(values),
            },
        )

    async def _async_update_fixture(
        self,
        fixture_uuid: str,
        body: Mapping[str, Any],
    ) -> SceneGlowFixtureCollection:
        """PATCH a fixture and parse its complete authoritative collection."""
        try:
            return SceneGlowFixtureCollection.from_dict(
                await self._request(
                    "PATCH",
                    f"/fixtures/{quote(fixture_uuid, safe='')}",
                    body=body,
                )
            )
        except ModelError as err:
            raise SceneGlowProtocolError("SceneGlow returned invalid fixtures") from err

    async def async_get_configuration(self) -> SceneGlowConfigurationCollection:
        """Fetch authoritative application configuration controls."""
        try:
            return SceneGlowConfigurationCollection.from_dict(
                await self._request("GET", "/config")
            )
        except ModelError as err:
            raise SceneGlowProtocolError(
                "SceneGlow returned invalid configuration"
            ) from err

    async def async_set_configuration_enabled(
        self,
        key: str,
        expected_revision: int,
        enabled: bool,
    ) -> SceneGlowConfigurationCollection:
        """Set one application control using optimistic concurrency."""
        try:
            return SceneGlowConfigurationCollection.from_dict(
                await self._request(
                    "PATCH",
                    f"/config/{quote(key, safe='')}",
                    body={
                        "expected_revision": expected_revision,
                        "enabled": enabled,
                    },
                )
            )
        except ModelError as err:
            raise SceneGlowProtocolError(
                "SceneGlow returned invalid configuration"
            ) from err

    async def async_start_service(self) -> SceneGlowState:
        """Request capture startup; platform consent may still be required."""
        try:
            return SceneGlowState.from_dict(
                await self._request("POST", "/service/start", body={})
            )
        except ModelError as err:
            raise SceneGlowProtocolError("SceneGlow returned invalid state") from err

    async def async_stop_service(self) -> SceneGlowState:
        """Request capture shutdown."""
        try:
            return SceneGlowState.from_dict(
                await self._request("POST", "/service/stop", body={})
            )
        except ModelError as err:
            raise SceneGlowProtocolError("SceneGlow returned invalid state") from err

    async def async_pause_service(self) -> SceneGlowState:
        """Pause frame processing while retaining capture permission."""
        try:
            return SceneGlowState.from_dict(
                await self._request("POST", "/service/pause", body={})
            )
        except ModelError as err:
            raise SceneGlowProtocolError("SceneGlow returned invalid state") from err

    async def async_resume_service(self) -> SceneGlowState:
        """Resume frame processing without requesting capture permission again."""
        try:
            return SceneGlowState.from_dict(
                await self._request("POST", "/service/resume", body={})
            )
        except ModelError as err:
            raise SceneGlowProtocolError("SceneGlow returned invalid state") from err

    async def async_unpair(self) -> None:
        """Best-effort removal of this client credential from SceneGlow."""
        await self._request("POST", "/unpair", body={})

    async def _open_websocket(self) -> ClientWebSocketResponse:
        try:
            async with timeout(self._request_timeout):
                return await self._session.ws_connect(
                    f"{self.endpoint.base_url}{API_PREFIX}/events",
                    headers=self._headers(authenticated=True),
                    ssl=self._ssl_parameter(),
                    timeout=ClientWSTimeout(ws_receive=90),
                )
        except TimeoutError as err:
            msg = "Timed out opening the SceneGlow event stream"
            raise SceneGlowCannotConnect(msg) from err
        except ServerFingerprintMismatch as err:
            raise SceneGlowIdentityMismatch(
                "SceneGlow TLS certificate does not match the stored identity"
            ) from err
        except WSServerHandshakeError as err:
            if err.status in {401, 403}:
                msg = "SceneGlow rejected event-stream authentication"
                raise SceneGlowAuthenticationError(msg) from err
            msg = f"SceneGlow rejected the event stream with HTTP {err.status}"
            raise SceneGlowCannotConnect(msg) from err
        except ClientConnectionError as err:
            msg = "Could not open the SceneGlow event stream"
            raise SceneGlowCannotConnect(msg) from err

    async def async_events(
        self,
        broker_handler: (
            Callable[[dict[str, Any]], Awaitable[dict[str, Any]]] | None
        ) = None,
    ) -> AsyncIterator[SceneGlowEvent]:
        """Yield validated events until the socket closes."""
        websocket = await self._open_websocket()
        async with websocket:
            async for message in websocket:
                if message.type is WSMsgType.TEXT:
                    try:
                        value = json.loads(message.data)
                    except json.JSONDecodeError as err:
                        msg = "SceneGlow event is invalid JSON"
                        raise SceneGlowProtocolError(msg) from err
                    if not isinstance(value, dict):
                        msg = "SceneGlow event must be a JSON object"
                        raise SceneGlowProtocolError(msg)
                    message_type = value.get("type")
                    if isinstance(message_type, str) and message_type.startswith(
                        "ha.light."
                    ):
                        response = (
                            await broker_handler(value)
                            if broker_handler is not None
                            else {
                                "type": f"{message_type}.result",
                                "request_id": value.get("request_id", ""),
                                "api_version": PROTOCOL_VERSION,
                                "error": "ha_light_broker_unavailable",
                            }
                        )
                        await websocket.send_json(response)
                        continue
                    try:
                        event = SceneGlowEvent.from_dict(value)
                    except ModelError as err:
                        raise SceneGlowProtocolError(
                            "SceneGlow returned an invalid event"
                        ) from err
                    if event.api_version != PROTOCOL_VERSION:
                        raise SceneGlowProtocolError(
                            "SceneGlow event protocol is incompatible"
                        )
                    yield event
                elif message.type is WSMsgType.ERROR:
                    msg = "SceneGlow event stream failed"
                    raise SceneGlowCannotConnect(msg)
                elif message.type in (WSMsgType.CLOSE, WSMsgType.CLOSED):
                    break
