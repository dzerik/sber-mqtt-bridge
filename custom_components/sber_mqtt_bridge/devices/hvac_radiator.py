"""Sber HVAC Radiator entity -- maps HA radiator climate entities to Sber hvac_radiator."""

from __future__ import annotations

import logging

from .base_entity import BaseEntity
from .climate import ClimateEntity

logger = logging.getLogger(__name__)

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

        Calls ``BaseEntity.__init__`` directly to set the radiator category
        while preserving all climate behavior from ``ClimateEntity``.

        Args:
            entity_data: HA entity registry dict containing entity metadata.
        """
        BaseEntity.__init__(self, HVAC_RADIATOR_CATEGORY, entity_data)
        self.current_state = False
        self.temperature = None
        self.target_temperature = None
        self.fan_modes = []
        self.swing_modes = []
        self.hvac_modes = []
        self.fan_mode = None
        self.swing_mode = None
        self.hvac_mode = None
        self.min_temp = 25.0
        self.max_temp = 40.0
