"""Sber Water Leak Sensor entity -- maps HA moisture binary sensors to Sber sensor_water_leak."""

from __future__ import annotations

import logging

from .base_entity import BaseEntity

logger = logging.getLogger(__name__)

WATER_LEAK_SENSOR_CATEGORY = "sensor_water_leak"
"""Sber device category for water leak sensor entities."""


class WaterLeakSensorEntity(BaseEntity):
    """Sber water leak sensor entity.

    Reports leak detection state from HA binary_sensor entities
    (device_class=moisture) to the Sber cloud via the ``water_leak`` feature.
    """

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

    def create_features_list(self) -> list[str]:
        """Return Sber feature list including 'water_leak'.

        Returns:
            List of Sber feature strings supported by this entity.
        """
        return [*super().create_features_list(), "water_leak"]

    def to_sber_current_state(self) -> dict[str, dict]:
        """Build Sber current state payload with online and water_leak keys.

        Returns:
            Dict mapping entity_id to its Sber state representation.
        """
        is_online = self.state not in ("unavailable", "unknown", None)
        states = [
            {"key": "online", "value": {"type": "BOOL", "bool_value": is_online}},
            {"key": "water_leak", "value": {"type": "BOOL", "bool_value": self.leak_detected}},
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
