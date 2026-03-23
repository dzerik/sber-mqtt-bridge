import logging
from .base_entity import BaseEntity

logger = logging.getLogger(__name__)

CLIMATE_CATEGORY = "hvac_ac"


class ClimateEntity(BaseEntity):

    def __init__(self, entity_data: dict):
        super().__init__(CLIMATE_CATEGORY, entity_data)
        self.current_state = False
        self.temperature = None
        self.target_temperature = None
        self.fan_modes = []
        self.swing_modes = []
        self.hvac_modes = []
        self.fan_mode = None
        self.swing_mode = None
        self.hvac_mode = None
        self.min_temp = 16.0
        self.max_temp = 32.0

    def fill_by_ha_state(self, ha_state):
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

    def create_features_list(self):
        features = super().create_features_list() + ["on_off", "temperature", "hvac_temp_set"]
        if self.swing_modes:
            features.append("hvac_air_flow_direction")
        if self.fan_modes:
            features.append("hvac_air_flow_power")
        if self.hvac_modes:
            features.append("hvac_work_mode")
        return features

    def create_allowed_values_list(self):
        allowed = {}
        if self.fan_modes:
            allowed["hvac_air_flow_power"] = {
                "type": "ENUM",
                "enum_values": {"values": self.fan_modes}
            }
        if self.swing_modes:
            allowed["hvac_air_flow_direction"] = {
                "type": "ENUM",
                "enum_values": {"values": self.swing_modes}
            }
        if self.hvac_modes:
            allowed["hvac_work_mode"] = {
                "type": "ENUM",
                "enum_values": {"values": self.hvac_modes}
            }
        return allowed

    def to_sber_state(self):
        res = super().to_sber_state()
        res["model"]["features"] = self.create_features_list()
        res["model"]["allowed_values"] = self.create_allowed_values_list()
        return res

    def to_sber_current_state(self):
        is_online = self.state not in ("unavailable", "unknown", None)
        states = [
            {"key": "online", "value": {"type": "BOOL", "bool_value": is_online}},
            {"key": "on_off", "value": {"type": "BOOL", "bool_value": self.current_state}},
        ]
        if self.temperature is not None:
            states.append({"key": "temperature", "value": {"type": "INTEGER", "integer_value": int(self.temperature * 10)}})
        if self.target_temperature is not None:
            states.append({"key": "hvac_temp_set", "value": {"type": "INTEGER", "integer_value": int(self.target_temperature * 10)}})
        if self.fan_mode:
            states.append({"key": "hvac_air_flow_power", "value": {"type": "ENUM", "enum_value": self.fan_mode}})
        if self.swing_mode:
            states.append({"key": "hvac_air_flow_direction", "value": {"type": "ENUM", "enum_value": self.swing_mode}})
        if self.hvac_mode:
            states.append({"key": "hvac_work_mode", "value": {"type": "ENUM", "enum_value": self.hvac_mode}})
        return {self.entity_id: {"states": states}}

    def process_cmd(self, cmd_data):
        results = []
        for item in cmd_data.get("states", []):
            key = item.get("key")
            value = item.get("value", {})

            if key == "on_off":
                on = value.get("bool_value", False)
                self.current_state = on
                results.append({"url": {
                    "type": "call_service",
                    "domain": "climate",
                    "service": "turn_on" if on else "turn_off",
                    "target": {"entity_id": self.entity_id}
                }})
            elif key == "hvac_temp_set":
                temp = value.get("integer_value", 220) / 10.0
                self.target_temperature = temp
                results.append({"url": {
                    "type": "call_service",
                    "domain": "climate",
                    "service": "set_temperature",
                    "service_data": {"temperature": temp},
                    "target": {"entity_id": self.entity_id}
                }})
            elif key == "hvac_air_flow_power":
                mode = value.get("enum_value")
                self.fan_mode = mode
                results.append({"url": {
                    "type": "call_service",
                    "domain": "climate",
                    "service": "set_fan_mode",
                    "service_data": {"fan_mode": mode},
                    "target": {"entity_id": self.entity_id}
                }})
            elif key == "hvac_air_flow_direction":
                mode = value.get("enum_value")
                self.swing_mode = mode
                results.append({"url": {
                    "type": "call_service",
                    "domain": "climate",
                    "service": "set_swing_mode",
                    "service_data": {"swing_mode": mode},
                    "target": {"entity_id": self.entity_id}
                }})
            elif key == "hvac_work_mode":
                mode = value.get("enum_value")
                self.hvac_mode = mode
                results.append({"url": {
                    "type": "call_service",
                    "domain": "climate",
                    "service": "set_hvac_mode",
                    "service_data": {"hvac_mode": mode},
                    "target": {"entity_id": self.entity_id}
                }})
        return results

    def process_state_change(self, old_state, new_state):
        self.fill_by_ha_state(new_state)
