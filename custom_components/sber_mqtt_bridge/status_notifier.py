"""Push notifications from the bridge to its own diagnostic entities.

The diagnostic entities (``binary_sensor.py``, ``sensor.py``) show values
the bridge keeps in memory — connection phase, what Sber knows, error
counters.  Instead of polling them, the bridge calls
:meth:`StatusNotifier.notify` wherever such a value may have changed, and
the entities re-read the bridge and write their state only when it differs.

Notifications are throttled because the busiest sources are high-rate: an
inbound MQTT message may bump the Sber error counter or the acknowledgement
set, and a burst of messages must not become a burst of state writes (every
write is an event on the bus and a row for the recorder).  The rule is
leading edge plus coalesced trailing edge:

* the first notification after a quiet period is delivered at once, so a
  single event is visible immediately;
* further notifications within :data:`STATUS_UPDATE_COOLDOWN` are merged
  into one delivery at the end of that window, so a burst costs at most one
  state write per window per entity, and its last value is never lost;
* a change of the *urgent key* (the connection phase and the link flag) is
  always delivered at once: automations react to a lost link, and such
  changes are rare by nature — reconnects are spaced by the backoff.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Hashable
from typing import TYPE_CHECKING

from homeassistant.core import callback

if TYPE_CHECKING:
    import asyncio

_LOGGER = logging.getLogger(__name__)

STATUS_UPDATE_COOLDOWN = 5.0
"""Seconds during which further non-urgent notifications are merged into one.

Diagnostic values are read by a person or an automation, not a control
loop: a few seconds of delay is invisible, while it caps an error storm at
twelve state writes a minute per entity.
"""

_NEVER: object = object()
"""Urgent-key placeholder before the first delivery; differs from any key."""


class StatusNotifier:
    """Throttled fan-out of "bridge status may have changed" to listeners."""

    __slots__ = ("_cooldown", "_last_key", "_listeners", "_loop", "_pending", "_shut_down", "_timer", "_urgent_key")

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        urgent_key: Callable[[], Hashable],
        *,
        cooldown: float = STATUS_UPDATE_COOLDOWN,
    ) -> None:
        """Create a notifier with no listeners.

        Args:
            loop: Event loop the cooldown timer runs on (HA's loop).
            urgent_key: Returns the part of the status whose change is
                delivered without waiting for the cooldown.
            cooldown: Seconds non-urgent notifications are merged over.
        """
        self._loop = loop
        self._urgent_key = urgent_key
        self._cooldown = cooldown
        self._listeners: list[Callable[[], None]] = []
        self._timer: asyncio.TimerHandle | None = None
        self._pending = False
        self._last_key: object = _NEVER
        self._shut_down = False

    def add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Call ``listener`` on every delivered notification.

        Args:
            listener: Zero-argument callable, run in the event loop.

        Returns:
            Callable that removes the listener.
        """
        self._listeners.append(listener)

        def _remove() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)
            if not self._listeners:
                # Nobody left to throttle for: drop the window so no timer
                # outlives the entities.
                self._pending = False
                self._cancel_timer()

        return _remove

    @callback
    def notify(self) -> None:
        """Report that a value shown by the listeners may have changed.

        Delivered at once when the urgent key changed or no cooldown is
        running; otherwise merged into the delivery at the end of the
        running cooldown.  Ignored without listeners (nothing to deliver,
        so no timer is armed) and after :meth:`shutdown`.
        """
        if self._shut_down or not self._listeners:
            return
        if self._timer is None or self._urgent_key() != self._last_key:
            self._deliver()
            return
        self._pending = True

    @callback
    def shutdown(self) -> None:
        """Deliver a pending notification now and stop accepting new ones.

        Cancels the cooldown timer, so nothing of the notifier outlives the
        bridge.
        """
        if self._pending:
            self._deliver()
        self._shut_down = True
        self._cancel_timer()

    def _deliver(self) -> None:
        self._cancel_timer()
        self._pending = False
        self._last_key = self._urgent_key()
        self._timer = self._loop.call_later(self._cooldown, self._on_cooldown_end)
        for listener in list(self._listeners):
            try:
                listener()
            except Exception:  # an entity must never break the bridge's own handling
                _LOGGER.exception("Bridge status listener failed")

    def _on_cooldown_end(self) -> None:
        self._timer = None
        if self._pending and not self._shut_down:
            self._deliver()

    def _cancel_timer(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
