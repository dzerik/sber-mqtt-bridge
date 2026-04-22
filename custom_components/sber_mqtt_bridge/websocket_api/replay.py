"""Replay / inject WebSocket commands (DevTools #3).

Forwards a synthetic Sber-shaped MQTT payload into the bridge's
dispatch table without touching the real broker.  The same pipeline
that handles live Sber traffic — :class:`SberCommandDispatcher`,
correlation traces, state diffs, ack audit — sees the injected
message indistinguishably from a real one (except for the
``direction="replay"`` marker in the message log, which the UI uses
to tint synthetic rows).

Two commands:
    * ``inject_sber_message`` — arbitrary ``{"topic", "payload"}``.
    * ``replay_message`` — convenience wrapper for re-sending an entry
      directly from the message log (log rows carry both fields, but
      the UI then has to know to re-encode; this is a thin alias so
      the UI can stay declarative).
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant

from ._common import get_bridge

_LOGGER = logging.getLogger(__name__)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "sber_mqtt_bridge/inject_sber_message",
        vol.Required("topic"): str,
        vol.Required("payload"): str,
        vol.Optional("mark_replay", default=True): bool,
    }
)
@websocket_api.async_response
async def ws_inject_sber_message(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Inject a synthetic Sber message into the bridge dispatch table."""
    bridge = get_bridge(hass)
    if bridge is None:
        connection.send_error(msg["id"], "bridge_not_found", "Bridge not available")
        return
    try:
        result = await bridge.async_inject_sber_message(msg["topic"], msg["payload"], mark_replay=msg["mark_replay"])
    except (
        ValueError,
        RuntimeError,
        TypeError,
    ) as e:
        # Explicit error channel — otherwise the UI sees a generic
        # timeout and the user has no idea why the inject silently failed.
        connection.send_error(msg["id"], "inject_failed", str(e))
        return
    connection.send_result(msg["id"], result)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "sber_mqtt_bridge/replay_message",
        vol.Required("topic"): str,
        vol.Required("payload"): str,
    }
)
@websocket_api.async_response
async def ws_replay_message(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Re-send a previously-captured Sber message (marked as replay)."""
    bridge = get_bridge(hass)
    if bridge is None:
        connection.send_error(msg["id"], "bridge_not_found", "Bridge not available")
        return
    try:
        result = await bridge.async_inject_sber_message(msg["topic"], msg["payload"], mark_replay=True)
    except (ValueError, RuntimeError, TypeError) as e:
        connection.send_error(msg["id"], "replay_failed", str(e))
        return
    connection.send_result(msg["id"], result)
