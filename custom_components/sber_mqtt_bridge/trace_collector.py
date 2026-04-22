"""Correlation-timeline trace collector for DevTools.

Groups MQTT + HA events into logical traces keyed by ``HomeAssistant.Context.id``
(which HA automatically propagates through service calls → state_changed events).
A trace is opened when a Sber command arrives or when a HA state change
originates outside an existing trace; events are appended while the trace is
active and the trace is closed either explicitly or via inactivity timeout.

Design notes:
    * Active traces live in ``_active`` keyed by ``trace_id`` for O(1) lookup.
    * Closed traces go into a bounded ``deque`` (same ring-buffer pattern as
      ``MessageLogger``) so the memory footprint stays predictable.
    * ``_last_trace_per_entity`` lets outbound publishes — which lose the
      original Context — be attached to the most recent trace for that entity.
    * Subscribers are notified on trace_started / trace_updated / trace_closed
      so the frontend can render incremental timelines.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

_LOGGER = logging.getLogger(__name__)

TraceTrigger = Literal["sber_command", "ha_state_change", "unknown"]
TraceStatus = Literal["active", "success", "failed", "timeout"]
TraceEventType = Literal[
    "sber_command",
    "ha_service_call",
    "ha_state_changed",
    "publish_out",
    "silent_rejection",
]
SubscriberEvent = Literal["trace_started", "trace_updated", "trace_closed"]


@dataclass
class TraceEvent:
    """A single event within a correlation trace."""

    ts: float
    type: TraceEventType
    entity_id: str | None = None
    topic: str | None = None
    payload: Any = None
    duration_ms: float | None = None

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""
        return asdict(self)


@dataclass
class Trace:
    """A correlation trace — one logical transaction spanning Sber ↔ HA."""

    trace_id: str
    started_at: float
    trigger: TraceTrigger
    entity_ids: set[str] = field(default_factory=set)
    events: list[TraceEvent] = field(default_factory=list)
    status: TraceStatus = "active"
    last_event_at: float = 0.0
    closed_at: float | None = None

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation (``entity_ids`` as list)."""
        return {
            "trace_id": self.trace_id,
            "started_at": self.started_at,
            "trigger": self.trigger,
            "entity_ids": sorted(self.entity_ids),
            "events": [e.as_dict() for e in self.events],
            "status": self.status,
            "last_event_at": self.last_event_at,
            "closed_at": self.closed_at,
        }


class TraceCollector:
    """In-memory store of active and recently-closed correlation traces.

    The collector is deliberately passive: it does not schedule its own timers.
    Callers invoke :meth:`sweep` from an existing periodic tick (or tests can
    drive it directly) to close traces that have been idle beyond
    ``trace_timeout``. This keeps the module HA-independent and trivial to
    unit-test.
    """

    def __init__(self, maxlen: int = 100, trace_timeout: float = 10.0) -> None:
        """Initialize a collector.

        Args:
            maxlen: Ring-buffer size for closed traces.
            trace_timeout: Seconds of inactivity after which an active trace
                auto-closes with status ``timeout`` (unless already
                ``success`` / ``failed``) on the next :meth:`sweep`.
        """
        self._active: dict[str, Trace] = {}
        self._closed: deque[Trace] = deque(maxlen=maxlen)
        self._trace_timeout = trace_timeout
        self._last_trace_per_entity: dict[str, str] = {}
        self._subscribers: set[Callable[[SubscriberEvent, Trace], None]] = set()

    # ------------------------------------------------------------------
    # Properties / config
    # ------------------------------------------------------------------

    @property
    def maxlen(self) -> int | None:
        """Return the closed-trace ring-buffer capacity."""
        return self._closed.maxlen

    @property
    def trace_timeout(self) -> float:
        """Return the configured inactivity timeout in seconds."""
        return self._trace_timeout

    def resize(self, new_maxlen: int) -> None:
        """Resize the closed-trace ring buffer, keeping the newest entries."""
        if new_maxlen == self._closed.maxlen:
            return
        old = list(self._closed)
        self._closed = deque(old[-new_maxlen:], maxlen=new_maxlen)

    def set_trace_timeout(self, seconds: float) -> None:
        """Update the inactivity timeout."""
        self._trace_timeout = seconds

    # ------------------------------------------------------------------
    # Snapshot / clear
    # ------------------------------------------------------------------

    def snapshot(self, *, include_active: bool = True) -> list[dict[str, Any]]:
        """Return a JSON-serializable snapshot: closed first (oldest→newest), then active."""
        out = [t.as_dict() for t in self._closed]
        if include_active:
            out.extend(t.as_dict() for t in self._active.values())
        return out

    def get(self, trace_id: str) -> dict[str, Any] | None:
        """Return one trace as dict, or ``None`` if unknown."""
        trace = self._active.get(trace_id)
        if trace is not None:
            return trace.as_dict()
        for t in self._closed:
            if t.trace_id == trace_id:
                return t.as_dict()
        return None

    def clear(self) -> None:
        """Drop all active and closed traces."""
        self._active.clear()
        self._closed.clear()
        self._last_trace_per_entity.clear()

    # ------------------------------------------------------------------
    # Subscribers
    # ------------------------------------------------------------------

    def subscribe(self, callback_fn: Callable[[SubscriberEvent, Trace], None]) -> Callable[[], None]:
        """Subscribe to trace lifecycle events.

        Returns:
            Unsubscribe callable.
        """
        self._subscribers.add(callback_fn)

        def unsub() -> None:
            self._subscribers.discard(callback_fn)

        return unsub

    def _notify(self, kind: SubscriberEvent, trace: Trace) -> None:
        for cb in list(self._subscribers):
            try:
                cb(kind, trace)
            except (RuntimeError, ValueError, TypeError, AttributeError):
                _LOGGER.exception("TraceCollector subscriber raised")

    # ------------------------------------------------------------------
    # Lifecycle: begin / record / close
    # ------------------------------------------------------------------

    def begin(
        self,
        *,
        trace_id: str | None,
        trigger: TraceTrigger,
        entity_ids: Iterable[str],
        topic: str | None = None,
        payload: Any = None,
    ) -> Trace:
        """Open a new trace (or reuse an existing active trace with the same id).

        Args:
            trace_id: Correlation id — typically ``event.context.id``. ``None``
                or empty string triggers a synthetic uuid so ad-hoc calls still
                produce a valid trace.
            trigger: What caused this trace (``sber_command`` /
                ``ha_state_change``).
            entity_ids: Entities involved; more may be added via subsequent
                :meth:`record` calls.
            topic: MQTT topic for the initiating event (if any).
            payload: Initiating payload (stored as-is in the first event).

        Returns:
            The active :class:`Trace` (new or existing).
        """
        tid = trace_id or f"synthetic-{uuid.uuid4().hex[:12]}"
        now = time.time()
        ids = set(entity_ids)

        existing = self._active.get(tid)
        if existing is not None:
            existing.entity_ids.update(ids)
            existing.last_event_at = now
            for eid in ids:
                self._last_trace_per_entity[eid] = tid
            return existing

        trace = Trace(
            trace_id=tid,
            started_at=now,
            trigger=trigger,
            entity_ids=ids,
            last_event_at=now,
        )
        event = TraceEvent(
            ts=now,
            type="sber_command" if trigger == "sber_command" else "ha_state_changed",
            entity_id=next(iter(ids)) if len(ids) == 1 else None,
            topic=topic,
            payload=payload,
        )
        trace.events.append(event)
        self._active[tid] = trace
        for eid in ids:
            self._last_trace_per_entity[eid] = tid
        self._notify("trace_started", trace)
        return trace

    def record(
        self,
        trace_id: str | None,
        *,
        type_: TraceEventType,
        entity_id: str | None = None,
        topic: str | None = None,
        payload: Any = None,
        duration_ms: float | None = None,
        trigger_if_new: TraceTrigger = "unknown",
    ) -> Trace | None:
        """Append an event to the trace identified by ``trace_id``.

        If the trace does not exist yet, a new one is opened with
        ``trigger_if_new`` — this covers HA state changes that weren't
        pre-registered by :meth:`begin`.

        Returns the trace, or ``None`` when ``trace_id`` is falsy and no
        fallback trace could be resolved (should never happen in practice).
        """
        if not trace_id:
            return None
        trace = self._active.get(trace_id)
        if trace is None:
            trace = self.begin(
                trace_id=trace_id,
                trigger=trigger_if_new,
                entity_ids=[entity_id] if entity_id else [],
                topic=topic,
                payload=None,  # avoid duplicating payload in both begin-event and recorded event
            )

        now = time.time()
        event = TraceEvent(
            ts=now,
            type=type_,
            entity_id=entity_id,
            topic=topic,
            payload=payload,
            duration_ms=duration_ms,
        )
        trace.events.append(event)
        trace.last_event_at = now
        if entity_id:
            trace.entity_ids.add(entity_id)
            self._last_trace_per_entity[entity_id] = trace.trace_id
        self._notify("trace_updated", trace)
        return trace

    def record_publish(self, entity_id: str, topic: str, payload: Any = None) -> Trace | None:
        """Attach an outbound publish to the most recent trace for ``entity_id``.

        Outbound publishes lose the original HA Context (they're typically
        fired from a debounced/batched path), so we fall back to the
        per-entity last-known trace_id.  Returns ``None`` if no trace is
        currently active for this entity.
        """
        tid = self._last_trace_per_entity.get(entity_id)
        if tid is None:
            return None
        trace = self._active.get(tid)
        if trace is None:
            return None
        now = time.time()
        event = TraceEvent(
            ts=now,
            type="publish_out",
            entity_id=entity_id,
            topic=topic,
            payload=payload,
        )
        trace.events.append(event)
        trace.last_event_at = now
        self._notify("trace_updated", trace)
        return trace

    def record_silent_rejection(self, entity_ids: Iterable[str]) -> list[str]:
        """Mark active traces for the given entities as failed due to silent rejection.

        Returns the list of trace_ids affected.
        """
        affected: list[str] = []
        now = time.time()
        for eid in entity_ids:
            tid = self._last_trace_per_entity.get(eid)
            if tid is None:
                continue
            trace = self._active.get(tid)
            if trace is None:
                continue
            trace.events.append(
                TraceEvent(
                    ts=now,
                    type="silent_rejection",
                    entity_id=eid,
                )
            )
            trace.last_event_at = now
            trace.status = "failed"
            self._notify("trace_updated", trace)
            affected.append(tid)
        return affected

    def close(self, trace_id: str, *, status: TraceStatus | None = None) -> Trace | None:
        """Close an active trace and move it to the closed ring buffer.

        If ``status`` is omitted, pick ``success`` (any ha_service_call or
        publish_out seen) otherwise ``timeout``.  Already-``failed`` traces
        keep their status.
        """
        trace = self._active.pop(trace_id, None)
        if trace is None:
            return None
        if status is not None:
            trace.status = status
        elif trace.status == "active":
            has_progress = any(e.type in ("ha_service_call", "publish_out", "ha_state_changed") for e in trace.events)
            trace.status = "success" if has_progress else "timeout"
        trace.closed_at = time.time()
        self._closed.append(trace)
        # Forget per-entity pointer only if it still points at this trace.
        for eid in list(self._last_trace_per_entity):
            if self._last_trace_per_entity[eid] == trace_id:
                del self._last_trace_per_entity[eid]
        self._notify("trace_closed", trace)
        return trace

    def sweep(self) -> list[str]:
        """Close any active traces that have been idle beyond the timeout.

        Intended to be called from an existing periodic tick (e.g. the
        bridge's housekeeping loop). Returns closed trace_ids.
        """
        now = time.time()
        to_close = [tid for tid, tr in self._active.items() if now - tr.last_event_at >= self._trace_timeout]
        for tid in to_close:
            self.close(tid)
        return to_close
