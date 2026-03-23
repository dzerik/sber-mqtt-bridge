"""Sber Temperature Sensor entity -- maps HA temperature sensors to Sber sensor_temp."""

from __future__ import annotations

import logging

from .simple_sensor import SimpleReadOnlySensor

logger = logging.getLogger(__name__)

SENSOR_TEMP_CATEGORY = "sensor_temp"
"""Sber device category for temperature sensor entities."""


class SensorTempEntity(SimpleReadOnlySensor):
    """Sber temperature sensor entity.

    Reports temperature readings from HA sensor entities to the Sber cloud.
    Temperature is transmitted as an integer value multiplied by 10
    (e.g. 22.5 C becomes 225).
    """

    _sber_value_key = "temperature"
    _sber_value_type = "INTEGER"

    def __init__(self, entity_data: dict) -> None:
        """Initialize temperature sensor entity.

        Args:
            entity_data: HA entity registry dict containing entity metadata.
        """
        super().__init__(SENSOR_TEMP_CATEGORY, entity_data)
        self.temperature = 0.0

    def fill_by_ha_state(self, ha_state: dict) -> None:
        """Parse HA state and update temperature value.

        Args:
            ha_state: HA state dict with 'state' containing the temperature reading.
        """
        super().fill_by_ha_state(ha_state)
        try:
            self.temperature = float(ha_state.get("state", 0))
        except (ValueError, TypeError):
            self.temperature = 0.0

    def _get_sber_value(self) -> int:
        """Return temperature as integer scaled by 10."""
        return int(self.temperature * 10)
