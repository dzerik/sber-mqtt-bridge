"""Export / import / redefinition WebSocket commands."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv

from ..const import (
    CONF_ENTITY_LINKS,
    CONF_ENTITY_TYPE_OVERRIDES,
    CONF_EXPOSED_ENTITIES,
)
from ._common import (  # noqa: F401 — get_bridge/get_config_entry re-exported for test patching
    OVERRIDABLE_CATEGORIES,
    WS_ENTITY_ID,
    get_bridge,
    get_config_entry,
    requires_bridge,
    requires_entry,
)

_LOGGER = logging.getLogger(__name__)


IMPORT_CONFIG_SCHEMA = vol.Schema(
    {
        vol.Optional("exposed_entities"): [cv.entity_id],
        vol.Optional("type_overrides"): vol.Schema({cv.entity_id: vol.In(OVERRIDABLE_CATEGORIES)}),
        vol.Optional("redefinitions"): vol.Schema(
            # strict ``str`` — cv.string would coerce numbers into strings
            {cv.entity_id: vol.Schema({vol.Any("name", "room", "home"): str})}
        ),
        vol.Optional("entity_links"): vol.Schema({cv.entity_id: vol.Schema({cv.string: cv.entity_id})}),
    },
    extra=vol.ALLOW_EXTRA,  # tolerate "version" and future metadata keys
)
"""Structural schema for the ``import`` payload.

Everything written to ``entry.options`` survives a full
``async_setup_entry``; a malformed import (e.g. ``entity_links`` as a
list, or string ``redefinitions`` values) would crash entity loading on
every subsequent reload, leaving the integration dead and the panel —
including a corrective re-import — unreachable.  Validate first, write
never on error."""


@websocket_api.websocket_command(
    {
        vol.Required("type"): "sber_mqtt_bridge/export",
    }
)
@websocket_api.async_response
@requires_entry
async def ws_export(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    entry: Any,
) -> None:
    """Export the full device configuration as JSON."""
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
@requires_entry
async def ws_import(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    entry: Any,
) -> None:
    """Import a device configuration from a JSON payload.

    The payload structure is validated against
    :data:`IMPORT_CONFIG_SCHEMA` *before* anything is persisted — on
    error the handler replies ``invalid_config`` and leaves
    ``entry.options`` untouched (no reload is triggered).
    """
    try:
        config: dict[str, Any] = IMPORT_CONFIG_SCHEMA(msg["config"])
    except vol.Invalid as err:
        connection.send_error(msg["id"], "invalid_config", f"Invalid import payload: {err}")
        return

    new_options = dict(entry.options)

    if "exposed_entities" in config:
        new_options[CONF_EXPOSED_ENTITIES] = config["exposed_entities"]
    if "type_overrides" in config:
        new_options[CONF_ENTITY_TYPE_OVERRIDES] = config["type_overrides"]
    if "redefinitions" in config:
        # TODO(v1.38.4): route through RedefinitionsStore once it exists
        # (docs/superpowers/plans/2026-05-14-v1.38.4-redefinitions-store.md) —
        # direct writes to the magic "redefinitions" options key can be
        # overwritten by the store's debounced flush.
        new_options["redefinitions"] = config["redefinitions"]
    if "entity_links" in config:
        new_options[CONF_ENTITY_LINKS] = config["entity_links"]

    hass.config_entries.async_update_entry(entry, options=new_options)
    await hass.config_entries.async_reload(entry.entry_id)

    connection.send_result(msg["id"], {"success": True})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "sber_mqtt_bridge/update_redefinitions",
        vol.Required("entity_id"): WS_ENTITY_ID,
        vol.Optional("name"): str,
        vol.Optional("room"): str,
        vol.Optional("home"): str,
    }
)
@websocket_api.async_response
@requires_bridge
async def ws_update_redefinitions(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    bridge: Any,
) -> None:
    """Update Sber redefinitions (name/room/home) for a single device.

    Delegates to :meth:`SberBridge.async_update_redefinition` — all
    private-state mutations live in the bridge, not here (encapsulation).
    """
    entity_id: str = msg["entity_id"]
    fields = {k: msg[k] for k in ("name", "room", "home") if k in msg}
    try:
        existing = await bridge.async_update_redefinition(entity_id, fields)
    except KeyError:
        connection.send_error(msg["id"], "not_found", f"Entity {entity_id} not in bridge")
        return
    except HomeAssistantError:
        _LOGGER.exception("Re-publish after redefinition update failed")
        connection.send_error(msg["id"], "publish_failed", "Republish after update failed")
        return

    connection.send_result(msg["id"], {"entity_id": entity_id, "redefinitions": existing})
