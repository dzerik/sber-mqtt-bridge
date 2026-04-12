"""Sber Valve entity -- maps HA valve entities to Sber valve category.

Uses ``open_set``/``open_state`` features (NOT ``on_off``).
Per Sber specification, valve is controlled via ENUM open/close/stop commands.
Supports optional battery and signal strength reporting.
"""

from __future__ import annotations

import contextlib
import logging
from typing import ClassVar

from ..sber_constants import SberFeature, SberValueType
from ..sber_models import make_bool_value, make_enum_value, make_integer_value, make_state
from .base_entity import (
    SENSOR_LINK_ROLES,
    AttrSpec,
    BaseEntity,
    CommandResult,
    _safe_int_parser,
)
from .utils.signal import rssi_to_signal_strength

_LOGGER = logging.getLogger(__name__)

VALVE_CATEGORY = "valve"
"""Sber device category for valve entities."""

_VALVE_OPEN_SET_SERVICES: dict[str, str] = {
    "open": "open_valve",
    "close": "close_valve",
    "stop": "stop_valve",
}
"""Map Sber ``open_set`` ENUM values to HA valve services."""


class ValveEntity(BaseEntity):
    """Sber valve entity for open/close valve control.

    Maps HA valve entities to the Sber 'valve' category.
    Uses ``open_set`` (command) and ``open_state`` (state) features
    per Sber specification. Does NOT use ``on_off``.

    Optionally reports ``battery_percentage``, ``battery_low_power``,
    and ``signal_strength`` when the HA entity provides these attributes.
    """

    LINKABLE_ROLES = SENSOR_LINK_ROLES

    ATTR_SPECS: ClassVar[tuple[AttrSpec, ...]] = (
        AttrSpec(
            field="_battery_level",
            attr_keys=("battery", "battery_level"),
            parser=_safe_int_parser,
        ),
        AttrSpec(
            field="_signal_strength_raw",
            attr_keys=("signal_strength", "rssi", "linkquality"),
            parser=_safe_int_parser,
        ),
    )

    def __init__(self, entity_data: dict) -> None:
        """Initialize valve entity.

        Args:
            entity_data: HA entity registry dict containing entity metadata.
        """
        super().__init__(VALVE_CATEGORY, entity_data)
        self.is_open: bool = False
        self._battery_level: int | None = None
        self._battery_low: bool | None = None
        self._signal_strength_raw: int | None = None

    def fill_by_ha_state(self, ha_state: dict) -> None:
        """Parse HA state and update open/close status, battery, and signal.

        Args:
            ha_state: HA state dict with 'state' and 'attributes' keys.
        """
        super().fill_by_ha_state(ha_state)
        self.is_open = ha_state.get("state") == "open"
        self._apply_attr_specs(ha_state.get("attributes", {}))

    def update_linked_data(self, role: str, ha_state: dict) -> None:
        """Inject data from a linked entity (battery, battery_low, signal).

        Args:
            role: Link role name.
            ha_state: HA state dict with 'state'.
        """
        state_val = ha_state.get("state")
        if state_val in (None, "unknown", "unavailable"):
            return
        if role == "battery":
            with contextlib.suppress(TypeError, ValueError):
                self._battery_level = int(float(state_val))
        elif role == "battery_low":
            self._battery_low = state_val == "on"
        elif role == "signal_strength":
            with contextlib.suppress(TypeError, ValueError):
                self._signal_strength_raw = int(float(state_val))

    def create_features_list(self) -> list[str]:
        """Return Sber feature list with open_set, open_state, open_percentage and optional battery/signal.

        ``open_percentage`` is marked obligatory for ``valve`` by Sber docs
        (✔︎ in the "Доступные функции устройства" table).  HA valves are
        binary (open/close), so we derive 0/100 from :attr:`is_open`.

        Returns:
            List of Sber feature strings supported by this entity.
        """
        features = [*super().create_features_list(), "open_set", "open_state", "open_percentage"]
        if self._battery_level is not None or self._battery_low is not None:
            features.append("battery_percentage")
            features.append("battery_low_power")
        if self._signal_strength_raw is not None:
            features.append("signal_strength")
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
        if self._battery_level is not None:
            states.append(make_state(SberFeature.BATTERY_PERCENTAGE, make_integer_value(self._battery_level)))
            battery_low = self._battery_low if self._battery_low is not None else self._battery_level < 20
            states.append(make_state(SberFeature.BATTERY_LOW_POWER, make_bool_value(battery_low)))
        elif self._battery_low is not None:
            states.append(make_state(SberFeature.BATTERY_LOW_POWER, make_bool_value(self._battery_low)))
        if self._signal_strength_raw is not None:
            states.append(
                make_state(
                    SberFeature.SIGNAL_STRENGTH, make_enum_value(rssi_to_signal_strength(self._signal_strength_raw))
                )
            )
        return {self.entity_id: {"states": states}}

    def process_cmd(self, cmd_data: dict) -> list[CommandResult]:
        """Process Sber open_set command and produce HA valve service calls.

        Maps ``open_set`` ENUM values:
        - ``"open"`` -> ``open_valve``
        - ``"close"`` -> ``close_valve``
        - ``"stop"`` -> ``stop_valve``

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
            if key != SberFeature.OPEN_SET or value.get("type") != SberValueType.ENUM:
                continue
            service = _VALVE_OPEN_SET_SERVICES.get(value.get("enum_value") or "")
            if service is None:
                continue
            results.append(self._build_service_call("valve", service, self.entity_id))
        return results
