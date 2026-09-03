"""Constrained Home Assistant compatible-light broker tests."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import Mock

from homeassistant.components.light import ATTR_SUPPORTED_COLOR_MODES, ColorMode
from homeassistant.const import SERVICE_TURN_ON
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sceneglow.const import DOMAIN
from custom_components.sceneglow.coordinator import SceneGlowCoordinator

INSTALLATION_ID = "8d359ff8-7ad9-4c80-ad9f-e7ca46e13b79"


def _coordinator(
    hass: HomeAssistant,
) -> SceneGlowCoordinator:
    entry = SimpleNamespace(
        unique_id=INSTALLATION_ID,
        entry_id="test-entry",
        async_on_unload=Mock(),
        options={},
    )
    return SceneGlowCoordinator(hass, entry, Mock())


def _colour_light(
    hass: HomeAssistant,
    unique_id: str = "lamp",
    area=None,
):
    area = area or ar.async_get(hass).async_create("Living Room")
    registry = er.async_get(hass)
    entry = registry.async_get_or_create(
        "light",
        "test",
        unique_id,
        suggested_object_id=unique_id,
        original_name=unique_id.replace("_", " ").title(),
    )
    registry.async_update_entity(entry.entity_id, area_id=area.id)
    hass.states.async_set(
        entry.entity_id,
        "on",
        {ATTR_SUPPORTED_COLOR_MODES: [ColorMode.RGB]},
    )
    return registry.async_get(entry.entity_id), area


def _unassigned_colour_light(hass: HomeAssistant, unique_id: str = "portable"):
    registry = er.async_get(hass)
    entry = registry.async_get_or_create(
        "light",
        "test",
        unique_id,
        suggested_object_id=unique_id,
        original_name=unique_id.replace("_", " ").title(),
    )
    hass.states.async_set(
        entry.entity_id,
        "on",
        {ATTR_SUPPORTED_COLOR_MODES: [ColorMode.RGB]},
    )
    return registry.async_get(entry.entity_id)


def test_catalogue_contains_all_compatible_lights_with_opaque_reference(
    hass: HomeAssistant,
) -> None:
    """Every compatible light enters the catalogue without an allowlist."""
    entry, area = _colour_light(hass)

    lights = _coordinator(hass)._light_catalogue()

    assert lights == [
        {
            "reference": entry.id,
            "entity_id": entry.entity_id,
            "name": "Lamp",
            "area_id": area.id,
            "area_name": "Living Room",
            "supported_color_modes": ["rgb"],
            "supports_transition": False,
        }
    ]


def test_catalogue_returns_parent_device_area_as_default(
    hass: HomeAssistant,
) -> None:
    """The SceneGlow device's configured HA Area is the initial room hint."""
    light_entry, area = _colour_light(hass)
    MockConfigEntry(domain=DOMAIN, entry_id="test-entry").add_to_hass(hass)
    devices = dr.async_get(hass)
    device = devices.async_get_or_create(
        config_entry_id="test-entry",
        identifiers={(DOMAIN, INSTALLATION_ID)},
        name="SceneGlow",
    )
    devices.async_update_device(device.id, area_id=area.id)

    response = _coordinator(hass)._light_catalogue_response()

    assert response["default_area_id"] == area.id
    assert response["default_area_name"] == "Living Room"
    assert response["lights"][0]["reference"] == light_entry.id


def test_catalogue_includes_unassigned_compatible_lights(
    hass: HomeAssistant,
) -> None:
    """Compatible lights without an HA Area remain available."""
    _unassigned_colour_light(hass, "unassigned")

    light = _coordinator(hass)._light_catalogue()[0]

    assert light["area_id"] == ""
    assert light["area_name"] == "Unassigned"


def test_area_catalogue_is_compact_and_counts_compatible_lights(
    hass: HomeAssistant,
) -> None:
    """Area discovery returns counts rather than the complete light payload."""
    _first, area = _colour_light(hass)
    _colour_light(hass, "second_lamp", area)
    _unassigned_colour_light(hass)

    response = _coordinator(hass)._light_area_catalogue_response()

    assert response["areas"] == [
        {
            "area_id": area.id,
            "area_name": "Living Room",
            "compatible_light_count": 2,
        },
        {
            "area_id": "",
            "area_name": "Unassigned",
            "compatible_light_count": 1,
        },
    ]


def test_large_installation_returns_a_compact_area_catalogue(
    hass: HomeAssistant,
) -> None:
    """Hundreds of lights do not make the first discovery response large."""
    areas = [
        ar.async_get(hass).async_create(f"Test Area {index}") for index in range(5)
    ]
    for index in range(500):
        _colour_light(hass, f"fixture_{index}", areas[index % len(areas)])

    coordinator = _coordinator(hass)
    response = coordinator._light_area_catalogue_response()

    assert len(response["areas"]) == 5
    assert {area["compatible_light_count"] for area in response["areas"]} == {100}
    assert len(json.dumps(response).encode()) < 2_048
    assert len(coordinator._light_catalogue(areas[0].id)) == 100


async def test_catalogue_request_can_be_scoped_to_one_area(
    hass: HomeAssistant,
) -> None:
    """Scope new clients to an Area while retaining full legacy catalogues."""
    first, area = _colour_light(hass)
    second, _area = _colour_light(hass, "second_lamp", area)
    unassigned = _unassigned_colour_light(hass)
    coordinator = _coordinator(hass)

    scoped = await coordinator._async_handle_broker_request(
        {
            "type": "ha.light.catalog.request",
            "request_id": "request-scoped",
            "area_id": area.id,
        }
    )
    unassigned_response = await coordinator._async_handle_broker_request(
        {
            "type": "ha.light.catalog.request",
            "request_id": "request-unassigned",
            "area_id": "",
        }
    )
    legacy = await coordinator._async_handle_broker_request(
        {
            "type": "ha.light.catalog.request",
            "request_id": "request-legacy",
        }
    )

    assert {light["entity_id"] for light in scoped["lights"]} == {
        first.entity_id,
        second.entity_id,
    }
    assert [light["entity_id"] for light in unassigned_response["lights"]] == [
        unassigned.entity_id
    ]
    assert len(legacy["lights"]) == 3


async def test_area_catalogue_request_uses_correlated_response_type(
    hass: HomeAssistant,
) -> None:
    """The Area-first request remains on the authenticated light-broker channel."""
    _entry, area = _colour_light(hass)

    response = await _coordinator(hass)._async_handle_broker_request(
        {
            "type": "ha.light.area.catalog.request",
            "request_id": "request-areas",
        }
    )

    assert response["type"] == "ha.light.area.catalog.response"
    assert response["request_id"] == "request-areas"
    assert response["areas"][0]["area_id"] == area.id


async def test_apply_is_constrained_to_compatible_light(
    hass: HomeAssistant,
) -> None:
    """A valid broker request becomes one bounded light service call."""
    entry, _area = _colour_light(hass)
    calls: list[ServiceCall] = []

    async def handle_turn_on(call: ServiceCall) -> None:
        calls.append(call)

    hass.services.async_register("light", SERVICE_TURN_ON, handle_turn_on)
    coordinator = _coordinator(hass)
    response = await coordinator._async_handle_broker_request(
        {
            "type": "ha.light.apply.request",
            "request_id": "request-1",
            "reference": entry.id,
            "red": 10,
            "green": 20,
            "blue": 30,
            "brightness": 128,
            "transition_ms": 1_000,
        }
    )

    assert response == {
        "type": "ha.light.apply.result",
        "api_version": 1,
        "request_id": "request-1",
        "status": "applied",
    }
    assert len(calls) == 1
    assert calls[0].data["entity_id"] == entry.entity_id
    assert calls[0].data["rgb_color"] == (10, 20, 30)


async def test_apply_rejects_unknown_reference(hass: HomeAssistant) -> None:
    """SceneGlow cannot turn an entity outside the compatible catalogue."""
    _entry, _area = _colour_light(hass)
    response = await _coordinator(hass)._async_handle_broker_request(
        {
            "type": "ha.light.apply.request",
            "request_id": "request-2",
            "reference": "not-in-catalogue",
            "red": 10,
            "green": 20,
            "blue": 30,
            "brightness": 128,
        }
    )

    assert response["error"] == "unknown_reference"
    assert response["request_id"] == "request-2"
