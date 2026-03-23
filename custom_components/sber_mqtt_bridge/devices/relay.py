"""Sber Relay entity -- maps HA switch/script/button to Sber relay category."""

from __future__ import annotations

import logging

from .base_entity import BaseEntity

logger = logging.getLogger(__name__)

RELAY_CATEGORY = "relay"
"""Sber device category for relay/switch entities."""


class RelayEntity(BaseEntity):
    """Sber relay entity for on/off control devices.

    Maps HA switch, script, and button entities to the Sber 'relay' category.
    Supports basic on/off toggling via the ``on_off`` Sber feature.
    """

    def __init__(self, entity_data: dict) -> None:
        """Initialize relay entity.

        Args:
            entity_data: HA entity registry dict containing entity metadata.
        """
        super().__init__(RELAY_CATEGORY, entity_data)
        self.current_state = False

    def fill_by_ha_state(self, ha_state: dict) -> None:
        """Parse HA state and update on/off status.

        Args:
            ha_state: HA state dict with 'state' and 'attributes' keys.
        """
        super().fill_by_ha_state(ha_state)
        self.current_state = ha_state.get("state") == "on"

    def create_features_list(self) -> list[str]:
        """Return Sber feature list including 'on_off'.

        Returns:
            List of Sber feature strings supported by this entity.
        """
        return super().create_features_list() + ["on_off"]

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
        """Process Sber on/off command and produce HA service calls.

        Handles the ``on_off`` key to generate ``turn_on``/``turn_off`` (or
        ``press`` for button domain) service calls.

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
                domain = self.entity_id.split(".")[0]

                if domain == "button":
                    service = "press"
                else:
                    service = "turn_on" if on else "turn_off"

                results.append({"url": {
                    "type": "call_service",
                    "domain": domain,
                    "service": service,
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
