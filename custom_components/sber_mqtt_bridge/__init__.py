"""Sber Smart Home MQTT Bridge integration for Home Assistant."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN as DOMAIN
from .sber_bridge import SberBridge

_LOGGER = logging.getLogger(__name__)


@dataclass
class SberBridgeData:
    """Runtime data for the Sber MQTT Bridge integration.

    Attributes:
        bridge: The active SberBridge instance managing MQTT communication.
    """

    bridge: SberBridge


type SberBridgeConfigEntry = ConfigEntry[SberBridgeData]
"""Type alias for a ConfigEntry carrying SberBridgeData as runtime_data."""


async def async_setup_entry(hass: HomeAssistant, entry: SberBridgeConfigEntry) -> bool:
    """Set up Sber MQTT Bridge from a config entry.

    The bridge starts in background-reconnect mode: entity loading and HA event
    subscription happen immediately, while the MQTT connection is established
    asynchronously. Connection failures are logged and retried with backoff.

    Args:
        hass: Home Assistant core instance.
        entry: Config entry with Sber broker credentials and options.

    Returns:
        True if setup succeeded.
    """
    bridge = SberBridge(hass, entry)
    await bridge.async_start()

    entry.runtime_data = SberBridgeData(bridge=bridge)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SberBridgeConfigEntry) -> bool:
    """Unload a config entry and stop the Sber bridge.

    Args:
        hass: Home Assistant core instance.
        entry: Config entry being unloaded.

    Returns:
        True if unload succeeded.
    """
    await entry.runtime_data.bridge.async_stop()
    return True


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate config entry to a newer version.

    Version 1 → 2: ensure ``entity_type_overrides`` key exists in options.

    Args:
        hass: Home Assistant core instance.
        entry: Config entry being migrated.

    Returns:
        True if migration succeeded.
    """
    if entry.version == 1:
        _LOGGER.info(
            "Migrating config entry %s from version %s to 2",
            entry.entry_id,
            entry.version,
        )
        new_options = dict(entry.options)
        if "entity_type_overrides" not in new_options:
            new_options["entity_type_overrides"] = {}
        hass.config_entries.async_update_entry(entry, options=new_options, version=2)
        _LOGGER.info("Migration of config entry %s to version 2 complete", entry.entry_id)

    return True
