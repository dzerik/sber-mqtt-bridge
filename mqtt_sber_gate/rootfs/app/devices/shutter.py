# devices/shutter.py
from .base_entity import BaseEntity

class ShutterDevice(BaseEntity):
    category = "shutter"
    
    def __init__(self, device_id, name=""):
        super().__init__(device_id)
        self.name = name
        self.position = 50  # Позиция (0-100%)
        self.moving = False  # В движении?

    def to_ha_state(self):
        """Формирует состояние для Home Assistant"""
        return {
            "id": self.id,
            "position": self.position,
            "moving": self.moving,
            "online": self.online
        }

    def to_sber_state(self):
        """Формирует состояние для Sber"""
        return {
            "id": self.id,
            "states": [
                {"key": "online", "value": {"type": "BOOL", "bool_value": self.online}},
                {"key": "position", "value": {"type": "INTEGER", "integer_value": self.position}},
                {"key": "moving", "value": {"type": "BOOL", "bool_value": self.moving}}
            ]
        }

    def process_cmd(self, source, cmd_data):
        """Обрабатывает команду от Sber или HA"""
        changed = False
        if "position" in cmd_data:
            new_position = cmd_data["position"]
            if self.position != new_position:
                self.position = new_position
                self.moving = True
                changed = True
        if "moving" in cmd_data:
            new_moving = cmd_data["moving"]
            if self.moving != new_moving:
                self.moving = new_moving
                changed = True
        return changed
