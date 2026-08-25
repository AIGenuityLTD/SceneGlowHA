"""Config-entry runtime setup tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant.components.button import DOMAIN as BUTTON_DOMAIN
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sceneglow import async_setup_entry
from custom_components.sceneglow.api import SceneGlowCannotConnect
from custom_components.sceneglow.const import (
    CONF_CLIENT_CREDENTIAL,
    CONF_CLIENT_ID,
    CONF_INSTALLATION_ID,
    CONF_SERVER_IDENTITY,
    CONF_USE_TLS,
    DOMAIN,
)
from custom_components.sceneglow.models import (
    SceneGlowCapabilities,
    SceneGlowInfo,
)
from tests.fake_sceneglow import CLIENT_CREDENTIAL, CLIENT_ID, FakeSceneGlowServer


async def test_setup_fetches_authenticated_server_capabilities(
    hass: HomeAssistant,
) -> None:
    """Runtime capability gating uses the app response rather than local defaults."""
    fake = FakeSceneGlowServer()
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=fake.installation_id,
        data={
            CONF_HOST: "192.0.2.10",
            CONF_PORT: 47_990,
            CONF_USE_TLS: True,
            CONF_SERVER_IDENTITY: fake.server_fingerprint,
            CONF_INSTALLATION_ID: fake.installation_id,
            CONF_CLIENT_ID: CLIENT_ID,
            CONF_CLIENT_CREDENTIAL: CLIENT_CREDENTIAL,
        },
    )
    entry.add_to_hass(hass)
    client = Mock()
    client.async_get_info = AsyncMock(
        return_value=SceneGlowInfo.from_dict(fake.info_payload())
    )
    capabilities = SceneGlowCapabilities(
        service_control=True,
        capture_pause=True,
        fixtures=True,
        configuration=True,
        ha_light_broker=True,
    )
    client.async_get_capabilities = AsyncMock(return_value=capabilities)
    coordinator = Mock()
    coordinator.async_start = AsyncMock()

    with (
        patch("custom_components.sceneglow._client_from_entry", return_value=client),
        patch(
            "custom_components.sceneglow.SceneGlowCoordinator",
            return_value=coordinator,
        ) as coordinator_class,
        patch.object(
            hass.config_entries,
            "async_forward_entry_setups",
            new=AsyncMock(),
        ),
    ):
        assert await async_setup_entry(hass, entry) is True

    client.async_get_info.assert_awaited_once_with(authenticated=True)
    client.async_get_capabilities.assert_awaited_once()
    coordinator_class.assert_called_once_with(hass, entry, client, capabilities)
    assert entry.runtime_data.capabilities is capabilities


async def test_offline_setup_still_removes_obsolete_refresh_entity(
    hass: HomeAssistant,
) -> None:
    """Registry migrations run before a device must be reachable."""
    fake = FakeSceneGlowServer()
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=fake.installation_id,
        data={
            CONF_HOST: "192.0.2.10",
            CONF_PORT: 47_990,
            CONF_USE_TLS: True,
            CONF_SERVER_IDENTITY: fake.server_fingerprint,
            CONF_INSTALLATION_ID: fake.installation_id,
            CONF_CLIENT_ID: CLIENT_ID,
            CONF_CLIENT_CREDENTIAL: CLIENT_CREDENTIAL,
        },
    )
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    refresh = registry.async_get_or_create(
        BUTTON_DOMAIN,
        DOMAIN,
        f"{fake.installation_id}_refresh",
        config_entry=entry,
    )
    client = Mock()
    client.async_get_info = AsyncMock(side_effect=SceneGlowCannotConnect("offline"))

    with (
        patch("custom_components.sceneglow._client_from_entry", return_value=client),
        pytest.raises(ConfigEntryNotReady),
    ):
        await async_setup_entry(hass, entry)

    assert registry.async_get(refresh.entity_id) is None
