"""Tests for proto3 default-value omission handling (issue #44).

Sber cloud serializes protobuf to JSON per proto3 rules: a field holding
its type's default value is OMITTED from the payload.  A command carrying
``0`` arrives as ``{"type": "INTEGER"}`` with no ``integer_value`` key,
``false`` arrives as ``{"type": "BOOL"}`` with no ``bool_value``, etc.

Handlers must treat a missing typed field as the type's default instead
of silently dropping the command.
"""

import unittest

from custom_components.sber_mqtt_bridge.devices.curtain import CurtainEntity
from custom_components.sber_mqtt_bridge.devices.light import LightEntity
from custom_components.sber_mqtt_bridge.devices.tv import TvEntity
from custom_components.sber_mqtt_bridge.sber_models import normalize_sber_value


class TestNormalizeSberValue(unittest.TestCase):
    """Unit tests for the normalize_sber_value helper."""

    def test_integer_missing_value_defaults_to_zero(self):
        """{"type": "INTEGER"} gains integer_value "0"."""
        result = normalize_sber_value({"type": "INTEGER"})
        self.assertEqual(result["integer_value"], "0")

    def test_float_missing_value_defaults_to_zero(self):
        """{"type": "FLOAT"} gains float_value 0.0."""
        result = normalize_sber_value({"type": "FLOAT"})
        self.assertEqual(result["float_value"], 0.0)

    def test_string_missing_value_defaults_to_empty(self):
        """{"type": "STRING"} gains string_value ""."""
        result = normalize_sber_value({"type": "STRING"})
        self.assertEqual(result["string_value"], "")

    def test_bool_missing_value_defaults_to_false(self):
        """{"type": "BOOL"} gains bool_value False."""
        result = normalize_sber_value({"type": "BOOL"})
        self.assertIs(result["bool_value"], False)

    def test_enum_missing_value_defaults_to_empty(self):
        """{"type": "ENUM"} gains enum_value ""."""
        result = normalize_sber_value({"type": "ENUM"})
        self.assertEqual(result["enum_value"], "")

    def test_colour_missing_value_defaults_to_zero_hsv(self):
        """{"type": "COLOUR"} gains colour_value with h/s/v zeros."""
        result = normalize_sber_value({"type": "COLOUR"})
        self.assertEqual(result["colour_value"], {"h": 0, "s": 0, "v": 0})

    def test_colour_partial_hsv_filled(self):
        """Missing h/s/v components inside colour_value are zero-filled."""
        result = normalize_sber_value({"type": "COLOUR", "colour_value": {"h": 120}})
        self.assertEqual(result["colour_value"], {"h": 120, "s": 0, "v": 0})

    def test_existing_integer_value_preserved(self):
        """An explicit integer_value is never overwritten."""
        result = normalize_sber_value({"type": "INTEGER", "integer_value": "42"})
        self.assertEqual(result["integer_value"], "42")

    def test_existing_bool_value_preserved(self):
        """An explicit bool_value True is never overwritten."""
        result = normalize_sber_value({"type": "BOOL", "bool_value": True})
        self.assertIs(result["bool_value"], True)

    def test_missing_type_left_untouched(self):
        """A payload without 'type' is returned as-is."""
        self.assertEqual(normalize_sber_value({}), {})

    def test_unknown_type_left_untouched(self):
        """An unknown type gets no injected fields."""
        result = normalize_sber_value({"type": "MYSTERY"})
        self.assertNotIn("integer_value", result)

    def test_input_not_mutated(self):
        """The original dict is not modified in place."""
        original = {"type": "INTEGER"}
        normalize_sber_value(original)
        self.assertNotIn("integer_value", original)


class TestLightZeroValues(unittest.TestCase):
    """Light commands with proto3-omitted zero values (issue #44 report)."""

    def _make_entity(self):
        entity = LightEntity({"entity_id": "light.room", "name": "Room Light"})
        entity.fill_by_ha_state(
            {
                "entity_id": "light.room",
                "state": "on",
                "attributes": {
                    "brightness": 200,
                    "color_temp": 300,
                    "min_mireds": 153,
                    "max_mireds": 500,
                    "supported_color_modes": ["color_temp"],
                    "color_mode": "color_temp",
                },
            }
        )
        return entity

    def test_colour_temp_slider_at_zero(self):
        """Exact payload from issue #44: colour_temp 0 without integer_value.

        Sber 0 on the reversed converter maps to max mireds (500), i.e.
        the warmest supported temperature: kelvin = 1_000_000 / 500 = 2000.
        """
        entity = self._make_entity()
        result = entity.process_cmd({"states": [{"key": "light_colour_temp", "value": {"type": "INTEGER"}}]})
        self.assertEqual(len(result), 1)
        url = result[0]["url"]
        self.assertEqual(url["service"], "turn_on")
        self.assertEqual(url["service_data"]["color_temp_kelvin"], 2000)

    def test_colour_temp_value_one_still_works(self):
        """Regression: explicit integer_value "1" keeps working."""
        entity = self._make_entity()
        result = entity.process_cmd(
            {"states": [{"key": "light_colour_temp", "value": {"type": "INTEGER", "integer_value": "1"}}]}
        )
        self.assertEqual(len(result), 1)
        self.assertIn("color_temp_kelvin", result[0]["url"]["service_data"])

    def test_brightness_without_integer_value(self):
        """Brightness command with omitted zero still produces a service call."""
        entity = self._make_entity()
        result = entity.process_cmd({"states": [{"key": "light_brightness", "value": {"type": "INTEGER"}}]})
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["url"]["service"], "turn_on")


class TestCurtainZeroPosition(unittest.TestCase):
    """Curtain position 0 (fully closed) with proto3-omitted value."""

    def test_position_zero_closes_curtain(self):
        """open_percentage 0 without integer_value → set_cover_position 0."""
        entity = CurtainEntity({"entity_id": "cover.room", "name": "Curtain"})
        entity.fill_by_ha_state({"entity_id": "cover.room", "state": "open", "attributes": {"current_position": 50}})
        result = entity.process_cmd({"states": [{"key": "open_percentage", "value": {"type": "INTEGER"}}]})
        self.assertEqual(len(result), 1)
        url = result[0]["url"]
        self.assertEqual(url["service"], "set_cover_position")
        self.assertEqual(url["service_data"]["position"], 0)


class TestTvZeroValues(unittest.TestCase):
    """TV volume/digit 0 with proto3-omitted value."""

    def _make_entity(self):
        entity = TvEntity({"entity_id": "media_player.tv", "name": "TV"})
        entity.fill_by_ha_state({"entity_id": "media_player.tv", "state": "on", "attributes": {"volume_level": 0.5}})
        return entity

    def test_volume_zero(self):
        """volume 0 without integer_value → volume_set 0.0."""
        entity = self._make_entity()
        result = entity.process_cmd({"states": [{"key": "volume_int", "value": {"type": "INTEGER"}}]})
        self.assertEqual(len(result), 1)
        url = result[0]["url"]
        self.assertEqual(url["service"], "volume_set")
        self.assertEqual(url["service_data"]["volume_level"], 0.0)


if __name__ == "__main__":
    unittest.main()
