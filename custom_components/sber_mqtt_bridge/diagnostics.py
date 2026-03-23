"""Diagnostics support for Sber MQTT Bridge."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import SberBridgeConfigEntry
from .const import CONF_SBER_PASSWORD

TO_REDACT = {CONF_SBER_PASSWORD}
"""Set of config keys whose values should be redacted in diagnostics output."""


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: SberBridgeConfigEntry) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    bridge = entry.runtime_data.bridge

    return {
        "entry_data": async_redact_data(dict(entry.data), TO_REDACT),
        "options": dict(entry.options),
        "bridge": {
            "connected": bridge.is_connected,
            "entities_loaded": len(bridge._entities),
            "enabled_entity_ids": bridge._enabled_entity_ids,
            "redefinitions": bridge._redefinitions,
        },
    }
