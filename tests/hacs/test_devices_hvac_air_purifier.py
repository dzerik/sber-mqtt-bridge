"""Tests for HvacAirPurifierEntity -- Sber air purifier device mapping."""

import unittest

from custom_components.sber_mqtt_bridge.devices.hvac_air_purifier import HvacAirPurifierEntity


ENTITY_DATA = {"entity_id": "fan.air_purifier", "name": "Air Purifier"}


def _make_ha_state(state="on", **attrs):
    return {
        "entity_id": "fan.air_purifier",
        "state": state,
        "attributes": attrs,
    }


class TestHvacAirPurifierCreate(unittest.TestCase):
    """Test HvacAirPurifierEntity initialization."""

    def test_category(self):
        entity = HvacAirPurifierEntity(ENTITY_DATA)
        self.assertEqual(entity.category, "hvac_air_purifier")

    def test_initial_state(self):
        entity = HvacAirPurifierEntity(ENTITY_DATA)
        self.assertFalse(entity.current_state)

    def test_features_list(self):
        entity = HvacAirPurifierEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state())
        features = entity.create_features_list()
        self.assertIn("online", features)
        self.assertIn("on_off", features)
        self.assertIn("hvac_air_flow_power", features)
        self.assertIn("hvac_ionization", features)
        self.assertIn("hvac_night_mode", features)
        self.assertIn("hvac_aromatization", features)
        self.assertIn("hvac_replace_filter", features)
        self.assertIn("hvac_replace_ionizator", features)


class TestHvacAirPurifierFillState(unittest.TestCase):
    """Test fill_by_ha_state."""

    def test_on_state(self):
        entity = HvacAirPurifierEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("on"))
        self.assertTrue(entity.current_state)

    def test_off_state(self):
        entity = HvacAirPurifierEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("off"))
        self.assertFalse(entity.current_state)

    def test_reads_bool_attrs(self):
        entity = HvacAirPurifierEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("on", ionization=True, night_mode=True))
        self.assertTrue(entity._ionization)
        self.assertTrue(entity._night_mode)


class TestHvacAirPurifierToSberCurrentState(unittest.TestCase):
    """Test to_sber_current_state."""

    def test_on_with_preset_mode(self):
        entity = HvacAirPurifierEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("on", preset_mode="high", preset_modes=["low", "high"]))
        result = entity.to_sber_current_state()
        states = result["fan.air_purifier"]["states"]
        on_off = next(s for s in states if s["key"] == "on_off")
        self.assertTrue(on_off["value"]["bool_value"])
        speed = next(s for s in states if s["key"] == "hvac_air_flow_power")
        self.assertEqual(speed["value"]["enum_value"], "high")

    def test_off_state(self):
        entity = HvacAirPurifierEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("off"))
        result = entity.to_sber_current_state()
        states = result["fan.air_purifier"]["states"]
        on_off = next(s for s in states if s["key"] == "on_off")
        self.assertFalse(on_off["value"]["bool_value"])

    def test_bool_features_in_state(self):
        entity = HvacAirPurifierEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("on", ionization=True, aromatization=True))
        result = entity.to_sber_current_state()
        states = result["fan.air_purifier"]["states"]
        ionization = next(s for s in states if s["key"] == "hvac_ionization")
        self.assertTrue(ionization["value"]["bool_value"])
        aroma = next(s for s in states if s["key"] == "hvac_aromatization")
        self.assertTrue(aroma["value"]["bool_value"])

    def test_unavailable_offline(self):
        entity = HvacAirPurifierEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("unavailable"))
        result = entity.to_sber_current_state()
        states = result["fan.air_purifier"]["states"]
        online = next(s for s in states if s["key"] == "online")
        self.assertFalse(online["value"]["bool_value"])


class TestHvacAirPurifierProcessCmd(unittest.TestCase):
    """Test process_cmd."""

    def _make_entity(self, state="on", **attrs):
        entity = HvacAirPurifierEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(state, **attrs))
        return entity

    def test_cmd_turn_on(self):
        entity = self._make_entity("off")
        result = entity.process_cmd({"states": [{"key": "on_off", "value": {"type": "BOOL", "bool_value": True}}]})
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["url"]["service"], "turn_on")
        self.assertEqual(result[0]["url"]["domain"], "fan")

    def test_cmd_turn_off(self):
        entity = self._make_entity("on")
        result = entity.process_cmd({"states": [{"key": "on_off", "value": {"type": "BOOL", "bool_value": False}}]})
        self.assertEqual(result[0]["url"]["service"], "turn_off")

    def test_cmd_set_preset_mode(self):
        entity = self._make_entity("on", preset_modes=["low", "medium", "high"])
        result = entity.process_cmd(
            {"states": [{"key": "hvac_air_flow_power", "value": {"type": "ENUM", "enum_value": "medium"}}]}
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["url"]["service"], "set_preset_mode")

    def test_cmd_set_percentage_fallback(self):
        entity = self._make_entity("on", preset_modes=[])
        result = entity.process_cmd(
            {"states": [{"key": "hvac_air_flow_power", "value": {"type": "ENUM", "enum_value": "high"}}]}
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["url"]["service"], "set_percentage")
        self.assertEqual(result[0]["url"]["service_data"]["percentage"], 75)

    def test_cmd_empty_states(self):
        entity = self._make_entity()
        result = entity.process_cmd({"states": []})
        self.assertEqual(result, [])


class TestHvacAirPurifierAllowedValues(unittest.TestCase):
    """Test allowed values in to_sber_state."""

    def test_allowed_values_present(self):
        entity = HvacAirPurifierEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("on"))
        result = entity.to_sber_state()
        allowed = result["model"]["allowed_values"]
        self.assertIn("hvac_air_flow_power", allowed)
        values = allowed["hvac_air_flow_power"]["enum_values"]["values"]
        self.assertIn("auto", values)
        self.assertIn("high", values)
