"""Sber HVAC Boiler entity -- maps HA water heater climate entities to Sber hvac_boiler."""

from __future__ import annotations

import logging

from .climate import ClimateEntity

_LOGGER = logging.getLogger(__name__)

HVAC_BOILER_CATEGORY = "hvac_boiler"
"""Sber device category for boiler/water heater entities."""


class HvacBoilerEntity(ClimateEntity):
    """Sber HVAC boiler entity for water heater devices.

    Inherits all climate behavior but registers under the Sber
    'hvac_boiler' category with boiler-appropriate temperature
    defaults (25-80 C).
    """

    def __init__(self, entity_data: dict) -> None:
        """Initialize HVAC boiler entity.

        Args:
            entity_data: HA entity registry dict containing entity metadata.
        """
        super().__init__(
            entity_data,
            category=HVAC_BOILER_CATEGORY,
            min_temp=25.0,
            max_temp=80.0,
        )
