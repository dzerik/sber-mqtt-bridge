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
    _unknown_is_online = True

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

    def _get_sber_value(self) -> str:
        """Return Sber ENUM value for motion detection.

        Per Sber C2C spec, ``pir`` is event-based: send ``"pir"`` only when
        motion is detected.  When idle, return empty string so the feature
        is omitted from the state payload.
        """
        return "pir" if self.motion_detected else ""

    def to_sber_current_state(self) -> dict[str, dict]:
        """Build Sber state, omitting pir key when no motion detected.

        PIR is event-based per Sber spec: only emit ``pir`` on motion,
        omit the key entirely when idle.
        """
        # Use parent implementation for online, battery, signal
        result = super().to_sber_current_state()
        entity_states = result[self.entity_id]["states"]

        if not self.motion_detected:
            # Remove the pir state entry added by parent
            entity_states[:] = [s for s in entity_states if s.get("key") != "pir"]

        if self._tamper is not None:
            entity_states.append(make_state(SberFeature.TAMPER_ALARM, make_bool_value(self._tamper)))

        return result
