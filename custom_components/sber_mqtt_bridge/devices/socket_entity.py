"""Sber Socket entity -- maps HA outlet switches to Sber socket category."""

from __future__ import annotations

import logging

from .on_off_entity import OnOffEntity
from .relay import RelayEntity

logger = logging.getLogger(__name__)

SOCKET_CATEGORY = "socket"
"""Sber device category for smart socket/outlet entities."""


class SocketEntity(RelayEntity):
    """Sber socket entity for smart outlet/plug devices.

    Inherits all relay behavior (on/off control) but registers under
    the Sber 'socket' category instead of 'relay'.
    """

    def __init__(self, entity_data: dict) -> None:
        """Initialize socket entity.

        Calls ``OnOffEntity.__init__`` directly (skipping ``RelayEntity``)
        to set the socket category while preserving relay behavior.

        Args:
            entity_data: HA entity registry dict containing entity metadata.
        """
        OnOffEntity.__init__(self, SOCKET_CATEGORY, entity_data)
