"""Base class for read-only Sber sensors with a single value feature.

Provides shared implementations of ``process_cmd``,
``create_features_list``, and ``to_sber_current_state`` so that concrete
sensor subclasses only need to define how their value is extracted and
formatted for the Sber protocol.

Supports optional ``battery_percentage`` feature when the HA entity
reports battery level via attributes.
"""

from __future__ import annotations

import logging
from abc import abstractmethod
from typing import ClassVar

from .base_entity import BaseEntity

_LOGGER = logging.getLogger(__name__)


class SimpleReadOnlySensor(BaseEntity):
    """Base class for read-only sensors that expose a single Sber feature.

    Subclasses must define the class-level attributes ``_sber_value_key``
    and ``_sber_value_type``, and implement ``_get_sber_value`` to return
    the current sensor value in the appropriate Sber format.

    Optionally reports ``battery_percentage`` when the HA entity has
    a ``battery`` or ``battery_level`` attribute.
    """

    _sber_value_key: str
    """Sber state key name (e.g., 'temperature', 'pir', 'water_leak')."""

    _sber_value_type: str
    """Sber value type string: 'INTEGER', 'BOOL', or 'ENUM'."""

    _TYPE_KEY_MAP: ClassVar[dict[str, str]] = {
        "INTEGER": "integer_value",
        "BOOL": "bool_value",
        "ENUM": "enum_value",
    }
    """Mapping from Sber value type to its JSON field name."""

    @abstractmethod
    def _get_sber_value(self) -> int | bool | str:
        """Return the current sensor value formatted for the Sber protocol.

        Returns:
            The value matching ``_sber_value_type``:
            ``int`` for INTEGER, ``bool`` for BOOL, ``str`` for ENUM.
        """

    def __init__(self, category: str, entity_data: dict) -> None:
        """Initialize simple read-only sensor.

        Args:
            category: Sber device category string.
            entity_data: HA entity registry dict containing entity metadata.
        """
        super().__init__(category, entity_data)
        self._battery_level: int | None = None

    def fill_by_ha_state(self, ha_state: dict) -> None:
        """Parse HA state and update internal state including battery level.

        Reads battery level from ``battery`` or ``battery_level`` attribute.

        Args:
            ha_state: HA state dict with 'state' and 'attributes' keys.
        """
        super().fill_by_ha_state(ha_state)
        attrs = ha_state.get("attributes", {})
        battery = attrs.get("battery") or attrs.get("battery_level")
        if battery is not None:
            try:
                self._battery_level = int(battery)
            except (TypeError, ValueError):
                self._battery_level = None
        else:
            self._battery_level = None

    def _build_sber_value_dict(self) -> dict:
        """Build the Sber value dict for the sensor's feature.

        Per Sber C2C specification, ``integer_value`` must be a string.

        Returns:
            Dict with 'type' and the corresponding value field.
        """
        value = self._get_sber_value()
        value_field = self._TYPE_KEY_MAP[self._sber_value_type]
        if self._sber_value_type == "INTEGER":
            value = str(value)
        return {"type": self._sber_value_type, value_field: value}

    def create_features_list(self) -> list[str]:
        """Return Sber feature list including the sensor's value key.

        Adds ``battery_percentage`` if battery level is available.

        Returns:
            List of Sber feature strings supported by this entity.
        """
        features = [*super().create_features_list(), self._sber_value_key]
        if self._battery_level is not None:
            features.append("battery_percentage")
        return features

    def to_sber_current_state(self) -> dict[str, dict]:
        """Build Sber current state payload with online, value, and battery keys.

        Returns:
            Dict mapping entity_id to its Sber state representation.
        """
        states = [
            {"key": "online", "value": {"type": "BOOL", "bool_value": self._is_online}},
            {"key": self._sber_value_key, "value": self._build_sber_value_dict()},
        ]
        if self._battery_level is not None:
            states.append(
                {"key": "battery_percentage", "value": {"type": "INTEGER", "integer_value": str(self._battery_level)}}
            )
        return {self.entity_id: {"states": states}}

    def process_cmd(self, cmd_data: dict) -> list[dict]:
        """Process Sber command (no-op for read-only sensor).

        Args:
            cmd_data: Sber command dict (ignored).

        Returns:
            Empty list -- sensors do not accept commands.
        """
        return []
