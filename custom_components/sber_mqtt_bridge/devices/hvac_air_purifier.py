"""Sber HVAC Air Purifier entity -- maps HA fan entities to Sber hvac_air_purifier category.

Supports on/off control, fan speed via ``hvac_air_flow_power``, and
read-only features: ionization, night mode, aromatization, filter/ionizer replacement.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import ClassVar

from ..sber_constants import SberFeature
from ..sber_models import make_bool_value, make_enum_value, make_state
from .base_entity import AttrSpec, BaseEntity, CommandResult, _safe_bool_parser, _safe_int_parser
from .fan_speed_mixin import SBER_SPEED_VALUES, FanSpeedMixin
from .hvac_fan import _FAN_FEATURE_SET_SPEED

_LOGGER = logging.getLogger(__name__)

HVAC_AIR_PURIFIER_CATEGORY = "hvac_air_purifier"
"""Sber device category for air purifier entities."""


class HvacAirPurifierEntity(FanSpeedMixin, BaseEntity):
    """Sber air purifier entity for purifier fan devices.

    Maps HA fan entities (with device_class purifier/air_purifier) to the
    Sber 'hvac_air_purifier' category with support for:
    - On/off control
    - Fan speed via preset_mode or percentage
    - Read-only flags: ionization, night mode, aromatization,
      filter replacement, ionizer replacement, decontamination
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
        AttrSpec(
            field="_ionization",
            attr_keys=("ionization",),
            parser=_safe_bool_parser,
            default=False,
        ),
        AttrSpec(
            field="_night_mode",
            attr_keys=("night_mode",),
            parser=_safe_bool_parser,
            default=False,
        ),
        AttrSpec(
            field="_aromatization",
            attr_keys=("aromatization",),
            parser=_safe_bool_parser,
            default=False,
        ),
        AttrSpec(
            field="_replace_filter",
            attr_keys=("replace_filter",),
            parser=_safe_bool_parser,
            default=False,
        ),
        AttrSpec(
            field="_replace_ionizator",
            attr_keys=("replace_ionizator",),
            parser=_safe_bool_parser,
            default=False,
        ),
        AttrSpec(
            field="_decontaminate",
            attr_keys=("decontaminate",),
            parser=_safe_bool_parser,
            default=False,
        ),
    )

    def __init__(self, entity_data: dict) -> None:
        """Initialize air purifier entity.

        Args:
            entity_data: HA entity registry dict containing entity metadata.
        """
        super().__init__(HVAC_AIR_PURIFIER_CATEGORY, entity_data)
        self.current_state: bool = False
        self.preset_mode: str | None = None
        self.preset_modes: list[str] = []
        self.percentage: int | None = None
        self.supported_features: int = 0
        self._has_percentage_attr: bool = False
        self._ionization: bool = False
        self._night_mode: bool = False
        self._aromatization: bool = False
        self._replace_filter: bool = False
        self._replace_ionizator: bool = False
        self._decontaminate: bool = False

    def fill_by_ha_state(self, ha_state: dict) -> None:
        """Parse HA state and update air purifier attributes.

        Args:
            ha_state: HA state dict with 'state' and 'attributes' keys.
        """
        super().fill_by_ha_state(ha_state)
        attrs = ha_state.get("attributes", {})
        self._apply_attr_specs(attrs)
        self.current_state = ha_state.get("state") != "off"

    @property
    def _supports_speed(self) -> bool:
        """Check if this purifier has speed control as a *capability*.

        Same rule as :attr:`HvacFanEntity._supports_speed` — both
        categories drive the same HA ``fan`` platform — and deliberately
        based on capabilities, not on the current ``percentage`` value: a
        purifier that is off reports ``percentage: None`` while still
        supporting speed control.  Capability sources, in order of
        reliability: the ``SET_SPEED`` bit of ``supported_features``, a
        non-empty ``preset_modes`` list, and the sticky presence of a
        ``percentage`` / ``percentage_step`` attribute key.  The latter
        two are preserved across updates so the feature list — and with
        it ``model.id`` — stays stable when the entity goes unavailable.
        """
        return bool(self.supported_features & _FAN_FEATURE_SET_SPEED or self.preset_modes or self._has_percentage_attr)

    def _create_features_list(self) -> list[str]:
        """Return Sber feature list for air purifier capabilities.

        ``hvac_air_flow_power`` is advertised only when the HA entity can
        actually change speed.  A purifier without ``SET_SPEED`` (a relay
        overridden into this category, a plain on/off unit) never has a
        speed to report, so declaring the function left a fan-speed
        control in the Sber app that no state ever filled.

        Returns:
            List of Sber feature strings supported by this entity.
        """
        features = [
            *super()._create_features_list(),
            "on_off",
            "hvac_ionization",
            "hvac_night_mode",
            "hvac_aromatization",
            "hvac_replace_filter",
            "hvac_replace_ionizator",
        ]
        if self._supports_speed:
            features.append("hvac_air_flow_power")
        if self._decontaminate:
            features.append("hvac_decontaminate")
        return features

    def create_allowed_values_list(self) -> dict[str, dict]:
        """Build allowed values map for air flow power feature.

        Returns empty dict when the purifier has no speed support — an
        ``allowed_values`` entry without its feature is dropped by
        :meth:`BaseEntity._build_model_descriptor` anyway.

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

    def _build_current_state(self) -> dict[str, dict]:
        """Build Sber current state payload with air purifier attributes.

        Returns:
            Dict mapping entity_id to its Sber state representation.
        """
        states = [
            make_state(SberFeature.ONLINE, make_bool_value(self._is_online)),
            make_state(SberFeature.ON_OFF, make_bool_value(self.current_state)),
        ]
        speed = self._get_sber_speed() if self._supports_speed else None
        if speed:
            states.append(make_state(SberFeature.HVAC_AIR_FLOW_POWER, make_enum_value(speed)))
        states.extend(
            [
                make_state(SberFeature.HVAC_IONIZATION, make_bool_value(self._ionization)),
                make_state(SberFeature.HVAC_NIGHT_MODE, make_bool_value(self._night_mode)),
                make_state(SberFeature.HVAC_AROMATIZATION, make_bool_value(self._aromatization)),
                make_state(SberFeature.HVAC_REPLACE_FILTER, make_bool_value(self._replace_filter)),
                make_state(SberFeature.HVAC_REPLACE_IONIZATOR, make_bool_value(self._replace_ionizator)),
            ]
        )
        if self._decontaminate:
            states.append(make_state(SberFeature.HVAC_DECONTAMINATE, make_bool_value(self._decontaminate)))
        return {self.entity_id: {"states": states}}

    @property
    def _cmd_handlers(self) -> dict[str, Callable[[dict], list[CommandResult]]]:
        """Return dispatch map for air purifier commands.

        Both handlers come from :class:`FanSpeedMixin` — they were
        byte-identical copies of ``HvacFanEntity``'s versions before
        (both categories drive the same HA ``fan`` platform).
        """
        return {
            SberFeature.ON_OFF: self._cmd_on_off,
            SberFeature.HVAC_AIR_FLOW_POWER: self._cmd_air_flow_power,
        }
