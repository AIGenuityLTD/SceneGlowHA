"""Config-flow tests for Zeroconf-first, PIN-only onboarding."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import config_validation as cv
from voluptuous_serialize import convert

from custom_components.sceneglow.api import SceneGlowPairingError
from custom_components.sceneglow.config_flow import _pair_schema
from custom_components.sceneglow.const import (
    CONF_CLIENT_CREDENTIAL,
    CONF_INSTALLATION_ID,
    CONF_PAIRING_CODE,
    DEFAULT_PORT,
    DOMAIN,
)
from custom_components.sceneglow.models import PairingResult, SceneGlowInfo
from tests.fake_sceneglow import CLIENT_ID, FakeSceneGlowServer


def _mock_client() -> tuple[AsyncMock, object]:
    fake = FakeSceneGlowServer()
    client = AsyncMock()
    client.async_probe_info.return_value = SceneGlowInfo.from_dict(fake.info_payload())
    client.async_pair.return_value = PairingResult(
        client_id=CLIENT_ID,
        client_name="Home Assistant",
        credential="scene-credential",
        server_fingerprint=fake.server_fingerprint,
        api_version=1,
    )

    def factory(_session, endpoint, **_kwargs):
        client.endpoint = endpoint.with_identity(fake.server_fingerprint)
        return client

    return client, factory


def test_pair_schema_is_frontend_serializable() -> None:
    """The PIN form must serialize for the Home Assistant frontend."""
    convert(_pair_schema(), custom_serializer=cv.custom_serializer)


async def test_zeroconf_discovery_goes_directly_to_pin(
    hass: HomeAssistant,
    enable_custom_integrations,
    mock_async_zeroconf,
    socket_enabled,
) -> None:
    """A discovered installation asks only for its TV PIN."""
    client, factory = _mock_client()
    fake = FakeSceneGlowServer()
    discovery = SimpleNamespace(
        host="127.0.0.1",
        port=DEFAULT_PORT,
        properties={
            "id": fake.installation_id,
            "name": fake.name,
            "api": "1",
            "pairing": "1",
        },
    )
    with patch(
        "custom_components.sceneglow.config_flow.SceneGlowApiClient",
        side_effect=factory,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_ZEROCONF},
            data=discovery,
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "pair"
        assert set(result["data_schema"].schema) == {CONF_PAIRING_CODE}

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_PAIRING_CODE: "123456"}
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_INSTALLATION_ID] == fake.installation_id
    assert result["data"][CONF_HOST] == "127.0.0.1"
    assert result["data"][CONF_CLIENT_CREDENTIAL] == "scene-credential"
    assert result["options"] == {}
    client.async_probe_info.assert_awaited_once()


async def test_manual_fallback_also_uses_pin_only(
    hass: HomeAssistant,
    enable_custom_integrations,
    mock_async_zeroconf,
    socket_enabled,
) -> None:
    """Manual address entry remains available when multicast is unavailable."""
    _client, factory = _mock_client()
    with patch(
        "custom_components.sceneglow.config_flow.SceneGlowApiClient",
        side_effect=factory,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        assert result["step_id"] == "user"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_HOST: "sceneglow.local", CONF_PORT: DEFAULT_PORT},
        )
        assert result["step_id"] == "pair"
        assert set(result["data_schema"].schema) == {CONF_PAIRING_CODE}


async def test_incorrect_pairing_code_stays_in_flow(
    hass: HomeAssistant,
    enable_custom_integrations,
    mock_async_zeroconf,
    socket_enabled,
) -> None:
    """A rejected TV code is shown on its field and stores no config entry."""
    client, factory = _mock_client()
    client.async_pair.side_effect = SceneGlowPairingError("rejected")
    with patch(
        "custom_components.sceneglow.config_flow.SceneGlowApiClient",
        side_effect=factory,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_HOST: "sceneglow.local", CONF_PORT: DEFAULT_PORT},
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_PAIRING_CODE: "000000"}
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_PAIRING_CODE: "invalid_pairing_code"}
    assert not hass.config_entries.async_entries(DOMAIN)


async def test_malformed_pairing_code_is_rejected_before_request(
    hass: HomeAssistant,
    enable_custom_integrations,
    mock_async_zeroconf,
    socket_enabled,
) -> None:
    """Malformed codes stay in the form and are never sent to SceneGlow."""
    client, factory = _mock_client()
    with patch(
        "custom_components.sceneglow.config_flow.SceneGlowApiClient",
        side_effect=factory,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_HOST: "sceneglow.local", CONF_PORT: DEFAULT_PORT},
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_PAIRING_CODE: "12a"}
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_PAIRING_CODE: "invalid_pairing_code"}
    client.async_pair.assert_not_awaited()
