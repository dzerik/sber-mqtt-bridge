"""Sber Humidity Sensor entity -- maps HA humidity sensors to Sber sensor_temp category."""

from __future__ import annotations

import logging

from .simple_sensor import SimpleReadOnlySensor

_LOGGER = logging.getLogger(__name__)

HUMIDITY_SENSOR_CATEGORY = "sensor_temp"
"""Sber device category for humidity sensor entities (shares sensor_temp category)."""


class HumiditySensorEntity(SimpleReadOnlySensor):
    """Sber humidity sensor entity.

    Reports humidity readings from HA sensor entities to the Sber cloud.
    Humidity is transmitted as a plain integer percentage (0-100).
    """

    _sber_value_key = "humidity"
    _sber_value_type = "INTEGER"

    def __init__(self, entity_data: dict) -> None:
        """Initialize humidity sensor entity.

        Args:
            entity_data: HA entity registry dict containing entity metadata.
        """
        super().__init__(HUMIDITY_SENSOR_CATEGORY, entity_data)
        self.humidity = 0.0

    def fill_by_ha_state(self, ha_state: dict) -> None:
        """Parse HA state and update humidity value.

        Args:
            ha_state: HA state dict with 'state' containing the humidity reading.
        """
        super().fill_by_ha_state(ha_state)
        try:
            self.humidity = float(ha_state.get("state", 0))
        except (ValueError, TypeError):
            self.humidity = 0.0

    def _get_sber_value(self) -> int:
        """Return humidity as integer percentage (0-100)."""
        return round(self.humidity)
