"""State-payload diff collector for DevTools.

For every Sber state publish we compare the ``{key → value}`` mapping
of each device against the previously published mapping for the same
device and keep only the delta — *added*, *removed*, and *changed*
entries.  Sber state payloads are chatty (every publish re-sends every
feature value for every affected device), so the raw MQTT log buries
the actual change in noise; this collector turns each publish into a
compact "what actually changed" record that DevTools can render in one
line per feature.

Design notes:
    * Like :class:`MessageLogger` / :class:`TraceCollector`, the store
      is an in-memory ring buffer with subscribe fan-out — same memory
      envelope, same panel-facing API shape.
    * Empty deltas (publish where nothing changed for a device) are
      dropped, so the log only surfaces publishes that matter.
    * ``_last_by_entity`` keeps the rolling baseline; it survives
      collector-level :meth:`clear` but is reset alongside entity data
      so stale baselines don't produce phantom "removed" entries.
"""

from __future__ import annotations

import copy
import logging
import time
from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from typing import Any

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class StateDiff:
    """Delta between two consecutive Sber state payloads for one device."""

    ts: float
    entity_id: str
    topic: str
    added: dict[str, Any] = field(default_factory=dict)
    removed: dict[str, Any] = field(default_factory=dict)
    changed: dict[str, dict[str, Any]] = field(default_factory=dict)
    """changed[key] = {"before": value, "after": value}"""
    is_initial: bool = False
    """True when this is the first publish ever seen for the entity —
    every key appears under ``added`` and consumers may choose to hide it."""

    @property
    def is_empty(self) -> bool:
        """True when nothing changed compared to the previous publish."""
        return not self.added and not self.removed and not self.changed

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""
        return asdict(self)


class DiffCollector:
    """In-memory ring buffer of recent state diffs with live subscribers.

    The collector is pure Python and HA-independent — callers drive it
    via :meth:`update` and :meth:`reset_entity`; the bridge wires it
    into the publish path.
    """

    def __init__(self, maxlen: int = 200, *, include_initial: bool = False) -> None:
        """Initialize a collector.

        Args:
            maxlen: Ring-buffer size for stored diffs.
            include_initial: Whether the very first publish for an
                entity should produce a diff (with every key under
                ``added``).  Off by default — the initial publish is
                rarely interesting and would otherwise spam the UI
                on startup.
        """
        self._diffs: deque[StateDiff] = deque(maxlen=maxlen)
        self._last_by_entity: dict[str, dict[str, Any]] = {}
        self._subscribers: set[Callable[[StateDiff], None]] = set()
        self._include_initial = include_initial

    # ------------------------------------------------------------------
    # Properties / config
    # ------------------------------------------------------------------

    @property
    def maxlen(self) -> int | None:
        """Return ring-buffer capacity."""
        return self._diffs.maxlen

    def resize(self, new_maxlen: int) -> None:
        """Resize the ring buffer, keeping the newest entries."""
        if new_maxlen == self._diffs.maxlen:
            return
        old = list(self._diffs)
        self._diffs = deque(old[-new_maxlen:], maxlen=new_maxlen)

    # ------------------------------------------------------------------
    # Snapshot / clear
    # ------------------------------------------------------------------

    def snapshot(self) -> list[dict[str, Any]]:
        """Return all stored diffs as JSON-serializable dicts, oldest first."""
        return [d.as_dict() for d in self._diffs]

    def clear(self) -> None:
        """Drop all stored diffs and the per-entity baseline."""
        self._diffs.clear()
        self._last_by_entity.clear()

    def reset_entity(self, entity_id: str) -> None:
        """Forget the baseline for one entity (e.g. when it's removed).

        A subsequent :meth:`update` will treat the entity as brand new.
        """
        self._last_by_entity.pop(entity_id, None)

    def get_last_state(self, entity_id: str) -> dict[str, Any] | None:
        """Return the baseline (key→value) dict for an entity, if any.

        Returned dict is a deep copy so callers can't mutate the baseline.
        """
        snap = self._last_by_entity.get(entity_id)
        return copy.deepcopy(snap) if snap is not None else None

    # ------------------------------------------------------------------
    # Subscribers
    # ------------------------------------------------------------------

    def subscribe(self, callback_fn: Callable[[StateDiff], None]) -> Callable[[], None]:
        """Subscribe to non-empty diffs as they are recorded.

        Returns:
            Unsubscribe callable.
        """
        self._subscribers.add(callback_fn)

        def unsub() -> None:
            self._subscribers.discard(callback_fn)

        return unsub

    def _notify(self, diff: StateDiff) -> None:
        for cb in list(self._subscribers):
            try:
                cb(diff)
            except (RuntimeError, ValueError, TypeError, AttributeError):
                _LOGGER.exception("DiffCollector subscriber raised")

    # ------------------------------------------------------------------
    # Core: update(entity, states)
    # ------------------------------------------------------------------

    def update(
        self,
        entity_id: str,
        states: Iterable[dict[str, Any]],
        topic: str = "up/status",
    ) -> StateDiff | None:
        """Compute the diff vs the previous publish and store it.

        Args:
            entity_id: Sber device identifier (HA entity_id).
            states: Sber ``states`` list — each item is
                ``{"key": str, "value": {...}}``.  Items without a
                ``key`` are ignored.
            topic: Source topic string, carried into the diff record so
                DevTools can distinguish ``up/status`` vs ``up/config``
                if we ever extend to config diffing.

        Returns:
            The :class:`StateDiff` record (also appended to the ring
            buffer), or ``None`` when the payload is empty or results
            in no delta (so non-empty-diff is the only way to reach
            subscribers).
        """
        new_map: dict[str, Any] = {}
        for s in states:
            key = s.get("key")
            if key is None:
                continue
            new_map[key] = s.get("value")

        prev = self._last_by_entity.get(entity_id)
        is_initial = prev is None
        # Record the new baseline even when the result is uninteresting —
        # otherwise we'd keep comparing against a stale prior for an
        # entity that was just re-initialised.
        self._last_by_entity[entity_id] = copy.deepcopy(new_map)

        if is_initial:
            if not self._include_initial or not new_map:
                return None
            diff = StateDiff(
                ts=time.time(),
                entity_id=entity_id,
                topic=topic,
                added=copy.deepcopy(new_map),
                is_initial=True,
            )
        else:
            added = {k: v for k, v in new_map.items() if k not in prev}
            removed = {k: v for k, v in prev.items() if k not in new_map}
            changed = {
                k: {"before": prev[k], "after": new_map[k]} for k in new_map if k in prev and prev[k] != new_map[k]
            }
            if not added and not removed and not changed:
                return None
            diff = StateDiff(
                ts=time.time(),
                entity_id=entity_id,
                topic=topic,
                added=copy.deepcopy(added),
                removed=copy.deepcopy(removed),
                changed=copy.deepcopy(changed),
            )

        self._diffs.append(diff)
        self._notify(diff)
        return diff

    def record_publish_payload(
        self,
        payload: str | dict[str, Any],
        topic: str = "up/status",
    ) -> list[StateDiff]:
        """Parse a full Sber state payload and record a diff per device.

        Convenience entry point for the publish path which already has
        the serialized JSON.  Invalid JSON / unexpected shape returns
        an empty list without raising — DevTools must never affect
        publish success.

        Args:
            payload: JSON string or pre-parsed dict with the Sber
                ``{"devices": {entity_id: {"states": [...]}}}`` shape.
            topic: MQTT topic the payload was sent to.

        Returns:
            The list of non-empty :class:`StateDiff` records produced
            (one per changed device).
        """
        if isinstance(payload, str):
            try:
                import json

                data = json.loads(payload)
            except (ValueError, TypeError):
                return []
        else:
            data = payload

        devices = data.get("devices") if isinstance(data, dict) else None
        if not isinstance(devices, dict):
            return []

        results: list[StateDiff] = []
        for eid, body in devices.items():
            if not isinstance(body, dict):
                continue
            states = body.get("states")
            if not isinstance(states, list):
                continue
            diff = self.update(eid, states, topic=topic)
            if diff is not None:
                results.append(diff)
        return results
