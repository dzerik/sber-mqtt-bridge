"""Raw-JSON DevTools commands (raw_config, raw_states, send_raw_*)."""

from __future__ import annotations

import json
import logging
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant

from ._common import WS_PAYLOAD, get_bridge, requires_bridge  # noqa: F401 — get_bridge re-exported for test patching

_LOGGER = logging.getLogger(__name__)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "sber_mqtt_bridge/raw_config",
    }
)
@websocket_api.async_response
@requires_bridge
async def ws_raw_config(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    bridge: Any,
) -> None:
    """Get the raw config JSON that would be sent to Sber."""
    from ..sber_protocol import build_devices_list_json

    payload, _valid, _invalid = build_devices_list_json(
        bridge.entities,
        bridge.enabled_entity_ids,
        bridge.redefinitions,
        ha_serial_prefix=bridge.ha_serial_prefix,
    )
    connection.send_result(msg["id"], {"payload": payload})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "sber_mqtt_bridge/raw_states",
    }
)
@websocket_api.async_response
@requires_bridge
async def ws_raw_states(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    bridge: Any,
) -> None:
    """Get the raw states JSON that would be sent to Sber."""
    from ..sber_protocol import build_states_list_json

    payload, _valid = build_states_list_json(bridge.entities, None, bridge.enabled_entity_ids)
    connection.send_result(msg["id"], {"payload": payload})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "sber_mqtt_bridge/send_raw_config",
        vol.Required("payload"): WS_PAYLOAD,
    }
)
@websocket_api.async_response
@requires_bridge
async def ws_send_raw_config(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    bridge: Any,
) -> None:
    """Send arbitrary JSON config payload to Sber MQTT broker."""
    await _send_raw(connection, msg, bridge, "config")


@websocket_api.websocket_command(
    {
        vol.Required("type"): "sber_mqtt_bridge/send_raw_state",
        vol.Required("payload"): WS_PAYLOAD,
    }
)
@websocket_api.async_response
@requires_bridge
async def ws_send_raw_state(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    bridge: Any,
) -> None:
    """Send arbitrary JSON state payload to Sber MQTT broker."""
    await _send_raw(connection, msg, bridge, "status")


async def _send_raw(
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    bridge: Any,
    target: str,
) -> None:
    """Validate and publish raw JSON to Sber MQTT.

    Args:
        connection: Active WebSocket connection.
        msg: Incoming message with ``payload`` key.
        bridge: The active :class:`SberBridge` instance.
        target: MQTT topic suffix (``"config"`` or ``"status"``).
    """
    try:
        json.loads(msg["payload"])
    except json.JSONDecodeError as exc:
        connection.send_error(msg["id"], "invalid_json", str(exc))
        return

    try:
        await bridge.async_publish_raw(msg["payload"], target)
    except RuntimeError as exc:
        connection.send_error(msg["id"], "not_connected", str(exc))
        return

    connection.send_result(msg["id"], {"success": True})
