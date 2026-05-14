"""Sber Smoke Sensor entity -- maps HA smoke binary sensors to Sber sensor_smoke."""

from __future__ import annotations

import logging

from .simple_sensor import SimpleReadOnlySensor
from .tamper_alarm_mute_mixin import TamperAlarmMuteMixin

_LOGGER = logging.getLogger(__name__)

SMOKE_SENSOR_CATEGORY = "sensor_smoke"
"""Sber device category for smoke sensor entities."""


class SmokeSensorEntity(TamperAlarmMuteMixin, SimpleReadOnlySensor):
    """Sber smoke sensor entity.

    Reports smoke detection state from HA binary_sensor entities
    (device_class=smoke) to the Sber cloud via the ``smoke_state`` feature.

    Per Sber specification, ``smoke_state`` uses BOOL type:
    - ``true`` = smoke detected
    - ``false`` = no smoke

    Optionally supports ``alarm_mute`` (BOOL) if the HA entity
    provides it in attributes.
    """

    _sber_value_key = "smoke_state"
    _sber_value_type = "BOOL"
    _unknown_is_online = True
    SUPPORTS_ALARM_MUTE = True

    def __init__(self, entity_data: dict) -> None:
        """Initialize smoke sensor entity.

        Args:
            entity_data: HA entity registry dict containing entity metadata.
        """
        super().__init__(SMOKE_SENSOR_CATEGORY, entity_data)
        self.smoke_detected: bool = False

    def fill_by_ha_state(self, ha_state: dict) -> None:
        """Parse HA state and update smoke detection flag, tamper and alarm_mute.

        Args:
            ha_state: HA state dict; 'on' means smoke detected.
        """
        super().fill_by_ha_state(ha_state)
        self.smoke_detected = ha_state.get("state") == "on"
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
        """Return whether smoke is currently detected."""
        return self.smoke_detected
