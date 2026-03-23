"""Base class for read-only Sber sensors with a single value feature.

Provides shared implementations of ``process_cmd``,
``create_features_list``, and ``to_sber_current_state`` so that concrete
sensor subclasses only need to define how their value is extracted and
formatted for the Sber protocol.
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

        Returns:
            List of Sber feature strings supported by this entity.
        """
        return [*super().create_features_list(), self._sber_value_key]

    def to_sber_current_state(self) -> dict[str, dict]:
        """Build Sber current state payload with online and value keys.

        Returns:
            Dict mapping entity_id to its Sber state representation.
        """
        states = [
            {"key": "online", "value": {"type": "BOOL", "bool_value": self._is_online}},
            {"key": self._sber_value_key, "value": self._build_sber_value_dict()},
        ]
        return {self.entity_id: {"states": states}}

    def process_cmd(self, cmd_data: dict) -> list[dict]:
        """Process Sber command (no-op for read-only sensor).

        Args:
            cmd_data: Sber command dict (ignored).

        Returns:
            Empty list -- sensors do not accept commands.
        """
        return []
