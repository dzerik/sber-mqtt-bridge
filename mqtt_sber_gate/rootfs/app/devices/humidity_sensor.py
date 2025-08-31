# devices/humidity_sensor.py
from .base_entity import BaseEntity

class HumiditySensorDevice(BaseEntity):
    category = "humidity"
    
    def __init__(self, device_id, name=""):
        super().__init__(device_id)
        self.name = name
        self.humidity = 50.0  # Влажность (%)

    def to_ha_state(self):
        """Формирует состояние для Home Assistant"""
        return {
            "id": self.id,
            "humidity": self.humidity,
            "online": self.online
        }

    def to_sber_state(self):
        """Формирует состояние для Sber"""
        return {
            "id": self.id,
            "states": [
                {"key": "online", "value": {"type": "BOOL", "bool_value": self.online}},
                {"key": "humidity", "value": {"type": "INTEGER", "integer_value": int(self.humidity * 10)}}
            ]
        }

    def process_cmd(self, source, cmd_data):
        """Обрабатывает команду от Sber или HA"""
        # Датчики влажности не принимают команды
        return False
