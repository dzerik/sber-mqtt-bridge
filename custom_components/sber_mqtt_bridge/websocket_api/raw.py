"""Raw-JSON DevTools commands (raw_config, raw_states, send_raw_*)."""

from __future__ import annotations

import json
import logging
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant

from ._common import get_bridge

_LOGGER = logging.getLogger(__name__)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "sber_mqtt_bridge/raw_config",
    }
)
@websocket_api.async_response
async def ws_raw_config(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Get the raw config JSON that would be sent to Sber."""
    bridge = get_bridge(hass)
    if bridge is None:
        connection.send_error(msg["id"], "bridge_not_found", "Bridge not available")
        return

    from ..sber_protocol import build_devices_list_json

    payload, _valid, _invalid = build_devices_list_json(bridge.entities, bridge.enabled_entity_ids, bridge.redefinitions)
    connection.send_result(msg["id"], {"payload": payload})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "sber_mqtt_bridge/raw_states",
    }
)
@websocket_api.async_response
async def ws_raw_states(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Get the raw states JSON that would be sent to Sber."""
    bridge = get_bridge(hass)
    if bridge is None:
        connection.send_error(msg["id"], "bridge_not_found", "Bridge not available")
        return

    from ..sber_protocol import build_states_list_json

    payload, _valid = build_states_list_json(bridge.entities, None, bridge.enabled_entity_ids)
    connection.send_result(msg["id"], {"payload": payload})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "sber_mqtt_bridge/send_raw_config",
        vol.Required("payload"): str,
    }
)
@websocket_api.async_response
async def ws_send_raw_config(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Send arbitrary JSON config payload to Sber MQTT broker."""
    await _send_raw(hass, connection, msg, "config")


@websocket_api.websocket_command(
    {
        vol.Required("type"): "sber_mqtt_bridge/send_raw_state",
        vol.Required("payload"): str,
    }
)
@websocket_api.async_response
async def ws_send_raw_state(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Send arbitrary JSON state payload to Sber MQTT broker."""
    await _send_raw(hass, connection, msg, "status")


async def _send_raw(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    target: str,
) -> None:
    """Validate and publish raw JSON to Sber MQTT.

    Args:
        hass: Home Assistant core instance.
        connection: Active WebSocket connection.
        msg: Incoming message with ``payload`` key.
        target: MQTT topic suffix (``"config"`` or ``"status"``).
    """
    bridge = get_bridge(hass)
    if bridge is None:
        connection.send_error(msg["id"], "bridge_not_found", "Bridge not available")
        return

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
