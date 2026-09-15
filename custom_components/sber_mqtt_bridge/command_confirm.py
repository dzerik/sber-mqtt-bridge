"""Per-key confirmation of Sber commands for DevTools.

A correlation trace shows that a Sber command turned into a Home Assistant
service call — not whether the device actually did it.  Issue #63 was a
cloud lamp that accepted ``turn_on`` and stayed as it was; every trace
looked healthy.

This tracker records the keys of each inbound command and compares them
with the state the bridge later publishes for that entity.  That state is
built from Home Assistant, and it is exactly what the Sber app will show,
so "confirmed" means the app and the device agree with the command.

Only full state snapshots may confirm: the immediate command echo repeats
the commanded values by design and would confirm everything at once.

Design notes:
    * HA-independent and passive, like :mod:`.trace_collector`: the bridge
      feeds it and calls :meth:`sweep` from its DevTools timer.
    * Command-only features (``open_set``, ``unlock`` …) carry no state and
      are not tracked — nothing could ever confirm them.
    * A newer command for the same entity and key closes the older one as
      ``superseded``: dragging a slider sends a burst of values, and only
      the last of them can ever be reported back.
    * Numeric values match within a tolerance supplied by the bridge,
      because a Sber value may pass through a coarser HA scale and come
      back rounded (brightness 100–900 ↔ 0–255).
"""

from __future__ import annotations

import logging
import time
import uuid
from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, Literal

from ._generated import COMMAND_ONLY_FEATURES

_LOGGER = logging.getLogger(__name__)

ConfirmStatus = Literal["pending", "confirmed", "partial", "not_confirmed", "superseded"]
SubscriberEvent = Literal["command_started", "command_updated", "command_closed"]
ToleranceFn = Callable[[str, str, str], float]

COLOUR_TOLERANCE: dict[str, int] = {"h": 2, "s": 10, "v": 4}
"""Allowed drift per HSV component of a ``light_colour`` value.

Sber saturation (0–1000) comes back through HA's percent scale, so it is
only precise to 10; value (0–1000) comes back through 8-bit brightness,
precise to ~4; hue is degrees on both sides, off by rounding only."""


@dataclass
class KeyCheck:
    """One commanded key and what the bridge reported for it so far."""

    key: str
    sent: dict[str, Any]
    reported: dict[str, Any] | None = None
    matched: bool = False

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""
        return {"key": self.key, "sent": self.sent, "reported": self.reported, "matched": self.matched}


@dataclass
class ConfirmRecord:
    """A Sber command for one entity and the confirmation state of its keys."""

    command_id: str
    entity_id: str
    sent_at: float
    context_id: str | None
    keys: list[KeyCheck] = field(default_factory=list)
    status: ConfirmStatus = "pending"
    closed_at: float | None = None

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""
        return {
            "command_id": self.command_id,
            "entity_id": self.entity_id,
            "sent_at": self.sent_at,
            "context_id": self.context_id,
            "keys": [k.as_dict() for k in self.keys],
            "status": self.status,
            "closed_at": self.closed_at,
        }


def _number(raw: Any) -> float | None:
    """Parse an int/float/numeric string, ``None`` for anything else."""
    if isinstance(raw, bool):
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def values_match(sent: dict[str, Any], reported: dict[str, Any], tolerance: float = 0) -> bool:
    """Tell whether a reported Sber value satisfies the commanded one.

    Args:
        sent: The ``value`` object from the command.
        reported: The ``value`` object from the published state.
        tolerance: Allowed absolute difference for INTEGER / FLOAT values.

    Returns:
        True when the types agree and the payloads are equal (within
        tolerance for numbers, per component for colours).
    """
    kind = sent.get("type")
    if kind != reported.get("type"):
        return False
    if kind in ("INTEGER", "FLOAT"):
        field_name = "integer_value" if kind == "INTEGER" else "float_value"
        a, b = _number(sent.get(field_name)), _number(reported.get(field_name))
        return a is not None and b is not None and abs(a - b) <= tolerance
    if kind == "COLOUR":
        a_col, b_col = sent.get("colour_value"), reported.get("colour_value")
        if not isinstance(a_col, dict) or not isinstance(b_col, dict):
            return False
        for comp, slack in COLOUR_TOLERANCE.items():
            a, b = _number(a_col.get(comp)), _number(b_col.get(comp))
            if a is None or b is None or abs(a - b) > slack:
                return False
        return True
    plain_field = {"BOOL": "bool_value", "ENUM": "enum_value", "STRING": "string_value"}.get(str(kind))
    return plain_field is not None and sent.get(plain_field) == reported.get(plain_field)


def _state_entries(states: Iterable[Any]) -> Iterable[tuple[str, dict[str, Any]]]:
    """Yield ``(key, value)`` for well-formed ``{"key", "value"}`` state entries."""
    for item in states:
        if not isinstance(item, dict):
            continue
        key, value = item.get("key"), item.get("value")
        if isinstance(key, str) and isinstance(value, dict):
            yield key, value


class CommandConfirmTracker:
    """In-memory store of pending and recently closed command confirmations."""

    def __init__(
        self,
        *,
        maxlen: int = 100,
        timeout: float = 10.0,
        tolerance_for: ToleranceFn | None = None,
    ) -> None:
        """Initialize a tracker.

        Args:
            maxlen: Ring-buffer size for closed commands.
            timeout: Seconds after which :meth:`sweep` closes a pending command.
            tolerance_for: ``(entity_id, key, value_type) -> tolerance`` for
                numeric comparisons; exact matching when omitted.
        """
        self._active: dict[str, ConfirmRecord] = {}
        self._closed: deque[ConfirmRecord] = deque(maxlen=maxlen)
        self._timeout = timeout
        self._tolerance_for: ToleranceFn = tolerance_for or (lambda *_: 0)
        self._subscribers: set[Callable[[SubscriberEvent, ConfirmRecord], None]] = set()

    @property
    def timeout(self) -> float:
        """Return seconds a command may stay pending."""
        return self._timeout

    def resize(self, new_maxlen: int) -> None:
        """Resize the closed-command ring buffer, keeping the newest entries."""
        if new_maxlen == self._closed.maxlen:
            return
        self._closed = deque(list(self._closed)[-new_maxlen:], maxlen=new_maxlen)

    def snapshot(self) -> list[dict[str, Any]]:
        """Return closed commands (oldest → newest) followed by pending ones."""
        return [r.as_dict() for r in self._closed] + [r.as_dict() for r in self._active.values()]

    def get(self, command_id: str) -> dict[str, Any] | None:
        """Return one command by id, or ``None`` if it is unknown."""
        record = self._active.get(command_id)
        if record is None:
            record = next((r for r in self._closed if r.command_id == command_id), None)
        return record.as_dict() if record else None

    def clear(self) -> None:
        """Drop all pending and closed commands."""
        self._active.clear()
        self._closed.clear()

    def subscribe(self, callback_fn: Callable[[SubscriberEvent, ConfirmRecord], None]) -> Callable[[], None]:
        """Subscribe to command lifecycle events.

        Returns:
            Unsubscribe callable.
        """
        self._subscribers.add(callback_fn)
        return lambda: self._subscribers.discard(callback_fn)

    def _notify(self, kind: SubscriberEvent, record: ConfirmRecord) -> None:
        for cb in list(self._subscribers):
            try:
                cb(kind, record)
            except Exception:
                _LOGGER.exception("CommandConfirmTracker subscriber raised")

    def _close(self, record: ConfirmRecord, status: ConfirmStatus) -> None:
        record.status = status
        record.closed_at = time.time()
        self._active.pop(record.command_id, None)
        self._closed.append(record)
        self._notify("command_closed", record)

    def record_command(
        self,
        entity_id: str,
        states: Iterable[Any],
        *,
        context_id: str | None = None,
    ) -> ConfirmRecord | None:
        """Start tracking the state-bearing keys of one entity's command.

        Args:
            entity_id: HA entity the command targets.
            states: ``states`` list of the command for this entity.
            context_id: HA context of the command, linking it to its trace.

        Returns:
            The new record, or ``None`` when no key can be confirmed.
        """
        checks = [KeyCheck(key=k, sent=v) for k, v in _state_entries(states) if k not in COMMAND_ONLY_FEATURES]
        if not checks:
            return None
        keys = {c.key for c in checks}
        for older in list(self._active.values()):
            if older.entity_id == entity_id and keys & {c.key for c in older.keys}:
                self._close(older, "superseded")
        record = ConfirmRecord(
            command_id=uuid.uuid4().hex[:12],
            entity_id=entity_id,
            sent_at=time.time(),
            context_id=context_id,
            keys=checks,
        )
        self._active[record.command_id] = record
        self._notify("command_started", record)
        return record

    def observe_state(self, entity_id: str, states: Iterable[Any]) -> None:
        """Compare a full published state of ``entity_id`` with its pending commands.

        Args:
            entity_id: Entity whose state was published.
            states: ``states`` list of the published snapshot.
        """
        pending = [r for r in self._active.values() if r.entity_id == entity_id]
        if not pending:
            return
        reported = dict(_state_entries(states))
        for record in pending:
            changed = False
            for check in record.keys:
                value = reported.get(check.key)
                if value is None or check.matched:
                    continue
                tolerance = self._tolerance_for(entity_id, check.key, str(check.sent.get("type")))
                check.reported = value
                check.matched = values_match(check.sent, value, tolerance)
                changed = True
            if all(c.matched for c in record.keys):
                self._close(record, "confirmed")
            elif changed:
                self._notify("command_updated", record)

    def sweep(self) -> list[str]:
        """Close commands pending longer than the timeout.

        Returns:
            Ids of the commands closed.
        """
        now = time.time()
        closed: list[str] = []
        for record in list(self._active.values()):
            if now - record.sent_at < self._timeout:
                continue
            self._close(record, "partial" if any(c.matched for c in record.keys) else "not_confirmed")
            closed.append(record.command_id)
        return closed
