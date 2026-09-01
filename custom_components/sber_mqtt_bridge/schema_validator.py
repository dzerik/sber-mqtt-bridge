"""Sber state payload schema validator for DevTools.

Validates every outgoing state publish against the auto-generated Sber
spec (see ``_generated/``) and surfaces four kinds of issue:

* **missing_obligatory** — a feature listed in
  :data:`CATEGORY_OBLIGATORY_FEATURES` is missing from the device model,
  or absent from the payload while being able to carry a quiet value.
  Sber silently drops such a device.  Event-only features
  (:data:`EVENT_ONLY_FEATURES`) are exempt from the payload half: they
  have no value for "nothing happened", so silence *is* the quiet state.
* **missing_conditional** — the device declares none of an
  "at least one of" group (:data:`CATEGORY_CONDITIONAL_FEATURES`): a
  gate with no way to open, an air sensor measuring nothing.  Just as
  fatal as the above, and checked against the *declared features*
  rather than the states — command-only members such as ``open_set``
  never appear in a publish.
* **unknown_enum_value** — an ENUM value outside the vocabulary the
  function's own page documents (``source: "HDMI 1"`` where Sber knows
  only ``hdmi1``).  The cloud cannot route a value it does not know.
* **out_of_range** — a numeric value outside the function's documented
  bounds.  A warning, not an error: the bound describes the function,
  and a device idling below it (a socket at 0 W against a 10 W floor)
  is common enough that an error would be noise.
* **unknown_for_category** — a feature key that isn't in the Sber
  reference set for this category.  Often tolerated today but an
  easy future breakage.
* **type_mismatch** — the payload's ``value.type`` does not match
  :data:`FEATURE_TYPES` for that key (e.g. sending ``INTEGER`` where
  the spec declares ``BOOL``).  Reliable way to get silently rejected.
* **not_declared** — the state's key isn't in the device's own
  ``features`` list as published in the config, so Sber will refuse
  to route the value.

Each issue carries ``severity`` (``error`` / ``warning`` / ``info``),
the ``entity_id`` and ``key``, and a short human-readable
``description`` for DevTools to render.

The collector keeps two views:

* ``recent_issues`` — ring buffer of every issue emitted, newest
  first, used for chronological scanning.
* ``by_entity`` — latest-only per (entity_id, key, type) tuple, so
  the UI can render a "current health of each entity" table.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from typing import Any, Literal

from ._generated.category_features import CATEGORY_REFERENCE_FEATURES
from ._generated.conditional_features import CATEGORY_CONDITIONAL_FEATURES
from ._generated.feature_types import FEATURE_TYPES
from ._generated.obligatory_features import CATEGORY_OBLIGATORY_FEATURES
from ._generated.reference_values import FEATURE_ENUM_VALUES, FEATURE_RANGES

_LOGGER = logging.getLogger(__name__)

EVENT_ONLY_FEATURES: frozenset[str] = frozenset(
    name for name, values in FEATURE_ENUM_VALUES.items() if len(values) == 1
)
"""Features that can only ever report that something *happened*.

Derived, not hand-listed: a documented vocabulary of exactly one value
leaves no way to say "not happening", so silence is the quiet state.
``pir`` is the case that matters — Sber's own page says it is "отправляется,
когда обнаружено движение" — and requiring it in every publish reported
every idle motion sensor as broken (issue #61) while the cloud was
perfectly happy with them."""

IssueType = Literal[
    "missing_obligatory",
    "missing_conditional",
    "unknown_enum_value",
    "out_of_range",
    "unknown_for_category",
    "type_mismatch",
    "not_declared",
]
Severity = Literal["error", "warning", "info"]

_SEVERITY: dict[IssueType, Severity] = {
    "missing_obligatory": "error",
    "missing_conditional": "error",
    "unknown_enum_value": "error",
    "out_of_range": "warning",
    "unknown_for_category": "warning",
    "type_mismatch": "error",
    "not_declared": "info",
}


@dataclass(frozen=True)
class ValidationIssue:
    """One validation problem found in a publish."""

    ts: float
    entity_id: str
    category: str
    type: IssueType
    severity: Severity
    key: str | None
    description: str
    details: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""
        return asdict(self)


def _value_type(value: Any) -> str | None:
    """Extract the declared ``type`` field from a Sber value dict."""
    if isinstance(value, dict):
        t = value.get("type")
        if isinstance(t, str):
            return t
    return None


def _numeric_payload(value: Any) -> float | None:
    """Extract the number from an INTEGER / FLOAT value dict.

    Sber sends integers as *strings* (``{"integer_value": "42"}``), so
    this deliberately accepts both, and returns ``None`` for anything it
    cannot read as a number — an unreadable value is the ``type_mismatch``
    check's business, not this one's.

    Args:
        value: Sber value dict.

    Returns:
        The number, or ``None`` when there is nothing numeric to read.
    """
    if not isinstance(value, dict):
        return None
    for key in ("integer_value", "float_value"):
        if key in value:
            try:
                return float(value[key])
            except (TypeError, ValueError):
                return None
    return None


def validate_publish(
    *,
    entity_id: str,
    category: str | None,
    states: Iterable[dict[str, Any]],
    declared_features: Iterable[str] | None = None,
) -> list[ValidationIssue]:
    """Classify every issue in one device's publish snapshot.

    Args:
        entity_id: HA entity id / Sber device id.
        category: Sber category (e.g. ``"light"``, ``"hvac_ac"``).
            Unknown categories short-circuit all spec-based checks
            (we can't validate what we don't know) — those entities
            only get the ``not_declared`` check.
        states: The ``states`` list from the Sber payload, each
            ``{"key": str, "value": {"type": ..., ...}}``.
        declared_features: Feature names advertised by the device in
            its config publish.  ``None`` skips the ``not_declared``
            check (useful when the caller genuinely doesn't have the
            info, e.g. synthetic payload).

    Returns:
        List of :class:`ValidationIssue`.  Empty list == clean publish.
    """
    now = time.time()
    issues: list[ValidationIssue] = []
    states_list = list(states)
    state_keys = {s.get("key") for s in states_list if s.get("key")}

    ref = CATEGORY_REFERENCE_FEATURES.get(category) if category else None
    declared_set = set(declared_features) if declared_features is not None else None

    # --- missing obligatory -------------------------------------------------
    # Sber's ✔︎ means "describe this feature in the device model", which is
    # not the same as "send it in every state publish".  An event-only
    # feature has no value for the quiet case, so its absence from a
    # payload is how the device says "nothing happened" — demanding it
    # every time flagged every idle motion sensor (issue #61).
    for must in sorted(CATEGORY_OBLIGATORY_FEATURES.get(category or "", ())):
        undeclared = declared_set is not None and must not in declared_set
        if undeclared:
            description = (
                f"Obligatory feature '{must}' for category '{category}' is "
                "missing from the device model. Sber will drop this device."
            )
        elif must not in state_keys and must not in EVENT_ONLY_FEATURES:
            description = (
                f"Obligatory feature '{must}' for category '{category}' is "
                "absent from the publish. Sber will drop this device."
            )
        else:
            continue
        issues.append(
            ValidationIssue(
                ts=now,
                entity_id=entity_id,
                category=category or "",
                type="missing_obligatory",
                severity=_SEVERITY["missing_obligatory"],
                key=must,
                description=description,
                details={"missing": must},
            )
        )

    # --- missing conditional group -----------------------------------------
    # Deliberately keyed on the declared features, never on the states: a
    # group member may be command-only (``open_set`` "не хранит состояние
    # устройства"), so an impulse gate that satisfies the rule perfectly
    # publishes none of the group.  Checking the payload would flag every
    # such device.  With no declared features to inspect we stay silent
    # rather than guess.
    conditional = CATEGORY_CONDITIONAL_FEATURES.get(category) if category else None
    if conditional and declared_set is not None and not (conditional & declared_set):
        group = ", ".join(sorted(conditional))
        issues.append(
            ValidationIssue(
                ts=now,
                entity_id=entity_id,
                category=category or "",
                type="missing_conditional",
                severity=_SEVERITY["missing_conditional"],
                key=None,
                description=(
                    f"Category '{category}' requires at least one of: {group}. "
                    "The device declares none of them, so Sber will drop it."
                ),
                details={"expected_any_of": sorted(conditional)},
            )
        )

    for s in states_list:
        key = s.get("key")
        if not key:
            continue
        val = s.get("value")
        actual_type = _value_type(val)

        # --- type mismatch -------------------------------------------------
        expected = FEATURE_TYPES.get(key)
        if expected is not None and actual_type and actual_type != expected:
            issues.append(
                ValidationIssue(
                    ts=now,
                    entity_id=entity_id,
                    category=category or "",
                    type="type_mismatch",
                    severity=_SEVERITY["type_mismatch"],
                    key=key,
                    description=(f"Feature '{key}' sent as {actual_type}, spec requires {expected}."),
                    details={"expected": expected, "actual": actual_type},
                )
            )

        # --- value outside the feature's documented vocabulary -------------
        vocabulary = FEATURE_ENUM_VALUES.get(key)
        if vocabulary and actual_type == "ENUM":
            sent = val.get("enum_value") if isinstance(val, dict) else None
            if isinstance(sent, str) and sent not in vocabulary:
                issues.append(
                    ValidationIssue(
                        ts=now,
                        entity_id=entity_id,
                        category=category or "",
                        type="unknown_enum_value",
                        severity=_SEVERITY["unknown_enum_value"],
                        key=key,
                        description=(
                            f"Feature '{key}' sent value '{sent}', which is not "
                            "one of the values Sber documents for it. The cloud "
                            "cannot route a value it does not know."
                        ),
                        details={"sent": sent, "allowed": sorted(vocabulary)},
                    )
                )

        # --- numeric value outside the documented range --------------------
        bounds = FEATURE_RANGES.get(key)
        number = _numeric_payload(val) if bounds else None
        if bounds is not None and number is not None and not (bounds[0] <= number <= bounds[1]):
            issues.append(
                ValidationIssue(
                    ts=now,
                    entity_id=entity_id,
                    category=category or "",
                    type="out_of_range",
                    severity=_SEVERITY["out_of_range"],
                    key=key,
                    description=(
                        f"Feature '{key}' sent {number:g}, outside the documented "
                        f"range {bounds[0]:g}…{bounds[1]:g}. Sber may clip or drop it."
                    ),
                    details={"sent": number, "min": bounds[0], "max": bounds[1]},
                )
            )

        # --- unknown for category -----------------------------------------
        if ref is not None and key not in ref:
            issues.append(
                ValidationIssue(
                    ts=now,
                    entity_id=entity_id,
                    category=category or "",
                    type="unknown_for_category",
                    severity=_SEVERITY["unknown_for_category"],
                    key=key,
                    description=(f"Feature '{key}' is not in Sber's reference set for category '{category}'."),
                    details={},
                )
            )

        # --- not in declared features -------------------------------------
        if declared_set is not None and key not in declared_set:
            issues.append(
                ValidationIssue(
                    ts=now,
                    entity_id=entity_id,
                    category=category or "",
                    type="not_declared",
                    severity=_SEVERITY["not_declared"],
                    key=key,
                    description=(
                        f"Feature '{key}' is published but not advertised in the device's config features list."
                    ),
                    details={},
                )
            )

    return issues


class ValidationCollector:
    """Stores recent validation issues with live subscribe fan-out.

    Keeps two complementary views: a chronological ring buffer
    (``recent_issues``) and a per-entity latest-snapshot
    (``issues_by_entity``) so the UI can answer both "what was the
    last problem" and "which entities are currently broken".
    """

    def __init__(self, maxlen: int = 500) -> None:
        """Initialize a collector with the given ring-buffer capacity."""
        self._recent: deque[ValidationIssue] = deque(maxlen=maxlen)
        self._by_entity: dict[str, list[ValidationIssue]] = {}
        self._subscribers: set[Callable[[list[ValidationIssue]], None]] = set()

    @property
    def maxlen(self) -> int | None:
        """Return ring-buffer capacity."""
        return self._recent.maxlen

    def resize(self, new_maxlen: int) -> None:
        """Resize the ring buffer keeping the newest entries."""
        if new_maxlen == self._recent.maxlen:
            return
        old = list(self._recent)
        self._recent = deque(old[-new_maxlen:], maxlen=new_maxlen)

    def snapshot(self) -> dict[str, Any]:
        """Return a JSON-serializable snapshot of both views."""
        return {
            "recent": [i.as_dict() for i in self._recent],
            "by_entity": {eid: [i.as_dict() for i in issues] for eid, issues in self._by_entity.items()},
        }

    def clear(self) -> None:
        """Drop all stored issues."""
        self._recent.clear()
        self._by_entity.clear()

    def record(self, entity_id: str, issues: list[ValidationIssue]) -> None:
        """Persist the set of issues for ``entity_id`` after a publish.

        A publish that fixes an entity's last error must overwrite the
        per-entity snapshot so DevTools flips it from red to clean;
        that's why we replace (not append) the per-entity list.
        """
        # Per-entity view — always overwrite; an empty list signals
        # "entity is clean now", otherwise DevTools can never show the
        # fix propagating.
        self._by_entity[entity_id] = list(issues)
        for i in issues:
            self._recent.append(i)
        if issues:
            self._notify(issues)

    def subscribe(self, callback_fn: Callable[[list[ValidationIssue]], None]) -> Callable[[], None]:
        """Subscribe to validation bursts (one call per publish with issues)."""
        self._subscribers.add(callback_fn)

        def unsub() -> None:
            self._subscribers.discard(callback_fn)

        return unsub

    def _notify(self, issues: list[ValidationIssue]) -> None:
        for cb in list(self._subscribers):
            try:
                cb(issues)
            except (RuntimeError, ValueError, TypeError, AttributeError):
                _LOGGER.exception("ValidationCollector subscriber raised")

    def record_publish_payload(
        self,
        payload: str | dict[str, Any],
        *,
        categories: dict[str, str] | None = None,
        declared_features: dict[str, Iterable[str]] | None = None,
    ) -> dict[str, list[ValidationIssue]]:
        """Parse a full Sber publish payload and record per-device issues.

        Args:
            payload: JSON string or already-parsed dict.
            categories: Optional mapping ``entity_id → sber_category``.
                Entities without a known category skip spec checks.
            declared_features: Optional mapping ``entity_id → features``
                (as published in the config).  Enables the
                ``not_declared`` check.

        Returns:
            ``entity_id → [issues]`` — empty list for clean devices.
            Malformed input returns an empty dict without raising.
        """
        if isinstance(payload, str):
            try:
                import json

                data = json.loads(payload)
            except (ValueError, TypeError):
                return {}
        else:
            data = payload
        devices = data.get("devices") if isinstance(data, dict) else None
        if not isinstance(devices, dict):
            return {}

        result: dict[str, list[ValidationIssue]] = {}
        categories = categories or {}
        declared_features = declared_features or {}
        for eid, body in devices.items():
            if not isinstance(body, dict):
                continue
            states = body.get("states")
            if not isinstance(states, list):
                continue
            issues = validate_publish(
                entity_id=eid,
                category=categories.get(eid),
                states=states,
                declared_features=declared_features.get(eid),
            )
            self.record(eid, issues)
            result[eid] = issues
        return result
