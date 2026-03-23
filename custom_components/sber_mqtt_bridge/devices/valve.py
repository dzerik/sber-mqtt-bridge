"""Sber Valve entity -- maps HA valve entities to Sber valve category."""

from __future__ import annotations

import logging

from .on_off_entity import OnOffEntity

_LOGGER = logging.getLogger(__name__)

VALVE_CATEGORY = "valve"
"""Sber device category for valve entities."""


class ValveEntity(OnOffEntity):
    """Sber valve entity for open/close valve control.

    Maps HA valve entities to the Sber 'valve' category.
    Uses ``on_off`` feature where on=open and off=close.
    """

    _ha_on_state = "open"

    def __init__(self, entity_data: dict) -> None:
        """Initialize valve entity.

        Args:
            entity_data: HA entity registry dict containing entity metadata.
        """
        super().__init__(VALVE_CATEGORY, entity_data)

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
                results.append(
                    {
                        "url": {
                            "type": "call_service",
                            "domain": "valve",
                            "service": "open_valve" if on else "close_valve",
                            "target": {"entity_id": self.entity_id},
                        }
                    }
                )
        return results
