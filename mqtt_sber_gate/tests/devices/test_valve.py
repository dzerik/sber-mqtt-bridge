import unittest
from devices.valve import ValveEntity

ENTITY_DATA = {
    "entity_id": "valve.water_main",
    "name": "Water Main",
    "original_name": "Water Valve",
    "device_id": "dev_valve_001",
    "area_id": "utility",
    "platform": "test",
}

HA_STATE_OPEN = {"entity_id": "valve.water_main", "state": "open", "attributes": {}}
HA_STATE_CLOSED = {"entity_id": "valve.water_main", "state": "closed", "attributes": {}}


class TestValveEntity(unittest.TestCase):

    def setUp(self):
        self.entity = ValveEntity(ENTITY_DATA)

    def test_construction(self):
        self.assertEqual(self.entity.category, "valve")
        self.assertFalse(self.entity.current_state)

    def test_fill_open(self):
        self.entity.fill_by_ha_state(HA_STATE_OPEN)
        self.assertTrue(self.entity.current_state)

    def test_process_cmd_open(self):
        cmd = {"states": [{"key": "on_off", "value": {"type": "BOOL", "bool_value": True}}]}
        results = self.entity.process_cmd(cmd)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["url"]["service"], "open_valve")

    def test_process_cmd_close(self):
        cmd = {"states": [{"key": "on_off", "value": {"type": "BOOL", "bool_value": False}}]}
        results = self.entity.process_cmd(cmd)
        self.assertEqual(results[0]["url"]["service"], "close_valve")


if __name__ == "__main__":
    unittest.main()
