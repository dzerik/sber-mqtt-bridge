# devices/climate.py
from .base import Device

class ClimateDevice(Device):
    category = "hvac_ac"
    
    def __init__(self, device_id, name=""):
        super().__init__(device_id)
        self.name = name
        self.temperature = 20.0
        self.hvac_temp_set = 20.0
        self.on_off = True

    def to_ha_state(self):
        """Формирует состояние для Home Assistant"""
        return {
            "id": self.id,
            "temperature": self.temperature,
            "hvac_temp_set": self.hvac_temp_set,
            "on_off": self.on_off,
            "online": self.online
        }

    def to_sber_state(self):
        """Формирует состояние для Sber"""
        return {
            "id": self.id,
            "states": [
                {"key": "online", "value": {"type": "BOOL", "bool_value": self.online}},
                {"key": "on_off", "value": {"type": "BOOL", "bool_value": self.on_off}},
                {"key": "temperature", "value": {"type": "INTEGER", "integer_value": int(self.temperature * 10)}},
                {"key": "hvac_temp_set", "value": {"type": "INTEGER", "integer_value": int(self.hvac_temp_set * 10)}}
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
        if "hvac_temp_set" in cmd_data:
            new_temp = cmd_data["hvac_temp_set"]
            if self.hvac_temp_set != new_temp:
                self.hvac_temp_set = new_temp
                changed = True
        return changed
