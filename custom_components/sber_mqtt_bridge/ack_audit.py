"""Sber acknowledgment tracking: reconnect guard + silent-rejection audit.

Two tightly-coupled concerns live here:

1. **Reconnect guard** — after each MQTT (re)connect, we block inbound
   Sber commands until Sber acknowledges our published state (via
   ``status_request`` / ``config_request``).  Without this, Sber cloud
   can override real HA state with its stale cache.

2. **Silent-rejection audit** — a fixed time after publishing config,
   we run a detection pass for entities Sber accepted in the config
   handshake but never sent any ``status_request`` for: those devices
   are silently rejected and need user intervention (reported as HA
   repair issues).

Both pieces share the same concept ("post-reconnect Sber handshake
protocol") but were previously scattered across the bridge as four
private methods plus a standalone :class:`ReconnectAckGuard`.  This
module wraps them in a single :class:`AckAudit` helper so the bridge
just calls ``activate_post_connect()`` / ``schedule_audit()`` /
``acknowledge()`` / ``cancel()`` and lets the helper own the timers
and state.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

from .reconnect_ack_guard import ReconnectAckGuard

if TYPE_CHECKING:
    import asyncio

    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


class AckAudit:
    """Owns the ack guard + silent-rejection audit scheduling.

    The audit-execution callback is injected by the bridge
    (``on_audit``) so this module stays ignorant of bridge internals
    (unacknowledged entity list, HA repair triggering, etc.).
    """

    __slots__ = ("_audit_delay", "_audit_handle", "_grace_timeout", "_guard", "_hass", "_on_audit")

    def __init__(
        self,
        hass: HomeAssistant,
        *,
        grace_timeout: float,
        audit_delay: float,
        on_audit: Callable[[], None],
    ) -> None:
        """Create an audit helper.

        Args:
            hass: Home Assistant core — we need the event loop for timers.
            grace_timeout: Seconds before the reconnect guard auto-clears.
            audit_delay: Seconds after ``schedule_audit()`` before
                ``on_audit`` fires.
            on_audit: Bridge-provided callback that performs the actual
                detection (reads unacknowledged entity list, logs,
                creates repair issues).  Called with no arguments.
        """
        self._guard = ReconnectAckGuard()
        self._hass = hass
        self._grace_timeout = grace_timeout
        self._audit_delay = audit_delay
        self._on_audit = on_audit
        self._audit_handle: asyncio.TimerHandle | None = None

    # Reconnect guard ---------------------------------------------------

    @property
    def is_awaiting(self) -> bool:
        """Return True while still blocking incoming Sber commands."""
        return self._guard.is_awaiting

    def activate_post_connect(self) -> None:
        """Arm the guard after a successful MQTT (re)connect handshake."""
        self._guard.activate(self._grace_timeout, self._hass.loop)

    def acknowledge(self) -> None:
        """Clear the guard — Sber has acknowledged our state."""
        self._guard.acknowledge()

    def timeout_check(self) -> bool:
        """Poll-based fallback: returns True if the guard just timed out."""
        return self._guard.timeout_check()

    # Silent-rejection audit --------------------------------------------

    @property
    def audit_delay(self) -> float:
        """Return the configured audit delay in seconds."""
        return self._audit_delay

    def schedule_audit(self) -> None:
        """Schedule an audit run ``audit_delay`` seconds from now.

        Cancels any previously pending audit so only the most recent
        config publish has a live timer — avoids duplicate runs if
        the bridge republishes in rapid succession.
        """
        if self._audit_handle is not None:
            self._audit_handle.cancel()
        self._audit_handle = self._hass.loop.call_later(self._audit_delay, self._fire_audit)

    def _fire_audit(self) -> None:
        self._audit_handle = None
        self._on_audit()

    # Shutdown ----------------------------------------------------------

    def cancel(self) -> None:
        """Cancel any pending audit timer and clear the guard.

        Safe to call multiple times (idempotent) — used during
        :meth:`SberBridge.async_stop` so the timer can't fire after
        the bridge has been torn down.
        """
        if self._audit_handle is not None:
            self._audit_handle.cancel()
            self._audit_handle = None
        self._guard.clear()
