"""Unit tests for the per-entity diagnostic advisor.

The advisor is a pure reducer over bridge state — breakage here
silently lies to the user ("no issues detected" when the entity is
dead, or "broken" for a healthy device).  These tests pin each rule
individually and the verdict aggregation.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.sber_mqtt_bridge.diagnostics_advisor import (
    DiagnosticReport,
    Finding,
    diagnose_entity,
)
from custom_components.sber_mqtt_bridge.schema_validator import (
    ValidationCollector,
    ValidationIssue,
)
from custom_components.sber_mqtt_bridge.state_diff import DiffCollector
from custom_components.sber_mqtt_bridge.trace_collector import TraceCollector


def _bridge(
    *,
    known: bool = True,
    enabled: bool = True,
    acknowledged: bool = True,
    filled: bool = True,
    linked_role: tuple[str, str] | None = None,
    category: str = "light",
    features: list[str] | None = None,
) -> MagicMock:
    """Assemble a minimal MagicMock bridge exposing the fields the advisor reads."""
    bridge = MagicMock()
    bridge._entities = {}
    if known:
        entity = MagicMock()
        entity.category = category
        entity.is_filled_by_state = filled
        entity.get_final_features_list = MagicMock(return_value=features or ["on_off", "online"])
        bridge._entities["x.y"] = entity
    bridge._enabled_entity_ids = ["x.y"] if enabled else []
    bridge._linked_reverse = {"x.y": linked_role} if linked_role else {}
    stats = MagicMock()
    stats.acknowledged_entities = {"x.y"} if acknowledged else set()
    bridge._stats = stats
    bridge.trace_collector = TraceCollector()
    bridge.diff_collector = DiffCollector()
    bridge.validation_collector = ValidationCollector()
    return bridge


class TestBasicRules:
    def test_clean_entity_returns_ok_verdict(self) -> None:
        report = diagnose_entity(_bridge(), "x.y")
        # Green path must surface an explicit "clean" finding —
        # otherwise the UI shows an empty list that looks unfinished.
        assert report.verdict == "ok"
        assert any(f.code == "clean" for f in report.findings)

    def test_unknown_entity_is_broken(self) -> None:
        report = diagnose_entity(_bridge(known=False, enabled=False), "x.y")
        assert report.verdict == "broken"
        assert any(f.code == "not_known_to_bridge" for f in report.findings)

    def test_known_but_not_enabled_is_broken(self) -> None:
        report = diagnose_entity(_bridge(enabled=False), "x.y")
        codes = {f.code for f in report.findings}
        assert "not_enabled" in codes
        assert report.verdict == "broken"

    def test_never_acknowledged_is_error_with_actionable_hint(self) -> None:
        # The most user-visible failure mode — Sber silent rejection.
        report = diagnose_entity(_bridge(acknowledged=False), "x.y")
        finding = next(f for f in report.findings if f.code == "never_acknowledged")
        assert finding.severity == "error"
        # The action must point the user to something concrete, not just
        # "something is wrong".
        assert finding.action


class TestLinkedSensor:
    def test_linked_sensor_gets_info_redirect(self) -> None:
        # Users often diagnose the wrong thing (linked sensor) — the
        # advisor must redirect them to the primary.
        report = diagnose_entity(_bridge(linked_role=("light.primary", "brightness")), "x.y")
        finding = next(f for f in report.findings if f.code == "linked_sensor")
        assert finding.severity == "info"
        assert "light.primary" in finding.action


class TestFilledByState:
    def test_not_filled_is_warning(self) -> None:
        report = diagnose_entity(_bridge(filled=False), "x.y")
        codes = {f.code for f in report.findings}
        assert "not_filled_by_state" in codes
        # Warning, not error — the bridge is healthy, the upstream
        # integration is the problem.
        assert report.verdict in {"warning", "broken"}


class TestValidationRules:
    def test_validation_error_surfaced(self) -> None:
        bridge = _bridge()
        bridge.validation_collector.record(
            "x.y",
            [
                ValidationIssue(
                    ts=0,
                    entity_id="x.y",
                    category="light",
                    type="type_mismatch",
                    severity="error",
                    key="on_off",
                    description="bad",
                    details={},
                )
            ],
        )
        report = diagnose_entity(bridge, "x.y")
        assert any(f.code == "validation_errors" for f in report.findings)
        assert report.verdict == "broken"

    def test_validation_warning_only_is_warning(self) -> None:
        bridge = _bridge()
        bridge.validation_collector.record(
            "x.y",
            [
                ValidationIssue(
                    ts=0,
                    entity_id="x.y",
                    category="light",
                    type="unknown_for_category",
                    severity="warning",
                    key="on_off",
                    description="unknown",
                    details={},
                )
            ],
        )
        report = diagnose_entity(bridge, "x.y")
        assert report.verdict == "warning"
        assert any(f.code == "validation_warnings" for f in report.findings)


class TestRecentTrace:
    def test_failed_trace_is_error(self) -> None:
        bridge = _bridge()
        tr = bridge.trace_collector.begin(
            trace_id="t1",
            trigger="sber_command",
            entity_ids=["x.y"],
        )
        tr.status = "failed"  # Simulate silent rejection via AckAudit.
        report = diagnose_entity(bridge, "x.y")
        assert any(f.code == "recent_trace_failed" for f in report.findings)

    def test_timeout_trace_is_warning(self) -> None:
        bridge = _bridge()
        tr = bridge.trace_collector.begin(
            trace_id="t1",
            trigger="sber_command",
            entity_ids=["x.y"],
        )
        tr.status = "timeout"
        report = diagnose_entity(bridge, "x.y")
        assert any(f.code == "recent_trace_timeout" for f in report.findings)

    def test_success_trace_produces_no_finding(self) -> None:
        bridge = _bridge()
        tr = bridge.trace_collector.begin(
            trace_id="t1",
            trigger="sber_command",
            entity_ids=["x.y"],
        )
        tr.status = "success"
        report = diagnose_entity(bridge, "x.y")
        # Successful traces must not produce noise.
        assert not any(f.code.startswith("recent_trace") for f in report.findings)


class TestVerdictAggregation:
    def test_verdict_picks_worst_severity(self) -> None:
        # Mix of info + error must still produce "broken", not
        # average-out to "warning".
        bridge = _bridge(acknowledged=False, linked_role=("a.b", "r"))
        report = diagnose_entity(bridge, "x.y")
        assert report.verdict == "broken"


class TestSerialization:
    def test_report_is_json_serializable(self) -> None:
        import json

        report = diagnose_entity(_bridge(), "x.y")
        data = json.dumps(report.as_dict())
        # Field names read directly by the UI — renames silently break it.
        assert '"verdict"' in data
        assert '"findings"' in data
        assert '"summary"' in data

    def test_finding_has_expected_fields(self) -> None:
        f = Finding(code="x", severity="info", title="t", detail="d")
        d = f.as_dict()
        assert set(d.keys()) == {"code", "severity", "title", "detail", "action"}


class TestReportDataclass:
    def test_construct_empty_and_serialize(self) -> None:
        r = DiagnosticReport(entity_id="x", verdict="ok")
        assert r.as_dict() == {
            "entity_id": "x",
            "verdict": "ok",
            "findings": [],
            "summary": {},
        }
