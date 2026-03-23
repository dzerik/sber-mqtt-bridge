import unittest
from devices.motion_sensor import MotionSensorEntity


ENTITY_DATA = {
    "area_id": "hallway",
    "config_entry_id": "test_config",
    "device_id": "dev_003",
    "entity_id": "binary_sensor.hallway_motion",
    "name": "Hallway Motion",
    "original_name": "Motion",
    "platform": "test",
    "unique_id": "motion_001",
}

HA_STATE_ON = {
    "entity_id": "binary_sensor.hallway_motion",
    "state": "on",
    "attributes": {"device_class": "motion"},
}

HA_STATE_OFF = {
    "entity_id": "binary_sensor.hallway_motion",
    "state": "off",
    "attributes": {"device_class": "motion"},
}


class TestMotionSensorEntity(unittest.TestCase):

    def setUp(self):
        self.entity = MotionSensorEntity(ENTITY_DATA)

    def test_construction(self):
        self.assertEqual(self.entity.category, "sensor_pir")
        self.assertFalse(self.entity.motion_detected)

    def test_fill_by_ha_state_on(self):
        self.entity.fill_by_ha_state(HA_STATE_ON)
        self.assertTrue(self.entity.motion_detected)

    def test_fill_by_ha_state_off(self):
        self.entity.fill_by_ha_state(HA_STATE_OFF)
        self.assertFalse(self.entity.motion_detected)

    def test_create_features_list(self):
        features = self.entity.create_features_list()
        self.assertIn("online", features)
        self.assertIn("pir", features)

    def test_to_sber_current_state(self):
        self.entity.fill_by_ha_state(HA_STATE_ON)
        result = self.entity.to_sber_current_state()
        states = result["binary_sensor.hallway_motion"]["states"]
        pir_state = next(s for s in states if s["key"] == "pir")
        self.assertTrue(pir_state["value"]["bool_value"])

    def test_process_cmd_returns_empty(self):
        self.assertEqual(self.entity.process_cmd({}), [])

    def test_process_state_change(self):
        self.entity.process_state_change(HA_STATE_OFF, HA_STATE_ON)
        self.assertTrue(self.entity.motion_detected)


if __name__ == "__main__":
    unittest.main()
