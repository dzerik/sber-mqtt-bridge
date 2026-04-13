"""Contract tests for :class:`AckAudit`.

The real requirement captured here: after (re)connect, inbound Sber
commands must be blocked until Sber acknowledges our published state,
and a silent-rejection audit must fire exactly once per successful
config publish.  Breakage of either behaviour means Sber can overwrite
real HA state (guard failure) or users stop getting repair issues
(audit failure) -- both visible-to-user regressions.

Tests poke the real Home Assistant event loop via a lightweight stub
rather than a pure MagicMock so the call_later timer contract is
exercised for real.
"""

from __future__ import annotations

import asyncio

import pytest

from custom_components.sber_mqtt_bridge.ack_audit import AckAudit


class _StubHass:
    """Minimal HA stand-in exposing the loop attribute AckAudit needs."""

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop


class TestReconnectGuard:
    """The command-blocking half of AckAudit.

    Sync tests use a fresh event loop since the guard itself schedules a
    fallback timer on activate and needs a live loop to register with.
    """

    def _stub(self) -> tuple[AckAudit, asyncio.AbstractEventLoop]:
        loop = asyncio.new_event_loop()
        return AckAudit(_StubHass(loop), grace_timeout=30, audit_delay=60, on_audit=lambda: None), loop

    def test_not_awaiting_before_activate(self) -> None:
        audit, loop = self._stub()
        try:
            # A freshly-constructed AckAudit must not block commands --
            # otherwise the first reconnect would silently swallow every user command.
            assert audit.is_awaiting is False
        finally:
            loop.close()

    def test_activate_post_connect_blocks_commands(self) -> None:
        audit, loop = self._stub()
        try:
            audit.activate_post_connect()
            assert audit.is_awaiting is True
        finally:
            audit.cancel()
            loop.close()

    def test_acknowledge_clears_guard(self) -> None:
        audit, loop = self._stub()
        try:
            audit.activate_post_connect()
            audit.acknowledge()
            # Sber sent status_request / config_request -- commands must flow again.
            assert audit.is_awaiting is False
        finally:
            loop.close()

    def test_cancel_clears_guard(self) -> None:
        # Shutdown must not leave the guard armed (a pending timer could
        # fire after the bridge is gone).
        audit, loop = self._stub()
        try:
            audit.activate_post_connect()
            audit.cancel()
            assert audit.is_awaiting is False
        finally:
            loop.close()


class TestSilentRejectionAudit:
    """Timer-driven silent-rejection detection."""

    @pytest.mark.asyncio
    async def test_scheduled_audit_runs_after_delay(self) -> None:
        hass = _StubHass(asyncio.get_running_loop())
        calls: list[int] = []
        audit = AckAudit(hass, grace_timeout=1, audit_delay=0.05, on_audit=lambda: calls.append(1))
        audit.schedule_audit()
        await asyncio.sleep(0.15)
        # The on_audit callback must fire exactly once per schedule_audit().
        # Zero fires means users never see repair issues for silently rejected devices.
        assert calls == [1]

    @pytest.mark.asyncio
    async def test_reschedule_cancels_previous_timer(self) -> None:
        # Rapid config republishes (e.g. user toggling entities) must coalesce
        # into a single audit run, not duplicate repair-issue creation.
        hass = _StubHass(asyncio.get_running_loop())
        calls: list[int] = []
        audit = AckAudit(hass, grace_timeout=1, audit_delay=0.2, on_audit=lambda: calls.append(1))
        audit.schedule_audit()
        await asyncio.sleep(0.05)
        audit.schedule_audit()  # cancels first timer, starts a fresh one
        await asyncio.sleep(0.35)
        assert calls == [1]

    @pytest.mark.asyncio
    async def test_cancel_prevents_audit_from_running(self) -> None:
        # async_stop() must guarantee no audit fires after shutdown.
        hass = _StubHass(asyncio.get_running_loop())
        calls: list[int] = []
        audit = AckAudit(hass, grace_timeout=1, audit_delay=0.05, on_audit=lambda: calls.append(1))
        audit.schedule_audit()
        audit.cancel()
        await asyncio.sleep(0.15)
        assert calls == []
