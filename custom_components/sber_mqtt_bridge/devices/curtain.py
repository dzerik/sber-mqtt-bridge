"""Sber Curtain entity -- maps HA cover entities to Sber curtain category."""

from __future__ import annotations

import contextlib
import logging

from ..sber_constants import SberFeature
from ..sber_models import make_bool_value, make_enum_value, make_integer_value, make_state
from .base_entity import BaseEntity
from .utils.signal import rssi_to_signal_strength

CURTAIN_ENTITY_CATEGORY = "curtain"
"""Sber device category for curtain/cover entities."""

_LOGGER = logging.getLogger(__name__)


class CurtainEntity(BaseEntity):
    """Sber curtain entity for cover control with position support.

    Maps HA cover entities to the Sber 'curtain' category with support for:
    - Position control (0-100%)
    - Open/close/stop commands
    - Open state reporting
    """

    current_position: int = 0
    """Current cover position (0-100%)."""

    min_position: int = 0
    """Minimum allowed position (0-100%)."""

    max_position: int = 100
    """Maximum allowed position (0-100%)."""

    battery_level: int = 0
    """Battery level percentage (0-100%)."""

    def __init__(self, entity_data: dict, category: str = CURTAIN_ENTITY_CATEGORY) -> None:
        """Initialize curtain entity.

        Args:
            entity_data: HA entity registry dict containing entity metadata.
            category: Sber device category (override in subclasses).
        """
        super().__init__(category, entity_data)
        self.current_position = 0
        self._battery_level: int | None = None
        self._battery_low: bool | None = None
        self._signal_strength_raw: int | None = None

    def fill_by_ha_state(self, ha_state: dict) -> None:
        """Update state from Home Assistant data.

        Reads ``current_position`` from attributes; falls back to 100
        if state is 'opened', otherwise 0. Also reads signal strength
        from ``signal_strength``, ``rssi``, or ``linkquality``.

        Args:
            ha_state: HA state dict with 'state' and 'attributes' keys.
        """
        super().fill_by_ha_state(ha_state)
        attrs = ha_state.get("attributes", {})

        position = attrs.get("current_position")
        if position is not None:
            self.current_position = position
        else:
            self.current_position = 100 if self.state == "opened" else 0

        battery = attrs.get("battery") or attrs.get("battery_level")
        if battery is not None:
            try:
                self._battery_level = int(battery)
            except (TypeError, ValueError):
                self._battery_level = None

        rssi = attrs.get("signal_strength") or attrs.get("rssi") or attrs.get("linkquality")
        if rssi is not None:
            try:
                self._signal_strength_raw = int(rssi)
            except (TypeError, ValueError):
                self._signal_strength_raw = None
        else:
            self._signal_strength_raw = None

    def update_linked_data(self, role: str, ha_state: dict) -> None:
        """Inject data from a linked entity (battery, battery_low, signal).

        Args:
            role: Link role name.
            ha_state: HA state dict with 'state'.
        """
        state_val = ha_state.get("state")
        if state_val in (None, "unknown", "unavailable"):
            return
        if role == "battery":
            with contextlib.suppress(TypeError, ValueError):
                self._battery_level = int(float(state_val))
        elif role == "battery_low":
            self._battery_low = state_val == "on"
        elif role == "signal_strength":
            with contextlib.suppress(TypeError, ValueError):
                self._signal_strength_raw = int(float(state_val))

    def _convert_position(self, ha_position: int) -> int:
        """Convert HA position (0-100) to Sber position (0-100).

        Currently a 1:1 mapping; override in subclasses if needed.

        Args:
            ha_position: Position value from Home Assistant.

        Returns:
            Position value for Sber protocol.
        """
        return int(ha_position)

    def process_cmd(self, cmd_data: dict) -> list[dict]:
        """Process Sber curtain commands and produce HA service calls.

        Handles the following Sber keys:
        - ``open_percentage``: set_cover_position (INTEGER 0-100)
        - ``cover_position``: set_cover_position (INTEGER 0-100)
        - ``open_set``: open_cover / close_cover / stop_cover (ENUM)

        Args:
            cmd_data: Sber command dict with 'states' list.

        Returns:
            List of HA service call dicts to execute.
        """
        processing_result = []

        for data_item in cmd_data.get("states", []):
            key = data_item.get("key")
            value = data_item.get("value", {})

            if key is None:
                continue

            if key in ("open_percentage", "cover_position"):
                ha_position = self._safe_int(value.get("integer_value")) or 0
                ha_position = max(0, min(100, ha_position))
                processing_result.append(
                    {
                        "url": {
                            "type": "call_service",
                            "domain": "cover",
                            "service": "set_cover_position",
                            "service_data": {"position": ha_position},
                            "target": {"entity_id": self.entity_id},
                        }
                    }
                )

            if key == "open_set":
                action = value.get("enum_value", None)
                if action is None:
                    continue

                if action == "open":
                    processing_result.append(
                        {
                            "url": {
                                "type": "call_service",
                                "domain": "cover",
                                "service": "open_cover",
                                "target": {"entity_id": self.entity_id},
                            }
                        }
                    )

                elif action == "close":
                    processing_result.append(
                        {
                            "url": {
                                "type": "call_service",
                                "domain": "cover",
                                "service": "close_cover",
                                "target": {"entity_id": self.entity_id},
                            }
                        }
                    )

                elif action == "stop":
                    processing_result.append(
                        {
                            "url": {
                                "type": "call_service",
                                "domain": "cover",
                                "service": "stop_cover",
                                "target": {"entity_id": self.entity_id},
                            }
                        }
                    )

        return processing_result

    def create_features_list(self) -> list[str]:
        """Return Sber feature list for curtain capabilities.

        Includes open_percentage, open_set, open_state, and optionally
        signal_strength features.

        Returns:
            List of Sber feature strings supported by this entity.
        """
        features = [
            *super().create_features_list(),
            "open_percentage",
            "open_set",
            "open_state",
        ]
        if self._battery_level is not None or self._battery_low is not None:
            features.append("battery_percentage")
            features.append("battery_low_power")
        if self._signal_strength_raw is not None:
            features.append("signal_strength")
        return features

    def create_allowed_values_list(self) -> dict[str, dict]:
        """Return allowed values for open_set and open_percentage features."""
        return {
            "open_set": {
                "type": "ENUM",
                "enum_values": {"values": ["open", "close", "stop"]},
            },
            "open_percentage": {
                "type": "INTEGER",
                "integer_values": {"min": "0", "max": "100", "step": "1"},
            },
        }

    def to_sber_current_state(self) -> dict[str, dict]:
        """Build Sber current state payload with position, open state, and signal.

        Per Sber C2C specification, ``integer_value`` is serialized as a string.

        Returns:
            Dict mapping entity_id to its Sber state representation.
        """
        if not self._is_online:
            states = [
                make_state(SberFeature.ONLINE, make_bool_value(False)),
            ]
            return {self.entity_id: {"states": states}}

        states = [
            make_state(SberFeature.ONLINE, make_bool_value(True)),
        ]

        states.append(
            make_state(SberFeature.OPEN_PERCENTAGE, make_integer_value(self._convert_position(self.current_position)))
        )

        # Enforce consistency: open_state must match open_percentage
        sber_pos = self._convert_position(self.current_position)
        state_map = {"open": "open", "opening": "open", "closed": "close", "closing": "close"}
        open_state = state_map.get(self.state, "close" if sber_pos == 0 else "open")
        # Force alignment: if percentage > 0, state must be 'open'; if 0, must be 'close'
        if sber_pos > 0 and open_state == "close":
            open_state = "open"
        elif sber_pos == 0 and open_state == "open":
            open_state = "close"
        states.append(
            make_state(SberFeature.OPEN_STATE, make_enum_value(open_state))
        )

        if self._battery_level is not None:
            states.append(
                make_state(SberFeature.BATTERY_PERCENTAGE, make_integer_value(self._battery_level))
            )
            battery_low = self._battery_low if self._battery_low is not None else self._battery_level < 20
            states.append(
                make_state(SberFeature.BATTERY_LOW_POWER, make_bool_value(battery_low))
            )
        elif self._battery_low is not None:
            states.append(
                make_state(SberFeature.BATTERY_LOW_POWER, make_bool_value(self._battery_low))
            )

        if self._signal_strength_raw is not None:
            states.append(
                make_state(SberFeature.SIGNAL_STRENGTH, make_enum_value(rssi_to_signal_strength(self._signal_strength_raw)))
            )

        return {self.entity_id: {"states": states}}
