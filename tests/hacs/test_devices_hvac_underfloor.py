"""Tests for HvacUnderfloorEntity -- Sber underfloor heating device mapping."""

import unittest

from custom_components.sber_mqtt_bridge.devices.hvac_underfloor_heating import HvacUnderfloorEntity


ENTITY_DATA = {"entity_id": "climate.floor", "name": "Underfloor Heating"}


def _make_ha_state(state="heat", **attrs):
    base_attrs = {"current_temperature": 28.0, "temperature": 30.0}
    base_attrs.update(attrs)
    return {
        "entity_id": "climate.floor",
        "state": state,
        "attributes": base_attrs,
    }


class TestHvacUnderfloorCreate(unittest.TestCase):
    """Test HvacUnderfloorEntity initialization."""

    def test_category(self):
        entity = HvacUnderfloorEntity(ENTITY_DATA)
        self.assertEqual(entity.category, "hvac_underfloor_heating")

    def test_temp_defaults(self):
        entity = HvacUnderfloorEntity(ENTITY_DATA)
        self.assertEqual(entity.min_temp, 25.0)
        self.assertEqual(entity.max_temp, 50.0)

    def test_inherits_climate(self):
        from custom_components.sber_mqtt_bridge.devices.climate import ClimateEntity

        entity = HvacUnderfloorEntity(ENTITY_DATA)
        self.assertIsInstance(entity, ClimateEntity)


class TestHvacUnderfloorToSberCurrentState(unittest.TestCase):
    """Test to_sber_current_state."""

    def test_basic_state(self):
        entity = HvacUnderfloorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("heat"))
        result = entity.to_sber_current_state()
        states = result["climate.floor"]["states"]
        on_off = next(s for s in states if s["key"] == "on_off")
        self.assertTrue(on_off["value"]["bool_value"])

    def test_off_state(self):
        entity = HvacUnderfloorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("off"))
        result = entity.to_sber_current_state()
        states = result["climate.floor"]["states"]
        on_off = next(s for s in states if s["key"] == "on_off")
        self.assertFalse(on_off["value"]["bool_value"])


class TestHvacUnderfloorProcessCmd(unittest.TestCase):
    """Test process_cmd."""

    def test_set_temperature(self):
        entity = HvacUnderfloorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("heat"))
        result = entity.process_cmd({
            "states": [{"key": "hvac_temp_set", "value": {"type": "INTEGER", "integer_value": "35"}}]
        })
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["url"]["service_data"]["temperature"], 35.0)
