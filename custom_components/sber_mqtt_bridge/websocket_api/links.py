"""Entity linking commands (set, suggest, auto-link, wizard)."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from ..const import (
    CONF_ENTITY_LINKS,
    CONF_ENTITY_TYPE_OVERRIDES,
    CONF_EXPOSED_ENTITIES,
)
from ..devices.base_entity import LinkableRole, resolve_link_role
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
    """Suggest linkable entities for a primary entity."""
    bridge = get_bridge(hass)
    entity_reg = er.async_get(hass)
    primary_entry = entity_reg.async_get(msg["entity_id"])

    if not primary_entry:
        connection.send_result(msg["id"], {"candidates": [], "allowed_roles": [], "category": ""})
        return

    primary_category = msg.get("category", "")
    primary_entity = None
    if bridge:
        primary_entity = bridge.entities.get(msg["entity_id"])
        if primary_entity and not primary_category:
            primary_category = primary_entity.category

    if primary_entity is None:
        from ..sber_entity_map import create_sber_entity

        entity_data = {
            "entity_id": primary_entry.entity_id,
            "original_device_class": primary_entry.original_device_class or "",
        }
        primary_entity = create_sber_entity(
            msg["entity_id"], entity_data, sber_category=primary_category or None,
        )
        if primary_entity and not primary_category:
            primary_category = primary_entity.category

    linkable_roles: tuple[LinkableRole, ...] = ()
    if primary_entity is not None:
        linkable_roles = primary_entity.LINKABLE_ROLES
    allowed_roles = [lr.role for lr in linkable_roles]

    existing_links: dict[str, str] = {}
    if bridge:
        existing_links = bridge.entity_links.get(msg["entity_id"], {})

    candidates: list[dict[str, Any]] = []
    primary_device_id = primary_entry.device_id
    same_device_only = msg.get("same_device_only", False)

    for e in entity_reg.entities.values():
        if e.entity_id == msg["entity_id"] or e.disabled:
            continue

        dc = e.original_device_class or ""
        same_device = bool(primary_device_id and e.device_id == primary_device_id)

        compatible = False
        suggested_role = ""
        for lr in linkable_roles:
            if lr.matches(e.domain, dc):
                suggested_role = lr.role
                compatible = True
                break

        if not suggested_role:
            suggested_role = resolve_link_role(e.domain, dc)

        if same_device and suggested_role:
            compatible = True

        if not suggested_role and e.entity_id not in existing_links.values():
            continue

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
                "linked_role": next(
                    (r for r, eid in existing_links.items() if eid == e.entity_id), ""
                ),
            }
        )

    candidates.sort(
        key=lambda c: (not c["same_device"], not c["compatible"], c["friendly_name"])
    )

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


@websocket_api.websocket_command(
    {
        vol.Required("type"): "sber_mqtt_bridge/add_device_wizard",
        vol.Required("entity_id"): str,
        vol.Required("category"): str,
        vol.Optional("entity_links", default={}): dict,
        vol.Optional("name"): str,
        vol.Optional("room"): str,
    }
)
@websocket_api.async_response
async def ws_add_device_wizard(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Atomic wizard action: add entity + set category override + set links."""
    entry = get_config_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "entry_not_found", "Config entry not found")
        return

    entity_id: str = msg["entity_id"]
    category: str = msg["category"]
    entity_links: dict[str, str] = msg.get("entity_links", {})

    new_options = dict(entry.options)

    exposed: list[str] = list(new_options.get(CONF_EXPOSED_ENTITIES, []))
    if entity_id not in exposed:
        exposed.append(entity_id)
    new_options[CONF_EXPOSED_ENTITIES] = exposed

    overrides: dict[str, str] = dict(new_options.get(CONF_ENTITY_TYPE_OVERRIDES, {}))
    if category and category != "auto":
        overrides[entity_id] = category
    else:
        overrides.pop(entity_id, None)
    new_options[CONF_ENTITY_TYPE_OVERRIDES] = overrides

    if entity_links:
        all_links: dict[str, dict] = dict(new_options.get(CONF_ENTITY_LINKS, {}))
        all_links[entity_id] = entity_links
        new_options[CONF_ENTITY_LINKS] = all_links

    wizard_name = msg.get("name", "").strip()
    wizard_room = msg.get("room", "").strip()
    if wizard_name or wizard_room:
        redefs: dict[str, dict] = dict(new_options.get("redefinitions", {}))
        entity_redef = dict(redefs.get(entity_id, {}))
        if wizard_name:
            entity_redef["name"] = wizard_name
        if wizard_room:
            entity_redef["room"] = wizard_room
        redefs[entity_id] = entity_redef
        new_options["redefinitions"] = redefs

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
