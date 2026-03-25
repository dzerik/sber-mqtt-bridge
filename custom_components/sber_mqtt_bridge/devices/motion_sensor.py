"""Sber Motion Sensor entity -- maps HA motion binary sensors to Sber sensor_pir."""

from __future__ import annotations

import logging

from ..sber_constants import SberFeature
from ..sber_models import make_bool_value, make_state
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
        self._tamper: bool | None = None

    def fill_by_ha_state(self, ha_state: dict) -> None:
        """Parse HA state and update motion detection flag and tamper alarm.

        Args:
            ha_state: HA state dict; 'on' means motion detected.
        """
        super().fill_by_ha_state(ha_state)
        self.motion_detected = ha_state.get("state") == "on"
        attrs = ha_state.get("attributes", {})
        tamper = attrs.get("tamper")
        if tamper is not None:
            self._tamper = bool(tamper)
        else:
            self._tamper = None

    def create_features_list(self) -> list[str]:
        """Return Sber feature list including tamper_alarm when available.

        Returns:
            List of Sber feature strings supported by this entity.
        """
        features = super().create_features_list()
        if self._tamper is not None:
            features.append("tamper_alarm")
        return features

    def to_sber_current_state(self) -> dict[str, dict]:
        """Build Sber current state payload with tamper_alarm when available.

        Returns:
            Dict mapping entity_id to its Sber state representation.
        """
        result = super().to_sber_current_state()
        if self._tamper is not None:
            result[self.entity_id]["states"].append(make_state(SberFeature.TAMPER_ALARM, make_bool_value(self._tamper)))
        return result

    def _get_sber_value(self) -> str:
        """Return Sber ENUM value for motion detection.

        Per Sber C2C spec: ``"pir"`` = motion detected, ``"no_pir"`` = no motion.
        """
        return "pir" if self.motion_detected else "no_pir"
