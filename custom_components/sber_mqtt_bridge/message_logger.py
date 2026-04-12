"""MQTT message ring-buffer logger with real-time subscriber support.

Extracted from ``SberBridge`` to isolate DevTools logging from bridge core
logic (SRP).  ``MessageLogger`` stores the last ``maxlen`` messages in a
``deque`` and fans them out to any number of subscriber callbacks for
WebSocket push.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from collections.abc import Callable
from typing import Any

_LOGGER = logging.getLogger(__name__)


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
