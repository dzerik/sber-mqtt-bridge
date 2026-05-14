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
from ._common import WS_ENTITY_ID, get_bridge, requires_bridge  # noqa: F401 — get_bridge re-exported for test patching

_LOGGER = logging.getLogger(__name__)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "sber_mqtt_bridge/diagnose_entity",
        vol.Required("entity_id"): WS_ENTITY_ID,
    }
)
@callback
@requires_bridge
def ws_diagnose_entity(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    bridge: Any,
) -> None:
    """Return a full diagnostic report for ``entity_id``."""
    report = diagnose_entity(bridge, msg["entity_id"])
    connection.send_result(msg["id"], {"report": report.as_dict()})
