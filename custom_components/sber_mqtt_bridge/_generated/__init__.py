"""AUTO-GENERATED from tests/hacs/__snapshots__/sber_full_spec.json.

DO NOT EDIT BY HAND.  Regenerate with:

    python tools/codegen.py

Source: https://developers.sber.ru/docs/ru/smarthome/c2c
Spec generated at: 2026-09-07T12:06:54.143165+00:00
"""

from __future__ import annotations

from .category_features import CATEGORY_REFERENCE_FEATURES
from .conditional_features import CATEGORY_CONDITIONAL_FEATURES
from .feature_types import FEATURE_TYPES
from .obligatory_features import CATEGORY_OBLIGATORY_FEATURES
from .reference_values import FEATURE_ENUM_VALUES, FEATURE_RANGES
from .usage_modes import (
    COMMAND_ONLY_FEATURES,
    EVENT_ONLY_FEATURES,
    FEATURE_USAGE_MODES,
    STATE_BEARING_FEATURES,
)

__all__ = [
    "CATEGORY_CONDITIONAL_FEATURES",
    "CATEGORY_OBLIGATORY_FEATURES",
    "CATEGORY_REFERENCE_FEATURES",
    "COMMAND_ONLY_FEATURES",
    "EVENT_ONLY_FEATURES",
    "FEATURE_ENUM_VALUES",
    "FEATURE_RANGES",
    "FEATURE_TYPES",
    "FEATURE_USAGE_MODES",
    "SPEC_GENERATED_AT",
    "SPEC_SOURCE",
    "STATE_BEARING_FEATURES",
]

SPEC_SOURCE: str = "https://developers.sber.ru/docs/ru/smarthome/c2c"
"""Upstream documentation URL used to generate this package."""

SPEC_GENERATED_AT: str = "2026-09-07T12:06:54.143165+00:00"
"""ISO 8601 timestamp when the spec snapshot was fetched."""
