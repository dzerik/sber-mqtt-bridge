import unittest
from devices.door_sensor import DoorSensorEntity

ENTITY_DATA = {
    "entity_id": "binary_sensor.front_door",
    "name": "Front Door",
    "original_name": "Door",
    "device_id": "dev_door_001",
    "area_id": "hallway",
    "platform": "test",
}

HA_STATE_OPEN = {"entity_id": "binary_sensor.front_door", "state": "on", "attributes": {}}
HA_STATE_CLOSED = {"entity_id": "binary_sensor.front_door", "state": "off", "attributes": {}}


class TestDoorSensorEntity(unittest.TestCase):

    def setUp(self):
        self.entity = DoorSensorEntity(ENTITY_DATA)

    def test_construction(self):
        self.assertEqual(self.entity.category, "sensor_door")
        self.assertFalse(self.entity.is_open)

    def test_fill_open(self):
        self.entity.fill_by_ha_state(HA_STATE_OPEN)
        self.assertTrue(self.entity.is_open)

    def test_fill_closed(self):
        self.entity.fill_by_ha_state(HA_STATE_CLOSED)
        self.assertFalse(self.entity.is_open)

    def test_to_sber_current_state(self):
        self.entity.fill_by_ha_state(HA_STATE_OPEN)
        result = self.entity.to_sber_current_state()
        states = result["binary_sensor.front_door"]["states"]
        door = next(s for s in states if s["key"] == "doorcontact_state")
        self.assertEqual(door["value"]["enum_value"], "open")

    def test_process_cmd_returns_empty(self):
        self.assertEqual(self.entity.process_cmd({}), [])


if __name__ == "__main__":
    unittest.main()
