"""Sber Humidity Sensor entity -- maps HA humidity sensors to Sber sensor_temp category."""

from __future__ import annotations

import contextlib
import logging

from ..sber_constants import SberFeature
from ..sber_models import make_integer_value, make_state
from .simple_sensor import SimpleReadOnlySensor

_LOGGER = logging.getLogger(__name__)

HUMIDITY_SENSOR_CATEGORY = "sensor_temp"
"""Sber device category for humidity sensor entities (shares sensor_temp category)."""


class HumiditySensorEntity(SimpleReadOnlySensor):
    """Sber humidity sensor entity.

    Reports humidity readings from HA sensor entities to the Sber cloud.
    Humidity is transmitted as a plain integer percentage (0-100).
    """

    _sber_value_key = "humidity"
    _sber_value_type = "INTEGER"

    def __init__(self, entity_data: dict) -> None:
        """Initialize humidity sensor entity.

        Args:
            entity_data: HA entity registry dict containing entity metadata.
        """
        super().__init__(HUMIDITY_SENSOR_CATEGORY, entity_data)
        self.humidity = 0.0
        self._linked_temperature: float | None = None

    def fill_by_ha_state(self, ha_state: dict) -> None:
        """Parse HA state and update humidity value.

        Args:
            ha_state: HA state dict with 'state' containing the humidity reading.
        """
        super().fill_by_ha_state(ha_state)
        try:
            self.humidity = float(ha_state.get("state", 0))
        except (ValueError, TypeError):
            self.humidity = 0.0

    def update_linked_data(self, role: str, ha_state: dict) -> None:
        """Inject data from a linked entity (temperature, battery, signal).

        Args:
            role: Link role name.
            ha_state: HA state dict.
        """
        super().update_linked_data(role, ha_state)
        if role == "temperature":
            state_val = ha_state.get("state")
            if state_val not in (None, "unknown", "unavailable"):
                with contextlib.suppress(TypeError, ValueError):
                    self._linked_temperature = float(state_val)

    def create_features_list(self) -> list[str]:
        """Return Sber feature list including temperature when linked.

        Returns:
            List of Sber feature strings supported by this entity.
        """
        features = super().create_features_list()
        if self._linked_temperature is not None:
            features.append("temperature")
        return features

    def to_sber_current_state(self) -> dict[str, dict]:
        """Build Sber current state payload with linked temperature.

        Returns:
            Dict mapping entity_id to its Sber state representation.
        """
        result = super().to_sber_current_state()
        if self._linked_temperature is not None:
            result[self.entity_id]["states"].append(
                make_state(SberFeature.TEMPERATURE, make_integer_value(int(self._linked_temperature * 10)))
            )
        return result

    def _get_sber_value(self) -> int:
        """Return humidity as integer percentage (0-100)."""
        return round(self.humidity)
