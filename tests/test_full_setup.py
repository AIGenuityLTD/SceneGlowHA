"""End-to-end config-entry and typed-platform setup tests."""

from __future__ import annotations

from homeassistant.components.button import DOMAIN as BUTTON_DOMAIN
from homeassistant.components.number import DOMAIN as NUMBER_DOMAIN
from homeassistant.components.select import DOMAIN as SELECT_DOMAIN
from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN
from homeassistant.components.switch import DOMAIN as SWITCH_DOMAIN
from homeassistant.components.text import DOMAIN as TEXT_DOMAIN
from homeassistant.const import CONF_HOST, CONF_PORT, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sceneglow import _migrate_registry_metadata
from custom_components.sceneglow.const import (
    CONF_CLIENT_CREDENTIAL,
    CONF_CLIENT_ID,
    CONF_INSTALLATION_ID,
    CONF_SERVER_IDENTITY,
    CONF_USE_TLS,
    DOMAIN,
    MANUFACTURER,
)
from tests.fake_sceneglow import (
    CLIENT_CREDENTIAL,
    CLIENT_ID,
    FakeSceneGlowServer,
)


async def test_real_entry_setup_registers_every_typed_control_platform(
    hass: HomeAssistant,
    aiohttp_server,
    enable_custom_integrations,
    mock_async_zeroconf,
    socket_enabled,
) -> None:
    """Forwarded platforms consume the complete initial coordinator snapshot."""
    fake = FakeSceneGlowServer(clients={CLIENT_ID: CLIENT_CREDENTIAL})
    server = await aiohttp_server(fake.create_app())
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="SceneGlow test screen",
        unique_id=fake.installation_id,
        data={
            CONF_HOST: server.host,
            CONF_PORT: server.port,
            CONF_USE_TLS: False,
            CONF_SERVER_IDENTITY: fake.server_fingerprint,
            CONF_INSTALLATION_ID: fake.installation_id,
            CONF_CLIENT_ID: CLIENT_ID,
            CONF_CLIENT_CREDENTIAL: CLIENT_CREDENTIAL,
        },
    )
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    preexisting_metric = registry.async_get_or_create(
        SENSOR_DOMAIN,
        DOMAIN,
        f"{fake.installation_id}_output_fps",
        config_entry=entry,
        disabled_by=er.RegistryEntryDisabler.INTEGRATION,
        entity_category=EntityCategory.DIAGNOSTIC,
    )
    assert hass.states.get(preexisting_metric.entity_id) is None

    assert await hass.config_entries.async_setup(entry.entry_id)

    try:
        entities = er.async_entries_for_config_entry(registry, entry.entry_id)
        by_domain: dict[str, int] = {}
        for entity in entities:
            domain = entity.entity_id.split(".", 1)[0]
            by_domain[domain] = by_domain.get(domain, 0) + 1
        assert by_domain[NUMBER_DOMAIN] == 32
        assert by_domain[SELECT_DOMAIN] == 14
        assert by_domain[SWITCH_DOMAIN] == 10
        assert by_domain[TEXT_DOMAIN] == 1
        assert len(entities) == 62
        performance = next(
            entity
            for entity in entities
            if entity.unique_id.endswith("_config_performance_diagnostics")
        )
        assert performance.entity_category is EntityCategory.DIAGNOSTIC
        assert registry.async_get(preexisting_metric.entity_id).disabled_by is None
        assert hass.states.get(preexisting_metric.entity_id) is not None

        devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
        assert len(devices) == 3
        assert {device.manufacturer for device in devices} == {"AIGenuity LTD"}
        assert sum(device.name.endswith("— ScreenGlow") for device in devices) == 1
    finally:
        assert await hass.config_entries.async_unload(entry.entry_id)
        for websocket in tuple(fake.sockets):
            await websocket.close()


async def test_registry_metadata_migration_updates_existing_entries(
    hass: HomeAssistant,
) -> None:
    """Existing devices and diagnostics adopt corrected integration metadata."""
    entry = MockConfigEntry(domain=DOMAIN, title="SceneGlow existing installation")
    entry.add_to_hass(hass)

    device_registry = dr.async_get(hass)
    parent = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, "existing-installation")},
        manufacturer="AI Genuity Limited",
        name="SceneGlow existing installation",
    )
    unrelated = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={("other_domain", "existing-installation")},
        manufacturer="Other manufacturer",
        name="Other device",
    )

    entity_registry = er.async_get(hass)
    performance = entity_registry.async_get_or_create(
        SWITCH_DOMAIN,
        DOMAIN,
        "existing-installation_config_performance_diagnostics",
        config_entry=entry,
        device_id=parent.id,
        entity_category=None,
    )
    capture = entity_registry.async_get_or_create(
        SWITCH_DOMAIN,
        DOMAIN,
        "existing-installation_capture",
        config_entry=entry,
        device_id=parent.id,
        entity_category=None,
    )
    integration_disabled_metric = entity_registry.async_get_or_create(
        SENSOR_DOMAIN,
        DOMAIN,
        "existing-installation_output_fps",
        config_entry=entry,
        device_id=parent.id,
        disabled_by=er.RegistryEntryDisabler.INTEGRATION,
        entity_category=EntityCategory.DIAGNOSTIC,
    )
    user_disabled_metric = entity_registry.async_get_or_create(
        SENSOR_DOMAIN,
        DOMAIN,
        "existing-installation_processing_time",
        config_entry=entry,
        device_id=parent.id,
        disabled_by=er.RegistryEntryDisabler.USER,
        entity_category=EntityCategory.DIAGNOSTIC,
    )
    refresh = entity_registry.async_get_or_create(
        BUTTON_DOMAIN,
        DOMAIN,
        "existing-installation_refresh",
        config_entry=entry,
        device_id=parent.id,
        entity_category=EntityCategory.DIAGNOSTIC,
    )

    _migrate_registry_metadata(hass, entry)

    assert entity_registry.async_get(performance.entity_id).entity_category is (
        EntityCategory.DIAGNOSTIC
    )
    assert entity_registry.async_get(capture.entity_id).entity_category is None
    assert (
        entity_registry.async_get(integration_disabled_metric.entity_id).disabled_by
        is None
    )
    assert entity_registry.async_get(user_disabled_metric.entity_id).disabled_by is (
        er.RegistryEntryDisabler.USER
    )
    assert entity_registry.async_get(refresh.entity_id) is None
    assert device_registry.async_get(parent.id).manufacturer == MANUFACTURER
    assert device_registry.async_get(unrelated.id).manufacturer == "Other manufacturer"
