"""Sber Temperature Sensor entity -- maps HA temperature sensors to Sber sensor_temp."""

from __future__ import annotations

import logging

from .base_entity import BaseEntity

logger = logging.getLogger(__name__)

SENSOR_TEMP_CATEGORY = "sensor_temp"
"""Sber device category for temperature sensor entities."""


class SensorTempEntity(BaseEntity):
    """Sber temperature sensor entity.

    Reports temperature readings from HA sensor entities to the Sber cloud.
    Temperature is transmitted as an integer value multiplied by 10
    (e.g. 22.5 C becomes 225).
    """

    def __init__(self, entity_data: dict) -> None:
        """Initialize temperature sensor entity.

        Args:
            entity_data: HA entity registry dict containing entity metadata.
        """
        super().__init__(SENSOR_TEMP_CATEGORY, entity_data)
        self.temperature = 0.0

    def fill_by_ha_state(self, ha_state: dict) -> None:
        """Parse HA state and update temperature value.

        Args:
            ha_state: HA state dict with 'state' containing the temperature reading.
        """
        super().fill_by_ha_state(ha_state)
        try:
            self.temperature = float(ha_state.get("state", 0))
        except (ValueError, TypeError):
            self.temperature = 0.0

    def create_features_list(self) -> list[str]:
        """Return Sber feature list including 'temperature'.

        Returns:
            List of Sber feature strings supported by this entity.
        """
        return [*super().create_features_list(), "temperature"]

    def to_sber_current_state(self) -> dict[str, dict]:
        """Build Sber current state payload with online and temperature keys.

        Temperature is encoded as ``integer_value = int(temperature * 10)``.

        Returns:
            Dict mapping entity_id to its Sber state representation.
        """
        is_online = self.state not in ("unavailable", "unknown", None)
        states = [
            {"key": "online", "value": {"type": "BOOL", "bool_value": is_online}},
            {"key": "temperature", "value": {"type": "INTEGER", "integer_value": int(self.temperature * 10)}},
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
