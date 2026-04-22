"""Unit tests for the Sber schema validator.

The validator is the canonical source of truth for "will Sber accept
this publish?" — a false negative (issue not flagged) costs a user
hours tracking down a silent rejection; a false positive drowns the
DevTools panel in noise and trains users to ignore it.  Tests pin
each check individually and the three collector views
(``record`` / ``snapshot`` / ``subscribe``).
"""

from __future__ import annotations

import json

from custom_components.sber_mqtt_bridge.schema_validator import (
    ValidationCollector,
    ValidationIssue,
    validate_publish,
)


def _state(key: str, type_: str, **body) -> dict:
    return {"key": key, "value": {"type": type_, **body}}


class TestMissingObligatory:
    def test_all_obligatory_present_no_issue_of_that_type(self) -> None:
        issues = validate_publish(
            entity_id="light.x",
            category="hub",
            states=[_state("online", "BOOL", bool_value=True)],
        )
        assert not any(i.type == "missing_obligatory" for i in issues)

    def test_missing_obligatory_is_error(self) -> None:
        # hvac_ac requires hvac_temp_set + on_off + online per the spec.
        issues = validate_publish(
            entity_id="climate.a",
            category="hvac_ac",
            states=[_state("on_off", "BOOL", bool_value=True)],
        )
        missing = {i.key for i in issues if i.type == "missing_obligatory"}
        # Missing any of these is a hard rejection by Sber — must be error severity.
        assert {"hvac_temp_set", "online"}.issubset(missing)
        assert all(i.severity == "error" for i in issues if i.type == "missing_obligatory")

    def test_unknown_category_skips_obligatory_check(self) -> None:
        # Can't validate what we don't know — unknown category is a
        # frequent case during codegen drift and must not spam issues.
        issues = validate_publish(
            entity_id="x.y",
            category="future_category",
            states=[_state("online", "BOOL", bool_value=True)],
        )
        assert not any(i.type == "missing_obligatory" for i in issues)


class TestTypeMismatch:
    def test_wrong_value_type_flagged_as_error(self) -> None:
        # hvac_work_mode is ENUM; sending STRING is the textbook silent
        # rejection path — the validator must flag it.
        issues = validate_publish(
            entity_id="climate.a",
            category="hvac_ac",
            states=[_state("hvac_work_mode", "STRING", string_value="cooling")],
        )
        mismatches = [i for i in issues if i.type == "type_mismatch"]
        assert mismatches
        assert mismatches[0].severity == "error"
        assert mismatches[0].details == {"expected": "ENUM", "actual": "STRING"}

    def test_correct_type_no_mismatch(self) -> None:
        issues = validate_publish(
            entity_id="light.x",
            category="light",
            states=[_state("on_off", "BOOL", bool_value=True)],
        )
        assert not any(i.type == "type_mismatch" for i in issues)

    def test_unknown_feature_key_is_not_a_type_mismatch(self) -> None:
        # Unknown keys go through the "unknown_for_category" channel,
        # not as type mismatches — otherwise a typo produces two issues
        # per payload instead of one actionable one.
        issues = validate_publish(
            entity_id="light.x",
            category="light",
            states=[_state("ghost_feature", "INTEGER", integer_value=1)],
        )
        assert not any(i.type == "type_mismatch" for i in issues)


class TestUnknownForCategory:
    def test_feature_outside_reference_set_is_warning(self) -> None:
        # hub has a small reference set — "on_off" is not in it.
        issues = validate_publish(
            entity_id="hub.x",
            category="hub",
            states=[_state("on_off", "BOOL", bool_value=True)],
        )
        unknowns = [i for i in issues if i.type == "unknown_for_category"]
        assert unknowns
        assert unknowns[0].severity == "warning"

    def test_known_feature_no_warning(self) -> None:
        issues = validate_publish(
            entity_id="light.x",
            category="light",
            states=[_state("on_off", "BOOL", bool_value=True)],
        )
        assert not any(i.type == "unknown_for_category" for i in issues)


class TestNotDeclared:
    def test_state_key_outside_declared_is_info(self) -> None:
        # User's device advertises only "online" but tries to publish
        # "on_off" — Sber will ignore the latter.
        issues = validate_publish(
            entity_id="light.x",
            category="light",
            states=[_state("on_off", "BOOL", bool_value=True)],
            declared_features=["online"],
        )
        nots = [i for i in issues if i.type == "not_declared"]
        assert nots
        # Info, not error — the publish may still land (e.g. during
        # feature rollout races) but the user should know.
        assert nots[0].severity == "info"

    def test_declared_keys_no_warning(self) -> None:
        issues = validate_publish(
            entity_id="light.x",
            category="light",
            states=[_state("on_off", "BOOL", bool_value=True)],
            declared_features=["on_off", "online"],
        )
        assert not any(i.type == "not_declared" for i in issues)

    def test_declared_features_none_skips_check(self) -> None:
        # Replay / synthetic payload may not have declared features —
        # the check simply doesn't run instead of raising.
        issues = validate_publish(
            entity_id="light.x",
            category="light",
            states=[_state("on_off", "BOOL", bool_value=True)],
            declared_features=None,
        )
        assert not any(i.type == "not_declared" for i in issues)


class TestCollector:
    def test_record_replaces_per_entity_view(self) -> None:
        vc = ValidationCollector()
        # First publish — 1 issue; second publish — 0 issues.  UI must
        # observe the entity going clean via the per-entity view.
        issues = validate_publish(
            entity_id="climate.a",
            category="hvac_ac",
            states=[_state("on_off", "BOOL", bool_value=True)],
        )
        vc.record("climate.a", issues)
        vc.record("climate.a", [])
        snap = vc.snapshot()
        assert snap["by_entity"]["climate.a"] == []

    def test_recent_accumulates_across_publishes(self) -> None:
        # Even after the entity snapshot goes clean, the chronological
        # record must keep the historical issue so users can scroll back.
        vc = ValidationCollector()
        issues = validate_publish(
            entity_id="climate.a",
            category="hvac_ac",
            states=[_state("on_off", "BOOL", bool_value=True)],
        )
        vc.record("climate.a", issues)
        vc.record("climate.a", [])
        assert len(vc.snapshot()["recent"]) == len(issues)

    def test_subscribers_called_only_for_non_empty_batches(self) -> None:
        vc = ValidationCollector()
        received: list[list[ValidationIssue]] = []
        vc.subscribe(received.append)
        vc.record("light.x", [])
        assert received == []
        issue = ValidationIssue(
            ts=0,
            entity_id="light.x",
            category="light",
            type="unknown_for_category",
            severity="warning",
            key="xxx",
            description="test",
            details={},
        )
        vc.record("light.x", [issue])
        assert len(received) == 1

    def test_subscriber_exception_does_not_break_collector(self) -> None:
        vc = ValidationCollector()

        def bad(_i):
            raise RuntimeError("boom")

        vc.subscribe(bad)
        issue = ValidationIssue(
            ts=0,
            entity_id="x",
            category="",
            type="unknown_for_category",
            severity="warning",
            key="k",
            description="t",
            details={},
        )
        # Must not raise — bad subscriber must not take the bridge down.
        vc.record("x", [issue])

    def test_clear_drops_both_views(self) -> None:
        vc = ValidationCollector()
        issue = ValidationIssue(
            ts=0,
            entity_id="x",
            category="",
            type="unknown_for_category",
            severity="warning",
            key="k",
            description="t",
            details={},
        )
        vc.record("x", [issue])
        vc.clear()
        snap = vc.snapshot()
        assert snap == {"recent": [], "by_entity": {}}


class TestRecordPublishPayload:
    def test_parses_and_records_per_device(self) -> None:
        vc = ValidationCollector()
        payload = json.dumps(
            {
                "devices": {
                    "climate.a": {
                        "states": [_state("on_off", "BOOL", bool_value=True)],
                    },
                    "light.x": {
                        "states": [
                            _state("on_off", "BOOL", bool_value=True),
                            _state("online", "BOOL", bool_value=True),
                        ],
                    },
                }
            }
        )
        result = vc.record_publish_payload(
            payload,
            categories={"climate.a": "hvac_ac", "light.x": "light"},
        )
        # climate.a has missing obligatory fields; light.x is fine.
        assert result["climate.a"]
        assert result["light.x"] == []

    def test_missing_category_map_still_runs_with_unknown(self) -> None:
        vc = ValidationCollector()
        # No category map at all — we still want SOME validation
        # (type_mismatch) rather than bail out entirely.
        payload = {
            "devices": {
                "x": {"states": [_state("on_off", "INTEGER", integer_value=1)]},
            }
        }
        result = vc.record_publish_payload(payload)
        # on_off is BOOL in the spec regardless of category → type_mismatch fires.
        assert any(i.type == "type_mismatch" for i in result["x"])

    def test_invalid_payload_returns_empty_dict(self) -> None:
        vc = ValidationCollector()
        assert vc.record_publish_payload("not json") == {}
        assert vc.record_publish_payload({"devices": "nope"}) == {}  # type: ignore[arg-type]


class TestSerialization:
    def test_snapshot_is_json_serializable(self) -> None:
        vc = ValidationCollector()
        issues = validate_publish(
            entity_id="climate.a",
            category="hvac_ac",
            states=[_state("on_off", "BOOL", bool_value=True)],
        )
        vc.record("climate.a", issues)
        data = json.dumps(vc.snapshot())
        # Fields read directly by the UI — renames silently break it.
        assert '"severity"' in data
        assert '"type"' in data
        assert '"description"' in data
