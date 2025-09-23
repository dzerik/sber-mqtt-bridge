# devices/scenario_button.py
from .base_entity import BaseEntity

class ScenarioButtonDevice(BaseEntity):
    category = "button"
    
    def __init__(self, device_id, name=""):
        super().__init__(device_id)
        self.name = name
        self.last_press = 0  # Последнее время нажатия
        self.press_count = 0  # Счетчик нажатий

    def to_ha_state(self):
        """Формирует состояние для Home Assistant"""
        return {
            "id": self.id,
            "last_press": self.last_press,
            "press_count": self.press_count,
            "online": self.online
        }

    def to_sber_state(self):
        """Формирует состояние для Sber"""
        return {
            "id": self.id,
            "states": [
                {"key": "online", "value": {"type": "BOOL", "bool_value": self.online}},
                {"key": "last_press", "value": {"type": "INTEGER", "integer_value": int(self.last_press)}},
                {"key": "press_count", "value": {"type": "INTEGER", "integer_value": self.press_count}}
            ]
        }

    def process_cmd(self, source, cmd_data):
        """Обрабатывает команду от Sber или HA"""
        # Кнопки обычно не принимают команды
        return False
