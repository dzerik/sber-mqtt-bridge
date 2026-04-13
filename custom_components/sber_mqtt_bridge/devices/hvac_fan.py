"""Sber HVAC Fan entity -- maps HA fan entities to Sber hvac_fan category.

Supports on/off control and fan speed via the ``hvac_air_flow_power`` feature.
"""

from __future__ import annotations

import logging
from typing import ClassVar

from ..sber_constants import SberFeature, SberValueType
from ..sber_models import make_bool_value, make_enum_value, make_state
from .base_entity import AttrSpec, BaseEntity, CommandResult

_LOGGER = logging.getLogger(__name__)

HVAC_FAN_CATEGORY = "hvac_fan"
"""Sber device category for fan entities."""

SBER_SPEED_VALUES = ["auto", "high", "low", "medium", "quiet", "turbo"]
"""Allowed Sber ENUM values for hvac_air_flow_power (per Sber C2C spec)."""

_SBER_SPEED_TO_PERCENTAGE: dict[str, int] = {
    "quiet": 10,
    "low": 25,
    "medium": 50,
    "high": 75,
    "turbo": 100,
    "auto": 0,
}
"""Reverse mapping: Sber speed ENUM to HA percentage. 'auto' maps to 0 (turn_on)."""

_PERCENTAGE_TO_SPEED = [
    (0, "quiet"),
    (20, "low"),
    (40, "medium"),
    (67, "high"),
    (90, "turbo"),
]
"""Mapping thresholds from HA percentage to Sber speed ENUM."""


def _percentage_to_sber_speed(percentage: int) -> str:
    """Convert HA fan percentage (0-100) to Sber speed ENUM.

    Args:
        percentage: Fan speed percentage (0-100).

    Returns:
        Sber speed ENUM string.
    """
    for threshold, speed in reversed(_PERCENTAGE_TO_SPEED):
        if percentage >= threshold:
            return speed
    return "low"


class HvacFanEntity(BaseEntity):
    """Sber fan entity for ventilator control.

    Maps HA fan entities to the Sber 'hvac_fan' category with support for:
    - On/off control
    - Fan speed via preset_mode or percentage-based speed mapping
    """

    ATTR_SPECS: ClassVar[tuple[AttrSpec, ...]] = (
        AttrSpec(
            field="preset_modes",
            converter=lambda attrs: attrs.get("preset_modes") or [],
            default=[],
        ),
        AttrSpec(
            field="preset_mode",
            attr_keys=("preset_mode",),
        ),
        AttrSpec(
            field="percentage",
            attr_keys=("percentage",),
        ),
    )

    def __init__(self, entity_data: dict) -> None:
        """Initialize fan entity.

        Args:
            entity_data: HA entity registry dict containing entity metadata.
        """
        super().__init__(HVAC_FAN_CATEGORY, entity_data)
        self.current_state: bool = False
        self.preset_mode: str | None = None
        self.preset_modes: list[str] = []
        self.percentage: int | None = None

    def fill_by_ha_state(self, ha_state: dict) -> None:
        """Parse HA state and update fan attributes.

        Args:
            ha_state: HA state dict with 'state' and 'attributes' keys.
        """
        super().fill_by_ha_state(ha_state)
        attrs = ha_state.get("attributes", {})
        self._apply_attr_specs(attrs)
        self.current_state = ha_state.get("state") != "off"

    def _get_sber_speed(self) -> str | None:
        """Get current fan speed as Sber ENUM value.

        Uses preset_mode if it matches Sber values, otherwise converts
        percentage to a speed ENUM.

        Returns:
            Sber speed string or None if not determinable.
        """
        if self.preset_mode and self.preset_mode in SBER_SPEED_VALUES:
            return self.preset_mode
        if self.percentage is not None:
            return _percentage_to_sber_speed(self.percentage)
        return None

    @property
    def _supports_speed(self) -> bool:
        """Check if this fan has speed control (preset_modes or percentage)."""
        return bool(self.preset_modes) or self.percentage is not None

    def _create_features_list(self) -> list[str]:
        """Return Sber feature list for fan capabilities.

        Only includes hvac_air_flow_power when the HA entity supports speed
        control. Simple on/off fans (e.g. relay overridden as fan) get only
        on_off.

        Returns:
            List of Sber feature strings supported by this entity.
        """
        features = [*super()._create_features_list(), "on_off"]
        if self._supports_speed:
            features.append("hvac_air_flow_power")
        return features

    def create_allowed_values_list(self) -> dict[str, dict]:
        """Build allowed values map for fan speed feature.

        Returns empty dict when the fan has no speed support.

        Returns:
            Dict mapping feature key to its allowed ENUM values descriptor.
        """
        if not self._supports_speed:
            return {}
        return {
            "hvac_air_flow_power": {
                "type": "ENUM",
                "enum_values": {"values": SBER_SPEED_VALUES},
            }
        }

    def to_sber_current_state(self) -> dict[str, dict]:
        """Build Sber current state payload with fan attributes.

        Returns:
            Dict mapping entity_id to its Sber state representation.
        """
        states = [
            make_state(SberFeature.ONLINE, make_bool_value(self._is_online)),
            make_state(SberFeature.ON_OFF, make_bool_value(self.current_state)),
        ]
        if self._supports_speed:
            speed = self._get_sber_speed() or "auto"
            states.append(make_state(SberFeature.HVAC_AIR_FLOW_POWER, make_enum_value(speed)))
        return {self.entity_id: {"states": states}}

    def process_cmd(self, cmd_data: dict) -> list[CommandResult]:
        """Process Sber fan commands and produce HA service calls.

        Handles the following Sber keys:
        - ``on_off``: fan.turn_on / fan.turn_off
        - ``hvac_air_flow_power``: fan.set_preset_mode (if mode matches)
          or fan.set_percentage (converted from speed ENUM)

        Args:
            cmd_data: Sber command dict with 'states' list.

        Returns:
            List of HA service call dicts to execute.
        """
        results: list[dict] = []
        for item in cmd_data.get("states", []):
            key = item.get("key", "")
            value = item.get("value", {})
            vtype = value.get("type", "")
            if key == SberFeature.ON_OFF and vtype == SberValueType.BOOL:
                on = value.get("bool_value", False)
                results.append(self._build_on_off_service_call(self.entity_id, "fan", on))
            elif key == SberFeature.HVAC_AIR_FLOW_POWER and vtype == SberValueType.ENUM:
                results.extend(self._cmd_fan_speed(value.get("enum_value")))
        return results

    def _cmd_fan_speed(self, speed: str | None) -> list[dict]:
        """Handle Sber fan speed ENUM → HA preset_mode or percentage."""
        if not speed:
            return []
        if speed in self.preset_modes:
            return [self._build_service_call("fan", "set_preset_mode", self.entity_id, {"preset_mode": speed})]
        pct = _SBER_SPEED_TO_PERCENTAGE.get(speed)
        if pct is None:
            return []
        if pct == 0:
            # 'auto' mode -- turn on without specific speed
            return [self._build_service_call("fan", "turn_on", self.entity_id)]
        return [self._build_service_call("fan", "set_percentage", self.entity_id, {"percentage": pct})]
