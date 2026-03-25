"""Sber Smoke Sensor entity -- maps HA smoke binary sensors to Sber sensor_smoke."""

from __future__ import annotations

import logging

from ..sber_constants import SberFeature
from ..sber_models import make_bool_value, make_state
from .simple_sensor import SimpleReadOnlySensor

_LOGGER = logging.getLogger(__name__)

SMOKE_SENSOR_CATEGORY = "sensor_smoke"
"""Sber device category for smoke sensor entities."""


class SmokeSensorEntity(SimpleReadOnlySensor):
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

    def __init__(self, entity_data: dict) -> None:
        """Initialize smoke sensor entity.

        Args:
            entity_data: HA entity registry dict containing entity metadata.
        """
        super().__init__(SMOKE_SENSOR_CATEGORY, entity_data)
        self.smoke_detected: bool = False
        self._alarm_mute: bool | None = None

    def fill_by_ha_state(self, ha_state: dict) -> None:
        """Parse HA state and update smoke detection flag and alarm_mute.

        Args:
            ha_state: HA state dict; 'on' means smoke detected.
        """
        super().fill_by_ha_state(ha_state)
        self.smoke_detected = ha_state.get("state") == "on"
        attrs = ha_state.get("attributes", {})
        alarm_mute = attrs.get("alarm_mute")
        if alarm_mute is not None:
            self._alarm_mute = bool(alarm_mute)

    def create_features_list(self) -> list[str]:
        """Return Sber feature list including alarm_mute when available."""
        features = super().create_features_list()
        if self._alarm_mute is not None:
            features.append("alarm_mute")
        return features

    def to_sber_current_state(self) -> dict[str, dict]:
        """Build Sber current state payload with alarm_mute when available."""
        result = super().to_sber_current_state()
        if self._alarm_mute is not None:
            result[self.entity_id]["states"].append(
                make_state(SberFeature.ALARM_MUTE, make_bool_value(self._alarm_mute))
            )
        return result

    def _get_sber_value(self) -> bool:
        """Return whether smoke is currently detected."""
        return self.smoke_detected
