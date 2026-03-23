"""Sber Window Blind entity -- maps HA blind/shade/shutter covers to Sber window_blind."""

from __future__ import annotations

import logging

from .base_entity import BaseEntity
from .curtain import CurtainEntity

logger = logging.getLogger(__name__)

WINDOW_BLIND_CATEGORY = "window_blind"
"""Sber device category for window blind/shade/shutter entities."""


class WindowBlindEntity(CurtainEntity):
    """Sber window blind entity for blind/shade/shutter devices.

    Inherits all curtain behavior (position control, open/close/stop)
    but registers under the Sber 'window_blind' category.
    """

    def __init__(self, entity_data: dict) -> None:
        """Initialize window blind entity.

        Calls ``BaseEntity.__init__`` directly to set the window_blind
        category while preserving all curtain behavior from ``CurtainEntity``.

        Args:
            entity_data: HA entity registry dict containing entity metadata.
        """
        BaseEntity.__init__(self, WINDOW_BLIND_CATEGORY, entity_data)
        self.current_position = 0
        self.min_position = 0
        self.max_position = 100
        self.battery_level = 0
        self._battery_level = 100
