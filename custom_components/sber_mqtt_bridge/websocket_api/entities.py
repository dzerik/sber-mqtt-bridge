"""Entity management commands (add, remove, override, clear).

Raw entity-level operations preserved for the Options Flow fallback
path and CLI scripting.  The device-centric wizard lives in
:mod:`.devices_grouped`.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant

from ..const import (
    CONF_ENTITY_LINKS,
    CONF_ENTITY_TYPE_OVERRIDES,
    CONF_EXPOSED_ENTITIES,
    CONF_GATE_OPTIONS,
)
from ..devices.gate import IMPULSE_SERVICE_OPTIONS
from ._common import (  # noqa: F401 — get_config_entry re-exported for test patching
    OVERRIDABLE_CATEGORIES,
    WS_ENTITY_ID,
    WS_ENTITY_IDS,
    get_config_entry,
    requires_entry,
)

_LOGGER = logging.getLogger(__name__)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "sber_mqtt_bridge/add_entities",
        vol.Required("entity_ids"): vol.All(WS_ENTITY_IDS, vol.Length(min=1)),
    }
)
@websocket_api.async_response
@requires_entry
async def ws_add_entities(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    entry: Any,
) -> None:
    """Add entities to the exposed list and reload the integration."""
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
        vol.Required("entity_ids"): vol.All(WS_ENTITY_IDS, vol.Length(min=1)),
    }
)
@websocket_api.async_response
@requires_entry
async def ws_remove_entities(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    entry: Any,
) -> None:
    """Remove entities from the exposed list and reload the integration."""
    to_remove = set(msg["entity_ids"])
    current: list[str] = list(entry.options.get(CONF_EXPOSED_ENTITIES, []))
    new_list = [eid for eid in current if eid not in to_remove]
    removed = len(current) - len(new_list)

    overrides: dict[str, str] = dict(entry.options.get(CONF_ENTITY_TYPE_OVERRIDES, {}))
    entity_links: dict[str, dict] = dict(entry.options.get(CONF_ENTITY_LINKS, {}))
    gate_options: dict[str, dict] = dict(entry.options.get(CONF_GATE_OPTIONS, {}))
    for eid in to_remove:
        overrides.pop(eid, None)
        entity_links.pop(eid, None)
        # Per-entity gate settings are removed together with the entity:
        # left behind, an inverted contact polarity would silently come
        # back the day the same entity is added again through the wizard.
        gate_options.pop(eid, None)

    if removed > 0:
        new_options = dict(entry.options)
        new_options[CONF_EXPOSED_ENTITIES] = new_list
        new_options[CONF_ENTITY_TYPE_OVERRIDES] = overrides
        new_options[CONF_ENTITY_LINKS] = entity_links
        new_options[CONF_GATE_OPTIONS] = gate_options
        hass.config_entries.async_update_entry(entry, options=new_options)
        await hass.config_entries.async_reload(entry.entry_id)

    connection.send_result(msg["id"], {"removed": removed, "total": len(new_list)})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "sber_mqtt_bridge/set_override",
        vol.Required("entity_id"): WS_ENTITY_ID,
        vol.Required("category"): vol.In(["auto", *OVERRIDABLE_CATEGORIES]),
    }
)
@websocket_api.async_response
@requires_entry
async def ws_set_type_override(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    entry: Any,
) -> None:
    """Set or clear the Sber category override for an entity.

    Pass ``category`` as ``"auto"`` to remove the override and use
    automatic detection.
    """
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
        vol.Required("type"): "sber_mqtt_bridge/update_gate_options",
        vol.Required("entity_id"): WS_ENTITY_ID,
        vol.Optional("invert_contact"): bool,
        vol.Optional("impulse_service"): vol.In(IMPULSE_SERVICE_OPTIONS),
    }
)
@websocket_api.async_response
@requires_entry
async def ws_update_gate_options(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    entry: Any,
) -> None:
    """Update impulse-gate options for a single entity (issue #53).

    Only the keys present in the payload are changed, so the panel can
    submit one toggle without resending the rest.  The entry is reloaded
    afterwards because the options are consumed while entities are being
    built (contact polarity must be applied before the first reading).
    """
    entity_id: str = msg["entity_id"]

    all_options: dict[str, dict] = dict(entry.options.get(CONF_GATE_OPTIONS, {}))
    entity_options: dict[str, Any] = dict(all_options.get(entity_id, {}))
    for key in ("invert_contact", "impulse_service"):
        if key in msg:
            entity_options[key] = msg[key]
    all_options[entity_id] = entity_options

    new_options = dict(entry.options)
    new_options[CONF_GATE_OPTIONS] = all_options
    hass.config_entries.async_update_entry(entry, options=new_options)
    await hass.config_entries.async_reload(entry.entry_id)

    connection.send_result(msg["id"], {"entity_id": entity_id, "gate_options": entity_options})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "sber_mqtt_bridge/clear_all",
    }
)
@websocket_api.async_response
@requires_entry
async def ws_clear_all(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    entry: Any,
) -> None:
    """Remove all entities from the exposed list and clear overrides."""
    new_options = dict(entry.options)
    previous_count = len(new_options.get(CONF_EXPOSED_ENTITIES, []))
    new_options[CONF_EXPOSED_ENTITIES] = []
    new_options[CONF_ENTITY_TYPE_OVERRIDES] = {}
    new_options[CONF_ENTITY_LINKS] = {}
    new_options[CONF_GATE_OPTIONS] = {}
    hass.config_entries.async_update_entry(entry, options=new_options)
    await hass.config_entries.async_reload(entry.entry_id)

    connection.send_result(msg["id"], {"removed": previous_count})
