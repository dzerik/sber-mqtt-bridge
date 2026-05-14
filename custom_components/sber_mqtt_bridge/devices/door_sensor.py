"""Sber Door Sensor entity -- maps HA door/window/garage binary sensors to Sber sensor_door."""

from __future__ import annotations

import logging

from .simple_sensor import SimpleReadOnlySensor
from .tamper_alarm_mute_mixin import TamperAlarmMuteMixin

_LOGGER = logging.getLogger(__name__)

DOOR_SENSOR_CATEGORY = "sensor_door"
"""Sber device category for door/window contact sensor entities."""


class DoorSensorEntity(TamperAlarmMuteMixin, SimpleReadOnlySensor):
    """Sber door sensor entity.

    Reports open/close state from HA binary_sensor entities
    (device_class=door, window, garage_door) to the Sber cloud
    via the ``doorcontact_state`` feature.

    Per Sber specification, ``doorcontact_state`` uses BOOL type:
    - ``true`` = open (contacts disconnected)
    - ``false`` = closed (contacts connected)
    """

    _sber_value_key = "doorcontact_state"
    _sber_value_type = "BOOL"
    _unknown_is_online = True

    def __init__(self, entity_data: dict) -> None:
        """Initialize door sensor entity.

        Args:
            entity_data: HA entity registry dict containing entity metadata.
        """
        super().__init__(DOOR_SENSOR_CATEGORY, entity_data)
        self.is_open = False

    def fill_by_ha_state(self, ha_state: dict) -> None:
        """Parse HA state and update open/close status and tamper alarm.

        Args:
            ha_state: HA state dict; 'on' means door is open.
        """
        super().fill_by_ha_state(ha_state)
        self.is_open = ha_state.get("state") == "on"
        self._parse_tamper_alarm_mute(ha_state.get("attributes", {}))

    def _create_features_list(self) -> list[str]:
        """Return Sber feature list including tamper_alarm when available.

        Returns:
            List of Sber feature strings supported by this entity.
        """
        features = super()._create_features_list()
        self._append_tamper_alarm_mute_features(features)
        return features

    def to_sber_current_state(self) -> dict[str, dict]:
        """Build Sber current state payload with tamper_alarm when available.

        Returns:
            Dict mapping entity_id to its Sber state representation.
        """
        result = super().to_sber_current_state()
        self._append_tamper_alarm_mute_states(result[self.entity_id]["states"])
        return result

    def _get_sber_value(self) -> bool:
        """Return door state as Sber BOOL value.

        Returns:
            True if door is open, False if closed.
        """
        return self.is_open
