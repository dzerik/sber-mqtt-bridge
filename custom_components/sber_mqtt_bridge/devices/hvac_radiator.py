"""Sber HVAC Radiator entity -- maps HA radiator climate entities to Sber hvac_radiator."""

from __future__ import annotations

import logging

from .climate import ClimateEntity

_LOGGER = logging.getLogger(__name__)

HVAC_RADIATOR_CATEGORY = "hvac_radiator"
"""Sber device category for radiator/heater climate entities."""


class HvacRadiatorEntity(ClimateEntity):
    """Sber HVAC radiator entity for heating devices.

    Inherits all climate behavior but registers under the Sber
    'hvac_radiator' category with radiator-appropriate temperature
    defaults (25-40 C).
    """

    def __init__(self, entity_data: dict) -> None:
        """Initialize HVAC radiator entity.

        Args:
            entity_data: HA entity registry dict containing entity metadata.
        """
        super().__init__(
            entity_data,
            category=HVAC_RADIATOR_CATEGORY,
            min_temp=25.0,
            max_temp=40.0,
        )
