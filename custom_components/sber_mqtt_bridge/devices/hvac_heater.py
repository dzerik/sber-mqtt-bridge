"""Sber HVAC Heater entity -- maps HA heater climate entities to Sber hvac_heater."""

from __future__ import annotations

import logging

from .climate import ClimateEntity

_LOGGER = logging.getLogger(__name__)

HVAC_HEATER_CATEGORY = "hvac_heater"
"""Sber device category for heater climate entities."""


class HvacHeaterEntity(ClimateEntity):
    """Sber HVAC heater entity for space heater devices.

    Inherits all climate behavior but registers under the Sber
    'hvac_heater' category with heater-appropriate temperature
    defaults (5-40 C).
    """

    def __init__(self, entity_data: dict) -> None:
        """Initialize HVAC heater entity.

        Args:
            entity_data: HA entity registry dict containing entity metadata.
        """
        super().__init__(
            entity_data,
            category=HVAC_HEATER_CATEGORY,
            min_temp=5.0,
            max_temp=40.0,
        )
