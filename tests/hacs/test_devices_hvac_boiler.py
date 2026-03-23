"""Tests for HvacBoilerEntity -- Sber boiler/water heater device mapping."""

import unittest

from custom_components.sber_mqtt_bridge.devices.hvac_boiler import HvacBoilerEntity


ENTITY_DATA = {"entity_id": "climate.boiler", "name": "Water Heater"}


def _make_ha_state(state="heat", **attrs):
    base_attrs = {"current_temperature": 45.0, "temperature": 60.0}
    base_attrs.update(attrs)
    return {
        "entity_id": "climate.boiler",
        "state": state,
        "attributes": base_attrs,
    }


class TestHvacBoilerCreate(unittest.TestCase):
    """Test HvacBoilerEntity initialization."""

    def test_category(self):
        entity = HvacBoilerEntity(ENTITY_DATA)
        self.assertEqual(entity.category, "hvac_boiler")

    def test_temp_defaults(self):
        entity = HvacBoilerEntity(ENTITY_DATA)
        self.assertEqual(entity.min_temp, 25.0)
        self.assertEqual(entity.max_temp, 80.0)

    def test_inherits_climate(self):
        from custom_components.sber_mqtt_bridge.devices.climate import ClimateEntity

        entity = HvacBoilerEntity(ENTITY_DATA)
        self.assertIsInstance(entity, ClimateEntity)


class TestHvacBoilerToSberCurrentState(unittest.TestCase):
    """Test to_sber_current_state."""

    def test_basic_state(self):
        entity = HvacBoilerEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("heat"))
        result = entity.to_sber_current_state()
        states = result["climate.boiler"]["states"]
        on_off = next(s for s in states if s["key"] == "on_off")
        self.assertTrue(on_off["value"]["bool_value"])
        temp_set = next(s for s in states if s["key"] == "hvac_temp_set")
        self.assertEqual(temp_set["value"]["integer_value"], "60")

    def test_off_state(self):
        entity = HvacBoilerEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("off"))
        result = entity.to_sber_current_state()
        states = result["climate.boiler"]["states"]
        on_off = next(s for s in states if s["key"] == "on_off")
        self.assertFalse(on_off["value"]["bool_value"])


class TestHvacBoilerProcessCmd(unittest.TestCase):
    """Test process_cmd."""

    def test_set_temperature(self):
        entity = HvacBoilerEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("heat"))
        result = entity.process_cmd({
            "states": [{"key": "hvac_temp_set", "value": {"type": "INTEGER", "integer_value": "70"}}]
        })
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["url"]["service_data"]["temperature"], 70.0)
