class DeviceData:
    area_id: str
    categories: list[str]
    config_entry_id: str
    device_id: str
    entity_category: str
    entity_id: str
    has_entity_name: bool
    hw_version: str
    id: str
    labels: list[str]
    manufacturer: str
    model: str
    name: str
    options: dict
    original_name: str
    platform: str
    sw_version: str
    translation_key: str
    unuque_id: str

    def __init__(self, device_data):
        self.area_id = device_data.get("area_id")
        self.categories = device_data.get("categories", [])
        self.config_entry_id = device_data.get("config_entry_id")
        self.device_id = device_data.get("device_id")
        self.entity_category = device_data.get("entity_category")
        self.entity_id = device_data.get("entity_id")
        self.has_entity_name = device_data.get("has_entity_name")
        self.hw_version = device_data.get("hw_version", "Unknown")
        self.id = device_data.get("id")
        self.labels = device_data.get("labels", [])
        self.manufacturer = device_data.get("manufacturer", "Unknown")
        self.model_id = device_data.get("model_id", "")
        self.model = device_data.get("model", "Unknown")
        self.name = device_data.get("name_by_user")
        self.options = device_data.get("options", {})
        self.original_name = device_data.get("name")
        self.platform = device_data.get("platform")
        self.translation_key = device_data.get("translation_key")
        self.sw_version = device_data.get("sw_version", "Unknown")
        self.unuque_id = device_data.get("unique_id")