"""Sber HVAC Air Purifier entity -- maps HA fan entities to Sber hvac_air_purifier category.

Supports on/off control, fan speed via ``hvac_air_flow_power``, and
read-only features: ionization, night mode, aromatization, filter/ionizer replacement.
"""

from __future__ import annotations

import logging

from .base_entity import BaseEntity

_LOGGER = logging.getLogger(__name__)

HVAC_AIR_PURIFIER_CATEGORY = "hvac_air_purifier"
"""Sber device category for air purifier entities."""

SBER_SPEED_VALUES = ["auto", "high", "low", "medium", "turbo"]
"""Allowed Sber ENUM values for hvac_air_flow_power."""

_SBER_SPEED_TO_PERCENTAGE: dict[str, int] = {
    "low": 25,
    "medium": 50,
    "high": 75,
    "turbo": 100,
    "auto": 0,
}
"""Reverse mapping: Sber speed ENUM to HA percentage. 'auto' maps to 0 (turn_on)."""

_PERCENTAGE_TO_SPEED = [
    (0, "low"),
    (34, "medium"),
    (67, "high"),
    (100, "turbo"),
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


class HvacAirPurifierEntity(BaseEntity):
    """Sber air purifier entity for purifier fan devices.

    Maps HA fan entities (with device_class purifier/air_purifier) to the
    Sber 'hvac_air_purifier' category with support for:
    - On/off control
    - Fan speed via preset_mode or percentage
    - Read-only flags: ionization, night mode, aromatization,
      filter replacement, ionizer replacement, decontamination
    """

    def __init__(self, entity_data: dict) -> None:
        """Initialize air purifier entity.

        Args:
            entity_data: HA entity registry dict containing entity metadata.
        """
        super().__init__(HVAC_AIR_PURIFIER_CATEGORY, entity_data)
        self.current_state: bool = False
        self.preset_mode: str | None = None
        self.preset_modes: list[str] = []
        self.percentage: int | None = None
        self._ionization: bool = False
        self._night_mode: bool = False
        self._aromatization: bool = False
        self._replace_filter: bool = False
        self._replace_ionizator: bool = False
        self._decontaminate: bool = False

    def fill_by_ha_state(self, ha_state: dict) -> None:
        """Parse HA state and update air purifier attributes.

        Args:
            ha_state: HA state dict with 'state' and 'attributes' keys.
        """
        super().fill_by_ha_state(ha_state)
        self.current_state = ha_state.get("state") != "off"
        attrs = ha_state.get("attributes", {})
        self.preset_modes = attrs.get("preset_modes") or []
        self.preset_mode = attrs.get("preset_mode")
        self.percentage = attrs.get("percentage")
        self._ionization = bool(attrs.get("ionization", False))
        self._night_mode = bool(attrs.get("night_mode", False))
        self._aromatization = bool(attrs.get("aromatization", False))
        self._replace_filter = bool(attrs.get("replace_filter", False))
        self._replace_ionizator = bool(attrs.get("replace_ionizator", False))
        self._decontaminate = bool(attrs.get("decontaminate", False))

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
        """Return Sber feature list for air purifier capabilities.

        Returns:
            List of Sber feature strings supported by this entity.
        """
        features = [
            *super().create_features_list(),
            "on_off",
            "hvac_air_flow_power",
            "hvac_ionization",
            "hvac_night_mode",
            "hvac_aromatization",
            "hvac_replace_filter",
            "hvac_replace_ionizator",
        ]
        if self._decontaminate:
            features.append("hvac_decontaminate")
        return features

    def create_allowed_values_list(self) -> dict[str, dict]:
        """Build allowed values map for air flow power feature.

        Returns:
            Dict mapping feature key to its allowed ENUM values descriptor.
        """
        return {
            "hvac_air_flow_power": {
                "type": "ENUM",
                "enum_values": {"values": SBER_SPEED_VALUES},
            }
        }

    def to_sber_current_state(self) -> dict[str, dict]:
        """Build Sber current state payload with air purifier attributes.

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
        states.extend(
            [
                {"key": "hvac_ionization", "value": {"type": "BOOL", "bool_value": self._ionization}},
                {"key": "hvac_night_mode", "value": {"type": "BOOL", "bool_value": self._night_mode}},
                {"key": "hvac_aromatization", "value": {"type": "BOOL", "bool_value": self._aromatization}},
                {"key": "hvac_replace_filter", "value": {"type": "BOOL", "bool_value": self._replace_filter}},
                {"key": "hvac_replace_ionizator", "value": {"type": "BOOL", "bool_value": self._replace_ionizator}},
            ]
        )
        if self._decontaminate:
            states.append({"key": "hvac_decontaminate", "value": {"type": "BOOL", "bool_value": self._decontaminate}})
        return {self.entity_id: {"states": states}}

    def process_cmd(self, cmd_data: dict) -> list[dict]:
        """Process Sber air purifier commands and produce HA service calls.

        Handles the following Sber keys:
        - ``on_off``: fan.turn_on / fan.turn_off
        - ``hvac_air_flow_power``: fan.set_preset_mode (if mode matches)
          or fan.set_percentage (converted from speed ENUM)

        Other features (ionization, night_mode, etc.) are read-only.

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
                    pct = _SBER_SPEED_TO_PERCENTAGE.get(speed)
                    if pct is not None:
                        if pct == 0:
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
