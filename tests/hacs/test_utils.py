"""Tests for ColorConverter and LinearConverter utilities."""

import unittest

import pytest

from custom_components.sber_mqtt_bridge.devices.utils.color_converter import ColorConverter
from custom_components.sber_mqtt_bridge.devices.utils.linear_converter import LinearConverter


# ---- ColorConverter Tests ----

class TestColorConverterHaToSber(unittest.TestCase):
    """Test ColorConverter.ha_to_sber_hsv."""

    def test_zero_values(self):
        """All zeros produce Sber (0, 0, 100) — minimum V is 100."""
        h, s, v = ColorConverter.ha_to_sber_hsv(0, 0, 0)
        self.assertEqual(h, 0)
        self.assertEqual(s, 0)
        self.assertEqual(v, 100)

    def test_max_values(self):
        """Max HA values produce Sber (360, 1000, 1000)."""
        h, s, v = ColorConverter.ha_to_sber_hsv(360, 100, 255)
        self.assertEqual(h, 360)
        self.assertEqual(s, 1000)
        self.assertEqual(v, 1000)

    def test_mid_values(self):
        """Middle brightness maps linearly."""
        h, s, v = ColorConverter.ha_to_sber_hsv(180, 50, 128)
        self.assertEqual(h, 180)
        self.assertEqual(s, 500)
        # 128/255 * 900 + 100 ~ 551.76 => 552
        self.assertAlmostEqual(v, 552, delta=1)

    def test_none_values(self):
        """None values are treated as 0."""
        h, s, v = ColorConverter.ha_to_sber_hsv(None, None, None)
        self.assertEqual(h, 0)
        self.assertEqual(s, 0)
        self.assertEqual(v, 100)

    def test_clamping_high(self):
        """Values above max are clamped."""
        h, s, v = ColorConverter.ha_to_sber_hsv(400, 200, 300)
        self.assertEqual(h, 360)
        self.assertEqual(s, 1000)
        self.assertEqual(v, 1000)

    def test_clamping_negative(self):
        """Negative values are clamped to 0."""
        h, s, v = ColorConverter.ha_to_sber_hsv(-10, -10, -10)
        self.assertEqual(h, 0)
        self.assertEqual(s, 0)
        self.assertEqual(v, 100)


class TestColorConverterSberToHa(unittest.TestCase):
    """Test ColorConverter.sber_to_ha_hsv."""

    def test_min_values(self):
        """Sber (0, 0, 100) produces HA (0, 0, 0)."""
        h, s, v = ColorConverter.sber_to_ha_hsv(0, 0, 100)
        self.assertEqual(h, 0)
        self.assertEqual(s, 0)
        self.assertEqual(v, 0)

    def test_max_values(self):
        """Sber (360, 1000, 1000) produces HA (360, 100, 255)."""
        h, s, v = ColorConverter.sber_to_ha_hsv(360, 1000, 1000)
        self.assertEqual(h, 360)
        self.assertEqual(s, 100)
        self.assertEqual(v, 255)

    def test_mid_values(self):
        h, s, v = ColorConverter.sber_to_ha_hsv(180, 500, 550)
        self.assertEqual(h, 180)
        self.assertEqual(s, 50)
        # (550-100)/900*255 ~ 127.5 => 128
        self.assertAlmostEqual(v, 128, delta=1)

    def test_none_values(self):
        """None values default to 0 (with V clamped to min 100)."""
        h, s, v = ColorConverter.sber_to_ha_hsv(None, None, None)
        self.assertEqual(h, 0)
        self.assertEqual(s, 0)
        # None -> 0 -> clamped to 100 -> (100-100)/900*255 = 0
        self.assertEqual(v, 0)

    def test_roundtrip(self):
        """Converting HA->Sber->HA preserves values (within rounding)."""
        original = (200, 75, 180)
        sber = ColorConverter.ha_to_sber_hsv(*original)
        ha = ColorConverter.sber_to_ha_hsv(*sber)
        self.assertAlmostEqual(ha[0], original[0], delta=1)
        self.assertAlmostEqual(ha[1], original[1], delta=1)
        self.assertAlmostEqual(ha[2], original[2], delta=1)


# ---- LinearConverter Tests ----

class TestLinearConverterCreate(unittest.TestCase):
    """Test LinearConverter constructor and defaults."""

    def test_constructor_returns_instance(self):
        lc = LinearConverter()
        self.assertIsInstance(lc, LinearConverter)

    def test_default_limits(self):
        lc = LinearConverter()
        self.assertEqual(lc.sber_side_min, 0)
        self.assertEqual(lc.sber_side_max, 1000)
        self.assertEqual(lc.ha_side_min, 0)
        self.assertEqual(lc.ha_side_max, 255)
        self.assertFalse(lc.is_reversed)


class TestLinearConverterSetLimits(unittest.TestCase):
    """Test set_sber_limits and set_ha_limits."""

    def test_set_sber_limits(self):
        lc = LinearConverter()
        lc.set_sber_limits(10, 500)
        self.assertEqual(lc.sber_side_min, 10)
        self.assertEqual(lc.sber_side_max, 500)

    def test_set_sber_limits_invalid(self):
        lc = LinearConverter()
        with self.assertRaises(ValueError):
            lc.set_sber_limits(500, 10)

    def test_set_sber_limits_equal(self):
        lc = LinearConverter()
        with self.assertRaises(ValueError):
            lc.set_sber_limits(100, 100)

    def test_set_ha_limits(self):
        lc = LinearConverter()
        lc.set_ha_limits(10, 100)
        self.assertEqual(lc.ha_side_min, 10)
        self.assertEqual(lc.ha_side_max, 100)

    def test_set_ha_limits_invalid(self):
        lc = LinearConverter()
        with self.assertRaises(ValueError):
            lc.set_ha_limits(100, 10)

    def test_set_ha_limits_equal(self):
        lc = LinearConverter()
        with self.assertRaises(ValueError):
            lc.set_ha_limits(50, 50)


class TestLinearConverterHaToSber(unittest.TestCase):
    """Test ha_to_sber conversion."""

    def test_min_value(self):
        lc = LinearConverter()
        self.assertEqual(lc.ha_to_sber(0), 0)

    def test_max_value(self):
        lc = LinearConverter()
        self.assertEqual(lc.ha_to_sber(255), 1000)

    def test_mid_value(self):
        lc = LinearConverter()
        result = lc.ha_to_sber(128)
        # 128/255 * 1000 ~ 502
        self.assertAlmostEqual(result, 502, delta=1)

    def test_below_min_clamped(self):
        lc = LinearConverter()
        self.assertEqual(lc.ha_to_sber(-10), 0)

    def test_above_max_clamped(self):
        lc = LinearConverter()
        self.assertEqual(lc.ha_to_sber(300), 1000)

    def test_custom_limits(self):
        lc = LinearConverter()
        lc.set_ha_limits(0, 100)
        lc.set_sber_limits(0, 500)
        self.assertEqual(lc.ha_to_sber(50), 250)


class TestLinearConverterSberToHa(unittest.TestCase):
    """Test sber_to_ha conversion."""

    def test_min_value(self):
        lc = LinearConverter()
        self.assertEqual(lc.sber_to_ha(0), 0)

    def test_max_value(self):
        lc = LinearConverter()
        self.assertEqual(lc.sber_to_ha(1000), 255)

    def test_mid_value(self):
        lc = LinearConverter()
        result = lc.sber_to_ha(500)
        # 500/1000 * 255 ~ 127.5 => 128
        self.assertAlmostEqual(result, 128, delta=1)

    def test_below_min_clamped(self):
        lc = LinearConverter()
        self.assertEqual(lc.sber_to_ha(-10), 0)

    def test_above_max_clamped(self):
        lc = LinearConverter()
        self.assertEqual(lc.sber_to_ha(1500), 255)


class TestLinearConverterReversed(unittest.TestCase):
    """Test reversed mode (inverted range mapping)."""

    def test_set_reversed(self):
        lc = LinearConverter()
        lc.set_reversed(True)
        self.assertTrue(lc.is_reversed)

    def test_reversed_ha_to_sber(self):
        """In reversed mode, ha_min maps to sber_max and vice versa."""
        lc = LinearConverter()
        lc.set_ha_limits(0, 100)
        lc.set_sber_limits(0, 1000)
        lc.set_reversed(True)
        # ha=0 -> sber_max=1000 (reversed: delta = ha_max - ha_value = 100)
        self.assertEqual(lc.ha_to_sber(0), 1000)
        self.assertEqual(lc.ha_to_sber(100), 0)
        self.assertEqual(lc.ha_to_sber(50), 500)

    def test_reversed_sber_to_ha(self):
        lc = LinearConverter()
        lc.set_ha_limits(0, 100)
        lc.set_sber_limits(0, 1000)
        lc.set_reversed(True)
        self.assertEqual(lc.sber_to_ha(0), 100)
        self.assertEqual(lc.sber_to_ha(1000), 0)
        self.assertEqual(lc.sber_to_ha(500), 50)

    def test_roundtrip(self):
        """HA -> Sber -> HA roundtrip preserves value."""
        lc = LinearConverter()
        lc.set_ha_limits(0, 255)
        lc.set_sber_limits(50, 1000)
        for original in [0, 50, 128, 200, 255]:
            sber = lc.ha_to_sber(original)
            back = lc.sber_to_ha(sber)
            self.assertAlmostEqual(back, original, delta=1)

    def test_roundtrip_reversed(self):
        """Reversed roundtrip preserves value."""
        lc = LinearConverter()
        lc.set_ha_limits(153, 500)
        lc.set_sber_limits(0, 1000)
        lc.set_reversed(True)
        for original in [153, 250, 350, 500]:
            sber = lc.ha_to_sber(original)
            back = lc.sber_to_ha(sber)
            self.assertAlmostEqual(back, original, delta=1)
