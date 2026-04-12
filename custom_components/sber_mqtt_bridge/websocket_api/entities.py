"""Entity management commands (add, remove, override, bulk, clear, available)."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from ..const import (
    CONF_ENTITY_LINKS,
    CONF_ENTITY_TYPE_OVERRIDES,
    CONF_EXPOSED_ENTITIES,
    SUPPORTED_DOMAINS,
)
from ._common import get_bridge, get_config_entry

_LOGGER = logging.getLogger(__name__)


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
    """Get all HA entities available for export to Sber."""
    entry = get_config_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "entry_not_found", "Config entry not found")
        return

    exposed: list[str] = list(entry.options.get(CONF_EXPOSED_ENTITIES, []))
    exposed_set = set(exposed)

    bridge = get_bridge(hass)
    linked_ids = bridge.linked_entity_ids if bridge else set()

    registry = er.async_get(hass)
    device_reg = dr.async_get(hass)
    area_reg = ar.async_get(hass)
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

        raw_area = entity_entry.area_id
        if not raw_area and entity_entry.device_id:
            device = device_reg.async_get(entity_entry.device_id)
            if device:
                raw_area = device.area_id
        area_obj = area_reg.async_get_area(raw_area) if raw_area else None
        area_name = area_obj.name if area_obj else ""

        entities.append(
            {
                "entity_id": entity_entry.entity_id,
                "domain": domain,
                "device_class": entity_entry.original_device_class or "",
                "friendly_name": friendly_name or entity_entry.name or entity_entry.original_name or "",
                "area": area_name,
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
    """Add entities to the exposed list and reload the integration."""
    entry = get_config_entry(hass)
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
    """Remove entities from the exposed list and reload the integration."""
    entry = get_config_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "entry_not_found", "Config entry not found")
        return

    to_remove = set(msg["entity_ids"])
    current: list[str] = list(entry.options.get(CONF_EXPOSED_ENTITIES, []))
    new_list = [eid for eid in current if eid not in to_remove]
    removed = len(current) - len(new_list)

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
    """
    entry = get_config_entry(hass)
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
    """Bulk add entities by domain or all supported domains."""
    entry = get_config_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "entry_not_found", "Config entry not found")
        return

    target_domains = msg.get("domains") or list(SUPPORTED_DOMAINS)
    current: list[str] = list(entry.options.get(CONF_EXPOSED_ENTITIES, []))
    current_set = set(current)

    from ..config_flow import _get_entities_by_domains

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
    """Remove all entities from the exposed list and clear overrides."""
    entry = get_config_entry(hass)
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
