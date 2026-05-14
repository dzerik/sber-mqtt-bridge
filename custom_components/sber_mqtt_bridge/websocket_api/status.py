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

from ._common import (  # noqa: F401 — get_bridge re-exported for test patching
    WS_ENTITY_ID,
    get_bridge,
    get_config_entry,
    requires_bridge,
)

_LOGGER = logging.getLogger(__name__)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "sber_mqtt_bridge/devices",
    }
)
@websocket_api.async_response
@requires_bridge
async def ws_get_devices(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    bridge: Any,
) -> None:
    """Get all exposed Sber devices with their states."""
    devices: list[dict[str, Any]] = []
    links = bridge.entity_links
    for eid, entity in bridge.entities.items():
        device_data: dict[str, Any] = {
            "entity_id": eid,
            "sber_category": entity.category,
            "features": entity.get_final_features_list(),
            "name": entity.name,
            "room": entity.effective_room,
            "is_online": entity.is_online,
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
@requires_bridge
async def ws_get_status(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    bridge: Any,
) -> None:
    """Get bridge connection status and statistics."""
    from ..sber_protocol import VERSION

    location = hass.config.location_name or "Мой дом"
    entry = get_config_entry(hass)
    auto_parent = entry.options.get("hub_auto_parent_id", True) if entry else True

    # Compute health score
    stats = bridge.stats
    unack = bridge.unacknowledged_entities
    issues: list[str] = []
    if unack:
        issues.append(f"{len(unack)} entities unacknowledged")
    if stats.get("errors_from_sber", 0) > 0:
        issues.append(f"{stats['errors_from_sber']} Sber error(s)")
    if stats.get("publish_errors", 0) > 0:
        issues.append(f"{stats['publish_errors']} publish error(s)")
    if not bridge.is_connected:
        issues.append("disconnected")

    if not bridge.is_connected:
        health_score = "unhealthy"
    elif unack or stats.get("errors_from_sber", 0) > 0:
        health_score = "degraded"
    else:
        health_score = "healthy"

    connection.send_result(
        msg["id"],
        {
            "connected": bridge.is_connected,
            "phase": bridge.connection_phase,
            "stats": stats,
            "entities_count": bridge.entities_count,
            "unacknowledged": unack,
            "version": VERSION,
            "health": {
                "score": health_score,
                "issues": issues,
            },
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
@requires_bridge
async def ws_republish(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    bridge: Any,
) -> None:
    """Force republish device config to Sber cloud."""
    await bridge.async_republish_config()
    connection.send_result(msg["id"], {"success": True})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "sber_mqtt_bridge/related_sensors",
        vol.Required("entity_id"): WS_ENTITY_ID,
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
        vol.Required("entity_id"): WS_ENTITY_ID,
    }
)
@websocket_api.async_response
@requires_bridge
async def ws_publish_one_status(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    bridge: Any,
) -> None:
    """Publish the current state of a single entity to Sber cloud."""
    await bridge.async_publish_entity_status(msg["entity_id"])
    connection.send_result(msg["id"], {"success": True})


def _section_overview(entity: Any, resolved_room: str) -> dict[str, Any]:
    """Return the base entity overview block."""
    return {
        "entity_id": entity.entity_id,
        "name": entity.name,
        "sber_category": entity.category,
        "features": entity.get_final_features_list(),
        "room": resolved_room,
        "is_online": entity.is_online,
        "is_filled": entity.is_filled_by_state,
        "state": entity.state,
    }


def _section_sber_states(entity: Any) -> list[dict[str, Any]]:
    """Build the Sber current-state list; empty list on failure."""
    try:
        sber_state = entity.to_sber_current_state()
        return sber_state.get(entity.entity_id, {}).get("states", [])
    except (RuntimeError, TypeError, ValueError):
        return []


def _section_sber_model(entity: Any) -> dict[str, Any]:
    """Build the Sber device-config model block; empty dict on failure."""
    try:
        sber_config = entity.to_sber_state()
        return sber_config.get("model", {})
    except (RuntimeError, TypeError, ValueError):
        return {}


def _section_ha_state(hass: HomeAssistant, entity_id: str) -> dict[str, Any]:
    """Return HA state + attributes (or None/empty if entity missing)."""
    ha_state = hass.states.get(entity_id)
    if ha_state is None:
        return {"ha_state": None, "ha_attributes": {}}
    return {
        "ha_state": ha_state.state,
        "ha_attributes": dict(ha_state.attributes),
    }


def _section_device_info(entry: Any, device_reg: Any, area_reg: Any) -> dict[str, Any] | None:
    """Return HA device-registry info, or None if no device linked."""
    if not entry or not entry.device_id:
        return None
    device = device_reg.async_get(entry.device_id)
    if device is None:
        return None
    area_obj = area_reg.async_get_area(device.area_id) if device.area_id else None
    resolved_device_area = area_obj.name if area_obj else (device.area_id or "")
    return {
        "name": device.name_by_user or device.name,
        "manufacturer": device.manufacturer,
        "model": device.model,
        "sw_version": device.sw_version,
        "hw_version": device.hw_version,
        "area_id": resolved_device_area,
    }


def _friendly_name(linked_state: Any, linked_entry: Any, linked_id: str) -> str:
    """Resolve a friendly_name for a linked entity (3-way fallback)."""
    if linked_state is not None:
        return linked_state.attributes.get("friendly_name", linked_id)
    if linked_entry is not None:
        return linked_entry.name or linked_entry.original_name or linked_id
    return linked_id


def _section_linked_entities(
    bridge: Any,
    entity_id: str,
    hass: HomeAssistant,
    entity_reg: Any,
) -> list[dict[str, Any]]:
    """Return the linked-sensor detail list (or empty if no links)."""
    links = bridge.entity_links.get(entity_id, {})
    if not links:
        return []
    out: list[dict[str, Any]] = []
    for role, linked_id in links.items():
        linked_state = hass.states.get(linked_id)
        linked_entry = entity_reg.async_get(linked_id)
        out.append(
            {
                "role": role,
                "entity_id": linked_id,
                "friendly_name": _friendly_name(linked_state, linked_entry, linked_id),
                "state": linked_state.state if linked_state else None,
                "device_class": (linked_entry.original_device_class if linked_entry else None),
            }
        )
    return out


@websocket_api.websocket_command(
    {
        vol.Required("type"): "sber_mqtt_bridge/device_detail",
        vol.Required("entity_id"): WS_ENTITY_ID,
    }
)
@websocket_api.async_response
@requires_bridge
async def ws_device_detail(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    bridge: Any,
) -> None:
    """Get full detail for a single Sber device."""
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

    result: dict[str, Any] = {
        **_section_overview(entity, resolved_room),
        "sber_states": _section_sber_states(entity),
        "sber_model": _section_sber_model(entity),
        **_section_ha_state(hass, entity_id),
    }

    device_info = _section_device_info(entry, device_reg, area_reg)
    if device_info is not None:
        result["device_info"] = device_info

    linked = _section_linked_entities(bridge, entity_id, hass, entity_reg)
    if linked:
        result["linked_entities"] = linked

    redefs = bridge.redefinitions.get(entity_id)
    if redefs:
        result["redefinitions"] = redefs

    connection.send_result(msg["id"], result)
