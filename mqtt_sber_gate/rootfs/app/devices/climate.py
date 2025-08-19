# devices/climate.py
from .base import BaseDevice


class ClimateDevice(BaseDevice):
    category = "hvac_ac"
    _temperature: float = 20.0
    _hvac_temp_set: float = 26.0
    _on_off: bool = False
    _fan_modes = []
    _swing_modes = []
    
    def __init__(self, ha_state):
        super().__init__(ha_state)
        self._temperature = ha_state["attributes"].get("current_temperature", self.temperature)
        self._hvac_temp_set = ha_state["attributes"].get("temperature", self.hvac_temp_set)
        self._on_off = ha_state.get("state", "off") != "off"
        self._fan_modes = ha_state["attributes"].get("fan_modes", [])
        self._swing_modes = ha_state["attributes"].get("swing_modes", [])

    # --- Аксессоры ---
    @property
    def temperature(self) -> float:
        """Текущая температура"""
        return self._temperature

    @temperature.setter
    def temperature(self, value: float):
        if not isinstance(value, (int, float)):
            raise TypeError("Температура должна быть числом")
        if value < -273.15:
            raise ValueError("Температура не может быть ниже абсолютного нуля (-273.15°C)")
        self._temperature = value

    @property
    def hvac_temp_set(self) -> float:
        """Установленная температура климатической системы"""
        return self._hvac_temp_set

    @hvac_temp_set.setter
    def hvac_temp_set(self, value: float):
        if not isinstance(value, (int, float)):
            raise TypeError("Установленная температура должна быть числом")
        if value < -273.15:
            raise ValueError("Температура не может быть ниже абсолютного нуля (-273.15°C)")
        self._hvac_temp_set = value

    @property
    def on_off(self) -> bool:
        """Состояние включения/выключения"""
        return self._on_off

    @on_off.setter
    def on_off(self, value: bool):
        if not isinstance(value, bool):
            raise TypeError("on_off должен быть boolean")
        self._on_off = value

    @property
    def fan_modes(self) -> list:
        """Режимы вентиляции"""
        return self._fan_modes

    @fan_modes.setter
    def fan_modes(self, value: list):
        if not isinstance(value, list):
            raise TypeError("fan_modes должен быть списком")
        self._fan_modes = value

    @property
    def swing_modes(self) -> list:
        """Режимы подъема/спуска"""
        return self._swing_modes

    @swing_modes.setter
    def swing_modes(self, value: list):
        if not isinstance(value, list):
            raise TypeError("swing_modes должен быть списком")
        self._swing_modes = value

    # --- Метод from_ha_state ---
    # @classmethod
    # def from_ha_state(cls, ha_state):
    #     """
    #     Создаёт устройство на основе состояния из Home Assistant
        
    #     Args:
    #         ha_state (dict): Словарь с данными из Home Assistant
            
    #     Returns:
    #         ClimateDevice: Экземпляр климатического устройства
    #     """
    #     entity_id = ha_state.get("entity_id", "unknown")
        
    #     # Извлечение атрибутов
    #     attributes = ha_state.get("attributes", {})
    #     friendly_name = attributes.get("friendly_name", "Unknown")
    #     available = attributes.get("available", False)
    #     current_temperature = attributes.get("current_temperature", 20.0)
    #     temperature = attributes.get("temperature", 20.0)
    #     state = attributes.get("state", "off")
        
    #     # Определение состояния включения/выключения
    #     is_on = state.lower() not in ["off", "idle"]
        
    #     return cls(
    #         device_id=entity_id,
    #         name=friendly_name
    #     )

    # --- Методы ---
    def to_ha_state(self):
        """Формирует состояние для Home Assistant"""
        return {
            "id": self.id,
            "name": self.description,
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
