"""Sber Vacuum Cleaner entity -- maps HA vacuum entities to Sber vacuum_cleaner category.

Supports start/stop/pause/return_to_base commands, status reporting,
cleaning program (fan speed), and battery level.
"""

from __future__ import annotations

import logging

from .base_entity import BaseEntity

_LOGGER = logging.getLogger(__name__)

VACUUM_CLEANER_CATEGORY = "vacuum_cleaner"
"""Sber device category for vacuum cleaner entities."""

_HA_STATE_TO_SBER_STATUS: dict[str, str] = {
    "cleaning": "cleaning",
    "returning": "returning",
    "docked": "docked",
    "paused": "paused",
    "idle": "docked",
    "error": "error",
}
"""Mapping from HA vacuum state to Sber vacuum_cleaner_status ENUM."""

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

    def fill_by_ha_state(self, ha_state: dict) -> None:
        """Parse HA state and update vacuum cleaner attributes.

        Args:
            ha_state: HA state dict with 'state' and 'attributes' keys.
        """
        super().fill_by_ha_state(ha_state)
        ha_status = ha_state.get("state", "")
        self._status = _HA_STATE_TO_SBER_STATUS.get(ha_status, "docked")
        attrs = ha_state.get("attributes", {})
        self._fan_speed = attrs.get("fan_speed")
        self._fan_speed_list = attrs.get("fan_speed_list") or []
        self._battery_level = self._safe_int(attrs.get("battery_level"))

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
            "vacuum_cleaner_status": {
                "type": "ENUM",
                "enum_values": {"values": ["cleaning", "charging", "docked", "returning", "error", "paused"]},
            },
        }
        if self._fan_speed_list:
            allowed["vacuum_cleaner_program"] = {
                "type": "ENUM",
                "enum_values": {"values": self._fan_speed_list},
            }
        return allowed

    def to_sber_current_state(self) -> dict[str, dict]:
        """Build Sber current state payload with vacuum attributes.

        Returns:
            Dict mapping entity_id to its Sber state representation.
        """
        states = [
            {"key": "online", "value": {"type": "BOOL", "bool_value": self._is_online}},
            {"key": "vacuum_cleaner_status", "value": {"type": "ENUM", "enum_value": self._status}},
        ]
        if self._fan_speed:
            states.append({"key": "vacuum_cleaner_program", "value": {"type": "ENUM", "enum_value": self._fan_speed}})
        if self._battery_level is not None:
            states.append(
                {"key": "battery_percentage", "value": {"type": "INTEGER", "integer_value": str(self._battery_level)}}
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
            key = item.get("key")
            value = item.get("value", {})

            if key == "vacuum_cleaner_command" and value.get("type") == "ENUM":
                cmd = value.get("enum_value")
                ha_service = _SBER_CMD_TO_HA_SERVICE.get(cmd or "")
                if ha_service is None:
                    continue
                results.append(
                    {
                        "url": {
                            "type": "call_service",
                            "domain": "vacuum",
                            "service": ha_service,
                            "target": {"entity_id": self.entity_id},
                        }
                    }
                )

            elif key == "vacuum_cleaner_program" and value.get("type") == "ENUM":
                fan_speed = value.get("enum_value")
                if not fan_speed:
                    continue
                results.append(
                    {
                        "url": {
                            "type": "call_service",
                            "domain": "vacuum",
                            "service": "set_fan_speed",
                            "service_data": {"fan_speed": fan_speed},
                            "target": {"entity_id": self.entity_id},
                        }
                    }
                )
        return results
