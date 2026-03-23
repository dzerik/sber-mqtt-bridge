"""Sber Window Blind entity -- maps HA blind/shade/shutter covers to Sber window_blind."""

from __future__ import annotations

import logging

from .curtain import CurtainEntity

_LOGGER = logging.getLogger(__name__)

WINDOW_BLIND_CATEGORY = "window_blind"
"""Sber device category for window blind/shade/shutter entities."""


class WindowBlindEntity(CurtainEntity):
    """Sber window blind entity for blind/shade/shutter devices.

    Inherits all curtain behavior (position control, open/close/stop)
    but registers under the Sber 'window_blind' category.
    """

    def __init__(self, entity_data: dict) -> None:
        """Initialize window blind entity.

        Args:
            entity_data: HA entity registry dict containing entity metadata.
        """
        super().__init__(entity_data, category=WINDOW_BLIND_CATEGORY)
