"""Sber Climate (AC) entity -- maps HA climate entities to Sber hvac_ac category."""

from __future__ import annotations

import logging
import math
from collections.abc import Callable
from typing import ClassVar

from ..sber_constants import SberFeature, SberValueType
from ..sber_models import make_bool_value, make_enum_value, make_integer_value, make_state
from .base_entity import (
    ROLE_TEMPERATURE,
    AttrSpec,
    BaseEntity,
    _safe_clamped_int_parser,
    _safe_float_parser,
    _safe_int_parser,
)

_LOGGER = logging.getLogger(__name__)

CLIMATE_CATEGORY = "hvac_ac"
"""Sber device category for air conditioner / HVAC entities."""

# HA hvac_mode → Sber hvac_work_mode mapping
HA_TO_SBER_WORK_MODE: dict[str, str] = {
    "cool": "cooling",
    "heat": "heating",
    "dry": "dehumidification",
    "fan_only": "ventilation",
    "heat_cool": "auto",
    "auto": "auto",
    "eco": "eco",
}
"""Map HA HVAC modes to Sber work mode enum values.

'off' is excluded — use on_off.
Sber also supports 'turbo' and 'quiet' work modes; these are mapped
from HA preset_modes (boost→turbo, sleep→quiet) in to_sber_current_state.
"""

SBER_TO_HA_WORK_MODE: dict[str, str] = {
    "cooling": "cool",
    "heating": "heat",
    "dehumidification": "dry",
    "ventilation": "fan_only",
    "auto": "auto",
    "eco": "eco",
}
"""Reverse mapping: Sber work mode → HA hvac_mode.

Note: kept as a separate literal (not auto-generated) because
``HA_TO_SBER_WORK_MODE`` has ``heat_cool`` and ``auto`` both mapping to
``auto`` — a naive reverse would lose ``heat_cool``.  The reverse here
prefers the canonical HA mode for each Sber value.
"""

# HA swing_mode → Sber hvac_air_flow_direction mapping
# TODO: Sber docs list "up/down/left/right" as default values, but real AC
# devices use "no/vertical/horizontal/rotation/swing/auto". Verify with
# actual Sber cloud responses via DevTools raw JSON inspection.
HA_TO_SBER_SWING: dict[str, str] = {
    "off": "no",
    "vertical": "vertical",
    "horizontal": "horizontal",
    "both": "rotation",
    "swing": "swing",
    "auto": "auto",
}
"""Map HA swing modes to Sber air flow direction values."""

SBER_TO_HA_SWING: dict[str, str] = {v: k for k, v in HA_TO_SBER_SWING.items()}
"""Reverse mapping: Sber swing → HA swing_mode."""

# HA hvac_mode → Sber hvac_thermostat_mode mapping (for boiler, underfloor, heater)
HA_TO_SBER_THERMOSTAT_MODE: dict[str, str] = {
    "heat": "heating",
    "auto": "auto",
    "heat_cool": "auto",
}
"""Map HA HVAC modes to Sber thermostat mode enum values (simpler devices)."""

SBER_TO_HA_THERMOSTAT_MODE: dict[str, str] = {
    "heating": "heat",
    "auto": "auto",
}
"""Reverse mapping: Sber thermostat mode → HA hvac_mode.

Kept as explicit literal for the same reason as ``SBER_TO_HA_WORK_MODE``:
``heat_cool`` and ``auto`` both forward-map to ``auto``.
"""

# HA fan_mode → Sber hvac_air_flow_power mapping
# Sber standard values: auto, low, medium, high, turbo, quiet
HA_TO_SBER_FAN_MODE: dict[str, str] = {
    "auto": "auto",
    "low": "low",
    "medium": "medium",
    "mid": "medium",
    "high": "high",
    "turbo": "turbo",
    "quiet": "quiet",
    "silent": "quiet",
    "sleep": "quiet",
    "strong": "turbo",
    "boost": "turbo",
    "max": "turbo",
    "min": "low",
    "1": "quiet",
    "2": "low",
    "3": "medium",
    "4": "high",
    "5": "turbo",
}
"""Map HA fan modes to Sber air flow power enum values."""


def _finite_float_parser(value: object) -> float | None:
    """Parse a value to float, returning None for non-finite results (NaN, Inf)."""
    parsed = _safe_float_parser(value)
    if parsed is not None and math.isfinite(parsed):
        return parsed
    return None


def _safe_bool_or_none(value: object) -> bool | None:
    """Parse to bool preserving None (for child_lock detection)."""
    if value is None:
        return None
    return bool(value)


class ClimateEntity(BaseEntity):
    """Sber climate entity for air conditioner control.

    Maps HA climate entities to the Sber 'hvac_ac' category with support for:
    - On/off control
    - Temperature reading and target temperature setting
    - Fan mode, swing mode, and HVAC work mode selection
    - Allowed values for dynamic enum features

    Subclasses override class-level flags to restrict features per Sber spec:
    - ``_supports_fan``: include hvac_air_flow_power (default True for AC)
    - ``_supports_swing``: include hvac_air_flow_direction (default True for AC)
    - ``_supports_work_mode``: include hvac_work_mode (default True for AC)
    - ``_supports_thermostat_mode``: include hvac_thermostat_mode (default False)
    """

    LINKABLE_ROLES = (ROLE_TEMPERATURE,)

    ATTR_SPECS: ClassVar[tuple[AttrSpec, ...]] = (
        AttrSpec(
            field="temperature",
            attr_keys=("current_temperature",),
            parser=_finite_float_parser,
        ),
        AttrSpec(
            field="target_temperature",
            attr_keys=("temperature",),
            parser=_finite_float_parser,
        ),
        AttrSpec(
            field="_target_temp_high",
            attr_keys=("target_temp_high",),
            parser=_finite_float_parser,
        ),
        AttrSpec(
            field="_target_temp_low",
            attr_keys=("target_temp_low",),
            parser=_finite_float_parser,
        ),
        AttrSpec(
            field="fan_modes",
            converter=lambda attrs: attrs.get("fan_modes") or [],
            default=[],
        ),
        AttrSpec(
            field="swing_modes",
            converter=lambda attrs: attrs.get("swing_modes") or [],
            default=[],
        ),
        AttrSpec(
            field="swing_horizontal_modes",
            converter=lambda attrs: attrs.get("swing_horizontal_modes") or [],
            default=[],
        ),
        AttrSpec(
            field="hvac_modes",
            converter=lambda attrs: attrs.get("hvac_modes") or [],
            default=[],
        ),
        AttrSpec(
            field="fan_mode",
            attr_keys=("fan_mode",),
        ),
        AttrSpec(
            field="swing_mode",
            attr_keys=("swing_mode",),
        ),
        AttrSpec(
            field="swing_horizontal_mode",
            attr_keys=("swing_horizontal_mode",),
        ),
        AttrSpec(
            field="min_temp",
            attr_keys=("min_temp",),
            parser=_safe_float_parser,
            default=16.0,
        ),
        AttrSpec(
            field="max_temp",
            attr_keys=("max_temp",),
            parser=_safe_float_parser,
            default=32.0,
        ),
        AttrSpec(
            field="_target_humidity",
            # HA climate publishes target humidity as "humidity" (ATTR_HUMIDITY);
            # "target_humidity" is kept as a legacy fallback key.
            attr_keys=("humidity", "target_humidity"),
            parser=_safe_int_parser,
        ),
        AttrSpec(
            field="_preset_mode",
            attr_keys=("preset_mode",),
        ),
        AttrSpec(
            field="_preset_modes",
            converter=lambda attrs: attrs.get("preset_modes") or [],
            default=[],
        ),
        AttrSpec(
            field="_child_lock",
            attr_keys=("child_lock",),
            parser=_safe_bool_or_none,
        ),
    )

    _supports_fan: bool = True
    _supports_swing: bool = True
    _supports_work_mode: bool = True
    _supports_thermostat_mode: bool = False

    def __init__(
        self,
        entity_data: dict,
        category: str = CLIMATE_CATEGORY,
        min_temp: float = 16.0,
        max_temp: float = 32.0,
        temp_step: int = 1,
    ) -> None:
        """Initialize climate entity.

        Args:
            entity_data: HA entity registry dict containing entity metadata.
            category: Sber device category (override in subclasses).
            min_temp: Minimum temperature default.
            max_temp: Maximum temperature default.
            temp_step: Temperature step for allowed_values (Sber spec varies by category).
        """
        super().__init__(category, entity_data)
        self.temp_step = temp_step
        self.current_state = False
        self.temperature = None
        self.target_temperature = None
        self.fan_modes = []
        self.swing_modes = []
        self.swing_horizontal_modes = []
        self.hvac_modes = []
        self.fan_mode = None
        self.swing_mode = None
        self.swing_horizontal_mode = None
        self.hvac_mode = None
        self.min_temp = min_temp
        self.max_temp = max_temp
        self._target_temp_high: float | None = None
        self._target_temp_low: float | None = None
        self._target_is_range: bool = False
        self._target_humidity: int | None = None
        self._preset_mode: str | None = None
        self._preset_modes: list[str] = []
        self._child_lock: bool | None = None

    def fill_by_ha_state(self, ha_state: dict) -> None:
        """Parse HA state and update all climate attributes.

        Simple attribute extraction is handled declaratively via
        :attr:`ATTR_SPECS`.  State-derived values (``current_state``,
        ``hvac_mode``) remain here since they come from the top-level
        ``state`` field, not from ``attributes``.

        Args:
            ha_state: HA state dict with 'state' and 'attributes' keys.
                Attributes may include current_temperature, temperature,
                target_temp_high/target_temp_low (heat_cool range),
                fan_modes, swing_modes, swing_horizontal_modes,
                hvac_modes, humidity, preset_mode, preset_modes, etc.
        """
        super().fill_by_ha_state(ha_state)
        attrs = ha_state.get("attributes", {})
        self._apply_attr_specs(attrs)

        # heat_cool thermostats publish temperature=None plus a
        # target_temp_high/target_temp_low range.  Sber has no range
        # feature, so expose the range midpoint as hvac_temp_set.
        self._target_is_range = False
        if self.target_temperature is None and self._target_temp_high is not None and self._target_temp_low is not None:
            self.target_temperature = (self._target_temp_high + self._target_temp_low) / 2
            self._target_is_range = True

        # Derive on/off state and hvac_mode from top-level state string
        self.current_state = ha_state.get("state", "off") != "off"
        self.hvac_mode = ha_state.get("state")

    def _create_features_list(self) -> list[str]:
        """Return Sber feature list based on available climate capabilities.

        Dynamically includes fan, swing, HVAC mode, humidity, and night mode
        features only when the HA entity supports them.

        Returns:
            List of Sber feature strings supported by this entity.
        """
        features = [*super()._create_features_list(), "on_off", "temperature", "hvac_temp_set"]
        if self._supports_swing and (self._mapped_swing_values() or self._uses_horizontal_swing):
            features.append("hvac_air_flow_direction")
        if self._supports_fan and self._mapped_fan_values():
            features.append("hvac_air_flow_power")
        if self._supports_work_mode and self._mapped_work_modes():
            features.append("hvac_work_mode")
        if self._supports_thermostat_mode and self._mapped_thermostat_modes():
            features.append("hvac_thermostat_mode")
        if self._target_humidity is not None:
            features.append("hvac_humidity_set")
        if self._has_night_mode and self.category in self._NIGHT_MODE_CATEGORIES:
            features.append("hvac_night_mode")
        return features

    _NIGHT_MODE_CATEGORIES = frozenset({"hvac_ac"})
    """Sber climate categories whose spec includes ``hvac_night_mode``."""

    def _has_instance_allowed_values(self) -> bool:
        """Climate limits vary per device (min/max temp, mode lists).

        ``hvac_temp_set`` min/max/step and the fan/swing/mode enum values
        come from HA attributes — devices sharing a model_id with
        different allowed_values get silently rejected by Sber cloud
        (issue #44 audit).
        """
        return True

    def _mapped_fan_values(self) -> list[str]:
        """Return Sber enum values for fan modes with a known mapping.

        Unmapped HA fan modes are dropped — device-specific HA strings
        must not leak into Sber enum_values (issue #44 audit).
        """
        return list(dict.fromkeys(HA_TO_SBER_FAN_MODE[m] for m in self.fan_modes or [] if m in HA_TO_SBER_FAN_MODE))

    def _mapped_swing_values(self) -> list[str]:
        """Return Sber enum values for vertical swing modes with a known mapping."""
        return list(dict.fromkeys(HA_TO_SBER_SWING[m] for m in self.swing_modes or [] if m in HA_TO_SBER_SWING))

    def _mapped_work_modes(self) -> list[str]:
        """Return Sber enum values for hvac modes mappable to hvac_work_mode."""
        return list(dict.fromkeys(HA_TO_SBER_WORK_MODE[m] for m in self.hvac_modes or [] if m in HA_TO_SBER_WORK_MODE))

    def _mapped_thermostat_modes(self) -> list[str]:
        """Return Sber enum values for hvac modes mappable to hvac_thermostat_mode."""
        return list(
            dict.fromkeys(
                HA_TO_SBER_THERMOSTAT_MODE[m] for m in self.hvac_modes or [] if m in HA_TO_SBER_THERMOSTAT_MODE
            )
        )

    def _mapped_horizontal_swing_values(self) -> list[str]:
        """Return Sber enum values for horizontal swing modes with a known mapping.

        Unlike vertical ``swing_modes`` (which pass unmapped values through),
        horizontal modes without a Sber mapping are dropped — Sber enum values
        must not be invented from device-specific HA strings like ``"on"``.

        Returns:
            De-duplicated list of mapped Sber air flow direction values.
        """
        return list(dict.fromkeys(HA_TO_SBER_SWING[m] for m in self.swing_horizontal_modes if m in HA_TO_SBER_SWING))

    @property
    def _uses_horizontal_swing(self) -> bool:
        """Check if horizontal swing is used as the air flow direction source.

        Horizontal-only devices (HA 2024.12+) publish ``swing_horizontal_modes``
        without ``swing_modes``.  The fallback is active only when no vertical
        swing modes exist and at least one horizontal mode maps to a Sber value.

        Returns:
            True when hvac_air_flow_direction should be driven by
            ``swing_horizontal_mode`` / ``set_swing_horizontal_mode``.
        """
        return not self.swing_modes and bool(self._mapped_horizontal_swing_values())

    @property
    def _has_night_mode(self) -> bool:
        """Check if the entity supports night/sleep preset mode.

        Returns:
            True if preset_modes contains 'sleep' or 'night'.
        """
        return any(m in self._preset_modes for m in ("sleep", "night"))

    def create_allowed_values_list(self) -> dict[str, dict]:
        """Build allowed values map for enum-based and integer-based features.

        Returns:
            Dict mapping feature key to its allowed values descriptor.
        """
        allowed: dict[str, dict] = {}
        sber_fans = self._mapped_fan_values()
        if self._supports_fan and sber_fans:
            allowed["hvac_air_flow_power"] = {
                "type": "ENUM",
                "enum_values": {"values": sber_fans},
            }
        sber_swings = self._mapped_swing_values()
        if self._supports_swing and sber_swings:
            allowed["hvac_air_flow_direction"] = {
                "type": "ENUM",
                "enum_values": {"values": sber_swings},
            }
        elif self._supports_swing and self._uses_horizontal_swing:
            allowed["hvac_air_flow_direction"] = {
                "type": "ENUM",
                "enum_values": {"values": self._mapped_horizontal_swing_values()},
            }
        sber_work = self._mapped_work_modes()
        if self._supports_work_mode and sber_work:
            allowed["hvac_work_mode"] = {"type": "ENUM", "enum_values": {"values": sber_work}}
        sber_thermo = self._mapped_thermostat_modes()
        if self._supports_thermostat_mode and sber_thermo:
            allowed["hvac_thermostat_mode"] = {
                "type": "ENUM",
                "enum_values": {"values": sber_thermo},
            }
        allowed["hvac_temp_set"] = {
            "type": "INTEGER",
            "integer_values": {
                "min": str(int(self.min_temp)),
                "max": str(int(self.max_temp)),
                "step": str(self.temp_step),
            },
        }
        return allowed

    def to_sber_current_state(self) -> dict[str, dict]:
        """Build Sber current state payload with all climate attributes.

        Includes online, on_off, temperature, target temperature, fan mode,
        swing mode, HVAC work mode, target humidity, and night mode
        when values are available.

        Per Sber specification:
        - ``temperature`` uses x10 encoding (e.g. 22.0C -> 220)
        - ``hvac_temp_set`` uses whole degrees (e.g. 22.0C -> 22)
        - All ``integer_value`` fields are serialized as strings.

        Returns:
            Dict mapping entity_id to its Sber state representation.
        """
        states = [
            make_state(SberFeature.ONLINE, make_bool_value(self._is_online)),
            make_state(SberFeature.ON_OFF, make_bool_value(self.current_state)),
        ]
        states.extend(self._state_temperature())
        states.extend(self._state_fan_with_presets())
        states.extend(self._state_swing())
        states.extend(self._state_work_mode_with_presets())
        states.extend(self._state_thermostat())
        states.extend(self._state_optional_flags())
        return {self.entity_id: {"states": states}}

    def _state_temperature(self) -> list:
        """Build temperature + target_temperature state entries (if available)."""
        out: list = []
        if self.temperature is not None and math.isfinite(self.temperature):
            out.append(make_state(SberFeature.TEMPERATURE, make_integer_value(int(self.temperature * 10))))
        if self.target_temperature is not None:
            out.append(make_state(SberFeature.HVAC_TEMP_SET, make_integer_value(round(self.target_temperature))))
        return out

    def _state_fan_with_presets(self) -> list:
        """Build hvac_air_flow_power state entry, mapping HA presets to Sber turbo/quiet."""
        if not (self._supports_fan and self.fan_mode):
            return []
        fan_value = HA_TO_SBER_FAN_MODE.get(self.fan_mode)
        if self._preset_mode == "boost":
            fan_value = "turbo"
        elif self._preset_mode == "sleep" and "quiet" not in (self.fan_modes or []):
            fan_value = "quiet"
        if fan_value is None:
            # Unmapped device-specific fan mode — never leak raw HA strings
            # into a Sber enum state (issue #44 audit).
            return []
        return [make_state(SberFeature.HVAC_AIR_FLOW_POWER, make_enum_value(fan_value))]

    def _state_swing(self) -> list:
        """Build hvac_air_flow_direction state entry (if swing supported).

        Vertical ``swing_mode`` takes precedence; horizontal-only devices
        fall back to ``swing_horizontal_mode`` (only when it maps to a
        known Sber value).
        """
        if not self._supports_swing:
            return []
        if self.swing_modes and self.swing_mode:
            sber_swing = HA_TO_SBER_SWING.get(self.swing_mode)
            if sber_swing is None:
                # Unmapped swing mode — do not leak raw HA strings (issue #44 audit).
                return []
            return [make_state(SberFeature.HVAC_AIR_FLOW_DIRECTION, make_enum_value(sber_swing))]
        if self._uses_horizontal_swing and self.swing_horizontal_mode:
            sber_swing = HA_TO_SBER_SWING.get(self.swing_horizontal_mode)
            if sber_swing:
                return [make_state(SberFeature.HVAC_AIR_FLOW_DIRECTION, make_enum_value(sber_swing))]
        return []

    def _state_work_mode_with_presets(self) -> list:
        """Build hvac_work_mode state entry, mapping HA presets (boost/sleep/eco) to Sber turbo/quiet."""
        if not (self._supports_work_mode and self.hvac_mode and self.hvac_mode != "off"):
            return []
        if self._preset_mode == "boost":
            sber_mode = "turbo"
        elif self._preset_mode in ("sleep", "eco"):
            sber_mode = "quiet"
        else:
            sber_mode = HA_TO_SBER_WORK_MODE.get(self.hvac_mode)
        if not sber_mode:
            return []
        return [make_state(SberFeature.HVAC_WORK_MODE, make_enum_value(sber_mode))]

    def _state_thermostat(self) -> list:
        """Build hvac_thermostat_mode state entry (if supported)."""
        if not (self._supports_thermostat_mode and self.hvac_mode and self.hvac_mode != "off"):
            return []
        sber_mode = HA_TO_SBER_THERMOSTAT_MODE.get(self.hvac_mode)
        if not sber_mode:
            return []
        return [make_state(SberFeature.HVAC_THERMOSTAT_MODE, make_enum_value(sber_mode))]

    def _state_optional_flags(self) -> list:
        """Build optional state entries: humidity_set, night_mode, child_lock."""
        out: list = []
        if self._target_humidity is not None:
            out.append(make_state(SberFeature.HVAC_HUMIDITY_SET, make_integer_value(self._target_humidity)))
        if self._has_night_mode and self.category in self._NIGHT_MODE_CATEGORIES:
            is_night = self._preset_mode in ("sleep", "night")
            out.append(make_state(SberFeature.HVAC_NIGHT_MODE, make_bool_value(is_night)))
        # child_lock is NOT published: the Sber spec has no child_lock for any
        # hvac_* category (only socket/kettle/vacuum_cleaner) — issue #44 audit.
        return out

    @property
    def _cmd_handlers(self) -> dict[str, Callable[[dict], list[dict]]]:
        """Return dispatch map from Sber feature key to handler method."""
        return {
            SberFeature.ON_OFF: self._cmd_on_off,
            SberFeature.HVAC_TEMP_SET: self._cmd_temp_set,
            SberFeature.HVAC_AIR_FLOW_POWER: self._cmd_air_flow_power,
            SberFeature.HVAC_AIR_FLOW_DIRECTION: self._cmd_air_flow_direction,
            SberFeature.HVAC_WORK_MODE: self._cmd_work_mode,
            SberFeature.HVAC_THERMOSTAT_MODE: self._cmd_thermostat_mode,
            SberFeature.HVAC_HUMIDITY_SET: self._cmd_humidity_set,
            SberFeature.HVAC_NIGHT_MODE: self._cmd_night_mode,
        }

    def _cmd_on_off(self, value: dict) -> list[dict]:
        if value.get("type") != SberValueType.BOOL:
            return []
        on = value.get("bool_value", False)
        return [self._build_on_off_service_call(self.entity_id, "climate", on)]

    def _cmd_temp_set(self, value: dict) -> list[dict]:
        """Handle ``hvac_temp_set``: single target or heat_cool range shift.

        For heat_cool thermostats (target derived from a
        ``target_temp_high``/``target_temp_low`` range) the range is shifted
        so its midpoint lands on the requested temperature while its width
        is preserved.  Otherwise a plain ``temperature`` is sent.

        Args:
            value: Sber command value dict with ``integer_value``.

        Returns:
            Single ``set_temperature`` service call, or empty list on bad input.
        """
        temp = _safe_float_parser(value.get("integer_value"))
        if temp is None:
            return []
        if self._target_is_range and self._target_temp_high is not None and self._target_temp_low is not None:
            midpoint = (self._target_temp_high + self._target_temp_low) / 2
            delta = temp - midpoint
            return [
                self._build_service_call(
                    "climate",
                    "set_temperature",
                    self.entity_id,
                    {
                        "target_temp_high": self._target_temp_high + delta,
                        "target_temp_low": self._target_temp_low + delta,
                    },
                )
            ]
        return [self._build_service_call("climate", "set_temperature", self.entity_id, {"temperature": temp})]

    def _cmd_air_flow_power(self, value: dict) -> list[dict]:
        """Handle fan speed: prefer ``set_fan_mode``, fall back to presets."""
        sber_mode = value.get("enum_value")
        if not sber_mode:
            return []
        # Reverse map: find HA fan_mode that maps to this Sber mode
        ha_fan = sber_mode
        for fm in self.fan_modes:
            if HA_TO_SBER_FAN_MODE.get(fm, fm) == sber_mode:
                ha_fan = fm
                break
        if ha_fan and (not self.fan_modes or ha_fan in self.fan_modes):
            return [self._build_service_call("climate", "set_fan_mode", self.entity_id, {"fan_mode": ha_fan})]
        # Fallback: turbo / quiet → preset_mode
        preset = self._sber_fan_mode_to_preset(sber_mode)
        if preset is not None:
            return [self._build_service_call("climate", "set_preset_mode", self.entity_id, {"preset_mode": preset})]
        return []

    def _sber_fan_mode_to_preset(self, sber_mode: str) -> str | None:
        """Map Sber turbo/quiet modes to HA preset names when available."""
        presets = self._preset_modes or []
        if sber_mode == "turbo" and "boost" in presets:
            return "boost"
        if sber_mode == "quiet" and "sleep" in presets:
            return "sleep"
        return None

    def _cmd_air_flow_direction(self, value: dict) -> list[dict]:
        """Handle ``hvac_air_flow_direction``: vertical swing first, horizontal fallback.

        Args:
            value: Sber command value dict with ``enum_value``.

        Returns:
            Single ``set_swing_mode`` / ``set_swing_horizontal_mode`` service
            call, or empty list when the mode is unknown or unsupported.
        """
        sber_swing = value.get("enum_value")
        if not sber_swing:
            return []
        ha_swing = SBER_TO_HA_SWING.get(sber_swing)
        if not ha_swing:
            return []
        if self._uses_horizontal_swing:
            if ha_swing not in self.swing_horizontal_modes:
                return []
            return [
                self._build_service_call(
                    "climate",
                    "set_swing_horizontal_mode",
                    self.entity_id,
                    {"swing_horizontal_mode": ha_swing},
                )
            ]
        if self.swing_modes and ha_swing not in self.swing_modes:
            return []
        return [self._build_service_call("climate", "set_swing_mode", self.entity_id, {"swing_mode": ha_swing})]

    def _cmd_work_mode(self, value: dict) -> list[dict]:
        """Handle ``hvac_work_mode``: prefer ``set_hvac_mode``, fall back to presets."""
        sber_mode = value.get("enum_value")
        if not sber_mode:
            return []
        # Sber turbo/quiet work modes map to HA preset_modes
        preset = self._sber_fan_mode_to_preset(sber_mode)
        if preset is not None:
            return [self._build_service_call("climate", "set_preset_mode", self.entity_id, {"preset_mode": preset})]
        ha_mode = SBER_TO_HA_WORK_MODE.get(sber_mode)
        if not ha_mode or (self.hvac_modes and ha_mode not in self.hvac_modes):
            return []
        return [self._build_service_call("climate", "set_hvac_mode", self.entity_id, {"hvac_mode": ha_mode})]

    def _cmd_thermostat_mode(self, value: dict) -> list[dict]:
        sber_mode = value.get("enum_value")
        if not sber_mode:
            return []
        ha_mode = SBER_TO_HA_THERMOSTAT_MODE.get(sber_mode)
        if not ha_mode or (self.hvac_modes and ha_mode not in self.hvac_modes):
            return []
        return [self._build_service_call("climate", "set_hvac_mode", self.entity_id, {"hvac_mode": ha_mode})]

    def _cmd_humidity_set(self, value: dict) -> list[dict]:
        humidity = _safe_clamped_int_parser(value.get("integer_value"), 0, 100)
        if humidity is None:
            return []
        return [self._build_service_call("climate", "set_humidity", self.entity_id, {"humidity": humidity})]

    def _cmd_night_mode(self, value: dict) -> list[dict]:
        """Handle ``hvac_night_mode``: toggle sleep/night preset."""
        night_on = value.get("bool_value", False)
        presets = self._preset_modes or []
        if night_on:
            preset = "sleep" if "sleep" in presets else "night"
            return [self._build_service_call("climate", "set_preset_mode", self.entity_id, {"preset_mode": preset})]
        # Turn off: fall back to first non-night preset or "none"
        normal_presets = [p for p in presets if p not in ("sleep", "night")]
        if "none" in presets or normal_presets:
            fallback = normal_presets[0] if normal_presets else "none"
            return [self._build_service_call("climate", "set_preset_mode", self.entity_id, {"preset_mode": fallback})]
        _LOGGER.warning(
            "Cannot turn off night mode for %s: no non-night presets available",
            self.entity_id,
        )
        return []
