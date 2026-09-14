"""System Health info for Sber MQTT Bridge (Settings → System → Repairs → System information).

A short, always-available summary for bug reports: users paste the System
information page without having to open the bridge panel or its DevTools.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components import system_health
from homeassistant.core import HomeAssistant, callback

from .conflict import detect_conflicts
from .const import CONF_SBER_LOGIN
from .message_logger import parse_sber_error
from .sber_protocol import VERSION
from .websocket_api._common import get_bridge, get_config_entry


@callback
def async_register(hass: HomeAssistant, register: system_health.SystemHealthRegistration) -> None:
    """Register the System Health info callback and the panel as its manage URL."""
    register.async_register_info(system_health_info, "/sber-mqtt-bridge")


async def system_health_info(hass: HomeAssistant) -> dict[str, Any]:
    """Return the bridge summary shown on the System information page.

    Returns:
        Plain values only — no login, topics or entity names, since the page
        is copied into public issues as is.
    """
    bridge = get_bridge(hass)
    if bridge is None:
        return {"version": VERSION, "connection": "not_loaded"}
    stats = bridge.stats
    uptime = stats.get("connection_uptime_seconds")
    last_error = parse_sber_error(stats.get("last_error_detail", ""))
    entry = get_config_entry(hass)
    login = entry.data.get(CONF_SBER_LOGIN) if entry else None
    return {
        "version": VERSION,
        "connection": bridge.connection_phase,
        "connected_for": f"{int(uptime // 60)} min" if uptime else "—",
        "exposed_entities": bridge.entities_count,
        "known_to_sber": len(bridge.cloud_known_entities),
        "never_confirmed": len(bridge.never_confirmed_entities),
        "reconnects": stats.get("reconnect_count", 0),
        "sber_errors": stats.get("errors_from_sber", 0),
        "last_sber_error": last_error["code"] if last_error else "—",
        "other_sber_bridges": len(detect_conflicts(hass, login)),
    }
