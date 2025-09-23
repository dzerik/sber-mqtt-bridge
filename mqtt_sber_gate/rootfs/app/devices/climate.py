# devices/climate.py
from .base_entity import BaseEntity


class ClimateDevice(BaseEntity):
    category = "hvac_ac"
    _temperature: float = None
    _hvac_temp_set: float = None
    _fan_modes = []
    _swing_modes = []
    _hvac_actions = []
    _fan_mode: str
    _swing_mode: str
    _hvac_action: str
    _icon: str
    _max_temp: float
    _min_temp: float
    _supported_features: int
    _target_temp_step: float

    def __init__(self, ha_state):
        super().__init__(ha_state)
        self._temperature = ha_state["attributes"].get("current_temperature", self._temperature)
        self._hvac_temp_set = ha_state["attributes"].get("temperature", self._hvac_temp_set)
        self._fan_modes = ha_state["attributes"].get("fan_modes", [])
        self._swing_modes = ha_state["attributes"].get("swing_modes", [])
        self._fan_mode = ha_state["attributes"].get("fan_mode", self._fan_modes[0] if self._fan_modes else None)
        self._swing_mode = ha_state["attributes"].get("swing_mode", self._swing_modes[0] if self._swing_modes else None)
        self._hvac_actions = ha_state["attributes"].get("hvac_modes", [])
        self._hvac_action = ha_state["attributes"].get("hvac_action", self._hvac_actions[0] if self._hvac_actions else None)
        self._icon = ha_state["attributes"].get("icon", "mdi:air-conditioner")
        self._max_temp = ha_state["attributes"].get("max_temp", None)
        self._min_temp = ha_state["attributes"].get("min_temp", None)
        self._supported_features = ha_state["attributes"].get("supported_features", None)
        self._target_temp_step = ha_state["attributes"].get("target_temp_step", None)

    def to_ha_state(self):
        """Формирует состояние для Home Assistant"""
        res = super().to_ha_state()
        
        return res | {
            # "state": "on" if self.on_off else "off",
            "attributes": {
                "current_temperature": self.temperature,
                "temperature": self.hvac_temp_set,
                "friendly_name": self.description,
                "fan_modes": self.fan_modes,
                "swing_modes": self.swing_modes,
                "fan_mode": self.fan_mode,
                "swing_mode": self.swing_mode,
                "hvac_modes": self.hvac_actions,
                "hvac_action": self.hvac_action,
                "icon": self.icon,
                "max_temp": self.max_temp,
                "min_temp": self.min_temp,
                "supported_features": self._supported_features,
                "target_temp_step": self._target_temp_step
            }
        }

    def _create_features_list(self):
        """Формирует список возможных функций"""
        
        features = super()._create_features_list()
        features += ["temperature"]
        features += ["hvac_temp_set"]
        features += ["hvac_air_flow_direction"] if len(self._swing_modes) > 0 else []
        features += ["hvac_air_flow_power"] if len(self._fan_modes) > 0 else []
        features += ["hvac_work_mode"] if len(self._hvac_actions) > 0 else []
        return features

    def _create_allowed_values_list(self):
        """Формирует список допустимых значений"""
        allowed_values = {}
        if len(self._fan_modes) > 0:
            allowed_values |= {
                "hvac_air_flow_power": {
                    "type": "ENUM",
                    "enum_values": {
                        "values": self._fan_modes
                    }
                }
            }
        if len(self._swing_modes) > 0:
            allowed_values |= {
                "hvac_air_flow_direction": {
                    "type": "ENUM",
                    "enum_values": {
                        "values": self._swing_modes
                    }
                }
            }
        if len(self._hvac_actions) > 0:
            allowed_values |= {
                "hvac_work_mode": {
                    "type": "ENUM",
                    "enum_values": {
                        "values": self._hvac_actions
                    }
                }
            }
        return allowed_values

    def to_sber_state(self):
        """Формирует состояние для Сбер"""
        res = super().to_sber_state()
        
        return res | {
            "features": self._create_features_list(),
            "allowed_values": self._create_allowed_values_list()
        }

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

    @property
    def fan_mode(self) -> str:
        """Текущий режим вентиляции"""
        return self._fan_mode

    @fan_mode.setter
    def fan_mode(self, value: str):
        if value not in self.fan_modes:
            raise ValueError("Недопустимый режим вентиляции")
        self._fan_mode = value

    @property
    def swing_mode(self) -> str:
        """Текущий режим подъема/спуска"""
        return self._swing_mode

    @swing_mode.setter
    def swing_mode(self, value: str):
        if value not in self.swing_modes:
            raise ValueError("Недопустимый режим подъема/спуска")
        self._swing_mode = value

    @property
    def hvac_actions(self) -> list:
        """Доступные действия климатической системы"""
        return self._hvac_actions

    @hvac_actions.setter
    def hvac_actions(self, value: list):
        if not isinstance(value, list):
            raise TypeError("hvac_actions должен быть списком")
        self._hvac_actions = value

    @property
    def hvac_action(self) -> str:
        """Текущее действие климатической системы"""
        return self._hvac_action

    @hvac_action.setter
    def hvac_action(self, value: str):
        if value not in self.hvac_actions:
            raise ValueError("Недопустимое действие климатической системы")
        self._hvac_action = value

    @property
    def icon(self) -> str:
        """Иконка устройства"""
        return self._icon

    @icon.setter
    def icon(self, value: str):
        self._icon = value

    @property
    def max_temp(self) -> float:
        """Максимальная допустимая температура"""
        return self._max_temp
    
    @max_temp.setter
    def max_temp(self, value: float):
        self._max_temp = value

    @property
    def min_temp(self) -> float:
        """Минимальная допустимая температура"""
        return self._min_temp
    
    @min_temp.setter
    def min_temp(self, value: float):
        self._min_temp = value

    # --- Методы ---
    def process_cmd(self, source, cmd_data):
        """Обрабатывает команду от Sber или HA"""
        if cmd_data is None:
            return None
        
        if "on_off" in cmd_data:
            return {
                "url": "/api/services/"+self.get_entity_domain()+("/turn_on" if cmd_data["on_off"] else "/turn_off"),
                "data": { "entity_id": self.id }
            }
        if "hvac_temp_set" in cmd_data:
            return {
                "url": "/api/services/"+self.get_entity_domain()+"/set_temperature",
                "data": {
                    "temperature": cmd_data["hvac_temp_set"],
                    "entity_id": self.id,
                    "hvac_mode": "cool" if self.on_off else "heat" # TODO: Проверить, что работает
                }
            }
        return None