"""Sber Vacuum Cleaner entity -- maps HA vacuum entities to Sber vacuum_cleaner category.

Supports start/stop/pause/return_to_base commands, status reporting,
cleaning program (fan speed), and battery level. Battery is sourced from
the deprecated HA vacuum ``battery_level`` attribute (legacy fallback,
removal planned in HA 2026.8) or from a linked battery sensor entity via
the ``battery`` link role.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Callable
from typing import ClassVar

from ..sber_constants import SberFeature, SberValueType
from ..sber_models import make_bool_value, make_enum_value, make_integer_value, make_state
from .base_entity import ROLE_BATTERY, AttrSpec, BaseEntity, CommandResult, _safe_int_parser

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
    - Battery percentage (legacy ``battery_level`` attribute or linked
      battery sensor via the ``battery`` link role)
    """

    LINKABLE_ROLES = (ROLE_BATTERY,)
    """Linked companion roles: a battery sensor supplies ``battery_percentage``.

    HA deprecated the vacuum ``battery_level`` attribute (removal in
    2026.8); migrated integrations expose battery as a separate sensor
    entity, which users link here.
    """

    ATTR_SPECS: ClassVar[tuple[AttrSpec, ...]] = (
        AttrSpec(
            field="_fan_speed",
            attr_keys=("fan_speed",),
        ),
        AttrSpec(
            field="_fan_speed_list",
            converter=lambda attrs: attrs.get("fan_speed_list") or [],
            default=[],
        ),
        AttrSpec(
            field="_battery_level",
            attr_keys=("battery_level",),
            parser=_safe_int_parser,
            preserve_on_missing=True,
        ),
        AttrSpec(
            field="_cleaning_type",
            attr_keys=("cleaning_type",),
        ),
    )

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
        attrs = ha_state.get("attributes", {})
        self._apply_attr_specs(attrs)
        ha_status = ha_state.get("state", "")
        self._status = _HA_STATE_TO_SBER_STATUS.get(ha_status, "standby")

    def update_linked_data(self, role: str, ha_state: dict) -> None:
        """Inject battery percentage from a linked battery sensor entity.

        HA deprecated the vacuum ``battery_level`` attribute; migrated
        integrations publish battery as a separate sensor entity. When
        such a sensor is linked with the ``battery`` role, its state
        feeds the Sber ``battery_percentage`` feature.

        Args:
            role: Link role name (only ``battery`` is handled).
            ha_state: HA state dict with 'state' containing the reading.
        """
        if role == "battery":
            state_val = ha_state.get("state")
            if state_val not in (None, "unknown", "unavailable"):
                with contextlib.suppress(TypeError, ValueError):
                    self._battery_level = int(float(state_val))

    def _create_features_list(self) -> list[str]:
        """Return Sber feature list for vacuum capabilities.

        Returns:
            List of Sber feature strings supported by this entity.
        """
        features = [
            *super()._create_features_list(),
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

    def _has_instance_allowed_values(self) -> bool:
        """Vacuum program list (fan_speed_list) varies per device.

        Devices sharing a model_id with different allowed_values get
        silently rejected by Sber cloud (issue #44 audit).
        """
        return bool(self._fan_speed_list)

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
            states.append(make_state(SberFeature.VACUUM_CLEANER_CLEANING_TYPE, make_enum_value(self._cleaning_type)))
        if self._battery_level is not None:
            states.append(make_state(SberFeature.BATTERY_PERCENTAGE, make_integer_value(self._battery_level)))
        return {self.entity_id: {"states": states}}

    @property
    def _cmd_handlers(self) -> dict[str, Callable[[dict], list[CommandResult]]]:
        """Return dispatch map for vacuum cleaner commands."""
        return {
            SberFeature.VACUUM_CLEANER_COMMAND: self._cmd_vacuum_command,
            SberFeature.VACUUM_CLEANER_PROGRAM: self._cmd_vacuum_program,
        }

    def _cmd_vacuum_command(self, value: dict) -> list[CommandResult]:
        """Handle ``vacuum_cleaner_command``: start/stop/pause/return_to_base.

        Args:
            value: Sber value dict from the command payload.

        Returns:
            List of HA service call dicts to execute.
        """
        if value.get("type") != SberValueType.ENUM:
            return []
        ha_service = _SBER_CMD_TO_HA_SERVICE.get(value.get("enum_value") or "")
        if ha_service is None:
            return []
        return [self._build_service_call("vacuum", ha_service, self.entity_id)]

    def _cmd_vacuum_program(self, value: dict) -> list[CommandResult]:
        """Handle ``vacuum_cleaner_program``: vacuum.set_fan_speed.

        Args:
            value: Sber value dict from the command payload.

        Returns:
            List of HA service call dicts to execute.
        """
        if value.get("type") != SberValueType.ENUM:
            return []
        fan_speed = value.get("enum_value")
        if not fan_speed:
            return []
        return [self._build_service_call("vacuum", "set_fan_speed", self.entity_id, {"fan_speed": fan_speed})]
