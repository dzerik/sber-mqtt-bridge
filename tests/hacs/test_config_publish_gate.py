"""Tests for the coalescing gate in front of ``up/config`` (issue #44).

The reporter's Zigbee devices lost their room on every HA restart.  Cause:
each entity that became available triggered its own config publish, and
``build_devices_list_json`` skips entities without state — so Sber received a
series of *partial* device lists.  Sber treats every payload as the complete
list, drops the missing devices, then re-registers them as new and puts them
in the hub's room.

These tests pin the three tiers: publish at once when the set is complete,
coalesce while entities are still arriving, and give up (loudly) if some
never arrive.
"""

from __future__ import annotations

import asyncio
import contextlib

import pytest

from custom_components.sber_mqtt_bridge.config_publish_gate import ConfigPublishGate


class FakeLoop:
    """Deterministic stand-in for ``hass.loop`` — virtual clock, no sleeping."""

    def __init__(self) -> None:
        self._now = 0.0
        self._timers: list[list] = []  # [due, callback, cancelled]

    def time(self) -> float:
        return self._now

    def call_later(self, delay: float, callback) -> asyncio.TimerHandle:
        entry = [self._now + delay, callback, False]
        self._timers.append(entry)

        class _Handle:
            def cancel(_self) -> None:  # noqa: N805
                entry[2] = True

        return _Handle()  # type: ignore[return-value]

    def advance(self, seconds: float) -> None:
        """Move the clock, firing every timer that comes due."""
        target = self._now + seconds
        while True:
            due = [t for t in self._timers if not t[2] and t[0] <= target]
            if not due:
                break
            due.sort(key=lambda t: t[0])
            entry = due[0]
            self._now = entry[0]
            entry[2] = True
            entry[1]()
        self._now = target

    @property
    def pending(self) -> int:
        return sum(1 for t in self._timers if not t[2])


class GateHarness:
    """Gate wired to a fake loop with recording publish."""

    SETTLE = 5.0
    MAX_WAIT = 120.0

    def __init__(self, enabled: list[str], ready: set[str] | None = None) -> None:
        self.loop = FakeLoop()
        self.enabled = enabled
        self.ready = set(ready or ())
        self.publishes: list[set[str]] = []

        async def _publish() -> None:
            # Snapshot what the payload *would* contain at publish time.
            self.publishes.append(set(self.ready))

        def _create_task(coro, *, name=None):
            # ``request()`` is synchronous while ``publish`` is a coroutine.
            # The recording publish never awaits, so driving it to completion
            # here keeps the test free of loop plumbing.
            with contextlib.suppress(StopIteration):
                coro.send(None)
            return

        self.gate = ConfigPublishGate(
            loop=self.loop,
            settle_delay=self.SETTLE,
            max_wait=self.MAX_WAIT,
            get_enabled_entity_ids=lambda: list(self.enabled),
            get_ready_entity_ids=lambda: set(self.ready),
            publish=_publish,
            create_task=_create_task,
        )

    def arrive(self, entity_id: str) -> None:
        """Simulate an entity reporting its first state."""
        self.ready.add(entity_id)
        self.gate.request(f"{entity_id} available")


def test_publishes_immediately_when_everything_is_ready() -> None:
    """Fast path: a complete set must not sit out the settle window."""
    h = GateHarness(enabled=["light.a"], ready={"light.a"})

    h.gate.request("connect")

    assert h.publishes == [{"light.a"}], "a complete set must publish at once"
    assert h.loop.pending == 0, "no timer should be armed"


def test_startup_burst_collapses_into_one_complete_publish() -> None:
    """The reporter's scenario: three entities arriving one by one.

    Before the gate this produced three publishes with 1, 2 and 3 devices —
    the partial ones are what made Sber re-create devices in the hub's room.
    """
    h = GateHarness(enabled=["light.a", "light.b", "light.c"])

    h.arrive("light.a")
    h.loop.advance(1.0)
    h.arrive("light.b")
    h.loop.advance(1.0)
    assert h.publishes == [], "nothing may go out while entities are still arriving"

    h.arrive("light.c")  # set is now complete → fast path fires

    assert h.publishes == [{"light.a", "light.b", "light.c"}]


def test_partial_set_waits_for_the_settle_window() -> None:
    """Entities stop arriving before the set is complete → publish after quiet."""
    h = GateHarness(enabled=["light.a", "light.b"])

    h.arrive("light.a")
    h.loop.advance(GateHarness.SETTLE - 0.1)
    assert h.publishes == [], "must not publish before the window elapses"

    h.loop.advance(0.2)

    assert h.publishes == [{"light.a"}], "publishes once quiet"


def test_each_arrival_rearms_the_window() -> None:
    """A steady trickle must not publish once per entity."""
    h = GateHarness(enabled=["light.a", "light.b", "light.c", "light.d"])

    for entity_id in ("light.a", "light.b", "light.c"):
        h.arrive(entity_id)
        h.loop.advance(GateHarness.SETTLE - 1.0)  # always re-armed before firing

    assert h.publishes == [], "the window must restart on every arrival"

    h.loop.advance(GateHarness.SETTLE)
    assert len(h.publishes) == 1, "exactly one publish for the whole burst"


def test_hard_cap_publishes_even_if_an_entity_never_arrives(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A device that never reports must not block the config forever."""
    h = GateHarness(enabled=["light.a", "light.ghost"])

    h.arrive("light.a")
    # Keep re-arming just under the settle window for longer than the cap.
    with caplog.at_level("WARNING"):
        for _ in range(40):
            h.loop.advance(GateHarness.SETTLE - 1.0)
            h.gate.request("still waiting")

    assert h.publishes, "the cap must force a publish"
    assert h.publishes[0] == {"light.a"}
    assert "light.ghost" in caplog.text, "the missing entity must be named in the log"


def test_cap_is_measured_from_the_first_request() -> None:
    """The cap is an absolute deadline, not a per-request timeout."""
    h = GateHarness(enabled=["light.a", "light.ghost"])

    h.arrive("light.a")
    h.loop.advance(GateHarness.MAX_WAIT + 1.0)

    assert len(h.publishes) == 1


async def test_flush_now_bypasses_coalescing() -> None:
    """Explicit user action publishes immediately and drops the pending timer."""
    h = GateHarness(enabled=["light.a", "light.b"])
    h.arrive("light.a")
    assert h.loop.pending == 1

    await h.gate.flush_now()

    assert h.publishes == [{"light.a"}]
    assert h.loop.pending == 0, "flush must cancel the pending timer"

    h.loop.advance(GateHarness.MAX_WAIT * 2)
    assert len(h.publishes) == 1, "the cancelled timer must not fire later"


def test_cancel_drops_pending_publish() -> None:
    """Shutdown must not leave a timer that publishes after unload."""
    h = GateHarness(enabled=["light.a", "light.b"])
    h.arrive("light.a")

    h.gate.cancel()
    h.loop.advance(GateHarness.MAX_WAIT * 2)

    assert h.publishes == [], "no publish may happen after cancel"
    assert h.loop.pending == 0


def test_has_pending_reflects_the_armed_timer() -> None:
    """The bridge uses this to reason about shutdown ordering."""
    h = GateHarness(enabled=["light.a", "light.b"])
    assert h.gate.has_pending is False

    h.arrive("light.a")
    assert h.gate.has_pending is True

    h.loop.advance(GateHarness.SETTLE)
    assert h.gate.has_pending is False


def test_empty_enabled_set_publishes_immediately() -> None:
    """No entities configured is a *complete* set, not an incomplete one."""
    h = GateHarness(enabled=[])

    h.gate.request("connect")

    assert len(h.publishes) == 1
    assert h.loop.pending == 0


def test_updated_delays_take_effect_on_the_next_burst() -> None:
    """Options flow can retune the gate without a restart."""
    h = GateHarness(enabled=["light.a", "light.b"])
    h.gate.update_delays(settle_delay=1.0, max_wait=10.0)

    h.arrive("light.a")
    h.loop.advance(1.5)

    assert h.publishes == [{"light.a"}], "the shorter window must be honoured"
