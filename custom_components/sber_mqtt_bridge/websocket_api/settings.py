"""Bridge-settings WebSocket commands (get / update)."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from ..const import CONF_SBER_VERIFY_SSL, SETTINGS_DEFAULTS
from ._common import get_bridge, get_config_entry

_LOGGER = logging.getLogger(__name__)


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
    """Return current bridge operational settings with their defaults."""
    entry = get_config_entry(hass)
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
    """Save bridge operational settings to config entry options."""
    entry = get_config_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_found", "Config entry not found")
        return

    new_options = dict(entry.options)
    valid_keys = set(SETTINGS_DEFAULTS.keys())
    new_options.update({k: v for k, v in msg["settings"].items() if k in valid_keys})

    hass.config_entries.async_update_entry(entry, options=new_options)

    bridge = get_bridge(hass)
    if bridge is not None:
        bridge.apply_settings(new_options)

    connection.send_result(msg["id"], {"success": True})
