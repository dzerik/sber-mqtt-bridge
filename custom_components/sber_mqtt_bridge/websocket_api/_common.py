"""Shared helpers for the Sber MQTT Bridge WebSocket API package."""

from __future__ import annotations

from typing import TYPE_CHECKING

import voluptuous as vol  # type: ignore[import-untyped]
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv

from ..const import DOMAIN
from ..sber_entity_map import CATEGORY_DOMAIN_MAP

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

    from ..sber_bridge import SberBridge

WS_ENTITY_ID = vol.All(cv.string, cv.entity_id)
"""Validator for a single entity_id field in a WS schema.

Use as ``vol.Required("entity_id"): WS_ENTITY_ID`` so HA rejects
malformed strings before they reach the handler and risk poisoning
``entry.options``.
"""

WS_ENTITY_IDS = vol.All(cv.ensure_list, [cv.entity_id])
"""Validator for an entity_ids list field — every element must look
like a real entity_id (``domain.object_id``)."""

OVERRIDABLE_CATEGORIES = sorted(CATEGORY_DOMAIN_MAP.keys())
"""Sorted list of valid Sber category strings, used to validate
``category`` fields in WS schemas."""


def get_config_entry(hass: HomeAssistant) -> ConfigEntry | None:
    """Return the first loaded config entry for this integration (or None)."""
    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    return entries[0] if entries else None


def get_bridge(hass: HomeAssistant) -> SberBridge | None:
    """Return the active ``SberBridge`` from ``ConfigEntry.runtime_data``.

    Returns:
        The bridge instance, or ``None`` if not available.
    """
    entry = get_config_entry(hass)
    if entry is None or not hasattr(entry, "runtime_data") or entry.runtime_data is None:
        return None
    return entry.runtime_data.bridge
