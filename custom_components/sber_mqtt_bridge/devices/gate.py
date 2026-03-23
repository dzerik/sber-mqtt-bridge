"""Sber Gate entity -- maps HA cover (gate/garage_door) entities to Sber gate category."""

from __future__ import annotations

import logging

from .curtain import CurtainEntity

GATE_ENTITY_CATEGORY = "gate"
"""Sber device category for gate/garage door entities."""

_LOGGER = logging.getLogger(__name__)


class GateEntity(CurtainEntity):
    """Sber gate entity for gate/garage door control.

    Inherits all curtain functionality (position, open/close/stop) but uses
    the Sber 'gate' category instead of 'curtain'.

    Maps HA cover entities with device_class 'gate' or 'garage_door'.
    """

    def __init__(self, entity_data: dict) -> None:
        """Initialize gate entity.

        Args:
            entity_data: HA entity registry dict containing entity metadata.
        """
        super().__init__(entity_data, category=GATE_ENTITY_CATEGORY)
