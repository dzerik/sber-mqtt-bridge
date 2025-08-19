# devices/light.py
from .base import BaseDevice

class LightDevice(BaseDevice):
    category = "light"
    
    def __init__(self, device_id, name=""):
        super().__init__(device_id)
        self.name = name
        self.on_off = False
        self.brightness = 50  # Яркость (0-100)
        self.color = "#FFFFFF"  # Цвет в HEX

    def to_ha_state(self):
        """Формирует состояние для Home Assistant"""
        return {
            "id": self.id,
            "on_off": self.on_off,
            "brightness": self.brightness,
            "color": self.color,
            "online": self.online
        }

    def to_sber_state(self):
        """Формирует состояние для Sber"""
        return {
            "id": self.id,
            "states": [
                {"key": "online", "value": {"type": "BOOL", "bool_value": self.online}},
                {"key": "on_off", "value": {"type": "BOOL", "bool_value": self.on_off}},
                {"key": "brightness", "value": {"type": "INTEGER", "integer_value": self.brightness}},
                {"key": "color", "value": {"type": "STRING", "string_value": self.color}}
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
        if "brightness" in cmd_data:
            new_brightness = cmd_data["brightness"]
            if self.brightness != new_brightness:
                self.brightness = new_brightness
                changed = True
        if "color" in cmd_data:
            new_color = cmd_data["color"]
            if self.color != new_color:
                self.color = new_color
                changed = True
        return changed
