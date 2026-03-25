"""Sber Temperature Sensor entity -- maps HA temperature sensors to Sber sensor_temp."""

from __future__ import annotations

import contextlib
import logging

from ..sber_constants import SberFeature
from ..sber_models import make_integer_value, make_state
from .simple_sensor import SimpleReadOnlySensor

_LOGGER = logging.getLogger(__name__)

SENSOR_TEMP_CATEGORY = "sensor_temp"
"""Sber device category for temperature sensor entities."""


class SensorTempEntity(SimpleReadOnlySensor):
    """Sber temperature sensor entity.

    Reports temperature readings from HA sensor entities to the Sber cloud.
    Temperature is transmitted as an integer value multiplied by 10
    (e.g. 22.5 C becomes 225).
    """

    _sber_value_key = "temperature"
    _sber_value_type = "INTEGER"

    def __init__(self, entity_data: dict) -> None:
        """Initialize temperature sensor entity.

        Args:
            entity_data: HA entity registry dict containing entity metadata.
        """
        super().__init__(SENSOR_TEMP_CATEGORY, entity_data)
        self.temperature = 0.0
        self._air_pressure: int | None = None
        self._linked_humidity: int | None = None

    def fill_by_ha_state(self, ha_state: dict) -> None:
        """Parse HA state and update temperature and air pressure values.

        Args:
            ha_state: HA state dict with 'state' containing the temperature reading.
                Attributes may include 'pressure' for air pressure.
        """
        super().fill_by_ha_state(ha_state)
        try:
            self.temperature = float(ha_state.get("state", 0))
        except (ValueError, TypeError):
            self.temperature = 0.0
        attrs = ha_state.get("attributes", {})
        pressure = attrs.get("pressure")
        if pressure is not None:
            try:
                self._air_pressure = int(pressure)
            except (TypeError, ValueError):
                self._air_pressure = None
        else:
            self._air_pressure = None

    def update_linked_data(self, role: str, ha_state: dict) -> None:
        """Inject data from a linked entity (humidity, battery, signal).

        Args:
            role: Link role name.
            ha_state: HA state dict.
        """
        super().update_linked_data(role, ha_state)
        if role == "humidity":
            state_val = ha_state.get("state")
            if state_val not in (None, "unknown", "unavailable"):
                with contextlib.suppress(TypeError, ValueError):
                    self._linked_humidity = round(float(state_val))

    def create_features_list(self) -> list[str]:
        """Return Sber feature list including humidity and air_pressure when available.

        Returns:
            List of Sber feature strings supported by this entity.
        """
        features = super().create_features_list()
        if self._linked_humidity is not None:
            features.append("humidity")
        if self._air_pressure is not None:
            features.append("air_pressure")
        return features

    def to_sber_current_state(self) -> dict[str, dict]:
        """Build Sber current state payload with linked humidity and air_pressure.

        Returns:
            Dict mapping entity_id to its Sber state representation.
        """
        result = super().to_sber_current_state()
        if self._linked_humidity is not None:
            result[self.entity_id]["states"].append(
                make_state(SberFeature.HUMIDITY, make_integer_value(self._linked_humidity))
            )
        if self._air_pressure is not None:
            result[self.entity_id]["states"].append(
                make_state(SberFeature.AIR_PRESSURE, make_integer_value(self._air_pressure))
            )
        return result

    def _get_sber_value(self) -> int:
        """Return temperature as integer scaled by 10."""
        return int(self.temperature * 10)
