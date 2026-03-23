"""Sber Climate (AC) entity -- maps HA climate entities to Sber hvac_ac category."""

from __future__ import annotations

import logging

from .base_entity import BaseEntity

_LOGGER = logging.getLogger(__name__)

CLIMATE_CATEGORY = "hvac_ac"
"""Sber device category for air conditioner / HVAC entities."""


class ClimateEntity(BaseEntity):
    """Sber climate entity for air conditioner control.

    Maps HA climate entities to the Sber 'hvac_ac' category with support for:
    - On/off control
    - Temperature reading and target temperature setting
    - Fan mode, swing mode, and HVAC work mode selection
    - Allowed values for dynamic enum features
    """

    def __init__(
        self,
        entity_data: dict,
        category: str = CLIMATE_CATEGORY,
        min_temp: float = 16.0,
        max_temp: float = 32.0,
    ) -> None:
        """Initialize climate entity.

        Args:
            entity_data: HA entity registry dict containing entity metadata.
            category: Sber device category (override in subclasses).
            min_temp: Minimum temperature default.
            max_temp: Maximum temperature default.
        """
        super().__init__(category, entity_data)
        self.current_state = False
        self.temperature = None
        self.target_temperature = None
        self.fan_modes = []
        self.swing_modes = []
        self.hvac_modes = []
        self.fan_mode = None
        self.swing_mode = None
        self.hvac_mode = None
        self.min_temp = min_temp
        self.max_temp = max_temp

    def fill_by_ha_state(self, ha_state: dict) -> None:
        """Parse HA state and update all climate attributes.

        Args:
            ha_state: HA state dict with 'state' and 'attributes' keys.
                Attributes may include current_temperature, temperature,
                fan_modes, swing_modes, hvac_modes, etc.
        """
        super().fill_by_ha_state(ha_state)
        self.current_state = ha_state.get("state", "off") != "off"
        attrs = ha_state.get("attributes", {})
        self.temperature = attrs.get("current_temperature")
        self.target_temperature = attrs.get("temperature")
        self.fan_modes = attrs.get("fan_modes", [])
        self.swing_modes = attrs.get("swing_modes", [])
        self.hvac_modes = attrs.get("hvac_modes", [])
        self.fan_mode = attrs.get("fan_mode")
        self.swing_mode = attrs.get("swing_mode")
        self.hvac_mode = ha_state.get("state")
        self.min_temp = attrs.get("min_temp", 16.0)
        self.max_temp = attrs.get("max_temp", 32.0)

    def create_features_list(self) -> list[str]:
        """Return Sber feature list based on available climate capabilities.

        Dynamically includes fan, swing, and HVAC mode features
        only when the HA entity supports them.

        Returns:
            List of Sber feature strings supported by this entity.
        """
        features = [*super().create_features_list(), "on_off", "temperature", "hvac_temp_set"]
        if self.swing_modes:
            features.append("hvac_air_flow_direction")
        if self.fan_modes:
            features.append("hvac_air_flow_power")
        if self.hvac_modes:
            features.append("hvac_work_mode")
        return features

    def create_allowed_values_list(self) -> dict[str, dict]:
        """Build allowed values map for enum-based features.

        Returns:
            Dict mapping feature key to its allowed ENUM values descriptor.
        """
        allowed = {}
        if self.fan_modes:
            allowed["hvac_air_flow_power"] = {"type": "ENUM", "enum_values": {"values": self.fan_modes}}
        if self.swing_modes:
            allowed["hvac_air_flow_direction"] = {"type": "ENUM", "enum_values": {"values": self.swing_modes}}
        if self.hvac_modes:
            allowed["hvac_work_mode"] = {"type": "ENUM", "enum_values": {"values": self.hvac_modes}}
        return allowed

    def to_sber_state(self) -> dict:
        """Build full Sber device descriptor including allowed values.

        Overrides base to inject features and allowed_values into the model.

        Returns:
            Sber device descriptor dict with model, features, and allowed_values.
        """
        res = super().to_sber_state()
        res["model"]["features"] = self.create_features_list()
        res["model"]["allowed_values"] = self.create_allowed_values_list()
        return res

    def to_sber_current_state(self) -> dict[str, dict]:
        """Build Sber current state payload with all climate attributes.

        Includes online, on_off, temperature, target temperature, fan mode,
        swing mode, and HVAC work mode when values are available.

        Returns:
            Dict mapping entity_id to its Sber state representation.
        """
        states = [
            {"key": "online", "value": {"type": "BOOL", "bool_value": self._is_online}},
            {"key": "on_off", "value": {"type": "BOOL", "bool_value": self.current_state}},
        ]
        if self.temperature is not None:
            states.append(
                {"key": "temperature", "value": {"type": "INTEGER", "integer_value": int(self.temperature * 10)}}
            )
        if self.target_temperature is not None:
            states.append(
                {
                    "key": "hvac_temp_set",
                    "value": {"type": "INTEGER", "integer_value": int(self.target_temperature * 10)},
                }
            )
        if self.fan_mode:
            states.append({"key": "hvac_air_flow_power", "value": {"type": "ENUM", "enum_value": self.fan_mode}})
        if self.swing_mode:
            states.append({"key": "hvac_air_flow_direction", "value": {"type": "ENUM", "enum_value": self.swing_mode}})
        if self.hvac_mode:
            states.append({"key": "hvac_work_mode", "value": {"type": "ENUM", "enum_value": self.hvac_mode}})
        return {self.entity_id: {"states": states}}

    def process_cmd(self, cmd_data: dict) -> list[dict]:
        """Process Sber climate commands and produce HA service calls.

        Handles the following Sber keys:
        - ``on_off``: turn_on / turn_off
        - ``hvac_temp_set``: set_temperature
        - ``hvac_air_flow_power``: set_fan_mode
        - ``hvac_air_flow_direction``: set_swing_mode
        - ``hvac_work_mode``: set_hvac_mode

        Args:
            cmd_data: Sber command dict with 'states' list.

        Returns:
            List of HA service call dicts to execute.
        """
        results = []
        for item in cmd_data.get("states", []):
            key = item.get("key")
            value = item.get("value", {})

            if key == "on_off":
                on = value.get("bool_value", False)
                self.current_state = on
                results.append(self._build_on_off_service_call(self.entity_id, "climate", on))
            elif key == "hvac_temp_set":
                raw_temp = value.get("integer_value")
                if raw_temp is None:
                    continue
                temp = raw_temp / 10.0
                self.target_temperature = temp
                results.append(
                    {
                        "url": {
                            "type": "call_service",
                            "domain": "climate",
                            "service": "set_temperature",
                            "service_data": {"temperature": temp},
                            "target": {"entity_id": self.entity_id},
                        }
                    }
                )
            elif key == "hvac_air_flow_power":
                mode = value.get("enum_value")
                if mode and (not self.fan_modes or mode in self.fan_modes):
                    self.fan_mode = mode
                    results.append(
                        {
                            "url": {
                                "type": "call_service",
                                "domain": "climate",
                                "service": "set_fan_mode",
                                "service_data": {"fan_mode": mode},
                                "target": {"entity_id": self.entity_id},
                            }
                        }
                    )
            elif key == "hvac_air_flow_direction":
                mode = value.get("enum_value")
                if mode and (not self.swing_modes or mode in self.swing_modes):
                    self.swing_mode = mode
                    results.append(
                        {
                            "url": {
                                "type": "call_service",
                                "domain": "climate",
                                "service": "set_swing_mode",
                                "service_data": {"swing_mode": mode},
                                "target": {"entity_id": self.entity_id},
                            }
                        }
                    )
            elif key == "hvac_work_mode":
                mode = value.get("enum_value")
                if mode and (not self.hvac_modes or mode in self.hvac_modes):
                    self.hvac_mode = mode
                    results.append(
                        {
                            "url": {
                                "type": "call_service",
                                "domain": "climate",
                                "service": "set_hvac_mode",
                                "service_data": {"hvac_mode": mode},
                                "target": {"entity_id": self.entity_id},
                            }
                        }
                    )
        return results

