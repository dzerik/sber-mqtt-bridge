"""Connectivity of the bridge to the Sber MQTT broker."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity

from .entity import SCAN_INTERVAL, SberBridgeDiagnosticEntity

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from . import SberBridgeConfigEntry

__all__ = ["SCAN_INTERVAL", "async_setup_entry"]


async def async_setup_entry(
    hass: HomeAssistant, entry: SberBridgeConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Create the connectivity sensor."""
    async_add_entities([SberBridgeConnectedSensor(entry.runtime_data.bridge, entry, "connected")])


class SberBridgeConnectedSensor(SberBridgeDiagnosticEntity, BinarySensorEntity):
    """On while the bridge holds a live MQTT connection to Sber."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    @property
    def is_on(self) -> bool:
        """Return whether the MQTT link is up."""
        return self._bridge.is_connected
