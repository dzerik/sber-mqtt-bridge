"""Diagnostics support for Sber MQTT Bridge."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import SberBridgeConfigEntry
from .const import CONF_SBER_LOGIN, CONF_SBER_PASSWORD

TO_REDACT = {CONF_SBER_PASSWORD, CONF_SBER_LOGIN}
"""Set of config keys whose values should be redacted in diagnostics output.

The Sber login doubles as the MQTT username **and** the root MQTT topic
segment (``sberdevices/v1/<login>/...``) — diagnostics files are routinely
attached to public GitHub issues, so it must not leak in clear text.
"""


def _build_entity_diagnostics(bridge) -> list[dict[str, Any]]:
    """Build per-entity diagnostic info.

    Args:
        bridge: SberBridge instance with loaded entities.

    Returns:
        List of dicts with entity diagnostic details.
    """
    missing_links = bridge.entities_missing_required_links
    result: list[dict[str, Any]] = []
    for entity_id, entity in bridge.entities.items():
        entry: dict[str, Any] = {
            "entity_id": entity_id,
            "sber_category": entity.category,
            "sber_features": entity.get_final_features_list(),
            "is_filled_by_state": entity.is_filled_by_state,
            "has_linked_device": entity.linked_device is not None,
            # Non-empty means the device is composite and mis-configured:
            # it publishes a fabricated state (see the matching repair).
            "missing_required_links": missing_links.get(entity_id, []),
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
            "entities_missing_required_links": bridge.entities_missing_required_links,
            "stats": bridge.stats,
        },
        # Its own block, not just a key buried in ``options``: "known to
        # Sber: 0" on a working bridge (issue #57) is answered by comparing
        # the live set, the persisted one and whether a config publish has
        # succeeded this session — three facts that were nowhere in the
        # dump, so the report could only be chased by guesswork.
        "cloud_device_registry": bridge.cloud_device_registry_state,
        "entities": _build_entity_diagnostics(bridge),
    }
