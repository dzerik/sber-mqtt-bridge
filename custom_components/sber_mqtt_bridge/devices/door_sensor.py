"""Sber Door Sensor entity -- maps HA door/window/garage binary sensors to Sber sensor_door."""

from __future__ import annotations

import logging

from .base_entity import BaseEntity

logger = logging.getLogger(__name__)

DOOR_SENSOR_CATEGORY = "sensor_door"
"""Sber device category for door/window contact sensor entities."""


class DoorSensorEntity(BaseEntity):
    """Sber door sensor entity.

    Reports open/close state from HA binary_sensor entities
    (device_class=door, window, garage_door) to the Sber cloud
    via the ``doorcontact_state`` feature.
    """

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

    def create_features_list(self) -> list[str]:
        """Return Sber feature list including 'doorcontact_state'.

        Returns:
            List of Sber feature strings supported by this entity.
        """
        return super().create_features_list() + ["doorcontact_state"]

    def to_sber_current_state(self) -> dict[str, dict]:
        """Build Sber current state payload with online and doorcontact_state.

        The door state is reported as an ENUM with values 'open' or 'close'.

        Returns:
            Dict mapping entity_id to its Sber state representation.
        """
        is_online = self.state not in ("unavailable", "unknown", None)
        states = [
            {"key": "online", "value": {"type": "BOOL", "bool_value": is_online}},
            {"key": "doorcontact_state", "value": {"type": "ENUM", "enum_value": "open" if self.is_open else "close"}},
        ]
        return {self.entity_id: {"states": states}}

    def process_cmd(self, cmd_data: dict) -> list[dict]:
        """Process Sber command (no-op for read-only sensor).

        Args:
            cmd_data: Sber command dict (ignored).

        Returns:
            Empty list -- sensors do not accept commands.
        """
        return []

    def process_state_change(self, old_state: dict | None, new_state: dict) -> None:
        """Handle HA state change event by refreshing internal state.

        Args:
            old_state: Previous HA state dict (unused).
            new_state: New HA state dict to apply.
        """
        self.fill_by_ha_state(new_state)
