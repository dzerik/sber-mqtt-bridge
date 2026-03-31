"""WebSocket API for Sber MQTT Bridge panel.

Provides real-time device and connection data to the frontend SPA panel
via Home Assistant native WebSocket commands, including entity management
(add, remove, override, bulk operations).
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_ENTITY_LINKS,
    CONF_ENTITY_TYPE_OVERRIDES,
    CONF_EXPOSED_ENTITIES,
    CONF_SBER_VERIFY_SSL,
    DOMAIN,
    SETTINGS_DEFAULTS,
    SUPPORTED_DOMAINS,
)
from .devices.base_entity import LinkableRole, resolve_link_role

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

    from .sber_bridge import SberBridge

_LOGGER = logging.getLogger(__name__)


def _get_config_entry(hass: HomeAssistant) -> ConfigEntry | None:
    """Get the first loaded config entry for the Sber MQTT Bridge domain.

    Returns:
        The ConfigEntry instance, or None if not found.
    """
    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    return entries[0] if entries else None


def _get_bridge(hass: HomeAssistant) -> SberBridge | None:
    """Get the active SberBridge instance from config entry runtime_data.

    Returns:
        The SberBridge instance, or None if not available.
    """
    entry = _get_config_entry(hass)
    if entry is None or not hasattr(entry, "runtime_data") or entry.runtime_data is None:
        return None
    return entry.runtime_data.bridge


@callback
def async_setup_websocket_api(hass: HomeAssistant) -> None:
    """Register WebSocket API commands for the Sber MQTT Bridge panel.

    Idempotent — skips registration if already done for this HA instance.

    Args:
        hass: Home Assistant core instance.
    """
    if hass.data.get(f"{DOMAIN}_ws_registered"):
        return
    hass.data[f"{DOMAIN}_ws_registered"] = True

    websocket_api.async_register_command(hass, ws_get_devices)
    websocket_api.async_register_command(hass, ws_get_status)
    websocket_api.async_register_command(hass, ws_republish)
    websocket_api.async_register_command(hass, ws_get_available_entities)
    websocket_api.async_register_command(hass, ws_add_entities)
    websocket_api.async_register_command(hass, ws_remove_entities)
    websocket_api.async_register_command(hass, ws_set_type_override)
    websocket_api.async_register_command(hass, ws_bulk_add)
    websocket_api.async_register_command(hass, ws_clear_all)
    websocket_api.async_register_command(hass, ws_related_sensors)
    websocket_api.async_register_command(hass, ws_publish_one_status)
    websocket_api.async_register_command(hass, ws_export)
    websocket_api.async_register_command(hass, ws_import)
    websocket_api.async_register_command(hass, ws_raw_config)
    websocket_api.async_register_command(hass, ws_raw_states)
    websocket_api.async_register_command(hass, ws_device_detail)
    websocket_api.async_register_command(hass, ws_set_entity_links)
    websocket_api.async_register_command(hass, ws_suggest_links)
    websocket_api.async_register_command(hass, ws_auto_link_all)
    websocket_api.async_register_command(hass, ws_add_device_wizard)
    websocket_api.async_register_command(hass, ws_message_log)
    websocket_api.async_register_command(hass, ws_clear_message_log)
    websocket_api.async_register_command(hass, ws_get_settings)
    websocket_api.async_register_command(hass, ws_update_settings)
    websocket_api.async_register_command(hass, ws_send_raw_config)
    websocket_api.async_register_command(hass, ws_send_raw_state)
    websocket_api.async_register_command(hass, ws_subscribe_messages)
    _LOGGER.debug("Sber MQTT Bridge WebSocket API registered")


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
    """Get all exposed Sber devices with their states.

    Args:
        hass: Home Assistant core instance.
        connection: Active WebSocket connection.
        msg: Incoming WebSocket message.
    """
    bridge = _get_bridge(hass)
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
            "room": getattr(entity, "area_id", ""),
            "is_online": entity._is_online,
            "state": entity.state,
            "is_filled": entity.is_filled_by_state,
        }
        if eid in links:
            device_data["linked_entities"] = links[eid]
        devices.append(device_data)

    enabled_ids = set(bridge.enabled_entity_ids)
    acknowledged_all = bridge.stats.get("acknowledged_entities", [])
    # Only count acknowledged entities that are still in the enabled list
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
    """Get bridge connection status and statistics.

    Args:
        hass: Home Assistant core instance.
        connection: Active WebSocket connection.
        msg: Incoming WebSocket message.
    """
    bridge = _get_bridge(hass)
    if bridge is None:
        connection.send_error(msg["id"], "bridge_not_found", "Sber bridge not available")
        return

    from .sber_protocol import VERSION

    connection.send_result(
        msg["id"],
        {
            "connected": bridge.is_connected,
            "stats": bridge.stats,
            "entities_count": bridge.entities_count,
            "unacknowledged": bridge.unacknowledged_entities,
            "version": VERSION,
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
    """Force republish device config to Sber cloud.

    Args:
        hass: Home Assistant core instance.
        connection: Active WebSocket connection.
        msg: Incoming WebSocket message.
    """
    bridge = _get_bridge(hass)
    if bridge is None:
        connection.send_error(msg["id"], "bridge_not_found", "Sber bridge not available")
        return

    await bridge.async_republish()
    connection.send_result(msg["id"], {"success": True})


# ---------- Entity management commands ----------


@websocket_api.websocket_command(
    {
        vol.Required("type"): "sber_mqtt_bridge/available_entities",
    }
)
@websocket_api.async_response
async def ws_get_available_entities(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Get all HA entities available for export to Sber.

    Returns entities from SUPPORTED_DOMAINS that are not disabled,
    excluding those already in the exposed list.

    Args:
        hass: Home Assistant core instance.
        connection: Active WebSocket connection.
        msg: Incoming WebSocket message.
    """
    entry = _get_config_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "entry_not_found", "Config entry not found")
        return

    exposed: list[str] = list(entry.options.get(CONF_EXPOSED_ENTITIES, []))
    exposed_set = set(exposed)

    # Collect linked entity IDs so they don't appear in available list
    bridge = _get_bridge(hass)
    linked_ids = bridge.linked_entity_ids if bridge else set()

    registry = er.async_get(hass)
    entities: list[dict[str, Any]] = []

    for entity_entry in registry.entities.values():
        if entity_entry.disabled:
            continue
        domain = entity_entry.domain
        if domain not in SUPPORTED_DOMAINS:
            continue
        if entity_entry.entity_id in exposed_set:
            continue
        if entity_entry.entity_id in linked_ids:
            continue

        state = hass.states.get(entity_entry.entity_id)
        friendly_name = ""
        if state and state.attributes:
            friendly_name = state.attributes.get("friendly_name", "")

        entities.append(
            {
                "entity_id": entity_entry.entity_id,
                "domain": domain,
                "device_class": entity_entry.original_device_class or "",
                "friendly_name": friendly_name or entity_entry.name or entity_entry.original_name or "",
            }
        )

    connection.send_result(msg["id"], {"entities": entities})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "sber_mqtt_bridge/add_entities",
        vol.Required("entity_ids"): [str],
    }
)
@websocket_api.async_response
async def ws_add_entities(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Add entities to the exposed list and reload the integration.

    Args:
        hass: Home Assistant core instance.
        connection: Active WebSocket connection.
        msg: Incoming WebSocket message with ``entity_ids`` list.
    """
    entry = _get_config_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "entry_not_found", "Config entry not found")
        return

    current: list[str] = list(entry.options.get(CONF_EXPOSED_ENTITIES, []))
    current_set = set(current)
    added: list[str] = []

    for eid in msg["entity_ids"]:
        if eid not in current_set:
            current.append(eid)
            current_set.add(eid)
            added.append(eid)

    if added:
        new_options = dict(entry.options)
        new_options[CONF_EXPOSED_ENTITIES] = current
        hass.config_entries.async_update_entry(entry, options=new_options)
        await hass.config_entries.async_reload(entry.entry_id)

    connection.send_result(msg["id"], {"added": added, "total": len(current)})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "sber_mqtt_bridge/remove_entities",
        vol.Required("entity_ids"): [str],
    }
)
@websocket_api.async_response
async def ws_remove_entities(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Remove entities from the exposed list and reload the integration.

    Args:
        hass: Home Assistant core instance.
        connection: Active WebSocket connection.
        msg: Incoming WebSocket message with ``entity_ids`` list.
    """
    entry = _get_config_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "entry_not_found", "Config entry not found")
        return

    to_remove = set(msg["entity_ids"])
    current: list[str] = list(entry.options.get(CONF_EXPOSED_ENTITIES, []))
    new_list = [eid for eid in current if eid not in to_remove]
    removed = len(current) - len(new_list)

    # Also clean up type overrides and entity links for removed entities
    overrides: dict[str, str] = dict(entry.options.get(CONF_ENTITY_TYPE_OVERRIDES, {}))
    entity_links: dict[str, dict] = dict(entry.options.get(CONF_ENTITY_LINKS, {}))
    for eid in to_remove:
        overrides.pop(eid, None)
        entity_links.pop(eid, None)

    if removed > 0:
        new_options = dict(entry.options)
        new_options[CONF_EXPOSED_ENTITIES] = new_list
        new_options[CONF_ENTITY_TYPE_OVERRIDES] = overrides
        new_options[CONF_ENTITY_LINKS] = entity_links
        hass.config_entries.async_update_entry(entry, options=new_options)
        await hass.config_entries.async_reload(entry.entry_id)

    connection.send_result(msg["id"], {"removed": removed, "total": len(new_list)})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "sber_mqtt_bridge/set_override",
        vol.Required("entity_id"): str,
        vol.Required("category"): str,
    }
)
@websocket_api.async_response
async def ws_set_type_override(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Set or clear the Sber category override for an entity.

    Pass ``category`` as ``"auto"`` to remove the override and use
    automatic detection.

    Args:
        hass: Home Assistant core instance.
        connection: Active WebSocket connection.
        msg: Incoming WebSocket message with ``entity_id`` and ``category``.
    """
    entry = _get_config_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "entry_not_found", "Config entry not found")
        return

    entity_id: str = msg["entity_id"]
    category: str = msg["category"]

    overrides: dict[str, str] = dict(entry.options.get(CONF_ENTITY_TYPE_OVERRIDES, {}))

    if category == "auto":
        overrides.pop(entity_id, None)
    else:
        overrides[entity_id] = category

    new_options = dict(entry.options)
    new_options[CONF_ENTITY_TYPE_OVERRIDES] = overrides
    hass.config_entries.async_update_entry(entry, options=new_options)
    await hass.config_entries.async_reload(entry.entry_id)

    connection.send_result(msg["id"], {"entity_id": entity_id, "category": category})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "sber_mqtt_bridge/bulk_add",
        vol.Optional("domains", default=[]): [str],
    }
)
@websocket_api.async_response
async def ws_bulk_add(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Bulk add entities by domain or all supported domains.

    If ``domains`` is empty, all entities from SUPPORTED_DOMAINS are added.

    Args:
        hass: Home Assistant core instance.
        connection: Active WebSocket connection.
        msg: Incoming WebSocket message with optional ``domains`` list.
    """
    entry = _get_config_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "entry_not_found", "Config entry not found")
        return

    target_domains = msg.get("domains") or list(SUPPORTED_DOMAINS)

    current: list[str] = list(entry.options.get(CONF_EXPOSED_ENTITIES, []))
    current_set = set(current)

    # Use deduplication by device_id (same logic as config_flow)
    from .config_flow import _get_entities_by_domains

    domain_ids = _get_entities_by_domains(hass, target_domains)
    added: list[str] = []
    for eid in domain_ids:
        if eid not in current_set:
            current.append(eid)
            current_set.add(eid)
            added.append(eid)

    if added:
        new_options = dict(entry.options)
        new_options[CONF_EXPOSED_ENTITIES] = current
        hass.config_entries.async_update_entry(entry, options=new_options)
        await hass.config_entries.async_reload(entry.entry_id)

    connection.send_result(msg["id"], {"added": len(added), "total": len(current)})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "sber_mqtt_bridge/clear_all",
    }
)
@websocket_api.async_response
async def ws_clear_all(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Remove all entities from the exposed list and clear overrides.

    Args:
        hass: Home Assistant core instance.
        connection: Active WebSocket connection.
        msg: Incoming WebSocket message.
    """
    entry = _get_config_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "entry_not_found", "Config entry not found")
        return

    new_options = dict(entry.options)
    previous_count = len(new_options.get(CONF_EXPOSED_ENTITIES, []))
    new_options[CONF_EXPOSED_ENTITIES] = []
    new_options[CONF_ENTITY_TYPE_OVERRIDES] = {}
    new_options[CONF_ENTITY_LINKS] = {}
    hass.config_entries.async_update_entry(entry, options=new_options)
    await hass.config_entries.async_reload(entry.entry_id)

    connection.send_result(msg["id"], {"removed": previous_count})


# ---------- Related sensors, publish one, export/import ----------


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
    """Find sensors related to entity by shared device_id.

    Searches the entity registry for other sensor entities that belong
    to the same physical device.

    Args:
        hass: Home Assistant core instance.
        connection: Active WebSocket connection.
        msg: Incoming WebSocket message with ``entity_id``.
    """
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
    """Publish the current state of a single entity to Sber cloud.

    Args:
        hass: Home Assistant core instance.
        connection: Active WebSocket connection.
        msg: Incoming WebSocket message with ``entity_id``.
    """
    bridge = _get_bridge(hass)
    if bridge is None:
        connection.send_error(msg["id"], "bridge_not_found", "Sber bridge not available")
        return

    await bridge.async_publish_entity_status(msg["entity_id"])
    connection.send_result(msg["id"], {"success": True})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "sber_mqtt_bridge/export",
    }
)
@websocket_api.async_response
async def ws_export(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Export the full device configuration as JSON.

    Args:
        hass: Home Assistant core instance.
        connection: Active WebSocket connection.
        msg: Incoming WebSocket message.
    """
    entry = _get_config_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "entry_not_found", "Config entry not found")
        return

    connection.send_result(
        msg["id"],
        {
            "version": 2,
            "exposed_entities": list(entry.options.get(CONF_EXPOSED_ENTITIES, [])),
            "type_overrides": dict(entry.options.get(CONF_ENTITY_TYPE_OVERRIDES, {})),
            "redefinitions": dict(entry.options.get("redefinitions", {})),
            "entity_links": dict(entry.options.get(CONF_ENTITY_LINKS, {})),
        },
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "sber_mqtt_bridge/import",
        vol.Required("config"): dict,
    }
)
@websocket_api.async_response
async def ws_import(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Import a device configuration from a JSON payload.

    Replaces the current exposed entities, type overrides, and
    redefinitions with the values from the supplied config object.

    Args:
        hass: Home Assistant core instance.
        connection: Active WebSocket connection.
        msg: Incoming WebSocket message with ``config`` dict.
    """
    entry = _get_config_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "entry_not_found", "Config entry not found")
        return

    config: dict[str, Any] = msg["config"]
    new_options = dict(entry.options)

    if "exposed_entities" in config:
        new_options[CONF_EXPOSED_ENTITIES] = config["exposed_entities"]
    if "type_overrides" in config:
        new_options[CONF_ENTITY_TYPE_OVERRIDES] = config["type_overrides"]
    if "redefinitions" in config:
        new_options["redefinitions"] = config["redefinitions"]
    if "entity_links" in config:
        new_options[CONF_ENTITY_LINKS] = config["entity_links"]

    hass.config_entries.async_update_entry(entry, options=new_options)
    await hass.config_entries.async_reload(entry.entry_id)

    connection.send_result(msg["id"], {"success": True})


# ---------- DevTools commands ----------


@websocket_api.websocket_command(
    {
        vol.Required("type"): "sber_mqtt_bridge/raw_config",
    }
)
@websocket_api.async_response
async def ws_raw_config(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Get the raw config JSON that would be sent to Sber.

    Returns the full device list payload as published to ``up/config``.

    Args:
        hass: Home Assistant core instance.
        connection: Active WebSocket connection.
        msg: Incoming WebSocket message.
    """
    bridge = _get_bridge(hass)
    if bridge is None:
        connection.send_error(msg["id"], "bridge_not_found", "Bridge not available")
        return

    from .sber_protocol import build_devices_list_json

    payload = build_devices_list_json(bridge.entities, bridge.enabled_entity_ids, bridge.redefinitions)
    connection.send_result(msg["id"], {"payload": payload})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "sber_mqtt_bridge/raw_states",
    }
)
@websocket_api.async_response
async def ws_raw_states(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Get the raw states JSON that would be sent to Sber.

    Returns the full state list payload as published to ``up/status``.

    Args:
        hass: Home Assistant core instance.
        connection: Active WebSocket connection.
        msg: Incoming WebSocket message.
    """
    bridge = _get_bridge(hass)
    if bridge is None:
        connection.send_error(msg["id"], "bridge_not_found", "Bridge not available")
        return

    from .sber_protocol import build_states_list_json

    payload, _valid = build_states_list_json(bridge.entities, None, bridge.enabled_entity_ids)
    connection.send_result(msg["id"], {"payload": payload})


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
    """Get full detail for a single Sber device.

    Returns device config, current Sber state, linked entities with their
    current values, HA entity attributes, and device registry info.
    """
    bridge = _get_bridge(hass)
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
    entry = entity_reg.async_get(entity_id)

    # Basic info
    features = entity.get_final_features_list() if hasattr(entity, "get_final_features_list") else entity.create_features_list()
    result: dict[str, Any] = {
        "entity_id": entity_id,
        "name": entity.name,
        "sber_category": entity.category,
        "features": features,
        "room": getattr(entity, "area_id", ""),
        "is_online": entity._is_online,
        "is_filled": entity.is_filled_by_state,
        "state": entity.state,
    }

    # Sber current state payload
    try:
        sber_state = entity.to_sber_current_state()
        result["sber_states"] = sber_state.get(entity_id, {}).get("states", [])
    except (RuntimeError, TypeError, ValueError):
        result["sber_states"] = []

    # Sber device config (model, allowed_values, dependencies)
    try:
        sber_config = entity.to_sber_state()
        result["sber_model"] = sber_config.get("model", {})
    except (RuntimeError, TypeError, ValueError):
        result["sber_model"] = {}

    # HA entity attributes
    ha_state = hass.states.get(entity_id)
    if ha_state:
        result["ha_state"] = ha_state.state
        result["ha_attributes"] = dict(ha_state.attributes)
    else:
        result["ha_state"] = None
        result["ha_attributes"] = {}

    # HA device registry info
    if entry and entry.device_id:
        device = device_reg.async_get(entry.device_id)
        if device:
            result["device_info"] = {
                "name": device.name_by_user or device.name,
                "manufacturer": device.manufacturer,
                "model": device.model,
                "sw_version": device.sw_version,
                "hw_version": device.hw_version,
                "area_id": device.area_id,
            }

    # Linked entities with current state values
    links = bridge.entity_links.get(entity_id, {})
    if links:
        linked_detail: list[dict[str, Any]] = []
        for role, linked_id in links.items():
            linked_state = hass.states.get(linked_id)
            linked_entry = entity_reg.async_get(linked_id)
            linked_detail.append({
                "role": role,
                "entity_id": linked_id,
                "friendly_name": (
                    linked_state.attributes.get("friendly_name", linked_id)
                    if linked_state
                    else linked_entry.name or linked_entry.original_name or linked_id
                    if linked_entry
                    else linked_id
                ),
                "state": linked_state.state if linked_state else None,
                "device_class": linked_entry.original_device_class if linked_entry else None,
            })
        result["linked_entities"] = linked_detail

    # Redefinitions (custom name/room from Sber)
    redefs = bridge.redefinitions.get(entity_id)
    if redefs:
        result["redefinitions"] = redefs

    connection.send_result(msg["id"], result)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "sber_mqtt_bridge/message_log",
    }
)
@callback
def ws_message_log(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Get the recent MQTT message log from the ring buffer.

    Returns the last 50 MQTT messages (incoming and outgoing).

    Args:
        hass: Home Assistant core instance.
        connection: Active WebSocket connection.
        msg: Incoming WebSocket message.
    """
    bridge = _get_bridge(hass)
    if bridge is None:
        connection.send_error(msg["id"], "bridge_not_found", "Bridge not available")
        return

    connection.send_result(msg["id"], {"messages": bridge.message_log})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "sber_mqtt_bridge/clear_message_log",
    }
)
@callback
def ws_clear_message_log(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Clear the MQTT message log ring buffer.

    Args:
        hass: Home Assistant core instance.
        connection: Active WebSocket connection.
        msg: Incoming WebSocket message.
    """
    bridge = _get_bridge(hass)
    if bridge is None:
        connection.send_error(msg["id"], "bridge_not_found", "Bridge not available")
        return

    bridge.clear_message_log()
    connection.send_result(msg["id"], {"success": True})


# ---------- Entity Linking commands ----------


@websocket_api.websocket_command(
    {
        vol.Required("type"): "sber_mqtt_bridge/set_entity_links",
        vol.Required("entity_id"): str,
        vol.Required("links"): dict,
    }
)
@websocket_api.async_response
async def ws_set_entity_links(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Set linked entities for a primary entity.

    Args:
        hass: Home Assistant core instance.
        connection: Active WebSocket connection.
        msg: Message with ``entity_id`` (primary) and ``links`` dict {role: linked_entity_id}.
    """
    entry = _get_config_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "entry_not_found", "Config entry not found")
        return

    entity_id: str = msg["entity_id"]
    new_links: dict[str, str] = msg["links"]

    # Validate primary is exposed
    exposed = set(entry.options.get(CONF_EXPOSED_ENTITIES, []))
    if entity_id not in exposed:
        connection.send_error(msg["id"], "not_exposed", f"{entity_id} is not in exposed entities")
        return

    # Validate no circular links (linked entity cannot be a primary with its own links)
    existing_links = dict(entry.options.get(CONF_ENTITY_LINKS, {}))
    for linked_id in new_links.values():
        if linked_id in existing_links:
            connection.send_error(
                msg["id"], "circular_link", f"{linked_id} is already a primary entity with links — cannot link it"
            )
            return
        if linked_id == entity_id:
            connection.send_error(msg["id"], "self_link", "Cannot link entity to itself")
            return

    # Save links
    all_links = dict(entry.options.get(CONF_ENTITY_LINKS, {}))
    if new_links:
        all_links[entity_id] = new_links
    else:
        all_links.pop(entity_id, None)

    new_options = dict(entry.options)
    new_options[CONF_ENTITY_LINKS] = all_links
    hass.config_entries.async_update_entry(entry, options=new_options)
    await hass.config_entries.async_reload(entry.entry_id)

    connection.send_result(msg["id"], {"success": True, "links": new_links})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "sber_mqtt_bridge/suggest_links",
        vol.Required("entity_id"): str,
        vol.Optional("category"): str,
        vol.Optional("same_device_only", default=False): bool,
    }
)
@websocket_api.async_response
async def ws_suggest_links(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Suggest linkable entities for a primary entity.

    First returns siblings on the same HA device, then compatible entities
    from other devices (marked ``same_device: false``) so users can link
    battery/signal sensors even when HA splits them into separate devices.

    Args:
        hass: Home Assistant core instance.
        connection: Active WebSocket connection.
        msg: Message with ``entity_id`` (primary) and optional ``category``.
    """
    bridge = _get_bridge(hass)
    entity_reg = er.async_get(hass)
    primary_entry = entity_reg.async_get(msg["entity_id"])

    if not primary_entry:
        connection.send_result(msg["id"], {"candidates": [], "allowed_roles": [], "category": ""})
        return

    # Resolve primary entity: bridge instance > auto-detect via factory
    primary_category = msg.get("category", "")
    primary_entity = None
    if bridge:
        primary_entity = bridge.entities.get(msg["entity_id"])
        if primary_entity and not primary_category:
            primary_category = primary_entity.category
    if not primary_category:
        from .sber_entity_map import create_sber_entity

        entity_data = {
            "entity_id": primary_entry.entity_id,
            "original_device_class": primary_entry.original_device_class or "",
        }
        primary_entity = create_sber_entity(msg["entity_id"], entity_data)
        if primary_entity:
            primary_category = primary_entity.category

    # Linkable roles are declared on the device class itself
    linkable_roles: tuple[LinkableRole, ...] = ()
    if primary_entity is not None:
        linkable_roles = primary_entity.LINKABLE_ROLES
    allowed_roles = [lr.role for lr in linkable_roles]

    # Collect existing links for pre-selection
    existing_links: dict[str, str] = {}
    if bridge:
        existing_links = bridge.entity_links.get(msg["entity_id"], {})

    # Build candidates: siblings first, then compatible from other devices
    candidates: list[dict[str, Any]] = []
    primary_device_id = primary_entry.device_id
    same_device_only = msg.get("same_device_only", False)

    for e in entity_reg.entities.values():
        if e.entity_id == msg["entity_id"]:
            continue
        if e.disabled:
            continue

        dc = e.original_device_class or ""

        # Check if any of the primary's linkable roles match this candidate
        compatible = False
        suggested_role = ""
        for lr in linkable_roles:
            if lr.matches(e.domain, dc):
                suggested_role = lr.role
                compatible = True
                break

        # Fallback: resolve role for display (greyed-out incompatible candidates)
        if not suggested_role:
            suggested_role = resolve_link_role(e.domain, dc)

        # Skip entities that don't map to any link role (unless already linked)
        if not suggested_role and e.entity_id not in existing_links.values():
            continue

        same_device = bool(primary_device_id and e.device_id == primary_device_id)

        # When same_device_only is set (wizard mode), skip entities from other devices
        if same_device_only and not same_device:
            continue

        state = hass.states.get(e.entity_id)
        friendly_name = ""
        if state and state.attributes:
            friendly_name = state.attributes.get("friendly_name", "")

        candidates.append(
            {
                "entity_id": e.entity_id,
                "domain": e.domain,
                "device_class": dc,
                "friendly_name": friendly_name or e.name or e.original_name or e.entity_id,
                "suggested_role": suggested_role,
                "compatible": compatible,
                "same_device": same_device,
                "currently_linked": e.entity_id in existing_links.values(),
                "linked_role": next((r for r, eid in existing_links.items() if eid == e.entity_id), ""),
            }
        )

    # Sort: same-device first, then compatible first, then by name
    candidates.sort(key=lambda c: (not c["same_device"], not c["compatible"], c["friendly_name"]))

    connection.send_result(
        msg["id"],
        {
            "candidates": candidates,
            "allowed_roles": allowed_roles,
            "category": primary_category,
        },
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "sber_mqtt_bridge/auto_link_all",
    }
)
@websocket_api.async_response
async def ws_auto_link_all(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Auto-link all exposed entities by shared device_id.

    Groups exposed entities by device_id, finds auxiliary sensors
    (battery, humidity, temperature, signal), and links them to
    the primary entity in each group.

    Args:
        hass: Home Assistant core instance.
        connection: Active WebSocket connection.
        msg: Incoming WebSocket message.
    """
    entry = _get_config_entry(hass)
    bridge = _get_bridge(hass)
    if entry is None or bridge is None:
        connection.send_error(msg["id"], "not_found", "Bridge or config entry not found")
        return

    entity_reg = er.async_get(hass)
    all_links: dict[str, dict[str, str]] = dict(entry.options.get(CONF_ENTITY_LINKS, {}))
    linked_count = 0

    # Group exposed entities by device_id
    for primary_id, primary_entity in bridge.entities.items():
        primary_reg = entity_reg.async_get(primary_id)
        if not primary_reg or not primary_reg.device_id:
            continue
        if primary_id in all_links:
            continue  # Already has links

        linkable_roles = primary_entity.LINKABLE_ROLES
        if not linkable_roles:
            continue

        # Find siblings on same device
        new_links: dict[str, str] = {}
        for e in entity_reg.entities.values():
            if e.device_id != primary_reg.device_id:
                continue
            if e.entity_id == primary_id:
                continue
            if e.disabled:
                continue
            dc = e.original_device_class or ""
            for lr in linkable_roles:
                if lr.matches(e.domain, dc) and lr.role not in new_links:
                    new_links[lr.role] = e.entity_id
                    break

        if new_links:
            all_links[primary_id] = new_links
            linked_count += len(new_links)

    if linked_count > 0:
        new_options = dict(entry.options)
        new_options[CONF_ENTITY_LINKS] = all_links
        hass.config_entries.async_update_entry(entry, options=new_options)
        await hass.config_entries.async_reload(entry.entry_id)

    connection.send_result(
        msg["id"],
        {
            "linked_count": linked_count,
            "devices_affected": sum(1 for v in all_links.values() if v),
        },
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "sber_mqtt_bridge/add_device_wizard",
        vol.Required("entity_id"): str,
        vol.Required("category"): str,
        vol.Optional("entity_links", default={}): dict,
    }
)
@websocket_api.async_response
async def ws_add_device_wizard(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Atomic wizard action: add entity + set category override + set links in one reload.

    Combines add_entities, set_type_override, and set_entity_links into a single
    options update and reload to avoid triple-reload race conditions.

    Args:
        hass: Home Assistant core instance.
        connection: Active WebSocket connection.
        msg: Message with ``entity_id``, ``category``, and optional ``entity_links``.
    """
    entry = _get_config_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "entry_not_found", "Config entry not found")
        return

    entity_id: str = msg["entity_id"]
    category: str = msg["category"]
    entity_links: dict[str, str] = msg.get("entity_links", {})

    new_options = dict(entry.options)

    # 1. Add entity to exposed list
    exposed: list[str] = list(new_options.get(CONF_EXPOSED_ENTITIES, []))
    if entity_id not in exposed:
        exposed.append(entity_id)
    new_options[CONF_EXPOSED_ENTITIES] = exposed

    # 2. Set category override
    overrides: dict[str, str] = dict(new_options.get(CONF_ENTITY_TYPE_OVERRIDES, {}))
    if category and category != "auto":
        overrides[entity_id] = category
    else:
        overrides.pop(entity_id, None)
    new_options[CONF_ENTITY_TYPE_OVERRIDES] = overrides

    # 3. Set entity links
    if entity_links:
        all_links: dict[str, dict] = dict(new_options.get(CONF_ENTITY_LINKS, {}))
        all_links[entity_id] = entity_links
        new_options[CONF_ENTITY_LINKS] = all_links

    # Single atomic update + reload
    hass.config_entries.async_update_entry(entry, options=new_options)
    await hass.config_entries.async_reload(entry.entry_id)

    connection.send_result(
        msg["id"],
        {
            "success": True,
            "entity_id": entity_id,
            "category": category,
            "links_count": len(entity_links),
        },
    )


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


@websocket_api.websocket_command(
    {
        vol.Required("type"): "sber_mqtt_bridge/get_settings",
    }
)
@callback
def ws_get_settings(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return current bridge operational settings with their defaults.

    Args:
        hass: Home Assistant core instance.
        connection: Active WebSocket connection.
        msg: Incoming WebSocket message dict.
    """
    entry = _get_config_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_found", "Config entry not found")
        return

    settings: dict[str, Any] = {}
    for key, default in SETTINGS_DEFAULTS.items():
        if key == CONF_SBER_VERIFY_SSL:
            settings[key] = entry.options.get(key, entry.data.get(key, default))
        else:
            settings[key] = entry.options.get(key, default)

    connection.send_result(msg["id"], {"settings": settings, "defaults": dict(SETTINGS_DEFAULTS)})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "sber_mqtt_bridge/update_settings",
        vol.Required("settings"): dict,
    }
)
@websocket_api.async_response
async def ws_update_settings(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Save bridge operational settings to config entry options.

    Only known keys from SETTINGS_DEFAULTS are accepted. Changes are applied
    to the running bridge immediately where possible.

    Args:
        hass: Home Assistant core instance.
        connection: Active WebSocket connection.
        msg: Incoming WebSocket message dict with 'settings' payload.
    """
    entry = _get_config_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_found", "Config entry not found")
        return

    new_options = dict(entry.options)
    valid_keys = set(SETTINGS_DEFAULTS.keys())
    new_options.update({k: v for k, v in msg["settings"].items() if k in valid_keys})

    hass.config_entries.async_update_entry(entry, options=new_options)

    bridge = _get_bridge(hass)
    if bridge is not None:
        bridge.apply_settings(new_options)

    connection.send_result(msg["id"], {"success": True})


# ---------------------------------------------------------------------------
# Raw JSON send to Sber (DevTools)
# ---------------------------------------------------------------------------


@websocket_api.websocket_command(
    {
        vol.Required("type"): "sber_mqtt_bridge/send_raw_config",
        vol.Required("payload"): str,
    }
)
@websocket_api.async_response
async def ws_send_raw_config(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Send arbitrary JSON config payload to Sber MQTT broker.

    Args:
        hass: Home Assistant core instance.
        connection: Active WebSocket connection.
        msg: Incoming message with 'payload' JSON string.
    """
    await _send_raw(hass, connection, msg, "config")


@websocket_api.websocket_command(
    {
        vol.Required("type"): "sber_mqtt_bridge/send_raw_state",
        vol.Required("payload"): str,
    }
)
@websocket_api.async_response
async def ws_send_raw_state(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Send arbitrary JSON state payload to Sber MQTT broker.

    Args:
        hass: Home Assistant core instance.
        connection: Active WebSocket connection.
        msg: Incoming message with 'payload' JSON string.
    """
    await _send_raw(hass, connection, msg, "status")


async def _send_raw(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    target: str,
) -> None:
    """Validate and publish raw JSON to Sber MQTT.

    Args:
        hass: Home Assistant core instance.
        connection: Active WebSocket connection.
        msg: Incoming message with 'payload'.
        target: MQTT topic suffix ("config" or "status").
    """
    bridge = _get_bridge(hass)
    if bridge is None:
        connection.send_error(msg["id"], "bridge_not_found", "Bridge not available")
        return

    try:
        json.loads(msg["payload"])
    except json.JSONDecodeError as exc:
        connection.send_error(msg["id"], "invalid_json", str(exc))
        return

    try:
        await bridge.async_publish_raw(msg["payload"], target)
    except RuntimeError as exc:
        connection.send_error(msg["id"], "not_connected", str(exc))
        return

    connection.send_result(msg["id"], {"success": True})


# ---------------------------------------------------------------------------
# WebSocket push for MQTT message log (DevTools)
# ---------------------------------------------------------------------------


@websocket_api.websocket_command(
    {
        vol.Required("type"): "sber_mqtt_bridge/subscribe_messages",
    }
)
@callback
def ws_subscribe_messages(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Subscribe to real-time MQTT message log updates.

    Sends initial snapshot of current log, then pushes each new message
    as an event. Automatically unsubscribes on WebSocket disconnect.

    Args:
        hass: Home Assistant core instance.
        connection: Active WebSocket connection.
        msg: Incoming WebSocket message dict.
    """
    bridge = _get_bridge(hass)
    if bridge is None:
        connection.send_error(msg["id"], "bridge_not_found", "Bridge not available")
        return

    # ACK subscription
    connection.send_result(msg["id"])

    # Send initial snapshot as first event
    connection.send_message(
        websocket_api.event_message(msg["id"], {"snapshot": bridge.message_log})
    )

    # Subscribe to new messages
    @callback
    def forward_message(message_data: dict) -> None:
        connection.send_message(
            websocket_api.event_message(msg["id"], {"message": message_data})
        )

    unsub = bridge.subscribe_messages(forward_message)
    connection.subscriptions[msg["id"]] = unsub
