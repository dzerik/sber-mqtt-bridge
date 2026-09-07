"""AUTO-GENERATED from tests/hacs/__snapshots__/sber_full_spec.json.

DO NOT EDIT BY HAND.  Regenerate with:

    python tools/codegen.py

Source: https://developers.sber.ru/docs/ru/smarthome/c2c
Spec generated at: 2026-09-07T15:07:37.367121+00:00
"""

from __future__ import annotations

VALUE_TYPES: frozenset[str] = frozenset({"BOOL", "COLOUR", "ENUM", "FLOAT", "INTEGER", "STRING"})
"""Every value type the ``value`` structure may declare.

Source: the ``type`` row of
developers.sber.ru/docs/ru/smarthome/c2c/value — "Может
принимать значение: FLOAT, INTEGER, STRING, BOOL, ENUM,
COLOUR"."""


VALUE_FIELD_BY_TYPE: dict[str, str] = {
    "BOOL": "bool_value",
    "COLOUR": "colour_value",
    "ENUM": "enum_value",
    "FLOAT": "float_value",
    "INTEGER": "integer_value",
    "STRING": "string_value",
}
"""Value type → the payload key that carries it.

A ``value`` object holds exactly two keys: ``type`` and the one
named here.  Publishing an INTEGER under ``float_value`` (or
inventing a third key) is accepted by every check the bridge has
today and then dropped by the cloud without a word."""


VALUE_FIELD_JSON_TYPES: dict[str, str] = {
    "bool_value": "boolean",
    "colour_value": "colour",
    "enum_value": "string",
    "float_value": "number",
    "integer_value": "string",
    "string_value": "string",
}
"""Payload key → the JSON type Sber documents for it.

The one that matters is ``integer_value: "string"`` — Sber words
it "целочисленное значение long, записанное в виде строки", so an
INTEGER must go on the wire quoted.  ``float_value`` is
``number``, which settles the contradiction in the examples: two
function pages show a FLOAT quoted, and those examples are
wrong."""


COLOUR_COMPONENT_RANGES: dict[str, tuple[int, int]] = {
    "h": (0, 360),
    "s": (0, 1000),
    "v": (100, 1000),
}
"""Inclusive HSV bounds of ``colour_value``.

Note ``v`` starts at 100, not 0 — a detail the bridge already
honours in ``devices/utils/color_converter.py`` by hand.  Binding
it to the scraped page means a change upstream breaks a test
instead of breaking colour on real lamps."""


ALLOWED_VALUES_TYPES: frozenset[str] = frozenset({"ENUM", "FLOAT", "INTEGER"})
"""The only types an ``allowed_values`` entry may declare.

Source: developers.sber.ru/docs/ru/smarthome/c2c/allowed_values —
"Структура может использоваться только в описании функций,
которые принимают значения (value) в одном из следующих типов".
COLOUR is *not* among them, so an ``allowed_values`` entry for a
colour feature is malformed however harmless it looks."""
