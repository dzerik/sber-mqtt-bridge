import unittest
from devices.window_blind import WindowBlindEntity

ENTITY_DATA = {
    "entity_id": "cover.bedroom_blind",
    "name": "Bedroom Blind",
    "original_name": "Blind",
    "device_id": "dev_blind_001",
    "area_id": "bedroom",
    "platform": "test",
}

HA_STATE_OPEN = {
    "entity_id": "cover.bedroom_blind",
    "state": "open",
    "attributes": {"current_position": 75},
}


class TestWindowBlindEntity(unittest.TestCase):

    def setUp(self):
        self.entity = WindowBlindEntity(ENTITY_DATA)

    def test_construction(self):
        self.assertEqual(self.entity.category, "window_blind")

    def test_inherits_curtain_features(self):
        features = self.entity.create_features_list()
        self.assertIn("open_percentage", features)
        self.assertIn("open_set", features)
        self.assertIn("open_state", features)

    def test_fill_by_ha_state(self):
        self.entity.fill_by_ha_state(HA_STATE_OPEN)
        self.assertEqual(self.entity.current_position, 75)

    def test_process_cmd_open(self):
        cmd = {"states": [{"key": "open_set", "value": {"type": "ENUM", "enum_value": "open"}}]}
        results = self.entity.process_cmd(cmd)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["url"]["service"], "open_cover")


if __name__ == "__main__":
    unittest.main()
