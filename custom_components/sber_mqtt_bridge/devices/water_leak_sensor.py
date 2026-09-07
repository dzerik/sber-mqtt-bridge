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

    The HA attributes ``tamper`` and ``alarm_mute`` are **not** forwarded:
    the "Доступные функции устройства" table on ``c2c/sensor_water_leak``
    lists only ``online``, ``water_leak_state``, ``battery_low_power``,
    ``battery_percentage`` and ``signal_strength``.  Zigbee leak sensors
    report both attributes anyway, and up to 1.50 the bridge put them into
    the model — a model with a function outside its category's table can
    be rejected by the cloud as a whole, losing the whole sensor rather
    than one row in its card.  Sensitivity is dropped for the same reason
    (see :class:`~.simple_sensor.SimpleReadOnlySensor`).
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

    def fill_by_ha_state(self, ha_state: dict) -> None:
        """Parse HA state and update leak detection flag.

        Args:
            ha_state: HA state dict; 'on' means leak detected.
        """
        super().fill_by_ha_state(ha_state)
        self.leak_detected = ha_state.get("state") == "on"
        self._parse_tamper_alarm_mute(ha_state.get("attributes", {}))

    def _create_features_list(self) -> list[str]:
        """Return Sber feature list — ``tamper_alarm`` / ``alarm_mute`` are never in it."""
        features = super()._create_features_list()
        self._append_tamper_alarm_mute_features(features)
        return features

    def _build_current_state(self) -> dict[str, dict]:
        """Build Sber current state payload — ``tamper_alarm`` / ``alarm_mute`` excluded."""
        result = super()._build_current_state()
        self._append_tamper_alarm_mute_states(result[self.entity_id]["states"])
        return result

    def _get_sber_value(self) -> bool:
        """Return whether a leak is currently detected."""
        return self.leak_detected
