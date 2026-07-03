"""Sber Kettle entity -- maps HA water_heater entities to Sber kettle category.

Supports on/off control, water temperature reading, and target temperature setting.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable
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
        AttrSpec(
            field="_water_temp",
            attr_keys=("current_temperature", "temperature"),
            parser=float,
            default=None,
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
        self._water_temp: float | None = None

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

    def _create_features_list(self) -> list[str]:
        """Return Sber feature list for kettle capabilities.

        Returns:
            List of Sber feature strings supported by this entity.
        """
        features = [*super()._create_features_list(), "on_off"]
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
        if self._water_temp is not None and math.isfinite(self._water_temp):
            states.append(
                make_state(
                    SberFeature.KITCHEN_WATER_TEMPERATURE,
                    make_integer_value(round(self._water_temp * 10)),
                )
            )
            # Low water level heuristic: temperature below 30 indicates no/little water
            low_level = self._water_temp < 3.0  # 3°C threshold (30/10)
            states.append(make_state(SberFeature.KITCHEN_WATER_LOW_LEVEL, make_bool_value(low_level)))
        if self._water_level is not None:
            states.append(make_state(SberFeature.KITCHEN_WATER_LEVEL, make_integer_value(self._water_level)))
        if self._target_temperature is not None:
            states.append(
                make_state(SberFeature.KITCHEN_WATER_TEMPERATURE_SET, make_integer_value(self._target_temperature))
            )
        states.append(make_state(SberFeature.CHILD_LOCK, make_bool_value(self._child_lock)))
        return {self.entity_id: {"states": states}}

    @property
    def _cmd_handlers(self) -> dict[str, Callable[[dict], list[CommandResult]]]:
        """Return dispatch map for kettle commands."""
        return {
            SberFeature.ON_OFF: self._cmd_on_off,
            SberFeature.KITCHEN_WATER_TEMPERATURE_SET: self._cmd_water_temp_set,
        }

    def _cmd_on_off(self, value: dict) -> list[CommandResult]:
        """Handle ``on_off``: turn_on / turn_off (domain auto-detected from entity_id).

        Args:
            value: Sber value dict from the command payload.

        Returns:
            List of HA service call dicts to execute.
        """
        if value.get("type") != SberValueType.BOOL:
            return []
        on = value.get("bool_value", False)
        domain = self.get_entity_domain()
        return [self._build_on_off_service_call(self.entity_id, domain, on)]

    def _cmd_water_temp_set(self, value: dict) -> list[CommandResult]:
        """Handle ``kitchen_water_temperature_set``: water_heater.set_temperature.

        Args:
            value: Sber value dict from the command payload.

        Returns:
            List of HA service call dicts to execute.
        """
        if value.get("type") != SberValueType.INTEGER:
            return []
        temp = _safe_int_parser(value.get("integer_value"))
        if temp is None:
            return []
        domain = self.get_entity_domain()
        return [self._build_service_call(domain, "set_temperature", self.entity_id, {"temperature": temp})]
