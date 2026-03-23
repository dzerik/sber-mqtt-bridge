"""Sber LED Strip entity -- maps HA light entities to Sber led_strip category.

Identical to light in features and behavior, but uses the ``led_strip``
Sber category for LED strip devices.
"""

from __future__ import annotations

import logging

from .light import LightEntity

_LOGGER = logging.getLogger(__name__)

LED_STRIP_CATEGORY = "led_strip"
"""Sber device category for LED strip entities."""


class LedStripEntity(LightEntity):
    """Sber LED strip entity.

    Inherits all light behavior (on/off, brightness, color, color temperature)
    but registers under the Sber 'led_strip' category.
    """

    def __init__(self, entity_data: dict) -> None:
        """Initialize LED strip entity.

        Args:
            entity_data: HA entity registry dict containing entity metadata.
        """
        super().__init__(entity_data)
        self.category = LED_STRIP_CATEGORY
