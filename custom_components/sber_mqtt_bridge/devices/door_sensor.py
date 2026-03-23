"""Sber Door Sensor entity -- maps HA door/window/garage binary sensors to Sber sensor_door."""

from __future__ import annotations

import logging

from .simple_sensor import SimpleReadOnlySensor

logger = logging.getLogger(__name__)

DOOR_SENSOR_CATEGORY = "sensor_door"
"""Sber device category for door/window contact sensor entities."""


class DoorSensorEntity(SimpleReadOnlySensor):
    """Sber door sensor entity.

    Reports open/close state from HA binary_sensor entities
    (device_class=door, window, garage_door) to the Sber cloud
    via the ``doorcontact_state`` feature.
    """

    _sber_value_key = "doorcontact_state"
    _sber_value_type = "ENUM"

    def __init__(self, entity_data: dict) -> None:
        """Initialize door sensor entity.

        Args:
            entity_data: HA entity registry dict containing entity metadata.
        """
        super().__init__(DOOR_SENSOR_CATEGORY, entity_data)
        self.is_open = False

    def fill_by_ha_state(self, ha_state: dict) -> None:
        """Parse HA state and update open/close status.

        Args:
            ha_state: HA state dict; 'on' means door is open.
        """
        super().fill_by_ha_state(ha_state)
        self.is_open = ha_state.get("state") == "on"

    def _get_sber_value(self) -> str:
        """Return door state as Sber ENUM value."""
        return "open" if self.is_open else "close"
