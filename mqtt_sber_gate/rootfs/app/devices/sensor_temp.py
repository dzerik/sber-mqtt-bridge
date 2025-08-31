# devices/sensor_temp.py
from .base_entity import BaseEntity

class SensorTempDevice(BaseEntity):
    category = "sensor_temp"
    
    def __init__(self, device_id, name=""):
        super().__init__(device_id)
        self.name = name
        self.temperature = 0.0

    def to_ha_state(self):
        """Формирует состояние для Home Assistant"""
        return {
            "id": self.id,
            "temperature": self.temperature,
            "online": self.online
        }

    def to_sber_state(self):
        """Формирует состояние для Sber"""
        return {
            "id": self.id,
            "states": [
                {"key": "online", "value": {"type": "BOOL", "bool_value": self.online}},
                {"key": "temperature", "value": {"type": "INTEGER", "integer_value": int(self.temperature * 10)}}
            ]
        }

    def process_cmd(self, source, cmd_data):
        """Обрабатывает команду от Sber или HA"""
        # Датчики температуры обычно не принимают команды
        return False
