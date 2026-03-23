import unittest
from devices.relay import RelayEntity


SWITCH_ENTITY_DATA = {
    "entity_id": "switch.living_room_lamp",
    "name": "Living Room Lamp",
    "original_name": "Lamp",
    "device_id": "dev_sw_001",
    "area_id": "living_room",
    "platform": "test",
}

BUTTON_ENTITY_DATA = {
    "entity_id": "button.reboot_server",
    "name": "Reboot Server",
    "original_name": "Reboot",
    "device_id": "dev_btn_001",
    "area_id": "",
    "platform": "test",
}

HA_STATE_ON = {
    "entity_id": "switch.living_room_lamp",
    "state": "on",
    "attributes": {"friendly_name": "Living Room Lamp"},
}

HA_STATE_OFF = {
    "entity_id": "switch.living_room_lamp",
    "state": "off",
    "attributes": {"friendly_name": "Living Room Lamp"},
}

CMD_TURN_ON = {
    "states": [
        {"key": "on_off", "value": {"type": "BOOL", "bool_value": True}}
    ]
}

CMD_TURN_OFF = {
    "states": [
        {"key": "on_off", "value": {"type": "BOOL", "bool_value": False}}
    ]
}


class TestRelayEntity(unittest.TestCase):

    def setUp(self):
        self.entity = RelayEntity(SWITCH_ENTITY_DATA)

    def test_construction(self):
        self.assertEqual(self.entity.category, "relay")
        self.assertEqual(self.entity.entity_id, "switch.living_room_lamp")
        self.assertFalse(self.entity.current_state)

    def test_fill_by_ha_state(self):
        self.entity.fill_by_ha_state(HA_STATE_ON)
        self.assertTrue(self.entity.current_state)

    def test_create_features_list(self):
        features = self.entity.create_features_list()
        self.assertIn("online", features)
        self.assertIn("on_off", features)

    def test_to_sber_current_state(self):
        self.entity.fill_by_ha_state(HA_STATE_ON)
        result = self.entity.to_sber_current_state()
        states = result["switch.living_room_lamp"]["states"]
        on_off = next(s for s in states if s["key"] == "on_off")
        self.assertTrue(on_off["value"]["bool_value"])

    def test_process_cmd_turn_on(self):
        results = self.entity.process_cmd(CMD_TURN_ON)
        self.assertEqual(len(results), 1)
        cmd = results[0]["url"]
        self.assertEqual(cmd["domain"], "switch")
        self.assertEqual(cmd["service"], "turn_on")
        self.assertTrue(self.entity.current_state)

    def test_process_cmd_turn_off(self):
        self.entity.current_state = True
        results = self.entity.process_cmd(CMD_TURN_OFF)
        self.assertEqual(len(results), 1)
        cmd = results[0]["url"]
        self.assertEqual(cmd["service"], "turn_off")
        self.assertFalse(self.entity.current_state)

    def test_process_cmd_button_press(self):
        entity = RelayEntity(BUTTON_ENTITY_DATA)
        results = entity.process_cmd(CMD_TURN_ON)
        self.assertEqual(len(results), 1)
        cmd = results[0]["url"]
        self.assertEqual(cmd["domain"], "button")
        self.assertEqual(cmd["service"], "press")

    def test_process_state_change(self):
        self.entity.process_state_change(HA_STATE_OFF, HA_STATE_ON)
        self.assertTrue(self.entity.current_state)


if __name__ == "__main__":
    unittest.main()
