"""Status, republish, devices, device_detail, publish-one, related-sensors commands."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from ._common import get_bridge, get_config_entry

_LOGGER = logging.getLogger(__name__)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "sber_mqtt_bridge/devices",
    }
)
@websocket_api.async_response
async def ws_get_devices(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Get all exposed Sber devices with their states."""
    bridge = get_bridge(hass)
    if bridge is None:
        connection.send_error(msg["id"], "bridge_not_found", "Sber bridge not available")
        return

    devices: list[dict[str, Any]] = []
    links = bridge.entity_links
    for eid, entity in bridge.entities.items():
        features = (
            entity.get_final_features_list()
            if hasattr(entity, "get_final_features_list")
            else entity.create_features_list()
        )
        device_data: dict[str, Any] = {
            "entity_id": eid,
            "sber_category": entity.category,
            "features": features,
            "name": entity.name,
            "room": entity.effective_room,
            "is_online": entity._is_online,
            "state": entity.state,
            "is_filled": entity.is_filled_by_state,
        }
        if eid in links:
            device_data["linked_entities"] = links[eid]
        devices.append(device_data)

    enabled_ids = set(bridge.enabled_entity_ids)
    acknowledged_all = bridge.stats.get("acknowledged_entities", [])
    acknowledged = [eid for eid in acknowledged_all if eid in enabled_ids]
    unacknowledged = bridge.unacknowledged_entities

    connection.send_result(
        msg["id"],
        {
            "devices": devices,
            "total": len(enabled_ids),
            "acknowledged_count": len(acknowledged),
            "unacknowledged_count": len(unacknowledged),
            "unacknowledged": unacknowledged,
        },
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "sber_mqtt_bridge/status",
    }
)
@websocket_api.async_response
async def ws_get_status(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Get bridge connection status and statistics."""
    bridge = get_bridge(hass)
    if bridge is None:
        connection.send_error(msg["id"], "bridge_not_found", "Sber bridge not available")
        return

    from ..sber_protocol import VERSION

    location = hass.config.location_name or "Мой дом"
    entry = get_config_entry(hass)
    auto_parent = entry.options.get("hub_auto_parent_id", True) if entry else True

    connection.send_result(
        msg["id"],
        {
            "connected": bridge.is_connected,
            "phase": bridge.connection_phase,
            "stats": bridge.stats,
            "entities_count": bridge.entities_count,
            "unacknowledged": bridge.unacknowledged_entities,
            "version": VERSION,
            "hub": {
                "id": "root",
                "name": "Home Assistant Bridge",
                "home": location,
                "room": location,
                "version": VERSION,
                "is_online": bridge.is_connected,
                "children_count": len(bridge.enabled_entity_ids),
                "auto_parent_id": auto_parent,
            },
        },
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "sber_mqtt_bridge/republish",
    }
)
@websocket_api.async_response
async def ws_republish(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Force republish device config to Sber cloud."""
    bridge = get_bridge(hass)
    if bridge is None:
        connection.send_error(msg["id"], "bridge_not_found", "Sber bridge not available")
        return
    await bridge.async_republish()
    connection.send_result(msg["id"], {"success": True})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "sber_mqtt_bridge/related_sensors",
        vol.Required("entity_id"): str,
    }
)
@websocket_api.async_response
async def ws_related_sensors(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Find sensors related to entity by shared device_id."""
    entity_reg = er.async_get(hass)
    entry = entity_reg.async_get(msg["entity_id"])
    if not entry or not entry.device_id:
        connection.send_result(msg["id"], {"sensors": []})
        return

    sensors: list[dict[str, Any]] = []
    for e in entity_reg.entities.values():
        if e.device_id == entry.device_id and e.entity_id != msg["entity_id"]:
            domain = e.entity_id.split(".")[0]
            if domain == "sensor":
                sensors.append(
                    {
                        "entity_id": e.entity_id,
                        "device_class": e.original_device_class or "",
                        "name": e.name or e.original_name or e.entity_id,
                    }
                )

    connection.send_result(msg["id"], {"sensors": sensors})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "sber_mqtt_bridge/publish_one_status",
        vol.Required("entity_id"): str,
    }
)
@websocket_api.async_response
async def ws_publish_one_status(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Publish the current state of a single entity to Sber cloud."""
    bridge = get_bridge(hass)
    if bridge is None:
        connection.send_error(msg["id"], "bridge_not_found", "Sber bridge not available")
        return
    await bridge.async_publish_entity_status(msg["entity_id"])
    connection.send_result(msg["id"], {"success": True})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "sber_mqtt_bridge/device_detail",
        vol.Required("entity_id"): str,
    }
)
@websocket_api.async_response
async def ws_device_detail(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Get full detail for a single Sber device."""
    bridge = get_bridge(hass)
    if bridge is None:
        connection.send_error(msg["id"], "bridge_not_found", "Bridge not available")
        return

    entity_id: str = msg["entity_id"]
    entity = bridge.entities.get(entity_id)
    if entity is None:
        connection.send_error(msg["id"], "not_found", f"Entity {entity_id} not in bridge")
        return

    entity_reg = er.async_get(hass)
    device_reg = dr.async_get(hass)
    area_reg = ar.async_get(hass)
    entry = entity_reg.async_get(entity_id)

    raw_area = entity.effective_room
    area_obj = area_reg.async_get_area(raw_area) if raw_area else None
    resolved_room = area_obj.name if area_obj else raw_area

    features = (
        entity.get_final_features_list()
        if hasattr(entity, "get_final_features_list")
        else entity.create_features_list()
    )
    result: dict[str, Any] = {
        "entity_id": entity_id,
        "name": entity.name,
        "sber_category": entity.category,
        "features": features,
        "room": resolved_room,
        "is_online": entity._is_online,
        "is_filled": entity.is_filled_by_state,
        "state": entity.state,
    }

    try:
        sber_state = entity.to_sber_current_state()
        result["sber_states"] = sber_state.get(entity_id, {}).get("states", [])
    except (RuntimeError, TypeError, ValueError):
        result["sber_states"] = []

    try:
        sber_config = entity.to_sber_state()
        result["sber_model"] = sber_config.get("model", {})
    except (RuntimeError, TypeError, ValueError):
        result["sber_model"] = {}

    ha_state = hass.states.get(entity_id)
    if ha_state:
        result["ha_state"] = ha_state.state
        result["ha_attributes"] = dict(ha_state.attributes)
    else:
        result["ha_state"] = None
        result["ha_attributes"] = {}

    if entry and entry.device_id:
        device = device_reg.async_get(entry.device_id)
        if device:
            resolved_device_area = (
                area_reg.async_get_area(device.area_id).name
                if device.area_id and area_reg.async_get_area(device.area_id)
                else device.area_id or ""
            )
            result["device_info"] = {
                "name": device.name_by_user or device.name,
                "manufacturer": device.manufacturer,
                "model": device.model,
                "sw_version": device.sw_version,
                "hw_version": device.hw_version,
                "area_id": resolved_device_area,
            }

    links = bridge.entity_links.get(entity_id, {})
    if links:
        linked_detail: list[dict[str, Any]] = []
        for role, linked_id in links.items():
            linked_state = hass.states.get(linked_id)
            linked_entry = entity_reg.async_get(linked_id)
            if linked_state:
                friendly_name = linked_state.attributes.get("friendly_name", linked_id)
            elif linked_entry:
                friendly_name = linked_entry.name or linked_entry.original_name or linked_id
            else:
                friendly_name = linked_id
            linked_detail.append(
                {
                    "role": role,
                    "entity_id": linked_id,
                    "friendly_name": friendly_name,
                    "state": linked_state.state if linked_state else None,
                    "device_class": (linked_entry.original_device_class if linked_entry else None),
                }
            )
        result["linked_entities"] = linked_detail

    redefs = bridge.redefinitions.get(entity_id)
    if redefs:
        result["redefinitions"] = redefs

    connection.send_result(msg["id"], result)
