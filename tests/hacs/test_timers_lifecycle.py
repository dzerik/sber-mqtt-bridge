"""Timer-lifecycle tests: reconnect ack-guard fallback + redefinitions persist.

Covers the W2A review findings:

1. ``ReconnectAckGuard.activate()`` must cancel the previous fallback
   timer — otherwise a stale timer from the prior connection clears
   the new connection's guard early and stale Sber "corrective"
   commands overwrite real HA state.
2. The grace-timeout fallback itself (``_on_timeout`` timer path and
   the ``timeout_check()`` poll path) must clear the guard — a broken
   fallback blocks inbound Sber commands forever.
3. ``RedefinitionsStore`` must expose a public shutdown that flushes
   pending (dirty) redefinitions and guarantees no debounce timer can
   fire after shutdown and overwrite a successor instance's options.

All timing is driven through a fake event loop clock — no real sleeps.
"""

from __future__ import annotations

from typing import Any

from custom_components.sber_mqtt_bridge import reconnect_ack_guard as guard_module
from custom_components.sber_mqtt_bridge.reconnect_ack_guard import ReconnectAckGuard
from custom_components.sber_mqtt_bridge.redefinitions_store import RedefinitionsStore


class FakeTimerHandle:
    """Timer handle stand-in mirroring asyncio.TimerHandle semantics."""

    def __init__(self, when: float, callback: Any) -> None:
        self.when = when
        self.callback = callback
        self.cancelled = False

    def cancel(self) -> None:
        """Mark the timer cancelled so the fake loop skips it."""
        self.cancelled = True


class FakeLoop:
    """Deterministic event-loop clock: fires call_later timers on advance()."""

    def __init__(self) -> None:
        self.now = 0.0
        self._timers: list[FakeTimerHandle] = []

    def call_later(self, delay: float, callback: Any, *args: Any) -> FakeTimerHandle:
        """Schedule callback at now+delay, like asyncio's call_later."""
        handle = FakeTimerHandle(self.now + delay, lambda: callback(*args))
        self._timers.append(handle)
        return handle

    def advance(self, dt: float) -> None:
        """Move the clock forward, firing every due non-cancelled timer in order."""
        self.now += dt
        while True:
            due = [t for t in self._timers if not t.cancelled and t.when <= self.now]
            if not due:
                break
            due.sort(key=lambda t: t.when)
            handle = due[0]
            self._timers.remove(handle)
            handle.callback()

    @property
    def pending(self) -> list[FakeTimerHandle]:
        """Return timers that are still armed (not fired, not cancelled)."""
        return [t for t in self._timers if not t.cancelled]


class _FakeTime:
    """time-module stand-in whose monotonic() follows a FakeLoop clock."""

    def __init__(self, loop: FakeLoop) -> None:
        self._loop = loop

    def monotonic(self) -> float:
        return self._loop.now


# ---------------------------------------------------------------------------
# ReconnectAckGuard fallback-timer lifecycle
# ---------------------------------------------------------------------------


class TestGuardStaleTimer:
    """A reconnect must never inherit the previous connection's timer."""

    def test_stale_timer_from_previous_activate_does_not_clear_new_guard(self) -> None:
        loop = FakeLoop()
        guard = ReconnectAckGuard()

        guard.activate(30, loop)  # connect #1 at t=0, deadline t=30
        loop.advance(15)
        guard.activate(30, loop)  # reconnect at t=15, deadline t=45

        loop.advance(15)  # t=30: connection #1's timer would fire here
        assert guard.is_awaiting is True, (
            "stale timer from the previous connection cleared the new guard early — "
            "stale Sber commands would be accepted before Sber acknowledged our state"
        )

        loop.advance(15)  # t=45: the *new* connection's own deadline
        assert guard.is_awaiting is False

    def test_flapping_connection_keeps_full_grace_window(self) -> None:
        loop = FakeLoop()
        guard = ReconnectAckGuard()
        # 5 rapid reconnects, 1s apart: only the last deadline may clear.
        for _ in range(5):
            guard.activate(30, loop)
            loop.advance(1)
        # t=5 now; last activation at t=4 → deadline t=34.
        loop.advance(28.5)  # t=33.5, all earlier deadlines passed
        assert guard.is_awaiting is True
        loop.advance(1)  # t=34.5 — past the final deadline
        assert guard.is_awaiting is False

    def test_old_timer_after_acknowledge_does_not_touch_next_guard(self) -> None:
        loop = FakeLoop()
        guard = ReconnectAckGuard()

        guard.activate(30, loop)  # deadline t=30
        loop.advance(10)
        guard.acknowledge()  # Sber acked connection #1
        guard.activate(30, loop)  # reconnect at t=10, deadline t=40

        loop.advance(25)  # t=35: past connection #1's deadline
        assert guard.is_awaiting is True
        loop.advance(10)  # t=45: past the new deadline
        assert guard.is_awaiting is False


class TestGuardTimeoutFallback:
    """Grace-timeout fallback: without it a silent Sber blocks commands forever."""

    def test_timer_clears_guard_after_grace_period(self) -> None:
        loop = FakeLoop()
        guard = ReconnectAckGuard()
        guard.activate(30, loop)

        loop.advance(29.9)
        assert guard.is_awaiting is True, "guard cleared before grace period elapsed"
        loop.advance(0.2)
        assert guard.is_awaiting is False, (
            "fallback timer did not clear the guard — inbound Sber commands "
            "would be blocked forever if Sber never sends status_request"
        )

    def test_timeout_check_clears_guard_exactly_once(self, monkeypatch) -> None:
        loop = FakeLoop()
        monkeypatch.setattr(guard_module, "time", _FakeTime(loop))
        guard = ReconnectAckGuard()
        guard.activate(30, loop)

        loop.now += 29.0  # move clock without firing the timer
        assert guard.timeout_check() is False
        assert guard.is_awaiting is True

        loop.now += 2.0  # past the deadline
        assert guard.timeout_check() is True
        assert guard.is_awaiting is False
        # Second poll must not report a fresh timeout for an already-cleared guard.
        assert guard.timeout_check() is False

    def test_timeout_check_inactive_guard_returns_false(self, monkeypatch) -> None:
        loop = FakeLoop()
        monkeypatch.setattr(guard_module, "time", _FakeTime(loop))
        guard = ReconnectAckGuard()
        loop.now += 100.0
        assert guard.timeout_check() is False
        assert guard.is_awaiting is False

    def test_acknowledge_cancels_pending_timer(self) -> None:
        loop = FakeLoop()
        guard = ReconnectAckGuard()
        guard.activate(30, loop)
        guard.acknowledge()
        assert loop.pending == [], "acknowledge left the fallback timer armed"
        loop.advance(60)  # a leaked timer firing here must not blow up
        assert guard.is_awaiting is False

    def test_timer_fire_is_noop_after_manual_clear(self) -> None:
        loop = FakeLoop()
        guard = ReconnectAckGuard()
        guard.activate(30, loop)
        guard.clear()
        loop.advance(60)
        assert guard.is_awaiting is False
        # Guard must be re-armable after a clear (fresh connection).
        guard.activate(30, loop)
        assert guard.is_awaiting is True
        loop.advance(31)
        assert guard.is_awaiting is False


class TestGuardIdempotency:
    """Repeated deactivation paths must be safe."""

    def test_clear_twice_then_acknowledge_is_safe(self) -> None:
        loop = FakeLoop()
        guard = ReconnectAckGuard()
        guard.activate(30, loop)
        guard.clear()
        guard.clear()
        guard.acknowledge()  # ack after clear: nothing to do, no error
        assert guard.is_awaiting is False

    def test_acknowledge_twice_is_safe(self) -> None:
        loop = FakeLoop()
        guard = ReconnectAckGuard()
        guard.activate(30, loop)
        guard.acknowledge()
        guard.acknowledge()
        assert guard.is_awaiting is False
        assert loop.pending == []


# ---------------------------------------------------------------------------
# RedefinitionsStore persist lifecycle
# ---------------------------------------------------------------------------


class _StubConfigEntries:
    """Records async_update_entry calls and mirrors HA's options replacement."""

    def __init__(self) -> None:
        self.written_options: list[dict] = []

    def async_update_entry(self, entry: Any, *, options: dict) -> None:
        self.written_options.append(options)
        entry.options = options


class _StubEntry:
    def __init__(self) -> None:
        self.options: dict = {}


class _StubHass:
    def __init__(self, loop: FakeLoop) -> None:
        self.loop = loop
        self.config_entries = _StubConfigEntries()


class _StubBridge:
    """Just the two attributes RedefinitionsStore reads from its bridge."""

    def __init__(self, loop: FakeLoop) -> None:
        self._hass = _StubHass(loop)
        self._entry = _StubEntry()


def _make_store() -> tuple[RedefinitionsStore, _StubBridge, FakeLoop]:
    loop = FakeLoop()
    bridge = _StubBridge(loop)
    return RedefinitionsStore(bridge), bridge, loop


class TestStoreDebounceFlush:
    """Normal debounced persistence still works after the shutdown additions."""

    async def test_flush_fires_after_debounce_window(self) -> None:
        store, bridge, loop = _make_store()
        await store.async_update("light.lamp", {"name": "  Лампа  ", "room": ""})

        loop.advance(1.9)
        assert bridge._entry.options == {}, "persisted before the debounce window elapsed"

        loop.advance(0.2)
        # Normalization must survive the round-trip: stripped name, empty room dropped.
        assert bridge._entry.options["redefinitions"] == {"light.lamp": {"name": "Лампа"}}

    async def test_rapid_updates_coalesce_into_one_write(self) -> None:
        store, bridge, loop = _make_store()
        await store.async_update("light.lamp", {"name": "A"})
        loop.advance(1.0)
        await store.async_update("light.lamp", {"name": "B"})
        loop.advance(3.0)
        assert len(bridge._hass.config_entries.written_options) == 1
        assert bridge._entry.options["redefinitions"] == {"light.lamp": {"name": "B"}}

    async def test_persisted_options_are_a_copy_not_the_live_dict(self) -> None:
        store, bridge, loop = _make_store()
        await store.async_update("light.lamp", {"name": "Lamp"})
        loop.advance(2.1)
        persisted = bridge._entry.options["redefinitions"]

        # In-memory mutation after flush (e.g. handle_rename_device writes
        # into raw) must not silently rewrite the already-persisted options.
        store.raw["light.lamp"]["name"] = "Mutated"
        store.raw["switch.new"] = {"name": "X"}
        assert persisted == {"light.lamp": {"name": "Lamp"}}


class TestStoreShutdown:
    """shutdown() must flush dirty state and kill the debounce timer."""

    async def test_shutdown_flushes_unsaved_changes(self) -> None:
        store, bridge, loop = _make_store()
        await store.async_update("light.lamp", {"name": "Lamp"})
        assert bridge._entry.options == {}  # still inside the debounce window

        store.shutdown()
        assert bridge._entry.options["redefinitions"] == {"light.lamp": {"name": "Lamp"}}, (
            "rename within 2s of shutdown was lost — shutdown must flush dirty state"
        )
        assert loop.pending == [], "shutdown left the debounce timer armed"

    async def test_no_timer_fires_after_shutdown(self) -> None:
        store, bridge, loop = _make_store()
        await store.async_update("light.lamp", {"name": "Old"})
        store.shutdown()

        # A successor bridge instance writes its own options after unload...
        successor_options = {"redefinitions": {"light.lamp": {"name": "New"}}}
        bridge._entry.options = successor_options

        # ...and a post-shutdown update must not arm a timer that would
        # later do a last-writer-wins overwrite of the successor's data.
        await store.async_update("light.other", {"name": "Late"})
        loop.advance(10)
        assert bridge._entry.options is successor_options, (
            "a debounce timer survived shutdown and overwrote the successor's options"
        )
        assert len(bridge._hass.config_entries.written_options) == 1

    async def test_shutdown_is_idempotent(self) -> None:
        store, bridge, _loop = _make_store()
        await store.async_update("light.lamp", {"name": "Lamp"})
        store.shutdown()
        store.shutdown()
        assert len(bridge._hass.config_entries.written_options) == 1

    def test_shutdown_clean_store_writes_nothing(self) -> None:
        store, bridge, _loop = _make_store()
        store.shutdown()
        assert bridge._hass.config_entries.written_options == []
        assert bridge._entry.options == {}


class TestStoreFlushNow:
    """flush_now() persists immediately but keeps the store alive."""

    async def test_flush_now_persists_and_store_stays_usable(self) -> None:
        store, bridge, loop = _make_store()
        await store.async_update("light.lamp", {"name": "A"})
        store.flush_now()
        assert bridge._entry.options["redefinitions"] == {"light.lamp": {"name": "A"}}
        assert loop.pending == []

        # Unlike shutdown, the store must keep persisting afterwards.
        await store.async_update("light.lamp", {"name": "B"})
        loop.advance(2.1)
        assert bridge._entry.options["redefinitions"] == {"light.lamp": {"name": "B"}}

    def test_flush_now_clean_store_is_noop(self) -> None:
        store, bridge, _loop = _make_store()
        store.flush_now()
        store.flush_now()
        assert bridge._hass.config_entries.written_options == []
