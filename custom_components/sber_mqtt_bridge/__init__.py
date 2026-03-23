"""Sber Smart Home MQTT Bridge integration for Home Assistant."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import DOMAIN
from .sber_bridge import SberBridge

_LOGGER = logging.getLogger(__name__)


@dataclass
class SberBridgeData:
    """Runtime data for the Sber MQTT Bridge integration."""

    bridge: SberBridge


type SberBridgeConfigEntry = ConfigEntry[SberBridgeData]


async def async_setup_entry(
    hass: HomeAssistant, entry: SberBridgeConfigEntry
) -> bool:
    """Set up Sber MQTT Bridge from a config entry."""
    bridge = SberBridge(hass, entry)

    try:
        await bridge.async_start()
    except Exception as err:
        await bridge.async_stop()
        raise ConfigEntryNotReady(
            f"Failed to connect to Sber MQTT broker: {err}"
        ) from err

    entry.runtime_data = SberBridgeData(bridge=bridge)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: SberBridgeConfigEntry
) -> bool:
    """Unload a config entry."""
    await entry.runtime_data.bridge.async_stop()
    return True
