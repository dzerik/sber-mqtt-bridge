import unittest
from devices.sensor_temp import SensorTempEntity


ENTITY_DATA = {
    "area_id": "living_room",
    "config_entry_id": "test_config",
    "device_id": "dev_001",
    "entity_id": "sensor.living_room_temperature",
    "name": "Living Room Temperature",
    "original_name": "Temperature",
    "platform": "test",
    "unique_id": "temp_001",
}

HA_STATE_NORMAL = {
    "entity_id": "sensor.living_room_temperature",
    "state": "22.5",
    "attributes": {
        "friendly_name": "Living Room Temperature",
        "device_class": "temperature",
        "unit_of_measurement": "\u00b0C",
    },
}

HA_STATE_UNAVAILABLE = {
    "entity_id": "sensor.living_room_temperature",
    "state": "unavailable",
    "attributes": {},
}


class TestSensorTempEntity(unittest.TestCase):

    def setUp(self):
        self.entity = SensorTempEntity(ENTITY_DATA)

    def test_construction(self):
        self.assertEqual(self.entity.category, "sensor_temp")
        self.assertEqual(self.entity.entity_id, "sensor.living_room_temperature")
        self.assertEqual(self.entity.temperature, 0.0)

    def test_fill_by_ha_state(self):
        self.entity.fill_by_ha_state(HA_STATE_NORMAL)
        self.assertEqual(self.entity.temperature, 22.5)
        self.assertTrue(self.entity.is_filled_by_state)

    def test_fill_by_ha_state_unavailable(self):
        self.entity.fill_by_ha_state(HA_STATE_UNAVAILABLE)
        self.assertEqual(self.entity.temperature, 0.0)
        self.assertEqual(self.entity.state, "unavailable")

    def test_create_features_list(self):
        features = self.entity.create_features_list()
        self.assertIn("online", features)
        self.assertIn("temperature", features)

    def test_to_sber_current_state(self):
        self.entity.fill_by_ha_state(HA_STATE_NORMAL)
        result = self.entity.to_sber_current_state()
        self.assertIn("sensor.living_room_temperature", result)
        states = result["sensor.living_room_temperature"]["states"]
        online_state = next(s for s in states if s["key"] == "online")
        temp_state = next(s for s in states if s["key"] == "temperature")
        self.assertTrue(online_state["value"]["bool_value"])
        self.assertEqual(temp_state["value"]["integer_value"], 225)

    def test_to_sber_current_state_unavailable(self):
        self.entity.fill_by_ha_state(HA_STATE_UNAVAILABLE)
        result = self.entity.to_sber_current_state()
        states = result["sensor.living_room_temperature"]["states"]
        online_state = next(s for s in states if s["key"] == "online")
        self.assertFalse(online_state["value"]["bool_value"])

    def test_process_cmd_returns_empty(self):
        result = self.entity.process_cmd({"states": []})
        self.assertEqual(result, [])

    def test_process_state_change(self):
        new_state = {
            "entity_id": "sensor.living_room_temperature",
            "state": "25.3",
            "attributes": {},
        }
        self.entity.process_state_change(HA_STATE_NORMAL, new_state)
        self.assertEqual(self.entity.temperature, 25.3)


if __name__ == "__main__":
    unittest.main()
