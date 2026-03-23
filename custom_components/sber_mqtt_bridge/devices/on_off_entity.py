"""Base class for Sber on/off entities (relay, valve, socket).

Provides shared implementations of ``fill_by_ha_state``, ``create_features_list``,
and ``to_sber_current_state`` for devices that expose a simple on/off state
via the Sber ``on_off`` feature.
"""

from __future__ import annotations

import logging

from .base_entity import BaseEntity

_LOGGER = logging.getLogger(__name__)


class OnOffEntity(BaseEntity):
    """Base class for on/off entities that expose the Sber 'on_off' feature.

    Subclasses must implement ``process_cmd`` to map Sber on/off commands
    to the appropriate HA service calls (e.g., ``turn_on``/``turn_off``
    for relays, ``open_valve``/``close_valve`` for valves).

    Subclasses may override ``_ha_on_state`` if the HA 'on' state string
    differs from the default ``"on"`` (e.g., ``"open"`` for valves).
    """

    current_state: bool
    """Current on/off state of the entity."""

    _ha_on_state: str = "on"
    """HA state string that corresponds to 'on' (override in subclass if needed)."""

    def __init__(self, category: str, entity_data: dict) -> None:
        """Initialize on/off entity.

        Args:
            category: Sber device category string.
            entity_data: HA entity registry dict containing entity metadata.
        """
        super().__init__(category, entity_data)
        self.current_state = False

    def fill_by_ha_state(self, ha_state: dict) -> None:
        """Parse HA state and update on/off status.

        Args:
            ha_state: HA state dict with 'state' and 'attributes' keys.
        """
        super().fill_by_ha_state(ha_state)
        self.current_state = ha_state.get("state") == self._ha_on_state

    def create_features_list(self) -> list[str]:
        """Return Sber feature list including 'on_off'.

        Returns:
            List of Sber feature strings supported by this entity.
        """
        return [*super().create_features_list(), "on_off"]

    def to_sber_current_state(self) -> dict[str, dict]:
        """Build Sber current state payload with online and on_off keys.

        Returns:
            Dict mapping entity_id to its Sber state representation.
        """
        states = [
            {"key": "online", "value": {"type": "BOOL", "bool_value": self._is_online}},
            {"key": "on_off", "value": {"type": "BOOL", "bool_value": self.current_state}},
        ]
        return {self.entity_id: {"states": states}}
