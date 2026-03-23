import unittest
from devices.hvac_radiator import HvacRadiatorEntity

ENTITY_DATA = {
    "entity_id": "climate.bedroom_radiator",
    "name": "Bedroom Radiator",
    "original_name": "Radiator",
    "device_id": "dev_rad_001",
    "area_id": "bedroom",
    "platform": "test",
}

HA_STATE = {
    "entity_id": "climate.bedroom_radiator",
    "state": "heat",
    "attributes": {
        "current_temperature": 22.0,
        "temperature": 28.0,
        "hvac_modes": ["off", "heat"],
        "min_temp": 20,
        "max_temp": 35,
    },
}


class TestHvacRadiatorEntity(unittest.TestCase):

    def setUp(self):
        self.entity = HvacRadiatorEntity(ENTITY_DATA)

    def test_construction(self):
        self.assertEqual(self.entity.category, "hvac_radiator")
        self.assertEqual(self.entity.min_temp, 25.0)
        self.assertEqual(self.entity.max_temp, 40.0)

    def test_inherits_climate_behavior(self):
        self.entity.fill_by_ha_state(HA_STATE)
        features = self.entity.create_features_list()
        self.assertIn("on_off", features)
        self.assertIn("temperature", features)
        self.assertIn("hvac_temp_set", features)

    def test_process_cmd(self):
        cmd = {"states": [{"key": "hvac_temp_set", "value": {"type": "INTEGER", "integer_value": 300}}]}
        results = self.entity.process_cmd(cmd)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["url"]["service_data"]["temperature"], 30.0)


if __name__ == "__main__":
    unittest.main()
