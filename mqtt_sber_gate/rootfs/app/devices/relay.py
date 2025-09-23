# devices/relay.py
from .base_entity import BaseEntity

class RelayDevice(BaseEntity):
    category = "relay"
    
    def __init__(self, device_id, name=""):
        super().__init__(device_id)
        self.name = name
        self.on_off = False

    def to_ha_state(self):
        """Формирует состояние для Home Assistant"""
        return {
            "id": self.id,
            "on_off": self.on_off,
            "online": self.online
        }

    def to_sber_state(self):
        """Формирует состояние для Sber"""
        return {
            "id": self.id,
            "states": [
                {"key": "online", "value": {"type": "BOOL", "bool_value": self.online}},
                {"key": "on_off", "value": {"type": "BOOL", "bool_value": self.on_off}}
            ]
        }

    def process_cmd(self, source, cmd_data):
        """Обрабатывает команду от Sber или HA"""
        changed = False
        if "on_off" in cmd_data:
            new_on_off = cmd_data["on_off"]
            if self.on_off != new_on_off:
                self.on_off = new_on_off
                changed = True
        return changed
