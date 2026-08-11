"""Coalescing gate in front of the Sber ``up/config`` publish.

Sber treats every ``up/config`` message as the **authoritative, complete**
device list: a device missing from a payload is dropped cloud-side, and when
it shows up in a later payload it is registered anew — losing the room the
user assigned and landing in the hub's room instead.

Home Assistant, meanwhile, brings entities up gradually: a Zigbee coordinator
can take a minute to report all of its devices, and
``build_devices_list_json`` skips entities that have not received their first
state yet.  Publishing on every "entity became available" event therefore sent
a *series* of partial lists during startup — exactly the destructive pattern
above (issue #44).

This gate turns that burst into a single complete publish:

* **Fast path** — every enabled entity already has state: publish at once, do
  not sit out the settle window.  This is the common case.
* **Settle window** — entities are still arriving: each request re-arms a
  short timer, so the publish happens once the stream goes quiet.
* **Hard cap** — something never loads (a stick that did not come up, a
  disabled device): publish anyway once the cap expires and log which
  entities are missing, instead of waiting forever.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

_LOGGER = logging.getLogger(__name__)


class ConfigPublishGate:
    """Coalesce config-publish requests into one complete payload.

    The gate owns no device state: it reads the enabled and the
    ready (state-filled) entity sets through callbacks, so the bridge
    remains the single source of truth.
    """

    def __init__(
        self,
        *,
        loop: asyncio.AbstractEventLoop,
        settle_delay: float,
        max_wait: float,
        get_enabled_entity_ids: Callable[[], list[str]],
        get_ready_entity_ids: Callable[[], set[str]],
        get_cloud_known_ids: Callable[[], frozenset[str]],
        publish: Callable[[], Awaitable[None]],
        create_task: Callable[..., asyncio.Task],
    ) -> None:
        """Initialize the gate.

        Args:
            loop: Event loop used for timers (``hass.loop``).
            settle_delay: Seconds of quiet before publishing while entities
                are still arriving.
            max_wait: Upper bound, from the first pending request, after which
                an incomplete config is published anyway.
            get_enabled_entity_ids: Callable returning the entity IDs that
                should end up in the payload.
            get_ready_entity_ids: Callable returning the entity IDs that
                currently have state and would actually be serialized.
            get_cloud_known_ids: Callable returning the entity IDs the Sber
                cloud currently holds.  Only these block a publish: omitting
                a device the cloud has is destructive, whereas a device it
                has never seen can safely join a later payload.
            publish: Async callback performing the real config publish.
            create_task: Bridge helper that schedules a task with error
                logging.
        """
        self._loop = loop
        self._settle_delay = settle_delay
        self._max_wait = max_wait
        self._get_enabled_entity_ids = get_enabled_entity_ids
        self._get_ready_entity_ids = get_ready_entity_ids
        self._get_cloud_known_ids = get_cloud_known_ids
        self._publish = publish
        self._create_task = create_task

        self._timer: asyncio.TimerHandle | None = None
        self._pending_since: float | None = None
        """Loop time of the first request in the current burst."""
        self._ready_event = asyncio.Event()
        """Set whenever the enabled set is fully loaded — see wait_until_ready."""

    def update_delays(self, *, settle_delay: float, max_wait: float) -> None:
        """Update the timing policy at runtime (options flow reload)."""
        self._settle_delay = settle_delay
        self._max_wait = max_wait

    @property
    def has_pending(self) -> bool:
        """Return True while a publish is scheduled but not yet fired."""
        return self._timer is not None

    def request(self, reason: str) -> None:
        """Ask for a config publish, coalescing with any pending request.

        Args:
            reason: Short human-readable trigger description, logged at DEBUG
                so bursts can be traced back to their cause.
        """
        missing = self._missing_entity_ids()
        if not missing:
            # Complete set — nothing to gain from waiting.
            _LOGGER.debug("Config publish (%s): all entities ready, publishing now", reason)
            self._ready_event.set()
            self._fire()
            return

        now = self._loop.time()
        if self._pending_since is None:
            self._pending_since = now
            blocking = self._blocking_entity_ids()
            if blocking:
                _LOGGER.debug(
                    "Config publish (%s): holding — %d device(s) the cloud already holds have not reported yet: %s",
                    reason,
                    len(blocking),
                    ", ".join(sorted(blocking)),
                )
            else:
                _LOGGER.debug(
                    "Config publish (%s): coalescing while %d entity(ies) still load",
                    reason,
                    len(missing),
                )
        self._cancel_timer()
        deadline = self._pending_since + self._max_wait
        delay = min(self._settle_delay, max(0.0, deadline - now))
        self._timer = self._loop.call_later(delay, self._on_timer)

    def cancel(self) -> None:
        """Drop any pending publish (bridge shutdown)."""
        self._cancel_timer()
        self._pending_since = None

    async def wait_until_ready(self) -> bool:
        """Block until every enabled entity has state, or the cap expires.

        Used by the connect handshake, which publishes config before states
        and before subscribing: firing it while entities are still loading
        would ship the very partial list this gate exists to prevent.

        Returns:
            True if the set became complete, False if the cap expired first
            (the caller should publish anyway — a device that never reports
            must not block the bridge forever).
        """
        if not self._blocking_entity_ids():
            return True

        self._ready_event.clear()
        try:
            async with asyncio.timeout(self._max_wait):
                await self._ready_event.wait()
        except TimeoutError:
            missing = self._blocking_entity_ids()
            _LOGGER.warning(
                "Publishing Sber config after waiting %.0fs without %d entity(ies): %s. "
                "Sber registers late arrivals as new devices and moves them to the hub's room; "
                "check whether these entities are available in Home Assistant.",
                self._max_wait,
                len(missing),
                ", ".join(sorted(missing)),
            )
            return False
        return True

    async def flush_now(self) -> None:
        """Publish immediately, bypassing coalescing.

        Used by explicit user actions (panel "Re-publish", Sber
        ``config_request``) where waiting would be surprising.
        """
        self.cancel()
        await self._publish()

    def _missing_entity_ids(self) -> list[str]:
        """Return enabled entity IDs that have no state yet."""
        ready = self._get_ready_entity_ids()
        return [entity_id for entity_id in self._get_enabled_entity_ids() if entity_id not in ready]

    def _blocking_entity_ids(self) -> list[str]:
        """Return the entities whose absence from a publish would be destructive.

        Only devices the cloud already holds qualify: dropping one of those
        makes Sber re-register it as new and move it to the hub's room.  A
        device the cloud has never seen can safely arrive in a later payload,
        so a battery sensor that wakes up minutes after start does not hold
        up the rest of the house on first setup.
        """
        cloud_known = self._get_cloud_known_ids()
        return [entity_id for entity_id in self._missing_entity_ids() if entity_id in cloud_known]

    def _cancel_timer(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def _on_timer(self) -> None:
        """Fire after the settle window or the hard cap."""
        self._timer = None
        missing = self._blocking_entity_ids()
        now = self._loop.time()
        cap_reached = self._pending_since is None or now - self._pending_since >= self._max_wait
        if missing and not cap_reached:
            # The stream went quiet, but a device the cloud holds is still
            # absent — publishing now would drop it.  Silence is not evidence
            # that it will never arrive: a battery sensor may report minutes
            # later.  Keep waiting until the hard cap decides.
            _LOGGER.debug(
                "Config publish: still holding for %d cloud-known device(s): %s",
                len(missing),
                ", ".join(sorted(missing)),
            )
            deadline = self._pending_since + self._max_wait
            self._timer = self._loop.call_later(max(0.0, min(self._settle_delay, deadline - now)), self._on_timer)
            return
        if missing:
            _LOGGER.warning(
                "Publishing Sber config without %d entity(ies) that never reported state: %s. "
                "Sber registers late arrivals as new devices and moves them to the hub's room; "
                "check whether these entities are available in Home Assistant.",
                len(missing),
                ", ".join(sorted(missing)),
            )
        self._fire()

    def _fire(self) -> None:
        """Perform the publish and reset the burst."""
        self._cancel_timer()
        self._pending_since = None
        self._create_task(self._publish(), name="config_publish_gate")
