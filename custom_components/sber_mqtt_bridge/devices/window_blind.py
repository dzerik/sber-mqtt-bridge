import logging
from .curtain import CurtainEntity
from .base_entity import BaseEntity

logger = logging.getLogger(__name__)

WINDOW_BLIND_CATEGORY = "window_blind"


class WindowBlindEntity(CurtainEntity):

    def __init__(self, entity_data: dict):
        BaseEntity.__init__(self, WINDOW_BLIND_CATEGORY, entity_data)
        self.current_position = 0
        self.min_position = 0
        self.max_position = 100
        self.battery_level = 0
        self._battery_level = 100
