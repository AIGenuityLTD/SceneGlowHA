"""UI configuration flows for SceneGlow."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
from homeassistant.util.network import is_host_valid

from .api import (
    SceneGlowApiClient,
    SceneGlowApiError,
    SceneGlowCannotConnect,
    SceneGlowEndpoint,
    SceneGlowIdentityMismatch,
    SceneGlowPairingError,
    SceneGlowProtocolError,
)
from .const import (
    CONF_CLIENT_CREDENTIAL,
    CONF_CLIENT_ID,
    CONF_INSTALLATION_ID,
    CONF_PAIRING_CODE,
    CONF_PROTOCOL_VERSION,
    CONF_SERVER_IDENTITY,
    CONF_USE_TLS,
    DEFAULT_PORT,
    DOMAIN,
)
from .models import PairingResult, SceneGlowInfo


def _endpoint_schema(host: str | None = None, port: int = DEFAULT_PORT) -> vol.Schema:
    """Build the manual/reconfigure endpoint schema."""
    host_key = (
        vol.Required(CONF_HOST, default=host) if host else vol.Required(CONF_HOST)
    )
    return vol.Schema(
        {
            host_key: str,
            vol.Required(CONF_PORT, default=port): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=65535)
            ),
        }
    )


def _pair_schema() -> vol.Schema:
    """Build the PIN-only pairing form."""
    return vol.Schema({vol.Required(CONF_PAIRING_CODE): str})


def _valid_pairing_code(value: str) -> bool:
    """Return whether a pairing code contains exactly six ASCII digits."""
    return len(value) == 6 and value.isascii() and value.isdigit()


def _discovery_property(value: object) -> str:
    """Normalize Zeroconf TXT values across HA/zeroconf versions."""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return str(value)


class SceneGlowConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle SceneGlow discovery, pairing, reauth and reconfiguration."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize transient flow state."""
        self._endpoint: SceneGlowEndpoint | None = None
        self._info: SceneGlowInfo | None = None

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Handle the advanced manual-address fallback."""
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            if not is_host_valid(host):
                errors[CONF_HOST] = "invalid_host"
            else:
                self._endpoint = SceneGlowEndpoint(
                    host=host,
                    port=user_input[CONF_PORT],
                    use_tls=True,
                )
                error = await self._async_probe()
                if error is None:
                    info = self._require_info()
                    await self.async_set_unique_id(info.installation_id)
                    self._abort_if_unique_id_configured()
                    self.context["title_placeholders"] = {"name": info.name}
                    return await self.async_step_pair()
                errors["base"] = error

        return self.async_show_form(
            step_id="user",
            data_schema=_endpoint_schema(),
            errors=errors,
        )

    async def async_step_zeroconf(
        self,
        discovery_info: ZeroconfServiceInfo,
    ) -> ConfigFlowResult:
        """Handle an untrusted Zeroconf candidate endpoint."""
        properties = {
            _discovery_property(key): _discovery_property(value)
            for key, value in discovery_info.properties.items()
        }
        installation_id = properties.get("id")
        if not installation_id:
            return self.async_abort(reason="invalid_discovery")

        await self.async_set_unique_id(installation_id)
        candidate = SceneGlowEndpoint(
            host=discovery_info.host,
            port=discovery_info.port,
            use_tls=True,
        )

        existing = next(
            (
                entry
                for entry in self._async_current_entries()
                if entry.unique_id == installation_id
            ),
            None,
        )
        if existing is not None:
            await self._async_verified_rediscovery(existing, candidate)
            return self.async_abort(reason="already_configured")

        self._endpoint = candidate
        error = await self._async_probe()
        if error is not None:
            return self.async_abort(reason=error)
        info = self._require_info()
        if info.installation_id != installation_id:
            return self.async_abort(reason="identity_mismatch")
        self.context["title_placeholders"] = {"name": info.name}
        return await self.async_step_pair()

    async def async_step_pair(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Pair using only the short-lived PIN displayed by SceneGlow."""
        info = self._require_info()
        errors: dict[str, str] = {}
        if user_input is not None:
            pairing_code = user_input[CONF_PAIRING_CODE].strip()
            if not _valid_pairing_code(pairing_code):
                errors[CONF_PAIRING_CODE] = "invalid_pairing_code"
            else:
                try:
                    result = await self._async_pair(pairing_code)
                except SceneGlowPairingError:
                    errors[CONF_PAIRING_CODE] = "invalid_pairing_code"
                except SceneGlowCannotConnect:
                    errors["base"] = "cannot_connect"
                except SceneGlowIdentityMismatch:
                    errors["base"] = "identity_mismatch"
                except SceneGlowProtocolError:
                    errors["base"] = "protocol_incompatible"
                except SceneGlowApiError:
                    errors["base"] = "unknown"
                else:
                    return self.async_create_entry(
                        title=info.name,
                        data=self._entry_data(result),
                    )

        return self.async_show_form(
            step_id="pair",
            data_schema=_pair_schema(),
            errors=errors,
            description_placeholders={"name": info.name},
        )

    async def async_step_reauth(
        self,
        entry_data: Mapping[str, Any],
    ) -> ConfigFlowResult:
        """Begin TV-confirmed credential replacement."""
        entry = self._get_reauth_entry()
        self._endpoint = SceneGlowEndpoint(
            host=entry.data[CONF_HOST],
            port=entry.data[CONF_PORT],
            use_tls=entry.data.get(CONF_USE_TLS, True),
            server_identity=entry.data[CONF_SERVER_IDENTITY],
        )
        self._info = SceneGlowInfo(
            installation_id=entry.data[CONF_INSTALLATION_ID],
            name=entry.title,
            app_version="unknown",
            platform="unknown",
            api_min=entry.data[CONF_PROTOCOL_VERSION],
            api_max=entry.data[CONF_PROTOCOL_VERSION],
            pairing=True,
        )
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Collect a fresh short-lived code after pairing is enabled on TV."""
        errors: dict[str, str] = {}
        if user_input is not None:
            pairing_code = user_input[CONF_PAIRING_CODE].strip()
            if not _valid_pairing_code(pairing_code):
                errors[CONF_PAIRING_CODE] = "invalid_pairing_code"
            else:
                try:
                    result = await self._async_pair(pairing_code)
                except SceneGlowPairingError:
                    errors[CONF_PAIRING_CODE] = "invalid_pairing_code"
                except SceneGlowIdentityMismatch:
                    errors["base"] = "identity_mismatch"
                except SceneGlowProtocolError:
                    errors["base"] = "protocol_incompatible"
                except SceneGlowApiError:
                    errors["base"] = "cannot_connect"
                else:
                    await self.async_set_unique_id(self._require_info().installation_id)
                    self._abort_if_unique_id_mismatch()
                    return self.async_update_reload_and_abort(
                        self._get_reauth_entry(),
                        data_updates=self._entry_data(result),
                    )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=_pair_schema(),
            errors=errors,
        )

    async def async_step_reconfigure(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Validate and update required endpoint details."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            endpoint = SceneGlowEndpoint(
                host=user_input[CONF_HOST].strip(),
                port=user_input[CONF_PORT],
                use_tls=entry.data.get(CONF_USE_TLS, True),
                server_identity=entry.data[CONF_SERVER_IDENTITY],
            )
            try:
                info = await self._authenticated_info(entry, endpoint)
                if info.installation_id != entry.unique_id:
                    raise SceneGlowIdentityMismatch
            except SceneGlowIdentityMismatch:
                errors["base"] = "identity_mismatch"
            except SceneGlowProtocolError:
                errors["base"] = "protocol_incompatible"
            except SceneGlowApiError:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(info.installation_id)
                self._abort_if_unique_id_mismatch()
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={
                        CONF_HOST: endpoint.host,
                        CONF_PORT: endpoint.port,
                    },
                )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_endpoint_schema(entry.data[CONF_HOST], entry.data[CONF_PORT]),
            errors=errors,
        )

    async def _async_probe(self) -> str | None:
        """Probe an unpaired candidate and retain its advertised identity."""
        try:
            client = SceneGlowApiClient(
                async_get_clientsession(self.hass), self._require_endpoint()
            )
            self._info = await client.async_probe_info()
            self._endpoint = client.endpoint
        except SceneGlowIdentityMismatch:
            return "identity_mismatch"
        except SceneGlowCannotConnect:
            return "cannot_connect"
        except SceneGlowProtocolError:
            return "protocol_incompatible"
        except SceneGlowApiError:
            return "unknown"
        return None

    async def _async_pair(self, pairing_code: str) -> PairingResult:
        """Pair and enforce identity binding between info and response."""
        endpoint = self._require_endpoint()
        result = await SceneGlowApiClient(
            async_get_clientsession(self.hass), endpoint
        ).async_pair(pairing_code.strip(), client_name="Home Assistant")
        if result.server_identity != endpoint.server_identity:
            raise SceneGlowIdentityMismatch(
                "Pairing response identity differs from the probed installation"
            )
        return result

    def _entry_data(self, result: PairingResult | None) -> dict[str, Any]:
        """Build the minimal persisted connection/authentication record."""
        if result is None:
            raise SceneGlowProtocolError("Pairing result was not retained")
        info = self._require_info()
        endpoint = self._require_endpoint()
        return {
            CONF_INSTALLATION_ID: info.installation_id,
            CONF_HOST: endpoint.host,
            CONF_PORT: endpoint.port,
            CONF_USE_TLS: endpoint.use_tls,
            CONF_CLIENT_ID: result.client_id,
            CONF_CLIENT_CREDENTIAL: result.client_credential,
            CONF_SERVER_IDENTITY: result.server_identity,
            CONF_PROTOCOL_VERSION: result.protocol_version,
        }

    def _require_endpoint(self) -> SceneGlowEndpoint:
        """Return the flow endpoint after its prerequisite step."""
        if self._endpoint is None:
            raise SceneGlowProtocolError("SceneGlow endpoint is not initialized")
        return self._endpoint

    def _require_info(self) -> SceneGlowInfo:
        """Return probed installation info after its prerequisite step."""
        if self._info is None:
            raise SceneGlowProtocolError("SceneGlow installation was not probed")
        return self._info

    async def _authenticated_info(
        self,
        entry: ConfigEntry,
        endpoint: SceneGlowEndpoint,
    ) -> SceneGlowInfo:
        client = SceneGlowApiClient(
            async_get_clientsession(self.hass),
            endpoint,
            client_id=entry.data[CONF_CLIENT_ID],
            client_credential=entry.data[CONF_CLIENT_CREDENTIAL],
        )
        return await client.async_get_info(authenticated=True)

    async def _async_verified_rediscovery(
        self,
        entry: ConfigEntry,
        candidate: SceneGlowEndpoint,
    ) -> None:
        """Only commit a new endpoint after credential and pin verification."""
        candidate = candidate.with_identity(entry.data[CONF_SERVER_IDENTITY])
        try:
            info = await self._authenticated_info(entry, candidate)
        except SceneGlowApiError:
            return
        if info.installation_id != entry.unique_id:
            return
        self.hass.config_entries.async_update_entry(
            entry,
            data={
                **entry.data,
                CONF_HOST: candidate.host,
                CONF_PORT: candidate.port,
                CONF_USE_TLS: candidate.use_tls,
            },
        )
