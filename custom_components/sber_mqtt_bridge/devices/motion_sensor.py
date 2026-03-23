"""Sber Motion Sensor entity -- maps HA motion binary sensors to Sber sensor_pir."""

from __future__ import annotations

import logging

from .base_entity import BaseEntity

logger = logging.getLogger(__name__)

MOTION_SENSOR_CATEGORY = "sensor_pir"
"""Sber device category for PIR / motion sensor entities."""


class MotionSensorEntity(BaseEntity):
    """Sber motion sensor entity.

    Reports motion detection state from HA binary_sensor entities
    (device_class=motion) to the Sber cloud via the ``pir`` feature.
    """

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

    def create_features_list(self) -> list[str]:
        """Return Sber feature list including 'pir'.

        Returns:
            List of Sber feature strings supported by this entity.
        """
        return [*super().create_features_list(), "pir"]

    def to_sber_current_state(self) -> dict[str, dict]:
        """Build Sber current state payload with online and pir keys.

        Returns:
            Dict mapping entity_id to its Sber state representation.
        """
        is_online = self.state not in ("unavailable", "unknown", None)
        states = [
            {"key": "online", "value": {"type": "BOOL", "bool_value": is_online}},
            {"key": "pir", "value": {"type": "BOOL", "bool_value": self.motion_detected}}
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
