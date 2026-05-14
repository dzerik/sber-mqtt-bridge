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

    async def async_update(self, entity_id: str, fields: dict[str, str | None]) -> dict[str, str]:
        """Update a redefinition entry and schedule a debounced persist.

        Applies ``fields`` to the in-memory store for ``entity_id``,
        strips whitespace from string values, and removes keys whose
        value resolves to an empty string or ``None``.  Schedules a
        debounced ConfigEntry write via :meth:`schedule_persist`.

        Note: The caller (bridge) is responsible for:
        - Checking whether ``entity_id`` exists in the loaded entities
          (raises ``KeyError`` before calling this method).
        - Triggering a config republish after this method returns.

        Args:
            entity_id: Target HA entity_id.
            fields: Mapping of redefinition keys (``home`` / ``room`` /
                ``name``) to new values; ``None`` or empty string clears
                a key. Unknown keys are silently ignored.

        Returns:
            The resulting redefinition dict for the entity (after the
            update is applied to the in-memory store but before the
            ConfigEntry persistence completes).
        """
        existing = dict(self._redefinitions.get(entity_id, {}))
        for key in ("name", "room", "home"):
            if key not in fields:
                continue
            raw = fields[key]
            value = raw.strip() if isinstance(raw, str) else ""
            if value:
                existing[key] = value
            else:
                existing.pop(key, None)
        self._redefinitions[entity_id] = existing
        self.schedule_persist()
        return dict(existing)

    def schedule_persist(self) -> None:
        """Mark the store dirty and arm/refresh the debounced flush timer."""
        self._dirty = True
        if self._timer is not None:
            self._timer.cancel()
        self._timer = self._bridge._hass.loop.call_later(
            _PERSIST_DEBOUNCE_SECONDS, self._flush
        )

    def _flush(self) -> None:
        """Persist the redefinitions to ``ConfigEntry.options`` if dirty.

        Called by the debounce timer. Side effect: updates ConfigEntry
        options so the next reload picks up the new redefinitions.
        """
        self._timer = None
        if not self._dirty:
            return
        self._dirty = False
        bridge = self._bridge
        new_options = {**bridge._entry.options, "redefinitions": self._redefinitions}
        bridge._hass.config_entries.async_update_entry(bridge._entry, options=new_options)
