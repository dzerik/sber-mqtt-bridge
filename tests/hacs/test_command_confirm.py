"""Per-key confirmation of Sber commands against what the bridge reports back.

Issue #63: a cloud lamp accepted ``turn_on`` yet never changed, and nothing
in DevTools said so — a trace only shows that a service call was made.  The
tracker compares each commanded key with the state the bridge later
publishes from Home Assistant, which is exactly what the Sber app will
display.
"""

from __future__ import annotations

import time

from custom_components.sber_mqtt_bridge.command_confirm import CommandConfirmTracker


def _int(key: str, value: int) -> dict:
    return {"key": key, "value": {"type": "INTEGER", "integer_value": str(value)}}


def _bool(key: str, value: bool) -> dict:
    return {"key": key, "value": {"type": "BOOL", "bool_value": value}}


def _colour(h: int, s: int, v: int) -> dict:
    return {"key": "light_colour", "value": {"type": "COLOUR", "colour_value": {"h": h, "s": s, "v": v}}}


def _tracker(**kwargs) -> CommandConfirmTracker:
    return CommandConfirmTracker(maxlen=50, timeout=10.0, **kwargs)


class TestConfirmation:
    def test_all_keys_reported_back_confirms(self) -> None:
        tr = _tracker()
        rec = tr.record_command("light.lamp", [_bool("on_off", True), _int("light_brightness", 500)], context_id="c1")
        tr.observe_state("light.lamp", [_bool("on_off", True), _int("light_brightness", 500), _bool("online", True)])
        got = tr.get(rec.command_id)
        assert got["status"] == "confirmed"
        assert got["context_id"] == "c1"
        assert {k["key"]: k["matched"] for k in got["keys"]} == {"on_off": True, "light_brightness": True}

    def test_waits_while_state_has_not_caught_up(self) -> None:
        tr = _tracker()
        rec = tr.record_command("light.lamp", [_int("light_brightness", 500)])
        tr.observe_state("light.lamp", [_int("light_brightness", 300)])
        got = tr.get(rec.command_id)
        assert got["status"] == "pending"
        assert got["keys"][0]["reported"] == {"type": "INTEGER", "integer_value": "300"}
        tr.observe_state("light.lamp", [_int("light_brightness", 500)])
        assert tr.get(rec.command_id)["status"] == "confirmed"

    def test_timeout_without_match_is_not_confirmed(self) -> None:
        tr = CommandConfirmTracker(maxlen=10, timeout=0.01)
        rec = tr.record_command("light.lamp", [_bool("on_off", True)])
        tr.observe_state("light.lamp", [_bool("on_off", False)])
        time.sleep(0.02)
        assert tr.sweep() == [rec.command_id]
        assert tr.get(rec.command_id)["status"] == "not_confirmed"

    def test_timeout_with_some_keys_is_partial(self) -> None:
        tr = CommandConfirmTracker(maxlen=10, timeout=0.01)
        rec = tr.record_command("light.lamp", [_bool("on_off", True), _int("light_colour_temp", 400)])
        tr.observe_state("light.lamp", [_bool("on_off", True), _int("light_colour_temp", 0)])
        time.sleep(0.02)
        tr.sweep()
        assert tr.get(rec.command_id)["status"] == "partial"

    def test_other_entity_state_does_not_confirm(self) -> None:
        tr = _tracker()
        rec = tr.record_command("light.lamp", [_bool("on_off", True)])
        tr.observe_state("light.other", [_bool("on_off", True)])
        assert tr.get(rec.command_id)["status"] == "pending"


class TestWhatIsTracked:
    def test_command_only_keys_are_not_tracked(self) -> None:
        """``open_set`` holds no state: nothing could ever confirm it."""
        tr = _tracker()
        rec = tr.record_command(
            "cover.gate", [{"key": "open_set", "value": {"type": "ENUM", "enum_value": "open"}}]
        )
        assert rec is None
        assert tr.snapshot() == []

    def test_newer_command_on_the_same_key_supersedes(self) -> None:
        """A dragged slider sends many values; only the last one must be judged."""
        tr = _tracker()
        old = tr.record_command("light.lamp", [_int("light_brightness", 300)])
        new = tr.record_command("light.lamp", [_int("light_brightness", 700)])
        assert tr.get(old.command_id)["status"] == "superseded"
        tr.observe_state("light.lamp", [_int("light_brightness", 700)])
        assert tr.get(new.command_id)["status"] == "confirmed"

    def test_different_key_does_not_supersede(self) -> None:
        tr = _tracker()
        first = tr.record_command("light.lamp", [_bool("on_off", True)])
        tr.record_command("light.lamp", [_int("light_brightness", 700)])
        assert tr.get(first.command_id)["status"] == "pending"


class TestValueMatching:
    def test_integer_as_string_and_number_match(self) -> None:
        tr = _tracker()
        rec = tr.record_command("light.lamp", [{"key": "light_brightness", "value": {"type": "INTEGER", "integer_value": 500}}])
        tr.observe_state("light.lamp", [_int("light_brightness", 500)])
        assert tr.get(rec.command_id)["status"] == "confirmed"

    def test_tolerance_absorbs_round_trip_rounding(self) -> None:
        tr = _tracker(tolerance_for=lambda _eid, key, _type: 3 if key == "light_brightness" else 0)
        rec = tr.record_command("light.lamp", [_int("light_brightness", 500)])
        tr.observe_state("light.lamp", [_int("light_brightness", 498)])
        assert tr.get(rec.command_id)["status"] == "confirmed"

    def test_beyond_tolerance_is_not_a_match(self) -> None:
        tr = _tracker(tolerance_for=lambda *_: 3)
        rec = tr.record_command("light.lamp", [_int("light_brightness", 500)])
        tr.observe_state("light.lamp", [_int("light_brightness", 490)])
        assert tr.get(rec.command_id)["status"] == "pending"

    def test_colour_components_are_compared_with_their_own_slack(self) -> None:
        tr = _tracker()
        rec = tr.record_command("light.lamp", [_colour(120, 800, 600)])
        tr.observe_state("light.lamp", [_colour(121, 795, 602)])
        assert tr.get(rec.command_id)["status"] == "confirmed"

    def test_different_colour_is_not_a_match(self) -> None:
        tr = _tracker()
        rec = tr.record_command("light.lamp", [_colour(120, 800, 600)])
        tr.observe_state("light.lamp", [_colour(240, 800, 600)])
        assert tr.get(rec.command_id)["status"] == "pending"

    def test_enum_and_type_mismatch(self) -> None:
        tr = _tracker()
        rec = tr.record_command("light.lamp", [{"key": "light_mode", "value": {"type": "ENUM", "enum_value": "white"}}])
        tr.observe_state("light.lamp", [{"key": "light_mode", "value": {"type": "ENUM", "enum_value": "colour"}}])
        assert tr.get(rec.command_id)["status"] == "pending"
        tr.observe_state("light.lamp", [{"key": "light_mode", "value": {"type": "ENUM", "enum_value": "white"}}])
        assert tr.get(rec.command_id)["status"] == "confirmed"


class TestBufferAndSubscribers:
    def test_ring_buffer_and_clear(self) -> None:
        tr = CommandConfirmTracker(maxlen=2, timeout=10.0)
        for i in range(3):
            rec = tr.record_command(f"switch.s{i}", [_bool("on_off", True)])
            tr.observe_state(f"switch.s{i}", [_bool("on_off", True)])
        assert [c["entity_id"] for c in tr.snapshot()] == ["switch.s1", "switch.s2"]
        tr.clear()
        assert tr.snapshot() == []
        assert rec is not None

    def test_resize_keeps_newest(self) -> None:
        tr = CommandConfirmTracker(maxlen=5, timeout=10.0)
        for i in range(4):
            tr.record_command(f"switch.s{i}", [_bool("on_off", True)])
            tr.observe_state(f"switch.s{i}", [_bool("on_off", True)])
        tr.resize(2)
        assert [c["entity_id"] for c in tr.snapshot()] == ["switch.s2", "switch.s3"]

    def test_subscribers_get_lifecycle_events(self) -> None:
        tr = _tracker()
        events: list[tuple[str, str]] = []
        unsub = tr.subscribe(lambda kind, rec: events.append((kind, rec.status)))
        tr.record_command("switch.s", [_bool("on_off", True)])
        tr.observe_state("switch.s", [_bool("on_off", True)])
        unsub()
        tr.record_command("switch.s", [_bool("on_off", False)])
        assert events == [("command_started", "pending"), ("command_closed", "confirmed")]

    def test_subscriber_error_does_not_break_tracking(self) -> None:
        tr = _tracker()

        def boom(*_):
            raise RuntimeError("subscriber bug")

        tr.subscribe(boom)
        rec = tr.record_command("switch.s", [_bool("on_off", True)])
        tr.observe_state("switch.s", [_bool("on_off", True)])
        assert tr.get(rec.command_id)["status"] == "confirmed"

    def test_malformed_states_are_ignored(self) -> None:
        tr = _tracker()
        assert tr.record_command("switch.s", ["junk", {"key": 5}, {"value": {}}]) is None
        rec = tr.record_command("switch.s", [_bool("on_off", True)])
        tr.observe_state("switch.s", ["junk", {"key": "on_off"}])
        assert tr.get(rec.command_id)["status"] == "pending"
