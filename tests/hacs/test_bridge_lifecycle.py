"""Lifecycle and safety tests for :class:`SberBridge` (wave W1D).

Covers the previously untested race-prone paths:

- ``async_start`` / ``async_stop`` (task hygiene, idempotency)
- connect handshake ordering (config before states, publish-before-subscribe)
- HA-startup gating of the initial publish
- disconnect handling (state reset, audit-timer cancellation, reconnect)
- payload-size guard (no decode / no DevTools buffering of oversized payloads,
  inclusive boundary, DevTools log truncation of large-but-legal payloads)
- per-handler error isolation in the MQTT message router (and CancelledError
  pass-through)

Only the external MQTT boundary (``aiomqtt.Client``) is faked; the bridge,
the transport service, the publisher and the dispatcher all run for real
against the ``hass`` fixture.
"""

from __future__ import annotations

import asyncio
import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import aiomqtt
import pytest
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState, HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sber_mqtt_bridge.const import (
    CONF_MAX_MQTT_PAYLOAD,
    CONF_RECONNECT_MAX,
    CONF_RECONNECT_MIN,
    CONF_SBER_BROKER,
    CONF_SBER_LOGIN,
    CONF_SBER_PASSWORD,
    CONF_SBER_PORT,
    CONF_SBER_VERIFY_SSL,
    DOMAIN,
)
from custom_components.sber_mqtt_bridge.sber_bridge import SberBridge

# ---------------------------------------------------------------------------
# Fakes / helpers
# ---------------------------------------------------------------------------


class FakeMqttClient:
    """In-memory stand-in for ``aiomqtt.Client`` driven by the test.

    The test can push messages or exceptions into the inbound queue and
    inspect everything the bridge published / subscribed to.
    """

    def __init__(self, fail_connects: int = 0) -> None:
        """Create a fake client.

        Args:
            fail_connects: Number of initial ``__aenter__`` calls that
                raise ``MqttError`` (simulates a broker that is down).
        """
        self.published: list[tuple[str, str | bytes]] = []
        self.subscribed: list[str] = []
        self.connect_count = 0
        self.fail_connects = fail_connects
        self._queue: asyncio.Queue = asyncio.Queue()

    async def __aenter__(self) -> FakeMqttClient:
        self.connect_count += 1
        if self.connect_count <= self.fail_connects:
            raise aiomqtt.MqttError("connection refused (fake)")
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def publish(self, topic: str, payload: str | bytes) -> None:
        self.published.append((topic, payload))

    async def subscribe(self, pattern: str) -> None:
        self.subscribed.append(pattern)

    def push_message(self, topic: str, payload: bytes) -> None:
        """Queue an inbound MQTT message for the consume loop."""
        self._queue.put_nowait(SimpleNamespace(topic=topic, payload=payload))

    def push_error(self, exc: Exception) -> None:
        """Queue a transport error — raised out of the message stream."""
        self._queue.put_nowait(exc)

    @property
    def messages(self):
        """Async iterator over queued messages (blocks until pushed)."""
        return self._iter()

    async def _iter(self):
        while True:
            item = await self._queue.get()
            if isinstance(item, Exception):
                raise item
            yield item


class SpyBytes(bytes):
    """Bytes subclass that counts ``decode`` calls (guard-order probe)."""

    decode_calls = 0

    def decode(self, *args, **kwargs):
        """Decode while recording that a decode happened."""
        type(self).decode_calls += 1
        return super().decode(*args, **kwargs)


def _make_entry(hass: HomeAssistant, options: dict | None = None) -> MockConfigEntry:
    """Create and register a MockConfigEntry with Sber credentials."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_SBER_LOGIN: "test",
            CONF_SBER_PASSWORD: "pass",
            CONF_SBER_BROKER: "broker.test",
            CONF_SBER_PORT: 8883,
            CONF_SBER_VERIFY_SSL: False,
        },
        options=options or {},
    )
    entry.add_to_hass(hass)
    return entry


def _install_fake_mqtt(monkeypatch: pytest.MonkeyPatch, fake: FakeMqttClient) -> None:
    """Route every ``aiomqtt.Client(...)`` construction to the fake."""
    monkeypatch.setattr(
        "custom_components.sber_mqtt_bridge.mqtt_client_service.aiomqtt.Client",
        lambda *args, **kwargs: fake,
    )


async def _wait_until(condition, deadline: float = 2.0) -> None:
    """Poll ``condition()`` every 5 ms until true or ``deadline`` elapses.

    Polling (instead of an event) is deliberate: the bridge under test has
    no test-visible completion hooks, and adding them would mean testing
    instrumentation rather than production code.
    """
    async with asyncio.timeout(deadline):
        while not condition():  # noqa: ASYNC110 — polling by design, see docstring
            await asyncio.sleep(0.005)


def _topics(fake: FakeMqttClient) -> list[str]:
    return [topic for topic, _ in fake.published]


async def _drain_leftover_tasks(before: set[asyncio.Task]) -> list[asyncio.Task]:
    """Return tasks created since ``before`` that are still alive."""
    await asyncio.sleep(0)
    current = asyncio.current_task()
    return [t for t in asyncio.all_tasks() if t not in before and t is not current and not t.done()]


# ---------------------------------------------------------------------------
# Connect handshake
# ---------------------------------------------------------------------------


async def test_connect_handshake_publishes_config_before_states_then_subscribes(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """After MQTT connect: config first, states second, then down/# subscribe."""
    registry = er.async_get(hass)
    registry.async_get_or_create("switch", "test", "lamp-uid", suggested_object_id="lamp")
    hass.states.async_set("switch.lamp", "on")
    entry = _make_entry(hass, options={"exposed_entities": ["switch.lamp"]})
    fake = FakeMqttClient()
    _install_fake_mqtt(monkeypatch, fake)
    bridge = SberBridge(hass, entry)

    try:
        await bridge.async_start()
        await _wait_until(lambda: fake.subscribed)

        assert bridge.is_connected
        topics = _topics(fake)
        config_idx = next(i for i, t in enumerate(topics) if t.endswith("up/config"))
        status_idx = next(i for i, t in enumerate(topics) if t.endswith("up/status"))
        assert config_idx < status_idx, "Sber must learn devices (config) before their states"

        # The published config actually contains the exposed entity
        config_payload = json.loads(fake.published[config_idx][1])
        assert any(device.get("id") == "switch.lamp" for device in config_payload["devices"])

        # Commands subscription happens only after the initial publish
        assert any("down/#" in s for s in fake.subscribed)
        assert bridge.connection_phase == "awaiting_ack"
    finally:
        await bridge.async_stop()


async def test_initial_publish_waits_for_ha_started(hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch) -> None:
    """When HA is still starting, nothing is published until STARTED fires."""
    hass.states.async_set("switch.lamp", "on")
    entry = _make_entry(hass, options={"exposed_entities": ["switch.lamp"]})
    fake = FakeMqttClient()
    _install_fake_mqtt(monkeypatch, fake)

    hass.set_state(CoreState.not_running)
    bridge = SberBridge(hass, entry)

    try:
        await bridge.async_start()
        # MQTT connects, but the handshake must block on the HA-ready gate
        await _wait_until(lambda: bridge.is_connected)
        await asyncio.sleep(0.02)
        assert fake.published == [], "states must not leak to Sber before HA has fully started"
        assert bridge.connection_phase == "starting"

        hass.set_state(CoreState.running)
        hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
        await _wait_until(lambda: fake.subscribed)

        assert any(t.endswith("up/config") for t in _topics(fake))
        assert any(t.endswith("up/status") for t in _topics(fake))
    finally:
        await bridge.async_stop()


# ---------------------------------------------------------------------------
# Disconnect handling
# ---------------------------------------------------------------------------


async def test_disconnect_resets_state_cancels_audit_and_schedules_reconnect(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Transport error → is_connected False, audit timer dead, backoff armed."""
    hass.states.async_set("switch.lamp", "on")
    entry = _make_entry(
        hass,
        options={
            "exposed_entities": ["switch.lamp"],
            CONF_RECONNECT_MIN: 60,
            CONF_RECONNECT_MAX: 60,
        },
    )
    fake = FakeMqttClient()
    _install_fake_mqtt(monkeypatch, fake)
    bridge = SberBridge(hass, entry)

    try:
        await bridge.async_start()
        await _wait_until(lambda: fake.subscribed)
        # publish_config armed the silent-rejection audit timer
        assert bridge._ack_audit._audit_handle is not None

        fake.push_error(aiomqtt.MqttError("broker went away"))
        await _wait_until(lambda: not bridge.is_connected)
        await _wait_until(lambda: bridge.stats["reconnect_count"] == 1)

        assert bridge.connection_phase == "connecting"
        assert bridge.stats["connected_since"] is None
        # The audit timer must NOT survive the disconnect: offline it can
        # only produce false "silent rejection" repair issues.
        assert bridge._ack_audit._audit_handle is None
    finally:
        await asyncio.wait_for(bridge.async_stop(), timeout=2)
    assert not bridge.is_connected


async def test_reconnect_after_error_republishes_config(hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch) -> None:
    """After a transport error the loop reconnects and redoes the handshake."""
    hass.states.async_set("switch.lamp", "on")
    entry = _make_entry(
        hass,
        options={
            "exposed_entities": ["switch.lamp"],
            CONF_RECONNECT_MIN: 0,
            CONF_RECONNECT_MAX: 0,
        },
    )
    fake = FakeMqttClient()
    _install_fake_mqtt(monkeypatch, fake)
    bridge = SberBridge(hass, entry)

    try:
        await bridge.async_start()
        await _wait_until(lambda: fake.connect_count == 1 and fake.subscribed)
        configs_before = sum(1 for t in _topics(fake) if t.endswith("up/config"))

        fake.push_error(aiomqtt.MqttError("flaky network"))
        await _wait_until(lambda: fake.connect_count >= 2)
        await _wait_until(lambda: bridge.is_connected)
        await _wait_until(lambda: sum(1 for t in _topics(fake) if t.endswith("up/config")) > configs_before)

        assert bridge.stats["reconnect_count"] == 1
    finally:
        await asyncio.wait_for(bridge.async_stop(), timeout=2)


async def test_ack_audit_is_noop_while_disconnected(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A stale audit run while offline must not report silent rejections."""
    entry = _make_entry(hass)
    bridge = SberBridge(hass, entry)
    bridge._enabled_entity_ids = ["switch.lamp"]  # unacknowledged by definition

    with caplog.at_level(logging.WARNING):
        bridge._run_ack_audit()
    assert "silent rejection" not in caplog.text, "audit fired offline → false positive"

    # Same state but connected → the audit must report.
    bridge._connected = True
    with caplog.at_level(logging.WARNING):
        bridge._run_ack_audit()
    await hass.async_block_till_done()
    assert "silent rejection" in caplog.text


# ---------------------------------------------------------------------------
# async_stop: task hygiene, flush, idempotency
# ---------------------------------------------------------------------------


async def test_stop_cancels_everything_flushes_redefinitions_and_is_idempotent(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """async_stop kills all bridge-owned tasks/timers and persists edits."""
    hass.states.async_set("switch.lamp", "on")
    entry = _make_entry(hass, options={"exposed_entities": ["switch.lamp"]})
    fake = FakeMqttClient()
    _install_fake_mqtt(monkeypatch, fake)

    tasks_before = set(asyncio.all_tasks())
    bridge = SberBridge(hass, entry)
    await bridge.async_start()
    await _wait_until(lambda: fake.subscribed)

    # A delayed-confirm task that would otherwise outlive the bridge
    bridge._confirm_delay = 30.0
    confirm_task = bridge._create_safe_task(bridge._delayed_confirm("switch.lamp"), name="confirm")
    bridge._confirm_tasks["switch.lamp"] = confirm_task

    # A dirty redefinitions store with a pending debounce timer
    await bridge._redef_store.async_update("switch.lamp", {"name": "Night Lamp"})
    assert bridge._redef_store._timer is not None

    await asyncio.wait_for(bridge.async_stop(), timeout=2)
    await asyncio.sleep(0)

    # Confirm task must be cancelled, not left sleeping 30 s into the past
    assert confirm_task.cancelled()
    assert bridge._confirm_tasks == {}

    # Pending user edits are flushed synchronously (not lost, no zombie timer)
    assert entry.options["redefinitions"]["switch.lamp"]["name"] == "Night Lamp"
    assert bridge._redef_store._timer is None

    # Connection loop is gone and the flag reads False through the service
    assert bridge._connection_task is None
    assert not bridge.is_connected

    # Second stop is idempotent
    await asyncio.wait_for(bridge.async_stop(), timeout=2)

    await hass.async_block_till_done()
    leftover = await _drain_leftover_tasks(tasks_before)
    assert leftover == [], f"tasks survived unload: {leftover}"


async def test_stop_after_connection_failure_leaves_no_hanging_tasks(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unload while the loop is stuck in backoff must cancel it cleanly."""
    entry = _make_entry(
        hass,
        options={CONF_RECONNECT_MIN: 60, CONF_RECONNECT_MAX: 60},
    )
    fake = FakeMqttClient(fail_connects=10**9)
    _install_fake_mqtt(monkeypatch, fake)

    tasks_before = set(asyncio.all_tasks())
    bridge = SberBridge(hass, entry)
    await bridge.async_start()
    # Wait until the loop has failed at least once and sits in backoff sleep
    await _wait_until(lambda: bridge.stats["reconnect_count"] >= 1)

    await asyncio.wait_for(bridge.async_stop(), timeout=2)

    assert bridge._connection_task is None
    assert not bridge.is_connected
    await hass.async_block_till_done()
    leftover = await _drain_leftover_tasks(tasks_before)
    assert leftover == [], f"tasks survived unload: {leftover}"


async def test_connection_loop_crash_is_logged_not_lost(hass: HomeAssistant, caplog: pytest.LogCaptureFixture) -> None:
    """A fatal error in the reconnect loop surfaces in the log immediately."""
    entry = _make_entry(hass)
    bridge = SberBridge(hass, entry)
    bridge._mqtt_service.run = AsyncMock(side_effect=RuntimeError("loop exploded"))

    with caplog.at_level(logging.WARNING):
        await bridge.async_start()
        await hass.async_block_till_done()

    assert "mqtt_connection_loop" in caplog.text
    assert "loop exploded" in caplog.text

    await bridge.async_stop()


async def test_staggered_entity_startup_publishes_one_complete_config(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Entities arriving one by one must yield ONE complete config, not N partial ones.

    Reproduces the reporter's setup from issue #44: a Zigbee coordinator
    brings devices up gradually.  ``build_devices_list_json`` skips entities
    without state, so every "entity became available" publish used to ship a
    device list missing the ones still loading.  Sber treats each payload as
    the authoritative list — it dropped the absent devices and re-registered
    them as new on the next payload, which is what reset their rooms.
    """
    registry = er.async_get(hass)
    for name in ("lamp_a", "lamp_b", "lamp_c"):
        registry.async_get_or_create("switch", "test", f"{name}-uid", suggested_object_id=name)
    exposed = ["switch.lamp_a", "switch.lamp_b", "switch.lamp_c"]

    # Only the first entity has state when the bridge starts.
    hass.states.async_set("switch.lamp_a", "on")
    entry = _make_entry(hass, options={"exposed_entities": exposed})
    fake = FakeMqttClient()
    _install_fake_mqtt(monkeypatch, fake)
    bridge = SberBridge(hass, entry)

    try:
        await bridge.async_start()
        hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
        await hass.async_block_till_done()

        # Let the transport actually connect, so the handshake is reached.
        await _wait_until(lambda: fake.connect_count >= 1)

        # Now the decisive assertion: connected, but two entities are still
        # missing, so NOTHING may reach the broker.  Without the gate the
        # handshake publishes a config holding only switch.lamp_a here, and
        # that partial list is what makes Sber drop the other two.
        with pytest.raises(TimeoutError):
            await _wait_until(lambda: bool(fake.published), deadline=0.3)

        # The remaining two arrive later, as a Zigbee stick would deliver them.
        for entity_id in ("switch.lamp_b", "switch.lamp_c"):
            hass.states.async_set(entity_id, "on")
            await hass.async_block_till_done()

        await _wait_until(lambda: fake.subscribed)

        configs = [json.loads(body) for topic, body in fake.published if topic.endswith("/up/config")]
        assert configs, "no config was published at all"

        # Not one payload may omit a device that already has state: that
        # omission is what Sber reads as "the device is gone".
        for payload in configs:
            ids = {device["id"] for device in payload["devices"]}
            assert set(exposed) <= ids, f"partial config published, missing {sorted(set(exposed) - ids)}"
    finally:
        await bridge.async_stop()


async def test_connection_loop_does_not_block_startup(hass: HomeAssistant) -> None:
    """The never-ending MQTT loop must not hold up HA bootstrap.

    Regression guard for a real startup stall: the loop was scheduled with
    ``hass.async_create_task``, which Home Assistant tracks and awaits in
    ``async_block_till_done``.  Since the loop runs forever, bootstrap sat
    on it until the setup timeout fired ("Setup timed out for bootstrap
    waiting on ... _mqtt_connection_loop - moving forward") and every HA
    start was delayed by that timeout.

    ``async_block_till_done`` is exactly the primitive bootstrap uses, so
    asserting that it returns while the loop is still running reproduces
    the stall directly: with a tracked task this call never comes back.
    """
    entry = _make_entry(hass)
    bridge = SberBridge(hass, entry)

    never_ends = asyncio.Event()

    async def _run_forever(*_args: object, **_kwargs: object) -> None:
        await never_ends.wait()

    bridge._mqtt_service.run = _run_forever

    await bridge.async_start()

    # Must not hang: a tracked (non-background) task makes this await the loop.
    async with asyncio.timeout(5):
        await hass.async_block_till_done()

    assert bridge._connection_task is not None
    assert not bridge._connection_task.done(), "precondition: the loop must still be running"
    assert bridge._connection_task in hass._background_tasks, (
        "the MQTT loop must be a background task — tracked tasks block HA bootstrap"
    )

    never_ends.set()
    await bridge.async_stop()


# ---------------------------------------------------------------------------
# Payload-size guard + handler isolation
# ---------------------------------------------------------------------------


async def test_oversized_payload_is_dropped_before_decode_and_buffering(hass: HomeAssistant) -> None:
    """Oversized inbound payloads are never decoded nor stored in DevTools."""
    entry = _make_entry(hass, options={CONF_MAX_MQTT_PAYLOAD: 64})
    bridge = SberBridge(hass, entry)
    bridge._command_dispatcher.handle_command = AsyncMock()

    SpyBytes.decode_calls = 0
    big = SpyBytes(b"x" * 10_000)
    await bridge._handle_mqtt_message(f"{bridge._down_topic}/commands", big)

    # Handler never sees the message
    bridge._command_dispatcher.handle_command.assert_not_awaited()
    # The raw body was never decoded (no CPU/memory spent on a dropped message)
    assert SpyBytes.decode_calls == 0
    # The DevTools ring buffer holds only a short drop marker, not the body
    assert bridge.message_log, "the drop itself should still be visible in DevTools"
    for msg in bridge.message_log:
        assert len(msg["payload"]) < 200
        assert "x" * 100 not in msg["payload"]
    assert any("exceeds max_payload_size" in msg["payload"] for msg in bridge.message_log)


async def test_payload_within_limit_is_dispatched_and_logged(hass: HomeAssistant) -> None:
    """Payloads under the limit flow to the handler and the message log."""
    entry = _make_entry(hass, options={CONF_MAX_MQTT_PAYLOAD: 64})
    bridge = SberBridge(hass, entry)
    bridge._command_dispatcher.handle_command = AsyncMock()

    body = b'{"devices": {}}'
    await bridge._handle_mqtt_message(f"{bridge._down_topic}/commands", body)

    bridge._command_dispatcher.handle_command.assert_awaited_once()
    assert any(m["payload"] == body.decode() for m in bridge.message_log)


async def test_payload_size_limit_is_inclusive_boundary(hass: HomeAssistant) -> None:
    """Exactly ``max_payload_size`` bytes is legal; one byte more is dropped."""
    entry = _make_entry(hass, options={CONF_MAX_MQTT_PAYLOAD: 64})
    bridge = SberBridge(hass, entry)
    bridge._command_dispatcher.handle_command = AsyncMock()
    topic = f"{bridge._down_topic}/commands"

    at_limit = b"x" * 64
    await bridge._handle_mqtt_message(topic, at_limit)
    bridge._command_dispatcher.handle_command.assert_awaited_once_with(at_limit)
    assert not any("exceeds max_payload_size" in m["payload"] for m in bridge.message_log)

    bridge._command_dispatcher.handle_command.reset_mock()
    await bridge._handle_mqtt_message(topic, b"x" * 65)
    bridge._command_dispatcher.handle_command.assert_not_awaited()
    assert any("exceeds max_payload_size" in m["payload"] for m in bridge.message_log)


async def test_devtools_log_stores_truncated_copy_of_large_payload(hass: HomeAssistant) -> None:
    """A large-but-legal payload reaches the handler whole, log keeps ~8 KB.

    Guards the memory bound of the DevTools ring buffer: without
    truncation 50 entries x 1 MB (defaults) pin ~50 MB of RSS and every
    WebSocket subscriber receives the full body on each message.
    """
    entry = _make_entry(hass)  # default max_payload_size (1 MB)
    bridge = SberBridge(hass, entry)
    bridge._command_dispatcher.handle_command = AsyncMock()

    body = (b"a" * 20_000) + b"TAIL-SENTINEL"
    await bridge._handle_mqtt_message(f"{bridge._down_topic}/commands", body)

    # Command processing must see the FULL payload — truncation is log-only
    bridge._command_dispatcher.handle_command.assert_awaited_once_with(body)

    logged = [m for m in bridge.message_log if m["direction"] == "in"]
    assert logged, "the message must still be visible in DevTools"
    for msg in logged:
        assert len(msg["payload"]) < 9_000, "ring buffer must hold a bounded copy"
        assert "TAIL-SENTINEL" not in msg["payload"]
    assert any("<truncated: " in m["payload"] for m in logged), "user must see the copy is partial"

    # Small payloads are stored verbatim (no marker noise)
    bridge.clear_message_log()
    await bridge._handle_mqtt_message(f"{bridge._down_topic}/commands", b'{"devices": {}}')
    assert any(m["payload"] == '{"devices": {}}' for m in bridge.message_log)


async def test_handler_cancellation_propagates_out_of_router(hass: HomeAssistant) -> None:
    """CancelledError from a handler must NOT be swallowed by isolation.

    If the per-handler ``except Exception`` ate cancellation, the MQTT
    consume task could refuse to die on unload and outlive the entry.
    """
    entry = _make_entry(hass)
    bridge = SberBridge(hass, entry)
    bridge._command_dispatcher.handle_command = AsyncMock(side_effect=asyncio.CancelledError)

    with pytest.raises(asyncio.CancelledError):
        await bridge._handle_mqtt_message(f"{bridge._down_topic}/commands", b"{}")


async def test_handler_exception_does_not_break_message_routing(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """One crashing topic handler must not poison subsequent messages."""
    entry = _make_entry(hass)
    bridge = SberBridge(hass, entry)
    bridge._command_dispatcher.handle_command = AsyncMock(side_effect=ValueError("handler bug"))
    bridge._command_dispatcher.handle_status_request = AsyncMock()

    with caplog.at_level(logging.ERROR):
        # Must not raise despite the handler blowing up
        await bridge._handle_mqtt_message(f"{bridge._down_topic}/commands", b"{}")
    assert "handler bug" in caplog.text or "Error handling MQTT message" in caplog.text

    # The next message on another suffix is still routed normally
    await bridge._handle_mqtt_message(f"{bridge._down_topic}/status_request", b'{"devices": []}')
    bridge._command_dispatcher.handle_status_request.assert_awaited_once()


# ---------------------------------------------------------------------------
# Connection-state single source of truth
# ---------------------------------------------------------------------------


async def test_is_connected_reflects_transport_service_state(hass: HomeAssistant) -> None:
    """bridge.is_connected mirrors MqttClientService — no stale duplicate."""
    entry = _make_entry(hass)
    bridge = SberBridge(hass, entry)

    assert not bridge.is_connected
    bridge._mqtt_service._connected = True
    assert bridge.is_connected, "bridge must read connection state from the service"
    bridge._mqtt_service._connected = False
    assert not bridge.is_connected


async def test_publish_raw_goes_through_service_guard(hass: HomeAssistant) -> None:
    """async_publish_raw uses the service transport (guard + accounting)."""
    entry = _make_entry(hass)
    bridge = SberBridge(hass, entry)

    # Disconnected → the service guard rejects the publish
    with pytest.raises(RuntimeError):
        await bridge.async_publish_raw('{"devices": []}', "status")

    # Connected → publish flows through the service to the client
    fake = FakeMqttClient()
    bridge._mqtt_service._client = fake
    bridge._mqtt_service._connected = True
    await bridge.async_publish_raw('{"devices": []}', "status")

    assert fake.published == [(f"{bridge._root_topic}/up/status", '{"devices": []}')]
    assert bridge.stats["messages_sent"] == 1
    assert any(m["direction"] == "out" for m in bridge.message_log)


async def test_publish_raw_transport_error_counts_publish_error(hass: HomeAssistant) -> None:
    """A transport failure in async_publish_raw is counted in publish_errors."""
    entry = _make_entry(hass)
    bridge = SberBridge(hass, entry)
    bridge._mqtt_service._connected = True
    failing = FakeMqttClient()
    failing.publish = AsyncMock(side_effect=aiomqtt.MqttError("tls reset"))
    bridge._mqtt_service._client = failing

    with pytest.raises(aiomqtt.MqttError):
        await bridge.async_publish_raw("{}", "status")
    assert bridge.stats["publish_errors"] == 1
