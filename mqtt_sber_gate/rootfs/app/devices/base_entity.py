# devices/base.py
from abc import abstractmethod
import copy

from devices.device_data import DeviceData

class EntityContext:
    id: str
    parent_id: str
    user_id: str

    def __init__(self, ha_state):
        if ha_state:
            self.id = ha_state.get("context", {}).get("id")
            self.parent_id = ha_state.get("context", {}).get("parent_id")
            self.user_id = ha_state.get("context", {}).get("user_id")

class BaseEntity:
    category: str
    area_id: str
    categories: list[str]
    config_entry_id: str
    config_subentry_id: str
    device_id: str
    disabled_by: str
    entity_category: str
    entity_id: str
    has_entity_name: bool
    hidden_by: str
    icon: str
    id: str
    labels: list[str]
    name: str
    options: dict
    original_name: str
    platform: str
    translation_key: str
    unique_id: str

    #State variables
    state: str
    attributes: dict = {}

    #Filling flags
    is_filled_by_state = False
    linked_device: DeviceData = None

    def __init__(self, category, entity_data: dict):
        self.category = category
        if entity_data:
            self.area_id = entity_data.get("area_id", "")
            self.categories = entity_data.get("categories", [])
            self.config_entry_id = entity_data.get("config_entry_id")
            self.config_subentry_id = entity_data.get("config_subentry_id")
            self.device_id = entity_data.get("device_id")
            self.disabled_by = entity_data.get("disabled_by")
            self.entity_category = entity_data.get("entity_category")
            self.entity_id = entity_data.get("entity_id")
            self.has_entity_name = entity_data.get("has_entity_name")
            self.hidden_by = entity_data.get("hidden_by")
            self.icon = entity_data.get("icon")
            self.id = entity_data.get("id")
            self.labels = entity_data.get("labels", [])
            self.name = entity_data.get("name")
            self.options = entity_data.get("options", {})
            self.original_name = entity_data.get("original_name")
            self.platform = entity_data.get("platform")
            self.translation_key = entity_data.get("translation_key")
            self.unique_id = entity_data.get("unique_id")

            if self.name is None or len(self.name) == 0:
                if self.original_name is not None and len(self.original_name) > 0:
                    self.name = self.original_name
                else:
                    self.name = self.entity_id

            if self.area_id is None:
                self.area_id = ""

    def fill_by_ha_state(self, ha_entity_state):
        self.state = ha_entity_state.get("state")
        self.attributes = copy.deepcopy(ha_entity_state.get("attributes", {}))
        self.is_filled_by_state = True

    def is_group_state(self):
        entity_list = self.attributes.get("entity_id")
        if entity_list == None or len(entity_list) == 0:
            return False
        return True

    def create_features_list(self):
        return ["online"]

    def link_device(self, device_data: DeviceData):
        assert self.device_id == device_data.get("id")
        self.linked_device = device_data

    def to_sber_state(self):
        assert self.is_filled_by_state

        if self.device_id is None: # Possibly it's a group
            return {
            "id": self.entity_id,
            "name": self.name,
            "default_name": self.entity_id,
            "room": self.area_id,
            "model": {
                "id": "Mdl_"+self.category,
                "manufacturer": "Unknown",
                "model": "Unknown",
                "description": self.name,
                "category": self.category,
                # "allowed_values": {},
                "features": self.create_features_list(),
            },
            "hw_version": "Unknown",
            "sw_version": "Unknown",
            "model_id": "",

            }

        assert self.linked_device is not None, True
        return {
            "id": self.entity_id ,
            "name": self.linked_device.get("name", self.original_name),
            "default_name": self.original_name,
            "room": self.linked_device.get("area_id", self.area_id),
            "model": {
                "id": self.linked_device["model_id"],
                "manufacturer": self.linked_device["manufacturer"],
                "model": self.linked_device["model"],
                "description": self.linked_device["name"],
                "category": self.category,
                # "allowed_values": {},
                "features": self.create_features_list(),
            },
            "hw_version": self.linked_device["hw_version"],
            "sw_version": self.linked_device["sw_version"],
            # "model_id": self.linked_device["model_id"],
        }

    def to_sber_current_state(self):
        raise NotImplementedError("Implement in child classes")

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

    def process_state_change(self, old_state, new_state):
        raise NotImplementedError("Method must be redefined in child classes")
    