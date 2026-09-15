"""Throttled status push from the bridge to its diagnostic entities (``status_notifier.py``)."""

from __future__ import annotations

from collections.abc import Generator
from datetime import timedelta

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.sber_mqtt_bridge.reconnect_ack_guard import ReconnectAckGuard
from custom_components.sber_mqtt_bridge.status_notifier import StatusNotifier

COOLDOWN = 5.0


class _Harness:
    """A notifier with one counting listener and a settable urgent key."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self.key = "ready"
        self.calls = 0
        self.notifier = StatusNotifier(hass.loop, lambda: self.key, cooldown=COOLDOWN)
        self.remove = self.notifier.add_listener(self._listener)

    def _listener(self) -> None:
        self.calls += 1

    async def wait(self, seconds: float) -> None:
        async_fire_time_changed(self.hass, dt_util.utcnow() + timedelta(seconds=seconds))
        await self.hass.async_block_till_done()


@pytest.fixture
def harness(hass: HomeAssistant) -> Generator[_Harness]:
    """Build the harness and shut the notifier down after the test."""
    built = _Harness(hass)
    yield built
    built.notifier.shutdown()


async def test_first_notification_is_delivered_at_once(harness: _Harness) -> None:
    harness.notifier.notify()
    assert harness.calls == 1


async def test_burst_is_merged_into_one_trailing_delivery(harness: _Harness) -> None:
    for _ in range(10):
        harness.notifier.notify()
    assert harness.calls == 1

    await harness.wait(COOLDOWN + 1)
    assert harness.calls == 2

    await harness.wait(3 * COOLDOWN)
    assert harness.calls == 2, "no trailing delivery without a new notification"


async def test_urgent_key_change_skips_the_cooldown(harness: _Harness) -> None:
    harness.notifier.notify()
    harness.notifier.notify()
    harness.key = "connecting"
    harness.notifier.notify()
    assert harness.calls == 2

    await harness.wait(COOLDOWN + 1)
    assert harness.calls == 2, "the urgent delivery already carried the pending change"


async def test_quiet_period_reopens_the_leading_edge(harness: _Harness) -> None:
    harness.notifier.notify()
    await harness.wait(COOLDOWN + 1)
    harness.notifier.notify()
    assert harness.calls == 2


async def test_without_listeners_nothing_is_scheduled(hass: HomeAssistant, harness: _Harness) -> None:
    harness.notifier.notify()
    harness.notifier.notify()
    harness.remove()
    harness.remove()  # removing twice is harmless

    await harness.wait(COOLDOWN + 1)
    harness.notifier.notify()
    assert harness.calls == 1
    assert harness.notifier._timer is None, "a notifier nobody listens to must not hold a timer"


async def test_shutdown_flushes_pending_and_ignores_later_notifications(harness: _Harness) -> None:
    harness.notifier.notify()
    harness.notifier.notify()
    harness.notifier.shutdown()
    assert harness.calls == 2

    harness.notifier.notify()
    await harness.wait(COOLDOWN + 1)
    assert harness.calls == 2
    assert harness.notifier._timer is None


async def test_failing_listener_does_not_stop_the_others(
    hass: HomeAssistant, harness: _Harness, caplog: pytest.LogCaptureFixture
) -> None:
    def _broken() -> None:
        raise RuntimeError("entity bug")

    harness.notifier.add_listener(_broken)
    harness.notifier.add_listener(harness._listener)

    harness.notifier.notify()

    assert harness.calls == 2
    assert "Bridge status listener failed" in caplog.text


async def test_guard_timer_reports_its_expiry(hass: HomeAssistant) -> None:
    expired: list[bool] = []
    guard = ReconnectAckGuard(on_expire=lambda: expired.append(guard.is_awaiting))

    guard.activate(1.0, hass.loop)
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=2))
    await hass.async_block_till_done()

    assert expired == [False], "reported once, after the guard is already cleared"
