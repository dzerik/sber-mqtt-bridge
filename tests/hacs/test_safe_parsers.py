"""Contract tests for the safe-value parsers in ``devices/base_entity.py``.

These helpers must behave identically everywhere they are used:
- as ``AttrSpec.parser`` callbacks when ingesting HA attributes, and
- inline in ``process_cmd`` when parsing Sber payload values.

The parsers are the single source of truth for "convert this arbitrary
object into a typed primitive, returning ``None`` on failure".  If any
of these invariants break, every device class that delegates to them
silently corrupts its state -- so tests here describe the protocol
contract, not the implementation.
"""

from __future__ import annotations

import pytest

from custom_components.sber_mqtt_bridge.devices.base_entity import (
    _safe_bool_parser,
    _safe_clamped_int_parser,
    _safe_float_parser,
    _safe_int_parser,
)


class TestSafeIntParser:
    """``_safe_int_parser`` converts arbitrary input to ``int | None``."""

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (42, 42),
            ("42", 42),
            ("22.5", 22),  # HA sensor values are strings like "22.5" -- must round down via float.
            (22.9, 22),  # Truncation (not rounding) is the spec.
            (0, 0),
            ("-5", -5),
        ],
    )
    def test_valid_values_converted(self, value: object, expected: int) -> None:
        assert _safe_int_parser(value) == expected

    @pytest.mark.parametrize("value", [None, "", "not-a-number", "nan", [], {}])
    def test_invalid_values_return_none(self, value: object) -> None:
        assert _safe_int_parser(value) is None


class TestSafeFloatParser:
    """``_safe_float_parser`` converts arbitrary input to ``float | None``."""

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (22.5, 22.5),
            ("22.5", 22.5),
            (42, 42.0),
            ("0", 0.0),
        ],
    )
    def test_valid_values_converted(self, value: object, expected: float) -> None:
        assert _safe_float_parser(value) == expected

    @pytest.mark.parametrize("value", [None, "", "junk", []])
    def test_invalid_values_return_none(self, value: object) -> None:
        assert _safe_float_parser(value) is None


class TestSafeBoolParser:
    """``_safe_bool_parser`` preserves ``None`` (unknown state) and coerces the rest."""

    def test_none_preserved(self) -> None:
        # The None-preservation contract matters for AttrSpec:
        # "attribute missing" must NOT become "attribute is False".
        assert _safe_bool_parser(None) is None

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (True, True),
            (False, False),
            (1, True),
            (0, False),
            ("on", True),
            ("", False),
        ],
    )
    def test_truthy_values_coerced(self, value: object, expected: bool) -> None:
        assert _safe_bool_parser(value) == expected


class TestSafeClampedIntParser:
    """``_safe_clamped_int_parser(value, low, high)`` parses then clamps.

    Used in command handlers that accept bounded integer ranges
    (cover position 0-100, HSV saturation 0-1000, etc.).  The critical
    invariant: **if the value parses at all, the result is in ``[low, high]``**.
    """

    @pytest.mark.parametrize(
        ("value", "low", "high", "expected"),
        [
            (50, 0, 100, 50),
            (-10, 0, 100, 0),  # Under range: clamped up.
            (150, 0, 100, 100),  # Over range: clamped down.
            ("50", 0, 100, 50),  # String input still works.
            (100, 0, 100, 100),  # Boundary inclusive.
            (0, 0, 100, 0),
        ],
    )
    def test_valid_values_clamped(self, value: object, low: int, high: int, expected: int) -> None:
        assert _safe_clamped_int_parser(value, low, high) == expected

    @pytest.mark.parametrize("value", [None, "junk", ""])
    def test_invalid_values_return_none(self, value: object) -> None:
        # No clamping on failure -- caller must distinguish "out of range" from "unparseable".
        assert _safe_clamped_int_parser(value, 0, 100) is None
