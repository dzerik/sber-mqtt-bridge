import unittest
from devices.water_leak_sensor import WaterLeakSensorEntity

ENTITY_DATA = {
    "entity_id": "binary_sensor.kitchen_leak",
    "name": "Kitchen Leak",
    "original_name": "Leak",
    "device_id": "dev_leak_001",
    "area_id": "kitchen",
    "platform": "test",
}

HA_STATE_LEAK = {"entity_id": "binary_sensor.kitchen_leak", "state": "on", "attributes": {}}
HA_STATE_DRY = {"entity_id": "binary_sensor.kitchen_leak", "state": "off", "attributes": {}}


class TestWaterLeakSensorEntity(unittest.TestCase):

    def setUp(self):
        self.entity = WaterLeakSensorEntity(ENTITY_DATA)

    def test_construction(self):
        self.assertEqual(self.entity.category, "sensor_water_leak")
        self.assertFalse(self.entity.leak_detected)

    def test_fill_leak(self):
        self.entity.fill_by_ha_state(HA_STATE_LEAK)
        self.assertTrue(self.entity.leak_detected)

    def test_to_sber_current_state(self):
        self.entity.fill_by_ha_state(HA_STATE_LEAK)
        result = self.entity.to_sber_current_state()
        states = result["binary_sensor.kitchen_leak"]["states"]
        leak = next(s for s in states if s["key"] == "water_leak")
        self.assertTrue(leak["value"]["bool_value"])

    def test_process_cmd_returns_empty(self):
        self.assertEqual(self.entity.process_cmd({}), [])


if __name__ == "__main__":
    unittest.main()
