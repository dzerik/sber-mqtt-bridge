"""MQTT message ring-buffer logger with real-time subscriber support.

Extracted from ``SberBridge`` to isolate DevTools logging from bridge core
logic (SRP).  ``MessageLogger`` stores the last ``maxlen`` messages in a
``deque`` and fans them out to any number of subscriber callbacks for
WebSocket push.

The logger also *reads* one kind of packet instead of only storing it:
the error the cloud publishes to ``down/errors``.  Sber sends a bare
number there (``{"code": 403, "message": "…"}``), and the documentation
is the only place that says what it means — 400 is a bad payload, 403 is
a bad token, 503 is "come back later".  Three completely different
situations that look identical in a raw packet dump, which is why
:func:`parse_sber_error` lifts the code out and the panel labels it.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections import deque
from collections.abc import Callable
from typing import Any

from .sber_constants import MqttTopicSuffix

_LOGGER = logging.getLogger(__name__)

_CODE_RE = re.compile(r'"code"\s*:\s*(\d+)')
"""Last-resort search for the error code in a payload that will not parse.

``SberBridge`` stores the last error truncated to 500 characters, so a
verbose ``details`` list can leave the panel with a JSON fragment.  The
code is the first field Sber writes and the one field worth rescuing.
"""

_MAX_ERROR_MESSAGE_CHARS = 300
"""Cap on the free-text ``message`` handed to the panel.

The field is "произвольное описание ошибки" — arbitrary text from the
cloud, rendered in a table cell.  Long enough to read, short enough not
to push a ring buffer of 500 entries into megabytes.
"""


def parse_sber_error(payload: str | None) -> dict[str, Any] | None:
    """Read the code and text out of a Sber error packet.

    Sber documents two error shapes (``error`` and ``common error``) and
    both start with an obligatory integer ``code`` plus an obligatory
    free-text ``message``; the per-device shape adds ``id``.  Only those
    three fields are extracted — the panel shows the raw payload next to
    the decoded line anyway.

    Args:
        payload: Decoded payload of a ``down/errors`` message, or the
            stored ``last_error_detail`` (which is the same JSON, cut to
            500 characters).

    Returns:
        ``{"code": int | None, "message": str, "device_id": str}`` when
        the payload looks like a Sber error, otherwise ``None``.  A
        ``None`` code means "the packet was an error but its code was
        unreadable" — worth showing, never worth guessing.
    """
    if not payload:
        return None
    data: Any = None
    try:
        data = json.loads(payload)
    except (TypeError, ValueError):
        data = None
    if isinstance(data, dict):
        raw_code = data.get("code")
        code = raw_code if isinstance(raw_code, int) and not isinstance(raw_code, bool) else None
        message = data.get("message")
        device_id = data.get("id")
        return {
            "code": code,
            "message": str(message)[:_MAX_ERROR_MESSAGE_CHARS] if isinstance(message, str) else "",
            "device_id": device_id if isinstance(device_id, str) else "",
        }
    match = _CODE_RE.search(payload)
    if match is None:
        return None
    return {"code": int(match.group(1)), "message": "", "device_id": ""}


def _is_error_entry(entry: dict[str, Any]) -> bool:
    """Tell whether a log entry is a packet from the ``down/errors`` topic.

    Decided by topic rather than by the decoded ``sber_error`` field: a
    packet the parser could not read is still an error, and it is exactly
    the one worth dating.

    Args:
        entry: One entry of :attr:`MessageLogger.entries`.

    Returns:
        True for a message that arrived on the error topic.
    """
    topic = entry.get("topic")
    return isinstance(topic, str) and topic.rsplit("/", 1)[-1] == MqttTopicSuffix.ERRORS


def last_error_moment(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Date the last error packet and say whether the cloud spoke after it.

    ``BridgeStats.last_error_detail`` is written once and never cleared:
    nothing resets it on reconnect, and nothing resets it when the bridge
    starts working again.  On its own it therefore cannot tell "the cloud
    is refusing us right now" from "the cloud refused us once, at boot,
    before the password was fixed" — and the panel drew the same red tile
    for both until Home Assistant was restarted.

    The message log is the only place that knows *when*.  Two facts come
    out of it, and both are needed: the moment of the error, and whether
    the cloud has addressed the bridge since — an inbound packet that is
    not itself an error means the connection carries traffic again.

    Args:
        entries: Snapshot of the ring buffer, oldest first — the value of
            :attr:`MessageLogger.entries`.

    Returns:
        ``{"at": float | None, "superseded": bool}``.  A ``None`` moment
        means "the error is older than the log remembers" (the buffer is
        bounded and the user can clear it), which is not the same as "just
        now" and must not be drawn as one.
    """
    for index in range(len(entries) - 1, -1, -1):
        entry = entries[index]
        if not _is_error_entry(entry):
            continue
        moment = entry.get("time")
        superseded = any(
            later.get("direction") == "in" and not _is_error_entry(later) for later in entries[index + 1 :]
        )
        return {"at": moment if isinstance(moment, (int, float)) else None, "superseded": superseded}
    return {"at": None, "superseded": False}


class MessageLogger:
    """Ring-buffer logger for MQTT messages (incoming and outgoing).

    Attributes:
        Not exposed directly; use the provided properties and methods.
    """

    def __init__(self, maxlen: int) -> None:
        """Initialize the logger with a ring-buffer of the given size.

        Args:
            maxlen: Maximum number of messages kept in the ring buffer.
        """
        self._log: deque[dict[str, Any]] = deque(maxlen=maxlen)
        self._subscribers: set[Callable[[dict], None]] = set()

    @property
    def entries(self) -> list[dict[str, Any]]:
        """Return a snapshot of the ring buffer as a list (oldest first)."""
        return list(self._log)

    @property
    def maxlen(self) -> int | None:
        """Return the current ring-buffer capacity."""
        return self._log.maxlen

    def resize(self, new_maxlen: int) -> None:
        """Replace the underlying deque with a new one of the requested size.

        Keeps the most recent ``new_maxlen`` entries.

        Args:
            new_maxlen: New ring-buffer capacity.
        """
        if new_maxlen == self._log.maxlen:
            return
        old = list(self._log)
        self._log = deque(old[-new_maxlen:], maxlen=new_maxlen)

    def log(self, direction: str, topic: str, payload: str) -> None:
        """Append a message to the ring buffer and notify subscribers.

        A message arriving on ``down/errors`` additionally carries a
        ``sber_error`` entry — the decoded ``{"code", "message",
        "device_id"}`` triple — so the panel can print what the number
        means instead of leaving the reader with a bare ``403``.  The
        parse is attempted only for that one topic: every other packet
        would pay for a JSON decode it has no use for.

        Args:
            direction: Either ``"in"`` (received) or ``"out"`` (sent).
            topic: MQTT topic string.
            payload: Decoded payload (may be raw text for debugging).
        """
        msg_dict: dict[str, Any] = {
            "time": time.time(),
            "direction": direction,
            "topic": topic,
            "payload": payload,
        }
        if topic.rsplit("/", 1)[-1] == MqttTopicSuffix.ERRORS:
            error = parse_sber_error(payload)
            if error is not None:
                msg_dict["sber_error"] = error
        self._log.append(msg_dict)
        for cb in list(self._subscribers):
            try:
                cb(msg_dict)
            except (RuntimeError, ValueError, TypeError, AttributeError):
                _LOGGER.exception("Error in message subscriber callback")

    def clear(self) -> None:
        """Remove all messages from the ring buffer."""
        self._log.clear()

    def subscribe(self, callback_fn: Callable[[dict], None]) -> Callable[[], None]:
        """Subscribe to new messages in real time.

        Args:
            callback_fn: Function called with each new message dict.

        Returns:
            Unsubscribe callable — invoke once to detach the listener.
        """
        self._subscribers.add(callback_fn)

        def unsub() -> None:
            self._subscribers.discard(callback_fn)

        return unsub
