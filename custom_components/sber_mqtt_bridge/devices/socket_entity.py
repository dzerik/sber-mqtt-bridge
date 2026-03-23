import logging
from .relay import RelayEntity
from .base_entity import BaseEntity

logger = logging.getLogger(__name__)

SOCKET_CATEGORY = "socket"


class SocketEntity(RelayEntity):

    def __init__(self, entity_data: dict):
        BaseEntity.__init__(self, SOCKET_CATEGORY, entity_data)
        self.current_state = False
