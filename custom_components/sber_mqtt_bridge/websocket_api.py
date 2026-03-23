"""WebSocket API for Sber MQTT Bridge panel.

Provides real-time device and connection data to the frontend SPA panel
via Home Assistant native WebSocket commands.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN

if TYPE_CHECKING:
    from .sber_bridge import SberBridge

_LOGGER = logging.getLogger(__name__)


def _get_bridge(hass: HomeAssistant) -> SberBridge | None:
    """Get the active SberBridge instance from hass.data.

    Returns:
        The SberBridge instance, or None if not available.
    """
    data = hass.data.get(DOMAIN, {})
    return data.get("bridge")


@callback
def async_setup_websocket_api(hass: HomeAssistant) -> None:
    """Register WebSocket API commands for the Sber MQTT Bridge panel.

    Args:
        hass: Home Assistant core instance.
    """
    websocket_api.async_register_command(hass, ws_get_devices)
    websocket_api.async_register_command(hass, ws_get_status)
    websocket_api.async_register_command(hass, ws_republish)
    _LOGGER.debug("Sber MQTT Bridge WebSocket API registered")


@websocket_api.websocket_command(
    {
        vol.Required("type"): "sber_mqtt_bridge/devices",
    }
)
@websocket_api.async_response
async def ws_get_devices(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Get all exposed Sber devices with their states.

    Args:
        hass: Home Assistant core instance.
        connection: Active WebSocket connection.
        msg: Incoming WebSocket message.
    """
    bridge = _get_bridge(hass)
    if bridge is None:
        connection.send_error(msg["id"], "bridge_not_found", "Sber bridge not available")
        return

    devices: list[dict[str, Any]] = []
    for eid, entity in bridge.entities.items():
        features = (
            entity.get_final_features_list()
            if hasattr(entity, "get_final_features_list")
            else entity.create_features_list()
        )
        devices.append(
            {
                "entity_id": eid,
                "sber_category": entity.category,
                "features": features,
                "name": entity.name,
                "room": getattr(entity, "area_id", ""),
                "is_online": entity._is_online,
                "state": entity.state,
                "is_filled": entity.is_filled_by_state,
            }
        )

    acknowledged = bridge.stats.get("acknowledged_entities", [])
    unacknowledged = bridge.unacknowledged_entities

    connection.send_result(
        msg["id"],
        {
            "devices": devices,
            "total": len(devices),
            "acknowledged_count": len(acknowledged),
            "unacknowledged_count": len(unacknowledged),
            "unacknowledged": unacknowledged,
        },
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "sber_mqtt_bridge/status",
    }
)
@websocket_api.async_response
async def ws_get_status(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Get bridge connection status and statistics.

    Args:
        hass: Home Assistant core instance.
        connection: Active WebSocket connection.
        msg: Incoming WebSocket message.
    """
    bridge = _get_bridge(hass)
    if bridge is None:
        connection.send_error(msg["id"], "bridge_not_found", "Sber bridge not available")
        return

    connection.send_result(
        msg["id"],
        {
            "connected": bridge.is_connected,
            "stats": bridge.stats,
            "entities_count": bridge.entities_count,
            "unacknowledged": bridge.unacknowledged_entities,
        },
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "sber_mqtt_bridge/republish",
    }
)
@websocket_api.async_response
async def ws_republish(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Force republish device config to Sber cloud.

    Args:
        hass: Home Assistant core instance.
        connection: Active WebSocket connection.
        msg: Incoming WebSocket message.
    """
    bridge = _get_bridge(hass)
    if bridge is None:
        connection.send_error(msg["id"], "bridge_not_found", "Sber bridge not available")
        return

    await bridge._publish_config()
    connection.send_result(msg["id"], {"success": True})
