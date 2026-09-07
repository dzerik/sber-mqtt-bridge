#!/usr/bin/env python3
# ruff: noqa: T201
"""Generate Sber-derived Python modules from the unified spec artifact.

Reads ``tests/hacs/__snapshots__/sber_full_spec.json`` and writes the
modules under ``custom_components/sber_mqtt_bridge/_generated/``:

- ``feature_types.py``  — ``FEATURE_TYPES: dict[str, str]``
  (feature name → Sber value type)
- ``category_features.py`` — ``CATEGORY_REFERENCE_FEATURES:
  dict[str, frozenset[str]]`` (all features Sber lists per category)
- ``usage_modes.py`` — ``FEATURE_USAGE_MODES`` plus the three sets it
  partitions into (command-only, event-only, state-bearing), taken from
  the "Способ использования" line of each function page
- ``value_envelope.py`` — the shape of a ``value`` object: which payload
  key each type uses, the JSON type of each key, the HSV bounds, and the
  types ``allowed_values`` may be declared for
- ``protocol_limits.py`` — required fields of ``model`` / ``device`` /
  ``state``, the 1024-character ``partner_meta`` cap, and Sber's error
  codes
- ``narrowing.py`` — whether a model may narrow a feature's allowed
  values, and how
- ``feature_labels.py`` — Sber's own Russian labels for features and
  ENUM values
- ``__init__.py`` — re-exports + spec provenance constants

The last four are generated from the ``structures`` / ``protocol``
sections of the spec.  Those sections are optional: a spec fetched
before they existed still generates, with the affected tables empty.
Empty always means *unknown*, never *unconstrained*.

Safety guarantees:

1. **Generated files are committed** — runtime never reads the JSON
   spec, only the committed ``.py`` modules.  Portal outages, spec
   corruption, or scraper bugs cannot break the production bridge.
2. **Atomic writes** — we write to a temp file in the same directory
   and ``os.replace`` into place, so interrupted codegen can never
   leave half-written files.
3. **Strict spec validation** — before any write, we validate the
   input structure.  On malformed spec, we abort with a clear error
   and leave committed files untouched.
4. **``--check`` mode** — CI runs codegen into a temp dir and diffs
   against committed files.  A mismatch fails the build without
   touching anything.
5. **No surprising deletions** — we only generate the modules listed
   above, never clean up unrelated files under ``_generated/``.

Usage:
    python tools/codegen.py          # regenerate, overwrite committed files
    python tools/codegen.py --check  # CI mode: exit 1 if out of date
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from textwrap import dedent
from typing import Any

SPEC_FILE = Path(__file__).parent.parent / "tests" / "hacs" / "__snapshots__" / "sber_full_spec.json"
OUTPUT_DIR = Path(__file__).parent.parent / "custom_components" / "sber_mqtt_bridge" / "_generated"

VALID_TYPES = frozenset({"BOOL", "INTEGER", "FLOAT", "STRING", "ENUM", "COLOUR"})

HEADER = '''"""AUTO-GENERATED from tests/hacs/__snapshots__/sber_full_spec.json.

DO NOT EDIT BY HAND.  Regenerate with:

    python tools/codegen.py

Source: {source}
Spec generated at: {generated_at}
"""

from __future__ import annotations
'''


# ---------------------------------------------------------------------------
# Spec loading + validation
# ---------------------------------------------------------------------------


class SpecValidationError(RuntimeError):
    """Spec structure is malformed — refuse to generate."""


def load_spec(path: Path) -> dict[str, Any]:
    """Load and validate the unified Sber spec."""
    if not path.exists():
        raise SpecValidationError(f"Spec file missing: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SpecValidationError(f"Spec is not valid JSON: {exc}") from exc

    for key in ("source", "generated_at", "categories", "functions"):
        if key not in data:
            raise SpecValidationError(f"Spec missing required top-level key: {key!r}")

    if not isinstance(data["functions"], dict) or not data["functions"]:
        raise SpecValidationError("Spec 'functions' must be a non-empty dict")
    if not isinstance(data["categories"], dict) or not data["categories"]:
        raise SpecValidationError("Spec 'categories' must be a non-empty dict")

    for name, spec in data["functions"].items():
        ftype = spec.get("type")
        if ftype not in VALID_TYPES:
            raise SpecValidationError(
                f"Function {name!r} has invalid type {ftype!r} (expected one of {sorted(VALID_TYPES)})"
            )

    for category, schema in data["categories"].items():
        features = schema.get("features")
        if not isinstance(features, list):
            raise SpecValidationError(f"Category {category!r} features must be a list, got {type(features)}")

    # ``structures`` / ``protocol`` are newer than the rest of the spec and
    # deliberately optional, but a *malformed* one must abort rather than
    # quietly generate an empty limits table that reads as "no limit".
    for key in ("structures", "protocol"):
        if key in data and not isinstance(data[key], dict):
            raise SpecValidationError(f"Spec {key!r} must be a dict, got {type(data[key])}")

    return data


# ---------------------------------------------------------------------------
# Module generators (pure functions — return file content, don't write)
# ---------------------------------------------------------------------------


def render_feature_types(spec: dict) -> str:
    """Render feature_types.py content."""
    header = HEADER.format(source=spec["source"], generated_at=spec["generated_at"]).rstrip()
    functions = spec["functions"]
    lines = [header, "", "FEATURE_TYPES: dict[str, str] = {"]
    for name in sorted(functions):
        ftype = functions[name]["type"]
        lines.append(f'    "{name}": "{ftype}",')
    lines.append("}")
    lines.append('"""Feature name → Sber value type. Source: developers.sber.ru/docs/ru/smarthome/c2c/functions."""')
    lines.append("")
    return "\n".join(lines)


def render_category_features(spec: dict) -> str:
    """Render category_features.py content."""
    header = HEADER.format(source=spec["source"], generated_at=spec["generated_at"]).rstrip()
    categories = spec["categories"]
    lines = [header, "", "CATEGORY_REFERENCE_FEATURES: dict[str, frozenset[str]] = {"]
    for category in sorted(categories):
        # all_features prefers table-extracted full list (superset of
        # the reference model example).  Fallback to features if table
        # scraping failed for a page.
        features = sorted(categories[category].get("all_features") or categories[category].get("features", []))
        if features:
            formatted = ", ".join(f'"{f}"' for f in features)
            lines.append(f'    "{category}": frozenset({{{formatted}}}),')
        else:
            lines.append(f'    "{category}": frozenset(),')
    lines.append("}")
    lines.append(
        dedent(
            '''"""All features declared for each category in Sber docs.

Source: the "Доступные функции устройства" table on each category
page plus the reference JSON example.  Use as the *widest* known-valid
feature set per category — features we emit outside this set are
unknown to Sber cloud and likely cause silent rejection (see the
TV ``allowed_values`` bug that motivated this module)."""
            ''',
        ).strip()
    )
    lines.append("")
    return "\n".join(lines)


def render_obligatory_features(spec: dict) -> str:
    """Render obligatory_features.py content."""
    header = HEADER.format(source=spec["source"], generated_at=spec["generated_at"]).rstrip()
    categories = spec["categories"]
    lines = [header, "", "CATEGORY_OBLIGATORY_FEATURES: dict[str, frozenset[str]] = {"]
    for category in sorted(categories):
        obligatory = sorted(categories[category].get("obligatory", []))
        if obligatory:
            formatted = ", ".join(f'"{f}"' for f in obligatory)
            lines.append(f'    "{category}": frozenset({{{formatted}}}),')
        else:
            lines.append(f'    "{category}": frozenset(),')
    lines.append("}")
    lines.append(
        dedent(
            '''"""Features marked obligatory (``✔︎``) in Sber docs per category.

Extracted from the "Доступные функции устройства" table on each
category page.  These are the features every device of this category
MUST emit to be accepted by Sber cloud — emitting fewer is a likely
cause of silent rejection."""
            ''',
        ).strip()
    )
    lines.append("")
    return "\n".join(lines)


def render_conditional_features(spec: dict) -> str:
    """Render conditional_features.py content."""
    header = HEADER.format(source=spec["source"], generated_at=spec["generated_at"]).rstrip()
    categories = spec["categories"]
    lines = [header, "", "CATEGORY_CONDITIONAL_FEATURES: dict[str, frozenset[str]] = {"]
    for category in sorted(categories):
        conditional = sorted(categories[category].get("conditional", []))
        if conditional:
            formatted = ", ".join(f'"{f}"' for f in conditional)
            lines.append(f'    "{category}": frozenset({{{formatted}}}),')
    lines.append("}")
    lines.append(
        dedent(
            '''"""Features marked conditionally obligatory (``✔︎*``) per category.

Sber footnotes these as "at least one of" groups: a gate must describe
*some* way to open (``open_percentage`` or ``open_set`` or both), an air
sensor must report *some* measurement.  Declaring none of them is as
fatal as omitting a strictly obligatory feature — the cloud drops the
device — yet the strict :data:`CATEGORY_OBLIGATORY_FEATURES` table
cannot express it, which is why this second table exists.

Only categories that actually carry a group are listed; the absence of
a key means "no conditional group", not "empty group".

The check belongs on the device's **declared features**, not on a state
payload: command-only members such as ``open_set`` hold no state and
never appear in a publish (see the Sber page for ``open_set``: "Не
хранит состояние устройства")."""
            ''',
        ).strip()
    )
    lines.append("")
    return "\n".join(lines)


def _parse_range(raw: str) -> tuple[float, float] | None:
    """Turn a documented ``"min, max"`` range into a pair of numbers.

    Args:
        raw: Range string exactly as the function page words it.

    Returns:
        ``(min, max)`` or ``None`` when the string is not a plain pair —
        an unparsable range must disable the check, never guess a bound.
    """
    parts = [p.strip() for p in str(raw).split(",")]
    if len(parts) != 2:
        return None
    try:
        low, high = float(parts[0]), float(parts[1])
    except ValueError:
        return None
    return (low, high) if low <= high else None


def render_reference_values(spec: dict) -> str:
    """Render reference_values.py content."""
    header = HEADER.format(source=spec["source"], generated_at=spec["generated_at"]).rstrip()
    functions = spec["functions"]

    lines = [header, "", "FEATURE_ENUM_VALUES: dict[str, frozenset[str]] = {"]
    for name in sorted(functions):
        values = functions[name].get("enum_values")
        if values:
            formatted = ", ".join(f'"{v}"' for v in sorted(values))
            lines.append(f'    "{name}": frozenset({{{formatted}}}),')
    lines.append("}")
    lines.append(
        dedent(
            '''"""Every value an ENUM feature accepts, per the function\'s own page.

This is the authoritative vocabulary, and deliberately NOT the
``allowed_values`` block of a category page: that block is an
illustrative example and is routinely shorter.  ``hvac_air_flow_power``
is the proof — its category examples omit ``quiet``, which the function
page lists and real air purifiers use, so validating against the example
would reject correct devices.

A feature absent from this table has no known vocabulary (every
non-ENUM one, plus the two command-only ENUMs whose pages word things
differently).  Absent means *unknown*, never *nothing allowed* — callers
must skip the check rather than reject."""
            ''',
        ).strip()
    )

    lines += ["", "", "FEATURE_RANGES: dict[str, tuple[float, float]] = {"]
    for name in sorted(functions):
        raw = functions[name].get("range")
        if not raw:
            continue
        bounds = _parse_range(raw)
        if bounds is None:
            continue
        low, high = bounds
        lines.append(f'    "{name}": ({low!r}, {high!r}),')
    lines.append("}")
    lines.append(
        dedent(
            '''"""Documented numeric bounds of a feature, inclusive.

Sber states these on the function page ("Тип данных: INTEGER(0, 100)").
A value outside the range is not something the cloud is promised to
handle, so publishing one is worth surfacing — but only as a warning:
the bound describes the *function*, and a device legitimately idling
below it (a socket reporting 0 W against a documented 10 W floor) is
common enough that an error would be noise."""
            ''',
        ).strip()
    )
    lines.append("")
    return "\n".join(lines)


USAGE_STATE_READ_WRITE = "state_read_write"
"""Usage mode: the feature holds state and Sber may change it."""

USAGE_STATE_READ_ONLY = "state_read_only"
"""Usage mode: the feature holds state but accepts no command."""

USAGE_COMMAND_ONLY = "command_only"
"""Usage mode: the feature carries no state, only accepts commands."""

USAGE_EVENT_ONLY = "event_only"
"""Usage mode: the feature notifies about an event and cannot be commanded."""

STATE_BEARING_USAGE_MODES = frozenset({USAGE_STATE_READ_WRITE, USAGE_STATE_READ_ONLY})
"""The two modes whose features do appear in a state publish."""


def _usage_names(functions: dict, *modes: str) -> list[str]:
    """Sorted names of every function classified into one of ``modes``."""
    wanted = frozenset(modes)
    return sorted(name for name, spec in functions.items() if spec.get("usage_mode") in wanted)


def _render_frozenset(name: str, values: list[str], doc: str) -> list[str]:
    """Render one ``NAME: frozenset[str] = frozenset({...})`` block + docstring."""
    formatted = ", ".join(f'"{v}"' for v in values)
    body = f"frozenset({{{formatted}}})" if values else "frozenset()"
    return ["", "", f"{name}: frozenset[str] = {body}", doc]


def render_usage_modes(spec: dict) -> str:
    """Render usage_modes.py content."""
    header = HEADER.format(source=spec["source"], generated_at=spec["generated_at"]).rstrip()
    functions = spec["functions"]

    lines = [header, "", "FEATURE_USAGE_MODES: dict[str, str] = {"]
    for name in sorted(functions):
        mode = functions[name].get("usage_mode")
        if mode:
            lines.append(f'    "{name}": "{mode}",')
    lines.append("}")
    lines.append(
        dedent(
            '''"""Feature name → what Sber says the feature is *for*.

Straight off the "Способ использования" line of each function page,
which words it in exactly four ways:

- ``state_read_write`` — "хранит состояние устройства и может менять его"
- ``state_read_only`` — "хранит состояние устройства, менять его не может"
- ``command_only`` — "не хранит состояние устройства, может менять его"
- ``event_only`` — "уведомляет о состоянии устройства, менять его не может"

A feature missing from this table has a wording the scraper did not
recognise — treat that as *unknown*, never as "no restriction"."""
            ''',
        ).strip()
    )

    lines += _render_frozenset(
        "COMMAND_ONLY_FEATURES",
        _usage_names(functions, USAGE_COMMAND_ONLY),
        dedent(
            '''"""Features that hold no state and exist only to accept a command.

``open_set`` is the archetype: a curtain must *declare* it, yet it can
never show up in a state publish because there is no state to report.
Any check that walks a publish looking for declared features has to
exempt this set, or it reports healthy devices as incomplete."""
            ''',
        ).strip(),
    )

    lines += _render_frozenset(
        "EVENT_ONLY_FEATURES",
        _usage_names(functions, USAGE_EVENT_ONLY),
        dedent(
            '''"""Features that only ever report that something *happened*.

Sber words these as "уведомляет о состоянии устройства": ``pir`` is
sent when motion is detected and silent otherwise, so silence is the
quiet state rather than a missing value (issue #61)."""
            ''',
        ).strip(),
    )

    lines += _render_frozenset(
        "STATE_BEARING_FEATURES",
        _usage_names(functions, *sorted(STATE_BEARING_USAGE_MODES)),
        dedent(
            '''"""Features that do carry device state, readable or writable.

The complement of :data:`COMMAND_ONLY_FEATURES` and
:data:`EVENT_ONLY_FEATURES` among the classified functions — these are
the only ones a state publish can legitimately be asked to contain."""
            ''',
        ).strip(),
    )
    lines.append("")
    return "\n".join(lines)


def _protocol(spec: dict) -> dict:
    """Normative constants distilled from the structure pages (may be empty)."""
    protocol = spec.get("protocol")
    return protocol if isinstance(protocol, dict) else {}


def _structure_fields(spec: dict, structure: str) -> dict[str, dict]:
    """Field table of one structure page, or ``{}`` when it was not scraped."""
    structures = spec.get("structures")
    if not isinstance(structures, dict):
        return {}
    fields = (structures.get(structure) or {}).get("fields")
    return fields if isinstance(fields, dict) else {}


def _field_names(fields: dict[str, dict], flag: str) -> list[str]:
    """Sorted field names whose ``flag`` (``obligatory``/``conditional``) is set."""
    return sorted(name for name, meta in fields.items() if meta.get(flag))


def render_value_envelope(spec: dict) -> str:
    """Render value_envelope.py content."""
    header = HEADER.format(source=spec["source"], generated_at=spec["generated_at"]).rstrip()
    protocol = _protocol(spec)
    value_types = list(protocol.get("value_types") or ())
    field_types: dict[str, str] = dict(protocol.get("value_field_types") or {})
    # "INTEGER" → "integer_value": derived from the field names the page
    # itself lists, never from a hardcoded table, so a renamed field shows
    # up as a missing entry instead of a wrong one.
    field_by_type = {
        name.removesuffix("_value").upper(): name
        for name in sorted(field_types)
        if name.removesuffix("_value").upper() in value_types
    }
    colour = {k: tuple(v) for k, v in sorted((protocol.get("colour_ranges") or {}).items())}
    allowed_types = list(protocol.get("allowed_values_types") or ())

    lines = [header, ""]
    lines += [
        f"VALUE_TYPES: frozenset[str] = frozenset({{{', '.join(repr(t) for t in sorted(value_types))}}})"
        if value_types
        else "VALUE_TYPES: frozenset[str] = frozenset()",
        dedent(
            '''"""Every value type the ``value`` structure may declare.

Source: the ``type`` row of
developers.sber.ru/docs/ru/smarthome/c2c/value — "Может
принимать значение: FLOAT, INTEGER, STRING, BOOL, ENUM,
COLOUR"."""
'''
        ).strip(),
        "",
        "",
        "VALUE_FIELD_BY_TYPE: dict[str, str] = {",
        *(f'    "{t}": "{f}",' for t, f in sorted(field_by_type.items())),
        "}",
        dedent(
            '''"""Value type → the payload key that carries it.

A ``value`` object holds exactly two keys: ``type`` and the one
named here.  Publishing an INTEGER under ``float_value`` (or
inventing a third key) is accepted by every check the bridge has
today and then dropped by the cloud without a word."""
'''
        ).strip(),
        "",
        "",
        "VALUE_FIELD_JSON_TYPES: dict[str, str] = {",
        *(f'    "{name}": "{jtype}",' for name, jtype in sorted(field_types.items())),
        "}",
        dedent(
            '''"""Payload key → the JSON type Sber documents for it.

The one that matters is ``integer_value: "string"`` — Sber words
it "целочисленное значение long, записанное в виде строки", so an
INTEGER must go on the wire quoted.  ``float_value`` is
``number``, which settles the contradiction in the examples: two
function pages show a FLOAT quoted, and those examples are
wrong."""
'''
        ).strip(),
        "",
        "",
        "COLOUR_COMPONENT_RANGES: dict[str, tuple[int, int]] = {",
        *(f'    "{k}": ({v[0]}, {v[1]}),' for k, v in colour.items()),
        "}",
        dedent(
            '''"""Inclusive HSV bounds of ``colour_value``.

Note ``v`` starts at 100, not 0 — a detail the bridge already
honours in ``devices/utils/color_converter.py`` by hand.  Binding
it to the scraped page means a change upstream breaks a test
instead of breaking colour on real lamps."""
'''
        ).strip(),
        "",
        "",
        f"ALLOWED_VALUES_TYPES: frozenset[str] = frozenset({{{', '.join(repr(t) for t in sorted(allowed_types))}}})"
        if allowed_types
        else "ALLOWED_VALUES_TYPES: frozenset[str] = frozenset()",
        dedent(
            '''"""The only types an ``allowed_values`` entry may declare.

Source: developers.sber.ru/docs/ru/smarthome/c2c/allowed_values —
"Структура может использоваться только в описании функций,
которые принимают значения (value) в одном из следующих типов".
COLOUR is *not* among them, so an ``allowed_values`` entry for a
colour feature is malformed however harmless it looks."""
'''
        ).strip(),
        "",
    ]
    return "\n".join(lines)


def render_protocol_limits(spec: dict) -> str:
    """Render protocol_limits.py content."""
    header = HEADER.format(source=spec["source"], generated_at=spec["generated_at"]).rstrip()
    protocol = _protocol(spec)
    model = _structure_fields(spec, "model")
    device = _structure_fields(spec, "device")
    state = _structure_fields(spec, "state")
    allowed = _structure_fields(spec, "allowed_values")
    limit = protocol.get("partner_meta_max_chars")
    codes = {int(code): text for code, text in (protocol.get("error_codes") or {}).items()}

    def frozen(name: str, values: list[str], doc: str) -> list[str]:
        body = f"frozenset({{{', '.join(repr(v) for v in values)}}})" if values else "frozenset()"
        return [f"{name}: frozenset[str] = {body}", doc, "", ""]

    lines = [header, ""]
    lines += frozen(
        "MODEL_REQUIRED_FIELDS",
        _field_names(model, "obligatory"),
        '"""Fields the ``model`` structure marks ✔︎ obligatory.\n\nA model missing one of these is rejected whole, taking every device\nthat references it along."""',
    )
    lines += frozen(
        "MODEL_FIELDS",
        sorted(model),
        '"""Every field the ``model`` structure documents, required or not.\n\nNote what is *not* here: ``dependencies``.  The bridge sends it, no Sber\npage mentions it, and our own models are ``extra="forbid"`` — if the\ncloud reasons the same way, that field is a silent rejection waiting to\nhappen."""',
    )
    lines += frozen(
        "DEVICE_REQUIRED_FIELDS",
        _field_names(device, "obligatory"),
        '"""Fields the ``device`` structure marks ✔︎ obligatory.\n\nRead this one with care: the page marks **both** ``model_id`` and\n``model`` obligatory while the ``model`` row itself says "указывается,\nтолько если не задан model_id".  Both cannot hold, so this set is not\nusable as a plain "all of these must be present" check — the bridge\nsends an inline ``model`` and no ``model_id``, matching the examples on\nall 29 category pages."""',
    )
    lines += frozen(
        "DEVICE_FIELDS",
        sorted(device),
        '"""Every field the ``device`` structure documents.\n\n``nicknames``, which the bridge sends, is absent here — same exposure as\n``dependencies`` on the model side."""',
    )
    lines += frozen(
        "STATE_REQUIRED_FIELDS",
        _field_names(state, "obligatory"),
        '"""Fields of one ``state`` entry: ``key`` and ``value``, both required."""',
    )
    lines += frozen(
        "ALLOWED_VALUES_CONDITIONAL_FIELDS",
        _field_names(allowed, "conditional"),
        '"""The ✔︎* rows of ``allowed_values``: exactly one of these per entry.\n\nWhich one is decided by the entry\'s ``type`` — ``integer_values`` for\nINTEGER, ``float_values`` for FLOAT, ``enum_values`` for ENUM."""',
    )
    lines += [
        f"PARTNER_META_MAX_CHARS: int | None = {limit!r}",
        dedent(
            '''"""Maximum length of ``partner_meta`` in its JSON form.

The only numeric limit in the entire C2C reference: Sber writes
"Максимально допустимое количество символов в JSON-представлении
объекта partner_meta — 1024".  ``None`` means the sentence stopped
parsing, which is a scraper problem, not permission to send
more."""
'''
        ).strip(),
        "",
        "",
        "SBER_ERROR_CODES: dict[int, str] = {",
        *(f'    {code}: "{codes[code]}",' for code in sorted(codes)),
        "}",
        dedent(
            '''"""Error codes Sber may return, with its own wording.

401 and 403 mean "the credentials are wrong"; 400 means "the
payload is wrong"; 500/503 mean "try later".  The bridge
currently logs the raw error body as one truncated string, so
these three very different situations look identical to the
user."""
'''
        ).strip(),
        "",
    ]
    return "\n".join(lines)


def render_narrowing(spec: dict) -> str:
    """Render narrowing.py content."""
    header = HEADER.format(source=spec["source"], generated_at=spec["generated_at"]).rstrip()
    functions = spec["functions"]
    narrowing = {name: functions[name]["narrowing"] for name in sorted(functions) if functions[name].get("narrowing")}
    enum_subset = sorted(n for n, mode in narrowing.items() if mode == "enum_subset")
    range_modes = sorted(n for n, mode in narrowing.items() if mode in {"range_and_step", "range_only"})

    lines = [header, "", "FEATURE_NARROWING: dict[str, str] = {"]
    lines += [f'    "{name}": "{mode}",' for name, mode in sorted(narrowing.items())]
    lines.append("}")
    lines.append(
        dedent(
            '''"""How far a model may narrow a feature, per the feature\'s own page.

Sber states it once per function, always opening with "При
описании модели устройства":

- ``enum_subset`` — "перечень … можно сократить"
- ``range_and_step`` — "можно уменьшить диапазон … либо изменить их шаг"
- ``range_only`` — the range may shrink; no step is mentioned

A feature **absent from this table** is one whose page never
mentions narrowing.  That is all it means: no page anywhere states
that a feature may *not* be narrowed, so an ``allowed_values``
entry for an unlisted feature is unconfirmed by the documentation,
not a known violation.

The direction, in contrast, is stated outright — the
``allowed_values`` page says "диапазон можно только сократить" — so
a bound wider than :data:`FEATURE_RANGES` contradicts the docs,
except where Sber's own category example is wider (the reference
``hvac_boiler`` model declares a hotter ``hvac_temp_set`` than the
function page allows)."""
'''
        ).strip()
    )
    lines += [
        "",
        "",
        f"NARROWABLE_ENUM_FEATURES: frozenset[str] = frozenset({{{', '.join(repr(n) for n in enum_subset)}}})"
        if enum_subset
        else "NARROWABLE_ENUM_FEATURES: frozenset[str] = frozenset()",
        '"""ENUM features whose published vocabulary may be a subset."""',
        "",
        "",
        f"NARROWABLE_RANGE_FEATURES: frozenset[str] = frozenset({{{', '.join(repr(n) for n in range_modes)}}})"
        if range_modes
        else "NARROWABLE_RANGE_FEATURES: frozenset[str] = frozenset()",
        '"""Numeric features whose published range may be shrunk."""',
        "",
    ]
    return "\n".join(lines)


def render_feature_labels(spec: dict) -> str:
    """Render feature_labels.py content."""
    header = HEADER.format(source=spec["source"], generated_at=spec["generated_at"]).rstrip()
    functions = spec["functions"]
    titles = {name: functions[name]["title_ru"] for name in sorted(functions) if functions[name].get("title_ru")}
    enum_labels = {
        name: functions[name]["enum_descriptions"]
        for name in sorted(functions)
        if functions[name].get("enum_descriptions")
    }

    lines = [header, "", "FEATURE_TITLES_RU: dict[str, str] = {"]
    lines += [f"    {name!r}: {title!r}," for name, title in titles.items()]
    lines.append("}")
    lines.append(
        dedent(
            '''"""Feature name → Sber\'s own Russian label for it.

Straight off each function page\'s heading — ``light_colour
(цвет)``.  The panel shows protocol slugs today; these are the
words the Salute app uses for the very same feature, so a user
reading our wizard and their phone sees one vocabulary instead of
two."""
'''
        ).strip()
    )

    lines += ["", "", "FEATURE_ENUM_LABELS: dict[str, dict[str, str]] = {"]
    for name, labels in enum_labels.items():
        lines.append(f"    {name!r}: {{")
        lines += [f"        {value!r}: {text!r}," for value, text in labels.items()]
        lines.append("    },")
    lines.append("}")
    lines.append(
        dedent(
            '''"""ENUM value → Sber\'s Russian gloss for that value.

"cooling — охлаждение воздуха", "self_cleaning — самоочистка и
сушка устройства".  Absent for the two command-only ENUMs whose
pages carry no vocabulary at all (``reject_call``, ``unlock``):
their single legal value appears only inside the state example,
which is captured in the snapshot but is too thin a source to
label from."""
'''
        ).strip()
    )
    lines.append("")
    return "\n".join(lines)


def render_init(spec: dict) -> str:
    """Render __init__.py content."""
    header = HEADER.format(source=spec["source"], generated_at=spec["generated_at"]).rstrip()
    body = dedent(
        '''

        from .category_features import CATEGORY_REFERENCE_FEATURES
        from .conditional_features import CATEGORY_CONDITIONAL_FEATURES
        from .feature_labels import FEATURE_ENUM_LABELS, FEATURE_TITLES_RU
        from .feature_types import FEATURE_TYPES
        from .narrowing import (
            FEATURE_NARROWING,
            NARROWABLE_ENUM_FEATURES,
            NARROWABLE_RANGE_FEATURES,
        )
        from .obligatory_features import CATEGORY_OBLIGATORY_FEATURES
        from .protocol_limits import (
            ALLOWED_VALUES_CONDITIONAL_FIELDS,
            DEVICE_FIELDS,
            DEVICE_REQUIRED_FIELDS,
            MODEL_FIELDS,
            MODEL_REQUIRED_FIELDS,
            PARTNER_META_MAX_CHARS,
            SBER_ERROR_CODES,
            STATE_REQUIRED_FIELDS,
        )
        from .reference_values import FEATURE_ENUM_VALUES, FEATURE_RANGES
        from .usage_modes import (
            COMMAND_ONLY_FEATURES,
            EVENT_ONLY_FEATURES,
            FEATURE_USAGE_MODES,
            STATE_BEARING_FEATURES,
        )
        from .value_envelope import (
            ALLOWED_VALUES_TYPES,
            COLOUR_COMPONENT_RANGES,
            VALUE_FIELD_BY_TYPE,
            VALUE_FIELD_JSON_TYPES,
            VALUE_TYPES,
        )

        __all__ = [
            "ALLOWED_VALUES_CONDITIONAL_FIELDS",
            "ALLOWED_VALUES_TYPES",
            "CATEGORY_CONDITIONAL_FEATURES",
            "CATEGORY_OBLIGATORY_FEATURES",
            "CATEGORY_REFERENCE_FEATURES",
            "COLOUR_COMPONENT_RANGES",
            "COMMAND_ONLY_FEATURES",
            "DEVICE_FIELDS",
            "DEVICE_REQUIRED_FIELDS",
            "EVENT_ONLY_FEATURES",
            "FEATURE_ENUM_LABELS",
            "FEATURE_ENUM_VALUES",
            "FEATURE_NARROWING",
            "FEATURE_RANGES",
            "FEATURE_TITLES_RU",
            "FEATURE_TYPES",
            "FEATURE_USAGE_MODES",
            "MODEL_FIELDS",
            "MODEL_REQUIRED_FIELDS",
            "NARROWABLE_ENUM_FEATURES",
            "NARROWABLE_RANGE_FEATURES",
            "PARTNER_META_MAX_CHARS",
            "SBER_ERROR_CODES",
            "SPEC_GENERATED_AT",
            "SPEC_SOURCE",
            "STATE_BEARING_FEATURES",
            "STATE_REQUIRED_FIELDS",
            "VALUE_FIELD_BY_TYPE",
            "VALUE_FIELD_JSON_TYPES",
            "VALUE_TYPES",
        ]

        SPEC_SOURCE: str = "{source}"
        """Upstream documentation URL used to generate this package."""

        SPEC_GENERATED_AT: str = "{generated_at}"
        """ISO 8601 timestamp when the spec snapshot was fetched."""
        '''
    ).format(source=spec["source"], generated_at=spec["generated_at"])
    return header + body


# ---------------------------------------------------------------------------
# Atomic I/O + check mode
# ---------------------------------------------------------------------------


def atomic_write(path: Path, content: str) -> None:
    """Write content to path via temp file + os.replace (no partial writes)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path_str = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent), text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.replace(tmp_path_str, path)
    except BaseException:
        Path(tmp_path_str).unlink(missing_ok=True)
        raise


def ruff_format_content(content: str, path: Path) -> str:
    """Run content through ``ruff format`` via stdin, keeping input on failure."""
    try:
        # ruff is a trusted dev tool — argv is static.
        result = subprocess.run(  # noqa: S603
            ["ruff", "format", "-", "--stdin-filename", str(path)],  # noqa: S607
            input=content,
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        # ruff not available or failed — keep input unchanged.
        return content
    return result.stdout


def diff_against_committed(path: Path, expected: str) -> str:
    """Return unified diff between committed file and expected content (empty if match)."""
    actual = path.read_text(encoding="utf-8") if path.exists() else ""
    if actual == expected:
        return ""
    return "\n".join(
        difflib.unified_diff(
            actual.splitlines(),
            expected.splitlines(),
            fromfile=f"committed:{path.name}",
            tofile=f"generated:{path.name}",
            lineterm="",
        )
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

TARGETS: tuple[tuple[str, str], ...] = (
    ("feature_types.py", "render_feature_types"),
    ("category_features.py", "render_category_features"),
    ("obligatory_features.py", "render_obligatory_features"),
    ("conditional_features.py", "render_conditional_features"),
    ("reference_values.py", "render_reference_values"),
    ("usage_modes.py", "render_usage_modes"),
    ("value_envelope.py", "render_value_envelope"),
    ("protocol_limits.py", "render_protocol_limits"),
    ("narrowing.py", "render_narrowing"),
    ("feature_labels.py", "render_feature_labels"),
    ("__init__.py", "render_init"),
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="CI mode: diff against committed files, exit 1 on mismatch, write nothing",
    )
    args = parser.parse_args(argv)

    try:
        spec = load_spec(SPEC_FILE)
    except SpecValidationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    renderers = {
        "render_feature_types": render_feature_types,
        "render_category_features": render_category_features,
        "render_obligatory_features": render_obligatory_features,
        "render_conditional_features": render_conditional_features,
        "render_reference_values": render_reference_values,
        "render_usage_modes": render_usage_modes,
        "render_value_envelope": render_value_envelope,
        "render_protocol_limits": render_protocol_limits,
        "render_narrowing": render_narrowing,
        "render_feature_labels": render_feature_labels,
        "render_init": render_init,
    }

    drift_found = False
    for filename, renderer_name in TARGETS:
        target_path = OUTPUT_DIR / filename
        raw_content = renderers[renderer_name](spec)
        # Run through ruff for canonical formatting so drift-check is stable.
        expected = ruff_format_content(raw_content, target_path)
        if args.check:
            diff = diff_against_committed(target_path, expected)
            if diff:
                drift_found = True
                print(f"DRIFT: {target_path}")
                print(diff)
            else:
                print(f"OK:    {target_path}")
        else:
            atomic_write(target_path, expected)
            print(f"WROTE: {target_path}")

    if args.check and drift_found:
        print(
            "\nGenerated files are out of date.  Run: python tools/codegen.py",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
