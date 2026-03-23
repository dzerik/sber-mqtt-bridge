import unittest
from devices.humidity_sensor import HumiditySensorEntity


ENTITY_DATA = {
    "area_id": "bathroom",
    "config_entry_id": "test_config",
    "device_id": "dev_002",
    "entity_id": "sensor.bathroom_humidity",
    "name": "Bathroom Humidity",
    "original_name": "Humidity",
    "platform": "test",
    "unique_id": "hum_001",
}

HA_STATE_NORMAL = {
    "entity_id": "sensor.bathroom_humidity",
    "state": "65.2",
    "attributes": {
        "friendly_name": "Bathroom Humidity",
        "device_class": "humidity",
        "unit_of_measurement": "%",
    },
}


class TestHumiditySensorEntity(unittest.TestCase):

    def setUp(self):
        self.entity = HumiditySensorEntity(ENTITY_DATA)

    def test_construction(self):
        self.assertEqual(self.entity.category, "sensor_temp")
        self.assertEqual(self.entity.entity_id, "sensor.bathroom_humidity")

    def test_fill_by_ha_state(self):
        self.entity.fill_by_ha_state(HA_STATE_NORMAL)
        self.assertEqual(self.entity.humidity, 65.2)

    def test_create_features_list(self):
        features = self.entity.create_features_list()
        self.assertIn("online", features)
        self.assertIn("humidity", features)

    def test_to_sber_current_state(self):
        self.entity.fill_by_ha_state(HA_STATE_NORMAL)
        result = self.entity.to_sber_current_state()
        states = result["sensor.bathroom_humidity"]["states"]
        hum_state = next(s for s in states if s["key"] == "humidity")
        self.assertEqual(hum_state["value"]["integer_value"], 652)

    def test_process_cmd_returns_empty(self):
        self.assertEqual(self.entity.process_cmd({}), [])


if __name__ == "__main__":
    unittest.main()
