"""Correlation-timeline WebSocket commands (list / get / subscribe / clear).

Frontend counterpart to :mod:`custom_components.sber_mqtt_bridge.trace_collector`.
Every handler fetches the bridge's :class:`TraceCollector` via ``bridge.trace_collector``
and returns JSON-serializable snapshots; live updates fan out through
subscribe so the DevTools panel can render incremental timelines.
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
        vol.Required("type"): "sber_mqtt_bridge/traces",
        vol.Optional("include_active", default=True): bool,
    }
)
@callback
def ws_list_traces(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return a snapshot of recent correlation traces (closed + active)."""
    bridge = get_bridge(hass)
    if bridge is None:
        connection.send_error(msg["id"], "bridge_not_found", "Bridge not available")
        return
    snapshot = bridge.trace_collector.snapshot(include_active=msg["include_active"])
    connection.send_result(msg["id"], {"traces": snapshot})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "sber_mqtt_bridge/trace",
        vol.Required("trace_id"): str,
    }
)
@callback
def ws_get_trace(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return a single trace by id, or an error if unknown."""
    bridge = get_bridge(hass)
    if bridge is None:
        connection.send_error(msg["id"], "bridge_not_found", "Bridge not available")
        return
    trace = bridge.trace_collector.get(msg["trace_id"])
    if trace is None:
        connection.send_error(msg["id"], "trace_not_found", f"Trace {msg['trace_id']} not found")
        return
    connection.send_result(msg["id"], {"trace": trace})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "sber_mqtt_bridge/clear_traces",
    }
)
@callback
def ws_clear_traces(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Drop all active and closed traces."""
    bridge = get_bridge(hass)
    if bridge is None:
        connection.send_error(msg["id"], "bridge_not_found", "Bridge not available")
        return
    bridge.trace_collector.clear()
    connection.send_result(msg["id"], {"success": True})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "sber_mqtt_bridge/subscribe_traces",
    }
)
@callback
def ws_subscribe_traces(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Stream correlation-trace lifecycle events to the subscriber.

    On subscribe we first send an initial snapshot so the UI has the
    current state, then emit ``{"kind": ..., "trace": ...}`` for every
    ``trace_started`` / ``trace_updated`` / ``trace_closed`` event.
    """
    bridge = get_bridge(hass)
    if bridge is None:
        connection.send_error(msg["id"], "bridge_not_found", "Bridge not available")
        return

    connection.send_result(msg["id"])
    connection.send_message(
        websocket_api.event_message(
            msg["id"],
            {"snapshot": bridge.trace_collector.snapshot()},
        )
    )

    @callback
    def forward(kind: str, trace: Any) -> None:
        connection.send_message(
            websocket_api.event_message(
                msg["id"],
                {"kind": kind, "trace": trace.as_dict()},
            )
        )

    unsub = bridge.trace_collector.subscribe(forward)
    connection.subscriptions[msg["id"]] = unsub
