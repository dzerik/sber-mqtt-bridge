"""Sber Gas Sensor entity -- maps HA gas binary sensors to Sber sensor_gas."""

from __future__ import annotations

import logging

from ..sber_constants import SberFeature
from ..sber_models import make_bool_value, make_state
from .simple_sensor import SimpleReadOnlySensor

_LOGGER = logging.getLogger(__name__)

GAS_SENSOR_CATEGORY = "sensor_gas"
"""Sber device category for gas leak sensor entities."""


class GasSensorEntity(SimpleReadOnlySensor):
    """Sber gas sensor entity.

    Reports gas leak detection state from HA binary_sensor entities
    (device_class=gas) to the Sber cloud via the ``gas_leak_state`` feature.

    Per Sber specification, ``gas_leak_state`` uses BOOL type:
    - ``true`` = gas leak detected
    - ``false`` = no gas leak

    Optionally supports ``alarm_mute`` (BOOL) if the HA entity
    provides it in attributes.
    """

    _sber_value_key = "gas_leak_state"
    _sber_value_type = "BOOL"
    _unknown_is_online = True

    def __init__(self, entity_data: dict) -> None:
        """Initialize gas sensor entity.

        Args:
            entity_data: HA entity registry dict containing entity metadata.
        """
        super().__init__(GAS_SENSOR_CATEGORY, entity_data)
        self.gas_detected: bool = False
        self._tamper: bool | None = None
        self._alarm_mute: bool | None = None

    def fill_by_ha_state(self, ha_state: dict) -> None:
        """Parse HA state and update gas leak detection flag, tamper and alarm_mute.

        Args:
            ha_state: HA state dict; 'on' means gas leak detected.
        """
        super().fill_by_ha_state(ha_state)
        self.gas_detected = ha_state.get("state") == "on"
        attrs = ha_state.get("attributes", {})
        tamper = attrs.get("tamper")
        if tamper is not None:
            self._tamper = bool(tamper)
        alarm_mute = attrs.get("alarm_mute")
        if alarm_mute is not None:
            self._alarm_mute = bool(alarm_mute)

    def create_features_list(self) -> list[str]:
        """Return Sber feature list including tamper_alarm and alarm_mute when available."""
        features = super().create_features_list()
        if self._tamper is not None:
            features.append("tamper_alarm")
        if self._alarm_mute is not None:
            features.append("alarm_mute")
        return features

    def to_sber_current_state(self) -> dict[str, dict]:
        """Build Sber current state payload with tamper_alarm and alarm_mute."""
        result = super().to_sber_current_state()
        if self._tamper is not None:
            result[self.entity_id]["states"].append(make_state(SberFeature.TAMPER_ALARM, make_bool_value(self._tamper)))
        if self._alarm_mute is not None:
            result[self.entity_id]["states"].append(
                make_state(SberFeature.ALARM_MUTE, make_bool_value(self._alarm_mute))
            )
        return result

    def _get_sber_value(self) -> bool:
        """Return whether a gas leak is currently detected."""
        return self.gas_detected
