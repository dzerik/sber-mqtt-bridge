"""Tests for HvacHeaterEntity -- Sber heater device mapping."""

import unittest

from custom_components.sber_mqtt_bridge.devices.hvac_heater import HvacHeaterEntity


ENTITY_DATA = {"entity_id": "climate.heater", "name": "Space Heater"}


def _make_ha_state(state="heat", **attrs):
    base_attrs = {"current_temperature": 20.0, "temperature": 25.0}
    base_attrs.update(attrs)
    return {
        "entity_id": "climate.heater",
        "state": state,
        "attributes": base_attrs,
    }


class TestHvacHeaterCreate(unittest.TestCase):
    """Test HvacHeaterEntity initialization."""

    def test_category(self):
        entity = HvacHeaterEntity(ENTITY_DATA)
        self.assertEqual(entity.category, "hvac_heater")

    def test_temp_defaults(self):
        entity = HvacHeaterEntity(ENTITY_DATA)
        self.assertEqual(entity.min_temp, 5.0)
        self.assertEqual(entity.max_temp, 40.0)

    def test_inherits_climate(self):
        from custom_components.sber_mqtt_bridge.devices.climate import ClimateEntity

        entity = HvacHeaterEntity(ENTITY_DATA)
        self.assertIsInstance(entity, ClimateEntity)


class TestHvacHeaterToSberCurrentState(unittest.TestCase):
    """Test to_sber_current_state."""

    def test_basic_state(self):
        entity = HvacHeaterEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("heat"))
        result = entity.to_sber_current_state()
        states = result["climate.heater"]["states"]
        on_off = next(s for s in states if s["key"] == "on_off")
        self.assertTrue(on_off["value"]["bool_value"])
        temp = next(s for s in states if s["key"] == "temperature")
        self.assertEqual(temp["value"]["integer_value"], "200")

    def test_off_state(self):
        entity = HvacHeaterEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("off"))
        result = entity.to_sber_current_state()
        states = result["climate.heater"]["states"]
        on_off = next(s for s in states if s["key"] == "on_off")
        self.assertFalse(on_off["value"]["bool_value"])


class TestHvacHeaterProcessCmd(unittest.TestCase):
    """Test process_cmd."""

    def test_set_temperature(self):
        entity = HvacHeaterEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("heat"))
        result = entity.process_cmd({
            "states": [{"key": "hvac_temp_set", "value": {"type": "INTEGER", "integer_value": "30"}}]
        })
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["url"]["service"], "set_temperature")
        self.assertEqual(result[0]["url"]["service_data"]["temperature"], 30.0)
