import logging
from .base_entity import BaseEntity

logger = logging.getLogger(__name__)

DOOR_SENSOR_CATEGORY = "sensor_door"


class DoorSensorEntity(BaseEntity):

    def __init__(self, entity_data: dict):
        super().__init__(DOOR_SENSOR_CATEGORY, entity_data)
        self.is_open = False

    def fill_by_ha_state(self, ha_state):
        super().fill_by_ha_state(ha_state)
        self.is_open = ha_state.get("state") == "on"

    def create_features_list(self):
        return super().create_features_list() + ["doorcontact_state"]

    def to_sber_current_state(self):
        is_online = self.state not in ("unavailable", "unknown", None)
        states = [
            {"key": "online", "value": {"type": "BOOL", "bool_value": is_online}},
            {"key": "doorcontact_state", "value": {"type": "ENUM", "enum_value": "open" if self.is_open else "close"}},
        ]
        return {self.entity_id: {"states": states}}

    def process_cmd(self, cmd_data):
        return []

    def process_state_change(self, old_state, new_state):
        self.fill_by_ha_state(new_state)
