"""Contract tests for :class:`AckAudit`.

The real requirement captured here: after (re)connect, inbound Sber
commands must be blocked until Sber acknowledges our published state,
and a silent-rejection audit must fire exactly once per successful
config publish.  Breakage of either behaviour means Sber can overwrite
real HA state (guard failure) or users stop getting repair issues
(audit failure) -- both visible-to-user regressions.

Timing is deterministic:

* Most tests drive a virtual clock (:class:`_FakeLoop`) that implements
  the exact ``call_later`` / ``TimerHandle.cancel`` contract ``AckAudit``
  relies on.  No wall-clock sleeps, so a loaded CI runner cannot change
  the outcome.
* One test keeps a genuine ``asyncio`` loop to pin the integration with
  the real ``call_later``.  It never sleeps a fixed amount either: it
  awaits a *marker* timer scheduled after (and longer than) the audit
  timer.  ``loop.call_later`` fires callbacks in due-time order, so the
  audit always gets its chance before the marker resolves regardless of
  how slow the runner is.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from custom_components.sber_mqtt_bridge.ack_audit import AckAudit


class _FakeTimerHandle:
    """Stand-in for :class:`asyncio.TimerHandle` with cancel support."""

    def __init__(self, when: float, callback: Any) -> None:
        """Store the due time and the zero-arg callback to run."""
        self.when = when
        self.callback = callback
        self.cancelled = False

    def cancel(self) -> None:
        """Mark the timer cancelled so the fake loop skips it."""
        self.cancelled = True


class _FakeLoop:
    """Virtual-clock event loop exposing only what AckAudit uses."""

    def __init__(self) -> None:
        """Start the clock at t=0 with no armed timers."""
        self.now = 0.0
        self._timers: list[_FakeTimerHandle] = []

    def time(self) -> float:
        """Return the current virtual monotonic time."""
        return self.now

    def call_later(self, delay: float, callback: Any, *args: Any) -> _FakeTimerHandle:
        """Schedule ``callback`` at ``now + delay``, like asyncio does."""
        handle = _FakeTimerHandle(self.now + delay, lambda: callback(*args))
        self._timers.append(handle)
        return handle

    def advance(self, dt: float) -> None:
        """Move the clock forward, firing every due timer in due order."""
        self.now += dt
        while True:
            due = sorted(
                (t for t in self._timers if not t.cancelled and t.when <= self.now),
                key=lambda t: t.when,
            )
            if not due:
                break
            handle = due[0]
            self._timers.remove(handle)
            handle.callback()

    @property
    def pending(self) -> list[_FakeTimerHandle]:
        """Return timers that are still armed (not fired, not cancelled)."""
        return [t for t in self._timers if not t.cancelled]


class _StubHass:
    """Minimal HA stand-in exposing the loop attribute AckAudit needs."""

    def __init__(self, loop: Any) -> None:
        """Bind the (real or fake) event loop AckAudit will schedule on."""
        self.loop = loop


async def _await_after(delay: float) -> None:
    """Await a marker timer scheduled ``delay`` seconds from now.

    ``loop.call_later`` fires callbacks ordered by due time, so any timer
    armed earlier with a shorter delay is guaranteed to have run by the
    time this returns -- even if the loop stalls for seconds.  That makes
    "did the audit fire?" assertions deterministic without wall-clock
    sleeps.

    Args:
        delay: Seconds (loop time) to wait before resolving.
    """
    loop = asyncio.get_running_loop()
    marker: asyncio.Future[None] = loop.create_future()
    loop.call_later(delay, lambda: marker.done() or marker.set_result(None))
    await marker


def _make_audit(
    loop: _FakeLoop,
    calls: list[int],
    *,
    grace_timeout: float = 30,
    audit_delay: float = 60,
) -> AckAudit:
    """Build an AckAudit bound to the fake loop, recording audit runs."""
    return AckAudit(
        _StubHass(loop),
        grace_timeout=grace_timeout,
        audit_delay=audit_delay,
        on_audit=lambda: calls.append(1),
    )


class TestReconnectGuard:
    """The command-blocking half of AckAudit."""

    def test_not_awaiting_before_activate(self) -> None:
        # A freshly-constructed AckAudit must not block commands --
        # otherwise the first reconnect would silently swallow every user command.
        audit = _make_audit(_FakeLoop(), [])
        assert audit.is_awaiting is False

    def test_activate_post_connect_blocks_commands(self) -> None:
        audit = _make_audit(_FakeLoop(), [])
        audit.activate_post_connect()
        assert audit.is_awaiting is True

    def test_acknowledge_clears_guard(self) -> None:
        audit = _make_audit(_FakeLoop(), [])
        audit.activate_post_connect()
        audit.acknowledge()
        # Sber sent status_request / config_request -- commands must flow again.
        assert audit.is_awaiting is False

    def test_cancel_clears_guard(self) -> None:
        # Shutdown must not leave the guard armed (a pending timer could
        # fire after the bridge is gone).
        audit = _make_audit(_FakeLoop(), [])
        audit.activate_post_connect()
        audit.cancel()
        assert audit.is_awaiting is False

    def test_grace_timeout_unblocks_commands(self) -> None:
        # Sber may never acknowledge; the fallback timer must release the
        # guard, otherwise the bridge ignores user commands forever.
        loop = _FakeLoop()
        audit = _make_audit(loop, [], grace_timeout=30)
        audit.activate_post_connect()

        loop.advance(29)
        assert audit.is_awaiting is True, "guard released before the grace window elapsed"

        loop.advance(2)
        assert audit.is_awaiting is False

    def test_cancel_leaves_no_armed_timers(self) -> None:
        # async_stop() must not leave guard/audit timers behind: a late
        # callback would touch a torn-down bridge.
        loop = _FakeLoop()
        audit = _make_audit(loop, [])
        audit.activate_post_connect()
        audit.schedule_audit()
        assert loop.pending, "sanity: activate + schedule_audit must arm timers"

        audit.cancel()

        assert loop.pending == []


class TestSilentRejectionAudit:
    """Timer-driven silent-rejection detection."""

    @pytest.mark.asyncio
    async def test_scheduled_audit_runs_after_delay_on_real_loop(self) -> None:
        # Integration check against a genuine asyncio loop: the callback the
        # bridge injects must actually be invoked exactly once per schedule.
        # Zero fires means users never see repair issues for silently
        # rejected devices; more than one means duplicate repair issues.
        hass = _StubHass(asyncio.get_running_loop())
        calls: list[int] = []
        audit = AckAudit(hass, grace_timeout=1, audit_delay=0.01, on_audit=lambda: calls.append(1))

        audit.schedule_audit()
        await _await_after(0.02)

        assert calls == [1]

    def test_audit_does_not_fire_before_its_delay(self) -> None:
        loop = _FakeLoop()
        calls: list[int] = []
        audit = _make_audit(loop, calls, audit_delay=60)

        audit.schedule_audit()
        loop.advance(59)
        assert calls == [], "audit fired ahead of its delay — Sber had no time to answer"

        loop.advance(2)
        assert calls == [1]

    def test_reschedule_coalesces_and_restarts_the_delay(self) -> None:
        # Rapid config republishes (e.g. user toggling entities) must coalesce
        # into a single audit run measured from the *last* publish, not
        # duplicate repair-issue creation nor fire against a stale publish.
        loop = _FakeLoop()
        calls: list[int] = []
        audit = _make_audit(loop, calls, audit_delay=60)

        audit.schedule_audit()  # t=0 → would fire at t=60
        loop.advance(30)
        audit.schedule_audit()  # t=30 → must fire at t=90 instead

        loop.advance(31)  # t=61: past the *first* deadline
        assert calls == [], "the superseded timer still fired — duplicate/early audit run"

        loop.advance(30)  # t=91: past the new deadline
        assert calls == [1]

    def test_cancel_prevents_audit_from_running(self) -> None:
        # async_stop() must guarantee no audit fires after shutdown.
        loop = _FakeLoop()
        calls: list[int] = []
        audit = _make_audit(loop, calls, audit_delay=60)

        audit.schedule_audit()
        audit.cancel()
        loop.advance(600)

        assert calls == []

    @pytest.mark.asyncio
    async def test_cancel_prevents_audit_on_real_loop(self) -> None:
        hass = _StubHass(asyncio.get_running_loop())
        calls: list[int] = []
        audit = AckAudit(hass, grace_timeout=1, audit_delay=0.01, on_audit=lambda: calls.append(1))

        audit.schedule_audit()
        audit.cancel()
        await _await_after(0.02)

        assert calls == []

    def test_schedule_after_fire_arms_a_new_timer(self) -> None:
        # Each config publish gets its own audit: the handle is cleared when
        # the timer fires, so the next schedule_audit() must still work.
        loop = _FakeLoop()
        calls: list[int] = []
        audit = _make_audit(loop, calls, audit_delay=60)

        audit.schedule_audit()
        loop.advance(61)
        audit.schedule_audit()
        loop.advance(61)

        assert calls == [1, 1]
