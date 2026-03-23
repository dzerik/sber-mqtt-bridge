"""Sber Climate (AC) entity -- maps HA climate entities to Sber hvac_ac category."""

from __future__ import annotations

import logging

from .base_entity import BaseEntity

_LOGGER = logging.getLogger(__name__)

CLIMATE_CATEGORY = "hvac_ac"
"""Sber device category for air conditioner / HVAC entities."""


class ClimateEntity(BaseEntity):
    """Sber climate entity for air conditioner control.

    Maps HA climate entities to the Sber 'hvac_ac' category with support for:
    - On/off control
    - Temperature reading and target temperature setting
    - Fan mode, swing mode, and HVAC work mode selection
    - Allowed values for dynamic enum features
    """

    def __init__(
        self,
        entity_data: dict,
        category: str = CLIMATE_CATEGORY,
        min_temp: float = 16.0,
        max_temp: float = 32.0,
    ) -> None:
        """Initialize climate entity.

        Args:
            entity_data: HA entity registry dict containing entity metadata.
            category: Sber device category (override in subclasses).
            min_temp: Minimum temperature default.
            max_temp: Maximum temperature default.
        """
        super().__init__(category, entity_data)
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
        self.temperature = attrs.get("current_temperature")
        self.target_temperature = attrs.get("temperature")
        self.fan_modes = attrs.get("fan_modes", [])
        self.swing_modes = attrs.get("swing_modes", [])
        self.hvac_modes = attrs.get("hvac_modes", [])
        self.fan_mode = attrs.get("fan_mode")
        self.swing_mode = attrs.get("swing_mode")
        self.hvac_mode = ha_state.get("state")
        self.min_temp = attrs.get("min_temp", 16.0)
        self.max_temp = attrs.get("max_temp", 32.0)
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
        if self.swing_modes:
            features.append("hvac_air_flow_direction")
        if self.fan_modes:
            features.append("hvac_air_flow_power")
        if self.hvac_modes:
            features.append("hvac_work_mode")
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
        if self.fan_modes:
            allowed["hvac_air_flow_power"] = {"type": "ENUM", "enum_values": {"values": self.fan_modes}}
        if self.swing_modes:
            allowed["hvac_air_flow_direction"] = {"type": "ENUM", "enum_values": {"values": self.swing_modes}}
        if self.hvac_modes:
            allowed["hvac_work_mode"] = {"type": "ENUM", "enum_values": {"values": self.hvac_modes}}
        allowed["hvac_temp_set"] = {
            "type": "INTEGER",
            "integer_values": {
                "min": str(int(self.min_temp)),
                "max": str(int(self.max_temp)),
                "step": "1",
            },
        }
        return allowed

    def to_sber_state(self) -> dict:
        """Build full Sber device descriptor including allowed values.

        Overrides base to inject allowed_values into the model.
        Features are already populated by ``super().to_sber_state()``.

        Returns:
            Sber device descriptor dict with model, features, and allowed_values.
        """
        res = super().to_sber_state()
        res["model"]["allowed_values"] = self.create_allowed_values_list()
        return res

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
        if self.fan_mode:
            fan_value = self.fan_mode
            # Map HA preset modes to Sber air flow power values
            if self._preset_mode == "boost":
                fan_value = "turbo"
            elif self._preset_mode == "sleep" and "quiet" not in (self.fan_modes or []):
                fan_value = "quiet"
            states.append({"key": "hvac_air_flow_power", "value": {"type": "ENUM", "enum_value": fan_value}})
        if self.swing_mode:
            states.append({"key": "hvac_air_flow_direction", "value": {"type": "ENUM", "enum_value": self.swing_mode}})
        if self.hvac_mode:
            states.append({"key": "hvac_work_mode", "value": {"type": "ENUM", "enum_value": self.hvac_mode}})
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
                if raw_temp is None:
                    continue
                # Sber sends hvac_temp_set as whole degrees (no x10 scaling)
                temp = float(int(raw_temp))
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
                mode = value.get("enum_value")
                if mode and (not self.fan_modes or mode in self.fan_modes):
                    results.append(
                        {
                            "url": {
                                "type": "call_service",
                                "domain": "climate",
                                "service": "set_fan_mode",
                                "service_data": {"fan_mode": mode},
                                "target": {"entity_id": self.entity_id},
                            }
                        }
                    )
                elif mode == "turbo" and "boost" in (self._preset_modes or []):
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
                elif mode == "quiet" and "sleep" in (self._preset_modes or []):
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
                mode = value.get("enum_value")
                if mode and (not self.swing_modes or mode in self.swing_modes):
                    results.append(
                        {
                            "url": {
                                "type": "call_service",
                                "domain": "climate",
                                "service": "set_swing_mode",
                                "service_data": {"swing_mode": mode},
                                "target": {"entity_id": self.entity_id},
                            }
                        }
                    )
            elif key == "hvac_work_mode":
                mode = value.get("enum_value")
                if mode and (not self.hvac_modes or mode in self.hvac_modes):
                    results.append(
                        {
                            "url": {
                                "type": "call_service",
                                "domain": "climate",
                                "service": "set_hvac_mode",
                                "service_data": {"hvac_mode": mode},
                                "target": {"entity_id": self.entity_id},
                            }
                        }
                    )
            elif key == "hvac_humidity_set":
                raw_humidity = value.get("integer_value")
                if raw_humidity is None:
                    continue
                results.append(
                    {
                        "url": {
                            "type": "call_service",
                            "domain": "climate",
                            "service": "set_humidity",
                            "service_data": {"humidity": int(raw_humidity)},
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
