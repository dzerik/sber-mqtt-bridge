#
# https://developers.sber.ru/docs/ru/smarthome/c2c/model
# Поле	            Тип	            Обязательное?	   Описание
# id	            string	            ✔︎	            Идентификатор модели (часто product_id)
# manufacturer	    string	            ✔︎	            Производитель
# model	            string	            ✔︎	            Название модели
# hw_version	    string		                       Версия оборудования
# sw_version	    string		                       Версия прошивки
# description	    string		                       Описание
# category	        string	            ✔︎	            Категория устройства (см. Устройства)
# features	        list<string>	    ✔︎	            Список функций (см. Функции устройств)
# dependencies	    map<string, object>		           Зависимости функций (см. Зависимость функции (dependencies))
# allowed_values	map<string, object>		           Допустимые значения функций (см. Допустимые

from devices.base_entity import BaseEntity


class DeviceModel:
    id: str
    manufacturer: str
    model_name: str
    hw_version: str
    sw_version: str
    description: str
    category: str
    features: list[str]
    dependencies: dict[str, object]

    def __init__(self, ha_entity: BaseEntity):
        assert ha_entity.linked_device is not None
        ha_device = ha_entity.linked_device
        assert ha_device is not None
        self.id = ha_device.model
        self.manufacturer = ha_device.manufacturer
        self.model_name = ha_device.model
        self.hw_version = ha_device.hw_version
        self.sw_version = ha_device.sw_version
        self.description = ha_device.original_name
        self.category = ha_entity.get_device_category()
        self.features = ha_entity.create_features_list()

    def to_sber_model(self) -> dict[str, object]:
        return {
                    "model": {
                        "id": self.id,
                        "manufacturer": self.linked_device.manufacturer,
                        "model": self.linked_device.model,
                        "hw_version": self.linked_device.hw_version,
                        "sw_version": self.linked_device.sw_version,
                        "description": self.linked_device.name,
                        "category": self.category,
                        "features": self.features,
                        "allowed_values": {}
                    }           
                }
