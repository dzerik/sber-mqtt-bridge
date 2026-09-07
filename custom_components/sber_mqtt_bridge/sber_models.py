"""Pydantic models for Sber Smart Home MQTT protocol.

Provides **strict** typed schemas for Sber protocol payloads (device config,
states, commands) and helper functions for constructing protocol values.

All models use ``extra="forbid"`` to reject unexpected fields — this catches
protocol violations like the TV ``allowed_values`` bug (extra keys caused
Sber cloud to silently reject devices).

These models serve as:
- Executable specification of the Sber C2C JSON protocol
- Pre-publish validation layer (invalid devices excluded from payload)
- Type-safe constructors for Sber state values

Source of truth: https://developers.sber.ru/docs/ru/smarthome/c2c/
"""

from __future__ import annotations

import json
import logging
import math
from collections.abc import Callable
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from ._generated import (
    CATEGORY_OBLIGATORY_FEATURES,
    CATEGORY_REFERENCE_FEATURES,
    FEATURE_ENUM_VALUES,
    FEATURE_TYPES,
)

_LOGGER = logging.getLogger(__name__)

# Structural constants scraped from the C2C reference pages ``/value`` and
# ``/device``.  They live in a package that a stale checkout may not have
# yet, so each one falls back to "unknown" rather than to a guessed value:
# an unknown bound disables its check instead of inventing a limit.
try:  # pragma: no cover — exercised only on an out-of-date checkout
    from ._generated import protocol_limits as _protocol_limits
except ImportError:  # pragma: no cover
    _protocol_limits = None  # type: ignore[assignment]
try:  # pragma: no cover
    from ._generated import value_envelope as _value_envelope
except ImportError:  # pragma: no cover
    _value_envelope = None  # type: ignore[assignment]

PARTNER_META_MAX_CHARS: int | None = getattr(_protocol_limits, "PARTNER_META_MAX_CHARS", None)
"""Character budget of ``partner_meta`` in its JSON form (VR-003).

Sourced from the scrape rather than typed in by hand: the number 1024 is
the only numeric limit in the whole C2C reference, and if Sber ever moves
it the drift check must break a test instead of leaving a stale constant
silently rejecting devices the cloud would accept."""

COLOUR_COMPONENT_RANGES: dict[str, tuple[int, int]] = getattr(_value_envelope, "COLOUR_COMPONENT_RANGES", {})
"""Inclusive HSV bounds of ``colour_value`` (VR-004: ``v`` starts at 100)."""

VALUE_FIELD_BY_TYPE: dict[str, str] = getattr(_value_envelope, "VALUE_FIELD_BY_TYPE", {})
"""``value.type`` → the single payload key that type may carry."""


# ---------------------------------------------------------------------------
# Value types
# ---------------------------------------------------------------------------


class SberColourValue(BaseModel):
    """HSV colour value per Sber spec.

    Ranges (from :data:`COLOUR_COMPONENT_RANGES`, scraped from the
    ``value`` structure page):
        h: 0-360 (hue degrees)
        s: 0-1000 (saturation, 0.1% steps)
        v: 100-1000 (value/brightness, min 100 per Sber spec VR-004)
    """

    model_config = ConfigDict(extra="forbid")

    h: int
    s: int
    v: int

    @model_validator(mode="after")
    def components_within_documented_range(self) -> SberColourValue:
        """Reject HSV components outside the bounds Sber documents.

        The bridge maps Home Assistant's 0-255 brightness onto Sber's
        100-1000 ``v`` by hand in ``devices/utils/color_converter.py``;
        until now nothing tied that arithmetic to the documentation, so a
        refactor that produced ``v = 0`` would have gone out on the wire
        and shown the wrong colour with no warning anywhere.  Checking
        against the scraped table also means a change upstream surfaces as
        a failing test rather than as wrong colours on real lamps.

        Raises:
            ValueError: If a component lies outside its documented range.
        """
        for component, value in (("h", self.h), ("s", self.s), ("v", self.v)):
            bounds = COLOUR_COMPONENT_RANGES.get(component)
            if bounds is not None and not bounds[0] <= value <= bounds[1]:
                raise ValueError(
                    f"colour_value.{component}={value} is outside the documented range {bounds[0]}..{bounds[1]}"
                )
        return self


class SberValue(BaseModel):
    """A typed value in Sber state or command payload.

    Sber protocol uses tagged unions: the ``type`` field selects which
    ``*_value`` field carries the actual data.

    Per Sber C2C spec:
    - ``integer_value`` is always a **string** (e.g. ``"220"``, not ``220``)
    - ``colour_value`` is an HSV object with h/s/v integer fields
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["BOOL", "INTEGER", "FLOAT", "STRING", "ENUM", "COLOUR"]
    bool_value: bool | None = None
    integer_value: str | None = None
    float_value: float | None = None
    string_value: str | None = None
    enum_value: str | None = None
    colour_value: SberColourValue | None = None

    @model_validator(mode="after")
    def payload_field_matches_type(self) -> SberValue:
        """Reject a payload carried under a key that does not fit ``type``.

        ``extra="forbid"`` only stops *invented* keys; every ``*_value``
        field is declared here, so ``{"type": "ENUM", "integer_value":
        "3"}`` used to validate cleanly and then be dropped by the cloud,
        which reads the field named by the type and nothing else.

        A value with **no** payload field is accepted on purpose: Sber
        serializes protobuf by proto3 rules, where a field holding its
        type's default is omitted, so ``{"type": "BOOL"}`` is a legitimate
        ``false`` — see :func:`normalize_sber_value` and issue #44.

        Raises:
            ValueError: If a payload field of another type is set.
        """
        own = VALUE_FIELD_BY_TYPE.get(self.type)
        if own is None:
            return self
        foreign = sorted(
            field for field in VALUE_FIELD_BY_TYPE.values() if field != own and getattr(self, field, None) is not None
        )
        if foreign:
            raise ValueError(f"type {self.type!r} must carry {own!r}, got {', '.join(foreign)}")
        return self


class SberState(BaseModel):
    """Single state key-value pair in the Sber protocol."""

    model_config = ConfigDict(extra="forbid")

    key: str
    value: SberValue

    @model_validator(mode="after")
    def check_feature_type_matches(self) -> SberState:
        """Reject states where the value type doesn't match the Sber spec for the key.

        Protects against silent Sber rejections like the PIR-as-BOOL bug:
        Sber expects ``pir`` as ``{"type": "ENUM", "enum_value": "pir"}``
        but a buggy device class could emit ``{"type": "BOOL", "bool_value": true}``
        — Sber would accept the payload and quietly drop the device.

        Uses :data:`FEATURE_TYPES` (auto-generated from Sber docs).  Unknown
        keys are allowed — not all features are in the generated catalog
        (typos / undocumented features are handled by compliance tests).
        """
        expected = FEATURE_TYPES.get(self.key)
        if expected is not None and self.value.type != expected:
            raise ValueError(f"Feature {self.key!r} must have type {expected!r}, got {self.value.type!r}")
        return self


# ---------------------------------------------------------------------------
# Allowed values (model descriptor)
# ---------------------------------------------------------------------------


class SberAllowedIntegerValues(BaseModel):
    """INTEGER allowed values with min/max/step as strings."""

    model_config = ConfigDict(extra="forbid")

    min: str
    max: str
    step: str


class SberAllowedFloatValues(BaseModel):
    """FLOAT allowed values with numeric min/max."""

    model_config = ConfigDict(extra="forbid")

    min: float
    max: float


class SberAllowedEnumValues(BaseModel):
    """ENUM allowed values with list of valid strings."""

    model_config = ConfigDict(extra="forbid")

    values: list[str]


class SberAllowedValue(BaseModel):
    """Single allowed_values entry for a feature.

    Type discriminator selects which ``*_values`` field is present.
    ``COLOUR`` type has no additional constraints — just ``{"type": "COLOUR"}``.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["INTEGER", "FLOAT", "ENUM", "COLOUR"]
    integer_values: SberAllowedIntegerValues | None = None
    float_values: SberAllowedFloatValues | None = None
    enum_values: SberAllowedEnumValues | None = None


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------


class SberDependencyCondition(BaseModel):
    """Single condition value in a dependency declaration."""

    model_config = ConfigDict(extra="forbid")

    type: str
    enum_value: str | None = None
    bool_value: bool | None = None


class SberDependency(BaseModel):
    """Feature dependency: feature X is available only when key Y has given values."""

    model_config = ConfigDict(extra="forbid")

    key: str
    values: list[SberDependencyCondition]


# ---------------------------------------------------------------------------
# Device descriptors
# ---------------------------------------------------------------------------


class SberDeviceModel(BaseModel):
    """Device model descriptor within a Sber device config.

    Per Sber spec, ``allowed_values`` should only contain keys that are
    in ``features`` and need non-default ranges.  Extra keys cause silent
    device rejection.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    manufacturer: str = "Unknown"
    model: str = "Unknown"
    description: str = ""
    category: str
    features: list[str]
    hw_version: str | None = None
    sw_version: str | None = None
    allowed_values: dict[str, SberAllowedValue] | None = None
    dependencies: dict[str, SberDependency] | None = None

    @field_validator("features")
    @classmethod
    def must_have_online(cls, v: list[str]) -> list[str]:
        """All Sber devices must include 'online' feature (VR-010)."""
        if "online" not in v:
            raise ValueError("'online' must be in features (VR-010)")
        return v

    @field_validator("allowed_values")
    @classmethod
    def allowed_values_keys_must_be_known(
        cls, v: dict[str, SberAllowedValue] | None, info: Any
    ) -> dict[str, SberAllowedValue] | None:
        """allowed_values keys must be subset of features (TV bug prevention)."""
        if v is None:
            return v
        features = info.data.get("features", [])
        extra_keys = set(v.keys()) - set(features)
        if extra_keys:
            raise ValueError(f"allowed_values contains keys not in features: {extra_keys}")
        return v

    @field_validator("allowed_values")
    @classmethod
    def allowed_enum_values_must_be_documented(
        cls, v: dict[str, SberAllowedValue] | None
    ) -> dict[str, SberAllowedValue] | None:
        """Reject ENUM ``allowed_values`` offering values Sber does not document.

        The keys check above only asks *which* features carry limits; it
        says nothing about the limits themselves, so a made-up vocabulary
        (``source: ["HDMI 1", "Станция"]`` instead of ``["hdmi1", "tv"]``)
        passed the gate untouched.  It is not a cosmetic error: the app
        renders exactly what is declared and sends the same string back as
        a command, so every such entry is a control that cannot work — and
        Sber may reject the whole device over it.  This is the class of
        defect that had to be fixed by hand in 1.49.0.

        Checked against :data:`FEATURE_ENUM_VALUES` (the function's own
        page, not a category example).  A feature absent from that table
        has no known vocabulary and is skipped — absent means *unknown*,
        never *nothing allowed*.
        """
        if v is None:
            return v
        for key, spec in v.items():
            vocabulary = FEATURE_ENUM_VALUES.get(key)
            if not vocabulary or spec.enum_values is None:
                continue
            unknown = sorted(set(spec.enum_values.values) - vocabulary)
            if unknown:
                raise ValueError(
                    f"allowed_values[{key!r}] offers values Sber does not document: "
                    f"{unknown}; documented values: {sorted(vocabulary)}"
                )
        return v


class SberDevice(BaseModel):
    """Full device descriptor for Sber config publish.

    Per Sber spec (VR-001), ``model_id`` and ``model`` are mutually exclusive.
    This integration always uses inline ``model``; ``model_id`` is not emitted.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    default_name: str | None = None
    room: str = ""
    home: str | None = None
    model: SberDeviceModel
    hw_version: str = "1"
    sw_version: str = "1"
    parent_id: str | None = None
    nicknames: list[str] | None = None
    groups: list[str] | None = None
    partner_meta: dict[str, Any] | None = None

    @field_validator("partner_meta")
    @classmethod
    def partner_meta_max_size(cls, v: dict | None) -> dict | None:
        """Enforce the ``partner_meta`` size limit Sber documents (VR-003).

        The budget comes from :data:`PARTNER_META_MAX_CHARS`, which is
        scraped from the ``device`` page rather than typed in here.  When
        the scrape could not read it the value is ``None`` and the check is
        skipped — unknown never means unlimited, but a validator is the
        wrong place to guess a number the documentation did not give.

        Raises:
            ValueError: If the JSON form exceeds the documented budget.
        """
        if PARTNER_META_MAX_CHARS is None or v is None:
            return v
        size = len(json.dumps(v))
        if size > PARTNER_META_MAX_CHARS:
            raise ValueError(f"partner_meta JSON is {size} chars, limit is {PARTNER_META_MAX_CHARS} (VR-003)")
        return v


# ---------------------------------------------------------------------------
# MQTT payloads
# ---------------------------------------------------------------------------


class SberDeviceState(BaseModel):
    """Current state of a single device."""

    model_config = ConfigDict(extra="forbid")

    states: list[SberState]


class SberConfigPayload(BaseModel):
    """Config publish payload (``up/config`` topic)."""

    model_config = ConfigDict(extra="forbid")

    devices: list[SberDevice]


class SberStatusPayload(BaseModel):
    """Status publish payload (``up/status`` topic)."""

    model_config = ConfigDict(extra="forbid")

    devices: dict[str, SberDeviceState]


class SberCommandPayload(BaseModel):
    """Incoming command payload from Sber cloud (``down/commands`` topic)."""

    model_config = ConfigDict(extra="forbid")

    devices: dict[str, SberDeviceState]


# ---------------------------------------------------------------------------
# Helper constructors
# ---------------------------------------------------------------------------


_PROTO3_VALUE_DEFAULTS: dict[str, tuple[str, Any]] = {
    "BOOL": ("bool_value", False),
    "INTEGER": ("integer_value", "0"),
    "FLOAT": ("float_value", 0.0),
    "STRING": ("string_value", ""),
    "ENUM": ("enum_value", ""),
}
"""Per-type default injected when the typed field is omitted (proto3 rules)."""


def normalize_sber_value(value: dict[str, Any]) -> dict[str, Any]:
    """Fill in typed fields omitted by proto3 default-value elision.

    Sber cloud serializes protobuf to JSON per proto3 rules: a field
    holding its type's default value is **omitted** from the payload.
    A command carrying ``0`` arrives as ``{"type": "INTEGER"}`` with no
    ``integer_value`` key, ``false`` arrives without ``bool_value``, and
    zero HSV components are dropped from ``colour_value`` (issue #44 —
    the colour-temperature slider at its edge produced a command the
    bridge silently ignored).

    Args:
        value: Raw Sber value dict from a command payload.

    Returns:
        The same dict if already complete, otherwise a shallow copy with
        the type's default injected.  Payloads without a known ``type``
        are returned unchanged.  The input is never mutated.
    """
    vtype = value.get("type")
    typed = _PROTO3_VALUE_DEFAULTS.get(vtype or "")
    if typed is not None:
        field, default = typed
        if field not in value:
            return {**value, field: default}
        return value
    if vtype == "COLOUR":
        colour = value.get("colour_value") or {}
        if all(k in colour for k in ("h", "s", "v")):
            return value
        filled = {"h": 0, "s": 0, "v": 0, **colour}
        return {**value, "colour_value": filled}
    return value


def make_bool_value(value: bool) -> dict[str, Any]:
    """Create a Sber BOOL value dict.

    Args:
        value: Boolean value.

    Returns:
        Dict ready for inclusion in a Sber state payload.
    """
    return {"type": "BOOL", "bool_value": value}


def make_integer_value(value: int) -> dict[str, Any]:
    """Create a Sber INTEGER value dict.

    Per Sber C2C specification, ``integer_value`` is serialized as a string.

    Args:
        value: Integer value.

    Returns:
        Dict ready for inclusion in a Sber state payload.
    """
    return {"type": "INTEGER", "integer_value": str(value)}


def make_enum_value(value: str) -> dict[str, Any]:
    """Create a Sber ENUM value dict.

    Args:
        value: Enum string value.

    Returns:
        Dict ready for inclusion in a Sber state payload.
    """
    return {"type": "ENUM", "enum_value": value}


def make_colour_value(h: int, s: int, v: int) -> dict[str, Any]:
    """Create a Sber COLOUR value dict.

    Args:
        h: Hue component (0-360).
        s: Saturation component (0-1000).
        v: Value/brightness component (100-1000).

    Returns:
        Dict ready for inclusion in a Sber state payload.
    """
    return {"type": "COLOUR", "colour_value": {"h": h, "s": s, "v": v}}


def make_float_value(value: float) -> dict[str, Any]:
    """Create a Sber FLOAT value dict.

    ``float_value`` travels as a JSON **number** — unlike
    ``integer_value``, which Sber documents as a quoted string (see
    :data:`~._generated.value_envelope.VALUE_FIELD_JSON_TYPES`).

    Args:
        value: Finite numeric value.

    Returns:
        Dict ready for inclusion in a Sber state payload.

    Raises:
        ValueError: If ``value`` is not a finite number.  ``nan`` and
            ``inf`` are Python extensions to JSON, and one of them in a
            payload costs the whole ``up/status`` message, not just the
            device that produced it.
    """
    try:
        number = float(value)
    except (TypeError, ValueError) as err:
        raise ValueError(f"float_value must be a number, got {value!r}") from err
    if not math.isfinite(number):
        raise ValueError(f"float_value must be finite, got {value!r}")
    return {"type": "FLOAT", "float_value": number}


def make_string_value(value: str) -> dict[str, Any]:
    """Create a Sber STRING value dict.

    Args:
        value: String value.

    Returns:
        Dict ready for inclusion in a Sber state payload.
    """
    return {"type": "STRING", "string_value": str(value)}


def _as_int(raw: Any) -> int:
    """Coerce a raw Python value into the integer Sber's INTEGER carries.

    Args:
        raw: Value produced by a device class (``int``, ``float``, ``bool``
            or a numeric string such as ``"22.5"``).

    Returns:
        The value as an ``int``; fractional input is truncated the same
        way ``devices/base_entity._safe_int_parser`` truncates it.

    Raises:
        ValueError: If ``raw`` is not numeric or is not finite.
    """
    if isinstance(raw, bool):
        return int(raw)
    if isinstance(raw, int):
        return raw
    try:
        number = float(raw)
    except (TypeError, ValueError) as err:
        raise ValueError(f"INTEGER value must be numeric, got {raw!r}") from err
    if not math.isfinite(number):
        raise ValueError(f"INTEGER value must be finite, got {raw!r}")
    return int(number)


def _as_colour(raw: Any) -> dict[str, Any]:
    """Coerce a raw Python value into a Sber COLOUR value dict.

    Args:
        raw: Either a mapping with ``h``/``s``/``v`` keys or a three-item
            sequence in that order.

    Returns:
        Dict ready for inclusion in a Sber state payload.

    Raises:
        ValueError: If ``raw`` is neither shape, or a component is not
            numeric.
    """
    if isinstance(raw, dict):
        missing = sorted({"h", "s", "v"} - set(raw))
        if missing:
            raise ValueError(f"COLOUR value is missing {missing}, got {raw!r}")
        return make_colour_value(_as_int(raw["h"]), _as_int(raw["s"]), _as_int(raw["v"]))
    if isinstance(raw, list | tuple) and len(raw) == 3:
        return make_colour_value(*(_as_int(component) for component in raw))
    raise ValueError(f"COLOUR value must be an h/s/v mapping or a 3-item sequence, got {raw!r}")


_VALUE_BUILDERS: dict[str, Callable[[Any], dict[str, Any]]] = {
    "BOOL": lambda raw: make_bool_value(bool(raw)),
    "INTEGER": lambda raw: make_integer_value(_as_int(raw)),
    "FLOAT": make_float_value,
    "STRING": lambda raw: make_string_value(str(raw)),
    "ENUM": lambda raw: make_enum_value(str(raw)),
    "COLOUR": _as_colour,
}
"""Sber value type → the constructor that wraps a raw value in it.

One entry per key of
:data:`~._generated.value_envelope.VALUE_FIELD_BY_TYPE`; the coverage is
asserted by ``tests/hacs/test_sber_models_value_shape.py`` so a new type
appearing in the documentation cannot stay unimplemented."""


_VALUE_TYPE_FAMILY: dict[str, str] = {
    "INTEGER": "number",
    "FLOAT": "number",
    "STRING": "text",
    "ENUM": "text",
    "BOOL": "bool",
    "COLOUR": "colour",
}
"""Value type → the family whose payload can be re-wrapped losslessly.

Used only by :func:`make_state` to decide whether a mistyped value can be
salvaged.  ``INTEGER`` and ``FLOAT`` carry the same number, ``ENUM`` and
``STRING`` the same characters; everything else would have to be invented
(a ``BOOL`` has no meaningful ENUM spelling), and inventing it would ship
a plausible-looking wrong value instead of a loud complaint."""


def make_typed_value(value_type: str, raw: Any) -> dict[str, Any]:
    """Wrap a raw Python value in the envelope of a given Sber type.

    Args:
        value_type: One of the types Sber documents for ``value.type``.
        raw: Value to carry.

    Returns:
        Dict with ``type`` and exactly the payload key that type owns.

    Raises:
        ValueError: If the type is unknown or ``raw`` does not fit it.
    """
    builder = _VALUE_BUILDERS.get(str(value_type))
    if builder is None:
        raise ValueError(f"unknown Sber value type {value_type!r}; known: {sorted(_VALUE_BUILDERS)}")
    return builder(raw)


def make_value_for(feature: str, raw: Any) -> dict[str, Any]:
    """Build the value for a feature using the type Sber documents for it.

    This is the constructor device classes should reach for.  Picking the
    envelope by hand is how ``kitchen_water_level`` — a documented FLOAT —
    ended up published as an INTEGER for two years: the mistake is
    invisible in review, passes every schema check the bridge had, and
    the cloud simply never shows the value.

    Args:
        feature: Sber feature key (``SberFeature`` members work as-is).
        raw: Plain Python value: ``bool`` for BOOL, a number for
            INTEGER/FLOAT, a string for ENUM/STRING, an ``h``/``s``/``v``
            mapping or triple for COLOUR.

    Returns:
        Dict ready for inclusion in a Sber state payload.

    Raises:
        ValueError: If the feature is absent from
            :data:`~._generated.feature_types.FEATURE_TYPES` — an
            undocumented key has no documented type, so the caller must
            build the value explicitly — or if ``raw`` does not fit the
            documented type.
    """
    documented = FEATURE_TYPES.get(str(feature))
    if documented is None:
        raise ValueError(
            f"feature {str(feature)!r} is not in the documented catalogue — "
            "build its value with an explicit make_*_value() call"
        )
    return make_typed_value(documented, raw)


def _conform_to_documented_type(key: str, documented: str, value: dict[str, Any]) -> dict[str, Any]:
    """Re-wrap a value built under the wrong type, or complain loudly.

    Args:
        key: Feature key the value belongs to.
        documented: Type Sber documents for that feature.
        value: Value dict as the device class built it.

    Returns:
        The value unchanged when it already matches the documentation or
        cannot be salvaged; otherwise the same payload re-wrapped in the
        documented envelope.
    """
    declared = str(value.get("type"))
    if declared == documented:
        return value
    field = VALUE_FIELD_BY_TYPE.get(declared)
    same_family = _VALUE_TYPE_FAMILY.get(declared) == _VALUE_TYPE_FAMILY.get(documented)
    if field is not None and field in value and same_family:
        try:
            recast = make_typed_value(documented, value[field])
        except ValueError:
            recast = None
        if recast is not None:
            _LOGGER.error(
                "Feature %r is documented as %s but was built as %s; republishing it as %s. "
                "Fix the device class to use make_value_for(%r, …)",
                key,
                documented,
                declared,
                documented,
                key,
            )
            return recast
    _LOGGER.error(
        "Feature %r is documented as %s but was built as %s and cannot be converted; "
        "Sber will drop this value silently",
        key,
        documented,
        declared,
    )
    return value


def make_state(key: str, value: dict[str, Any]) -> dict[str, Any]:
    """Create a Sber state entry dict.

    Every device class funnels its states through here, which makes it
    the one place where a value can be checked against the type its
    feature is documented with.  A mismatch is repaired when the payload
    allows it (INTEGER ↔ FLOAT, ENUM ↔ STRING) and logged at ``ERROR``
    either way: the wire form stays correct, and the mistake stops being
    the kind that only shows up as "the cloud does not display this
    value".

    Args:
        key: State key name.
        value: Typed value dict (from :func:`make_value_for` or the
            ``make_*_value`` helpers).

    Returns:
        Dict with ``key`` and ``value`` keys.
    """
    documented = FEATURE_TYPES.get(str(key))
    if documented is not None and isinstance(value, dict):
        value = _conform_to_documented_type(str(key), documented, value)
    return {"key": key, "value": value}


def make_state_for(key: str, raw: Any) -> dict[str, Any]:
    """Create a Sber state entry, choosing the value type from the docs.

    Shorthand for ``make_state(key, make_value_for(key, raw))`` — the
    form that leaves a device class with nothing to get wrong.

    Args:
        key: Sber feature key (``SberFeature`` members work as-is).
        raw: Plain Python value; see :func:`make_value_for`.

    Returns:
        Dict with ``key`` and ``value`` keys.

    Raises:
        ValueError: If the feature is undocumented or ``raw`` does not fit
            its documented type.
    """
    return {"key": key, "value": make_value_for(key, raw)}


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def validate_device(device_data: dict[str, Any]) -> tuple[bool, str]:
    """Validate a single device dict against SberDevice schema.

    Args:
        device_data: Raw device dict from ``to_sber_state()``.

    Returns:
        Tuple ``(valid, error_message)``.  ``error_message`` is empty on success.
    """
    try:
        SberDevice.model_validate(device_data)
    except (ValueError, TypeError) as exc:
        return False, str(exc)[:500]
    return True, ""


def validate_config_payload(data: dict[str, Any]) -> bool:
    """Validate a config payload dict against the SberConfigPayload schema.

    This is an optional validation step — failures are logged as warnings
    but do not prevent publishing (the raw dict is still valid JSON).

    Args:
        data: Raw dict to validate.

    Returns:
        True if validation passed, False otherwise.
    """
    try:
        SberConfigPayload.model_validate(data)
    except (ValueError, TypeError):
        _LOGGER.warning("Config payload validation failed", exc_info=True)
        return False
    return True


def validate_status_payload(data: dict[str, Any]) -> bool:
    """Validate a status payload dict against the SberStatusPayload schema.

    Args:
        data: Raw dict to validate.

    Returns:
        True if validation passed, False otherwise.
    """
    try:
        SberStatusPayload.model_validate(data)
    except (ValueError, TypeError):
        _LOGGER.warning("Status payload validation failed", exc_info=True)
        return False
    return True


# ---------------------------------------------------------------------------
# Category compliance validation (Context7-verified per Sber C2C docs)
# ---------------------------------------------------------------------------

# Categories where the HA integration model differs from Sber's combo
# reference device.  Keep this list minimal and well-justified.
_CATEGORY_OBLIGATORY_OVERRIDES: dict[str, frozenset[str]] = {
    # Sber's sensor_temp reference is a combo temperature+humidity device
    # (both marked ✔︎).  HA models temperature and humidity as separate
    # sensor entities — neither carries the other's value on its own.
    # Users who want Sber-combo semantics can link a humidity sensor to
    # the temperature sensor via the panel linking UI.  Until then the
    # single-value device must be considered compliant.
    "sensor_temp": frozenset({"online"}),
}
"""Per-category overrides for :data:`CATEGORY_OBLIGATORY_FEATURES`.

Used only when HA's entity model is architecturally incompatible with
Sber's reference combo device.  Adding entries here is a trade-off:
Sber may silently reject devices that miss features they mark ✔︎.
"""


def _effective_obligatory_features(category: str) -> frozenset[str] | None:
    """Return obligatory set for category, honouring overrides."""
    if category in _CATEGORY_OBLIGATORY_OVERRIDES:
        return _CATEGORY_OBLIGATORY_OVERRIDES[category]
    return CATEGORY_OBLIGATORY_FEATURES.get(category)


# Single source of truth for "what features must a device in this category
# emit": :data:`CATEGORY_OBLIGATORY_FEATURES`, auto-generated from the
# ``✔︎`` markers in Sber's "Доступные функции устройства" table (see
# ``tools/fetch_sber_schemas.py`` + ``tools/codegen.py``).  Overrides above
# loosen the set for categories where HA's entity model does not match
# Sber's combo reference device.
CATEGORY_REQUIRED_FEATURES: dict[str, frozenset[str]] = {
    cat: _CATEGORY_OBLIGATORY_OVERRIDES.get(cat, obligatory) for cat, obligatory in CATEGORY_OBLIGATORY_FEATURES.items()
}
"""Required features per Sber category.

Derived from :data:`CATEGORY_OBLIGATORY_FEATURES` with the
``_CATEGORY_OBLIGATORY_OVERRIDES`` applied.  Kept as the public name for
backward compatibility — callers should continue using this constant."""


def missing_obligatory_features(category: str, features: set[str]) -> set[str]:
    """Return obligatory features missing from the emitted set.

    Uses :data:`CATEGORY_OBLIGATORY_FEATURES` (auto-generated from Sber
    docs ``✔︎`` markers).  Missing obligatory features are a likely
    cause of silent device rejection by Sber cloud.

    Args:
        category: Sber category slug.
        features: Features our device would emit.

    Returns:
        Set of obligatory features absent from ``features``.  Empty set
        for unknown categories (fail-open — we don't block unknown cats).
    """
    obligatory = _effective_obligatory_features(category)
    if obligatory is None:
        return set()
    return obligatory - set(features)


def unknown_features_for_category(category: str, features: set[str]) -> set[str]:
    """Return features not present in Sber's reference model for the category.

    Uses :data:`CATEGORY_REFERENCE_FEATURES` (auto-generated).  Unknown
    categories (not in our registry) return empty set — validation falls
    back to general schema rules.

    Args:
        category: Sber category slug.
        features: Features our device would emit.
    """
    reference = CATEGORY_REFERENCE_FEATURES.get(category)
    if reference is None:
        return set()
    return set(features) - reference


def validate_category_compliance(device: dict[str, Any]) -> list[str]:
    """Check a device descriptor for Sber category-specific violations.

    Returns a list of human-readable violation messages (empty = compliant).
    Does NOT raise — callers decide how to handle violations.

    Args:
        device: Raw device dict (already passed SberDevice schema validation).
    """
    violations: list[str] = []
    model = device.get("model", {})
    category = model.get("category", "")
    features = set(model.get("features", []))

    # VR-010..VR-016: required features per category
    required = CATEGORY_REQUIRED_FEATURES.get(category)
    if required is not None:
        missing = required - features
        if missing:
            violations.append(f"Missing required features for {category}: {missing}")

    # TV bug prevention: allowed_values keys must be subset of features
    allowed_values = model.get("allowed_values") or {}
    extra_av = set(allowed_values.keys()) - features
    if extra_av:
        violations.append(f"allowed_values contains keys not in features: {extra_av}")

    return violations
