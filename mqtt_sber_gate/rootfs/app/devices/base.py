# devices/base.py
from abc import abstractmethod


class BaseDevice:
    _id: str
    _description: str
    _online: bool
    _on_off: bool
    _context: dict

    def __init__(self, ha_state):
        self._id=ha_state.get("entity_id")
        self._description=ha_state["attributes"].get("friendly_name", "Unknown")
        self._online=ha_state["attributes"].get("available", False)

        # self._id = device_id
        self._on_off = ha_state.get("state", "off") != "off"  # Стандартное состояние
        self._manufacturer = "Unknown"
        self._model = "Unknown"
        self._hw_version = "Unknown"
        self._sw_version = "Unknown"
        self._features = []  # Список доступных функций
        self._dependencies = {}
        self._allowed_values = {}
        self._context = {
            "id": ha_state["context"]["id"],
            "parent_id": ha_state["context"]["parent_id"],
            "user_id": ha_state["context"]["user_id"]
        }
        self._last_changed = ha_state["last_changed"]
        self._last_reported = ha_state["last_reported"]
        self._last_updated = ha_state["last_updated"]

    def to_ha_state(self):
        """
        Возвращает состояние устройства в формате Home Assistant
        """
        return {
            "entity_id": self.id,
            "attributes": {
                "friendly_name": self.description,
                "available": self.online,
            },
            "context": {
                "id": self._context["id"],
                "parent_id": self._context["parent_id"],
                "user_id": self._context["user_id"]
            },
            "state": "on" if self.online else "off",
            "last_changed": self._last_changed,
            "last_reported": self._last_reported,
            "last_updated": self._last_updated
        }

    def _create_features_list(self):
        features = []
        features += ["online"]
        features += ["on_off"]
        return features

    def to_sber_state(self):
        
        return {
            "id": self.id,
            "manufacturer": self.manufacturer,
            "model": self.model,
            "hw_version": self.hw_version,
            "sw_version": self.sw_version,
            "description": self.description,
            "category": self.category,

            "features": self._create_features_list(),
            "allowed_values": []
        }

    @property
    def id(self) -> str:
        """Идентификатор устройства"""
        return self._id

    @property
    def online(self) -> bool:
        """Статус онлайн/оффлайн устройства"""
        return self._online

    @online.setter
    def online(self, value: bool):
        if not isinstance(value, bool):
            raise TypeError("Online должен быть boolean")
        self._online = value

    @property
    def on_off(self) -> bool:
        """Статус включения/выключения устройства"""
        return self._on_off

    @on_off.setter
    def on_off(self, value: bool):
        if not isinstance(value, bool):
            raise TypeError("On/Off должен быть boolean")
        self._on_off = value

    @property
    def manufacturer(self) -> str:
        """Производитель устройства"""
        return self._manufacturer

    @manufacturer.setter
    def manufacturer(self, value: str):
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Manufacturer должен быть непустой строкой")
        self._manufacturer = value

    @property
    def model(self) -> str:
        """Модель устройства"""
        return self._model

    @model.setter
    def model(self, value: str):
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Model должен быть непустой строкой")
        self._model = value

    @property
    def hw_version(self) -> str:
        """Версия аппаратной части"""
        return self._hw_version

    @hw_version.setter
    def hw_version(self, value: str):
        if not isinstance(value, str) or not value.strip():
            raise ValueError("HW Version должен быть непустой строкой")
        self._hw_version = value

    @property
    def sw_version(self) -> str:
        """Версия программного обеспечения"""
        return self._sw_version

    @sw_version.setter
    def sw_version(self, value: str):
        if not isinstance(value, str) or not value.strip():
            raise ValueError("SW Version должен быть непустой строкой")
        self._sw_version = value

    @property
    def description(self) -> str:
        """Описание устройства"""
        return self._description

    @description.setter
    def description(self, value: str):
        if not isinstance(value, str):
            raise TypeError("Description должен быть строкой")
        self._description = value

    @property
    def features(self) -> list[str]:
        """Список доступных функций"""
        return self._features

    @features.setter
    def features(self, value: list[str]):
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ValueError("Features должен быть списком строк")
        self._features = value

    @property
    def dependencies(self) -> dict:
        """Зависимости устройства"""
        return self._dependencies

    @dependencies.setter
    def dependencies(self, value: dict):
        if not isinstance(value, dict):
            raise TypeError("Dependencies должен быть словарём")
        self._dependencies = value

    @property
    def allowed_values(self) -> dict:
        """Допустимые значения параметров"""
        return self._allowed_values

    @allowed_values.setter
    def allowed_values(self, value: dict):
        if not isinstance(value, dict):
            raise TypeError("Allowed values должен быть словарём")
        self._allowed_values = value

    @classmethod
    def get_device_category(cls):
        """
        Возвращает категорию устройства
        """
        raise NotImplementedError("Метод get_device_category должен быть переопределен")


    def get_entity_domain(self) -> str:
        """
        Извлекает домен из entity_id (например, 'climate' из 'climate.living_room')
        """
        if not isinstance(self.id, str) or '.' not in self.id:
            raise ValueError(f"entity_id '{self.id}' имеет недопустимый формат")

        domain, _ = self.id.split('.', 1)
        return domain

    @abstractmethod
    def process_cmd(self, source, cmd_data):
        """
        Обрабатывает команду от Sber или HA
        Возвращает True, если состояние было изменено
        """
        raise NotImplementedError("Метод process_cmd должен быть переопределен")
