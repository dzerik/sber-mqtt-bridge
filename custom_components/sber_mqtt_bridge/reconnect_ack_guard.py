"""Post-reconnect acknowledgment guard for Sber MQTT Bridge.

After (re)connecting to Sber MQTT, the bridge publishes its device
config and current states.  Sber cloud may send "corrective" commands
based on its stale cache before acknowledging our published states.
Accepting those would override the real HA device state.

This guard blocks command processing until Sber sends a
``status_request`` or ``config_request`` — an implicit acknowledgment
that our published state is authoritative.  A fallback timer ensures
we don't block forever.
"""

from __future__ import annotations

import logging
import time

_LOGGER = logging.getLogger(__name__)


class ReconnectAckGuard:
    """Manages post-reconnect acknowledgment guard state.

    Activated after (re)connect, cleared when Sber acknowledges via
    ``status_request`` / ``config_request``, or when the fallback
    timer expires.

    Attributes:
        _awaiting: True while waiting for Sber acknowledgment.
        _deadline: ``time.monotonic()`` timestamp for fallback timeout.
        _timeout_handle: Handle for the scheduled fallback timer
            (``loop.call_later``), so it can be cancelled on cleanup.
    """

    __slots__ = ("_awaiting", "_deadline", "_timeout_handle")

    def __init__(self) -> None:
        """Initialize the guard (inactive)."""
        self._awaiting: bool = False
        self._deadline: float = 0.0
        self._timeout_handle: object | None = None

    @property
    def is_awaiting(self) -> bool:
        """Return True if still waiting for Sber acknowledgment."""
        return self._awaiting

    @property
    def is_deadline_exceeded(self) -> bool:
        """Return True if the fallback timeout has been reached."""
        return self._awaiting and time.monotonic() >= self._deadline

    def activate(self, grace_timeout: float, loop: object) -> None:
        """Activate the guard with a fallback timeout.

        Args:
            grace_timeout: Seconds to wait before auto-clearing.
            loop: asyncio event loop for scheduling the timer callback.
        """
        self._awaiting = True
        self._deadline = time.monotonic() + grace_timeout
        self._timeout_handle = loop.call_later(grace_timeout, self._on_timeout)

    def acknowledge(self) -> None:
        """Clear the guard (Sber acknowledged our state)."""
        if self._awaiting:
            _LOGGER.info("Sber acknowledged — accepting commands")
            self._awaiting = False
            self._cancel_timer()

    def clear(self) -> None:
        """Force-clear the guard (e.g. on disconnect)."""
        self._awaiting = False
        self._cancel_timer()

    def timeout_check(self) -> bool:
        """Check and clear the guard if deadline exceeded.

        Returns:
            True if the guard was cleared (timed out), False if still active.
        """
        if self.is_deadline_exceeded:
            _LOGGER.info("Sber ack timeout reached — accepting commands")
            self._awaiting = False
            return True
        return False

    def _on_timeout(self) -> None:
        """Fallback timer callback: auto-clear after grace period."""
        if self._awaiting:
            _LOGGER.info("Sber ack timeout reached (timer) — accepting commands")
            self._awaiting = False

    def _cancel_timer(self) -> None:
        """Cancel the pending fallback timer if any."""
        handle = self._timeout_handle
        if handle is not None:
            if hasattr(handle, "cancel"):
                handle.cancel()
            self._timeout_handle = None
