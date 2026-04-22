"""Per-entity "why isn't it working?" diagnostic advisor.

Gathers every signal the bridge already exposes about one entity —
whether it's loaded, linked, enabled, acknowledged, validated, plus
the latest trace and state-diff records — and runs a cheap rule-based
check that turns the raw data into an actionable verdict for the
DevTools panel.

Design:
    * Pure function of ``bridge`` state — no timers, no side effects.
    * Every rule returns a :class:`Finding` with ``severity`` so the
      UI can colour-code; the report ``verdict`` is the worst severity
      present (``broken`` > ``warning`` > ``ok``).
    * The rules are deliberately independent one-liners: adding a
      new heuristic is one function, no orchestrator changes.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from .sber_bridge import SberBridge

Severity = Literal["error", "warning", "info", "ok"]
Verdict = Literal["ok", "warning", "broken"]


@dataclass(frozen=True)
class Finding:
    """One observation produced by a diagnostic rule."""

    code: str
    severity: Severity
    title: str
    detail: str
    action: str = ""

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""
        return asdict(self)


@dataclass
class DiagnosticReport:
    """Aggregated per-entity diagnostic."""

    entity_id: str
    verdict: Verdict
    findings: list[Finding] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""
        return {
            "entity_id": self.entity_id,
            "verdict": self.verdict,
            "findings": [f.as_dict() for f in self.findings],
            "summary": self.summary,
        }


def _verdict_for(severities: list[Severity]) -> Verdict:
    """Reduce a list of severities into a single trace-level verdict."""
    if "error" in severities:
        return "broken"
    if "warning" in severities:
        return "warning"
    return "ok"


def _collect_summary(bridge: SberBridge, entity_id: str) -> dict[str, Any]:
    """Gather raw state about the entity for the UI to render as-is."""
    entity = bridge._entities.get(entity_id)
    enabled = entity_id in bridge._enabled_entity_ids
    linked_role = bridge._linked_reverse.get(entity_id)
    acknowledged = entity_id in bridge._stats.acknowledged_entities

    # Latest trace that touched this entity (may be active or closed).
    last_trace = None
    for t in reversed(bridge.trace_collector.snapshot()):
        if entity_id in (t.get("entity_ids") or []):
            last_trace = t
            break

    # Latest state diff and validation issues.
    last_diff = None
    for d in reversed(bridge.diff_collector.snapshot()):
        if d.get("entity_id") == entity_id:
            last_diff = d
            break

    validation_by_entity = bridge.validation_collector.snapshot().get("by_entity", {})
    current_issues = validation_by_entity.get(entity_id, [])

    return {
        "known_to_bridge": entity is not None,
        "category": getattr(entity, "category", None),
        "enabled": enabled,
        "linked_role": ({"primary_entity_id": linked_role[0], "role": linked_role[1]} if linked_role else None),
        "acknowledged_by_sber": acknowledged,
        "is_filled_by_state": getattr(entity, "is_filled_by_state", None),
        "declared_features": (entity.get_final_features_list() if entity is not None else None),
        "last_trace": last_trace,
        "last_diff": last_diff,
        "current_validation_issues": current_issues,
    }


def _rule_not_known(summary: dict[str, Any]) -> Finding | None:
    if summary["known_to_bridge"]:
        return None
    return Finding(
        code="not_known_to_bridge",
        severity="error",
        title="Bridge does not know this entity",
        detail=(
            "The entity_id is not loaded in the bridge.  It was either "
            "never added, was removed, or the integration didn't reload "
            "after a config change."
        ),
        action=("Open the devices wizard and add the entity, or reload the Sber MQTT Bridge integration."),
    )


def _rule_not_enabled(summary: dict[str, Any]) -> Finding | None:
    if not summary["known_to_bridge"]:
        return None  # Covered by _rule_not_known.
    if summary["enabled"]:
        return None
    return Finding(
        code="not_enabled",
        severity="error",
        title="Entity is known but not enabled",
        detail="Bridge sees the entity but will not publish it to Sber.",
        action="Enable it in the devices wizard.",
    )


def _rule_linked(summary: dict[str, Any]) -> Finding | None:
    role = summary["linked_role"]
    if not role:
        return None
    return Finding(
        code="linked_sensor",
        severity="info",
        title="This is a linked sensor",
        detail=(
            f"State changes are forwarded to primary device "
            f"'{role['primary_entity_id']}' under role '{role['role']}'. "
            "Diagnose the primary if the user-facing behaviour is broken."
        ),
        action=f"Run diagnose on {role['primary_entity_id']} instead.",
    )


def _rule_not_filled(summary: dict[str, Any]) -> Finding | None:
    if not summary["known_to_bridge"]:
        return None
    if summary["is_filled_by_state"] is False:
        return Finding(
            code="not_filled_by_state",
            severity="warning",
            title="HA state has not populated the entity yet",
            detail=(
                "The bridge has no state snapshot for this entity — "
                "likely HA returned `unavailable` or the entity hasn't "
                "emitted a state_changed event since startup."
            ),
            action=(
                "Trigger the device once from HA so a state_changed "
                "event fires, or check that the underlying integration "
                "is healthy."
            ),
        )
    return None


def _rule_never_acknowledged(summary: dict[str, Any]) -> Finding | None:
    if not summary["enabled"]:
        return None
    if summary["acknowledged_by_sber"]:
        return None
    return Finding(
        code="never_acknowledged",
        severity="error",
        title="Sber has never acknowledged this device",
        detail=(
            "The bridge has published this entity's config at least "
            "once, but Sber has not issued a status_request or command "
            "for it.  Common causes: category mismatch (Sber silently "
            "drops unknown categories), obligatory feature missing, "
            "device not registered in Sber Studio."
        ),
        action=(
            "Check the Schema Validation tab for this entity; if clean, "
            "confirm the device exists in Sber Studio and republish."
        ),
    )


def _rule_validation_errors(summary: dict[str, Any]) -> Finding | None:
    errors = [i for i in summary["current_validation_issues"] if i.get("severity") == "error"]
    if not errors:
        return None
    keys = ", ".join(sorted({i.get("key") or "?" for i in errors}))
    return Finding(
        code="validation_errors",
        severity="error",
        title=f"{len(errors)} schema validation error(s)",
        detail=(f"The latest publish failed validation on: {keys}.  Sber is likely silently rejecting the payload."),
        action="Open the Schema Validation tab for the full list.",
    )


def _rule_validation_warnings(summary: dict[str, Any]) -> Finding | None:
    warnings = [i for i in summary["current_validation_issues"] if i.get("severity") == "warning"]
    if not warnings:
        return None
    return Finding(
        code="validation_warnings",
        severity="warning",
        title=f"{len(warnings)} schema validation warning(s)",
        detail=("Payload may still work today but is drifting from the Sber spec — easy future breakage."),
        action="Review in the Schema Validation tab.",
    )


def _rule_recent_trace(summary: dict[str, Any]) -> Finding | None:
    t = summary["last_trace"]
    if not t:
        return None
    status = t.get("status")
    if status == "failed":
        return Finding(
            code="recent_trace_failed",
            severity="error",
            title="Last command trace ended in failure",
            detail=(
                "The most recent Sber command involving this entity "
                "did not receive an acknowledgment (silent rejection)."
            ),
            action="Check the Correlation Timeline for the failed trace.",
        )
    if status == "timeout":
        return Finding(
            code="recent_trace_timeout",
            severity="warning",
            title="Last trace timed out without a publish",
            detail=(
                "The bridge saw a Sber command but never emitted a "
                "corresponding publish within the trace window — "
                "possibly a HA service call that did nothing."
            ),
            action="Check the Correlation Timeline + HA logs for service errors.",
        )
    return None


_RULES = (
    _rule_not_known,
    _rule_not_enabled,
    _rule_linked,
    _rule_not_filled,
    _rule_never_acknowledged,
    _rule_validation_errors,
    _rule_validation_warnings,
    _rule_recent_trace,
)


def diagnose_entity(bridge: SberBridge, entity_id: str) -> DiagnosticReport:
    """Run every diagnostic rule against ``entity_id`` and produce a report."""
    summary = _collect_summary(bridge, entity_id)
    findings: list[Finding] = []
    for rule in _RULES:
        f = rule(summary)
        if f is not None:
            findings.append(f)

    verdict = _verdict_for([f.severity for f in findings])
    if verdict == "ok" and not findings:
        # Signal the "all clear" state explicitly so the UI shows the
        # green verdict rather than an empty list that looks unfinished.
        findings.append(
            Finding(
                code="clean",
                severity="ok",
                title="No issues detected",
                detail=(
                    "The entity is loaded, enabled, acknowledged by Sber, "
                    "and the latest publish passes schema validation."
                ),
            )
        )
    return DiagnosticReport(
        entity_id=entity_id,
        verdict=verdict,
        findings=findings,
        summary=summary,
    )
