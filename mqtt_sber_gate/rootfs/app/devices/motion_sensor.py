# devices/motion_sensor.py
from .base_entity import BaseEntity

class MotionSensorDevice(BaseEntity):
    category = "motion"
    
    def __init__(self, device_id, name=""):
        super().__init__(device_id)
        self.name = name
        self.presence = False  # Наличие движения
        self.last_seen = 0     # Последнее время обнаружения

    def to_ha_state(self):
        """Формирует состояние для Home Assistant"""
        return {
            "id": self.id,
            "presence": self.presence,
            "last_seen": self.last_seen,
            "online": self.online
        }

    def to_sber_state(self):
        """Формирует состояние для Sber"""
        return {
            "id": self.id,
            "states": [
                {"key": "online", "value": {"type": "BOOL", "bool_value": self.online}},
                {"key": "presence", "value": {"type": "BOOL", "bool_value": self.presence}},
                {"key": "last_seen", "value": {"type": "INTEGER", "integer_value": int(self.last_seen)}}
            ]
        }

    def process_cmd(self, source, cmd_data):
        """Обрабатывает команду от Sber или HA"""
        # Датчики движения не принимают команды
        return False
