# devices/base.py
from abc import abstractmethod


class BaseDevice:
    _id: str
    _description: str
    _online: bool

    def __init__(self, ha_state):
        self._id=ha_state.get("entity_id")
        self._description=ha_state["attributes"].get("friendly_name", "Unknown")
        self._online=ha_state["attributes"].get("available", False)

        # self._id = device_id
        self._online = ha_state.get("state", "off") != "off"  # Стандартное состояние
        self._manufacturer = "Unknown manufacturer"
        self._model = "unknown model"
        self._hw_version = "unknown hw version"
        self._sw_version = "unknown sw version"
        # self._description = """
        # Описание устройства
        # """
        self._features = []  # Список доступных функций
        self._dependencies = {}
        self._allowed_values = {}

    @property
    def id(self) -> str:
        """Идентификатор устройства"""
        return self._id

    # @id.setter
    # def id(self, value: str):
    #     if not isinstance(value, str) or not value.strip():
    #         raise ValueError("ID должно быть непустой строкой")
    #     self._id = value

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
    def to_sber_state(self):
        """Создаёт устройство из состояния Home Assistant"""
        return {
            "id": self.id,
            "manufacturer": self.manufacturer,
            "model": self.model,
            "hw_version": self.hw_version,
            "sw_version": self.sw_version,
            "description": self.description,
            "features": self.features,
            "dependencies": self.dependencies,
            "allowed_values": self.allowed_values,
            "category": self.get_device_category(),
            "type": "device"
        }

    @classmethod
    def get_device_category(cls):
        """
        Возвращает категорию устройства
        """
        raise NotImplementedError("Метод get_device_category должен быть переопределен")

    @abstractmethod
    def process_cmd(self, source, cmd_data):
        """
        Обрабатывает команду от Sber или HA
        Возвращает True, если состояние было изменено
        """
        raise NotImplementedError("Метод process_cmd должен быть переопределен")
