import unittest
from devices.humidifier import HumidifierEntity

ENTITY_DATA = {
    "entity_id": "humidifier.bedroom",
    "name": "Bedroom Humidifier",
    "original_name": "Humidifier",
    "device_id": "dev_hum_001",
    "area_id": "bedroom",
    "platform": "test",
}

HA_STATE = {
    "entity_id": "humidifier.bedroom",
    "state": "on",
    "attributes": {
        "humidity": 55,
        "current_humidity": 42,
        "available_modes": ["normal", "eco", "sleep"],
        "mode": "normal",
    },
}


class TestHumidifierEntity(unittest.TestCase):

    def setUp(self):
        self.entity = HumidifierEntity(ENTITY_DATA)

    def test_construction(self):
        self.assertEqual(self.entity.category, "hvac_humidifier")

    def test_fill_by_ha_state(self):
        self.entity.fill_by_ha_state(HA_STATE)
        self.assertTrue(self.entity.current_state)
        self.assertEqual(self.entity.target_humidity, 55)
        self.assertEqual(self.entity.current_humidity, 42)
        self.assertEqual(self.entity.mode, "normal")

    def test_create_features_list(self):
        self.entity.fill_by_ha_state(HA_STATE)
        features = self.entity.create_features_list()
        self.assertIn("on_off", features)
        self.assertIn("humidity", features)
        self.assertIn("hvac_work_mode", features)

    def test_process_cmd_on_off(self):
        cmd = {"states": [{"key": "on_off", "value": {"type": "BOOL", "bool_value": True}}]}
        results = self.entity.process_cmd(cmd)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["url"]["service"], "turn_on")

    def test_process_cmd_humidity(self):
        cmd = {"states": [{"key": "humidity", "value": {"type": "INTEGER", "integer_value": 600}}]}
        results = self.entity.process_cmd(cmd)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["url"]["service"], "set_humidity")
        self.assertEqual(results[0]["url"]["service_data"]["humidity"], 60)

    def test_process_cmd_mode(self):
        cmd = {"states": [{"key": "hvac_work_mode", "value": {"type": "ENUM", "enum_value": "sleep"}}]}
        results = self.entity.process_cmd(cmd)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["url"]["service"], "set_mode")

    def test_to_sber_current_state(self):
        self.entity.fill_by_ha_state(HA_STATE)
        result = self.entity.to_sber_current_state()
        states = result["humidifier.bedroom"]["states"]
        hum = next(s for s in states if s["key"] == "humidity")
        self.assertEqual(hum["value"]["integer_value"], 550)


if __name__ == "__main__":
    unittest.main()
