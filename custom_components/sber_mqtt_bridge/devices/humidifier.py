import logging
from .base_entity import BaseEntity

logger = logging.getLogger(__name__)

HUMIDIFIER_CATEGORY = "hvac_humidifier"


class HumidifierEntity(BaseEntity):

    def __init__(self, entity_data: dict):
        super().__init__(HUMIDIFIER_CATEGORY, entity_data)
        self.current_state = False
        self.target_humidity = None
        self.current_humidity = None
        self.available_modes = []
        self.mode = None

    def fill_by_ha_state(self, ha_state):
        super().fill_by_ha_state(ha_state)
        self.current_state = ha_state.get("state") == "on"
        attrs = ha_state.get("attributes", {})
        self.target_humidity = attrs.get("humidity")
        self.current_humidity = attrs.get("current_humidity")
        self.available_modes = attrs.get("available_modes", [])
        self.mode = attrs.get("mode")

    def create_features_list(self):
        features = super().create_features_list() + ["on_off", "humidity"]
        if self.available_modes:
            features.append("hvac_work_mode")
        return features

    def create_allowed_values_list(self):
        allowed = {}
        if self.available_modes:
            allowed["hvac_work_mode"] = {
                "type": "ENUM",
                "enum_values": {"values": self.available_modes}
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
        if self.target_humidity is not None:
            states.append({"key": "humidity", "value": {"type": "INTEGER", "integer_value": int(self.target_humidity * 10)}})
        if self.mode:
            states.append({"key": "hvac_work_mode", "value": {"type": "ENUM", "enum_value": self.mode}})
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
                    "domain": "humidifier",
                    "service": "turn_on" if on else "turn_off",
                    "target": {"entity_id": self.entity_id}
                }})
            elif key == "humidity":
                humidity = value.get("integer_value", 500) / 10.0
                self.target_humidity = humidity
                results.append({"url": {
                    "type": "call_service",
                    "domain": "humidifier",
                    "service": "set_humidity",
                    "service_data": {"humidity": int(humidity)},
                    "target": {"entity_id": self.entity_id}
                }})
            elif key == "hvac_work_mode":
                mode = value.get("enum_value")
                self.mode = mode
                results.append({"url": {
                    "type": "call_service",
                    "domain": "humidifier",
                    "service": "set_mode",
                    "service_data": {"mode": mode},
                    "target": {"entity_id": self.entity_id}
                }})
        return results

    def process_state_change(self, old_state, new_state):
        self.fill_by_ha_state(new_state)
