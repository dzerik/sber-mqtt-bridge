"""Sber Water Leak Sensor entity -- maps HA moisture binary sensors to Sber sensor_water_leak."""

from __future__ import annotations

import logging

from ..sber_constants import SberFeature
from ..sber_models import make_bool_value, make_state
from .simple_sensor import SimpleReadOnlySensor

_LOGGER = logging.getLogger(__name__)

WATER_LEAK_SENSOR_CATEGORY = "sensor_water_leak"
"""Sber device category for water leak sensor entities."""


class WaterLeakSensorEntity(SimpleReadOnlySensor):
    """Sber water leak sensor entity.

    Reports leak detection state from HA binary_sensor entities
    (device_class=moisture) to the Sber cloud via the ``water_leak_state``
    feature.

    Optionally supports ``tamper_alarm`` and ``alarm_mute`` from HA attributes.
    """

    _sber_value_key = "water_leak_state"
    _sber_value_type = "BOOL"
    _unknown_is_online = True

    def __init__(self, entity_data: dict) -> None:
        """Initialize water leak sensor entity.

        Args:
            entity_data: HA entity registry dict containing entity metadata.
        """
        super().__init__(WATER_LEAK_SENSOR_CATEGORY, entity_data)
        self.leak_detected = False
        self._tamper: bool | None = None
        self._alarm_mute: bool | None = None

    def fill_by_ha_state(self, ha_state: dict) -> None:
        """Parse HA state and update leak detection flag.

        Args:
            ha_state: HA state dict; 'on' means leak detected.
        """
        super().fill_by_ha_state(ha_state)
        self.leak_detected = ha_state.get("state") == "on"
        attrs = ha_state.get("attributes", {})
        tamper = attrs.get("tamper")
        if tamper is not None:
            self._tamper = bool(tamper)
        alarm_mute = attrs.get("alarm_mute")
        if alarm_mute is not None:
            self._alarm_mute = bool(alarm_mute)

    def create_features_list(self) -> list[str]:
        """Return Sber feature list including tamper_alarm and alarm_mute when available."""
        features = super().create_features_list()
        if self._tamper is not None:
            features.append("tamper_alarm")
        if self._alarm_mute is not None:
            features.append("alarm_mute")
        return features

    def to_sber_current_state(self) -> dict[str, dict]:
        """Build Sber current state payload with tamper_alarm and alarm_mute."""
        result = super().to_sber_current_state()
        if self._tamper is not None:
            result[self.entity_id]["states"].append(make_state(SberFeature.TAMPER_ALARM, make_bool_value(self._tamper)))
        if self._alarm_mute is not None:
            result[self.entity_id]["states"].append(
                make_state(SberFeature.ALARM_MUTE, make_bool_value(self._alarm_mute))
            )
        return result

    def _get_sber_value(self) -> bool:
        """Return whether a leak is currently detected."""
        return self.leak_detected
