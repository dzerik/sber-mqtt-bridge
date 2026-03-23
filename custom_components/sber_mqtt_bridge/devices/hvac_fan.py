"""Sber HVAC Fan entity -- maps HA fan entities to Sber hvac_fan category.

Supports on/off control and fan speed via the ``hvac_air_flow_power`` feature.
"""

from __future__ import annotations

import logging

from .base_entity import BaseEntity

_LOGGER = logging.getLogger(__name__)

HVAC_FAN_CATEGORY = "hvac_fan"
"""Sber device category for fan entities."""

SBER_SPEED_VALUES = ["auto", "high", "low", "medium", "turbo"]
"""Allowed Sber ENUM values for hvac_air_flow_power."""

_PERCENTAGE_TO_SPEED = [
    (0, "low"),
    (34, "medium"),
    (67, "high"),
    (101, "turbo"),
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
        self.current_state = ha_state.get("state") != "off"
        attrs = ha_state.get("attributes", {})
        self.preset_modes = attrs.get("preset_modes") or []
        self.preset_mode = attrs.get("preset_mode")
        self.percentage = attrs.get("percentage")

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

    def create_features_list(self) -> list[str]:
        """Return Sber feature list for fan capabilities.

        Returns:
            List of Sber feature strings supported by this entity.
        """
        return [*super().create_features_list(), "on_off", "hvac_air_flow_power"]

    def create_allowed_values_list(self) -> dict[str, dict]:
        """Build allowed values map for fan speed feature.

        Returns:
            Dict mapping feature key to its allowed ENUM values descriptor.
        """
        return {
            "hvac_air_flow_power": {
                "type": "ENUM",
                "enum_values": {"values": SBER_SPEED_VALUES},
            }
        }

    def to_sber_state(self) -> dict:
        """Build full Sber device descriptor including allowed values.

        Returns:
            Sber device descriptor dict with model, features, and allowed_values.
        """
        res = super().to_sber_state()
        res["model"]["allowed_values"] = self.create_allowed_values_list()
        return res

    def to_sber_current_state(self) -> dict[str, dict]:
        """Build Sber current state payload with fan attributes.

        Returns:
            Dict mapping entity_id to its Sber state representation.
        """
        states = [
            {"key": "online", "value": {"type": "BOOL", "bool_value": self._is_online}},
            {"key": "on_off", "value": {"type": "BOOL", "bool_value": self.current_state}},
        ]
        speed = self._get_sber_speed()
        if speed:
            states.append({"key": "hvac_air_flow_power", "value": {"type": "ENUM", "enum_value": speed}})
        return {self.entity_id: {"states": states}}

    def process_cmd(self, cmd_data: dict) -> list[dict]:
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
            key = item.get("key")
            value = item.get("value", {})

            if key == "on_off" and value.get("type") == "BOOL":
                on = value.get("bool_value", False)
                results.append(self._build_on_off_service_call(self.entity_id, "fan", on))

            elif key == "hvac_air_flow_power" and value.get("type") == "ENUM":
                speed = value.get("enum_value")
                if not speed:
                    continue
                # Try preset_mode first if the HA entity supports it
                if speed in self.preset_modes:
                    results.append(
                        {
                            "url": {
                                "type": "call_service",
                                "domain": "fan",
                                "service": "set_preset_mode",
                                "service_data": {"preset_mode": speed},
                                "target": {"entity_id": self.entity_id},
                            }
                        }
                    )
                else:
                    # Convert Sber speed to percentage
                    speed_to_pct = {"low": 25, "medium": 50, "high": 75, "turbo": 100, "auto": 0}
                    pct = speed_to_pct.get(speed)
                    if pct is not None:
                        if pct == 0:
                            # 'auto' mode -- turn on without specific speed
                            results.append(
                                {
                                    "url": {
                                        "type": "call_service",
                                        "domain": "fan",
                                        "service": "turn_on",
                                        "target": {"entity_id": self.entity_id},
                                    }
                                }
                            )
                        else:
                            results.append(
                                {
                                    "url": {
                                        "type": "call_service",
                                        "domain": "fan",
                                        "service": "set_percentage",
                                        "service_data": {"percentage": pct},
                                        "target": {"entity_id": self.entity_id},
                                    }
                                }
                            )
        return results
