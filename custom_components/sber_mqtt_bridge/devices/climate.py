"""Sber Climate (AC) entity -- maps HA climate entities to Sber hvac_ac category."""

from __future__ import annotations

import logging
import math
from collections.abc import Callable

from ..sber_constants import SberFeature
from ..sber_models import make_bool_value, make_enum_value, make_integer_value, make_state
from .base_entity import ROLE_TEMPERATURE, BaseEntity, CommandResult

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
        self.hvac_modes = []
        self.fan_mode = None
        self.swing_mode = None
        self.hvac_mode = None
        self.min_temp = min_temp
        self.max_temp = max_temp
        self._target_humidity: int | None = None
        self._preset_mode: str | None = None
        self._preset_modes: list[str] = []
        self._child_lock: bool | None = None

    def fill_by_ha_state(self, ha_state: dict) -> None:
        """Parse HA state and update all climate attributes.

        Args:
            ha_state: HA state dict with 'state' and 'attributes' keys.
                Attributes may include current_temperature, temperature,
                fan_modes, swing_modes, hvac_modes, target_humidity,
                preset_mode, preset_modes, etc.
        """
        super().fill_by_ha_state(ha_state)
        self.current_state = ha_state.get("state", "off") != "off"
        attrs = ha_state.get("attributes", {})
        raw_temp = self._safe_float(attrs.get("current_temperature"))
        self.temperature = raw_temp if raw_temp is not None and math.isfinite(raw_temp) else None
        raw_target = self._safe_float(attrs.get("temperature"))
        self.target_temperature = raw_target if raw_target is not None and math.isfinite(raw_target) else None
        self.fan_modes = attrs.get("fan_modes") or []
        self.swing_modes = attrs.get("swing_modes") or []
        self.hvac_modes = attrs.get("hvac_modes") or []
        self.fan_mode = attrs.get("fan_mode")
        self.swing_mode = attrs.get("swing_mode")
        self.hvac_mode = ha_state.get("state")
        self.min_temp = self._safe_float(attrs.get("min_temp")) or 16.0
        self.max_temp = self._safe_float(attrs.get("max_temp")) or 32.0
        target_humidity = attrs.get("target_humidity")
        if target_humidity is not None:
            try:
                self._target_humidity = int(target_humidity)
            except (TypeError, ValueError):
                self._target_humidity = None
        else:
            self._target_humidity = None
        self._preset_mode = attrs.get("preset_mode")
        self._preset_modes = attrs.get("preset_modes", [])
        child_lock = attrs.get("child_lock")
        self._child_lock = bool(child_lock) if child_lock is not None else None

    def create_features_list(self) -> list[str]:
        """Return Sber feature list based on available climate capabilities.

        Dynamically includes fan, swing, HVAC mode, humidity, and night mode
        features only when the HA entity supports them.

        Returns:
            List of Sber feature strings supported by this entity.
        """
        features = [*super().create_features_list(), "on_off", "temperature", "hvac_temp_set"]
        if self._supports_swing and self.swing_modes:
            features.append("hvac_air_flow_direction")
        if self._supports_fan and self.fan_modes:
            features.append("hvac_air_flow_power")
        if self._supports_work_mode and self.hvac_modes:
            features.append("hvac_work_mode")
        if self._supports_thermostat_mode and self.hvac_modes:
            features.append("hvac_thermostat_mode")
        if self._target_humidity is not None:
            features.append("hvac_humidity_set")
        if self._has_night_mode:
            features.append("hvac_night_mode")
        if self._child_lock is not None:
            features.append("child_lock")
        return features

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
        if self._supports_fan and self.fan_modes:
            sber_fans = [HA_TO_SBER_FAN_MODE.get(m, m) for m in self.fan_modes]
            allowed["hvac_air_flow_power"] = {
                "type": "ENUM",
                "enum_values": {"values": list(dict.fromkeys(sber_fans))},
            }
        if self._supports_swing and self.swing_modes:
            sber_swings = [HA_TO_SBER_SWING.get(m, m) for m in self.swing_modes]
            allowed["hvac_air_flow_direction"] = {
                "type": "ENUM",
                "enum_values": {"values": list(dict.fromkeys(sber_swings))},
            }
        if self._supports_work_mode and self.hvac_modes:
            sber_modes = [HA_TO_SBER_WORK_MODE[m] for m in self.hvac_modes if m in HA_TO_SBER_WORK_MODE]
            if sber_modes:
                allowed["hvac_work_mode"] = {"type": "ENUM", "enum_values": {"values": list(dict.fromkeys(sber_modes))}}
        if self._supports_thermostat_mode and self.hvac_modes:
            sber_modes = [HA_TO_SBER_THERMOSTAT_MODE[m] for m in self.hvac_modes if m in HA_TO_SBER_THERMOSTAT_MODE]
            if sber_modes:
                allowed["hvac_thermostat_mode"] = {
                    "type": "ENUM",
                    "enum_values": {"values": list(dict.fromkeys(sber_modes))},
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
        if self.temperature is not None and math.isfinite(self.temperature):
            states.append(make_state(SberFeature.TEMPERATURE, make_integer_value(int(self.temperature * 10))))
        if self.target_temperature is not None:
            states.append(make_state(SberFeature.HVAC_TEMP_SET, make_integer_value(round(self.target_temperature))))
        if self._supports_fan and self.fan_mode:
            fan_value = HA_TO_SBER_FAN_MODE.get(self.fan_mode, self.fan_mode)
            # Map HA preset modes to Sber air flow power values
            if self._preset_mode == "boost":
                fan_value = "turbo"
            elif self._preset_mode == "sleep" and "quiet" not in (self.fan_modes or []):
                fan_value = "quiet"
            states.append(make_state(SberFeature.HVAC_AIR_FLOW_POWER, make_enum_value(fan_value)))
        if self._supports_swing and self.swing_mode:
            sber_swing = HA_TO_SBER_SWING.get(self.swing_mode, self.swing_mode)
            states.append(make_state(SberFeature.HVAC_AIR_FLOW_DIRECTION, make_enum_value(sber_swing)))
        if self._supports_work_mode and self.hvac_mode and self.hvac_mode != "off":
            # Map HA preset modes to Sber work modes (turbo/quiet)
            if self._preset_mode == "boost":
                sber_mode = "turbo"
            elif self._preset_mode in ("sleep", "eco"):
                sber_mode = "quiet"
            else:
                sber_mode = HA_TO_SBER_WORK_MODE.get(self.hvac_mode)
            if sber_mode:
                states.append(make_state(SberFeature.HVAC_WORK_MODE, make_enum_value(sber_mode)))
        if self._supports_thermostat_mode and self.hvac_mode and self.hvac_mode != "off":
            sber_mode = HA_TO_SBER_THERMOSTAT_MODE.get(self.hvac_mode)
            if sber_mode:
                states.append(make_state(SberFeature.HVAC_THERMOSTAT_MODE, make_enum_value(sber_mode)))
        if self._target_humidity is not None:
            states.append(make_state(SberFeature.HVAC_HUMIDITY_SET, make_integer_value(self._target_humidity)))
        if self._has_night_mode:
            is_night = self._preset_mode in ("sleep", "night")
            states.append(make_state(SberFeature.HVAC_NIGHT_MODE, make_bool_value(is_night)))
        if self._child_lock is not None:
            states.append(make_state(SberFeature.CHILD_LOCK, make_bool_value(self._child_lock)))
        return {self.entity_id: {"states": states}}

    def process_cmd(self, cmd_data: dict) -> list[CommandResult]:
        """Process Sber climate commands and produce HA service calls.

        Uses a command handler dispatch table (``_cmd_handlers``) to route
        each Sber feature key to a dedicated handler method.  Each handler
        returns a list of service calls (possibly empty).

        State is NOT mutated here -- it will be updated when HA fires a
        ``state_changed`` event that is handled by ``fill_by_ha_state``.

        Args:
            cmd_data: Sber command dict with 'states' list.

        Returns:
            List of HA service call dicts to execute.
        """
        handlers = self._cmd_handlers
        results: list[dict] = []
        for item in cmd_data.get("states", []):
            handler = handlers.get(item.get("key", ""))
            if handler is None:
                continue
            results.extend(handler(item.get("value", {})))
        return results

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
        on = value.get("bool_value", False)
        return [self._build_on_off_service_call(self.entity_id, "climate", on)]

    def _cmd_temp_set(self, value: dict) -> list[dict]:
        temp = self._safe_float(value.get("integer_value"))
        if temp is None:
            return []
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
        sber_swing = value.get("enum_value")
        if not sber_swing:
            return []
        ha_swing = SBER_TO_HA_SWING.get(sber_swing)
        if not ha_swing or (self.swing_modes and ha_swing not in self.swing_modes):
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
        humidity = self._safe_clamped_int(value.get("integer_value"), 0, 100)
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
