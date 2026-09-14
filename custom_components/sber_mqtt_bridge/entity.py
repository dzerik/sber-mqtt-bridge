"""Base class of the bridge's own diagnostic entities.

They describe the bridge itself — connection, what Sber knows, errors — so
automations can react to a lost link.  They live on one service device and
are never offered for export to Sber (see the ``platform == DOMAIN`` filters
in the entity pickers).
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from homeassistant.const import EntityCategory
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN
from .sber_protocol import VERSION

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

    from .sber_bridge import SberBridge

SCAN_INTERVAL = timedelta(seconds=30)
"""Counters are re-read this often; the connection itself is pushed at once."""


class SberBridgeDiagnosticEntity(Entity):
    """Diagnostic entity reading its value from the running bridge."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_should_poll = True

    def __init__(self, bridge: SberBridge, entry: ConfigEntry, key: str) -> None:
        """Bind the entity to the bridge.

        Args:
            bridge: Running bridge the value is read from.
            entry: Config entry owning the bridge.
            key: Stable key; also the translation key of the entity name.
        """
        self._bridge = bridge
        self._attr_translation_key = key
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Sber MQTT Bridge",
            manufacturer="dzerik",
            model="HA → Sber Smart Home bridge",
            sw_version=VERSION,
            entry_type=DeviceEntryType.SERVICE,
        )

    async def async_added_to_hass(self) -> None:
        """Refresh at once when the MQTT link changes."""
        self.async_on_remove(self._bridge.add_status_listener(self.async_write_ha_state))
