"""Sber Valve entity -- maps HA valve entities to Sber valve category."""

from __future__ import annotations

import logging

from .base_entity import BaseEntity

logger = logging.getLogger(__name__)

VALVE_CATEGORY = "valve"
"""Sber device category for valve entities."""


class ValveEntity(BaseEntity):
    """Sber valve entity for open/close valve control.

    Maps HA valve entities to the Sber 'valve' category.
    Uses ``on_off`` feature where on=open and off=close.
    """

    def __init__(self, entity_data: dict) -> None:
        """Initialize valve entity.

        Args:
            entity_data: HA entity registry dict containing entity metadata.
        """
        super().__init__(VALVE_CATEGORY, entity_data)
        self.current_state = False

    def fill_by_ha_state(self, ha_state: dict) -> None:
        """Parse HA state and update open/close status.

        Args:
            ha_state: HA state dict; 'open' means valve is open.
        """
        super().fill_by_ha_state(ha_state)
        self.current_state = ha_state.get("state") == "open"

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
        is_online = self.state not in ("unavailable", "unknown", None)
        states = [
            {"key": "online", "value": {"type": "BOOL", "bool_value": is_online}},
            {"key": "on_off", "value": {"type": "BOOL", "bool_value": self.current_state}},
        ]
        return {self.entity_id: {"states": states}}

    def process_cmd(self, cmd_data: dict) -> list[dict]:
        """Process Sber on/off command and produce HA valve service calls.

        Maps ``on_off=True`` to ``open_valve`` and ``on_off=False`` to
        ``close_valve``.

        Args:
            cmd_data: Sber command dict with 'states' list.

        Returns:
            List of HA service call dicts to execute.
        """
        results = []
        for item in cmd_data.get("states", []):
            key = item.get("key")
            value = item.get("value", {})

            if key == "on_off" and value.get("type") == "BOOL":
                on = value.get("bool_value", False)
                self.current_state = on
                results.append({"url": {
                    "type": "call_service",
                    "domain": "valve",
                    "service": "open_valve" if on else "close_valve",
                    "target": {"entity_id": self.entity_id}
                }})
        return results

    def process_state_change(self, old_state: dict | None, new_state: dict) -> None:
        """Handle HA state change event by refreshing internal state.

        Args:
            old_state: Previous HA state dict (unused).
            new_state: New HA state dict to apply.
        """
        self.fill_by_ha_state(new_state)
