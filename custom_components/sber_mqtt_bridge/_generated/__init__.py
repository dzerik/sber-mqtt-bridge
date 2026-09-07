"""AUTO-GENERATED from tests/hacs/__snapshots__/sber_full_spec.json.

DO NOT EDIT BY HAND.  Regenerate with:

    python tools/codegen.py

Source: https://developers.sber.ru/docs/ru/smarthome/c2c
Spec generated at: 2026-09-07T15:07:37.367121+00:00
"""

from __future__ import annotations

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

SPEC_SOURCE: str = "https://developers.sber.ru/docs/ru/smarthome/c2c"
"""Upstream documentation URL used to generate this package."""

SPEC_GENERATED_AT: str = "2026-09-07T15:07:37.367121+00:00"
"""ISO 8601 timestamp when the spec snapshot was fetched."""
