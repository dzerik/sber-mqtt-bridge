"""Tests for the MQTT transport core (MqttClientService) and payload parsing.

Covers the reconnect loop, exponential backoff, the per-message exception
barrier, runtime ``verify_ssl`` switching and structural validation of
untrusted inbound Sber payloads (``parse_sber_command`` /
``parse_sber_status_request``).

Only the external boundary (``aiomqtt.Client``) is faked; hooks are real
coroutines recording observable behavior.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import aiomqtt
import pytest

from custom_components.sber_mqtt_bridge import mqtt_client_service as mcs_module
from custom_components.sber_mqtt_bridge.mqtt_client_service import (
    MqttClientService,
    MqttServiceHooks,
    SberMqttCredentials,
)
from custom_components.sber_mqtt_bridge.sber_protocol import (
    parse_sber_command,
    parse_sber_status_request,
)

# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _StubHass:
    """Minimal HomeAssistant stand-in: runs executor jobs inline."""

    async def async_add_executor_job(self, func, *args):
        return func(*args)

    def async_create_background_task(self, target, name, eager_start=True):
        return asyncio.get_running_loop().create_task(target, name=name)


class _FakeMessage:
    """Minimal aiomqtt message stand-in (topic + payload)."""

    def __init__(self, topic: str, payload: bytes) -> None:
        self.topic = topic
        self.payload = payload


class _MessageStream:
    """Async iterator of messages driven by an asyncio.Queue.

    Push ``_FakeMessage`` to deliver a message, an ``Exception`` instance to
    raise it from the stream (simulates a broker drop mid-session), or
    ``None`` to end the stream (clean session close).
    """

    def __init__(self) -> None:
        self.queue: asyncio.Queue[Any] = asyncio.Queue()

    def __aiter__(self) -> _MessageStream:
        return self

    async def __anext__(self):
        item = await self.queue.get()
        if item is None:
            raise StopAsyncIteration
        if isinstance(item, Exception):
            raise item
        return item

    def __len__(self) -> int:
        return self.queue.qsize()


class _FakeClient:
    """Fake aiomqtt.Client: async context manager + scripted message stream."""

    def __init__(self, *, connect_error: Exception | None = None, connect_gate: asyncio.Event | None = None) -> None:
        self.connect_error = connect_error
        self.connect_gate = connect_gate
        """When set, the handshake does not complete until the event is set (a silent broker)."""
        self.stream = _MessageStream()
        self.published: list[tuple[str, Any]] = []
        self.subscribed: list[str] = []
        self.entered = False
        self.exit_count = 0

    async def __aenter__(self) -> _FakeClient:
        if self.connect_gate is not None:
            await self.connect_gate.wait()
        if self.connect_error is not None:
            raise self.connect_error
        self.entered = True
        return self

    async def __aexit__(self, *exc_info) -> bool:
        self.exit_count += 1
        return False

    @property
    def messages(self) -> _MessageStream:
        return self.stream

    async def publish(self, topic: str, payload: Any) -> None:
        self.published.append((topic, payload))

    async def subscribe(self, topic: str) -> None:
        self.subscribed.append(topic)


class _ClientFactory:
    """Replaces ``aiomqtt.Client``: hands out scripted clients, records kwargs."""

    def __init__(self, clients: list[_FakeClient]) -> None:
        self.clients = clients
        self.calls: list[dict[str, Any]] = []

    def __call__(self, *args: Any, **kwargs: Any) -> _FakeClient:
        self.calls.append(kwargs)
        if not self.clients:
            raise AssertionError("factory exhausted: unexpected extra connect attempt")
        return self.clients.pop(0)


class _Hooks:
    """Recording hook set with configurable behavior."""

    def __init__(self) -> None:
        self.messages: list[tuple[str, bytes]] = []
        self.connected_count = 0
        self.disconnects: list[tuple[Exception, bool]] = []
        self.keep_running_answers: list[bool] = []
        self.on_message_error: Exception | None = None
        self.on_message_error_payload: bytes | None = None
        self.on_connected_error: Exception | None = None
        self.on_disconnected_error: Exception | None = None
        self.message_started = asyncio.Event()
        self.block_on_message = False

    def as_hooks(self) -> MqttServiceHooks:
        return MqttServiceHooks(
            on_message=self._on_message,
            on_connected=self._on_connected,
            on_disconnected=self._on_disconnected,
        )

    async def _on_message(self, topic: str, payload: bytes) -> None:
        self.message_started.set()
        if self.block_on_message:
            await asyncio.Event().wait()  # blocks until cancelled
        if self.on_message_error is not None and payload == self.on_message_error_payload:
            raise self.on_message_error
        self.messages.append((topic, payload))

    async def _on_connected(self, client) -> None:
        self.connected_count += 1
        if self.on_connected_error is not None:
            err, self.on_connected_error = self.on_connected_error, None
            raise err

    async def _on_disconnected(self, err: Exception, unexpected: bool) -> bool:
        self.disconnects.append((err, unexpected))
        if self.on_disconnected_error is not None:
            hook_err, self.on_disconnected_error = self.on_disconnected_error, None
            raise hook_err
        if self.keep_running_answers:
            return self.keep_running_answers.pop(0)
        return True


CREDS = SberMqttCredentials(
    login="user",
    password="pass",
    broker="broker.test",
    port=8883,
    verify_ssl=True,
)


@pytest.fixture
def hooks() -> _Hooks:
    """Recording hooks."""
    return _Hooks()


@pytest.fixture
def fast_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Replace asyncio.sleep with an instant recorder; return recorded delays."""
    recorded: list[float] = []
    real_sleep = asyncio.sleep

    async def _sleep(delay: float, *args: Any) -> None:
        recorded.append(delay)
        await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", _sleep)
    return recorded


@pytest.fixture
def no_jitter(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the reconnect jitter deterministic (factor 1.0)."""
    monkeypatch.setattr(mcs_module.random, "uniform", lambda a, b: 1.0)


@pytest.fixture
def stub_ssl(monkeypatch: pytest.MonkeyPatch) -> list[bool]:
    """Stub out create_ssl_context; return the list of ``verify`` args seen."""
    calls: list[bool] = []

    def _fake_create(verify: bool = True) -> object:
        calls.append(verify)
        return object()

    monkeypatch.setattr(mcs_module, "create_ssl_context", _fake_create)
    return calls


def _make_service(hooks: _Hooks, *, reconnect_min: int = 1, reconnect_max: int = 8) -> MqttClientService:
    """Build a service instance against the stub hass."""
    return MqttClientService(
        hass=_StubHass(),
        credentials=CREDS,
        hooks=hooks.as_hooks(),
        reconnect_min=reconnect_min,
        reconnect_max=reconnect_max,
    )


def _install_factory(monkeypatch: pytest.MonkeyPatch, clients: list[_FakeClient]) -> _ClientFactory:
    """Patch aiomqtt.Client with a scripted factory."""
    factory = _ClientFactory(clients)
    monkeypatch.setattr(aiomqtt, "Client", factory)
    return factory


async def _wait_for(predicate) -> None:
    """Poll a predicate without real sleeping (0-delay event-loop yields)."""
    async with asyncio.timeout(1.0):
        while not predicate():  # noqa: ASYNC110 — deliberate 0-delay yield polling
            await asyncio.sleep(0)


async def test_queued_inbound_count_reports_backlog_seen_by_connect_hook(monkeypatch, hooks, stub_ssl) -> None:
    """The connect hook sees how many messages already wait; consumption drains the count."""
    client = _FakeClient()
    _install_factory(monkeypatch, [client])
    service = _make_service(hooks)
    assert service.queued_inbound_count == 0, "no client, no backlog"

    seen_in_hook: list[int] = []
    recording = hooks.as_hooks()

    async def _on_connected(live_client) -> None:
        client.stream.queue.put_nowait(_FakeMessage("down/status_request", b"{}"))
        client.stream.queue.put_nowait(_FakeMessage("down/commands", b"{}"))
        seen_in_hook.append(service.queued_inbound_count)
        await recording.on_connected(live_client)

    service._hooks = MqttServiceHooks(
        on_message=recording.on_message, on_connected=_on_connected, on_disconnected=recording.on_disconnected
    )
    task = asyncio.create_task(service.run())
    try:
        await _wait_for(lambda: len(hooks.messages) == 2)
        assert seen_in_hook == [2]
        assert service.queued_inbound_count == 0
    finally:
        task.cancel()
        await asyncio.wait_for(task, 1.0)


# ---------------------------------------------------------------------------
# Message barrier: one bad message must not kill the transport
# ---------------------------------------------------------------------------


async def test_bad_message_does_not_kill_loop(monkeypatch, hooks, stub_ssl) -> None:
    """A hook exception on ONE message is contained: session survives and the next message is processed."""
    client = _FakeClient()
    _install_factory(monkeypatch, [client])
    hooks.on_message_error = AttributeError("'list' object has no attribute 'get'")
    hooks.on_message_error_payload = b"[1,2,3]"

    service = _make_service(hooks)
    task = asyncio.create_task(service.run())
    try:
        client.stream.queue.put_nowait(_FakeMessage("down/commands", b"[1,2,3]"))
        client.stream.queue.put_nowait(_FakeMessage("down/commands", b'{"devices":{}}'))
        await _wait_for(lambda: hooks.messages)

        # The good message after the poison one was processed...
        assert hooks.messages == [("down/commands", b'{"devices":{}}')]
        # ...on the SAME session: no disconnect, still connected, loop alive.
        assert hooks.disconnects == []
        assert service.is_connected is True
        assert not task.done()
    finally:
        task.cancel()
        # run() treats cancellation as a stop request and exits normally.
        await asyncio.wait_for(task, 1.0)


async def test_unexpected_error_in_on_connected_reconnects(monkeypatch, hooks, stub_ssl, fast_sleep, no_jitter) -> None:
    """A non-transport exception (e.g. AttributeError) does not kill run(): the loop reconnects."""
    first = _FakeClient()
    second = _FakeClient()
    _install_factory(monkeypatch, [first, second])
    hooks.on_connected_error = AttributeError("boom in initial publish")

    service = _make_service(hooks)
    task = asyncio.create_task(service.run())
    try:
        # Second connect attempt must happen after the unexpected error.
        await _wait_for(lambda: hooks.connected_count == 2)
        assert len(hooks.disconnects) == 1
        _err, unexpected = hooks.disconnects[0]
        assert unexpected is True
        assert service.is_connected is True
        assert not task.done()
    finally:
        task.cancel()
        # run() treats cancellation as a stop request and exits normally.
        await asyncio.wait_for(task, 1.0)


async def test_cancellation_propagates_through_message_barrier(monkeypatch, hooks, stub_ssl) -> None:
    """Cancelling the task while a message handler runs stops run() promptly (barrier must re-raise CancelledError)."""
    client = _FakeClient()
    _install_factory(monkeypatch, [client])
    hooks.block_on_message = True

    service = _make_service(hooks)
    task = asyncio.create_task(service.run())
    client.stream.queue.put_nowait(_FakeMessage("down/commands", b"{}"))
    await asyncio.wait_for(hooks.message_started.wait(), 1.0)

    task.cancel()
    # run() treats cancellation as a stop request: the task must finish
    # promptly (would hang here if the barrier swallowed CancelledError).
    await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 1.0)
    assert task.done()
    assert service.is_connected is False
    assert service.client is None


# ---------------------------------------------------------------------------
# Reconnect loop / exponential backoff
# ---------------------------------------------------------------------------


async def test_backoff_grows_exponentially_and_clamps(monkeypatch, hooks, stub_ssl, fast_sleep, no_jitter) -> None:
    """Backoff doubles per failure and is clamped at reconnect_max."""
    clients = [_FakeClient(connect_error=aiomqtt.MqttError("refused")) for _ in range(6)]
    _install_factory(monkeypatch, clients)
    hooks.keep_running_answers = [True, True, True, True, True, False]

    service = _make_service(hooks, reconnect_min=1, reconnect_max=8)
    await asyncio.wait_for(service.run(), 5.0)

    # 5 sleeps between 6 attempts: 1 → 2 → 4 → 8 → 8 (clamped, never 16).
    assert fast_sleep == [1, 2, 4, 8, 8]
    assert len(hooks.disconnects) == 6
    assert all(unexpected is False for _err, unexpected in hooks.disconnects)
    assert service.is_connected is False
    assert service.client is None


def _dropping_client() -> _FakeClient:
    """A client whose CONNACK succeeds and whose session the broker drops at once.

    The shape of a session takeover (another client logged in with the same
    credentials), an ACL rejection or a broker-side kick.
    """
    client = _FakeClient()
    client.stream.queue.put_nowait(aiomqtt.MqttError("session taken over"))
    return client


class _ManualTimers:
    """Stand-in for ``loop.call_later`` that lets the test decide when time passes.

    Handles are real ``asyncio.TimerHandle`` objects that are never put on the
    loop, so ``cancel()`` behaves as in production while :meth:`elapse` plays
    the part of the clock running out — deterministic, no real waiting.
    """

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self.handles: list[tuple[float, asyncio.TimerHandle]] = []

    def call_later(self, delay: float, callback: Any, *args: Any, context: Any = None) -> asyncio.TimerHandle:
        handle = asyncio.TimerHandle(self._loop.time() + delay, callback, args, self._loop, context=context)
        self.handles.append((delay, handle))
        return handle

    @property
    def pending(self) -> list[asyncio.TimerHandle]:
        return [handle for _delay, handle in self.handles if not handle.cancelled()]

    def elapse(self) -> None:
        """Fire every timer that is still armed, as the loop would once it is due."""
        for _delay, handle in list(self.handles):
            if not handle.cancelled():
                handle._run()
                handle.cancel()


@pytest.fixture
async def manual_timers(monkeypatch: pytest.MonkeyPatch) -> _ManualTimers:
    """Route the running loop's ``call_later`` through :class:`_ManualTimers`."""
    loop = asyncio.get_running_loop()
    timers = _ManualTimers(loop)
    monkeypatch.setattr(loop, "call_later", timers.call_later)
    return timers


async def test_flapping_session_grows_backoff_to_max(monkeypatch, hooks, stub_ssl, fast_sleep, no_jitter) -> None:
    """Connect OK then an immediate drop, over and over, backs off like any failure.

    Resetting the delay on CONNACK used to pin a flapping bridge at
    ``reconnect_min`` forever: every accepted-then-dropped session looked
    like a recovery.
    """
    clients = [_dropping_client() for _ in range(6)]
    _install_factory(monkeypatch, clients)
    hooks.keep_running_answers = [True, True, True, True, True, False]

    service = _make_service(hooks, reconnect_min=1, reconnect_max=8)
    await asyncio.wait_for(service.run(), 5.0)

    assert hooks.connected_count == 6, "every attempt reached a live session"
    assert [d for d in fast_sleep if d > 0] == [1, 2, 4, 8, 8]
    assert service.reconnect_interval == 8


async def test_stable_session_resets_backoff(
    monkeypatch, hooks, stub_ssl, fast_sleep, no_jitter, manual_timers
) -> None:
    """A session that stays up past the threshold earns the minimum delay again."""
    stable = _FakeClient()
    clients = [
        _FakeClient(connect_error=aiomqtt.MqttError("refused")),
        _FakeClient(connect_error=aiomqtt.MqttError("refused")),
        stable,
        _FakeClient(connect_error=aiomqtt.MqttError("refused")),
    ]
    _install_factory(monkeypatch, clients)
    hooks.keep_running_answers = [True, True, True, False]

    service = _make_service(hooks, reconnect_min=1, reconnect_max=8)
    task = asyncio.create_task(service.run())
    try:
        await _wait_for(lambda: service.is_connected)
        assert service.reconnect_interval == 4, "CONNACK alone must not reset the backoff"
        assert [delay for delay, _handle in manual_timers.handles] == [mcs_module.STABLE_SESSION_SECONDS]

        manual_timers.elapse()
        assert service.reconnect_interval == 1, "a stable session must reset the backoff"

        stable.stream.queue.put_nowait(aiomqtt.MqttError("broker restart"))
        await asyncio.wait_for(task, 1.0)
        # fail(1) fail(2) stable-then-drop(1 again), final failure stops.
        assert [d for d in fast_sleep if d > 0] == [1, 2, 1]
    finally:
        if not task.done():
            task.cancel()
            await asyncio.wait_for(task, 1.0)


async def test_short_session_timer_does_not_reset_next_session(
    monkeypatch, hooks, stub_ssl, fast_sleep, no_jitter, manual_timers
) -> None:
    """A dropped session's pending reset is disarmed and cannot credit the next session.

    Session A is dropped early; session B connects right after and is still
    young when A's threshold would have run out.  Were A's timer left armed,
    it would find the bridge connected (B) and reset the delay although no
    session has been stable yet.
    """
    second = _FakeClient()
    _install_factory(monkeypatch, [_dropping_client(), second])

    service = _make_service(hooks, reconnect_min=1, reconnect_max=8)
    task = asyncio.create_task(service.run())
    try:
        await _wait_for(lambda: hooks.connected_count == 2 and service.is_connected)
        assert service.reconnect_interval == 2
        # A's threshold runs out; B's timer is armed but not yet due.
        first_session_timer = manual_timers.handles[0][1]
        if not first_session_timer.cancelled():
            first_session_timer._run()
        assert service.reconnect_interval == 2, "a dropped session was credited as stable"
    finally:
        task.cancel()
        await asyncio.wait_for(task, 1.0)


async def test_backoff_sleep_does_not_count_as_stable_session(
    monkeypatch, hooks, stub_ssl, no_jitter, manual_timers
) -> None:
    """Time spent waiting to reconnect never credits the dropped session.

    With a long backoff (up to ``reconnect_max``, far above the stable
    threshold) a reset left armed by the dropped session would run out during
    the wait and knock the delay back to the minimum on every round.
    """
    recorded: list[float] = []
    real_sleep = asyncio.sleep

    async def _sleep_and_let_time_pass(delay: float, *args: Any) -> None:
        if delay > 0:
            recorded.append(delay)
            manual_timers.elapse()
        await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", _sleep_and_let_time_pass)
    _install_factory(monkeypatch, [_dropping_client() for _ in range(5)])
    hooks.keep_running_answers = [True, True, True, True, False]

    service = _make_service(hooks, reconnect_min=1, reconnect_max=8)
    await asyncio.wait_for(service.run(), 5.0)

    assert recorded == [1, 2, 4, 8]
    assert service.reconnect_interval == 8


async def test_stop_mid_session_disarms_backoff_reset(
    monkeypatch, hooks, stub_ssl, fast_sleep, no_jitter, manual_timers
) -> None:
    """Unloading while connected cancels the pending reset along with the loop."""
    clients = [_FakeClient(connect_error=aiomqtt.MqttError("refused")), _FakeClient()]
    _install_factory(monkeypatch, clients)

    service = _make_service(hooks, reconnect_min=1, reconnect_max=8)
    task = asyncio.create_task(service.run())
    await _wait_for(lambda: service.is_connected)
    assert len(manual_timers.pending) == 1
    task.cancel()
    await asyncio.wait_for(task, 1.0)

    assert manual_timers.pending == [], "the backoff reset outlived the connection loop"
    manual_timers.elapse()
    assert service.reconnect_interval == 2


async def test_backoff_jitter_scales_sleep(monkeypatch, hooks, stub_ssl, fast_sleep) -> None:
    """The actual sleep is base interval multiplied by the jitter factor."""
    clients = [_FakeClient(connect_error=aiomqtt.MqttError("refused")) for _ in range(2)]
    _install_factory(monkeypatch, clients)
    hooks.keep_running_answers = [True, False]
    monkeypatch.setattr(mcs_module.random, "uniform", lambda a, b: 1.5)

    service = _make_service(hooks, reconnect_min=2, reconnect_max=8)
    await asyncio.wait_for(service.run(), 5.0)

    assert fast_sleep == [3.0]  # 2 * 1.5


async def test_stream_drop_triggers_disconnect_hook_and_backoff(
    monkeypatch, hooks, stub_ssl, fast_sleep, no_jitter
) -> None:
    """A mid-session broker drop reaches on_disconnected(unexpected=False) and applies backoff.

    Guards against an over-broad barrier in _consume_messages: if stream
    errors were swallowed there, the loop would reconnect with NO disconnect
    hook (broken stats) and NO backoff sleep (reconnect storm).
    """
    first = _FakeClient()
    second = _FakeClient()
    _install_factory(monkeypatch, [first, second])

    service = _make_service(hooks, reconnect_min=1, reconnect_max=8)
    task = asyncio.create_task(service.run())
    try:
        await _wait_for(lambda: service.is_connected)
        first.stream.queue.put_nowait(aiomqtt.MqttError("broker dropped connection"))
        await _wait_for(lambda: hooks.connected_count == 2)

        assert [(isinstance(e, aiomqtt.MqttError), u) for e, u in hooks.disconnects] == [(True, False)]
        # Backoff sleep happened between the two sessions (0-delay polling
        # yields from _wait_for are filtered out).
        assert [d for d in fast_sleep if d > 0] == [1]
    finally:
        task.cancel()
        # run() treats cancellation as a stop request and exits normally.
        await asyncio.wait_for(task, 1.0)


async def test_on_disconnected_hook_error_does_not_kill_loop(
    monkeypatch, hooks, stub_ssl, fast_sleep, no_jitter
) -> None:
    """An exception raised by the on_disconnected hook is contained: backoff + reconnect proceed."""
    clients = [_FakeClient(connect_error=aiomqtt.MqttError("refused")), _FakeClient()]
    _install_factory(monkeypatch, clients)
    hooks.on_disconnected_error = AttributeError("boom in disconnect stats")

    service = _make_service(hooks, reconnect_min=1, reconnect_max=8)
    task = asyncio.create_task(service.run())
    try:
        # The loop must survive the hook error and reach a live session.
        await _wait_for(lambda: service.is_connected)
        assert hooks.connected_count == 1
        assert len(hooks.disconnects) == 1
        # Backoff was still applied before the retry (no reconnect storm).
        assert [d for d in fast_sleep if d > 0] == [1]
        assert not task.done()
    finally:
        task.cancel()
        # run() treats cancellation as a stop request and exits normally.
        await asyncio.wait_for(task, 1.0)


async def test_on_disconnected_false_stops_loop(monkeypatch, hooks, stub_ssl, fast_sleep, no_jitter) -> None:
    """When the bridge hook returns False the loop stops without retrying."""
    _install_factory(monkeypatch, [_FakeClient(connect_error=aiomqtt.MqttError("refused"))])
    hooks.keep_running_answers = [False]

    service = _make_service(hooks)
    await asyncio.wait_for(service.run(), 5.0)

    assert fast_sleep == []  # no backoff sleep after the final failure
    assert service.is_connected is False
    assert service.client is None


async def test_stop_exits_loop_cleanly(monkeypatch, hooks, stub_ssl) -> None:
    """stop() ends the loop at the next message without reconnecting."""
    client = _FakeClient()
    _install_factory(monkeypatch, [client])

    service = _make_service(hooks)
    task = asyncio.create_task(service.run())
    try:
        await _wait_for(lambda: service.is_connected)
        await service.stop()
        client.stream.queue.put_nowait(_FakeMessage("down/commands", b"{}"))
        await asyncio.wait_for(task, 1.0)

        assert not task.cancelled()
        assert hooks.messages == []  # message after stop() is not dispatched
        assert service.is_connected is False
        assert service.client is None
    finally:
        if not task.done():
            task.cancel()


# ---------------------------------------------------------------------------
# verify_ssl runtime switching
# ---------------------------------------------------------------------------


async def test_verify_ssl_change_applies_on_next_reconnect(monkeypatch, hooks, stub_ssl, fast_sleep, no_jitter) -> None:
    """update_verify_ssl(False) is picked up when the loop rebuilds the SSL context."""
    first = _FakeClient()
    second = _FakeClient()
    factory = _install_factory(monkeypatch, [first, second])

    service = _make_service(hooks)
    task = asyncio.create_task(service.run())
    try:
        await _wait_for(lambda: service.is_connected)
        assert stub_ssl == [True]

        service.update_verify_ssl(False)
        # Simulate a broker drop → reconnect iteration.
        first.stream.queue.put_nowait(aiomqtt.MqttError("connection lost"))
        await _wait_for(lambda: hooks.connected_count == 2)

        # SSL context was rebuilt with the NEW flag and passed to the client.
        assert stub_ssl == [True, False]
        assert factory.calls[1]["tls_context"] is not factory.calls[0]["tls_context"]
        # The stream drop went through the disconnect hook (not swallowed by
        # an over-broad consume barrier).
        assert [(isinstance(e, aiomqtt.MqttError), u) for e, u in hooks.disconnects] == [(True, False)]
    finally:
        task.cancel()
        # run() treats cancellation as a stop request and exits normally.
        await asyncio.wait_for(task, 1.0)


# ---------------------------------------------------------------------------
# publish / subscribe guards
# ---------------------------------------------------------------------------


async def test_publish_raises_when_disconnected(hooks) -> None:
    """publish() before/without a connection fails loudly, not with AttributeError."""
    service = _make_service(hooks)
    with pytest.raises(RuntimeError, match="Not connected"):
        await service.publish("topic", "payload")


async def test_subscribe_raises_when_disconnected(hooks) -> None:
    """subscribe() before/without a connection fails loudly."""
    service = _make_service(hooks)
    with pytest.raises(RuntimeError, match="Not connected"):
        await service.subscribe("topic/#")


async def test_publish_and_subscribe_delegate_when_connected(monkeypatch, hooks, stub_ssl) -> None:
    """While connected, publish/subscribe go to the live client."""
    client = _FakeClient()
    _install_factory(monkeypatch, [client])

    service = _make_service(hooks)
    task = asyncio.create_task(service.run())
    try:
        await _wait_for(lambda: service.is_connected)
        await service.publish("up/status", b"{}")
        await service.subscribe("down/#")
        assert client.published == [("up/status", b"{}")]
        assert client.subscribed == ["down/#"]
    finally:
        task.cancel()
        # run() treats cancellation as a stop request and exits normally.
        await asyncio.wait_for(task, 1.0)


# ---------------------------------------------------------------------------
# parse_sber_command: structural validation of untrusted payloads
# ---------------------------------------------------------------------------


def test_parse_command_top_level_list_returns_empty() -> None:
    """'[1,2,3]' must not raise AttributeError (killed the MQTT loop before)."""
    assert parse_sber_command(b"[1,2,3]") == {"devices": {}}


@pytest.mark.parametrize(
    "payload",
    [b'"string"', b"42", b"null", b"true", b'{"devices": []}', b'{"devices": null}', b"{}"],
)
def test_parse_command_non_dict_devices_returns_empty(payload: bytes) -> None:
    """Any non-dict devices shape degrades to an empty command set."""
    assert parse_sber_command(payload) == {"devices": {}}


def test_parse_command_drops_non_dict_device_entries() -> None:
    """{"devices": {"x": 1}} must not leak a non-dict entry to the dispatcher."""
    result = parse_sber_command(b'{"devices": {"light.x": 1, "light.ok": {"states": []}}}')
    assert result["devices"] == {"light.ok": {"states": []}}


def test_parse_command_null_device_entry_dropped() -> None:
    """{"devices": {"id": null}} previously exploded in the dispatcher grace path."""
    result = parse_sber_command(b'{"devices": {"light.x": null}}')
    assert result["devices"] == {}


def test_parse_command_normalizes_non_list_states() -> None:
    """A non-list 'states' is replaced with an empty list."""
    result = parse_sber_command(b'{"devices": {"light.x": {"states": "on"}}}')
    assert result["devices"]["light.x"]["states"] == []


def test_parse_command_drops_non_dict_state_items() -> None:
    """Non-dict items inside 'states' are removed; dict items survive."""
    result = parse_sber_command(b'{"devices": {"light.x": {"states": [{"key": "on_off"}, 5, null, "x"]}}}')
    assert result["devices"]["light.x"]["states"] == [{"key": "on_off"}]


def test_parse_command_valid_payload_passes_through() -> None:
    """A well-formed payload is returned unchanged (top-level keys preserved)."""
    payload = {"devices": {"light.x": {"states": [{"key": "on_off", "value": {"type": "BOOL", "bool_value": True}}]}}}
    assert parse_sber_command(json.dumps(payload).encode()) == payload


def test_parse_command_deeply_nested_json_no_crash() -> None:
    """A pathologically nested document (RecursionError in json) degrades gracefully."""
    payload = b"[" * 100_000 + b"]" * 100_000
    assert parse_sber_command(payload) == {"devices": {}}


def test_parse_command_invalid_utf8_no_crash() -> None:
    """Invalid UTF-8 bytes are treated as a parse failure, not an exception."""
    assert parse_sber_command(b'\xff\xfe{"devices": {}}') == {"devices": {}}


def test_parse_command_non_bytes_input_no_crash() -> None:
    """Defensive: non-str/bytes payload degrades to empty."""
    assert parse_sber_command(None) == {"devices": {}}  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# parse_sber_status_request: structural validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [b"[1,2,3]", b"not json", b"null", b'{"devices": {}}', b'{"devices": null}', b'{"devices": [""]}'],
)
def test_parse_status_request_invalid_shapes_return_empty(payload: bytes) -> None:
    """Non-list / sentinel shapes mean 'all entities' (empty list), never raise."""
    assert parse_sber_status_request(payload) == []


def test_parse_status_request_drops_non_string_ids() -> None:
    """Dict/int items would be unhashable/wrong for lookups — only strings survive."""
    assert parse_sber_status_request(b'{"devices": [{"a": 1}, "light.x", 5]}') == ["light.x"]


def test_parse_status_request_deeply_nested_no_crash() -> None:
    """Deep nesting must not raise RecursionError."""
    payload = b"[" * 100_000 + b"]" * 100_000
    assert parse_sber_status_request(payload) == []


# ---------------------------------------------------------------------------
# async_connect: the setup's connection check hands its session to run()
# ---------------------------------------------------------------------------


async def test_async_connect_session_is_the_first_session_of_run(monkeypatch, hooks, stub_ssl) -> None:
    """A successful check costs one connection: run() continues on the same client."""
    only = _FakeClient()
    factory = _install_factory(monkeypatch, [only])
    service = _make_service(hooks)

    await service.async_connect(5)
    assert only.entered
    assert not service.is_connected, "no publish may go out before run() has subscribed"

    task = asyncio.create_task(service.run())
    try:
        await _wait_for(lambda: hooks.connected_count == 1)
        assert service.client is only
        assert len(factory.calls) == 1, "the factory raises on a second connection"
    finally:
        task.cancel()
        await asyncio.wait_for(task, 1.0)
    assert only.exit_count == 1


async def test_async_connect_failure_propagates_and_keeps_nothing(monkeypatch, hooks, stub_ssl) -> None:
    """A refused connection raises to the caller; run() then connects afresh."""
    refused = _FakeClient(connect_error=aiomqtt.MqttError("[Errno 111] Connection refused"))
    fresh = _FakeClient()
    factory = _install_factory(monkeypatch, [refused, fresh])
    service = _make_service(hooks)

    with pytest.raises(aiomqtt.MqttError, match="refused"):
        await service.async_connect(5)
    assert hooks.disconnects == [], "a setup check is not a runtime disconnect"

    task = asyncio.create_task(service.run())
    try:
        await _wait_for(lambda: hooks.connected_count == 1)
        assert service.client is fresh
        assert len(factory.calls) == 2
    finally:
        task.cancel()
        await asyncio.wait_for(task, 1.0)


async def test_async_connect_timeout_abandons_attempt_and_closes_it_later(monkeypatch, hooks, stub_ssl) -> None:
    """No answer in time: TimeoutError now, and the late session is closed, not leaked."""
    gate = asyncio.Event()
    slow = _FakeClient(connect_gate=gate)
    _install_factory(monkeypatch, [slow])
    service = _make_service(hooks)
    tasks_before = set(asyncio.all_tasks())

    with pytest.raises(TimeoutError, match=r"broker\.test:8883"):
        await service.async_connect(0.01)

    gate.set()
    await _wait_for(lambda: slow.exit_count == 1)
    assert slow.entered
    await _wait_for(lambda: not [t for t in asyncio.all_tasks() - tasks_before if not t.done()])
    await service.stop()
    assert slow.exit_count == 1, "the abandoned session is not the service's to close again"


async def test_async_connect_timeout_attempt_that_fails_later_needs_no_close(monkeypatch, hooks, stub_ssl) -> None:
    """An abandoned attempt that ends in an error leaves nothing to close and no stray error."""
    gate = asyncio.Event()
    slow = _FakeClient(connect_gate=gate, connect_error=aiomqtt.MqttError("late refusal"))
    _install_factory(monkeypatch, [slow])
    service = _make_service(hooks)
    tasks_before = set(asyncio.all_tasks())

    with pytest.raises(TimeoutError):
        await service.async_connect(0.01)
    gate.set()
    await _wait_for(lambda: not [t for t in asyncio.all_tasks() - tasks_before if not t.done()])
    assert slow.exit_count == 0


async def test_async_connect_cancelled_abandons_attempt(monkeypatch, hooks, stub_ssl) -> None:
    """Cancelling the check (HA shutting down) also closes a session that arrives late."""
    gate = asyncio.Event()
    slow = _FakeClient(connect_gate=gate)
    _install_factory(monkeypatch, [slow])
    service = _make_service(hooks)

    check = asyncio.create_task(service.async_connect(5))
    await asyncio.sleep(0)
    check.cancel()
    with pytest.raises(asyncio.CancelledError):
        await check
    gate.set()
    await _wait_for(lambda: slow.exit_count == 1)


async def test_stop_closes_session_run_never_took(monkeypatch, hooks, stub_ssl) -> None:
    """Setup failing after the check must not leave the checked session open."""
    only = _FakeClient()
    _install_factory(monkeypatch, [only])
    service = _make_service(hooks)

    await service.async_connect(5)
    await service.stop()
    assert only.exit_count == 1
    await service.stop()
    assert only.exit_count == 1


async def test_unexpected_error_is_not_logged_by_the_transport(monkeypatch, hooks, stub_ssl, caplog) -> None:
    """The on_disconnected hook owns the report; the transport adds no second traceback."""
    first = _FakeClient()
    second = _FakeClient()
    _install_factory(monkeypatch, [first, second])
    hooks.on_connected_error = AttributeError("boom in initial publish")
    service = _make_service(hooks, reconnect_min=0, reconnect_max=0)

    task = asyncio.create_task(service.run())
    try:
        await _wait_for(lambda: hooks.connected_count == 2)
    finally:
        task.cancel()
        await asyncio.wait_for(task, 1.0)
    assert hooks.disconnects[0][1] is True
    assert [r for r in caplog.records if r.name == mcs_module.__name__] == []


async def test_stop_tolerates_a_failing_disconnect_of_the_unused_session(monkeypatch, hooks, stub_ssl) -> None:
    """A broker that does not acknowledge DISCONNECT must not fail the unload."""
    only = _FakeClient()

    async def _exit_times_out(*_exc_info: object) -> bool:
        raise aiomqtt.MqttError("Operation timed out")

    monkeypatch.setattr(_FakeClient, "__aexit__", lambda self, *exc: _exit_times_out())
    _install_factory(monkeypatch, [only])
    service = _make_service(hooks)

    await service.async_connect(5)
    await service.stop()
    await service.stop()
