"""Sber Valve entity -- maps HA valve entities to Sber valve category.

Uses ``open_set``/``open_state`` features (NOT ``on_off``).
Per Sber specification, valve is controlled via ENUM open/close/stop commands.
Supports optional battery and signal strength reporting.
"""

from __future__ import annotations

import logging

from .base_entity import BaseEntity
from .utils.signal import rssi_to_signal_strength

_LOGGER = logging.getLogger(__name__)

VALVE_CATEGORY = "valve"
"""Sber device category for valve entities."""


class ValveEntity(BaseEntity):
    """Sber valve entity for open/close valve control.

    Maps HA valve entities to the Sber 'valve' category.
    Uses ``open_set`` (command) and ``open_state`` (state) features
    per Sber specification. Does NOT use ``on_off``.

    Optionally reports ``battery_percentage``, ``battery_low_power``,
    and ``signal_strength`` when the HA entity provides these attributes.
    """

    def __init__(self, entity_data: dict) -> None:
        """Initialize valve entity.

        Args:
            entity_data: HA entity registry dict containing entity metadata.
        """
        super().__init__(VALVE_CATEGORY, entity_data)
        self.is_open: bool = False
        self._battery_level: int | None = None
        self._signal_strength_raw: int | None = None

    def fill_by_ha_state(self, ha_state: dict) -> None:
        """Parse HA state and update open/close status, battery, and signal.

        Args:
            ha_state: HA state dict with 'state' and 'attributes' keys.
        """
        super().fill_by_ha_state(ha_state)
        self.is_open = ha_state.get("state") == "open"
        attrs = ha_state.get("attributes", {})

        battery = attrs.get("battery") or attrs.get("battery_level")
        if battery is not None:
            try:
                self._battery_level = int(battery)
            except (TypeError, ValueError):
                self._battery_level = None
        else:
            self._battery_level = None

        rssi = attrs.get("signal_strength") or attrs.get("rssi") or attrs.get("linkquality")
        if rssi is not None:
            try:
                self._signal_strength_raw = int(rssi)
            except (TypeError, ValueError):
                self._signal_strength_raw = None
        else:
            self._signal_strength_raw = None

    def create_features_list(self) -> list[str]:
        """Return Sber feature list with open_set, open_state, and optional battery/signal.

        Returns:
            List of Sber feature strings supported by this entity.
        """
        features = [*super().create_features_list(), "open_set", "open_state"]
        if self._battery_level is not None:
            features.append("battery_percentage")
            features.append("battery_low_power")
        if self._signal_strength_raw is not None:
            features.append("signal_strength")
        return features

    def create_allowed_values_list(self) -> dict[str, dict]:
        """Return allowed values for the open_set feature."""
        return {
            "open_set": {
                "type": "ENUM",
                "enum_values": {"values": ["open", "close", "stop"]},
            },
        }

    def to_sber_current_state(self) -> dict[str, dict]:
        """Build Sber current state payload with online, open_state, battery, and signal.

        Returns:
            Dict mapping entity_id to its Sber state representation.
        """
        states = [
            {"key": "online", "value": {"type": "BOOL", "bool_value": self._is_online}},
            {"key": "open_state", "value": {"type": "ENUM", "enum_value": "open" if self.is_open else "close"}},
        ]
        if self._battery_level is not None:
            states.append(
                {"key": "battery_percentage", "value": {"type": "INTEGER", "integer_value": str(self._battery_level)}}
            )
            states.append(
                {"key": "battery_low_power", "value": {"type": "BOOL", "bool_value": self._battery_level < 20}}
            )
        if self._signal_strength_raw is not None:
            states.append(
                {
                    "key": "signal_strength",
                    "value": {"type": "ENUM", "enum_value": rssi_to_signal_strength(self._signal_strength_raw)},
                }
            )
        return {self.entity_id: {"states": states}}

    def process_cmd(self, cmd_data: dict) -> list[dict]:
        """Process Sber open_set command and produce HA valve service calls.

        Maps ``open_set`` ENUM values:
        - ``"open"`` -> ``open_valve``
        - ``"close"`` -> ``close_valve``
        - ``"stop"`` -> ``stop_valve``

        State is NOT mutated here -- it will be updated when HA fires a
        ``state_changed`` event that is handled by ``fill_by_ha_state``.

        Args:
            cmd_data: Sber command dict with 'states' list.

        Returns:
            List of HA service call dicts to execute.
        """
        results: list[dict] = []
        service_map = {
            "open": "open_valve",
            "close": "close_valve",
            "stop": "stop_valve",
        }
        for item in cmd_data.get("states", []):
            key = item.get("key")
            value = item.get("value", {})

            if key == "open_set" and value.get("type") == "ENUM":
                action = value.get("enum_value")
                service = service_map.get(action)
                if service:
                    results.append(
                        {
                            "url": {
                                "type": "call_service",
                                "domain": "valve",
                                "service": service,
                                "target": {"entity_id": self.entity_id},
                            }
                        }
                    )
        return results
