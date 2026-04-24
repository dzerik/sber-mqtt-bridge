"""Tests for custom_components.sber_mqtt_bridge.name_utils."""

from __future__ import annotations

import logging

import pytest

from custom_components.sber_mqtt_bridge.name_utils import (
    is_safe_sber_id,
    is_salut_friendly_name,
    slugify_sber_id,
    warn_if_suspicious_id,
    warn_if_suspicious_name,
)

# --------------------------------------------------------------------------- #
# slugify_sber_id
# --------------------------------------------------------------------------- #


class TestSlugifySberId:
    @pytest.mark.parametrize(
        ("src", "expected"),
        [
            ("", ""),
            # Our transliteration follows Salut convention (я → ya),
            # which differs from HA's (я → ia) — that's intentional.
            ("Удлинитель Кухня №1", "udlinitel_kukhnya_1"),
            ("Телевизор", "televizor"),
            ("Смарт-телевизор", "smart_televizor"),
            ("Living Room Lamp", "living_room_lamp"),
            ("   spaces   ", "spaces"),
            ("a!!b??c", "a_b_c"),
            ("Ёжик", "yozhik"),
        ],
    )
    def test_slug_shapes(self, src, expected):
        assert slugify_sber_id(src) == expected

    def test_mixed_case_lowered(self):
        assert slugify_sber_id("FooBar") == "foobar"


# --------------------------------------------------------------------------- #
# is_safe_sber_id
# --------------------------------------------------------------------------- #


class TestIsSafeSberId:
    @pytest.mark.parametrize(
        "value",
        [
            "switch.udlinitel_kukhnia_rozetka_no1",   # HA entity_id
            "device-456",
            "ABCD_004",
            "root",
        ],
    )
    def test_safe_ids(self, value):
        assert is_safe_sber_id(value) is True

    @pytest.mark.parametrize(
        "value",
        [
            "",                         # empty
            "устройство_1",             # cyrillic
            "device with spaces",       # space
            "device#1",                 # hash
            "a/b",                      # slash
        ],
    )
    def test_unsafe_ids(self, value):
        assert is_safe_sber_id(value) is False


# --------------------------------------------------------------------------- #
# is_salut_friendly_name
# --------------------------------------------------------------------------- #


class TestIsSalutFriendlyName:
    @pytest.mark.parametrize(
        "value",
        [
            "Мой телевизор",
            "Смарт-телевизор",
            "Кухня 1",
            "Ёлка",
        ],
    )
    def test_salut_ok(self, value):
        assert is_salut_friendly_name(value) is True

    @pytest.mark.parametrize(
        "value",
        [
            "",                         # empty
            "ab",                       # too short
            "a" * 34,                   # too long
            "Living Room",              # latin
            "Кухня №1",                 # "№" not allowed
            "Кухня!",                   # punctuation
        ],
    )
    def test_salut_fail(self, value):
        assert is_salut_friendly_name(value) is False


# --------------------------------------------------------------------------- #
# warn_if_suspicious_* — side-effect logging
# --------------------------------------------------------------------------- #


class TestWarnHelpers:
    def test_warn_empty_name(self, caplog):
        caplog.set_level(logging.WARNING, logger="custom_components.sber_mqtt_bridge.name_utils")
        warn_if_suspicious_name("switch.lamp", "")
        assert any("empty name" in r.message for r in caplog.records)

    def test_warn_long_name(self, caplog):
        caplog.set_level(logging.WARNING, logger="custom_components.sber_mqtt_bridge.name_utils")
        warn_if_suspicious_name("switch.lamp", "x" * 70)
        assert any(">63" in r.message for r in caplog.records)

    def test_no_warn_for_ok_name(self, caplog):
        caplog.set_level(logging.WARNING, logger="custom_components.sber_mqtt_bridge.name_utils")
        warn_if_suspicious_name("switch.lamp", "Телевизор")
        # no WARN-level records about this name
        assert not any(r.levelno == logging.WARNING for r in caplog.records)

    def test_warn_cyrillic_id(self, caplog):
        caplog.set_level(logging.WARNING, logger="custom_components.sber_mqtt_bridge.name_utils")
        warn_if_suspicious_id("устройство_1")
        assert any("outside [A-Za-z0-9_.-]" in r.message for r in caplog.records)

    def test_no_warn_for_ha_entity_id(self, caplog):
        caplog.set_level(logging.WARNING, logger="custom_components.sber_mqtt_bridge.name_utils")
        warn_if_suspicious_id("switch.udlinitel_kukhnia_rozetka_no1")
        assert not any(r.levelno == logging.WARNING for r in caplog.records)
