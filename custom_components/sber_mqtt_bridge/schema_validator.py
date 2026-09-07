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
  is common enough that an error would be noise.  The bounds come from
  :func:`_documented_bounds`, the same helper the ``allowed_values``
  half uses, so a category whose own Sber example is wider than the
  function page (:data:`_CATEGORY_RANGE_SANCTIONED`) is judged by one
  rule in both scopes rather than passing the config check and failing
  every status publish.
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
  ``features`` list as published in the config.  Sber's rule is
  unconditional and repeated on all 96 function pages: "Функция должна
  быть добавлена в описания моделей всех поддерживающих ее устройств".
  Publishing a value for a feature the model never mentions is therefore
  a direct violation, and the cloud has no slot to route the value into.
* **value_shape** — the ``value`` envelope itself is malformed: no
  ``type``, a ``type`` Sber does not define, a payload key that does not
  belong to the declared type, or a payload carried in the wrong JSON
  type.  The one that bites in practice is ``integer_value``: Sber
  documents it as "целочисленное значение long, записанное **в виде
  строки**", so ``{"type": "INTEGER", "integer_value": 42}`` looks right,
  passes every other check here and is then dropped without a word.
  A *missing* payload key is deliberately **not** reported — proto3
  elides fields holding their type's default, so ``{"type": "BOOL"}``
  legitimately means ``false`` and the command echo forwards Sber's own
  elided values back verbatim.
* **colour_out_of_range** — a ``colour_value`` component outside the
  bounds the ``value`` page states (``h`` 0–360, ``s`` 0–1000, ``v``
  **100**–1000).  Components absent from the payload are skipped for the
  proto3 reason above.
* **missing_required_field** — a device or model descriptor is missing a
  field Sber marks ✔︎ obligatory.  Sber drops such a model whole, and
  every device that references it with it.
* **partner_meta_too_long** — ``partner_meta`` exceeds the only numeric
  limit in the entire C2C reference (1024 characters of JSON).
* **allowed_values_widened** — a numeric ``allowed_values`` entry offers
  a range wider than the function's own page documents.  Sber is explicit
  that "диапазон можно только сократить, а шаг можно установить любой",
  so a Home Assistant entity reporting 0–100 % humidity must still
  advertise no more than the documented 30–90.  A warning rather than an
  error: Sber's own category examples break this rule (see
  :data:`_CATEGORY_RANGE_SANCTIONED`), so the wording is stronger than
  the cloud's actual behaviour.
* **allowed_values_shape** — an ``allowed_values`` entry that cannot mean
  what it says: a type outside FLOAT / INTEGER / ENUM carrying limits, a
  ``*_values`` block that does not match the entry's own ``type``, or a
  narrowing of a feature whose page never *states* that narrowing is
  allowed.  That last one is reported as unconfirmed, not as a
  violation — Sber writes the permission on 68 of the 96 function pages
  and writes the prohibition on none.
* **allowed_values_inert** — an entry that is structurally illegal but
  overrides nothing, in practice only ``{"type": "COLOUR"}``.  Reported
  at ``info`` on purpose: every RGB lamp the bridge has ever published
  carries one and every one of them works, so painting them yellow would
  cost more than the finding is worth.

Each issue carries ``severity`` (``error`` / ``warning`` / ``info``),
the ``entity_id`` and ``key``, an English ``description`` for logs and
diagnostics, and the ``message_key`` / ``message_args`` pair the panel
translates into the user's own language (see
:data:`VALIDATION_MESSAGES`).

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

import json
import logging
import time
from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from ._generated.category_features import CATEGORY_REFERENCE_FEATURES
from ._generated.conditional_features import CATEGORY_CONDITIONAL_FEATURES
from ._generated.feature_types import FEATURE_TYPES
from ._generated.obligatory_features import CATEGORY_OBLIGATORY_FEATURES
from ._generated.reference_values import FEATURE_ENUM_VALUES, FEATURE_RANGES
from ._generated.usage_modes import EVENT_ONLY_FEATURES, STATE_BEARING_FEATURES

_LOGGER = logging.getLogger(__name__)

# The four modules below are newer than the rest of ``_generated`` and are
# rebuilt by ``tools/codegen.py`` from the structural pages of the C2C
# reference (``/value``, ``/model``, ``/device``, ``/allowed_values``).  A
# checkout whose ``_generated`` predates them must keep working: every
# constant they carry falls back to an empty container, and every check
# below treats "empty" as *unknown*, never as "nothing is allowed".  That
# is the same rule the scraper itself follows — silence beats inventing a
# rule out of a page that failed to load.
try:  # pragma: no cover — exercised only on an out-of-date checkout
    from ._generated import narrowing as _narrowing
except ImportError:  # pragma: no cover
    _narrowing = None  # type: ignore[assignment]
try:  # pragma: no cover
    from ._generated import protocol_limits as _protocol_limits
except ImportError:  # pragma: no cover
    _protocol_limits = None  # type: ignore[assignment]
try:  # pragma: no cover
    from ._generated import value_envelope as _value_envelope
except ImportError:  # pragma: no cover
    _value_envelope = None  # type: ignore[assignment]

FEATURE_NARROWING: dict[str, str] = getattr(_narrowing, "FEATURE_NARROWING", {})
"""Feature → how far a model may narrow it (``enum_subset`` / ``range_*``).

Absent from the table means only that the function's page never states
the values may be shortened.  Sber nowhere writes the opposite — that
narrowing is *forbidden* — so an ``allowed_values`` entry narrowing such
a feature is reported as **unconfirmed by the documentation**, at
``warning``, and never as a known violation."""

MODEL_REQUIRED_FIELDS: frozenset[str] = getattr(_protocol_limits, "MODEL_REQUIRED_FIELDS", frozenset())
"""Fields the ``model`` structure marks ✔︎ obligatory."""

PARTNER_META_MAX_CHARS: int | None = getattr(_protocol_limits, "PARTNER_META_MAX_CHARS", None)
"""Character budget of ``partner_meta`` in its JSON form, or ``None`` if unknown."""

VALUE_TYPES: frozenset[str] = getattr(_value_envelope, "VALUE_TYPES", frozenset())
"""Every ``value.type`` Sber defines."""

VALUE_FIELD_BY_TYPE: dict[str, str] = getattr(_value_envelope, "VALUE_FIELD_BY_TYPE", {})
"""``value.type`` → the single payload key that carries it."""

VALUE_FIELD_JSON_TYPES: dict[str, str] = getattr(_value_envelope, "VALUE_FIELD_JSON_TYPES", {})
"""Payload key → the JSON type Sber documents for it (``integer_value`` is a *string*)."""

COLOUR_COMPONENT_RANGES: dict[str, tuple[int, int]] = getattr(_value_envelope, "COLOUR_COMPONENT_RANGES", {})
"""Inclusive bounds of the ``colour_value`` components."""

ALLOWED_VALUES_TYPES: frozenset[str] = getattr(_value_envelope, "ALLOWED_VALUES_TYPES", frozenset())
"""The only ``type`` values an ``allowed_values`` entry may declare."""

_ALLOWED_VALUES_BLOCK_BY_TYPE: dict[str, str] = {
    "ENUM": "enum_values",
    "FLOAT": "float_values",
    "INTEGER": "integer_values",
}
"""``allowed_values.type`` → the ``*_values`` block that must accompany it.

Sber marks the three blocks ✔︎* — exactly one per entry, chosen by the
entry's own ``type``.  An INTEGER entry holding ``enum_values`` declares
nothing the cloud can read."""

DEVICE_REQUIRED_FIELDS: frozenset[str] = frozenset({"id", "name", "default_name"})
"""Device fields the bridge can demand unconditionally.

Deliberately **not** :data:`_generated.protocol_limits.DEVICE_REQUIRED_FIELDS`:
that set is taken verbatim from the page, which marks both ``model_id``
and ``model`` obligatory while the ``model`` row says "указывается,
только если не задан model_id".  Both cannot hold at once, so the
either/or half is checked separately and only the three fields that carry
no contradiction are demanded here."""

_CATEGORY_RANGE_SANCTIONED: dict[tuple[str, str], tuple[float, float]] = {
    ("hvac_boiler", "hvac_temp_set"): (5.0, 80.0),
}
"""Ranges Sber's own category example allows beyond the function's page.

The ``hvac_temp_set`` page says ``INTEGER(5, 50)``, and then the
``hvac_boiler`` page publishes a reference model declaring ``25…80``.
The category example is the more specific statement for boilers — and it
is what :class:`~.devices.hvac_boiler.HvacBoilerEntity` was built from —
so flagging a boiler that reaches 80 °C would be reporting Sber's own
reference device as broken.  Every entry here is re-derived from the
scraped snapshot by ``test_schema_validator_spec_checks.py``, so a
documentation fix upstream turns into a failing test rather than into a
warning nobody can act on."""

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
    "value_shape",
    "colour_out_of_range",
    "missing_required_field",
    "partner_meta_too_long",
    "allowed_values_widened",
    "allowed_values_shape",
    "allowed_values_inert",
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
    # Error, not info.  Sber repeats the rule on every one of its 96
    # function pages — "Функция должна быть добавлена в описания моделей
    # всех поддерживающих ее устройств" — and the cloud has nowhere to put
    # a value whose key the model never mentioned.  It cannot fire on a
    # healthy bridge either: the publisher hands the collector the very
    # same ``get_final_features_list()`` the payload was built from, so a
    # finding here always means the two halves genuinely disagree.
    "not_declared": "error",
    "value_shape": "error",
    "colour_out_of_range": "error",
    "missing_required_field": "error",
    "partner_meta_too_long": "error",
    # Warning, not error, and the gap is Sber's own.  The rule is stated
    # flatly on /allowed_values ("диапазон можно только сократить"), but
    # the hvac_boiler category page then publishes a reference model that
    # breaks it, so the documentation does not support painting a device
    # red over this.
    "allowed_values_widened": "warning",
    "allowed_values_shape": "warning",
    "allowed_values_inert": "info",
}


@dataclass(frozen=True)
class ValidationIssue:
    """One validation problem found in a publish.

    ``description`` is the English sentence, kept for everything that has
    no translation catalogue — logs, diagnostics dumps, test failures.
    The panel renders ``message_key`` / ``message_args`` through the
    integration's own ``config_panel`` strings instead, so a Russian user
    reads Russian and an English one English; see
    :data:`VALIDATION_MESSAGES`.
    """

    ts: float
    entity_id: str
    category: str
    type: IssueType
    severity: Severity
    key: str | None
    description: str
    details: dict[str, Any]
    message_key: str = ""
    """Key under ``config_panel.validation_issue`` naming the sentence."""

    message_args: dict[str, str] = field(default_factory=dict)
    """Ready-to-render placeholder values, identical in every language."""

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


def _json_kind(payload: Any) -> str:
    """Name the JSON type of a payload the way Sber's ``value`` page does.

    ``bool`` is checked before ``int`` on purpose — in Python ``True`` is
    an ``int``, and calling a boolean a number would let
    ``{"type": "INTEGER", "integer_value": true}`` pass.

    Args:
        payload: The raw value read out of a ``value`` envelope.

    Returns:
        One of ``boolean`` / ``string`` / ``number`` / ``colour`` /
        ``array`` / ``null`` / ``unknown``.  ``colour`` is the page's own
        name for the ``{h, s, v}`` object.
    """
    if isinstance(payload, bool):
        return "boolean"
    if isinstance(payload, str):
        return "string"
    if isinstance(payload, int | float):
        return "number"
    if isinstance(payload, dict):
        return "colour"
    if isinstance(payload, list):
        return "array"
    if payload is None:
        return "null"
    return "unknown"


VALIDATION_MESSAGES: dict[str, str] = {
    "value_not_an_object": (
        "Feature “{key}”: the value is not an object but a JSON {json_type}, so Sber cannot read it."
    ),
    "value_missing_type": (
        "Feature “{key}”: the value has no “type” field, so Sber cannot tell how to read it and drops the state."
    ),
    "value_unknown_type": ("Feature “{key}”: value type “{declared}” is unknown to Sber. Only {allowed} are defined."),
    "value_foreign_fields": (
        "Feature “{key}”: the {declared} value carries foreign fields {foreign} next to the "
        "expected “{own_field}”. Extra fields are a known cause of silent rejection."
    ),
    "value_wrong_json_type": (
        "Feature “{key}”: field “{field}” is sent as a JSON {actual}, but Sber documents it as "
        "{expected}. Such a state reaches the cloud and is silently lost."
    ),
    "value_integer_must_be_string": (
        "Feature “{key}”: field “integer_value” is sent as a JSON {actual}, but Sber requires the "
        "integer as a string (“42”, not 42). Such a state reaches the cloud and is silently lost."
    ),
    "colour_component_out_of_range": (
        "Feature “{key}”: colour component {component} = {sent} is outside the documented range "
        "{min}…{max}. Sber will show a different colour or drop the value."
    ),
    "allowed_values_bad_type": (
        "Feature “{key}”: allowed_values declares type “{declared}”, but Sber only lets a model "
        "override {permitted}. The limit will not be applied."
    ),
    "allowed_values_inert": (
        "Feature “{key}”: an allowed_values entry of type “{declared}” restricts nothing — Sber "
        "only overrides {permitted}. It does not affect the device and can be removed."
    ),
    "allowed_values_wrong_block": (
        "Feature “{key}”: the entry declares type “{declared}” but carries its limits in {present} "
        "instead of “{expected_block}”. Sber cannot read such an entry."
    ),
    "allowed_values_type_mismatch": (
        "Feature “{key}”: allowed_values declares type “{declared}” while Sber types the feature "
        "itself as “{expected}”."
    ),
    "allowed_values_unknown_enum": (
        "Feature “{key}”: allowed_values offers {sent}, which is missing from Sber's vocabulary for "
        "this feature ({allowed}). The app will draw a button that does nothing."
    ),
    "allowed_values_widened": (
        "Feature “{key}”: the model declares the range {declared_min}…{declared_max} while Sber "
        "documents {min}…{max}. A range may only be narrowed, never widened. Limit the entity in "
        "Home Assistant or in the bridge's redefinitions."
    ),
    "allowed_values_narrowing_unconfirmed": (
        "Feature “{key}”: the model shortens its allowed values, and this function's page does not "
        "state that shortening is permitted. Sber does not forbid it in writing either — check the "
        "model against the documentation."
    ),
    "obligatory_not_declared": (
        "Feature “{key}” is obligatory for category “{category}” but is missing from the device "
        "model. Sber drops such a device silently."
    ),
    "obligatory_not_published": (
        "Feature “{key}” is obligatory for category “{category}” but carries no value in this "
        "publish. Sber drops such a device silently."
    ),
    "conditional_group_missing": (
        "Category “{category}” requires at least one of: {group}. The device declares none of them, "
        "so Sber will drop it."
    ),
    "feature_unknown_for_category_model": (
        "Feature “{key}” is advertised in the device model but is not in Sber's reference set for "
        "category “{category}”. Remove it, or move the device to a category that has it."
    ),
    "declared_not_published": (
        "Feature “{key}” is advertised in the device model but carries no value in this publish. "
        "Sber's answer to a state query must list every advertised feature, so the app is left with "
        "a control that never updates. Either publish a value for it or drop the feature."
    ),
    "type_mismatch": "Feature “{key}” sent as {actual}, spec requires {expected}.",
    "state_unknown_enum": (
        "Feature “{key}” sent value “{sent}”, which is not one of the values Sber documents for it. "
        "The cloud cannot route a value it does not know."
    ),
    "value_out_of_range": (
        "Feature “{key}” sent {sent}, outside the documented range {min}…{max}. Sber may clip or drop it."
    ),
    "feature_unknown_for_category_state": ("Feature “{key}” is not in Sber's reference set for category “{category}”."),
    "state_not_declared": (
        "Feature “{key}” is published but not advertised in the device's config features list. Sber "
        "requires every supported feature to be described in the model, or the value is discarded."
    ),
    "device_missing_field": (
        "The device descriptor has no obligatory field “{field}”. Sber drops such a device whole — "
        "it will not appear in the app."
    ),
    "device_missing_model": (
        "The device declares no model: it needs either the “model_id” of an already registered "
        "model, or an inline “model” description."
    ),
    "model_missing_field": (
        "The device model has no obligatory field “{field}”. Sber drops the model, and with it "
        "every device built on it."
    ),
    "partner_meta_too_long": (
        "partner_meta takes {size} JSON characters against a limit of {max}. It is the only numeric "
        "limit in the whole Sber reference, and a device above it is not accepted."
    ),
}
"""Message key → English sentence, with ``{name}`` placeholders.

The one source of the English wording.  The panel does not render these
strings: it looks the same keys up in ``config_panel.validation_issue``
of the integration's translations, so the text follows the user's Home
Assistant language instead of being frozen in Python (the panel itself
has been fully localized since v1.36.0).  ``translations/en.json`` must
therefore repeat this table verbatim, which
``test_validation_messages_are_localized.py`` enforces key by key,
placeholder by placeholder.

Placeholder values are pre-formatted strings built at the call site
(numbers through ``:g``, lists joined with ", "), so every language
renders the same figures and no formatting logic has to be duplicated in
JavaScript."""


def _issue(
    *,
    now: float,
    entity_id: str,
    category: str | None,
    kind: IssueType,
    key: str | None,
    message_key: str,
    message_args: dict[str, str] | None = None,
    details: dict[str, Any],
) -> ValidationIssue:
    """Build one :class:`ValidationIssue` with the kind's default severity.

    The English ``description`` is rendered here from
    :data:`VALIDATION_MESSAGES`, so a call site states the sentence once —
    as a key plus its placeholder values — and the panel can translate the
    very same pair.

    Args:
        now: Timestamp shared by every issue of one publish.
        entity_id: HA entity id / Sber device id.
        category: Sber category, or ``None`` when unknown.
        kind: Issue type; also selects the severity.
        key: Feature the finding is about, or ``None`` for device-wide ones.
        message_key: Key into :data:`VALIDATION_MESSAGES`.
        message_args: Pre-formatted placeholder values.
        details: Machine-readable payload for the UI and for tests.

    Returns:
        The assembled issue.
    """
    args = dict(message_args or {})
    return ValidationIssue(
        ts=now,
        entity_id=entity_id,
        category=category or "",
        type=kind,
        severity=_SEVERITY[kind],
        key=key,
        description=VALIDATION_MESSAGES[message_key].format(**args),
        message_key=message_key,
        message_args=args,
        details=details,
    )


def _value_shape_issues(
    *,
    now: float,
    entity_id: str,
    category: str | None,
    key: str,
    value: Any,
) -> list[ValidationIssue]:
    """Check one ``value`` envelope against the ``/value`` structure page.

    Four things are checked, and one deliberately is not.  Checked: the
    envelope is an object; ``type`` is present and is one Sber defines;
    every payload key present belongs to that type; and each payload is
    carried in the JSON type the page assigns it — the case that matters
    being ``integer_value``, which Sber requires as a *string*.

    Not checked: the *absence* of the type's payload key.  Sber serializes
    protobuf by proto3 rules, so a field holding its type's default value
    is omitted — ``{"type": "BOOL"}`` is a perfectly legal ``false``.  The
    command echo forwards Sber's own command values back verbatim
    (``sber_publisher`` merges them into the baseline before publishing),
    so demanding the key would raise an error on every "turn it off"
    command the bridge ever confirms.

    Args:
        now: Timestamp shared by every issue of one publish.
        entity_id: HA entity id / Sber device id.
        category: Sber category, or ``None``.
        key: Feature the value belongs to.
        value: The ``value`` object from the state entry.

    Returns:
        Issues found, newest-check-last; empty when the envelope is sound
        or when the generated tables are unavailable.
    """
    if not VALUE_TYPES or not VALUE_FIELD_BY_TYPE:
        return []
    if not isinstance(value, dict):
        return [
            _issue(
                now=now,
                entity_id=entity_id,
                category=category,
                kind="value_shape",
                key=key,
                message_key="value_not_an_object",
                message_args={"key": key, "json_type": _json_kind(value)},
                details={"reason": "not_an_object", "json_type": _json_kind(value)},
            )
        ]

    declared = value.get("type")
    if not isinstance(declared, str) or not declared:
        return [
            _issue(
                now=now,
                entity_id=entity_id,
                category=category,
                kind="value_shape",
                key=key,
                message_key="value_missing_type",
                message_args={"key": key},
                details={"reason": "missing_type"},
            )
        ]
    if declared not in VALUE_TYPES:
        return [
            _issue(
                now=now,
                entity_id=entity_id,
                category=category,
                kind="value_shape",
                key=key,
                message_key="value_unknown_type",
                message_args={
                    "key": key,
                    "declared": declared,
                    "allowed": ", ".join(sorted(VALUE_TYPES)),
                },
                details={"reason": "unknown_type", "declared": declared, "allowed": sorted(VALUE_TYPES)},
            )
        ]

    issues: list[ValidationIssue] = []
    own_field = VALUE_FIELD_BY_TYPE[declared]
    foreign = sorted(k for k in value if k != "type" and k != own_field)
    if foreign:
        issues.append(
            _issue(
                now=now,
                entity_id=entity_id,
                category=category,
                kind="value_shape",
                key=key,
                message_key="value_foreign_fields",
                message_args={
                    "key": key,
                    "declared": declared,
                    "foreign": ", ".join(foreign),
                    "own_field": own_field,
                },
                details={"reason": "foreign_fields", "declared": declared, "foreign": foreign},
            )
        )

    if own_field in value:
        expected_json = VALUE_FIELD_JSON_TYPES.get(own_field)
        actual_json = _json_kind(value[own_field])
        if expected_json is not None and actual_json != expected_json:
            issues.append(
                _issue(
                    now=now,
                    entity_id=entity_id,
                    category=category,
                    kind="value_shape",
                    key=key,
                    message_key=(
                        "value_integer_must_be_string" if own_field == "integer_value" else "value_wrong_json_type"
                    ),
                    message_args={
                        "key": key,
                        "field": own_field,
                        "actual": actual_json,
                        "expected": expected_json,
                    },
                    details={
                        "reason": "wrong_json_type",
                        "field": own_field,
                        "expected": expected_json,
                        "actual": actual_json,
                    },
                )
            )
    return issues


def _colour_issues(
    *,
    now: float,
    entity_id: str,
    category: str | None,
    key: str,
    value: Any,
) -> list[ValidationIssue]:
    """Range-check the components of a ``colour_value``.

    Only components actually present are checked — proto3 drops a zero
    component, and issue #44 was exactly that: the colour-temperature
    slider at its edge produced ``{"h": 0}`` with ``s`` and ``v`` elided.

    Args:
        now: Timestamp shared by every issue of one publish.
        entity_id: HA entity id / Sber device id.
        category: Sber category, or ``None``.
        key: Feature the colour belongs to.
        value: The ``value`` object from the state entry.

    Returns:
        One issue per out-of-bounds component.
    """
    if not COLOUR_COMPONENT_RANGES or not isinstance(value, dict):
        return []
    colour = value.get("colour_value")
    if not isinstance(colour, dict):
        return []
    issues: list[ValidationIssue] = []
    for component, (low, high) in sorted(COLOUR_COMPONENT_RANGES.items()):
        raw = colour.get(component)
        if raw is None or isinstance(raw, bool) or not isinstance(raw, int | float):
            continue
        if low <= raw <= high:
            continue
        issues.append(
            _issue(
                now=now,
                entity_id=entity_id,
                category=category,
                kind="colour_out_of_range",
                key=key,
                message_key="colour_component_out_of_range",
                message_args={
                    "key": key,
                    "component": component,
                    "sent": f"{raw:g}",
                    "min": f"{low:g}",
                    "max": f"{high:g}",
                },
                details={"component": component, "sent": raw, "min": low, "max": high},
            )
        )
    return issues


def _documented_bounds(category: str | None, key: str) -> tuple[float, float] | None:
    """Return the widest range a model of ``category`` may declare for ``key``.

    Normally the function page's own range, but Sber's category examples
    occasionally exceed it — see :data:`_CATEGORY_RANGE_SANCTIONED`, where
    the reference boiler declares a hotter ``hvac_temp_set`` than the
    function page allows.  For those pairs the example wins, because a
    device copied from Sber's own reference must not be reported as
    broken.

    Args:
        category: Sber category the model declares.
        key: Feature name.

    Returns:
        ``(min, max)`` inclusive, or ``None`` when the feature has no
        documented range at all.
    """
    sanctioned = _CATEGORY_RANGE_SANCTIONED.get((category or "", key))
    if sanctioned is not None:
        return sanctioned
    return FEATURE_RANGES.get(key)


def _allowed_values_issues(
    *,
    now: float,
    entity_id: str,
    category: str | None,
    allowed_values: dict[str, Any],
) -> list[ValidationIssue]:
    """Check an ``allowed_values`` map against the rules Sber states for it.

    ``allowed_values`` exists for exactly one purpose — to *narrow* what a
    particular model accepts — and the page constrains it three ways: it
    may only be used for FLOAT / INTEGER / ENUM features; the block inside
    must match the entry's own ``type``; and "диапазон можно только
    сократить, а шаг можно установить любой".  Whether a *given* feature
    may be narrowed is stated per function page and collected in
    :data:`FEATURE_NARROWING`; a feature missing from it is reported as
    unconfirmed rather than forbidden, because no page states a
    prohibition.

    An entry that merely restates the full documented vocabulary or the
    full documented range is left alone: it narrows nothing, so none of
    the rules is engaged and reporting it would be noise on a device that
    is behaving.

    Args:
        now: Timestamp shared by every issue of one publish.
        entity_id: HA entity id / Sber device id.
        category: Sber category the model declares.
        allowed_values: The ``model.allowed_values`` map as published.

    Returns:
        Issues found across every entry.
    """
    issues: list[ValidationIssue] = []
    for key, spec in sorted(allowed_values.items()):
        if not isinstance(spec, dict):
            continue
        declared = spec.get("type")
        block_name = _ALLOWED_VALUES_BLOCK_BY_TYPE.get(declared or "")
        block = spec.get(block_name) if block_name else None
        carries_limits = any(name in spec for name in _ALLOWED_VALUES_BLOCK_BY_TYPE.values())

        # --- a type Sber never lets a model override ----------------------
        if ALLOWED_VALUES_TYPES and declared not in ALLOWED_VALUES_TYPES:
            permitted = ", ".join(sorted(ALLOWED_VALUES_TYPES))
            if carries_limits:
                issues.append(
                    _issue(
                        now=now,
                        entity_id=entity_id,
                        category=category,
                        kind="allowed_values_shape",
                        key=key,
                        message_key="allowed_values_bad_type",
                        message_args={"key": key, "declared": str(declared), "permitted": permitted},
                        details={"declared": declared, "allowed": sorted(ALLOWED_VALUES_TYPES)},
                    )
                )
            else:
                issues.append(
                    _issue(
                        now=now,
                        entity_id=entity_id,
                        category=category,
                        kind="allowed_values_inert",
                        key=key,
                        message_key="allowed_values_inert",
                        message_args={"key": key, "declared": str(declared), "permitted": permitted},
                        details={"declared": declared, "allowed": sorted(ALLOWED_VALUES_TYPES)},
                    )
                )
            continue

        # --- the block inside must match the entry's own type -------------
        if block_name is not None and block is None and carries_limits:
            present = sorted(n for n in _ALLOWED_VALUES_BLOCK_BY_TYPE.values() if n in spec)
            issues.append(
                _issue(
                    now=now,
                    entity_id=entity_id,
                    category=category,
                    kind="allowed_values_shape",
                    key=key,
                    message_key="allowed_values_wrong_block",
                    message_args={
                        "key": key,
                        "declared": str(declared),
                        "present": ", ".join(present),
                        "expected_block": block_name,
                    },
                    details={"declared": declared, "expected_block": block_name, "present": present},
                )
            )
            continue

        spec_type = FEATURE_TYPES.get(key)
        if spec_type is not None and declared != spec_type:
            issues.append(
                _issue(
                    now=now,
                    entity_id=entity_id,
                    category=category,
                    kind="allowed_values_shape",
                    key=key,
                    message_key="allowed_values_type_mismatch",
                    message_args={"key": key, "declared": str(declared), "expected": spec_type},
                    details={"declared": declared, "expected": spec_type},
                )
            )
            continue

        issues.extend(
            _allowed_entry_issues(
                now=now,
                entity_id=entity_id,
                category=category,
                key=key,
                declared=declared or "",
                block=block,
            )
        )
    return issues


def _allowed_entry_issues(
    *,
    now: float,
    entity_id: str,
    category: str | None,
    key: str,
    declared: str,
    block: Any,
) -> list[ValidationIssue]:
    """Check the limits inside one well-formed ``allowed_values`` entry.

    Args:
        now: Timestamp shared by every issue of one publish.
        entity_id: HA entity id / Sber device id.
        category: Sber category the model declares.
        key: Feature the entry belongs to.
        declared: The entry's ``type`` (already known to be permitted).
        block: The ``*_values`` block, or ``None`` when the entry carries none.

    Returns:
        Issues about the limits themselves.
    """
    if not isinstance(block, dict):
        return []
    issues: list[ValidationIssue] = []
    narrows = False

    if declared == "ENUM":
        offered = block.get("values")
        vocabulary = FEATURE_ENUM_VALUES.get(key)
        if isinstance(offered, list) and vocabulary:
            unknown = sorted(v for v in offered if isinstance(v, str) and v not in vocabulary)
            narrows = bool(set(vocabulary) - {v for v in offered if isinstance(v, str)})
            if unknown:
                issues.append(
                    _issue(
                        now=now,
                        entity_id=entity_id,
                        category=category,
                        kind="unknown_enum_value",
                        key=key,
                        message_key="allowed_values_unknown_enum",
                        message_args={
                            "key": key,
                            "sent": ", ".join(unknown),
                            "allowed": ", ".join(sorted(vocabulary)),
                        },
                        details={"source": "allowed_values", "sent": unknown, "allowed": sorted(vocabulary)},
                    )
                )
    else:
        bounds = _documented_bounds(category, key)
        low, high = _numeric_bounds(block)
        narrows = bounds is not None and (
            (low is not None and low > bounds[0]) or (high is not None and high < bounds[1])
        )
        if bounds is not None and (low is not None or high is not None):
            wider_low = low is not None and low < bounds[0]
            wider_high = high is not None and high > bounds[1]
            if wider_low or wider_high:
                shown_low = low if low is not None else bounds[0]
                shown_high = high if high is not None else bounds[1]
                issues.append(
                    _issue(
                        now=now,
                        entity_id=entity_id,
                        category=category,
                        kind="allowed_values_widened",
                        key=key,
                        message_key="allowed_values_widened",
                        message_args={
                            "key": key,
                            "declared_min": f"{shown_low:g}",
                            "declared_max": f"{shown_high:g}",
                            "min": f"{bounds[0]:g}",
                            "max": f"{bounds[1]:g}",
                        },
                        details={
                            "declared_min": low,
                            "declared_max": high,
                            "min": bounds[0],
                            "max": bounds[1],
                        },
                    )
                )

    if narrows and FEATURE_NARROWING and key not in FEATURE_NARROWING:
        issues.append(
            _issue(
                now=now,
                entity_id=entity_id,
                category=category,
                kind="allowed_values_shape",
                key=key,
                message_key="allowed_values_narrowing_unconfirmed",
                message_args={"key": key},
                details={"reason": "narrowing_not_documented"},
            )
        )
    return issues


def _numeric_bounds(block: dict[str, Any]) -> tuple[float | None, float | None]:
    """Read ``min`` / ``max`` out of an ``integer_values`` / ``float_values`` block.

    Sber writes INTEGER limits as strings and FLOAT limits as numbers, so
    both are accepted; anything unreadable comes back as ``None`` and the
    caller skips that side rather than guessing.

    Args:
        block: The ``*_values`` block.

    Returns:
        ``(min, max)``, either of which may be ``None``.
    """
    parsed: list[float | None] = []
    for name in ("min", "max"):
        raw = block.get(name)
        try:
            parsed.append(float(raw))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            parsed.append(None)
    return parsed[0], parsed[1]


def validate_publish(
    *,
    entity_id: str,
    category: str | None,
    states: Iterable[dict[str, Any]],
    declared_features: Iterable[str] | None = None,
    scope: PayloadScope = "state",
    check_completeness: bool = False,
    allowed_values: dict[str, Any] | None = None,
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
        allowed_values: The device's ``model.allowed_values`` map, when the
            caller has it.  Only a config publish carries one, so it is
            inspected in ``model`` scope alone; ``None`` skips the
            ``allowed_values_*`` checks entirely.

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
            message_key = "obligatory_not_declared"
        elif not model_only and must not in state_keys and must not in EVENT_ONLY_FEATURES:
            message_key = "obligatory_not_published"
        else:
            continue
        issues.append(
            _issue(
                now=now,
                entity_id=entity_id,
                category=category,
                kind="missing_obligatory",
                key=must,
                message_key=message_key,
                message_args={"key": must, "category": category or ""},
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
            _issue(
                now=now,
                entity_id=entity_id,
                category=category,
                kind="missing_conditional",
                key=None,
                message_key="conditional_group_missing",
                message_args={"category": category or "", "group": group},
                details={"expected_any_of": sorted(conditional)},
            )
        )

    # --- limits the model declares for its own features ---------------------
    if model_only and isinstance(allowed_values, dict) and allowed_values:
        issues.extend(
            _allowed_values_issues(now=now, entity_id=entity_id, category=category, allowed_values=allowed_values)
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
            _issue(
                now=now,
                entity_id=entity_id,
                category=category,
                kind="unknown_for_category",
                key=key,
                message_key="feature_unknown_for_category_model",
                message_args={"key": key, "category": category or ""},
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
            _issue(
                now=now,
                entity_id=entity_id,
                category=category,
                kind="declared_not_published",
                key=key,
                message_key="declared_not_published",
                message_args={"key": key},
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

        # --- the value envelope itself -------------------------------------
        # Runs before the semantic checks: a payload whose ``type`` is not
        # one Sber defines, or whose integer arrived unquoted, is broken no
        # matter what the feature tables say about the key.
        issues.extend(_value_shape_issues(now=now, entity_id=entity_id, category=category, key=key, value=val))
        issues.extend(_colour_issues(now=now, entity_id=entity_id, category=category, key=key, value=val))

        # --- type mismatch -------------------------------------------------
        expected = FEATURE_TYPES.get(key)
        if expected is not None and actual_type and actual_type != expected:
            issues.append(
                _issue(
                    now=now,
                    entity_id=entity_id,
                    category=category,
                    kind="type_mismatch",
                    key=key,
                    message_key="type_mismatch",
                    message_args={"key": key, "actual": actual_type, "expected": expected},
                    details={"expected": expected, "actual": actual_type},
                )
            )

        # --- value outside the feature's documented vocabulary -------------
        vocabulary = FEATURE_ENUM_VALUES.get(key)
        if vocabulary and actual_type == "ENUM":
            sent = val.get("enum_value") if isinstance(val, dict) else None
            if isinstance(sent, str) and sent not in vocabulary:
                issues.append(
                    _issue(
                        now=now,
                        entity_id=entity_id,
                        category=category,
                        kind="unknown_enum_value",
                        key=key,
                        message_key="state_unknown_enum",
                        message_args={"key": key, "sent": sent},
                        details={"sent": sent, "allowed": sorted(vocabulary)},
                    )
                )

        # --- numeric value outside the documented range --------------------
        # Same rule the model half uses (see _documented_bounds): a boiler
        # copied from Sber's own reference model must not be called broken
        # in its config publish and then again in every status publish.
        bounds = _documented_bounds(category, key)
        number = _numeric_payload(val) if bounds else None
        if bounds is not None and number is not None and not (bounds[0] <= number <= bounds[1]):
            issues.append(
                _issue(
                    now=now,
                    entity_id=entity_id,
                    category=category,
                    kind="out_of_range",
                    key=key,
                    message_key="value_out_of_range",
                    message_args={
                        "key": key,
                        "sent": f"{number:g}",
                        "min": f"{bounds[0]:g}",
                        "max": f"{bounds[1]:g}",
                    },
                    details={"sent": number, "min": bounds[0], "max": bounds[1]},
                )
            )

        # --- unknown for category -----------------------------------------
        if ref is not None and key not in ref:
            issues.append(
                _issue(
                    now=now,
                    entity_id=entity_id,
                    category=category,
                    kind="unknown_for_category",
                    key=key,
                    message_key="feature_unknown_for_category_state",
                    message_args={"key": key, "category": category or ""},
                    details={"source": "state"},
                )
            )

        # --- not in declared features -------------------------------------
        if declared_set is not None and key not in declared_set:
            issues.append(
                _issue(
                    now=now,
                    entity_id=entity_id,
                    category=category,
                    kind="not_declared",
                    key=key,
                    message_key="state_not_declared",
                    message_args={"key": key},
                    details={},
                )
            )

    return issues


def validate_device_descriptor(descriptor: dict[str, Any]) -> list[ValidationIssue]:
    """Validate one device entry of a config publish (``up/config``).

    Covers what :func:`validate_publish` cannot see, because it looks at
    the *envelope* around the model rather than at its feature list: the
    fields Sber marks ✔︎ obligatory on the ``device`` and ``model``
    structure pages, the ``partner_meta`` size limit, and the either/or
    between ``model_id`` and an inline ``model``.  Then it hands the model
    itself — features and ``allowed_values`` — to :func:`validate_publish`
    in ``model`` scope.

    Args:
        descriptor: One entry of the ``devices`` list from a config
            payload, exactly as it went on the wire.

    Returns:
        Every finding for this device, device-level ones first.
    """
    now = time.time()
    device_id = descriptor.get("id")
    entity_id = device_id if isinstance(device_id, str) and device_id else ""
    model = descriptor.get("model")
    model_dict = model if isinstance(model, dict) else {}
    category = model_dict.get("category")
    category_str = category if isinstance(category, str) else None

    issues: list[ValidationIssue] = []

    issues.extend(
        _issue(
            now=now,
            entity_id=entity_id,
            category=category_str,
            kind="missing_required_field",
            key=None,
            message_key="device_missing_field",
            message_args={"field": field},
            details={"scope": "device", "field": field},
        )
        for field in sorted(DEVICE_REQUIRED_FIELDS)
        if descriptor.get(field) in (None, "")
    )
    if not model_dict and not descriptor.get("model_id"):
        issues.append(
            _issue(
                now=now,
                entity_id=entity_id,
                category=category_str,
                kind="missing_required_field",
                key=None,
                message_key="device_missing_model",
                details={"scope": "device", "field": "model"},
            )
        )

    issues.extend(
        _issue(
            now=now,
            entity_id=entity_id,
            category=category_str,
            kind="missing_required_field",
            key=None,
            message_key="model_missing_field",
            message_args={"field": field},
            details={"scope": "model", "field": field},
        )
        for field in sorted(MODEL_REQUIRED_FIELDS)
        if model_dict and model_dict.get(field) in (None, "", [], {})
    )

    partner_meta = descriptor.get("partner_meta")
    if PARTNER_META_MAX_CHARS is not None and partner_meta is not None:
        try:
            size = len(json.dumps(partner_meta, ensure_ascii=False))
        except (TypeError, ValueError):
            size = None
        if size is not None and size > PARTNER_META_MAX_CHARS:
            issues.append(
                _issue(
                    now=now,
                    entity_id=entity_id,
                    category=category_str,
                    kind="partner_meta_too_long",
                    key=None,
                    message_key="partner_meta_too_long",
                    message_args={"size": str(size), "max": str(PARTNER_META_MAX_CHARS)},
                    details={"size": size, "max": PARTNER_META_MAX_CHARS},
                )
            )

    features = model_dict.get("features")
    allowed = model_dict.get("allowed_values")
    issues.extend(
        validate_publish(
            entity_id=entity_id,
            category=category_str,
            states=(),
            declared_features=features if isinstance(features, list) else None,
            scope="model",
            allowed_values=allowed if isinstance(allowed, dict) else None,
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
            if not isinstance(device_id, str) or not device_id:
                continue
            # A descriptor without an inline ``model`` is deliberately let
            # through: it is legal (Sber's either/or with ``model_id``) and
            # :func:`validate_device_descriptor` has the checks for it.
            # Filtering it out here would leave those checks reachable only
            # from tests.
            issues = validate_device_descriptor(body)
            self.record(device_id, issues, scope="model")
            result[device_id] = issues
        return result
