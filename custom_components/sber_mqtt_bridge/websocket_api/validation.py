"""Schema-validation WebSocket commands (DevTools #4).

Frontend counterpart to
:mod:`custom_components.sber_mqtt_bridge.schema_validator`.  Returns
both the chronological ring buffer of issues and the latest-per-entity
map so the UI can render "what happened" and "what is broken right
now" without two round-trips.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from ._common import get_bridge

_LOGGER = logging.getLogger(__name__)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "sber_mqtt_bridge/validation_issues",
    }
)
@callback
def ws_list_validation_issues(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return the full snapshot (recent + by_entity)."""
    bridge = get_bridge(hass)
    if bridge is None:
        connection.send_error(msg["id"], "bridge_not_found", "Bridge not available")
        return
    connection.send_result(msg["id"], bridge.validation_collector.snapshot())


@websocket_api.websocket_command(
    {
        vol.Required("type"): "sber_mqtt_bridge/clear_validation_issues",
    }
)
@callback
def ws_clear_validation_issues(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Drop all recorded validation issues."""
    bridge = get_bridge(hass)
    if bridge is None:
        connection.send_error(msg["id"], "bridge_not_found", "Bridge not available")
        return
    bridge.validation_collector.clear()
    connection.send_result(msg["id"], {"success": True})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "sber_mqtt_bridge/subscribe_validation_issues",
    }
)
@callback
def ws_subscribe_validation_issues(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Stream validation bursts to the subscriber.

    Sends the initial snapshot, then one event per publish that
    produces issues.  A "clean" publish (no issues) does NOT trigger
    an event — the per-entity snapshot is still updated but the UI
    learns about it only on next re-fetch / subscribe.
    """
    bridge = get_bridge(hass)
    if bridge is None:
        connection.send_error(msg["id"], "bridge_not_found", "Bridge not available")
        return

    connection.send_result(msg["id"])
    connection.send_message(
        websocket_api.event_message(msg["id"], {"snapshot": bridge.validation_collector.snapshot()})
    )

    @callback
    def forward(issues: list[Any]) -> None:
        connection.send_message(websocket_api.event_message(msg["id"], {"issues": [i.as_dict() for i in issues]}))

    unsub = bridge.validation_collector.subscribe(forward)
    connection.subscriptions[msg["id"]] = unsub
