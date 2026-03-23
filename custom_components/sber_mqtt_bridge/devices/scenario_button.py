"""Sber Scenario Button entity -- maps HA input_boolean to Sber scenario_button."""

from __future__ import annotations

import logging

from .base_entity import BaseEntity

logger = logging.getLogger(__name__)

SCENARIO_BUTTON_CATEGORY = "scenario_button"
"""Sber device category for scenario button entities."""


class ScenarioButtonEntity(BaseEntity):
    """Sber scenario button entity.

    Maps HA input_boolean entities to the Sber 'scenario_button' category.
    Reports button events ('click' / 'double_click') based on the boolean state.
    """

    def __init__(self, entity_data: dict) -> None:
        """Initialize scenario button entity.

        Args:
            entity_data: HA entity registry dict containing entity metadata.
        """
        super().__init__(SCENARIO_BUTTON_CATEGORY, entity_data)
        self.button_event = "click"

    def fill_by_ha_state(self, ha_state: dict) -> None:
        """Parse HA state and update button event type.

        Maps 'on' to 'click' and anything else to 'double_click'.

        Args:
            ha_state: HA state dict with 'state' key.
        """
        super().fill_by_ha_state(ha_state)
        if ha_state.get("state") == "on":
            self.button_event = "click"
        else:
            self.button_event = "double_click"

    def create_features_list(self) -> list[str]:
        """Return Sber feature list including 'button_event'.

        Returns:
            List of Sber feature strings supported by this entity.
        """
        return super().create_features_list() + ["button_event"]

    def to_sber_current_state(self) -> dict[str, dict]:
        """Build Sber current state payload with online and button_event keys.

        Returns:
            Dict mapping entity_id to its Sber state representation.
        """
        is_online = self.state not in ("unavailable", "unknown", None)
        states = [
            {"key": "online", "value": {"type": "BOOL", "bool_value": is_online}},
            {"key": "button_event", "value": {"type": "ENUM", "enum_value": self.button_event}},
        ]
        return {self.entity_id: {"states": states}}

    def process_cmd(self, cmd_data: dict) -> list[dict]:
        """Process Sber command (no-op for scenario button).

        Args:
            cmd_data: Sber command dict (ignored).

        Returns:
            Empty list -- scenario buttons are read-only.
        """
        return []

    def process_state_change(self, old_state: dict | None, new_state: dict) -> None:
        """Handle HA state change event by refreshing internal state.

        Args:
            old_state: Previous HA state dict (unused).
            new_state: New HA state dict to apply.
        """
        self.fill_by_ha_state(new_state)
