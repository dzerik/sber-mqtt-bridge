"""Sber Vacuum Cleaner entity -- maps HA vacuum entities to Sber vacuum_cleaner category.

Supports start/stop/pause/return_to_base commands, status reporting,
cleaning program (fan speed), and battery level.
"""

from __future__ import annotations

import logging

from ..sber_constants import SberFeature, SberValueType
from ..sber_models import make_bool_value, make_enum_value, make_integer_value, make_state
from .base_entity import BaseEntity

_LOGGER = logging.getLogger(__name__)

VACUUM_CLEANER_CATEGORY = "vacuum_cleaner"
"""Sber device category for vacuum cleaner entities."""

_HA_STATE_TO_SBER_STATUS: dict[str, str] = {
    "cleaning": "cleaning",
    "returning": "go_home",
    "docked": "standby",
    "paused": "standby",
    "idle": "standby",
    "error": "error",
}
"""Mapping from HA vacuum state to Sber vacuum_cleaner_status ENUM.

Sber documented values: cleaning, charging, standby, go_home, error.
"""

_SBER_CMD_TO_HA_SERVICE: dict[str, str] = {
    "start": "start",
    "stop": "stop",
    "pause": "pause",
    "return_to_dock": "return_to_base",
}
"""Mapping from Sber vacuum_cleaner_command ENUM to HA vacuum service."""


class VacuumCleanerEntity(BaseEntity):
    """Sber vacuum cleaner entity for robot vacuum devices.

    Maps HA vacuum entities to the Sber 'vacuum_cleaner' category with support for:
    - Start/stop/pause/return_to_base commands
    - Status reporting (cleaning, charging, docked, returning, error, paused)
    - Cleaning program (fan speed)
    - Battery percentage
    """

    def __init__(self, entity_data: dict) -> None:
        """Initialize vacuum cleaner entity.

        Args:
            entity_data: HA entity registry dict containing entity metadata.
        """
        super().__init__(VACUUM_CLEANER_CATEGORY, entity_data)
        self._status: str = "docked"
        self._fan_speed: str | None = None
        self._fan_speed_list: list[str] = []
        self._battery_level: int | None = None
        self._cleaning_type: str | None = None

    def fill_by_ha_state(self, ha_state: dict) -> None:
        """Parse HA state and update vacuum cleaner attributes.

        Args:
            ha_state: HA state dict with 'state' and 'attributes' keys.
        """
        super().fill_by_ha_state(ha_state)
        ha_status = ha_state.get("state", "")
        self._status = _HA_STATE_TO_SBER_STATUS.get(ha_status, "standby")
        attrs = ha_state.get("attributes", {})
        self._fan_speed = attrs.get("fan_speed")
        self._fan_speed_list = attrs.get("fan_speed_list") or []
        self._battery_level = self._safe_int(attrs.get("battery_level"))
        # cleaning_type from custom attribute (dry/wet/dry_and_wet)
        self._cleaning_type = attrs.get("cleaning_type")

    def create_features_list(self) -> list[str]:
        """Return Sber feature list for vacuum capabilities.

        Returns:
            List of Sber feature strings supported by this entity.
        """
        features = [
            *super().create_features_list(),
            "vacuum_cleaner_command",
            "vacuum_cleaner_status",
        ]
        if self._fan_speed_list:
            features.append("vacuum_cleaner_program")
        if self._cleaning_type is not None:
            features.append("vacuum_cleaner_cleaning_type")
        if self._battery_level is not None:
            features.append("battery_percentage")
        return features

    def create_allowed_values_list(self) -> dict[str, dict]:
        """Build allowed values map for vacuum features.

        Returns:
            Dict mapping feature key to its allowed ENUM values descriptor.
        """
        allowed: dict[str, dict] = {
            "vacuum_cleaner_command": {
                "type": "ENUM",
                "enum_values": {"values": list(_SBER_CMD_TO_HA_SERVICE.keys())},
            },
        }
        if self._fan_speed_list:
            allowed["vacuum_cleaner_program"] = {
                "type": "ENUM",
                "enum_values": {"values": self._fan_speed_list},
            }
        # vacuum_cleaner_status and vacuum_cleaner_cleaning_type are read-only:
        # not included in allowed_values to prevent Sber from sending commands
        # for features that have no HA service handler.
        return allowed

    def to_sber_current_state(self) -> dict[str, dict]:
        """Build Sber current state payload with vacuum attributes.

        Returns:
            Dict mapping entity_id to its Sber state representation.
        """
        states = [
            make_state(SberFeature.ONLINE, make_bool_value(self._is_online)),
            make_state(SberFeature.VACUUM_CLEANER_STATUS, make_enum_value(self._status)),
        ]
        if self._fan_speed:
            states.append(make_state(SberFeature.VACUUM_CLEANER_PROGRAM, make_enum_value(self._fan_speed)))
        if self._cleaning_type:
            states.append(
                make_state(SberFeature.VACUUM_CLEANER_CLEANING_TYPE, make_enum_value(self._cleaning_type))
            )
        if self._battery_level is not None:
            states.append(
                make_state(SberFeature.BATTERY_PERCENTAGE, make_integer_value(self._battery_level))
            )
        return {self.entity_id: {"states": states}}

    def process_cmd(self, cmd_data: dict) -> list[dict]:
        """Process Sber vacuum commands and produce HA service calls.

        Handles the following Sber keys:
        - ``vacuum_cleaner_command``: start/stop/pause/return_to_base
        - ``vacuum_cleaner_program``: vacuum.set_fan_speed

        Args:
            cmd_data: Sber command dict with 'states' list.

        Returns:
            List of HA service call dicts to execute.
        """
        results: list[dict] = []
        for item in cmd_data.get("states", []):
            key = item.get("key", "")
            value = item.get("value", {})
            if value.get("type") != SberValueType.ENUM:
                continue
            if key == SberFeature.VACUUM_CLEANER_COMMAND:
                ha_service = _SBER_CMD_TO_HA_SERVICE.get(value.get("enum_value") or "")
                if ha_service is None:
                    continue
                results.append(self._build_service_call("vacuum", ha_service, self.entity_id))
            elif key == SberFeature.VACUUM_CLEANER_PROGRAM:
                fan_speed = value.get("enum_value")
                if not fan_speed:
                    continue
                results.append(
                    self._build_service_call(
                        "vacuum", "set_fan_speed", self.entity_id, {"fan_speed": fan_speed}
                    )
                )
        return results
