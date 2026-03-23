"""Sber Water Leak Sensor entity -- maps HA moisture binary sensors to Sber sensor_water_leak."""

from __future__ import annotations

import logging

from .simple_sensor import SimpleReadOnlySensor

logger = logging.getLogger(__name__)

WATER_LEAK_SENSOR_CATEGORY = "sensor_water_leak"
"""Sber device category for water leak sensor entities."""


class WaterLeakSensorEntity(SimpleReadOnlySensor):
    """Sber water leak sensor entity.

    Reports leak detection state from HA binary_sensor entities
    (device_class=moisture) to the Sber cloud via the ``water_leak`` feature.
    """

    _sber_value_key = "water_leak"
    _sber_value_type = "BOOL"

    def __init__(self, entity_data: dict) -> None:
        """Initialize water leak sensor entity.

        Args:
            entity_data: HA entity registry dict containing entity metadata.
        """
        super().__init__(WATER_LEAK_SENSOR_CATEGORY, entity_data)
        self.leak_detected = False

    def fill_by_ha_state(self, ha_state: dict) -> None:
        """Parse HA state and update leak detection flag.

        Args:
            ha_state: HA state dict; 'on' means leak detected.
        """
        super().fill_by_ha_state(ha_state)
        self.leak_detected = ha_state.get("state") == "on"

    def _get_sber_value(self) -> bool:
        """Return whether a leak is currently detected."""
        return self.leak_detected
