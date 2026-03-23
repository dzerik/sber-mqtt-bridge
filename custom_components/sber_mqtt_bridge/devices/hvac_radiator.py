import logging

from .base_entity import BaseEntity
from .climate import ClimateEntity

logger = logging.getLogger(__name__)

HVAC_RADIATOR_CATEGORY = "hvac_radiator"


class HvacRadiatorEntity(ClimateEntity):

    def __init__(self, entity_data: dict):
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
