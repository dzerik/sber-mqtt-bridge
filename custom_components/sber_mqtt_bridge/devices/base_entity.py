"""Base entity class for Sber Smart Home device representations.

All device types (light, relay, climate, etc.) inherit from BaseEntity.
It defines the contract for converting between HA states and Sber JSON protocol.
"""

from __future__ import annotations

import copy
from abc import ABC, abstractmethod

# DeviceData type alias — linked_device is stored as a plain dict with keys:
# id, name, area_id, manufacturer, model, model_id, hw_version, sw_version
DeviceData = dict[str, str]


class BaseEntity(ABC):
    """Abstract base class for all Sber device entities.

    Defines the interface that all device types must implement:
    - fill_by_ha_state: Parse HA state into internal representation
    - create_features_list: Return Sber feature names
    - to_sber_state: Build Sber device config JSON
    - to_sber_current_state: Build Sber current state JSON
    - process_cmd: Handle Sber commands, return HA service calls
    - process_state_change: Handle HA state change events
    """

    category: str
    area_id: str
    categories: list[str]
    config_entry_id: str | None
    config_subentry_id: str | None
    device_id: str | None
    disabled_by: str | None
    entity_category: str | None
    entity_id: str
    has_entity_name: bool | None
    hidden_by: str | None
    icon: str | None
    id: str | None
    labels: list[str]
    name: str
    options: dict
    original_name: str | None
    platform: str | None
    translation_key: str | None
    unique_id: str | None

    # State variables
    state: str | None
    is_filled_by_state: bool
    linked_device: DeviceData | None

    def __init__(self, category: str, entity_data: dict) -> None:
        """Initialize base entity from HA entity registry data.

        Args:
            category: Sber device category (e.g., 'light', 'relay', 'sensor_temp').
            entity_data: Dict with HA entity registry fields.
        """
        self.category = category
        self.attributes: dict = {}
        self.state = None
        self.is_filled_by_state = False
        self.linked_device = None
        self.nicknames: list[str] = []
        self.groups: list[str] = []
        self.parent_entity_id: str | None = None
        self.partner_meta: dict[str, str] = {}
        self.extra_features: list[str] = []
        self.removed_features: list[str] = []
        self._previous_sber_state: dict | None = None
        self._linked_entities: dict[str, str] = {}

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

            if not self.name:
                self.name = self.original_name or self.entity_id

            if self.area_id is None:
                self.area_id = ""

    def fill_by_ha_state(self, ha_entity_state: dict) -> None:
        """Parse HA state dict and update internal state.

        Args:
            ha_entity_state: Dict with 'state' and 'attributes' keys from HA.
        """
        self.state = ha_entity_state.get("state")
        self.attributes = copy.deepcopy(ha_entity_state.get("attributes", {}))
        self.is_filled_by_state = True

    def is_group_state(self) -> bool:
        """Check if this entity represents a group of other entities."""
        entity_list = self.attributes.get("entity_id")
        return entity_list is not None and len(entity_list) > 0

    def create_features_list(self) -> list[str]:
        """Return list of Sber feature names supported by this entity.

        Base implementation returns ['online']. Child classes extend this.
        """
        return ["online"]

    def create_allowed_values_list(self) -> dict[str, dict]:
        """Return allowed values map for Sber model descriptor.

        Override in subclasses to provide allowed_values for features
        that require INTEGER ranges or ENUM value lists.

        Returns:
            Dict mapping feature key to its allowed values descriptor,
            or empty dict if no allowed values needed.
        """
        return {}

    def create_dependencies(self) -> dict[str, dict]:
        """Return feature dependencies map for Sber model descriptor.

        Override in subclasses to declare feature dependencies
        (e.g., light_colour depends on light_mode == 'colour').

        Returns:
            Dict mapping feature key to its dependency descriptor,
            or empty dict if no dependencies needed.
        """
        return {}

    def get_final_features_list(self) -> list[str]:
        """Return features list with user overrides applied.

        Removes features from ``removed_features`` and appends features
        from ``extra_features``.  Duplicate-safe.

        Returns:
            Final list of Sber feature names.
        """
        features = self.create_features_list()
        if self.removed_features:
            features = [f for f in features if f not in self.removed_features]
        if self.extra_features:
            existing = set(features)
            features.extend(f for f in self.extra_features if f not in existing)
        return features

    def link_device(self, device_data: DeviceData) -> None:
        """Link this entity to a HA device registry entry.

        Args:
            device_data: Device registry data dict.

        Raises:
            ValueError: If device_id does not match.
        """
        if self.device_id != device_data.get("id"):
            raise ValueError(f"Device ID mismatch: {self.device_id} != {device_data.get('id')}")
        self.linked_device = device_data

    def to_sber_state(self) -> dict:
        """Build Sber device config JSON for MQTT publish.

        Returns:
            Dict with device descriptor for Sber (id, name, room, model, features).
            Optionally includes nicknames, groups, parent_id, and partner_meta
            when configured.

        Raises:
            RuntimeError: If fill_by_ha_state was not called first.
            RuntimeError: If device has device_id but linked_device is not set.
        """
        if not self.is_filled_by_state:
            raise RuntimeError(f"Entity {self.entity_id}: fill_by_ha_state must be called before to_sber_state")

        if self.device_id is None:
            res: dict = {
                "id": self.entity_id,
                "name": self.name,
                "default_name": self.entity_id,
                "room": self.area_id,
                "model": {
                    "id": f"Mdl_{self.category}",
                    "manufacturer": "Unknown",
                    "model": "Unknown",
                    "description": self.name,
                    "category": self.category,
                    "features": self.get_final_features_list(),
                },
                "hw_version": "Unknown",
                "sw_version": "Unknown",
            }
        else:
            if self.linked_device is None:
                raise RuntimeError(f"Entity {self.entity_id}: linked_device required when device_id is set")
            # Use overridden name (e.g. sber_name from YAML) if set, otherwise device name
            device_name = self.linked_device.get("name", self.original_name)
            display_name = self.name if self.name != self.original_name else device_name
            res = {
                "id": self.entity_id,
                "name": display_name,
                "default_name": self.original_name,
                "room": self.linked_device.get("area_id", self.area_id),
                "model": {
                    "id": self.linked_device["model_id"],
                    "manufacturer": self.linked_device["manufacturer"],
                    "model": self.linked_device["model"],
                    "description": display_name,
                    "category": self.category,
                    "features": self.get_final_features_list(),
                },
                "hw_version": self.linked_device["hw_version"],
                "sw_version": self.linked_device["sw_version"],
            }

        # Inject allowed_values and dependencies from subclass hooks
        allowed = self.create_allowed_values_list()
        if allowed:
            res["model"]["allowed_values"] = allowed
        deps = self.create_dependencies()
        if deps:
            res["model"]["dependencies"] = deps

        if self.nicknames:
            res["nicknames"] = self.nicknames
        if self.groups:
            res["groups"] = self.groups
        if self.parent_entity_id:
            res["parent_id"] = self.parent_entity_id
        if self.partner_meta:
            res["partner_meta"] = self.partner_meta

        return res

    @abstractmethod
    def to_sber_current_state(self) -> dict:
        """Build Sber current state JSON for MQTT publish.

        Returns:
            Dict with entity_id key mapping to {'states': [...]}.
        """

    def get_entity_domain(self) -> str:
        """Extract HA domain from entity_id.

        Returns:
            Domain string (e.g., 'climate' from 'climate.living_room').

        Raises:
            ValueError: If entity_id has invalid format.
        """
        entity_id = self.entity_id
        if not isinstance(entity_id, str) or "." not in entity_id:
            raise ValueError(f"entity_id '{entity_id}' has invalid format")
        domain, _ = entity_id.split(".", 1)
        return domain

    @staticmethod
    def _build_on_off_service_call(entity_id: str, domain: str, on: bool) -> dict:
        """Build a HA service call dict for turning a device on or off.

        Args:
            entity_id: HA entity identifier (e.g., 'climate.living_room').
            domain: HA service domain (e.g., 'climate', 'humidifier').
            on: True to turn on, False to turn off.

        Returns:
            Dict with 'url' key containing the HA service call descriptor.
        """
        return {
            "url": {
                "type": "call_service",
                "domain": domain,
                "service": "turn_on" if on else "turn_off",
                "target": {"entity_id": entity_id},
            }
        }

    @abstractmethod
    def process_cmd(self, cmd_data: dict) -> list[dict]:
        """Process a command from Sber cloud.

        Args:
            cmd_data: Command payload with 'states' list.

        Returns:
            List of dicts with 'url' key containing HA service call descriptors,
            or empty list if no action needed.
        """

    @property
    def _is_online(self) -> bool:
        """Check if entity is online (not unavailable/unknown).

        Returns:
            True if the entity state indicates it is reachable.
        """
        return self.state not in ("unavailable", "unknown", None)

    @property
    def is_online(self) -> bool:
        """Public accessor for entity online status.

        Returns:
            True if the entity state indicates it is reachable.
        """
        return self._is_online

    @staticmethod
    def _safe_float(value: object) -> float | None:
        """Safely convert a value to float.

        Args:
            value: Value to convert (can be str, int, float, or None).

        Returns:
            Float value, or None if conversion fails.
        """
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _safe_int(value: object) -> int | None:
        """Safely convert a value to int (via float to handle "22.5" strings).

        Args:
            value: Value to convert (can be str, int, float, or None).

        Returns:
            Integer value, or None if conversion fails.
        """
        if value is None:
            return None
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None

    def process_state_change(self, old_state: dict | None, new_state: dict) -> None:
        """Handle a state change event from Home Assistant.

        Default implementation refreshes internal state via fill_by_ha_state.
        Override in subclasses if additional processing is needed.

        Args:
            old_state: Previous HA state dict (may be None).
            new_state: New HA state dict.
        """
        self.fill_by_ha_state(new_state)

    def has_significant_change(self) -> bool:
        """Check if current Sber state differs from last published state.

        Used to avoid unnecessary MQTT publishes when only non-relevant
        HA attributes changed (e.g., last_updated, icon, etc.).

        Returns:
            True if the state has changed and should be published.
        """
        if self._previous_sber_state is None:
            return True
        try:
            current = self.to_sber_current_state()
        except (RuntimeError, TypeError, ValueError):
            return True
        return current != self._previous_sber_state

    def mark_state_published(self) -> None:
        """Snapshot current Sber state as the last published state.

        Called after successful MQTT publish to enable value diffing.
        """
        try:
            self._previous_sber_state = self.to_sber_current_state()
        except (RuntimeError, TypeError, ValueError):
            self._previous_sber_state = None
