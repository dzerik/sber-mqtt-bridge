"""Sber Socket entity -- maps HA outlet switches to Sber socket category."""

from __future__ import annotations

import logging

from .relay import RelayEntity

_LOGGER = logging.getLogger(__name__)

SOCKET_CATEGORY = "socket"
"""Sber device category for smart socket/outlet entities."""


class SocketEntity(RelayEntity):
    """Sber socket entity for smart outlet/plug devices.

    Inherits all relay behavior (on/off control) but registers under
    the Sber 'socket' category instead of 'relay'.
    """

    def __init__(self, entity_data: dict) -> None:
        """Initialize socket entity.

        Args:
            entity_data: HA entity registry dict containing entity metadata.
        """
        super().__init__(entity_data, category=SOCKET_CATEGORY)
