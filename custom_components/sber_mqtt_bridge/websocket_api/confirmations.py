"""Command-confirmation WebSocket commands (list / subscribe / clear).

Frontend counterpart to :mod:`custom_components.sber_mqtt_bridge.command_confirm`:
for every Sber command, which keys the state published back to Sber has
confirmed.  Same snapshot-then-live pattern as :mod:`.traces`.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from ._common import get_bridge, requires_bridge  # noqa: F401 — get_bridge re-exported for test patching

_LOGGER = logging.getLogger(__name__)


@websocket_api.websocket_command({vol.Required("type"): "sber_mqtt_bridge/command_confirmations"})
@callback
@requires_bridge
def ws_command_confirmations(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    bridge: Any,
) -> None:
    """Return recent command confirmations (closed, then pending)."""
    connection.send_result(msg["id"], {"commands": bridge.command_confirm.snapshot()})


@websocket_api.websocket_command({vol.Required("type"): "sber_mqtt_bridge/clear_command_confirmations"})
@callback
@requires_bridge
def ws_clear_command_confirmations(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    bridge: Any,
) -> None:
    """Drop all tracked command confirmations."""
    bridge.command_confirm.clear()
    connection.send_result(msg["id"], {"success": True})


@websocket_api.websocket_command({vol.Required("type"): "sber_mqtt_bridge/subscribe_command_confirmations"})
@callback
@requires_bridge
def ws_subscribe_command_confirmations(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    bridge: Any,
) -> None:
    """Stream confirmation lifecycle events after an initial snapshot.

    Emits ``{"snapshot": [...]}`` once, then ``{"kind": ..., "command": ...}``
    for every ``command_started`` / ``command_updated`` / ``command_closed``.
    """
    tracker = bridge.command_confirm
    connection.send_result(msg["id"])
    connection.send_message(websocket_api.event_message(msg["id"], {"snapshot": tracker.snapshot()}))

    @callback
    def forward(kind: str, record: Any) -> None:
        connection.send_message(websocket_api.event_message(msg["id"], {"kind": kind, "command": record.as_dict()}))

    connection.subscriptions[msg["id"]] = tracker.subscribe(forward)
