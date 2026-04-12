"""Export / import / redefinition WebSocket commands."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from ..const import (
    CONF_ENTITY_LINKS,
    CONF_ENTITY_TYPE_OVERRIDES,
    CONF_EXPOSED_ENTITIES,
)
from ._common import get_bridge, get_config_entry

_LOGGER = logging.getLogger(__name__)


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
    """Export the full device configuration as JSON."""
    entry = get_config_entry(hass)
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
    """Import a device configuration from a JSON payload."""
    entry = get_config_entry(hass)
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


@websocket_api.websocket_command(
    {
        vol.Required("type"): "sber_mqtt_bridge/update_redefinitions",
        vol.Required("entity_id"): str,
        vol.Optional("name"): str,
        vol.Optional("room"): str,
        vol.Optional("home"): str,
    }
)
@websocket_api.async_response
async def ws_update_redefinitions(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Update Sber redefinitions (name/room/home) for a single device.

    Delegates to :meth:`SberBridge.async_update_redefinition` — all
    private-state mutations live in the bridge, not here (encapsulation).
    """
    bridge = get_bridge(hass)
    if bridge is None:
        connection.send_error(msg["id"], "bridge_not_found", "Bridge not available")
        return

    entity_id: str = msg["entity_id"]
    fields = {k: msg[k] for k in ("name", "room", "home") if k in msg}
    try:
        existing = await bridge.async_update_redefinition(entity_id, fields)
    except KeyError:
        connection.send_error(
            msg["id"], "not_found", f"Entity {entity_id} not in bridge"
        )
        return
    except HomeAssistantError:
        _LOGGER.exception("Re-publish after redefinition update failed")
        connection.send_error(
            msg["id"], "publish_failed", "Republish after update failed"
        )
        return

    connection.send_result(
        msg["id"], {"entity_id": entity_id, "redefinitions": existing}
    )
