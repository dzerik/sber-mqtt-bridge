"""State-diff WebSocket commands (list / clear / subscribe).

Frontend counterpart to
:mod:`custom_components.sber_mqtt_bridge.state_diff`.  Every handler
fetches the bridge's :class:`DiffCollector` via ``bridge.diff_collector``
and returns JSON-serializable snapshots; live updates fan out via
subscribe so the DevTools panel renders new diffs as they happen.
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
        vol.Required("type"): "sber_mqtt_bridge/state_diffs",
    }
)
@callback
def ws_list_state_diffs(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return a snapshot of recorded state diffs, oldest first."""
    bridge = get_bridge(hass)
    if bridge is None:
        connection.send_error(msg["id"], "bridge_not_found", "Bridge not available")
        return
    connection.send_result(msg["id"], {"diffs": bridge.diff_collector.snapshot()})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "sber_mqtt_bridge/clear_state_diffs",
    }
)
@callback
def ws_clear_state_diffs(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Drop all recorded diffs and the per-entity baseline."""
    bridge = get_bridge(hass)
    if bridge is None:
        connection.send_error(msg["id"], "bridge_not_found", "Bridge not available")
        return
    bridge.diff_collector.clear()
    connection.send_result(msg["id"], {"success": True})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "sber_mqtt_bridge/subscribe_state_diffs",
    }
)
@callback
def ws_subscribe_state_diffs(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Stream state diffs to the subscriber.

    Sends an initial ``{"snapshot": [...]}`` event, then ``{"diff": {...}}``
    for each subsequent non-empty diff.
    """
    bridge = get_bridge(hass)
    if bridge is None:
        connection.send_error(msg["id"], "bridge_not_found", "Bridge not available")
        return

    connection.send_result(msg["id"])
    connection.send_message(websocket_api.event_message(msg["id"], {"snapshot": bridge.diff_collector.snapshot()}))

    @callback
    def forward(diff: Any) -> None:
        connection.send_message(websocket_api.event_message(msg["id"], {"diff": diff.as_dict()}))

    unsub = bridge.diff_collector.subscribe(forward)
    connection.subscriptions[msg["id"]] = unsub
