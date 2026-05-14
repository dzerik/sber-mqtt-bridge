"""Sber Valve entity -- maps HA valve entities to Sber valve category.

Uses ``open_set``/``open_state`` features (NOT ``on_off``).
Per Sber specification, valve is controlled via ENUM open/close/stop commands.
Supports optional battery and signal strength reporting.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import ClassVar

from ..sber_constants import SberFeature, SberValueType
from ..sber_models import make_bool_value, make_enum_value, make_integer_value, make_state
from .base_entity import (
    SENSOR_LINK_ROLES,
    AttrSpec,
    BaseEntity,
    CommandResult,
)
from .battery_signal_mixin import BATTERY_SIGNAL_ATTR_SPECS, BatteryAndSignalLinkMixin

_LOGGER = logging.getLogger(__name__)

VALVE_CATEGORY = "valve"
"""Sber device category for valve entities."""

_VALVE_OPEN_SET_SERVICES: dict[str, str] = {
    "open": "open_valve",
    "close": "close_valve",
    "stop": "stop_valve",
}
"""Map Sber ``open_set`` ENUM values to HA valve services."""


class ValveEntity(BatteryAndSignalLinkMixin, BaseEntity):
    """Sber valve entity for open/close valve control.

    Maps HA valve entities to the Sber 'valve' category.
    Uses ``open_set`` (command) and ``open_state`` (state) features
    per Sber specification. Does NOT use ``on_off``.

    Optionally reports ``battery_percentage``, ``battery_low_power``,
    and ``signal_strength`` when the HA entity provides these attributes.
    """

    LINKABLE_ROLES = SENSOR_LINK_ROLES

    ATTR_SPECS: ClassVar[tuple[AttrSpec, ...]] = (*BATTERY_SIGNAL_ATTR_SPECS,)

    def __init__(self, entity_data: dict) -> None:
        """Initialize valve entity.

        Args:
            entity_data: HA entity registry dict containing entity metadata.
        """
        super().__init__(VALVE_CATEGORY, entity_data)
        self.is_open: bool = False

    def fill_by_ha_state(self, ha_state: dict) -> None:
        """Parse HA state and update open/close status, battery, and signal.

        Args:
            ha_state: HA state dict with 'state' and 'attributes' keys.
        """
        super().fill_by_ha_state(ha_state)
        self.is_open = ha_state.get("state") == "open"
        self._apply_attr_specs(ha_state.get("attributes", {}))

    def _create_features_list(self) -> list[str]:
        """Return Sber feature list with open_set, open_state, open_percentage and optional battery/signal.

        ``open_percentage`` is marked obligatory for ``valve`` by Sber docs
        (✔︎ in the "Доступные функции устройства" table).  HA valves are
        binary (open/close), so we derive 0/100 from :attr:`is_open`.

        Returns:
            List of Sber feature strings supported by this entity.
        """
        features = [*super()._create_features_list(), "open_set", "open_state", "open_percentage"]
        self._append_battery_signal_features(features)
        return features

    def create_allowed_values_list(self) -> dict[str, dict]:
        """Return allowed values for the open_set feature."""
        return {
            "open_set": {
                "type": "ENUM",
                "enum_values": {"values": ["open", "close", "stop"]},
            },
        }

    def to_sber_current_state(self) -> dict[str, dict]:
        """Build Sber current state payload with online, open_state, battery, and signal.

        Returns:
            Dict mapping entity_id to its Sber state representation.
        """
        states = [
            make_state(SberFeature.ONLINE, make_bool_value(self._is_online)),
            make_state(SberFeature.OPEN_STATE, make_enum_value("open" if self.is_open else "close")),
            make_state(SberFeature.OPEN_PERCENTAGE, make_integer_value(100 if self.is_open else 0)),
        ]
        self._append_battery_signal_states(states)
        return {self.entity_id: {"states": states}}

    @property
    def _cmd_handlers(self) -> dict[str, Callable[[dict], list[CommandResult]]]:
        """Return dispatch map for valve commands."""
        return {SberFeature.OPEN_SET: self._cmd_open_set}

    def _cmd_open_set(self, value: dict) -> list[CommandResult]:
        """Handle ``open_set``: open_valve / close_valve / stop_valve.

        Maps ``open_set`` ENUM values:
        - ``"open"`` -> ``open_valve``
        - ``"close"`` -> ``close_valve``
        - ``"stop"`` -> ``stop_valve``

        State is NOT mutated here -- it will be updated when HA fires a
        ``state_changed`` event that is handled by ``fill_by_ha_state``.

        Args:
            value: Sber value dict from the command payload.

        Returns:
            List of HA service call dicts to execute.
        """
        if value.get("type") != SberValueType.ENUM:
            return []
        service = _VALVE_OPEN_SET_SERVICES.get(value.get("enum_value") or "")
        if service is None:
            return []
        return [self._build_service_call("valve", service, self.entity_id)]
