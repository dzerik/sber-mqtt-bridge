"""Sber Kettle entity -- maps HA water_heater entities to Sber kettle category.

Supports on/off control, water temperature reading, and target temperature setting.
"""

from __future__ import annotations

import logging

from .base_entity import BaseEntity

_LOGGER = logging.getLogger(__name__)

KETTLE_CATEGORY = "kettle"
"""Sber device category for kettle entities."""


class KettleEntity(BaseEntity):
    """Sber kettle entity for smart kettle devices.

    Maps HA water_heater entities to the Sber 'kettle' category with support for:
    - On/off control
    - Current water temperature reading
    - Target temperature setting (60-100, step 10)
    - Child lock (read-only from HA attributes)
    - Water level and low water level indicators
    """

    def __init__(self, entity_data: dict) -> None:
        """Initialize kettle entity.

        Args:
            entity_data: HA entity registry dict containing entity metadata.
        """
        super().__init__(KETTLE_CATEGORY, entity_data)
        self.current_state: bool = False
        self._current_temperature: int | None = None
        self._target_temperature: int | None = None
        self._child_lock: bool = False

    def fill_by_ha_state(self, ha_state: dict) -> None:
        """Parse HA state and update kettle attributes.

        Args:
            ha_state: HA state dict with 'state' and 'attributes' keys.
        """
        super().fill_by_ha_state(ha_state)
        state_str = ha_state.get("state", "")
        self.current_state = state_str not in ("off", "idle", "unavailable", "unknown")
        attrs = ha_state.get("attributes", {})

        raw_temp = attrs.get("current_temperature")
        self._current_temperature = int(raw_temp) if raw_temp is not None else None

        raw_target = attrs.get("temperature")
        self._target_temperature = int(raw_target) if raw_target is not None else None

        self._child_lock = bool(attrs.get("child_lock", False))

    def create_features_list(self) -> list[str]:
        """Return Sber feature list for kettle capabilities.

        Returns:
            List of Sber feature strings supported by this entity.
        """
        features = [*super().create_features_list(), "on_off"]
        features.append("kitchen_water_temperature")
        features.append("kitchen_water_temperature_set")
        features.append("kitchen_water_low_level")
        features.append("child_lock")
        return features

    def create_allowed_values_list(self) -> dict[str, dict]:
        """Build allowed values map for temperature setting.

        Returns:
            Dict mapping feature key to its allowed INTEGER values descriptor.
        """
        return {
            "kitchen_water_temperature_set": {
                "type": "INTEGER",
                "integer_values": {"min": "60", "max": "100", "step": "10"},
            }
        }

    def to_sber_state(self) -> dict:
        """Build full Sber device descriptor including allowed values.

        Returns:
            Sber device descriptor dict with model, features, and allowed_values.
        """
        res = super().to_sber_state()
        res["model"]["allowed_values"] = self.create_allowed_values_list()
        return res

    def to_sber_current_state(self) -> dict[str, dict]:
        """Build Sber current state payload with kettle attributes.

        Returns:
            Dict mapping entity_id to its Sber state representation.
        """
        states = [
            {"key": "online", "value": {"type": "BOOL", "bool_value": self._is_online}},
            {"key": "on_off", "value": {"type": "BOOL", "bool_value": self.current_state}},
        ]
        if self._current_temperature is not None:
            states.append(
                {
                    "key": "kitchen_water_temperature",
                    "value": {"type": "INTEGER", "integer_value": str(self._current_temperature)},
                }
            )
            # Low water level heuristic: temperature below 30 indicates no/little water
            low_level = self._current_temperature < 30
            states.append({"key": "kitchen_water_low_level", "value": {"type": "BOOL", "bool_value": low_level}})
        if self._target_temperature is not None:
            states.append(
                {
                    "key": "kitchen_water_temperature_set",
                    "value": {"type": "INTEGER", "integer_value": str(self._target_temperature)},
                }
            )
        states.append({"key": "child_lock", "value": {"type": "BOOL", "bool_value": self._child_lock}})
        return {self.entity_id: {"states": states}}

    def process_cmd(self, cmd_data: dict) -> list[dict]:
        """Process Sber kettle commands and produce HA service calls.

        Handles the following Sber keys:
        - ``on_off``: turn_on / turn_off (domain auto-detected from entity_id)
        - ``kitchen_water_temperature_set``: water_heater.set_temperature

        Args:
            cmd_data: Sber command dict with 'states' list.

        Returns:
            List of HA service call dicts to execute.
        """
        results: list[dict] = []
        domain = self.get_entity_domain()

        for item in cmd_data.get("states", []):
            key = item.get("key")
            value = item.get("value", {})

            if key == "on_off" and value.get("type") == "BOOL":
                on = value.get("bool_value", False)
                results.append(self._build_on_off_service_call(self.entity_id, domain, on))

            elif key == "kitchen_water_temperature_set" and value.get("type") == "INTEGER":
                raw = value.get("integer_value")
                if raw is None:
                    continue
                results.append(
                    {
                        "url": {
                            "type": "call_service",
                            "domain": domain,
                            "service": "set_temperature",
                            "service_data": {"temperature": self._safe_int(raw) or 0},
                            "target": {"entity_id": self.entity_id},
                        }
                    }
                )
        return results
