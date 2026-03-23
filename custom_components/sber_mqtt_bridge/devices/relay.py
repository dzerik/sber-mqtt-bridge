"""Sber Relay entity -- maps HA switch/script/button to Sber relay category."""

from __future__ import annotations

import logging

from .on_off_entity import OnOffEntity

logger = logging.getLogger(__name__)

RELAY_CATEGORY = "relay"
"""Sber device category for relay/switch entities."""


class RelayEntity(OnOffEntity):
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

                service = "press" if domain == "button" else "turn_on" if on else "turn_off"

                results.append(
                    {
                        "url": {
                            "type": "call_service",
                            "domain": domain,
                            "service": service,
                            "target": {"entity_id": self.entity_id},
                        }
                    }
                )
        return results
