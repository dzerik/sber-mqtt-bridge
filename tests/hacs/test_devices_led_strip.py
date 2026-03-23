"""Tests for LedStripEntity -- Sber LED strip device mapping."""

import unittest

from custom_components.sber_mqtt_bridge.devices.led_strip import LedStripEntity


ENTITY_DATA = {"entity_id": "light.led_strip", "name": "LED Strip"}


def _make_ha_state(state="on", **attrs):
    base_attrs = {"supported_color_modes": [], "brightness": 128}
    base_attrs.update(attrs)
    return {
        "entity_id": "light.led_strip",
        "state": state,
        "attributes": base_attrs,
    }


class TestLedStripCreate(unittest.TestCase):
    """Test LedStripEntity initialization."""

    def test_category_is_led_strip(self):
        entity = LedStripEntity(ENTITY_DATA)
        self.assertEqual(entity.category, "led_strip")

    def test_entity_id(self):
        entity = LedStripEntity(ENTITY_DATA)
        self.assertEqual(entity.entity_id, "light.led_strip")

    def test_inherits_light_entity(self):
        from custom_components.sber_mqtt_bridge.devices.light import LightEntity

        entity = LedStripEntity(ENTITY_DATA)
        self.assertIsInstance(entity, LightEntity)


class TestLedStripToSberCurrentState(unittest.TestCase):
    """Test to_sber_current_state."""

    def test_basic_on_state(self):
        entity = LedStripEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("on"))
        result = entity.to_sber_current_state()
        self.assertIn("light.led_strip", result)
        states = result["light.led_strip"]["states"]
        on_off = next(s for s in states if s["key"] == "on_off")
        self.assertTrue(on_off["value"]["bool_value"])

    def test_off_state(self):
        entity = LedStripEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("off"))
        result = entity.to_sber_current_state()
        states = result["light.led_strip"]["states"]
        on_off = next(s for s in states if s["key"] == "on_off")
        self.assertFalse(on_off["value"]["bool_value"])


class TestLedStripProcessCmd(unittest.TestCase):
    """Test process_cmd."""

    def test_on_off_command(self):
        entity = LedStripEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("off"))
        result = entity.process_cmd({
            "states": [{"key": "on_off", "value": {"type": "BOOL", "bool_value": True}}]
        })
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["url"]["service"], "turn_on")
        self.assertEqual(result[0]["url"]["domain"], "light")
