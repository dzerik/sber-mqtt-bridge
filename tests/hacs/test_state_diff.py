"""Unit tests for :class:`DiffCollector`.

A faulty diff collector silently turns "nothing changed" into a
phantom entry or swallows a real state transition — both break the
DevTools "what actually changed" view without any other visible
symptom.  These tests pin the delta algorithm, the ring-buffer
contract, and the full-payload entry point used by the publish path.
"""

from __future__ import annotations

import json

from custom_components.sber_mqtt_bridge.state_diff import (
    DiffCollector,
    StateDiff,
)


def _v(kind: str, **body) -> dict:
    """Build a Sber value dict — ``{"type": ..., "<kind>_value": ...}``."""
    return {"type": kind.upper(), **body}


class TestInitialPublish:
    """First publish per entity must establish a baseline."""

    def test_initial_publish_default_drops_record(self) -> None:
        # Most users never want to see the startup flood — initial is
        # silent by default.
        dc = DiffCollector()
        res = dc.update("light.x", [{"key": "on_off", "value": _v("bool", bool_value=True)}])
        assert res is None
        # Baseline is still captured so the next call produces a real diff.
        assert dc.get_last_state("light.x") == {"on_off": _v("bool", bool_value=True)}

    def test_initial_publish_opt_in_emits_added_record(self) -> None:
        dc = DiffCollector(include_initial=True)
        res = dc.update("light.x", [{"key": "on_off", "value": _v("bool", bool_value=True)}])
        assert res is not None
        assert res.is_initial is True
        assert "on_off" in res.added

    def test_empty_initial_payload_drops_even_with_opt_in(self) -> None:
        # A truly empty states list is noise — don't record it even
        # when the user asked for initial diffs.
        dc = DiffCollector(include_initial=True)
        assert dc.update("light.x", []) is None


class TestDeltaMath:
    """The core add/remove/change classification."""

    def _prime(self, dc: DiffCollector, entity="light.x") -> None:
        dc.update(
            entity,
            [
                {"key": "on_off", "value": _v("bool", bool_value=True)},
                {"key": "light_brightness", "value": _v("integer", integer_value=50)},
            ],
        )

    def test_changed_key_lands_in_changed_with_before_after(self) -> None:
        dc = DiffCollector()
        self._prime(dc)
        res = dc.update(
            "light.x",
            [
                {"key": "on_off", "value": _v("bool", bool_value=True)},
                {"key": "light_brightness", "value": _v("integer", integer_value=75)},
            ],
        )
        assert res is not None
        assert res.changed.keys() == {"light_brightness"}
        # Before/after must both be present — missing "before" turns
        # the UI into a guessing game about what the previous value was.
        assert res.changed["light_brightness"]["before"] == _v("integer", integer_value=50)
        assert res.changed["light_brightness"]["after"] == _v("integer", integer_value=75)
        assert res.added == {}
        assert res.removed == {}

    def test_added_key_lands_in_added(self) -> None:
        dc = DiffCollector()
        self._prime(dc)
        res = dc.update(
            "light.x",
            [
                {"key": "on_off", "value": _v("bool", bool_value=True)},
                {"key": "light_brightness", "value": _v("integer", integer_value=50)},
                {"key": "light_colour", "value": _v("integer", integer_value=16711680)},
            ],
        )
        assert res is not None
        assert "light_colour" in res.added
        assert res.changed == {}

    def test_removed_key_lands_in_removed(self) -> None:
        dc = DiffCollector()
        self._prime(dc)
        res = dc.update(
            "light.x",
            [{"key": "on_off", "value": _v("bool", bool_value=True)}],
        )
        assert res is not None
        assert "light_brightness" in res.removed
        # Keeping the value on removed helps the UI show "what disappeared",
        # otherwise the removal card would be empty.
        assert res.removed["light_brightness"] == _v("integer", integer_value=50)

    def test_equal_payload_returns_none(self) -> None:
        dc = DiffCollector()
        self._prime(dc)
        assert (
            dc.update(
                "light.x",
                [
                    {"key": "on_off", "value": _v("bool", bool_value=True)},
                    {"key": "light_brightness", "value": _v("integer", integer_value=50)},
                ],
            )
            is None
        )

    def test_entries_without_key_are_ignored(self) -> None:
        dc = DiffCollector()
        self._prime(dc)
        # A malformed state entry must not crash or corrupt the baseline —
        # otherwise one bad payload poisons every future diff for the entity.
        res = dc.update(
            "light.x",
            [
                {"key": "on_off", "value": _v("bool", bool_value=True)},
                {"value": _v("integer", integer_value=99)},  # no "key"
                {"key": "light_brightness", "value": _v("integer", integer_value=50)},
            ],
        )
        assert res is None


class TestBaselineLifecycle:
    """Baseline reset + per-entity isolation."""

    def test_reset_entity_makes_next_update_initial(self) -> None:
        dc = DiffCollector(include_initial=True)
        dc.update("light.x", [{"key": "on_off", "value": _v("bool", bool_value=True)}])
        dc.reset_entity("light.x")
        res = dc.update("light.x", [{"key": "on_off", "value": _v("bool", bool_value=True)}])
        assert res is not None
        assert res.is_initial is True

    def test_entities_have_independent_baselines(self) -> None:
        # Cross-pollination between entities would be a catastrophic
        # bug — the diff for light.x must never reflect changes to light.y.
        dc = DiffCollector()
        dc.update("light.x", [{"key": "on_off", "value": _v("bool", bool_value=True)}])
        dc.update("light.y", [{"key": "on_off", "value": _v("bool", bool_value=False)}])
        res = dc.update("light.x", [{"key": "on_off", "value": _v("bool", bool_value=False)}])
        assert res is not None
        assert res.changed["on_off"]["before"] == _v("bool", bool_value=True)

    def test_get_last_state_returns_deep_copy(self) -> None:
        dc = DiffCollector()
        dc.update("light.x", [{"key": "on_off", "value": _v("bool", bool_value=True)}])
        snap = dc.get_last_state("light.x")
        assert snap is not None
        snap["on_off"]["bool_value"] = False
        # Mutating the returned snapshot must not leak back into the collector.
        assert dc.get_last_state("light.x")["on_off"]["bool_value"] is True


class TestRecordPublishPayload:
    """Entry point wired into the bridge publish path."""

    def test_parses_json_string(self) -> None:
        dc = DiffCollector(include_initial=True)
        payload = json.dumps(
            {
                "devices": {
                    "light.x": {
                        "states": [
                            {"key": "on_off", "value": _v("bool", bool_value=True)},
                        ],
                    },
                    "switch.y": {
                        "states": [
                            {"key": "on_off", "value": _v("bool", bool_value=False)},
                        ],
                    },
                }
            }
        )
        diffs = dc.record_publish_payload(payload, topic="up/status")
        assert {d.entity_id for d in diffs} == {"light.x", "switch.y"}

    def test_accepts_pre_parsed_dict(self) -> None:
        dc = DiffCollector(include_initial=True)
        data = {"devices": {"light.x": {"states": [{"key": "on_off", "value": {}}]}}}
        assert len(dc.record_publish_payload(data)) == 1

    def test_invalid_json_returns_empty_without_raising(self) -> None:
        # A publish with unexpected shape must not break the bridge.
        dc = DiffCollector()
        assert dc.record_publish_payload("not json") == []
        assert dc.record_publish_payload("{}") == []
        assert dc.record_publish_payload({"devices": "nope"}) == []  # type: ignore[arg-type]

    def test_device_without_states_list_is_skipped(self) -> None:
        dc = DiffCollector(include_initial=True)
        payload = {"devices": {"ghost": {"name": "noop"}, "light.x": {"states": []}}}
        # "ghost" has no states — must be skipped silently.
        diffs = dc.record_publish_payload(payload)
        assert diffs == []


class TestSubscribers:
    def test_subscriber_receives_only_non_empty_diffs(self) -> None:
        dc = DiffCollector()
        received: list[StateDiff] = []
        dc.subscribe(received.append)
        # Prime — no initial emission by default.
        dc.update("light.x", [{"key": "on_off", "value": _v("bool", bool_value=True)}])
        assert received == []
        # Real change — one event.
        dc.update("light.x", [{"key": "on_off", "value": _v("bool", bool_value=False)}])
        # No change — still one event.
        dc.update("light.x", [{"key": "on_off", "value": _v("bool", bool_value=False)}])
        assert len(received) == 1

    def test_unsubscribe_stops_delivery(self) -> None:
        dc = DiffCollector()
        received: list[StateDiff] = []
        unsub = dc.subscribe(received.append)
        dc.update("light.x", [{"key": "on_off", "value": _v("bool", bool_value=True)}])
        dc.update("light.x", [{"key": "on_off", "value": _v("bool", bool_value=False)}])
        unsub()
        dc.update("light.x", [{"key": "on_off", "value": _v("bool", bool_value=True)}])
        assert len(received) == 1

    def test_subscriber_exception_does_not_break_collector(self) -> None:
        dc = DiffCollector()

        def bad(_d: StateDiff) -> None:
            raise RuntimeError("boom")

        dc.subscribe(bad)
        dc.update("light.x", [{"key": "on_off", "value": _v("bool", bool_value=True)}])
        # Update that would fire subscribers — must not raise.
        dc.update("light.x", [{"key": "on_off", "value": _v("bool", bool_value=False)}])


class TestRingBuffer:
    def test_maxlen_enforced(self) -> None:
        dc = DiffCollector(maxlen=3)
        for i in range(5):
            dc.update(
                f"light.{i}",
                [{"key": "on_off", "value": _v("bool", bool_value=True)}],
            )
            dc.update(
                f"light.{i}",
                [{"key": "on_off", "value": _v("bool", bool_value=False)}],
            )
        # Only 5 *real* diffs were generated (one per entity) and the
        # ring buffer must trim to 3.
        assert len(dc.snapshot()) == 3

    def test_resize_shrinks_keeping_newest(self) -> None:
        dc = DiffCollector(maxlen=10)
        for i in range(4):
            dc.update(
                "light.x",
                [{"key": "on_off", "value": _v("bool", bool_value=i % 2 == 0)}],
            )
        dc.resize(2)
        assert len(dc.snapshot()) == 2

    def test_clear_resets_everything(self) -> None:
        dc = DiffCollector()
        dc.update("light.x", [{"key": "on_off", "value": _v("bool", bool_value=True)}])
        dc.update("light.x", [{"key": "on_off", "value": _v("bool", bool_value=False)}])
        dc.clear()
        assert dc.snapshot() == []
        # Baseline must go with the clear — otherwise first next update
        # would be a phantom "changed" against the cleared history.
        assert dc.get_last_state("light.x") is None


class TestSerialization:
    def test_diff_as_dict_is_json_serializable(self) -> None:
        dc = DiffCollector()
        dc.update("light.x", [{"key": "on_off", "value": _v("bool", bool_value=True)}])
        dc.update("light.x", [{"key": "on_off", "value": _v("bool", bool_value=False)}])
        data = json.dumps(dc.snapshot())
        # Field names must stay stable — UI reads them directly.
        assert '"entity_id"' in data
        assert '"changed"' in data
        assert '"before"' in data
        assert '"after"' in data
