import logging

from .base_entity import BaseEntity

logger = logging.getLogger(__name__)

HUMIDITY_SENSOR_CATEGORY = "sensor_temp"


class HumiditySensorEntity(BaseEntity):

    def __init__(self, entity_data: dict):
        super().__init__(HUMIDITY_SENSOR_CATEGORY, entity_data)
        self.humidity = 0.0

    def fill_by_ha_state(self, ha_state):
        super().fill_by_ha_state(ha_state)
        try:
            self.humidity = float(ha_state.get("state", 0))
        except (ValueError, TypeError):
            self.humidity = 0.0

    def create_features_list(self):
        return super().create_features_list() + ["humidity"]

    def to_sber_current_state(self):
        is_online = self.state not in ("unavailable", "unknown", None)
        states = [
            {"key": "online", "value": {"type": "BOOL", "bool_value": is_online}},
            {"key": "humidity", "value": {"type": "INTEGER", "integer_value": int(self.humidity * 10)}}
        ]
        return {self.entity_id: {"states": states}}

    def process_cmd(self, cmd_data):
        return []

    def process_state_change(self, old_state, new_state):
        self.fill_by_ha_state(new_state)
