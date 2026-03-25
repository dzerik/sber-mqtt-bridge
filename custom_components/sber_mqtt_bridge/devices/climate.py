"""Sber Climate (AC) entity -- maps HA climate entities to Sber hvac_ac category."""

from __future__ import annotations

import logging

from .base_entity import BaseEntity

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
}
"""Map HA HVAC modes to Sber work mode enum values. 'off' is excluded — use on_off."""

SBER_TO_HA_WORK_MODE: dict[str, str] = {
    "cooling": "cool",
    "heating": "heat",
    "dehumidification": "dry",
    "ventilation": "fan_only",
    "auto": "auto",
}
"""Reverse mapping: Sber work mode → HA hvac_mode."""

# HA swing_mode → Sber hvac_air_flow_direction mapping
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
"""Reverse mapping: Sber thermostat mode → HA hvac_mode."""

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

SBER_TO_HA_FAN_MODE: dict[str, str] = {}
"""Reverse mapping populated dynamically per-device from available fan_modes."""


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
        self.temperature = self._safe_float(attrs.get("current_temperature"))
        self.target_temperature = self._safe_float(attrs.get("temperature"))
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
            {"key": "online", "value": {"type": "BOOL", "bool_value": self._is_online}},
            {"key": "on_off", "value": {"type": "BOOL", "bool_value": self.current_state}},
        ]
        if self.temperature is not None:
            states.append(
                {"key": "temperature", "value": {"type": "INTEGER", "integer_value": str(int(self.temperature * 10))}}
            )
        if self.target_temperature is not None:
            states.append(
                {
                    "key": "hvac_temp_set",
                    "value": {"type": "INTEGER", "integer_value": str(round(self.target_temperature))},
                }
            )
        if self._supports_fan and self.fan_mode:
            fan_value = HA_TO_SBER_FAN_MODE.get(self.fan_mode, self.fan_mode)
            # Map HA preset modes to Sber air flow power values
            if self._preset_mode == "boost":
                fan_value = "turbo"
            elif self._preset_mode == "sleep" and "quiet" not in (self.fan_modes or []):
                fan_value = "quiet"
            states.append({"key": "hvac_air_flow_power", "value": {"type": "ENUM", "enum_value": fan_value}})
        if self._supports_swing and self.swing_mode:
            sber_swing = HA_TO_SBER_SWING.get(self.swing_mode, self.swing_mode)
            states.append({"key": "hvac_air_flow_direction", "value": {"type": "ENUM", "enum_value": sber_swing}})
        if self._supports_work_mode and self.hvac_mode and self.hvac_mode != "off":
            sber_mode = HA_TO_SBER_WORK_MODE.get(self.hvac_mode)
            if sber_mode:
                states.append({"key": "hvac_work_mode", "value": {"type": "ENUM", "enum_value": sber_mode}})
        if self._supports_thermostat_mode and self.hvac_mode and self.hvac_mode != "off":
            sber_mode = HA_TO_SBER_THERMOSTAT_MODE.get(self.hvac_mode)
            if sber_mode:
                states.append({"key": "hvac_thermostat_mode", "value": {"type": "ENUM", "enum_value": sber_mode}})
        if self._target_humidity is not None:
            states.append(
                {"key": "hvac_humidity_set", "value": {"type": "INTEGER", "integer_value": str(self._target_humidity)}}
            )
        if self._has_night_mode:
            is_night = self._preset_mode in ("sleep", "night")
            states.append({"key": "hvac_night_mode", "value": {"type": "BOOL", "bool_value": is_night}})
        return {self.entity_id: {"states": states}}

    def process_cmd(self, cmd_data: dict) -> list[dict]:
        """Process Sber climate commands and produce HA service calls.

        Handles the following Sber keys:
        - ``on_off``: turn_on / turn_off
        - ``hvac_temp_set``: set_temperature (whole degrees, no scaling)
        - ``hvac_air_flow_power``: set_fan_mode
        - ``hvac_air_flow_direction``: set_swing_mode
        - ``hvac_work_mode``: set_hvac_mode
        - ``hvac_humidity_set``: set_humidity (INTEGER 0-100)
        - ``hvac_night_mode``: set_preset_mode (sleep/none)

        State is NOT mutated here -- it will be updated when HA fires a
        ``state_changed`` event that is handled by ``fill_by_ha_state``.

        Args:
            cmd_data: Sber command dict with 'states' list.

        Returns:
            List of HA service call dicts to execute.
        """
        results = []
        for item in cmd_data.get("states", []):
            key = item.get("key")
            value = item.get("value", {})

            if key == "on_off":
                on = value.get("bool_value", False)
                results.append(self._build_on_off_service_call(self.entity_id, "climate", on))
            elif key == "hvac_temp_set":
                raw_temp = value.get("integer_value")
                temp = self._safe_float(raw_temp)
                if temp is None:
                    continue
                results.append(
                    {
                        "url": {
                            "type": "call_service",
                            "domain": "climate",
                            "service": "set_temperature",
                            "service_data": {"temperature": temp},
                            "target": {"entity_id": self.entity_id},
                        }
                    }
                )
            elif key == "hvac_air_flow_power":
                sber_mode = value.get("enum_value")
                if not sber_mode:
                    continue
                # Reverse map: find HA fan_mode that maps to this Sber mode
                ha_fan = sber_mode
                for fm in self.fan_modes:
                    if HA_TO_SBER_FAN_MODE.get(fm, fm) == sber_mode:
                        ha_fan = fm
                        break
                if ha_fan and (not self.fan_modes or ha_fan in self.fan_modes):
                    results.append(
                        {
                            "url": {
                                "type": "call_service",
                                "domain": "climate",
                                "service": "set_fan_mode",
                                "service_data": {"fan_mode": ha_fan},
                                "target": {"entity_id": self.entity_id},
                            }
                        }
                    )
                elif sber_mode == "turbo" and "boost" in (self._preset_modes or []):
                    results.append(
                        {
                            "url": {
                                "type": "call_service",
                                "domain": "climate",
                                "service": "set_preset_mode",
                                "service_data": {"preset_mode": "boost"},
                                "target": {"entity_id": self.entity_id},
                            }
                        }
                    )
                elif sber_mode == "quiet" and "sleep" in (self._preset_modes or []):
                    results.append(
                        {
                            "url": {
                                "type": "call_service",
                                "domain": "climate",
                                "service": "set_preset_mode",
                                "service_data": {"preset_mode": "sleep"},
                                "target": {"entity_id": self.entity_id},
                            }
                        }
                    )
            elif key == "hvac_air_flow_direction":
                sber_swing = value.get("enum_value")
                ha_swing = SBER_TO_HA_SWING.get(sber_swing or "") if sber_swing else None
                if ha_swing and (not self.swing_modes or ha_swing in self.swing_modes):
                    results.append(
                        {
                            "url": {
                                "type": "call_service",
                                "domain": "climate",
                                "service": "set_swing_mode",
                                "service_data": {"swing_mode": ha_swing},
                                "target": {"entity_id": self.entity_id},
                            }
                        }
                    )
            elif key == "hvac_work_mode":
                sber_mode = value.get("enum_value")
                ha_mode = SBER_TO_HA_WORK_MODE.get(sber_mode or "") if sber_mode else None
                if ha_mode and (not self.hvac_modes or ha_mode in self.hvac_modes):
                    results.append(
                        {
                            "url": {
                                "type": "call_service",
                                "domain": "climate",
                                "service": "set_hvac_mode",
                                "service_data": {"hvac_mode": ha_mode},
                                "target": {"entity_id": self.entity_id},
                            }
                        }
                    )
            elif key == "hvac_thermostat_mode":
                sber_mode = value.get("enum_value")
                ha_mode = SBER_TO_HA_THERMOSTAT_MODE.get(sber_mode or "") if sber_mode else None
                if ha_mode and (not self.hvac_modes or ha_mode in self.hvac_modes):
                    results.append(
                        {
                            "url": {
                                "type": "call_service",
                                "domain": "climate",
                                "service": "set_hvac_mode",
                                "service_data": {"hvac_mode": ha_mode},
                                "target": {"entity_id": self.entity_id},
                            }
                        }
                    )
            elif key == "hvac_humidity_set":
                humidity = self._safe_int(value.get("integer_value"))
                if humidity is None:
                    continue
                results.append(
                    {
                        "url": {
                            "type": "call_service",
                            "domain": "climate",
                            "service": "set_humidity",
                            "service_data": {"humidity": humidity},
                            "target": {"entity_id": self.entity_id},
                        }
                    }
                )
            elif key == "hvac_night_mode":
                night_on = value.get("bool_value", False)
                if night_on:
                    # Find the night/sleep preset mode
                    preset = "sleep" if "sleep" in self._preset_modes else "night"
                    results.append(
                        {
                            "url": {
                                "type": "call_service",
                                "domain": "climate",
                                "service": "set_preset_mode",
                                "service_data": {"preset_mode": preset},
                                "target": {"entity_id": self.entity_id},
                            }
                        }
                    )
                else:
                    results.append(
                        {
                            "url": {
                                "type": "call_service",
                                "domain": "climate",
                                "service": "set_preset_mode",
                                "service_data": {"preset_mode": "none"},
                                "target": {"entity_id": self.entity_id},
                            }
                        }
                    )
        return results
