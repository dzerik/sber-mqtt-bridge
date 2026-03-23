import logging
from .base_entity import BaseEntity

logger = logging.getLogger(__name__)

SCENARIO_BUTTON_CATEGORY = "scenario_button"


class ScenarioButtonEntity(BaseEntity):

    def __init__(self, entity_data: dict):
        super().__init__(SCENARIO_BUTTON_CATEGORY, entity_data)
        self.button_event = "click"

    def fill_by_ha_state(self, ha_state):
        super().fill_by_ha_state(ha_state)
        if ha_state.get("state") == "on":
            self.button_event = "click"
        else:
            self.button_event = "double_click"

    def create_features_list(self):
        return super().create_features_list() + ["button_event"]

    def to_sber_current_state(self):
        is_online = self.state not in ("unavailable", "unknown", None)
        states = [
            {"key": "online", "value": {"type": "BOOL", "bool_value": is_online}},
            {"key": "button_event", "value": {"type": "ENUM", "enum_value": self.button_event}},
        ]
        return {self.entity_id: {"states": states}}

    def process_cmd(self, cmd_data):
        return []

    def process_state_change(self, old_state, new_state):
        self.fill_by_ha_state(new_state)
