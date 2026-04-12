"""Sber Humidifier entity -- maps HA humidifier entities to Sber hvac_humidifier."""

from __future__ import annotations

import contextlib
import logging
from typing import ClassVar

from ..sber_constants import SberFeature
from ..sber_models import make_bool_value, make_enum_value, make_integer_value, make_state
from .base_entity import ROLE_HUMIDITY, AttrSpec, BaseEntity, CommandResult, _safe_bool_parser, _safe_int_parser

_LOGGER = logging.getLogger(__name__)

HUMIDIFIER_CATEGORY = "hvac_humidifier"
"""Sber device category for humidifier entities."""

# HA humidifier mode → Sber hvac_work_mode (lowercase, Sber-standard names)
HA_TO_SBER_HUMIDIFIER_MODE: dict[str, str] = {
    "auto": "auto",
    "low": "low",
    "mid": "medium",
    "medium": "medium",
    "high": "high",
    "silent": "quiet",
    "sleep": "quiet",
    "night": "quiet",
    "strong": "turbo",
    "boost": "turbo",
}
"""Map HA humidifier modes to Sber-standard enum values (case-insensitive lookup)."""


def _min_humidity_parser(value: object) -> int:
    """Parse min_humidity, defaulting to 35 on None or invalid."""
    parsed = _safe_int_parser(value)
    return parsed or 35


def _max_humidity_parser(value: object) -> int:
    """Parse max_humidity, defaulting to 85 on None or invalid."""
    parsed = _safe_int_parser(value)
    return parsed or 85


class HumidifierEntity(BaseEntity):
    """Sber humidifier entity for humidity control devices.

    Maps HA humidifier entities to the Sber 'hvac_humidifier' category
    with support for:
    - On/off control
    - Target humidity setting
    - Work mode selection (when supported by the device)
    """

    LINKABLE_ROLES = (ROLE_HUMIDITY,)

    ATTR_SPECS: ClassVar[tuple[AttrSpec, ...]] = (
        AttrSpec(
            field="target_humidity",
            attr_keys=("humidity",),
        ),
        AttrSpec(
            field="current_humidity",
            attr_keys=("current_humidity",),
            preserve_on_missing=True,
        ),
        AttrSpec(
            field="available_modes",
            converter=lambda attrs: attrs.get("available_modes") or [],
            default=[],
        ),
        AttrSpec(
            field="mode",
            attr_keys=("mode",),
        ),
        AttrSpec(
            field="_min_humidity",
            attr_keys=("min_humidity",),
            parser=_min_humidity_parser,
            default=35,
        ),
        AttrSpec(
            field="_max_humidity",
            attr_keys=("max_humidity",),
            parser=_max_humidity_parser,
            default=85,
        ),
        AttrSpec(
            field="_water_level",
            attr_keys=("water_level",),
            parser=_safe_int_parser,
        ),
        AttrSpec(
            field="_water_low_level",
            attr_keys=("water_low_level",),
            parser=_safe_bool_parser,
        ),
        AttrSpec(
            field="_child_lock",
            attr_keys=("child_lock",),
            parser=_safe_bool_parser,
        ),
    )

    def __init__(self, entity_data: dict) -> None:
        """Initialize humidifier entity.

        Args:
            entity_data: HA entity registry dict containing entity metadata.
        """
        super().__init__(HUMIDIFIER_CATEGORY, entity_data)
        self.current_state = False
        self.target_humidity = None
        self.current_humidity = None
        self.available_modes: list[str] = []
        self.mode: str | None = None
        self._min_humidity: int = 35
        self._max_humidity: int = 85
        self._water_level: int | None = None
        self._water_low_level: bool | None = None
        self._child_lock: bool | None = None

    def fill_by_ha_state(self, ha_state: dict) -> None:
        """Parse HA state and update all humidifier attributes.

        Args:
            ha_state: HA state dict with 'state' and 'attributes' keys.
                Attributes may include humidity, current_humidity,
                available_modes, and mode.
        """
        super().fill_by_ha_state(ha_state)
        attrs = ha_state.get("attributes", {})
        self._apply_attr_specs(attrs)
        self.current_state = ha_state.get("state") == "on"

    def update_linked_data(self, role: str, ha_state: dict) -> None:
        """Inject current humidity from a linked sensor entity.

        When the HA humidifier entity does not provide ``current_humidity``
        in its attributes, an external humidity sensor can be linked to
        supply the value for the Sber ``humidity`` feature.

        Args:
            role: Link role name (only ``humidity`` is handled).
            ha_state: HA state dict with 'state' containing the reading.
        """
        if role == "humidity":
            state_val = ha_state.get("state")
            if state_val not in (None, "unknown", "unavailable"):
                with contextlib.suppress(TypeError, ValueError):
                    self.current_humidity = float(state_val)

    def create_features_list(self) -> list[str]:
        """Return Sber feature list based on available humidifier capabilities.

        Dynamically includes work mode and night mode features only when
        the HA entity supports them.

        Returns:
            List of Sber feature strings supported by this entity.
        """
        features = [*super().create_features_list(), "on_off", "humidity", "hvac_humidity_set"]
        if self.available_modes:
            features.append("hvac_air_flow_power")
        if self._has_night_mode:
            features.append("hvac_night_mode")
        if self._water_level is not None:
            features.append("hvac_water_percentage")
        if self._water_low_level is not None:
            features.append("hvac_water_low_level")
        if self._child_lock is not None:
            features.append("child_lock")
        return features

    @property
    def _has_night_mode(self) -> bool:
        """Check if the entity supports night/sleep mode.

        Returns:
            True if available_modes contains 'sleep' or 'night'.
        """
        return any(m in self.available_modes for m in ("sleep", "night"))

    def create_allowed_values_list(self) -> dict[str, dict]:
        """Build allowed values map for enum-based and integer-based features.

        Returns:
            Dict mapping feature key to its allowed values descriptor.
        """
        allowed: dict[str, dict] = {}
        if self.available_modes:
            sber_modes = [HA_TO_SBER_HUMIDIFIER_MODE.get(m.lower(), m.lower()) for m in self.available_modes]
            # Deduplicate while preserving order
            allowed["hvac_air_flow_power"] = {
                "type": "ENUM",
                "enum_values": {"values": list(dict.fromkeys(sber_modes))},
            }
        allowed["hvac_humidity_set"] = {
            "type": "INTEGER",
            "integer_values": {
                "min": str(self._min_humidity),
                "max": str(self._max_humidity),
                "step": "5",
            },
        }
        return allowed

    def to_sber_current_state(self) -> dict[str, dict]:
        """Build Sber current state payload with humidifier attributes.

        Includes online, on_off, target humidity, work mode, and night mode
        when values are available.

        Per Sber C2C specification, ``integer_value`` is serialized as a string.

        Returns:
            Dict mapping entity_id to its Sber state representation.
        """
        states = [
            make_state(SberFeature.ONLINE, make_bool_value(self._is_online)),
            make_state(SberFeature.ON_OFF, make_bool_value(self.current_state)),
        ]
        if self.current_humidity is not None:
            states.append(make_state(SberFeature.HUMIDITY, make_integer_value(round(self.current_humidity))))
        if self.target_humidity is not None:
            states.append(make_state(SberFeature.HVAC_HUMIDITY_SET, make_integer_value(round(self.target_humidity))))
        if self.mode:
            sber_mode = HA_TO_SBER_HUMIDIFIER_MODE.get(self.mode.lower(), self.mode.lower())
            states.append(make_state(SberFeature.HVAC_AIR_FLOW_POWER, make_enum_value(sber_mode)))
        if self._has_night_mode:
            is_night = self.mode in ("sleep", "night")
            states.append(make_state(SberFeature.HVAC_NIGHT_MODE, make_bool_value(is_night)))
        if self._water_level is not None:
            states.append(make_state(SberFeature.HVAC_WATER_PERCENTAGE, make_integer_value(self._water_level)))
        if self._water_low_level is not None:
            states.append(make_state(SberFeature.HVAC_WATER_LOW_LEVEL, make_bool_value(self._water_low_level)))
        if self._child_lock is not None:
            states.append(make_state(SberFeature.CHILD_LOCK, make_bool_value(self._child_lock)))
        return {self.entity_id: {"states": states}}

    def process_cmd(self, cmd_data: dict) -> list[CommandResult]:
        """Process Sber humidifier commands and produce HA service calls.

        State is NOT mutated here -- it will be updated when HA fires a
        ``state_changed`` event that is handled by ``fill_by_ha_state``.

        Args:
            cmd_data: Sber command dict with 'states' list.

        Returns:
            List of HA service call dicts to execute.
        """
        results: list[dict] = []
        for item in cmd_data.get("states", []):
            key = item.get("key", "")
            value = item.get("value", {})
            if key == SberFeature.ON_OFF:
                results.extend(self._cmd_on_off(value))
            elif key in (SberFeature.HUMIDITY, SberFeature.HVAC_HUMIDITY_SET):
                results.extend(self._cmd_humidity(value))
            elif key in (SberFeature.HVAC_AIR_FLOW_POWER, SberFeature.HVAC_WORK_MODE):
                results.extend(self._cmd_mode(value))
            elif key == SberFeature.HVAC_NIGHT_MODE:
                results.extend(self._cmd_night_mode(value))
        return results

    def _cmd_on_off(self, value: dict) -> list[dict]:
        on = value.get("bool_value", False)
        return [self._build_on_off_service_call(self.entity_id, "humidifier", on)]

    def _cmd_humidity(self, value: dict) -> list[dict]:
        humidity = self._safe_int(value.get("integer_value"))
        if humidity is None:
            return []
        return [self._build_service_call("humidifier", "set_humidity", self.entity_id, {"humidity": humidity})]

    def _cmd_mode(self, value: dict) -> list[dict]:
        sber_mode = value.get("enum_value")
        if sber_mode is None:
            return []
        # Reverse map: find HA mode that maps to this Sber mode
        ha_mode = sber_mode
        for ha_m in self.available_modes:
            if HA_TO_SBER_HUMIDIFIER_MODE.get(ha_m.lower(), ha_m.lower()) == sber_mode:
                ha_mode = ha_m
                break
        return [self._build_service_call("humidifier", "set_mode", self.entity_id, {"mode": ha_mode})]

    def _cmd_night_mode(self, value: dict) -> list[dict]:
        night_on = value.get("bool_value", False)
        if night_on:
            mode = "sleep" if "sleep" in self.available_modes else "night"
            return [self._build_service_call("humidifier", "set_mode", self.entity_id, {"mode": mode})]
        normal_modes = [m for m in self.available_modes if m not in ("sleep", "night")]
        if not normal_modes:
            return []
        return [self._build_service_call("humidifier", "set_mode", self.entity_id, {"mode": normal_modes[0]})]
