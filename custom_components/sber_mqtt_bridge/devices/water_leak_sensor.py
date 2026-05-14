"""Sber Water Leak Sensor entity -- maps HA moisture binary sensors to Sber sensor_water_leak."""

from __future__ import annotations

import logging

from .simple_sensor import SimpleReadOnlySensor
from .tamper_alarm_mute_mixin import TamperAlarmMuteMixin

_LOGGER = logging.getLogger(__name__)

WATER_LEAK_SENSOR_CATEGORY = "sensor_water_leak"
"""Sber device category for water leak sensor entities."""


class WaterLeakSensorEntity(TamperAlarmMuteMixin, SimpleReadOnlySensor):
    """Sber water leak sensor entity.

    Reports leak detection state from HA binary_sensor entities
    (device_class=moisture) to the Sber cloud via the ``water_leak_state``
    feature.

    Optionally supports ``tamper_alarm`` and ``alarm_mute`` from HA attributes.
    """

    _sber_value_key = "water_leak_state"
    _sber_value_type = "BOOL"
    _unknown_is_online = True
    SUPPORTS_ALARM_MUTE = True

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
        self._parse_tamper_alarm_mute(ha_state.get("attributes", {}))

    def _create_features_list(self) -> list[str]:
        """Return Sber feature list including tamper_alarm and alarm_mute when available."""
        features = super()._create_features_list()
        self._append_tamper_alarm_mute_features(features)
        return features

    def to_sber_current_state(self) -> dict[str, dict]:
        """Build Sber current state payload with tamper_alarm and alarm_mute."""
        result = super().to_sber_current_state()
        self._append_tamper_alarm_mute_states(result[self.entity_id]["states"])
        return result

    def _get_sber_value(self) -> bool:
        """Return whether a leak is currently detected."""
        return self.leak_detected
