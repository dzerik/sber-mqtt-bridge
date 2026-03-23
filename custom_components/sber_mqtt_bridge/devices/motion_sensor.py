"""Sber Motion Sensor entity -- maps HA motion binary sensors to Sber sensor_pir."""

from __future__ import annotations

import logging

from .simple_sensor import SimpleReadOnlySensor

_LOGGER = logging.getLogger(__name__)

MOTION_SENSOR_CATEGORY = "sensor_pir"
"""Sber device category for PIR / motion sensor entities."""


class MotionSensorEntity(SimpleReadOnlySensor):
    """Sber motion sensor entity.

    Reports motion detection state from HA binary_sensor entities
    (device_class=motion) to the Sber cloud via the ``pir`` feature.

    Per Sber specification, ``pir`` uses ENUM type with value ``"pir"``
    when motion is detected. This is an event-based sensor.
    """

    _sber_value_key = "pir"
    _sber_value_type = "ENUM"

    def __init__(self, entity_data: dict) -> None:
        """Initialize motion sensor entity.

        Args:
            entity_data: HA entity registry dict containing entity metadata.
        """
        super().__init__(MOTION_SENSOR_CATEGORY, entity_data)
        self.motion_detected = False

    def fill_by_ha_state(self, ha_state: dict) -> None:
        """Parse HA state and update motion detection flag.

        Args:
            ha_state: HA state dict; 'on' means motion detected.
        """
        super().fill_by_ha_state(ha_state)
        self.motion_detected = ha_state.get("state") == "on"

    def _get_sber_value(self) -> str:
        """Return Sber ENUM value for motion detection.

        Always returns ``"pir"`` as this is an event-based sensor.
        Sber ignores the value when no motion is detected.
        """
        return "pir"
