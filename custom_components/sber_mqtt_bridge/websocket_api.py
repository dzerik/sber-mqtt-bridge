"""WebSocket API for Sber MQTT Bridge panel.

Provides real-time device and connection data to the frontend SPA panel
via Home Assistant native WebSocket commands, including entity management
(add, remove, override, bulk operations).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_ENTITY_TYPE_OVERRIDES,
    CONF_EXPOSED_ENTITIES,
    DOMAIN,
    SUPPORTED_DOMAINS,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

    from .sber_bridge import SberBridge

_LOGGER = logging.getLogger(__name__)


def _get_bridge(hass: HomeAssistant) -> SberBridge | None:
    """Get the active SberBridge instance from hass.data.

    Returns:
        The SberBridge instance, or None if not available.
    """
    data = hass.data.get(DOMAIN, {})
    return data.get("bridge")


def _get_config_entry(hass: HomeAssistant) -> ConfigEntry | None:
    """Get the first config entry for the Sber MQTT Bridge domain.

    Returns:
        The ConfigEntry instance, or None if not found.
    """
    entries = hass.config_entries.async_entries(DOMAIN)
    return entries[0] if entries else None


@callback
def async_setup_websocket_api(hass: HomeAssistant) -> None:
    """Register WebSocket API commands for the Sber MQTT Bridge panel.

    Args:
        hass: Home Assistant core instance.
    """
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
    for eid, entity in bridge.entities.items():
        features = (
            entity.get_final_features_list()
            if hasattr(entity, "get_final_features_list")
            else entity.create_features_list()
        )
        devices.append(
            {
                "entity_id": eid,
                "sber_category": entity.category,
                "features": features,
                "name": entity.name,
                "room": getattr(entity, "area_id", ""),
                "is_online": entity._is_online,
                "state": entity.state,
                "is_filled": entity.is_filled_by_state,
            }
        )

    acknowledged = bridge.stats.get("acknowledged_entities", [])
    unacknowledged = bridge.unacknowledged_entities

    connection.send_result(
        msg["id"],
        {
            "devices": devices,
            "total": len(devices),
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

    connection.send_result(
        msg["id"],
        {
            "connected": bridge.is_connected,
            "stats": bridge.stats,
            "entities_count": bridge.entities_count,
            "unacknowledged": bridge.unacknowledged_entities,
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

    await bridge._publish_config()
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

        state = hass.states.get(entity_entry.entity_id)
        friendly_name = ""
        if state and state.attributes:
            friendly_name = state.attributes.get("friendly_name", "")

        entities.append(
            {
                "entity_id": entity_entry.entity_id,
                "domain": domain,
                "device_class": entity_entry.device_class or entity_entry.original_device_class or "",
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

    # Also clean up type overrides for removed entities
    overrides: dict[str, str] = dict(entry.options.get(CONF_ENTITY_TYPE_OVERRIDES, {}))
    for eid in to_remove:
        overrides.pop(eid, None)

    if removed > 0:
        new_options = dict(entry.options)
        new_options[CONF_EXPOSED_ENTITIES] = new_list
        new_options[CONF_ENTITY_TYPE_OVERRIDES] = overrides
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
    target_domains_set = set(target_domains)

    current: list[str] = list(entry.options.get(CONF_EXPOSED_ENTITIES, []))
    current_set = set(current)

    registry = er.async_get(hass)
    added: list[str] = []

    for entity_entry in registry.entities.values():
        if entity_entry.disabled:
            continue
        if entity_entry.domain not in target_domains_set:
            continue
        if entity_entry.entity_id in current_set:
            continue
        current.append(entity_entry.entity_id)
        current_set.add(entity_entry.entity_id)
        added.append(entity_entry.entity_id)

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

    await bridge._publish_states([msg["entity_id"]])
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
            "version": 1,
            "exposed_entities": list(entry.options.get(CONF_EXPOSED_ENTITIES, [])),
            "type_overrides": dict(entry.options.get(CONF_ENTITY_TYPE_OVERRIDES, {})),
            "redefinitions": dict(entry.options.get("redefinitions", {})),
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

    hass.config_entries.async_update_entry(entry, options=new_options)
    await hass.config_entries.async_reload(entry.entry_id)

    connection.send_result(msg["id"], {"success": True})
