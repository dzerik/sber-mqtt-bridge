"""Sber Relay entity -- maps HA switch/script/button to Sber relay category."""

from __future__ import annotations

import logging
from collections.abc import Callable

from ..sber_constants import (
    SERVICE_PRESS,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    SberFeature,
    SberValueType,
)
from .base_entity import CommandResult
from .on_off_entity import OnOffEntity

_LOGGER = logging.getLogger(__name__)

RELAY_CATEGORY = "relay"
"""Sber device category for relay/switch entities."""


class RelayEntity(OnOffEntity):
    """Sber relay entity for on/off control devices.

    Maps HA switch, script, and button entities to the Sber 'relay' category.
    Supports basic on/off toggling via the ``on_off`` Sber feature.
    """

    def __init__(self, entity_data: dict, category: str = RELAY_CATEGORY) -> None:
        """Initialize relay entity.

        Args:
            entity_data: HA entity registry dict containing entity metadata.
            category: Sber device category (override in subclasses).
        """
        super().__init__(category, entity_data)

    @property
    def _cmd_handlers(self) -> dict[str, Callable[[dict], list[CommandResult]]]:
        """Return dispatch map for relay commands."""
        return {SberFeature.ON_OFF: self._cmd_on_off}

    def _cmd_on_off(self, value: dict) -> list[CommandResult]:
        """Handle ``on_off``: turn_on / turn_off (or press for button domain).

        Args:
            value: Sber value dict from the command payload.

        Returns:
            List of HA service call dicts to execute.
        """
        if value.get("type") != SberValueType.BOOL:
            return []
        on = value.get("bool_value", False)
        domain = self.entity_id.split(".", 1)[0]
        service = SERVICE_PRESS if domain == "button" else SERVICE_TURN_ON if on else SERVICE_TURN_OFF
        return [self._build_service_call(domain, service, self.entity_id)]
