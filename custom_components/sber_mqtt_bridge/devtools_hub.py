"""DevTools collector hub — aggregates the four panel-side observers.

Owns the four DevTools collectors extracted from :class:`SberBridge`:

* :class:`MessageLogger` — outbound message ring buffer for the panel
  Messages tab.
* :class:`TraceCollector` — correlation timelines (DevTools Traces tab).
* :class:`DiffCollector` — per-publish state deltas (State Diff tab).
* :class:`ValidationCollector` — Sber schema issues (Schema Validation
  tab).

The hub centralises lifecycle (instantiation, resize, sweep) and lets
the bridge expose them via thin proxy properties so the ~83 existing
call sites do not need to be rewritten.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from .message_logger import MessageLogger
from .schema_validator import ValidationCollector
from .state_diff import DiffCollector
from .trace_collector import TraceCollector

if TYPE_CHECKING:
    from collections.abc import Callable

_LOGGER = logging.getLogger(__name__)


class DevToolsHub:
    """Owns the four DevTools observers and their shared lifecycle.

    Constructed with the initial ring-buffer capacity; the bridge calls
    :meth:`resize` from ``apply_settings`` to keep all four collectors
    in sync with the user-tunable ``message_log_size`` option.
    """

    def __init__(self, message_log_size: int) -> None:
        """Build the hub with the four collectors at the given size.

        Args:
            message_log_size: Capacity passed to each collector's ring
                buffer. Tuned via the ``message_log_size`` config option;
                kept identical across all four for parallel scrollback.
        """
        self._msg_logger = MessageLogger(maxlen=message_log_size)
        self._trace_collector = TraceCollector(
            maxlen=message_log_size,
            trace_timeout=10.0,
        )
        self._diff_collector = DiffCollector(maxlen=message_log_size)
        self._validation_collector = ValidationCollector(maxlen=message_log_size)

    # ------------------------------------------------------------------ accessors
    @property
    def message_logger(self) -> MessageLogger:
        """Return the outbound-message ring buffer collector."""
        return self._msg_logger

    @property
    def trace_collector(self) -> TraceCollector:
        """Return the correlation-timeline collector."""
        return self._trace_collector

    @property
    def diff_collector(self) -> DiffCollector:
        """Return the per-publish state-delta collector."""
        return self._diff_collector

    @property
    def validation_collector(self) -> ValidationCollector:
        """Return the Sber schema-validation collector."""
        return self._validation_collector

    # ------------------------------------------------------------------ message log
    @property
    def message_log(self) -> list[dict[str, Any]]:
        """Return the current outbound-message ring buffer entries."""
        return self._msg_logger.entries

    def clear_message_log(self) -> None:
        """Drop all entries from the DevTools message log."""
        self._msg_logger.clear()

    def subscribe_messages(self, callback_fn: Callable) -> Callable:
        """Subscribe to outbound MQTT messages.

        Args:
            callback_fn: Invoked with each new message entry as it lands.

        Returns:
            Unsubscribe callable.
        """
        return self._msg_logger.subscribe(callback_fn)

    def log_message(self, direction: str, topic: str, payload: str) -> None:
        """Append a message to the ring buffer and notify subscribers."""
        self._msg_logger.log(direction, topic, payload)

    # ------------------------------------------------------------------ lifecycle
    def resize(self, message_log_size: int) -> None:
        """Resize all four ring buffers in lock-step."""
        self._msg_logger.resize(message_log_size)
        self._trace_collector.resize(message_log_size)
        self._diff_collector.resize(message_log_size)
        self._validation_collector.resize(message_log_size)

    def sweep_traces(self) -> None:
        """Close traces idle beyond the configured timeout.

        Safe to call from any context; ``TraceCollector.sweep`` is
        CPU-only and the hub swallows defensive exceptions so the bridge
        housekeeping path never breaks.
        """
        try:
            self._trace_collector.sweep()
        except Exception:  # pragma: no cover — must never break the bridge
            _LOGGER.exception("Trace sweep failed")
