"""Sber MQTT bridge — persisted device redefinitions store.

Owns the in-memory redefinitions dict and the debounced ConfigEntry
persistence flow extracted from :class:`SberBridge`. Bridge keeps
thin proxies for backward compatibility with the WS API, the command
dispatcher, and existing tests.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .sber_bridge import SberBridge

_LOGGER = logging.getLogger(__name__)

_PERSIST_DEBOUNCE_SECONDS = 2.0
"""How long to coalesce successive update_redefinition calls before
writing back to ConfigEntry.options. Mirrors the prior bridge value."""


class RedefinitionsStore:
    """Holds device redefinitions and debounces their persistence.

    Constructed with a back-reference to its parent :class:`SberBridge`
    so it can reach ``_hass`` (for the event loop) and ``_entry`` (for
    options persistence). The coupling is one-way and explicit.
    """

    def __init__(self, bridge: SberBridge) -> None:
        """Bind the store to its parent bridge.

        Args:
            bridge: The parent bridge whose ``_hass`` and ``_entry``
                this store reads.
        """
        self._bridge = bridge
        self._redefinitions: dict[str, dict] = {}
        self._dirty = False
        self._timer: asyncio.TimerHandle | None = None

    @property
    def redefinitions(self) -> dict[str, dict]:
        """Return a defensive shallow copy of the redefinitions dict."""
        return dict(self._redefinitions)

    @property
    def raw(self) -> dict[str, dict]:
        """Return the live dict (internal use only — for bridge proxies)."""
        return self._redefinitions

    @raw.setter
    def raw(self, value: dict[str, dict]) -> None:
        """Replace the live dict (used by entity loader on reload)."""
        self._redefinitions = value
