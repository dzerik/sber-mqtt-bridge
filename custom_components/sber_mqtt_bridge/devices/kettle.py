"""Sber Kettle entity -- maps HA water_heater entities to Sber kettle category.

Supports on/off control, water temperature reading, and target temperature setting.
"""

from __future__ import annotations

import logging
from typing import ClassVar

from ..sber_constants import SberFeature, SberValueType
from ..sber_models import make_bool_value, make_integer_value, make_state
from .base_entity import AttrSpec, BaseEntity, CommandResult, _safe_int_parser

_LOGGER = logging.getLogger(__name__)

KETTLE_CATEGORY = "kettle"
"""Sber device category for kettle entities."""


def _child_lock_parser(value: object) -> bool:
    """Parse child_lock attribute, defaulting to False."""
    return bool(value) if value is not None else False


class KettleEntity(BaseEntity):
    """Sber kettle entity for smart kettle devices.

    Maps HA water_heater entities to the Sber 'kettle' category with support for:
    - On/off control
    - Current water temperature reading
    - Target temperature setting (60-100, step 10)
    - Child lock (read-only from HA attributes)
    - Water level and low water level indicators
    """

    ATTR_SPECS: ClassVar[tuple[AttrSpec, ...]] = (
        AttrSpec(
            field="_current_temperature",
            attr_keys=("current_temperature",),
            parser=_safe_int_parser,
        ),
        AttrSpec(
            field="_target_temperature",
            attr_keys=("temperature",),
            parser=_safe_int_parser,
        ),
        AttrSpec(
            field="_child_lock",
            attr_keys=("child_lock",),
            parser=_child_lock_parser,
            default=False,
        ),
        AttrSpec(
            field="_water_level",
            attr_keys=("water_level",),
            parser=_safe_int_parser,
        ),
    )

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
        self._water_level: int | None = None

    def fill_by_ha_state(self, ha_state: dict) -> None:
        """Parse HA state and update kettle attributes.

        Args:
            ha_state: HA state dict with 'state' and 'attributes' keys.
        """
        super().fill_by_ha_state(ha_state)
        attrs = ha_state.get("attributes", {})
        self._apply_attr_specs(attrs)
        state_str = ha_state.get("state", "")
        self.current_state = state_str not in ("off", "idle", "unavailable", "unknown")

    def create_features_list(self) -> list[str]:
        """Return Sber feature list for kettle capabilities.

        Returns:
            List of Sber feature strings supported by this entity.
        """
        features = [*super().create_features_list(), "on_off"]
        features.append("kitchen_water_temperature")
        features.append("kitchen_water_temperature_set")
        features.append("kitchen_water_level")
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

    def to_sber_current_state(self) -> dict[str, dict]:
        """Build Sber current state payload with kettle attributes.

        Returns:
            Dict mapping entity_id to its Sber state representation.
        """
        states = [
            make_state(SberFeature.ONLINE, make_bool_value(self._is_online)),
            make_state(SberFeature.ON_OFF, make_bool_value(self.current_state)),
        ]
        if self._current_temperature is not None:
            states.append(
                make_state(SberFeature.KITCHEN_WATER_TEMPERATURE, make_integer_value(self._current_temperature))
            )
            # Low water level heuristic: temperature below 30 indicates no/little water
            low_level = self._current_temperature < 30
            states.append(make_state(SberFeature.KITCHEN_WATER_LOW_LEVEL, make_bool_value(low_level)))
        if self._water_level is not None:
            states.append(make_state(SberFeature.KITCHEN_WATER_LEVEL, make_integer_value(self._water_level)))
        if self._target_temperature is not None:
            states.append(
                make_state(SberFeature.KITCHEN_WATER_TEMPERATURE_SET, make_integer_value(self._target_temperature))
            )
        states.append(make_state(SberFeature.CHILD_LOCK, make_bool_value(self._child_lock)))
        return {self.entity_id: {"states": states}}

    def process_cmd(self, cmd_data: dict) -> list[CommandResult]:
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
            key = item.get("key", "")
            value = item.get("value", {})
            vtype = value.get("type", "")
            if key == SberFeature.ON_OFF and vtype == SberValueType.BOOL:
                on = value.get("bool_value", False)
                results.append(self._build_on_off_service_call(self.entity_id, domain, on))
            elif key == SberFeature.KITCHEN_WATER_TEMPERATURE_SET and vtype == SberValueType.INTEGER:
                temp = self._safe_int(value.get("integer_value"))
                if temp is None:
                    continue
                results.append(
                    self._build_service_call(domain, "set_temperature", self.entity_id, {"temperature": temp})
                )
        return results
