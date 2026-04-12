"""Sber Curtain entity -- maps HA cover entities to Sber curtain category."""

from __future__ import annotations

import contextlib
import logging
from typing import ClassVar

from ..sber_constants import SberFeature
from ..sber_models import make_bool_value, make_enum_value, make_integer_value, make_state
from .base_entity import (
    SENSOR_LINK_ROLES,
    AttrSpec,
    BaseEntity,
    _safe_int_parser,
)
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

    LINKABLE_ROLES = SENSOR_LINK_ROLES

    ATTR_SPECS: ClassVar[tuple[AttrSpec, ...]] = (
        AttrSpec(
            field="_battery_level",
            attr_keys=("battery", "battery_level"),
            parser=_safe_int_parser,
        ),
        AttrSpec(
            field="_tilt_position",
            attr_keys=("current_tilt_position",),
            parser=_safe_int_parser,
        ),
        AttrSpec(
            field="_signal_strength_raw",
            attr_keys=("signal_strength", "rssi", "linkquality"),
            parser=_safe_int_parser,
        ),
    )

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
        self._open_rate: str | None = None
        self._tilt_position: int | None = None

    def fill_by_ha_state(self, ha_state: dict) -> None:
        """Update state from Home Assistant data.

        Battery level, tilt position and signal strength are parsed via
        :class:`AttrSpec`.  ``current_position`` and ``open_rate`` have
        custom fallback / mapping logic and stay imperative.

        Args:
            ha_state: HA state dict with 'state' and 'attributes' keys.
        """
        super().fill_by_ha_state(ha_state)
        attrs = ha_state.get("attributes", {})
        self._apply_attr_specs(attrs)
        self.current_position = self._parse_current_position(attrs)
        self._open_rate = self._parse_open_rate(attrs)

    def _parse_current_position(self, attrs: dict) -> int:
        """Parse ``current_position`` with fallback based on HA state."""
        position = attrs.get("current_position")
        if position is not None:
            try:
                return max(0, min(100, int(float(position))))
            except (TypeError, ValueError):
                pass
        return 100 if self.state in ("open", "opening") else 0

    @staticmethod
    def _parse_open_rate(attrs: dict) -> str | None:
        """Parse ``speed`` / ``motor_speed`` into a Sber ``open_rate`` value."""
        speed = attrs.get("speed") or attrs.get("motor_speed")
        if speed is None:
            return None
        speed_str = str(speed).lower()
        if speed_str not in ("auto", "low", "high"):
            return None
        return speed_str

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

    _OPEN_SET_SERVICE_MAP: ClassVar[dict[str, str]] = {
        "open": "open_cover",
        "close": "close_cover",
        "stop": "stop_cover",
    }
    """Map Sber ``open_set`` enum values to HA cover services."""

    def process_cmd(self, cmd_data: dict) -> list[dict]:
        """Process Sber curtain commands and produce HA service calls.

        Handles the following Sber keys:
        - ``open_percentage`` / ``cover_position``: set_cover_position (0-100)
        - ``open_set``: open_cover / close_cover / stop_cover

        Args:
            cmd_data: Sber command dict with 'states' list.

        Returns:
            List of HA service call dicts to execute.
        """
        results: list[dict] = []
        for data_item in cmd_data.get("states", []):
            key = data_item.get("key")
            value = data_item.get("value", {})
            if key is None:
                continue
            if key in (SberFeature.OPEN_PERCENTAGE, "cover_position"):
                results.extend(self._cmd_set_position(value))
            elif key == SberFeature.OPEN_SET:
                results.extend(self._cmd_open_set(value))
        return results

    def _cmd_set_position(self, value: dict) -> list[dict]:
        ha_position = self._safe_clamped_int(value.get("integer_value"), 0, 100)
        if ha_position is None:
            return []
        return [self._build_service_call("cover", "set_cover_position", self.entity_id, {"position": ha_position})]

    def _cmd_open_set(self, value: dict) -> list[dict]:
        action = value.get("enum_value")
        service = self._OPEN_SET_SERVICE_MAP.get(action or "")
        if service is None:
            return []
        return [self._build_service_call("cover", service, self.entity_id)]

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
        if self._open_rate is not None:
            features.append("open_rate")
        if self._tilt_position is not None:
            features.append("light_transmission_percentage")
        return features

    def create_allowed_values_list(self) -> dict[str, dict]:
        """Return allowed values for open_set, open_percentage, and open_rate features."""
        allowed: dict[str, dict] = {
            "open_set": {
                "type": "ENUM",
                "enum_values": {"values": ["open", "close", "stop"]},
            },
            "open_percentage": {
                "type": "INTEGER",
                "integer_values": {"min": "0", "max": "100", "step": "1"},
            },
        }
        # open_rate is read-only (HA cover has no set_speed service)
        # light_transmission_percentage maps to tilt — handled via open_percentage
        return allowed

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
        # Sber supports: open, close, opening, closing
        state_map = {"open": "open", "opening": "opening", "closed": "close", "closing": "closing"}
        open_state = state_map.get(self.state, "close" if sber_pos == 0 else "open")
        # Force alignment for stable states: percentage > 0 must be 'open'; 0 must be 'close'
        if self.state not in ("opening", "closing"):
            if sber_pos > 0 and open_state == "close":
                open_state = "open"
            elif sber_pos == 0 and open_state == "open":
                open_state = "close"
        states.append(make_state(SberFeature.OPEN_STATE, make_enum_value(open_state)))

        if self._battery_level is not None:
            states.append(make_state(SberFeature.BATTERY_PERCENTAGE, make_integer_value(self._battery_level)))
            battery_low = self._battery_low if self._battery_low is not None else self._battery_level < 20
            states.append(make_state(SberFeature.BATTERY_LOW_POWER, make_bool_value(battery_low)))
        elif self._battery_low is not None:
            states.append(make_state(SberFeature.BATTERY_LOW_POWER, make_bool_value(self._battery_low)))

        if self._signal_strength_raw is not None:
            states.append(
                make_state(
                    SberFeature.SIGNAL_STRENGTH, make_enum_value(rssi_to_signal_strength(self._signal_strength_raw))
                )
            )
        if self._open_rate is not None:
            states.append(make_state(SberFeature.OPEN_RATE, make_enum_value(self._open_rate)))
        if self._tilt_position is not None:
            states.append(
                make_state(SberFeature.LIGHT_TRANSMISSION_PERCENTAGE, make_integer_value(self._tilt_position))
            )

        return {self.entity_id: {"states": states}}
