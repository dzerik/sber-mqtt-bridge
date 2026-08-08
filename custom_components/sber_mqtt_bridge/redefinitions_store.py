"""Sber MQTT bridge — persisted device redefinitions store.

Owns the in-memory redefinitions dict and the debounced ConfigEntry
persistence flow extracted from :class:`SberBridge`. The command
dispatcher holds the store directly; the bridge keeps a read-only
``_redefinitions`` proxy for the WS API and existing tests.

The store depends only on the two HA objects it actually needs — the
core (for the event loop) and the config entry (for options persistence)
— never on the bridge that owns it.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

_PERSIST_DEBOUNCE_SECONDS = 2.0
"""How long to coalesce successive update_redefinition calls before
writing back to ConfigEntry.options. Mirrors the prior bridge value."""


class RedefinitionsStore:
    """Holds device redefinitions and debounces their persistence.

    Constructed with the HA core and the owning config entry; it never
    sees the bridge, so bridge internals can move freely.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Bind the store to its HA context.

        Args:
            hass: HA core — used for the event loop (debounce timer) and
                for ``config_entries.async_update_entry``.
            entry: Config entry whose ``options`` hold the persisted
                redefinitions snapshot.
        """
        self._hass = hass
        self._entry = entry
        self._redefinitions: dict[str, dict] = {}
        self._dirty = False
        self._timer: asyncio.TimerHandle | None = None
        self._stopped = False

    @property
    def redefinitions(self) -> dict[str, dict]:
        """Return a defensive shallow copy of the redefinitions dict."""
        return dict(self._redefinitions)

    @property
    def raw(self) -> dict[str, dict]:
        """Return the live dict (read-only view for bridge proxies).

        Deliberately getter-only: :meth:`replace` is the single write
        path for the whole map, so there is no second way to swap it.
        """
        return self._redefinitions

    def has(self, entity_id: str) -> bool:
        """Return True when a redefinition record exists for ``entity_id``.

        Lets callers probe the store without borrowing the live dict.
        """
        return entity_id in self._redefinitions

    def replace(self, values: dict[str, dict]) -> None:
        """Swap the whole redefinitions map (entity reload path).

        Does not mark the store dirty: the incoming map comes *from*
        persisted options, so re-persisting it would be a no-op write.

        The caller must hand over ownership of ``values``: the store
        keeps the mapping it was given and mutates it in place from
        :meth:`async_update`, so a caller that keeps its own alias will
        observe those writes.  No aliasing guarantee is offered in the
        other direction — do not rely on mutating ``values`` afterwards
        to update the store.

        Args:
            values: New ``entity_id → fields`` mapping, built by the
                entity loader from persisted options.
        """
        self._redefinitions = values

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
        """Mark the store dirty and arm/refresh the debounced flush timer.

        After :meth:`shutdown` this becomes a no-op (aside from marking
        dirty): a stopped store must never arm a timer that could write
        stale options after the config entry has been unloaded and a
        newer bridge instance owns the entry.
        """
        self._dirty = True
        if self._stopped:
            _LOGGER.warning("Redefinitions store already shut down — dropping persist request")
            return
        if self._timer is not None:
            self._timer.cancel()
        self._timer = self._hass.loop.call_later(_PERSIST_DEBOUNCE_SECONDS, self._flush)

    def flush_now(self) -> None:
        """Cancel the pending debounce timer and persist immediately.

        Public API for teardown paths (:meth:`SberBridge.async_stop`)
        and anyone who cannot wait out the debounce window. No-op when
        the store is not dirty.
        """
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        self._flush()

    def shutdown(self) -> None:
        """Finalize the store: flush pending changes, stop all timers.

        Idempotent. After this call no new debounce timers are armed
        (see :meth:`schedule_persist`), so a timer from a dying bridge
        instance can never overwrite options written by its successor.
        """
        self._stopped = True
        self.flush_now()

    def _flush(self) -> None:
        """Persist the redefinitions to ``ConfigEntry.options`` if dirty.

        Called by the debounce timer. Side effect: updates ConfigEntry
        options so the next reload picks up the new redefinitions.
        Persists a per-entity copy so later in-memory mutations cannot
        silently alter the already-written options snapshot.
        """
        self._timer = None
        if not self._dirty:
            return
        self._dirty = False
        snapshot = {entity_id: dict(fields) for entity_id, fields in self._redefinitions.items()}
        new_options = {**self._entry.options, "redefinitions": snapshot}
        self._hass.config_entries.async_update_entry(self._entry, options=new_options)
