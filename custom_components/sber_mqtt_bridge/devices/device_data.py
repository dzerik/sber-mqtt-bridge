"""Data class representing a Home Assistant device entity record."""

from __future__ import annotations


class DeviceData:
    """Container for Home Assistant entity registry data.

    Wraps the raw entity registry dict into typed attributes for
    convenient access throughout the integration. Used as an
    intermediate representation between HA entity registry and
    Sber device entities.

    Attributes:
        area_id: HA area identifier the entity belongs to.
        categories: List of category strings assigned to the entity.
        config_entry_id: Config entry that owns this entity.
        device_id: HA device identifier.
        entity_category: Entity category (e.g. 'diagnostic', 'config').
        entity_id: Full HA entity ID (e.g. 'light.living_room').
        has_entity_name: Whether the entity uses the device name prefix.
        hw_version: Hardware version string.
        id: Internal registry ID.
        labels: List of user-assigned labels.
        manufacturer: Device manufacturer name.
        model: Device model name.
        name: User-facing entity name (from name_by_user).
        options: Entity options dict.
        original_name: Original entity name from the integration.
        platform: Integration platform name.
        sw_version: Software/firmware version string.
        translation_key: Translation key for localized names.
        unuque_id: Unique identifier for the entity (note: typo preserved).
    """

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

    def __init__(self, device_data: dict) -> None:
        """Initialize DeviceData from a raw entity registry dict.

        Args:
            device_data: Dict from HA entity registry containing keys such as
                area_id, device_id, entity_id, name, manufacturer, model, etc.
        """
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
