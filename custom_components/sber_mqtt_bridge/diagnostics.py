"""Diagnostics support for Sber MQTT Bridge."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import SberBridgeConfigEntry
from .const import CONF_SBER_PASSWORD

TO_REDACT = {CONF_SBER_PASSWORD}
"""Set of config keys whose values should be redacted in diagnostics output."""


def _build_entity_diagnostics(bridge) -> list[dict[str, Any]]:
    """Build per-entity diagnostic info.

    Args:
        bridge: SberBridge instance with loaded entities.

    Returns:
        List of dicts with entity diagnostic details.
    """
    result: list[dict[str, Any]] = []
    for entity_id, entity in bridge.entities.items():
        entry: dict[str, Any] = {
            "entity_id": entity_id,
            "sber_category": entity.category,
            "sber_features": entity.create_features_list(),
            "is_filled_by_state": entity.is_filled_by_state,
            "has_linked_device": entity.linked_device is not None,
        }

        # Current state summary
        if entity.is_filled_by_state:
            entry["current_state"] = {
                "state": entity.state,
                "is_online": entity.is_online,
            }
        else:
            entry["current_state"] = None

        result.append(entry)
    return result


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: SberBridgeConfigEntry) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    bridge = entry.runtime_data.bridge

    return {
        "entry_data": async_redact_data(dict(entry.data), TO_REDACT),
        "options": dict(entry.options),
        "bridge": {
            "connected": bridge.is_connected,
            "entities_loaded": bridge.entities_count,
            "enabled_entity_ids": bridge.enabled_entity_ids,
            "redefinitions": bridge.redefinitions,
            "unacknowledged_entities": bridge.unacknowledged_entities,
            "stats": bridge.stats,
        },
        "entities": _build_entity_diagnostics(bridge),
    }
