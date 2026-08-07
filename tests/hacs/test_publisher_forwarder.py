"""Behavioural tests for :mod:`sber_publisher` and :mod:`ha_state_forwarder`.

The W2B wave changed both modules substantially (lost-update guard on the
"last published" snapshot, debounce max-wait, pending flush on resubscribe,
guard on the linked-entity path) without adding tests.  These tests pin the
*observable* behaviour of that code:

* what actually goes on the MQTT wire (payload contents, not mock calls);
* which entities end up marked as published (and which must not be);
* stats / DevTools side effects of a failed publish;
* the forwarder's timer arithmetic, driven by a deterministic fake clock.

Every test here was verified to fail against a mutated copy of the
implementation (see the review notes for the mutation list).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import aiomqtt
import pytest

from custom_components.sber_mqtt_bridge.const import (
    CONF_SBER_BROKER,
    CONF_SBER_LOGIN,
    CONF_SBER_PASSWORD,
    CONF_SBER_PORT,
)
from custom_components.sber_mqtt_bridge.devices.light import LightEntity
from custom_components.sber_mqtt_bridge.devices.relay import RelayEntity
from custom_components.sber_mqtt_bridge.ha_state_forwarder import (
    DEBOUNCE_MAX_WAIT_FACTOR,
    HaStateForwarder,
)
from custom_components.sber_mqtt_bridge.sber_bridge import SberBridge
from custom_components.sber_mqtt_bridge.sber_publisher import SberPublisher

# ---------------------------------------------------------------------------
# Publisher fixtures
# ---------------------------------------------------------------------------


def _make_entry(options: dict | None = None) -> MagicMock:
    """Build a mock ConfigEntry with Sber credentials."""
    entry = MagicMock()
    entry.data = {
        CONF_SBER_LOGIN: "test",
        CONF_SBER_PASSWORD: "pass",
        CONF_SBER_BROKER: "broker.test",
        CONF_SBER_PORT: 8883,
    }
    entry.options = options or {}
    return entry


def _make_bridge() -> SberBridge:
    """Build a connected bridge with a mocked MQTT transport."""
    hass = MagicMock()
    hass.config.location_name = "My Home"
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock()
    bridge = SberBridge(hass, _make_entry())
    bridge._mqtt_client = AsyncMock()
    bridge._mqtt_service.publish = AsyncMock()
    bridge._connected = True
    bridge._ack_audit.cancel()
    return bridge


def _add_relay(bridge: SberBridge, entity_id: str, state: str = "on", *, enable: bool = True) -> RelayEntity:
    """Register a filled RelayEntity on the bridge."""
    entity = RelayEntity({"entity_id": entity_id, "name": entity_id})
    entity.fill_by_ha_state({"entity_id": entity_id, "state": state, "attributes": {}})
    bridge._entities[entity_id] = entity
    if enable:
        bridge._enabled_entity_ids.append(entity_id)
    return entity


def _status_payloads(bridge: SberBridge) -> list[dict]:
    """Return every ``up/status`` payload published so far, decoded."""
    out = []
    for call in bridge._mqtt_service.publish.call_args_list:
        topic, payload = call.args[0], call.args[1]
        if str(topic).endswith("up/status"):
            out.append(json.loads(payload))
    return out


def _bool_value(payload: dict, entity_id: str, key: str) -> Any:
    """Extract a BOOL feature value from a decoded status payload."""
    for state in payload["devices"][entity_id]["states"]:
        if state["key"] == key:
            return state["value"]["bool_value"]
    raise AssertionError(f"{key} missing for {entity_id}: {payload}")


# ---------------------------------------------------------------------------
# publish_states — lost-update guard and diffing
# ---------------------------------------------------------------------------


class TestPublishStatesSnapshot:
    """The "last published" snapshot must describe the wire payload."""

    async def test_state_change_during_publish_is_published_afterwards(self) -> None:
        """A state change racing the publish await must not be swallowed.

        The snapshot is taken *before* the await; if it were taken after,
        the mid-flight ``off`` would be recorded as already published and
        Sber would keep showing ``on`` forever.
        """
        bridge = _make_bridge()
        entity = _add_relay(bridge, "switch.lamp", "on")

        async def _publish_then_race(topic: str, payload: str) -> None:
            # HA delivers "off" while the MQTT round-trip is in flight.
            entity.fill_by_ha_state({"entity_id": "switch.lamp", "state": "off", "attributes": {}})

        bridge._mqtt_service.publish.side_effect = _publish_then_race

        await bridge._publish_states(["switch.lamp"])
        assert _bool_value(_status_payloads(bridge)[0], "switch.lamp", "on_off") is True

        assert entity.has_significant_change() is True, "the mid-publish change was recorded as already published"

        bridge._mqtt_service.publish.side_effect = None
        await bridge._publish_states(["switch.lamp"])
        payloads = _status_payloads(bridge)
        assert len(payloads) == 2, "the racing OFF state was never published"
        assert _bool_value(payloads[1], "switch.lamp", "on_off") is False

    async def test_snapshot_equals_the_payload_that_went_on_the_wire(self) -> None:
        """The stored snapshot is the serialized device body, not ``None``."""
        bridge = _make_bridge()
        entity = _add_relay(bridge, "switch.lamp", "on")

        await bridge._publish_states(["switch.lamp"])

        wire = _status_payloads(bridge)[0]["devices"]
        assert entity._previous_sber_state == wire, "snapshot does not match the published payload"

    async def test_unchanged_entity_is_not_republished(self) -> None:
        """Second publish of an unchanged entity must not hit the wire."""
        bridge = _make_bridge()
        _add_relay(bridge, "switch.lamp", "on")

        await bridge._publish_states(["switch.lamp"])
        await bridge._publish_states(["switch.lamp"])

        assert len(_status_payloads(bridge)) == 1, "unchanged state was republished (dedup lost)"

    async def test_changed_entity_is_republished(self) -> None:
        """A real change after a publish still reaches Sber."""
        bridge = _make_bridge()
        entity = _add_relay(bridge, "switch.lamp", "on")

        await bridge._publish_states(["switch.lamp"])
        entity.fill_by_ha_state({"entity_id": "switch.lamp", "state": "off", "attributes": {}})
        await bridge._publish_states(["switch.lamp"])

        payloads = _status_payloads(bridge)
        assert len(payloads) == 2
        assert _bool_value(payloads[1], "switch.lamp", "on_off") is False

    async def test_force_publishes_unchanged_state(self) -> None:
        """``force=True`` (status_request path) bypasses the diff."""
        bridge = _make_bridge()
        _add_relay(bridge, "switch.lamp", "on")

        await bridge._publish_states(["switch.lamp"])
        await bridge._publish_states(["switch.lamp"], force=True)

        assert len(_status_payloads(bridge)) == 2


# ---------------------------------------------------------------------------
# publish_states — which entities may be marked as published
# ---------------------------------------------------------------------------


class TestPublishedSetAccounting:
    """Only entities present in the payload may be marked as published."""

    async def test_entity_missing_from_payload_is_not_marked(self) -> None:
        """An entity filtered out by ``enabled_entity_ids`` stays dirty.

        Otherwise re-enabling it would leave Sber without its state until
        the entity happened to change again.
        """
        bridge = _make_bridge()
        hidden = _add_relay(bridge, "switch.hidden", "on", enable=False)
        _add_relay(bridge, "switch.lamp", "on")

        await bridge._publish_states(["switch.hidden", "switch.lamp"], force=True)

        payload = _status_payloads(bridge)[0]
        assert "switch.hidden" not in payload["devices"], "test premise broken: entity was published after all"
        assert hidden._previous_sber_state is None
        assert hidden.has_significant_change() is True, "an entity that never reached the wire was marked published"

    async def test_entity_added_during_publish_is_not_marked(self) -> None:
        """The publish set is frozen before the await (hot-reload safety)."""
        bridge = _make_bridge()
        _add_relay(bridge, "switch.lamp", "on")
        late: list[RelayEntity] = []

        async def _publish_then_add(topic: str, payload: str) -> None:
            late.append(_add_relay(bridge, "switch.late", "on"))

        bridge._mqtt_service.publish.side_effect = _publish_then_add
        await bridge._publish_states(force=True)

        assert late[0]._previous_sber_state is None
        assert late[0].has_significant_change() is True, "an entity added mid-publish was marked as published"


# ---------------------------------------------------------------------------
# publish_states — a broken entity must not take the batch down
# ---------------------------------------------------------------------------


class TestBrokenEntityIsolation:
    """``build_states_list_json`` drops broken entities; so must the snapshot."""

    @pytest.mark.parametrize("exc", [KeyError("boom"), AttributeError("boom"), TypeError("boom")])
    async def test_broken_entity_does_not_block_the_batch(self, exc: Exception) -> None:
        """One entity raising during serialization still lets the batch ship."""
        bridge = _make_bridge()
        broken = _add_relay(bridge, "switch.broken", "on")
        _add_relay(bridge, "switch.lamp", "on")
        broken.to_sber_current_state = MagicMock(side_effect=exc)  # type: ignore[method-assign]

        await bridge._publish_states(["switch.broken", "switch.lamp"], force=True)

        assert bridge._mqtt_service.publish.await_count == 1, "a broken entity aborted the whole publish"
        payload = _status_payloads(bridge)[0]
        assert _bool_value(payload, "switch.lamp", "on_off") is True
        assert "switch.broken" not in payload["devices"]

    async def test_broken_entity_is_left_dirty(self) -> None:
        """A failed snapshot must not count as a successful publish."""
        bridge = _make_bridge()
        broken = _add_relay(bridge, "switch.broken", "on")
        broken.to_sber_current_state = MagicMock(side_effect=KeyError("boom"))  # type: ignore[method-assign]

        await bridge._publish_states(["switch.broken"], force=True)

        assert broken._previous_sber_state is None

    @pytest.mark.parametrize(
        "exc",
        [KeyError("k"), AttributeError("a"), TypeError("t"), ValueError("v"), RuntimeError("r")],
    )
    def test_snapshot_never_propagates(self, exc: Exception) -> None:
        """``_snapshot_wire_state`` must swallow everything the builder swallows.

        ``build_states_list_json`` drops a broken entity and still ships the
        batch; if the re-serialization here raised, a single bad entity would
        abort the publish for every other device in the payload.
        """
        entity = MagicMock()
        entity.entity_id = "switch.broken"
        entity.to_sber_current_state.side_effect = exc

        assert SberPublisher._snapshot_wire_state(entity) is None

    async def test_entity_failing_only_on_resnapshot_still_ships_the_batch(self) -> None:
        """Serialization that succeeds once and then fails must not abort.

        The entity *is* in the payload (first call succeeded), so the
        snapshot pass touches it — and the snapshot pass runs before the
        publish ``await``, so a leaking exception would drop the whole
        payload on the floor.
        """
        bridge = _make_bridge()
        flaky = _add_relay(bridge, "switch.flaky", "on")
        good_state = flaky.to_sber_current_state()
        flaky.to_sber_current_state = MagicMock(  # type: ignore[method-assign]
            side_effect=[good_state, KeyError("boom")]
        )
        _add_relay(bridge, "switch.lamp", "on")

        await bridge._publish_states(["switch.flaky", "switch.lamp"], force=True)

        assert bridge._mqtt_service.publish.await_count == 1, "a re-snapshot failure aborted the publish"
        payload = _status_payloads(bridge)[0]
        assert "switch.flaky" in payload["devices"]
        assert flaky._previous_sber_state is None, "an entity with a failed snapshot was marked published"


# ---------------------------------------------------------------------------
# Failure semantics of the shared publish tail
# ---------------------------------------------------------------------------


class TestPublishFailureSemantics:
    """A transport failure must be counted, logged and never marked done."""

    async def test_mqtt_error_bumps_publish_errors_and_leaves_state_dirty(self) -> None:
        bridge = _make_bridge()
        entity = _add_relay(bridge, "switch.lamp", "on")
        bridge._mqtt_service.publish.side_effect = aiomqtt.MqttError("broker gone")

        await bridge._publish_states(["switch.lamp"])

        assert bridge._stats.publish_errors == 1, "publish failure was swallowed"
        assert bridge._stats.messages_sent == 0
        assert entity.has_significant_change() is True, "state marked published although nothing was sent"
        assert bridge.message_log == [], "a failed publish was logged as an outbound message"

    async def test_missing_mqtt_service_is_counted_as_a_publish_error(self) -> None:
        """Torn-down transport must not look like a successful no-op."""
        bridge = _make_bridge()
        bridge._mqtt_service = None

        ok = await bridge._publisher._publish_logged("topic", "{}", "states")

        assert ok is False
        assert bridge._stats.publish_errors == 1
        assert bridge._stats.messages_sent == 0

    async def test_echo_publish_error_skips_devtools(self) -> None:
        bridge = _make_bridge()
        _add_relay(bridge, "switch.lamp", "on")
        bridge._mqtt_service.publish.side_effect = aiomqtt.MqttError("broker gone")

        await bridge._publish_command_echo(
            {"switch.lamp": {"states": [{"key": "on_off", "value": {"type": "BOOL", "bool_value": False}}]}}
        )

        assert bridge._stats.publish_errors == 1
        assert bridge.message_log == []

    async def test_config_publish_error_leaves_timestamp_unset(self) -> None:
        bridge = _make_bridge()
        _add_relay(bridge, "switch.lamp", "on")
        bridge._mqtt_service.publish.side_effect = aiomqtt.MqttError("broker gone")

        await bridge._publish_config()

        assert bridge._publisher.last_config_publish_time is None
        assert bridge._stats.publish_errors == 1


class TestPublishGuards:
    """Nothing goes on the wire while the bridge is not connected."""

    async def test_states_and_config_are_skipped_while_disconnected(self) -> None:
        bridge = _make_bridge()
        entity = _add_relay(bridge, "switch.lamp", "on")
        publish = bridge._mqtt_service.publish
        bridge._connected = False

        await bridge._publish_states(["switch.lamp"], force=True)
        await bridge._publish_config()
        await bridge._publish_command_echo({"switch.lamp": {"states": []}})

        assert publish.await_count == 0
        assert bridge._stats.publish_errors == 0, "a skipped publish was counted as an error"
        assert entity.has_significant_change() is True

    async def test_echo_ignores_unknown_entities(self) -> None:
        """Sber may echo devices the bridge no longer exposes."""
        bridge = _make_bridge()
        _add_relay(bridge, "switch.lamp", "on")

        await bridge._publish_command_echo(
            {
                "switch.ghost": {"states": [{"key": "on_off", "value": {"type": "BOOL", "bool_value": True}}]},
                "switch.lamp": {"states": [{"key": "on_off", "value": {"type": "BOOL", "bool_value": False}}]},
            }
        )

        payload = _status_payloads(bridge)[0]
        assert "switch.ghost" not in payload["devices"]
        assert _bool_value(payload, "switch.lamp", "on_off") is False, "the command value was not echoed back"
        assert _bool_value(payload, "switch.lamp", "online") is True, "the baseline state was dropped from the echo"

    async def test_echo_with_only_unknown_entities_publishes_nothing(self) -> None:
        bridge = _make_bridge()
        _add_relay(bridge, "switch.lamp", "on")

        await bridge._publish_command_echo({"switch.ghost": {"states": []}})

        assert bridge._mqtt_service.publish.await_count == 0

    async def test_config_records_entities_excluded_by_validation(self) -> None:
        """Broken devices are dropped from config and surfaced in stats."""
        bridge = _make_bridge()
        broken = _add_relay(bridge, "switch.broken", "on")
        _add_relay(bridge, "switch.lamp", "on")
        broken.to_sber_state = MagicMock(side_effect=KeyError("boom"))  # type: ignore[method-assign]

        await bridge._publish_config()

        assert bridge._stats.validation_failures == ["switch.broken"]
        payload = json.loads(bridge._mqtt_service.publish.await_args.args[1])
        ids = {device["id"] for device in payload["devices"]}
        assert "switch.broken" not in ids
        assert "switch.lamp" in ids


# ---------------------------------------------------------------------------
# DevTools instrumentation of the publish tail
# ---------------------------------------------------------------------------


class TestDevToolsInstrumentation:
    """Every successful publish feeds the log and the collectors."""

    async def test_outbound_payload_is_logged_verbatim(self) -> None:
        bridge = _make_bridge()
        _add_relay(bridge, "switch.lamp", "on")

        await bridge._publish_states(["switch.lamp"], force=True)

        sent_topic, sent_payload = bridge._mqtt_service.publish.await_args.args
        log = bridge.message_log
        assert len(log) == 1, "the outbound state publish was not logged for DevTools"
        assert log[0]["direction"] == "out"
        assert log[0]["topic"] == sent_topic
        assert json.loads(log[0]["payload"]) == json.loads(sent_payload)
        assert bridge._stats.messages_sent == 1

    async def test_publish_is_attached_to_the_open_correlation_trace(self) -> None:
        """DevTools timelines need the outbound publish on the entity's trace."""
        bridge = _make_bridge()
        _add_relay(bridge, "switch.lamp", "on")
        bridge.trace_collector.begin(
            trace_id="trace-1",
            trigger="ha_state_change",
            entity_ids=["switch.lamp"],
        )

        await bridge._publish_states(["switch.lamp"], force=True)

        _topic, sent_payload = bridge._mqtt_service.publish.await_args.args
        trace = bridge.trace_collector.get("trace-1")
        publish_events = [e for e in trace["events"] if e["type"] == "publish_out"]
        assert len(publish_events) == 1, "the publish was not recorded on the correlation trace"
        assert publish_events[0]["entity_id"] == "switch.lamp"
        assert publish_events[0]["topic"].endswith("up/status")
        assert json.loads(publish_events[0]["payload"]) == json.loads(sent_payload)

    async def test_state_diff_is_recorded_between_two_publishes(self) -> None:
        """The DevTools diff view is fed from the published payload."""
        bridge = _make_bridge()
        entity = _add_relay(bridge, "switch.lamp", "on")

        await bridge._publish_states(["switch.lamp"], force=True)
        entity.fill_by_ha_state({"entity_id": "switch.lamp", "state": "off", "attributes": {}})
        await bridge._publish_states(["switch.lamp"], force=True)

        diffs = [d for d in bridge.diff_collector.snapshot() if not d["is_initial"]]
        assert len(diffs) == 1, "the state change was not recorded as a diff"
        assert diffs[0]["entity_id"] == "switch.lamp"
        assert diffs[0]["changed"]["on_off"] == {
            "before": {"type": "BOOL", "bool_value": True},
            "after": {"type": "BOOL", "bool_value": False},
        }

    async def test_config_publish_is_logged_and_timestamped(self) -> None:
        bridge = _make_bridge()
        _add_relay(bridge, "switch.lamp", "on")

        await bridge._publish_config()

        assert bridge._publisher.last_config_publish_time is not None
        log = bridge.message_log
        assert [entry["direction"] for entry in log] == ["out"]
        assert log[0]["topic"].endswith("up/config")
        assert "switch.lamp" in log[0]["payload"]

    async def test_validation_collector_gets_category_and_declared_features(self) -> None:
        """The collector must see the real category and declared feature set.

        Both maps are built lazily for the published IDs only; if either is
        empty the validator silently degrades to "unknown device" and stops
        reporting missing obligatory / undeclared features.
        """
        bridge = _make_bridge()
        entity = LightEntity({"entity_id": "light.lamp", "name": "Lamp"})
        entity.fill_by_ha_state({"entity_id": "light.lamp", "state": "on", "attributes": {}})
        bridge._entities["light.lamp"] = entity
        bridge._enabled_entity_ids.append("light.lamp")
        # Wire state advertising an undeclared feature and missing both
        # obligatory ones for category "light" (on_off, online).
        entity.to_sber_current_state = MagicMock(  # type: ignore[method-assign]
            return_value={
                "light.lamp": {
                    "states": [{"key": "light_brightness", "value": {"type": "INTEGER", "integer_value": "50"}}]
                }
            }
        )
        entity.get_final_features_list = MagicMock(return_value=["on_off"])  # type: ignore[method-assign]

        await bridge._publish_states(["light.lamp"], force=True)

        issues = bridge._validation_collector.snapshot()["by_entity"]["light.lamp"]
        types = {issue["type"] for issue in issues}
        assert "missing_obligatory" in types, "category was not passed to the validation collector"
        assert "not_declared" in types, "declared features were not passed to the validation collector"
        assert {issue["category"] for issue in issues} == {"light"}


# ---------------------------------------------------------------------------
# HaStateForwarder — deterministic clock
# ---------------------------------------------------------------------------


class _FakeTimerHandle:
    """asyncio.TimerHandle stand-in for the fake loop."""

    def __init__(self, when: float, callback: Any) -> None:
        self.when = when
        self.callback = callback
        self.cancelled = False

    def cancel(self) -> None:
        """Mark the timer as cancelled so ``advance`` skips it."""
        self.cancelled = True


class _FakeLoop:
    """Deterministic loop clock exposing ``time`` and ``call_later``."""

    def __init__(self) -> None:
        self.now = 0.0
        self._timers: list[_FakeTimerHandle] = []

    def time(self) -> float:
        """Return the current fake monotonic time."""
        return self.now

    def call_later(self, delay: float, callback: Any, *args: Any) -> _FakeTimerHandle:
        """Schedule ``callback`` at ``now + delay``."""
        handle = _FakeTimerHandle(self.now + delay, lambda: callback(*args))
        self._timers.append(handle)
        return handle

    def advance(self, dt: float) -> None:
        """Advance the clock, firing every due timer in chronological order."""
        target = self.now + dt
        while True:
            due = sorted(
                (t for t in self._timers if not t.cancelled and t.when <= target),
                key=lambda t: t.when,
            )
            if not due:
                break
            handle = due[0]
            self._timers.remove(handle)
            self.now = max(self.now, handle.when)
            handle.callback()
        self.now = target

    @property
    def pending(self) -> list[_FakeTimerHandle]:
        """Return still-armed timers."""
        return [t for t in self._timers if not t.cancelled]


async def _noop() -> None:
    """Awaitable placeholder for the forwarder's async callbacks."""


class _ForwarderHarness:
    """Records everything the forwarder emits through its callbacks."""

    def __init__(self, debounce_delay: float = 0.1) -> None:
        self.loop = _FakeLoop()
        self.hass = MagicMock()
        self.hass.loop = self.loop
        self.entities: dict[str, Any] = {}
        self.linked_reverse: dict[str, tuple[str, str]] = {}
        self.published: list[list[str]] = []
        self.task_names: list[str] = []
        self.forwarder = HaStateForwarder(
            hass=self.hass,
            debounce_delay=debounce_delay,
            get_entities=lambda: self.entities,
            get_linked_reverse=lambda: self.linked_reverse,
            on_publish_states=self._publish_states,
            on_republish_config=self._republish_config,
            create_safe_task=self._create_safe_task,
        )

    def _publish_states(self, entity_ids: list[str]) -> Any:
        self.published.append(sorted(entity_ids))
        return _noop()

    def _republish_config(self) -> Any:
        return _noop()

    def _create_safe_task(self, coro: Any, *, name: str | None = None) -> Any:
        self.task_names.append(name or "")
        coro.close()
        return MagicMock()

    def fire(self, entity_id: str, state: str, *, old: str | None = "old") -> None:
        """Deliver a synthetic HA ``state_changed`` event to the forwarder."""
        event = MagicMock()
        event.data = {
            "entity_id": entity_id,
            "new_state": _FakeState(entity_id, state),
            "old_state": _FakeState(entity_id, old) if old is not None else None,
        }
        self.forwarder._on_ha_state_changed(event)


class _FakeState:
    """Minimal HA State stand-in."""

    def __init__(self, entity_id: str, state: str, attributes: dict | None = None) -> None:
        self.entity_id = entity_id
        self.state = state
        self.attributes = attributes or {}


class _FakeEntity:
    """Bridge entity stand-in recording the calls the forwarder makes."""

    def __init__(self, *, filled: bool = True, features: list[str] | None = None) -> None:
        self.is_filled_by_state = filled
        self.features = features or ["on_off"]
        self.state_changes: list[dict] = []
        self.linked_updates: list[tuple[str, dict]] = []
        self.raise_on_state_change: Exception | None = None
        self.raise_on_linked_update: Exception | None = None
        self.fill_on_state_change = False

    def process_state_change(self, old_state: dict | None, new_state: dict) -> None:
        """Record (or reject) a primary state change."""
        if self.raise_on_state_change is not None:
            raise self.raise_on_state_change
        self.state_changes.append(new_state)
        if self.fill_on_state_change:
            self.is_filled_by_state = True

    def update_linked_data(self, role: str, state: dict) -> None:
        """Record (or reject) a linked-sensor update."""
        if self.raise_on_linked_update is not None:
            raise self.raise_on_linked_update
        self.linked_updates.append((role, state))

    def get_final_features_list(self) -> list[str]:
        """Return the current feature list."""
        return list(self.features)


class TestForwarderErrorPaths:
    """A malformed entity must not break the HA event bus."""

    def test_process_state_change_exception_skips_publish(self) -> None:
        harness = _ForwarderHarness()
        entity = _FakeEntity()
        entity.raise_on_state_change = KeyError("bad attribute")
        harness.entities["light.lamp"] = entity

        harness.fire("light.lamp", "on")
        harness.loop.advance(10)

        assert harness.published == [], "a broken entity still scheduled a publish"
        assert harness.loop.pending == []

    def test_unfilled_entity_becoming_filled_republishes_config(self) -> None:
        harness = _ForwarderHarness()
        entity = _FakeEntity(filled=False)
        entity.fill_on_state_change = True
        harness.entities["light.lamp"] = entity

        harness.fire("light.lamp", "on")

        assert "republish_config_new_entity" in harness.task_names, (
            "an entity that became available did not trigger a config republish"
        )

    def test_already_filled_entity_does_not_republish_config(self) -> None:
        harness = _ForwarderHarness()
        harness.entities["light.lamp"] = _FakeEntity(filled=True)

        harness.fire("light.lamp", "on")

        assert harness.task_names == []

    def test_linked_update_exception_is_contained(self) -> None:
        harness = _ForwarderHarness()
        primary = _FakeEntity()
        primary.raise_on_linked_update = AttributeError("bad linked payload")
        harness.entities["climate.ac"] = primary
        harness.linked_reverse["sensor.temp"] = ("climate.ac", "current_temperature")

        harness.fire("sensor.temp", "21.5")
        harness.loop.advance(10)

        assert harness.published == [], "a broken linked sensor still scheduled a publish"
        assert harness.task_names == []

    def test_linked_update_feature_change_republishes_config(self) -> None:
        harness = _ForwarderHarness()
        primary = _FakeEntity(features=["on_off"])
        harness.entities["climate.ac"] = primary
        harness.linked_reverse["sensor.temp"] = ("climate.ac", "current_temperature")

        def _grow_features(role: str, state: dict) -> None:
            primary.features = ["on_off", "temperature"]

        primary.update_linked_data = _grow_features  # type: ignore[method-assign]

        harness.fire("sensor.temp", "21.5")
        harness.loop.advance(10)

        assert "republish_config_linked" in harness.task_names
        assert harness.published == [["climate.ac"]], "linked update was not forwarded to the primary entity"

    def test_linked_sensor_with_unknown_primary_is_ignored(self) -> None:
        """A stale link must not schedule a publish for a missing primary."""
        harness = _ForwarderHarness()
        harness.linked_reverse["sensor.temp"] = ("climate.gone", "current_temperature")

        harness.fire("sensor.temp", "21.5")
        harness.loop.advance(10)

        assert harness.published == []
        assert harness.task_names == []

    def test_unknown_entity_is_ignored(self) -> None:
        harness = _ForwarderHarness()

        harness.fire("light.ghost", "on")
        harness.loop.advance(10)

        assert harness.published == []


class TestForwarderDebounce:
    """Timer arithmetic of the shared debounce."""

    def test_rapid_changes_coalesce_into_one_publish(self) -> None:
        harness = _ForwarderHarness(debounce_delay=1.0)
        harness.entities["light.a"] = _FakeEntity()
        harness.entities["light.b"] = _FakeEntity()

        harness.fire("light.a", "on")
        harness.loop.advance(0.5)
        harness.fire("light.b", "on")
        harness.loop.advance(0.9)
        assert harness.published == [], "published before the debounce window elapsed"

        harness.loop.advance(0.2)
        assert harness.published == [["light.a", "light.b"]]

    def test_max_wait_forces_flush_under_continuous_chatter(self) -> None:
        """A chattering entity must not defer everyone else indefinitely."""
        harness = _ForwarderHarness(debounce_delay=1.0)
        harness.entities["sensor.noisy"] = _FakeEntity()
        harness.entities["light.important"] = _FakeEntity()

        harness.fire("light.important", "on")
        for _ in range(20):  # 20 * 0.5s = 10s of chatter, debounce never expires
            harness.loop.advance(0.5)
            harness.fire("sensor.noisy", "1")

        assert harness.published, "continuous chatter starved the debounce flush"
        deadline = 1.0 * DEBOUNCE_MAX_WAIT_FACTOR
        assert harness.loop.now >= deadline
        assert "light.important" in harness.published[0], "the first flush lost the pending entity"

    def test_max_wait_anchor_resets_after_a_flush(self) -> None:
        """A stale max-wait anchor would disable debouncing forever.

        The second burst starts *after* the first burst's max-wait deadline
        has passed; if ``_pending_since`` were not cleared on flush, the
        computed delay would be 0 and every later event would publish on
        its own instead of coalescing.
        """
        harness = _ForwarderHarness(debounce_delay=1.0)
        harness.entities["light.a"] = _FakeEntity()

        harness.fire("light.a", "on")
        harness.loop.advance(1.5)
        assert len(harness.published) == 1

        # t=1.5 → jump past the old deadline (0 + 1.0 * DEBOUNCE_MAX_WAIT_FACTOR).
        harness.loop.advance(1.0 * DEBOUNCE_MAX_WAIT_FACTOR)
        harness.fire("light.a", "off")
        harness.loop.advance(0.4)
        assert len(harness.published) == 1, "publish fired inside the debounce window — stale max-wait anchor"
        harness.fire("light.a", "on")
        harness.loop.advance(1.5)

        assert len(harness.published) == 2, "the two changes of the second burst did not coalesce"

    def test_unsubscribe_all_cancels_the_pending_flush(self) -> None:
        harness = _ForwarderHarness(debounce_delay=1.0)
        harness.entities["light.a"] = _FakeEntity()

        harness.fire("light.a", "on")
        harness.forwarder.unsubscribe_all()

        assert harness.loop.pending == [], "unsubscribe_all left a debounce timer armed"
        harness.loop.advance(10)
        assert harness.published == [], "a debounce timer fired after unsubscribe_all"

    def test_subscribe_flushes_pending_before_resubscribing(self) -> None:
        """Hot-reload must not drop already-accumulated state updates."""
        harness = _ForwarderHarness(debounce_delay=1.0)
        harness.entities["light.a"] = _FakeEntity()

        harness.fire("light.a", "on")
        with patch(
            "custom_components.sber_mqtt_bridge.ha_state_forwarder.async_track_state_change_event",
            return_value=MagicMock(),
        ):
            harness.forwarder.subscribe(["light.a"])

        assert harness.published == [["light.a"]], "pending state update was dropped on resubscribe"

    def test_flush_pending_is_a_noop_without_pending_ids(self) -> None:
        harness = _ForwarderHarness()

        harness.forwarder.flush_pending()

        assert harness.published == []

    def test_subscribe_replaces_previous_listeners(self) -> None:
        harness = _ForwarderHarness()
        first_unsub = MagicMock()
        second_unsub = MagicMock()
        with patch(
            "custom_components.sber_mqtt_bridge.ha_state_forwarder.async_track_state_change_event",
            side_effect=[first_unsub, second_unsub],
        ):
            harness.forwarder.subscribe(["light.a"])
            harness.forwarder.subscribe(["light.b"])

        first_unsub.assert_called_once_with()
        second_unsub.assert_not_called()

    def test_subscribe_with_empty_list_only_unsubscribes(self) -> None:
        harness = _ForwarderHarness()
        unsub = MagicMock()
        with patch(
            "custom_components.sber_mqtt_bridge.ha_state_forwarder.async_track_state_change_event",
            return_value=unsub,
        ) as tracker:
            harness.forwarder.subscribe(["light.a"])
            harness.forwarder.subscribe([])

        unsub.assert_called_once_with()
        assert tracker.call_count == 1

    def test_set_debounce_delay_applies_to_the_next_schedule(self) -> None:
        harness = _ForwarderHarness(debounce_delay=5.0)
        harness.entities["light.a"] = _FakeEntity()

        harness.forwarder.set_debounce_delay(0.5)
        harness.fire("light.a", "on")
        harness.loop.advance(0.6)

        assert harness.published == [["light.a"]]

    def test_state_change_without_new_state_is_ignored(self) -> None:
        harness = _ForwarderHarness()
        harness.entities["light.a"] = _FakeEntity()
        event = MagicMock()
        event.data = {"entity_id": "light.a", "new_state": None, "old_state": None}

        harness.forwarder._on_ha_state_changed(event)
        harness.loop.advance(10)

        assert harness.published == []


class TestForwarderTraceHook:
    """The optional DevTools hook must never break forwarding."""

    def test_trace_hook_receives_context_and_state(self) -> None:
        harness = _ForwarderHarness()
        harness.entities["light.a"] = _FakeEntity()
        seen: list[tuple] = []
        harness.forwarder._on_trace_state_change = lambda ctx, eid, state: seen.append((ctx, eid, state["state"]))

        event = MagicMock()
        event.data = {
            "entity_id": "light.a",
            "new_state": _FakeState("light.a", "on"),
            "old_state": None,
        }
        event.context.id = "ctx-1"
        harness.forwarder._on_ha_state_changed(event)

        assert seen == [("ctx-1", "light.a", "on")]

    def test_failing_trace_hook_does_not_block_publish(self) -> None:
        harness = _ForwarderHarness(debounce_delay=1.0)
        harness.entities["light.a"] = _FakeEntity()

        def _boom(ctx: Any, eid: str, state: dict) -> None:
            raise RuntimeError("devtools exploded")

        harness.forwarder._on_trace_state_change = _boom

        harness.fire("light.a", "on")
        harness.loop.advance(1.5)

        assert harness.published == [["light.a"]]


class TestForwarderIsolationFromAsyncio:
    """Guard against the harness accidentally leaking real tasks."""

    async def test_publish_callback_receives_a_plain_id_list(self) -> None:
        harness = _ForwarderHarness(debounce_delay=0.01)
        harness.entities["light.a"] = _FakeEntity()

        harness.fire("light.a", "on")
        harness.loop.advance(0.05)
        await asyncio.sleep(0)

        assert harness.published == [["light.a"]]
        assert harness.task_names == ["debounced_publish"]
