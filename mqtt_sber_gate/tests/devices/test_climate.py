import unittest
from devices.climate import ClimateEntity

ENTITY_DATA = {
    "entity_id": "climate.living_room_ac",
    "name": "Living Room AC",
    "original_name": "Air Conditioner",
    "device_id": "dev_ac_001",
    "area_id": "living_room",
    "platform": "test",
}

HA_STATE = {
    "entity_id": "climate.living_room_ac",
    "state": "cool",
    "attributes": {
        "current_temperature": 26.5,
        "temperature": 24.0,
        "fan_modes": ["auto", "low", "medium", "high"],
        "swing_modes": ["off", "vertical"],
        "hvac_modes": ["off", "cool", "heat", "auto"],
        "fan_mode": "auto",
        "swing_mode": "off",
        "min_temp": 16,
        "max_temp": 30,
        "friendly_name": "Living Room AC",
    },
}


class TestClimateEntity(unittest.TestCase):

    def setUp(self):
        self.entity = ClimateEntity(ENTITY_DATA)

    def test_construction(self):
        self.assertEqual(self.entity.category, "hvac_ac")
        self.assertEqual(self.entity.entity_id, "climate.living_room_ac")

    def test_fill_by_ha_state(self):
        self.entity.fill_by_ha_state(HA_STATE)
        self.assertTrue(self.entity.current_state)
        self.assertEqual(self.entity.temperature, 26.5)
        self.assertEqual(self.entity.target_temperature, 24.0)
        self.assertEqual(self.entity.fan_mode, "auto")
        self.assertEqual(self.entity.hvac_mode, "cool")
        self.assertEqual(self.entity.fan_modes, ["auto", "low", "medium", "high"])

    def test_create_features_list(self):
        self.entity.fill_by_ha_state(HA_STATE)
        features = self.entity.create_features_list()
        self.assertIn("on_off", features)
        self.assertIn("temperature", features)
        self.assertIn("hvac_temp_set", features)
        self.assertIn("hvac_air_flow_power", features)
        self.assertIn("hvac_air_flow_direction", features)
        self.assertIn("hvac_work_mode", features)

    def test_create_allowed_values_list(self):
        self.entity.fill_by_ha_state(HA_STATE)
        allowed = self.entity.create_allowed_values_list()
        self.assertIn("hvac_air_flow_power", allowed)
        self.assertEqual(allowed["hvac_air_flow_power"]["enum_values"]["values"], ["auto", "low", "medium", "high"])

    def test_to_sber_current_state(self):
        self.entity.fill_by_ha_state(HA_STATE)
        result = self.entity.to_sber_current_state()
        states = result["climate.living_room_ac"]["states"]
        temp = next(s for s in states if s["key"] == "temperature")
        self.assertEqual(temp["value"]["integer_value"], 265)
        hvac_set = next(s for s in states if s["key"] == "hvac_temp_set")
        self.assertEqual(hvac_set["value"]["integer_value"], 240)

    def test_process_cmd_on_off(self):
        cmd = {"states": [{"key": "on_off", "value": {"type": "BOOL", "bool_value": True}}]}
        results = self.entity.process_cmd(cmd)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["url"]["service"], "turn_on")

    def test_process_cmd_temperature(self):
        cmd = {"states": [{"key": "hvac_temp_set", "value": {"type": "INTEGER", "integer_value": 250}}]}
        results = self.entity.process_cmd(cmd)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["url"]["service"], "set_temperature")
        self.assertEqual(results[0]["url"]["service_data"]["temperature"], 25.0)

    def test_process_cmd_fan_mode(self):
        cmd = {"states": [{"key": "hvac_air_flow_power", "value": {"type": "ENUM", "enum_value": "high"}}]}
        results = self.entity.process_cmd(cmd)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["url"]["service"], "set_fan_mode")
        self.assertEqual(results[0]["url"]["service_data"]["fan_mode"], "high")

    def test_process_cmd_returns_list(self):
        cmd = {"states": []}
        results = self.entity.process_cmd(cmd)
        self.assertIsInstance(results, list)

    def test_process_state_change(self):
        self.entity.process_state_change(HA_STATE, HA_STATE)
        self.assertTrue(self.entity.current_state)


if __name__ == "__main__":
    unittest.main()
