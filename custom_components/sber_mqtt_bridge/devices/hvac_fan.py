"""Sber HVAC Fan entity -- maps HA fan entities to Sber hvac_fan category.

Supports on/off control and fan speed via the ``hvac_air_flow_power`` feature.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import ClassVar

from ..sber_constants import SberFeature, SberValueType
from ..sber_models import make_bool_value, make_enum_value, make_state
from .base_entity import AttrSpec, BaseEntity, CommandResult, _safe_int_parser
from .fan_speed_mixin import (
    _SBER_SPEED_TO_PERCENTAGE,
    SBER_SPEED_VALUES,
    FanSpeedMixin,
    _percentage_to_sber_speed,
)

_LOGGER = logging.getLogger(__name__)

HVAC_FAN_CATEGORY = "hvac_fan"
"""Sber device category for fan entities."""

_FAN_FEATURE_SET_SPEED = 1
"""HA fan platform ``FanEntityFeature.SET_SPEED`` bit.

Mirrors ``homeassistant.components.fan.FanEntityFeature.SET_SPEED``
(verified against HA 2026.4) without importing the fan component into
this dependency-free device module.
"""

__all__ = [
    "HVAC_FAN_CATEGORY",
    "SBER_SPEED_VALUES",
    "_SBER_SPEED_TO_PERCENTAGE",
    "HvacFanEntity",
    "_percentage_to_sber_speed",
]


class HvacFanEntity(FanSpeedMixin, BaseEntity):
    """Sber fan entity for ventilator control.

    Maps HA fan entities to the Sber 'hvac_fan' category with support for:
    - On/off control
    - Fan speed via preset_mode or percentage-based speed mapping
    """

    ATTR_SPECS: ClassVar[tuple[AttrSpec, ...]] = (
        AttrSpec(
            field="preset_modes",
            converter=lambda attrs: (attrs.get("preset_modes") or []) if "preset_modes" in attrs else None,
            default=[],
            preserve_on_missing=True,
        ),
        AttrSpec(
            field="preset_mode",
            attr_keys=("preset_mode",),
        ),
        AttrSpec(
            field="percentage",
            attr_keys=("percentage",),
        ),
        AttrSpec(
            field="supported_features",
            attr_keys=("supported_features",),
            parser=_safe_int_parser,
            default=0,
            preserve_on_missing=True,
        ),
        AttrSpec(
            field="_has_percentage_attr",
            converter=lambda attrs: True if "percentage" in attrs or "percentage_step" in attrs else None,
            default=False,
            preserve_on_missing=True,
        ),
    )

    def __init__(self, entity_data: dict) -> None:
        """Initialize fan entity.

        Args:
            entity_data: HA entity registry dict containing entity metadata.
        """
        super().__init__(HVAC_FAN_CATEGORY, entity_data)
        self.current_state: bool = False
        self.preset_mode: str | None = None
        self.preset_modes: list[str] = []
        self.percentage: int | None = None
        self.supported_features: int = 0
        self._has_percentage_attr: bool = False

    def fill_by_ha_state(self, ha_state: dict) -> None:
        """Parse HA state and update fan attributes.

        Args:
            ha_state: HA state dict with 'state' and 'attributes' keys.
        """
        super().fill_by_ha_state(ha_state)
        attrs = ha_state.get("attributes", {})
        self._apply_attr_specs(attrs)
        self.current_state = ha_state.get("state") != "off"

    @property
    def _supports_speed(self) -> bool:
        """Check if this fan has speed control as a *capability*.

        Deliberately based on capabilities, not on the current value of
        ``percentage``: a fan that is turned off reports ``percentage: None``
        while still supporting speed control, and gating on the value made
        the ``hvac_air_flow_power`` feature disappear from the published
        device config on every off state. Capability sources (checked in
        order of reliability):

        * ``supported_features`` bitmask contains ``SET_SPEED`` (primary,
          matches HA fan platform semantics);
        * non-empty ``preset_modes`` list (preset-only fans);
        * sticky presence of a ``percentage``/``percentage_step`` attribute
          key -- HA only exposes these keys when SET_SPEED is supported,
          covering entities that omit ``supported_features``.

        The latter two are latched / preserved across state updates so the
        feature list stays stable when the entity goes unavailable.
        """
        return bool(self.supported_features & _FAN_FEATURE_SET_SPEED or self.preset_modes or self._has_percentage_attr)

    def _create_features_list(self) -> list[str]:
        """Return Sber feature list for fan capabilities.

        Only includes hvac_air_flow_power when the HA entity supports speed
        control. Simple on/off fans (e.g. relay overridden as fan) get only
        on_off.

        Returns:
            List of Sber feature strings supported by this entity.
        """
        features = [*super()._create_features_list(), "on_off"]
        if self._supports_speed:
            features.append("hvac_air_flow_power")
        return features

    def create_allowed_values_list(self) -> dict[str, dict]:
        """Build allowed values map for fan speed feature.

        Returns empty dict when the fan has no speed support.

        Returns:
            Dict mapping feature key to its allowed ENUM values descriptor.
        """
        if not self._supports_speed:
            return {}
        return {
            "hvac_air_flow_power": {
                "type": "ENUM",
                "enum_values": {"values": SBER_SPEED_VALUES},
            }
        }

    def to_sber_current_state(self) -> dict[str, dict]:
        """Build Sber current state payload with fan attributes.

        The speed state is reported only when the current speed is actually
        known (``preset_mode`` or ``percentage`` available). A speed-capable
        fan that is off with ``percentage: None`` keeps the feature in its
        config but simply omits the speed state instead of fabricating one.
        Legacy exception: preset-capable fans (non-empty ``preset_modes``)
        with an unknown mode keep the historical ``auto`` fallback.

        Returns:
            Dict mapping entity_id to its Sber state representation.
        """
        states = [
            make_state(SberFeature.ONLINE, make_bool_value(self._is_online)),
            make_state(SberFeature.ON_OFF, make_bool_value(self.current_state)),
        ]
        speed = self._get_sber_speed() if self._supports_speed else None
        if speed is None and self.preset_modes:
            speed = "auto"
        if speed:
            states.append(make_state(SberFeature.HVAC_AIR_FLOW_POWER, make_enum_value(speed)))
        return {self.entity_id: {"states": states}}

    @property
    def _cmd_handlers(self) -> dict[str, Callable[[dict], list[CommandResult]]]:
        """Return dispatch map for fan commands."""
        return {
            SberFeature.ON_OFF: self._cmd_on_off,
            SberFeature.HVAC_AIR_FLOW_POWER: self._cmd_air_flow_power,
        }

    def _cmd_on_off(self, value: dict) -> list[CommandResult]:
        """Handle ``on_off``: fan.turn_on / fan.turn_off.

        Args:
            value: Sber value dict from the command payload.

        Returns:
            List of HA service call dicts to execute.
        """
        if value.get("type") != SberValueType.BOOL:
            return []
        on = value.get("bool_value", False)
        return [self._build_on_off_service_call(self.entity_id, "fan", on)]

    def _cmd_air_flow_power(self, value: dict) -> list[CommandResult]:
        """Handle ``hvac_air_flow_power``: fan speed via preset_mode or percentage.

        Args:
            value: Sber value dict from the command payload.

        Returns:
            List of HA service call dicts to execute.
        """
        if value.get("type") != SberValueType.ENUM:
            return []
        return self._cmd_fan_speed(value.get("enum_value"))
