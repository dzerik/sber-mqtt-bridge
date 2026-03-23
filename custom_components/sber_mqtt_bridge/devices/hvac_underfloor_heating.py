"""Sber HVAC Underfloor Heating entity -- maps HA underfloor heating climate entities."""

from __future__ import annotations

import logging

from .climate import ClimateEntity

_LOGGER = logging.getLogger(__name__)

HVAC_UNDERFLOOR_CATEGORY = "hvac_underfloor_heating"
"""Sber device category for underfloor heating entities."""


class HvacUnderfloorEntity(ClimateEntity):
    """Sber HVAC underfloor heating entity.

    Inherits all climate behavior but registers under the Sber
    'hvac_underfloor_heating' category with underfloor-appropriate
    temperature defaults (25-50 C).
    """

    def __init__(self, entity_data: dict) -> None:
        """Initialize HVAC underfloor heating entity.

        Args:
            entity_data: HA entity registry dict containing entity metadata.
        """
        super().__init__(
            entity_data,
            category=HVAC_UNDERFLOOR_CATEGORY,
            min_temp=25.0,
            max_temp=50.0,
        )
