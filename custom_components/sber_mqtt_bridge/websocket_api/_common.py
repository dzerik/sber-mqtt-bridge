"""Shared helpers for the Sber MQTT Bridge WebSocket API package."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant

from ..const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

    from ..sber_bridge import SberBridge


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
