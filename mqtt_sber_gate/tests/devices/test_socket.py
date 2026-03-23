import unittest
from devices.socket_entity import SocketEntity


ENTITY_DATA = {
    "entity_id": "switch.kitchen_outlet",
    "name": "Kitchen Outlet",
    "original_name": "Outlet",
    "device_id": "dev_out_001",
    "area_id": "kitchen",
    "original_device_class": "outlet",
    "platform": "test",
}


class TestSocketEntity(unittest.TestCase):

    def setUp(self):
        self.entity = SocketEntity(ENTITY_DATA)

    def test_construction(self):
        self.assertEqual(self.entity.category, "socket")
        self.assertEqual(self.entity.entity_id, "switch.kitchen_outlet")

    def test_inherits_relay_behavior(self):
        features = self.entity.create_features_list()
        self.assertIn("on_off", features)

    def test_process_cmd(self):
        cmd = {"states": [{"key": "on_off", "value": {"type": "BOOL", "bool_value": True}}]}
        results = self.entity.process_cmd(cmd)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["url"]["service"], "turn_on")


if __name__ == "__main__":
    unittest.main()
