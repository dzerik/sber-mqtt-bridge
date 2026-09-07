"""Sber payload schema validator for DevTools.

Validates every outgoing publish against the auto-generated Sber spec
(see ``_generated/``).  Two payload shapes reach it, and the ``scope``
argument of :func:`validate_publish` says which one:

* ``"state"`` — a status publish (``up/status``), where ``devices`` is a
  **dict** of ``{"states": [...]}`` blocks.  Every check below applies.
* ``"model"`` — a config publish (``up/config``), where ``devices`` is a
  **list** of device descriptors carrying ``model.category`` and
  ``model.features`` and no states at all.  Only the checks that read the
  declared feature list apply; the payload-content ones are skipped,
  since there is no payload content to read.

The issue kinds:

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
  reference set for this category.  Checked both on the keys that reach
  a state publish and on the ``features`` list the device advertises:
  an invented feature name that is never published is invisible to the
  first half and still makes the app render a dead control.  Often
  tolerated today but an easy future breakage.
* **declared_not_published** — the device advertises a state-bearing
  feature (:data:`STATE_BEARING_FEATURES`) that carries no value in the
  publish, so the app shows a control that never updates (issue #63).
  Command-only and event-only features are exempt by construction —
  they have no state to report.  Opt-in via ``check_completeness``,
  all the way up to :meth:`ValidationCollector.record_publish_payload`:
  a partial push is legal, and the command echo is deliberately one
  (it drops the keys the command made irrelevant), so only a caller
  that knows it built a full snapshot may ask for the check.
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
  the UI can render a "current health of each entity" table.  State-
  and model-scope findings are stored side by side there: a config
  publish must not wipe what the last status publish found, nor the
  other way round.
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
from ._generated.usage_modes import EVENT_ONLY_FEATURES, STATE_BEARING_FEATURES

_LOGGER = logging.getLogger(__name__)

EVENT_SHAPED_STATE_FEATURES: frozenset[str] = frozenset(
    name for name in STATE_BEARING_FEATURES if name.startswith("button_") and name.endswith("_event")
)
"""``button_*_event`` — classified as state-bearing, behaving as events.

Sber words all 17 of them as "хранит состояние устройства и может менять
его", which is what puts them in :data:`STATE_BEARING_FEATURES`.  They
are used by exactly one category, ``scenario_button``, whose reference
model is a multi-gang wall remote: a six-button panel advertises
``button_1_event``…``button_6_event`` and reports the one that was
actually pressed.  Taking the classification literally would demand a
"last press" value for all six on every publish and flag five of them
every time — a stream of false positives on a device that is working
exactly as designed.  So they are exempt from the
``declared_not_published`` check, and only from that one: their type,
vocabulary and category membership are still validated normally."""

IssueType = Literal[
    "missing_obligatory",
    "missing_conditional",
    "unknown_enum_value",
    "out_of_range",
    "unknown_for_category",
    "declared_not_published",
    "type_mismatch",
    "not_declared",
]
Severity = Literal["error", "warning", "info"]
PayloadScope = Literal["state", "model"]
"""Which half of the protocol a payload describes — see the module docstring."""

_SEVERITY: dict[IssueType, Severity] = {
    "missing_obligatory": "error",
    "missing_conditional": "error",
    "unknown_enum_value": "error",
    "out_of_range": "warning",
    "unknown_for_category": "warning",
    # Warning, not error, on purpose.  Sber requires a *complete* feature
    # list only in the answer to a query
    # (https://developers.sber.ru/docs/ru/smarthome/c2c/webhook-post-query
    # — "Ответ должен содержать все заявленные функции устройства"); a
    # spontaneous push is allowed to carry a subset.  The bridge always
    # publishes full snapshots, so a gap here does mean the query answer
    # will be short too — but the payload on the wire is not itself
    # illegal, and calling it an error would put a red badge on a device
    # the cloud accepts.
    "declared_not_published": "warning",
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
    scope: PayloadScope = "state",
    check_completeness: bool = False,
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
            its config publish.  ``None`` skips every check that reads
            the feature list (useful when the caller genuinely doesn't
            have the info, e.g. synthetic payload).
        scope: ``"state"`` for a status publish, ``"model"`` for a
            config publish.  A config publish carries no states, so the
            checks that read the payload content are skipped instead of
            reporting the whole device as silent.
        check_completeness: Enables the ``declared_not_published`` check.
            Off by default because it answers a different question from
            the rest: those ask "is this payload legal?", and a partial
            push *is* legal — completeness is required only of the answer
            to a state query.  It asks "is this device fully wired up?",
            which is what the DevTools panel wants and what a caller
            probing one specific rule does not.

    Returns:
        List of :class:`ValidationIssue`.  Empty list == clean publish.
    """
    now = time.time()
    issues: list[ValidationIssue] = []
    states_list = list(states)
    state_keys = {s.get("key") for s in states_list if s.get("key")}
    model_only = scope == "model"

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
        elif not model_only and must not in state_keys and must not in EVENT_ONLY_FEATURES:
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

    # --- feature advertised that the category has never heard of -----------
    # The per-state loop below only sees keys that made it into a publish, so
    # a feature name that is wrong *and* never published (a typo in a manual
    # ``sber_features_add``, a leftover from another category) used to slip
    # through both halves.  In state scope the published keys are left to the
    # loop, or every such key would be reported twice.
    if ref is not None and declared_set is not None:
        suspects = declared_set if model_only else declared_set - state_keys
        issues.extend(
            ValidationIssue(
                ts=now,
                entity_id=entity_id,
                category=category or "",
                type="unknown_for_category",
                severity=_SEVERITY["unknown_for_category"],
                key=key,
                description=(
                    f"Feature '{key}' is advertised in the device model but is not in "
                    f"Sber's reference set for category '{category}'. Remove it, or move "
                    "the device to a category that has it."
                ),
                details={"source": "model"},
            )
            for key in sorted(suspects - ref)
        )

    # --- advertised but never published ------------------------------------
    # Only state-bearing features qualify: a command-only one ("не хранит
    # состояние устройства") has nothing to report by definition, an
    # event-only one reports by staying silent, and ``button_*_event`` is
    # state-bearing on paper only — see EVENT_SHAPED_STATE_FEATURES.
    if check_completeness and not model_only and declared_set is not None:
        must_publish = (declared_set & STATE_BEARING_FEATURES) - EVENT_SHAPED_STATE_FEATURES
        if ref is not None:
            # A feature the category never had is already reported as
            # unknown_for_category, and the fix is the same one ("drop it").
            # Adding "…and it is never published" counts one mistake twice.
            must_publish &= ref
        issues.extend(
            ValidationIssue(
                ts=now,
                entity_id=entity_id,
                category=category or "",
                type="declared_not_published",
                severity=_SEVERITY["declared_not_published"],
                key=key,
                description=(
                    f"Feature '{key}' is advertised in the device model but carries no "
                    "value in this publish. Sber's answer to a state query must list "
                    "every advertised feature, so the app is left with a control that "
                    "never updates. Either publish a value for it or drop the feature."
                ),
                details={"declared": key},
            )
            for key in sorted(must_publish - state_keys)
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
                    details={"source": "state"},
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

    The per-entity view is kept per :data:`PayloadScope`.  Config and
    status publishes alternate on a live bridge, and a single list would
    let each wipe what the other found — a device whose model is wrong
    would look clean for as long as its states are fine.
    """

    def __init__(self, maxlen: int = 500) -> None:
        """Initialize a collector with the given ring-buffer capacity."""
        self._recent: deque[ValidationIssue] = deque(maxlen=maxlen)
        self._by_entity: dict[str, dict[PayloadScope, list[ValidationIssue]]] = {}
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

    @staticmethod
    def _merge_scopes(per_scope: dict[PayloadScope, list[ValidationIssue]]) -> list[ValidationIssue]:
        """Flatten the per-scope lists of one entity into the UI's single list.

        A model-scope finding is dropped when the state scope already
        reports the same ``(type, key)``: an invented feature that is both
        advertised and published is one problem, and showing it twice —
        once from the config publish, once from the status publish — reads
        as two broken things.

        Args:
            per_scope: This entity's ``scope → issues`` mapping.

        Returns:
            State-scope issues first, then the model-scope ones that add
            something new.
        """
        state_issues = per_scope.get("state", [])
        seen = {(i.type, i.key) for i in state_issues}
        return [*state_issues, *(i for i in per_scope.get("model", []) if (i.type, i.key) not in seen)]

    def snapshot(self) -> dict[str, Any]:
        """Return a JSON-serializable snapshot of both views."""
        return {
            "recent": [i.as_dict() for i in self._recent],
            "by_entity": {
                eid: [i.as_dict() for i in self._merge_scopes(per_scope)] for eid, per_scope in self._by_entity.items()
            },
        }

    def clear(self) -> None:
        """Drop all stored issues."""
        self._recent.clear()
        self._by_entity.clear()

    def record(self, entity_id: str, issues: list[ValidationIssue], *, scope: PayloadScope = "state") -> None:
        """Persist the set of issues for ``entity_id`` after a publish.

        A publish that fixes an entity's last error must overwrite the
        per-entity snapshot so DevTools flips it from red to clean;
        that's why we replace (not append) the per-entity list — but only
        within ``scope``, so a config publish does not erase what the last
        status publish found.

        Args:
            entity_id: HA entity id / Sber device id the issues belong to.
            issues: The complete finding list for this publish; empty
                means "this scope is clean now".
            scope: Which half of the protocol produced them.
        """
        # Per-entity view — always overwrite; an empty list signals
        # "entity is clean now", otherwise DevTools can never show the
        # fix propagating.
        self._by_entity.setdefault(entity_id, {})[scope] = list(issues)
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
        check_completeness: bool = False,
    ) -> dict[str, list[ValidationIssue]]:
        """Parse a full Sber publish payload and record per-device issues.

        Accepts **both** publish shapes and tells them apart by the type of
        ``devices``: a dict is a status publish (states per device id), a
        list is a config publish (device descriptors).  Until 1.49.x only
        the dict form was understood, so on a live bridge the whole class
        of "the device model is wrong" was never checked — it only ever
        surfaced in the offline test suite.

        Args:
            payload: JSON string or already-parsed dict.
            categories: Optional mapping ``entity_id → sber_category``.
                Entities without a known category skip spec checks.
                Ignored for a config payload, which states the category of
                every device itself.
            declared_features: Optional mapping ``entity_id → features``
                (as published in the config).  Enables the
                ``not_declared`` check, and — together with
                ``check_completeness`` — the ``declared_not_published``
                one.  Ignored for a config payload, for the same reason.
            check_completeness: Whether this payload is a **full** snapshot
                of every entity in it.  Off by default because the same
                collector also sees the command echo, which deliberately
                drops keys the command made irrelevant
                (``sanitize_echo_states``): demanding completeness there
                turns every ordinary command into a
                ``declared_not_published`` warning about a healthy device.
                Only a caller that builds the whole snapshot itself may
                pass ``True``.  Ignored for a config payload, which
                carries no states to be complete about.

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
        if isinstance(devices, list):
            return self._record_config_devices(devices)
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
                check_completeness=check_completeness,
            )
            self.record(eid, issues)
            result[eid] = issues
        return result

    def _record_config_devices(self, devices: list[Any]) -> dict[str, list[ValidationIssue]]:
        """Validate and record the *model* half of a config publish.

        Each entry carries its own ``model.category`` and
        ``model.features``, so this needs none of the caller-supplied maps
        the status path relies on — it validates exactly what went on the
        wire.  Only model-scope checks run; there are no states here, and
        demanding them would report every device as silent.

        Args:
            devices: The ``devices`` list from a config payload.

        Returns:
            ``device_id → [issues]``.  Entries that are not device
            descriptors are skipped rather than reported: a malformed
            payload is the payload builder's bug, not the user's.
        """
        result: dict[str, list[ValidationIssue]] = {}
        for body in devices:
            if not isinstance(body, dict):
                continue
            device_id = body.get("id")
            model = body.get("model")
            if not isinstance(device_id, str) or not device_id or not isinstance(model, dict):
                continue
            category = model.get("category")
            features = model.get("features")
            issues = validate_publish(
                entity_id=device_id,
                category=category if isinstance(category, str) else None,
                states=(),
                declared_features=features if isinstance(features, list) else None,
                scope="model",
            )
            self.record(device_id, issues, scope="model")
            result[device_id] = issues
        return result
