import logging
from .base_entity import BaseEntity

logger = logging.getLogger(__name__)

RELAY_CATEGORY = "relay"


class RelayEntity(BaseEntity):

    def __init__(self, entity_data: dict):
        super().__init__(RELAY_CATEGORY, entity_data)
        self.current_state = False

    def fill_by_ha_state(self, ha_state):
        super().fill_by_ha_state(ha_state)
        self.current_state = ha_state.get("state") == "on"

    def create_features_list(self):
        return super().create_features_list() + ["on_off"]

    def to_sber_current_state(self):
        is_online = self.state not in ("unavailable", "unknown", None)
        states = [
            {"key": "online", "value": {"type": "BOOL", "bool_value": is_online}},
            {"key": "on_off", "value": {"type": "BOOL", "bool_value": self.current_state}},
        ]
        return {self.entity_id: {"states": states}}

    def process_cmd(self, cmd_data):
        results = []
        for item in cmd_data.get("states", []):
            key = item.get("key")
            value = item.get("value", {})

            if key == "on_off" and value.get("type") == "BOOL":
                on = value.get("bool_value", False)
                self.current_state = on
                domain = self.entity_id.split(".")[0]

                if domain == "button":
                    service = "press"
                else:
                    service = "turn_on" if on else "turn_off"

                results.append({"url": {
                    "type": "call_service",
                    "domain": domain,
                    "service": service,
                    "target": {"entity_id": self.entity_id}
                }})
        return results

    def process_state_change(self, old_state, new_state):
        self.fill_by_ha_state(new_state)
