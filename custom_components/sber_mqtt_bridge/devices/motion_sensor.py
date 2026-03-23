import logging
from .base_entity import BaseEntity

logger = logging.getLogger(__name__)

MOTION_SENSOR_CATEGORY = "sensor_pir"


class MotionSensorEntity(BaseEntity):

    def __init__(self, entity_data: dict):
        super().__init__(MOTION_SENSOR_CATEGORY, entity_data)
        self.motion_detected = False

    def fill_by_ha_state(self, ha_state):
        super().fill_by_ha_state(ha_state)
        self.motion_detected = ha_state.get("state") == "on"

    def create_features_list(self):
        return super().create_features_list() + ["pir"]

    def to_sber_current_state(self):
        is_online = self.state not in ("unavailable", "unknown", None)
        states = [
            {"key": "online", "value": {"type": "BOOL", "bool_value": is_online}},
            {"key": "pir", "value": {"type": "BOOL", "bool_value": self.motion_detected}}
        ]
        return {self.entity_id: {"states": states}}

    def process_cmd(self, cmd_data):
        return []

    def process_state_change(self, old_state, new_state):
        self.fill_by_ha_state(new_state)
