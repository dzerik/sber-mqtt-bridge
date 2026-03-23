"""Tests for KettleEntity -- Sber kettle device mapping."""

import unittest

from custom_components.sber_mqtt_bridge.devices.kettle import KettleEntity


ENTITY_DATA = {"entity_id": "water_heater.kettle", "name": "Kitchen Kettle"}


def _make_ha_state(state="idle", **attrs):
    return {
        "entity_id": "water_heater.kettle",
        "state": state,
        "attributes": attrs,
    }


class TestKettleCreate(unittest.TestCase):
    """Test KettleEntity initialization."""

    def test_category(self):
        entity = KettleEntity(ENTITY_DATA)
        self.assertEqual(entity.category, "kettle")

    def test_initial_state(self):
        entity = KettleEntity(ENTITY_DATA)
        self.assertFalse(entity.current_state)

    def test_features_list(self):
        entity = KettleEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state())
        features = entity.create_features_list()
        self.assertIn("online", features)
        self.assertIn("on_off", features)
        self.assertIn("kitchen_water_temperature", features)
        self.assertIn("kitchen_water_temperature_set", features)
        self.assertIn("kitchen_water_low_level", features)
        self.assertIn("child_lock", features)


class TestKettleFillState(unittest.TestCase):
    """Test fill_by_ha_state."""

    def test_heating_state(self):
        entity = KettleEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("heating", current_temperature=75, temperature=100))
        self.assertTrue(entity.current_state)
        self.assertEqual(entity._current_temperature, 75)
        self.assertEqual(entity._target_temperature, 100)

    def test_idle_state(self):
        entity = KettleEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("idle"))
        self.assertFalse(entity.current_state)

    def test_off_state(self):
        entity = KettleEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("off"))
        self.assertFalse(entity.current_state)


class TestKettleToSberCurrentState(unittest.TestCase):
    """Test to_sber_current_state."""

    def test_with_temperature(self):
        entity = KettleEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("heating", current_temperature=85, temperature=100))
        result = entity.to_sber_current_state()
        states = result["water_heater.kettle"]["states"]
        temp = next(s for s in states if s["key"] == "kitchen_water_temperature")
        self.assertEqual(temp["value"]["integer_value"], "85")
        target = next(s for s in states if s["key"] == "kitchen_water_temperature_set")
        self.assertEqual(target["value"]["integer_value"], "100")

    def test_low_water_level_heuristic(self):
        entity = KettleEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("idle", current_temperature=25))
        result = entity.to_sber_current_state()
        states = result["water_heater.kettle"]["states"]
        low = next(s for s in states if s["key"] == "kitchen_water_low_level")
        self.assertTrue(low["value"]["bool_value"])

    def test_not_low_water_level(self):
        entity = KettleEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("heating", current_temperature=50))
        result = entity.to_sber_current_state()
        states = result["water_heater.kettle"]["states"]
        low = next(s for s in states if s["key"] == "kitchen_water_low_level")
        self.assertFalse(low["value"]["bool_value"])

    def test_unavailable_offline(self):
        entity = KettleEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("unavailable"))
        result = entity.to_sber_current_state()
        states = result["water_heater.kettle"]["states"]
        online = next(s for s in states if s["key"] == "online")
        self.assertFalse(online["value"]["bool_value"])


class TestKettleProcessCmd(unittest.TestCase):
    """Test process_cmd."""

    def _make_entity(self, state="idle", **attrs):
        entity = KettleEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(state, **attrs))
        return entity

    def test_cmd_turn_on(self):
        entity = self._make_entity("off")
        result = entity.process_cmd({"states": [{"key": "on_off", "value": {"type": "BOOL", "bool_value": True}}]})
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["url"]["service"], "turn_on")
        self.assertEqual(result[0]["url"]["domain"], "water_heater")

    def test_cmd_turn_off(self):
        entity = self._make_entity("heating")
        result = entity.process_cmd({"states": [{"key": "on_off", "value": {"type": "BOOL", "bool_value": False}}]})
        self.assertEqual(result[0]["url"]["service"], "turn_off")

    def test_cmd_set_temperature(self):
        entity = self._make_entity("heating")
        result = entity.process_cmd(
            {"states": [{"key": "kitchen_water_temperature_set", "value": {"type": "INTEGER", "integer_value": "80"}}]}
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["url"]["service"], "set_temperature")
        self.assertEqual(result[0]["url"]["service_data"]["temperature"], 80)

    def test_cmd_empty_states(self):
        entity = self._make_entity()
        result = entity.process_cmd({"states": []})
        self.assertEqual(result, [])


class TestKettleAllowedValues(unittest.TestCase):
    """Test allowed values in to_sber_state."""

    def test_allowed_values_present(self):
        entity = KettleEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("idle"))
        result = entity.to_sber_state()
        allowed = result["model"]["allowed_values"]
        self.assertIn("kitchen_water_temperature_set", allowed)
        vals = allowed["kitchen_water_temperature_set"]["integer_values"]
        self.assertEqual(vals["min"], "60")
        self.assertEqual(vals["max"], "100")
        self.assertEqual(vals["step"], "10")
