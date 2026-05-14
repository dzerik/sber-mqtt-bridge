"""MQTT message log WebSocket commands (get, clear, subscribe)."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from ._common import get_bridge, requires_bridge  # noqa: F401 — get_bridge re-exported for test patching

_LOGGER = logging.getLogger(__name__)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "sber_mqtt_bridge/message_log",
    }
)
@callback
@requires_bridge
def ws_message_log(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    bridge: Any,
) -> None:
    """Return the recent MQTT message log from the ring buffer."""
    connection.send_result(msg["id"], {"messages": bridge.message_log})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "sber_mqtt_bridge/clear_message_log",
    }
)
@callback
@requires_bridge
def ws_clear_message_log(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    bridge: Any,
) -> None:
    """Clear the MQTT message log ring buffer."""
    bridge.clear_message_log()
    connection.send_result(msg["id"], {"success": True})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "sber_mqtt_bridge/subscribe_messages",
    }
)
@callback
@requires_bridge
def ws_subscribe_messages(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    bridge: Any,
) -> None:
    """Subscribe to real-time MQTT message log updates."""
    connection.send_result(msg["id"])

    connection.send_message(websocket_api.event_message(msg["id"], {"snapshot": bridge.message_log}))

    @callback
    def forward_message(message_data: dict) -> None:
        connection.send_message(websocket_api.event_message(msg["id"], {"message": message_data}))

    unsub = bridge.subscribe_messages(forward_message)
    connection.subscriptions[msg["id"]] = unsub
