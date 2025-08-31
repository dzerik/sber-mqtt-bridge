# devices/pressure_sensor.py
from .base_entity import BaseEntity

class PressureSensorDevice(BaseEntity):
    category = "pressure"
    
    def __init__(self, device_id, name=""):
        super().__init__(device_id)
        self.name = name
        self.pressure = 1013.25  # Давление (hPa)

    def to_ha_state(self):
        """Формирует состояние для Home Assistant"""
        return {
            "id": self.id,
            "pressure": self.pressure,
            "online": self.online
        }

    def to_sber_state(self):
        """Формирует состояние для Sber"""
        return {
            "id": self.id,
            "states": [
                {"key": "online", "value": {"type": "BOOL", "bool_value": self.online}},
                {"key": "pressure", "value": {"type": "INTEGER", "integer_value": int(self.pressure * 10)}}
            ]
        }

    def process_cmd(self, source, cmd_data):
        """Обрабатывает команду от Sber или HA"""
        # Датчики давления не принимают команды
        return False
