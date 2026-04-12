"""Entity linking commands.

Covers post-add link management (``ws_set_entity_links``,
``ws_auto_link_all``) for entities that are already exposed.  The
initial linking during device add is handled by the device-centric
wizard commands in :mod:`.devices_grouped`.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from ..const import CONF_ENTITY_LINKS, CONF_EXPOSED_ENTITIES
from ._common import get_bridge, get_config_entry

_LOGGER = logging.getLogger(__name__)


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
    """Set linked entities for a primary entity."""
    entry = get_config_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "entry_not_found", "Config entry not found")
        return

    entity_id: str = msg["entity_id"]
    new_links: dict[str, str] = msg["links"]

    exposed = set(entry.options.get(CONF_EXPOSED_ENTITIES, []))
    if entity_id not in exposed:
        connection.send_error(msg["id"], "not_exposed", f"{entity_id} is not in exposed entities")
        return

    existing_links = dict(entry.options.get(CONF_ENTITY_LINKS, {}))
    for linked_id in new_links.values():
        if linked_id in existing_links:
            connection.send_error(
                msg["id"],
                "circular_link",
                f"{linked_id} is already a primary entity with links — cannot link it",
            )
            return
        if linked_id == entity_id:
            connection.send_error(msg["id"], "self_link", "Cannot link entity to itself")
            return

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
        vol.Required("type"): "sber_mqtt_bridge/auto_link_all",
    }
)
@websocket_api.async_response
async def ws_auto_link_all(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Auto-link all exposed entities by shared device_id."""
    entry = get_config_entry(hass)
    bridge = get_bridge(hass)
    if entry is None or bridge is None:
        connection.send_error(msg["id"], "not_found", "Bridge or config entry not found")
        return

    entity_reg = er.async_get(hass)
    all_links: dict[str, dict[str, str]] = dict(entry.options.get(CONF_ENTITY_LINKS, {}))
    linked_count = 0

    for primary_id, primary_entity in bridge.entities.items():
        primary_reg = entity_reg.async_get(primary_id)
        if not primary_reg or not primary_reg.device_id:
            continue
        if primary_id in all_links:
            continue

        linkable_roles = primary_entity.LINKABLE_ROLES
        if not linkable_roles:
            continue

        new_links: dict[str, str] = {}
        for e in entity_reg.entities.values():
            if e.device_id != primary_reg.device_id or e.entity_id == primary_id:
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
