"""SceneGlow Home Assistant integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryError,
    ConfigEntryNotReady,
)
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    SceneGlowApiClient,
    SceneGlowApiError,
    SceneGlowAuthenticationError,
    SceneGlowCannotConnect,
    SceneGlowEndpoint,
    SceneGlowIdentityMismatch,
    SceneGlowProtocolError,
)
from .const import (
    CONF_CLIENT_CREDENTIAL,
    CONF_CLIENT_ID,
    CONF_INSTALLATION_ID,
    CONF_SERVER_IDENTITY,
    CONF_USE_TLS,
    DOMAIN,
    MANUFACTURER,
    PLATFORMS,
)
from .coordinator import SceneGlowCoordinator
from .models import SceneGlowCapabilities, SceneGlowInfo

_LOGGER = logging.getLogger(__name__)

_PERFORMANCE_SENSOR_SUFFIXES = (
    "_output_fps",
    "_processing_time",
    "_capture_resolution",
)


@dataclass(slots=True)
class SceneGlowRuntimeData:
    """Non-persisted objects owned by one SceneGlow config entry."""

    client: SceneGlowApiClient
    coordinator: SceneGlowCoordinator
    info: SceneGlowInfo
    capabilities: SceneGlowCapabilities


type SceneGlowConfigEntry = ConfigEntry[SceneGlowRuntimeData]


def _client_from_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> SceneGlowApiClient:
    """Build a client from persisted connection and authentication data."""
    endpoint = SceneGlowEndpoint(
        host=entry.data[CONF_HOST],
        port=entry.data[CONF_PORT],
        use_tls=entry.data.get(CONF_USE_TLS, True),
        server_identity=entry.data[CONF_SERVER_IDENTITY],
    )
    return SceneGlowApiClient(
        async_get_clientsession(hass),
        endpoint,
        client_id=entry.data[CONF_CLIENT_ID],
        client_credential=entry.data[CONF_CLIENT_CREDENTIAL],
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SceneGlowConfigEntry,
) -> bool:
    """Set up SceneGlow from a config entry."""
    _migrate_registry_metadata(hass, entry)
    client = _client_from_entry(hass, entry)
    try:
        info = await client.async_get_info(authenticated=True)
        if info.installation_id != entry.data[CONF_INSTALLATION_ID]:
            raise SceneGlowIdentityMismatch(
                "SceneGlow installation UUID differs from the configured installation"
            )
        capabilities = await client.async_get_capabilities()
    except SceneGlowAuthenticationError as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except (SceneGlowIdentityMismatch, SceneGlowProtocolError) as err:
        raise ConfigEntryError(str(err)) from err
    except (SceneGlowCannotConnect, SceneGlowApiError) as err:
        raise ConfigEntryNotReady(str(err)) from err

    coordinator = SceneGlowCoordinator(hass, entry, client, capabilities)
    try:
        await coordinator.async_start()
    except SceneGlowAuthenticationError as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except SceneGlowApiError as err:
        raise ConfigEntryNotReady(str(err)) from err

    entry.runtime_data = SceneGlowRuntimeData(
        client=client,
        coordinator=coordinator,
        info=info,
        capabilities=capabilities,
    )
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


def _migrate_registry_metadata(
    hass: HomeAssistant,
    entry: SceneGlowConfigEntry,
) -> None:
    """Apply integration-owned metadata to registry entries from older builds."""
    entity_registry = er.async_get(hass)
    for entity in er.async_entries_for_config_entry(entity_registry, entry.entry_id):
        if entity.platform == DOMAIN and entity.unique_id.endswith("_refresh"):
            entity_registry.async_remove(entity.entity_id)
            continue
        if (
            entity.platform == DOMAIN
            and entity.unique_id.endswith("_config_performance_diagnostics")
            and entity.entity_category is not EntityCategory.DIAGNOSTIC
        ):
            entity_registry.async_update_entity(
                entity.entity_id,
                entity_category=EntityCategory.DIAGNOSTIC,
            )
        if (
            entity.platform == DOMAIN
            and entity.unique_id.endswith(_PERFORMANCE_SENSOR_SUFFIXES)
            and entity.disabled_by == er.RegistryEntryDisabler.INTEGRATION
        ):
            entity_registry.async_update_entity(
                entity.entity_id,
                disabled_by=None,
            )

    device_registry = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(device_registry, entry.entry_id):
        if (
            any(domain == DOMAIN for domain, _identifier in device.identifiers)
            and device.manufacturer != MANUFACTURER
        ):
            device_registry.async_update_device(
                device.id,
                manufacturer=MANUFACTURER,
            )


async def async_unload_entry(
    hass: HomeAssistant,
    entry: SceneGlowConfigEntry,
) -> bool:
    """Unload platforms and stop entry-owned tasks."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.coordinator.async_stop()
    return unload_ok


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Best-effort server-side credential revocation on entry removal."""
    try:
        await _client_from_entry(hass, entry).async_unpair()
    except (SceneGlowApiError, KeyError):
        _LOGGER.info(
            "Could not notify SceneGlow while removing %s; revoke the client on the TV",
            entry.title,
        )


async def _async_update_listener(
    hass: HomeAssistant,
    entry: SceneGlowConfigEntry,
) -> None:
    """Reload after config-entry connection data changes."""
    await hass.config_entries.async_reload(entry.entry_id)
