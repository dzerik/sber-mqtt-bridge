"""Tests for ClimateEntity — Sber HVAC/AC device mapping."""

import unittest

from custom_components.sber_mqtt_bridge.devices.climate import ClimateEntity


ENTITY_DATA = {"entity_id": "climate.ac", "name": "AC"}


def _make_ha_state(
    state="cool",
    current_temperature=24.5,
    temperature=22.0,
    fan_modes=None,
    swing_modes=None,
    hvac_modes=None,
    fan_mode="auto",
    swing_mode="off",
    min_temp=16.0,
    max_temp=32.0,
):
    if fan_modes is None:
        fan_modes = ["auto", "low", "medium", "high"]
    if swing_modes is None:
        swing_modes = ["off", "vertical", "horizontal"]
    if hvac_modes is None:
        hvac_modes = ["off", "cool", "heat", "fan_only", "dry"]
    return {
        "entity_id": "climate.ac",
        "state": state,
        "attributes": {
            "current_temperature": current_temperature,
            "temperature": temperature,
            "fan_modes": fan_modes,
            "swing_modes": swing_modes,
            "hvac_modes": hvac_modes,
            "fan_mode": fan_mode,
            "swing_mode": swing_mode,
            "min_temp": min_temp,
            "max_temp": max_temp,
        },
    }


class TestClimateInit(unittest.TestCase):
    """Test ClimateEntity initialization."""

    def test_init_defaults(self):
        entity = ClimateEntity(ENTITY_DATA)
        self.assertEqual(entity.category, "hvac_ac")
        self.assertEqual(entity.entity_id, "climate.ac")
        self.assertFalse(entity.current_state)
        self.assertIsNone(entity.temperature)
        self.assertIsNone(entity.target_temperature)
        self.assertEqual(entity.fan_modes, [])
        self.assertEqual(entity.swing_modes, [])
        self.assertEqual(entity.hvac_modes, [])


class TestClimateFillByHaState(unittest.TestCase):
    """Test fill_by_ha_state parses HA climate attributes."""

    def test_fill_basic(self):
        entity = ClimateEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state())
        self.assertTrue(entity.current_state)  # "cool" != "off"
        self.assertEqual(entity.temperature, 24.5)
        self.assertEqual(entity.target_temperature, 22.0)
        self.assertEqual(entity.fan_mode, "auto")
        self.assertEqual(entity.swing_mode, "off")
        self.assertEqual(entity.hvac_mode, "cool")
        self.assertEqual(entity.min_temp, 16.0)
        self.assertEqual(entity.max_temp, 32.0)

    def test_fill_off_state(self):
        entity = ClimateEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(state="off"))
        self.assertFalse(entity.current_state)

    def test_fill_heat_state(self):
        entity = ClimateEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(state="heat"))
        self.assertTrue(entity.current_state)
        self.assertEqual(entity.hvac_mode, "heat")

    def test_fill_fan_modes(self):
        entity = ClimateEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(fan_modes=["low", "high"]))
        self.assertEqual(entity.fan_modes, ["low", "high"])

    def test_fill_no_optional_attributes(self):
        """Missing attributes use defaults."""
        entity = ClimateEntity(ENTITY_DATA)
        entity.fill_by_ha_state({
            "entity_id": "climate.ac",
            "state": "off",
            "attributes": {},
        })
        self.assertFalse(entity.current_state)
        self.assertIsNone(entity.temperature)
        self.assertIsNone(entity.target_temperature)
        self.assertEqual(entity.fan_modes, [])


class TestClimateCreateFeaturesList(unittest.TestCase):
    """Test create_features_list with various capabilities."""

    def test_all_modes_present(self):
        entity = ClimateEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state())
        features = entity.create_features_list()
        self.assertIn("on_off", features)
        self.assertIn("temperature", features)
        self.assertIn("hvac_temp_set", features)
        self.assertIn("hvac_air_flow_direction", features)
        self.assertIn("hvac_air_flow_power", features)
        self.assertIn("hvac_work_mode", features)
        self.assertIn("online", features)

    def test_no_fan_modes(self):
        entity = ClimateEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(fan_modes=[]))
        features = entity.create_features_list()
        self.assertNotIn("hvac_air_flow_power", features)

    def test_no_swing_modes(self):
        entity = ClimateEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(swing_modes=[]))
        features = entity.create_features_list()
        self.assertNotIn("hvac_air_flow_direction", features)

    def test_no_hvac_modes(self):
        entity = ClimateEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(hvac_modes=[]))
        features = entity.create_features_list()
        self.assertNotIn("hvac_work_mode", features)


class TestClimateCreateAllowedValues(unittest.TestCase):
    """Test create_allowed_values_list."""

    def test_all_modes(self):
        entity = ClimateEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state())
        av = entity.create_allowed_values_list()
        self.assertIn("hvac_air_flow_power", av)
        self.assertIn("hvac_air_flow_direction", av)
        self.assertIn("hvac_work_mode", av)
        self.assertEqual(av["hvac_air_flow_power"]["type"], "ENUM")
        self.assertEqual(
            av["hvac_air_flow_power"]["enum_values"]["values"],
            ["auto", "low", "medium", "high"],
        )

    def test_empty_modes(self):
        entity = ClimateEntity(ENTITY_DATA)
        entity.fill_by_ha_state(
            _make_ha_state(fan_modes=[], swing_modes=[], hvac_modes=[])
        )
        av = entity.create_allowed_values_list()
        self.assertEqual(av, {})


class TestClimateToSberCurrentState(unittest.TestCase):
    """Test to_sber_current_state builds correct Sber payload."""

    def test_full_state(self):
        entity = ClimateEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state())
        result = entity.to_sber_current_state()
        self.assertIn("climate.ac", result)
        states = result["climate.ac"]["states"]
        keys = [s["key"] for s in states]

        self.assertIn("online", keys)
        self.assertIn("on_off", keys)
        self.assertIn("temperature", keys)
        self.assertIn("hvac_temp_set", keys)
        self.assertIn("hvac_air_flow_power", keys)
        self.assertIn("hvac_air_flow_direction", keys)
        self.assertIn("hvac_work_mode", keys)

        online = next(s for s in states if s["key"] == "online")
        self.assertTrue(online["value"]["bool_value"])

        temp = next(s for s in states if s["key"] == "temperature")
        self.assertEqual(temp["value"]["integer_value"], "245")  # 24.5 * 10, as string per spec

        temp_set = next(s for s in states if s["key"] == "hvac_temp_set")
        self.assertEqual(temp_set["value"]["integer_value"], "22")  # whole degrees, as string per spec

    def test_unavailable_state(self):
        entity = ClimateEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(state="unavailable"))
        result = entity.to_sber_current_state()
        states = result["climate.ac"]["states"]
        online = next(s for s in states if s["key"] == "online")
        self.assertFalse(online["value"]["bool_value"])

    def test_no_temperature(self):
        entity = ClimateEntity(ENTITY_DATA)
        entity.fill_by_ha_state({
            "entity_id": "climate.ac",
            "state": "cool",
            "attributes": {"fan_mode": "auto"},
        })
        result = entity.to_sber_current_state()
        states = result["climate.ac"]["states"]
        keys = [s["key"] for s in states]
        self.assertNotIn("temperature", keys)
        self.assertNotIn("hvac_temp_set", keys)

    def test_off_state_on_off_false(self):
        entity = ClimateEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(state="off"))
        result = entity.to_sber_current_state()
        states = result["climate.ac"]["states"]
        on_off = next(s for s in states if s["key"] == "on_off")
        self.assertFalse(on_off["value"]["bool_value"])


class TestClimateProcessCmd(unittest.TestCase):
    """Test process_cmd dispatches HA service calls."""

    def _make_entity(self):
        entity = ClimateEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state())
        return entity

    def test_cmd_on_off_turn_on(self):
        entity = self._make_entity()
        result = entity.process_cmd({
            "states": [{"key": "on_off", "value": {"bool_value": True}}]
        })
        self.assertEqual(len(result), 1)
        url = result[0]["url"]
        self.assertEqual(url["domain"], "climate")
        self.assertEqual(url["service"], "turn_on")

    def test_cmd_on_off_turn_off(self):
        entity = self._make_entity()
        result = entity.process_cmd({
            "states": [{"key": "on_off", "value": {"bool_value": False}}]
        })
        url = result[0]["url"]
        self.assertEqual(url["service"], "turn_off")

    def test_cmd_hvac_temp_set(self):
        entity = self._make_entity()
        result = entity.process_cmd({
            "states": [{"key": "hvac_temp_set", "value": {"integer_value": 25}}]
        })
        url = result[0]["url"]
        self.assertEqual(url["service"], "set_temperature")
        self.assertEqual(url["service_data"]["temperature"], 25.0)

    def test_cmd_fan_mode_valid(self):
        entity = self._make_entity()
        result = entity.process_cmd({
            "states": [{"key": "hvac_air_flow_power", "value": {"enum_value": "low"}}]
        })
        url = result[0]["url"]
        self.assertEqual(url["service"], "set_fan_mode")
        self.assertEqual(url["service_data"]["fan_mode"], "low")

    def test_cmd_fan_mode_invalid_rejected(self):
        """Invalid fan mode not in allowed list is rejected."""
        entity = self._make_entity()
        result = entity.process_cmd({
            "states": [{"key": "hvac_air_flow_power", "value": {"enum_value": "turbo"}}]
        })
        self.assertEqual(len(result), 0)

    def test_cmd_swing_mode_valid(self):
        entity = self._make_entity()
        result = entity.process_cmd({
            "states": [{"key": "hvac_air_flow_direction", "value": {"enum_value": "vertical"}}]
        })
        url = result[0]["url"]
        self.assertEqual(url["service"], "set_swing_mode")
        self.assertEqual(url["service_data"]["swing_mode"], "vertical")

    def test_cmd_swing_mode_invalid_rejected(self):
        entity = self._make_entity()
        result = entity.process_cmd({
            "states": [{"key": "hvac_air_flow_direction", "value": {"enum_value": "3d"}}]
        })
        self.assertEqual(len(result), 0)

    def test_cmd_hvac_mode_valid(self):
        entity = self._make_entity()
        result = entity.process_cmd({
            "states": [{"key": "hvac_work_mode", "value": {"enum_value": "heat"}}]
        })
        url = result[0]["url"]
        self.assertEqual(url["service"], "set_hvac_mode")
        self.assertEqual(url["service_data"]["hvac_mode"], "heat")

    def test_cmd_hvac_mode_invalid_rejected(self):
        entity = self._make_entity()
        result = entity.process_cmd({
            "states": [{"key": "hvac_work_mode", "value": {"enum_value": "turbo_cool"}}]
        })
        self.assertEqual(len(result), 0)

    def test_cmd_empty_states(self):
        entity = self._make_entity()
        result = entity.process_cmd({"states": []})
        self.assertEqual(result, [])

    def test_cmd_multiple(self):
        entity = self._make_entity()
        result = entity.process_cmd({
            "states": [
                {"key": "on_off", "value": {"bool_value": True}},
                {"key": "hvac_temp_set", "value": {"integer_value": 20}},
                {"key": "hvac_air_flow_power", "value": {"enum_value": "high"}},
            ]
        })
        self.assertEqual(len(result), 3)

    def test_cmd_fan_mode_empty_list_accepts_any(self):
        """When fan_modes is empty, any mode is accepted."""
        entity = ClimateEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(fan_modes=[]))
        result = entity.process_cmd({
            "states": [{"key": "hvac_air_flow_power", "value": {"enum_value": "turbo"}}]
        })
        self.assertEqual(len(result), 1)


class TestClimateProcessStateChange(unittest.TestCase):
    """Test process_state_change delegates to fill_by_ha_state."""

    def test_state_change(self):
        entity = ClimateEntity(ENTITY_DATA)
        old = _make_ha_state(state="off")
        new = _make_ha_state(state="heat", temperature=26.0)
        entity.fill_by_ha_state(old)
        self.assertFalse(entity.current_state)
        entity.process_state_change(old, new)
        self.assertTrue(entity.current_state)
        self.assertEqual(entity.hvac_mode, "heat")
