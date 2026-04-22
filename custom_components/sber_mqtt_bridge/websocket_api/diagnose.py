"""Diagnostic-advisor WebSocket command (DevTools #5).

Single request/response command — ``diagnose_entity`` — that returns
a full per-entity health report built from the signals the bridge
already exposes (entity registry, ack stats, correlation trace,
schema validation).  No subscribe channel: diagnostics are
user-initiated ("Why isn't X working?") so there's no background
stream to push.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from ..diagnostics_advisor import diagnose_entity
from ._common import get_bridge

_LOGGER = logging.getLogger(__name__)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "sber_mqtt_bridge/diagnose_entity",
        vol.Required("entity_id"): str,
    }
)
@callback
def ws_diagnose_entity(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return a full diagnostic report for ``entity_id``."""
    bridge = get_bridge(hass)
    if bridge is None:
        connection.send_error(msg["id"], "bridge_not_found", "Bridge not available")
        return
    report = diagnose_entity(bridge, msg["entity_id"])
    connection.send_result(msg["id"], {"report": report.as_dict()})
