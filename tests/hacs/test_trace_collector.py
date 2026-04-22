"""Unit tests for :class:`TraceCollector`.

Breakage of this module means the DevTools correlation timeline shows
events under the wrong trace, drops events, or leaks memory — all
user-visible regressions in the debugging path.  The tests are purely
synchronous and HA-independent (the collector deliberately exposes a
manual :meth:`sweep` so callers own the timer).
"""

from __future__ import annotations

import time

from custom_components.sber_mqtt_bridge.trace_collector import (
    Trace,
    TraceCollector,
    TraceEvent,
)


class TestBeginTrace:
    """Opening a trace from a Sber command or a raw HA state change."""

    def test_begin_creates_trace_with_initiating_event(self) -> None:
        tc = TraceCollector()
        trace = tc.begin(
            trace_id="ctx-1",
            trigger="sber_command",
            entity_ids=["light.kitchen"],
            topic="down/commands",
            payload={"on": True},
        )
        # An empty trace would be useless to DevTools — the "something happened"
        # event is what the user sees at the top of the timeline.
        assert trace.trace_id == "ctx-1"
        assert trace.status == "active"
        assert trace.trigger == "sber_command"
        assert trace.entity_ids == {"light.kitchen"}
        assert len(trace.events) == 1
        assert trace.events[0].type == "sber_command"
        assert trace.events[0].payload == {"on": True}

    def test_begin_twice_same_id_merges_not_duplicates(self) -> None:
        # Two commands touching overlapping entities under the same HA
        # Context (rare but real — multi-device service calls) must not
        # become two separate traces with the same id or the UI breaks.
        tc = TraceCollector()
        tc.begin(trace_id="ctx-1", trigger="sber_command", entity_ids=["light.a"])
        trace = tc.begin(trace_id="ctx-1", trigger="sber_command", entity_ids=["light.b"])
        assert trace.entity_ids == {"light.a", "light.b"}
        # Only one initiating event — second begin must not re-emit one.
        assert len(trace.events) == 1

    def test_begin_with_empty_id_generates_synthetic(self) -> None:
        # We must never drop a trace just because the caller had no
        # Context — DevTools still needs to show it.
        tc = TraceCollector()
        trace = tc.begin(trace_id=None, trigger="ha_state_change", entity_ids=["switch.x"])
        assert trace.trace_id.startswith("synthetic-")
        assert tc.get(trace.trace_id) is not None


class TestRecord:
    """Appending follow-up events."""

    def test_record_appends_event_and_bumps_last_event_at(self) -> None:
        tc = TraceCollector()
        tc.begin(trace_id="c", trigger="sber_command", entity_ids=["light.x"])
        before = tc.get("c")["last_event_at"]
        time.sleep(0.01)
        tc.record("c", type_="ha_service_call", entity_id="light.x", payload={"svc": "turn_on"})
        after = tc.get("c")
        assert len(after["events"]) == 2
        assert after["events"][-1]["type"] == "ha_service_call"
        # last_event_at must advance so sweep's timeout logic works.
        assert after["last_event_at"] > before

    def test_record_unknown_trace_opens_new_with_trigger_if_new(self) -> None:
        # HA state changes initiated by the user (not by a Sber command)
        # arrive with a context.id that we've never seen. The collector
        # must still capture them so DevTools covers both directions.
        tc = TraceCollector()
        trace = tc.record(
            "fresh-ctx",
            type_="ha_state_changed",
            entity_id="switch.lamp",
            trigger_if_new="ha_state_change",
        )
        assert trace is not None
        assert trace.trigger == "ha_state_change"
        assert trace.entity_ids == {"switch.lamp"}

    def test_record_with_falsy_id_is_noop(self) -> None:
        tc = TraceCollector()
        assert tc.record("", type_="ha_service_call") is None
        assert tc.record(None, type_="ha_service_call") is None  # type: ignore[arg-type]


class TestPublishAttachment:
    """Outbound publishes must glue onto the right trace."""

    def test_publish_attaches_to_last_trace_for_entity(self) -> None:
        tc = TraceCollector()
        tc.begin(trace_id="c", trigger="sber_command", entity_ids=["light.x"])
        res = tc.record_publish("light.x", topic="up/status", payload="{}")
        assert res is not None
        events = tc.get("c")["events"]
        assert events[-1]["type"] == "publish_out"
        assert events[-1]["topic"] == "up/status"

    def test_publish_without_active_trace_returns_none(self) -> None:
        # Publishes during startup (before any Sber command) must not crash
        # and must not resurrect closed traces.
        tc = TraceCollector()
        assert tc.record_publish("light.ghost", topic="up/status", payload="{}") is None

    def test_publish_after_close_drops_attachment(self) -> None:
        tc = TraceCollector()
        tc.begin(trace_id="c", trigger="sber_command", entity_ids=["light.x"])
        tc.close("c")
        # Publishes for a closed trace must not re-open it, else a late
        # publish would flip "timeout" back into the active pool.
        assert tc.record_publish("light.x", topic="up/status", payload="{}") is None


class TestSilentRejection:
    """Silent-rejection audit integration."""

    def test_silent_rejection_marks_trace_failed(self) -> None:
        tc = TraceCollector()
        tc.begin(trace_id="c", trigger="sber_command", entity_ids=["light.x"])
        affected = tc.record_silent_rejection(["light.x"])
        assert affected == ["c"]
        trace = tc.get("c")
        assert trace["status"] == "failed"
        assert trace["events"][-1]["type"] == "silent_rejection"

    def test_silent_rejection_skips_unknown_entities(self) -> None:
        tc = TraceCollector()
        # Entity with no active trace — must be silently ignored, not crash.
        assert tc.record_silent_rejection(["light.ghost"]) == []


class TestClose:
    """Trace closure and status inference."""

    def test_close_moves_from_active_to_closed(self) -> None:
        tc = TraceCollector()
        tc.begin(trace_id="c", trigger="sber_command", entity_ids=["light.x"])
        tc.close("c")
        # Active pool is empty, snapshot still finds it, get() still works.
        snap = tc.snapshot(include_active=False)
        assert any(t["trace_id"] == "c" for t in snap)
        assert tc.get("c") is not None

    def test_close_sets_success_when_progress_seen(self) -> None:
        tc = TraceCollector()
        tc.begin(trace_id="c", trigger="sber_command", entity_ids=["light.x"])
        tc.record("c", type_="ha_service_call", entity_id="light.x")
        tc.close("c")
        assert tc.get("c")["status"] == "success"

    def test_close_sets_timeout_when_no_progress(self) -> None:
        # A sber_command with no service call / no state change means
        # the bridge did nothing — the UI should mark it as dead.
        tc = TraceCollector()
        tc.begin(trace_id="c", trigger="sber_command", entity_ids=["light.x"])
        tc.close("c")
        assert tc.get("c")["status"] == "timeout"

    def test_close_preserves_failed_status(self) -> None:
        tc = TraceCollector()
        tc.begin(trace_id="c", trigger="sber_command", entity_ids=["light.x"])
        tc.record_silent_rejection(["light.x"])
        tc.close("c")
        # A failed trace must stay failed — the heuristic must not "upgrade"
        # it back to success because a ha_service_call happened before
        # the silent rejection was detected.
        assert tc.get("c")["status"] == "failed"


class TestSweep:
    """Inactivity-driven auto-close."""

    def test_sweep_closes_idle_traces_only(self) -> None:
        tc = TraceCollector(trace_timeout=0.05)
        tc.begin(trace_id="old", trigger="sber_command", entity_ids=["light.x"])
        time.sleep(0.1)
        tc.begin(trace_id="fresh", trigger="sber_command", entity_ids=["light.y"])
        closed = tc.sweep()
        assert closed == ["old"]
        # Fresh trace must remain active — sweeping must be selective.
        assert tc.get("fresh")["status"] == "active"


class TestSubscribers:
    """Real-time fan-out for the WS subscribe channel."""

    def test_subscriber_receives_lifecycle_events(self) -> None:
        tc = TraceCollector()
        kinds: list[str] = []

        def cb(kind: str, trace: Trace) -> None:
            kinds.append(kind)

        unsub = tc.subscribe(cb)
        tc.begin(trace_id="c", trigger="sber_command", entity_ids=["light.x"])
        tc.record("c", type_="ha_service_call", entity_id="light.x")
        tc.close("c")
        assert kinds == ["trace_started", "trace_updated", "trace_closed"]
        unsub()
        tc.begin(trace_id="c2", trigger="sber_command", entity_ids=["light.y"])
        # After unsub the callback must stop — otherwise DevTools leaks
        # subscribers across panel reloads.
        assert kinds == ["trace_started", "trace_updated", "trace_closed"]

    def test_subscriber_exception_does_not_break_collector(self) -> None:
        tc = TraceCollector()

        def bad(_kind: str, _trace: Trace) -> None:
            raise RuntimeError("boom")

        tc.subscribe(bad)
        # Must not raise — a buggy UI subscriber must never take the
        # bridge down with it.
        tc.begin(trace_id="c", trigger="sber_command", entity_ids=["light.x"])


class TestRingBuffer:
    """Bounded memory contract."""

    def test_resize_keeps_newest(self) -> None:
        tc = TraceCollector(maxlen=10)
        for i in range(5):
            tc.begin(trace_id=f"c{i}", trigger="sber_command", entity_ids=["light.x"])
            tc.close(f"c{i}")
        tc.resize(3)
        snap = tc.snapshot(include_active=False)
        # Only the last 3 trace ids must remain after shrink.
        ids = [t["trace_id"] for t in snap]
        assert ids == ["c2", "c3", "c4"]

    def test_clear_empties_everything(self) -> None:
        tc = TraceCollector()
        tc.begin(trace_id="a", trigger="sber_command", entity_ids=["light.x"])
        tc.begin(trace_id="b", trigger="sber_command", entity_ids=["light.y"])
        tc.close("b")
        tc.clear()
        assert tc.snapshot() == []


class TestSerialization:
    """JSON-serializable output for the WS API."""

    def test_trace_as_dict_is_json_serializable(self) -> None:
        import json

        tc = TraceCollector()
        tc.begin(
            trace_id="c",
            trigger="sber_command",
            entity_ids=["light.x"],
            payload={"on": True},
        )
        tc.record("c", type_="ha_service_call", entity_id="light.x")
        tc.close("c")
        # If json.dumps chokes, the WS command will fail silently for users.
        data = json.dumps(tc.snapshot())
        assert "trace_id" in data
        assert "ha_service_call" in data

    def test_event_as_dict_preserves_fields(self) -> None:
        ev = TraceEvent(
            ts=1.0,
            type="publish_out",
            entity_id="light.x",
            topic="up/status",
            payload="{}",
            duration_ms=42.0,
        )
        assert ev.as_dict() == {
            "ts": 1.0,
            "type": "publish_out",
            "entity_id": "light.x",
            "topic": "up/status",
            "payload": "{}",
            "duration_ms": 42.0,
        }
