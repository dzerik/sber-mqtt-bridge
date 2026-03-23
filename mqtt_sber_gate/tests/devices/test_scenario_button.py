import unittest
from devices.scenario_button import ScenarioButtonEntity


ENTITY_DATA = {
    "entity_id": "input_boolean.guest_mode",
    "name": "Guest Mode",
    "original_name": "Guest Mode",
    "device_id": "dev_ib_001",
    "area_id": "",
    "platform": "test",
}

HA_STATE_ON = {
    "entity_id": "input_boolean.guest_mode",
    "state": "on",
    "attributes": {},
}

HA_STATE_OFF = {
    "entity_id": "input_boolean.guest_mode",
    "state": "off",
    "attributes": {},
}


class TestScenarioButtonEntity(unittest.TestCase):

    def setUp(self):
        self.entity = ScenarioButtonEntity(ENTITY_DATA)

    def test_construction(self):
        self.assertEqual(self.entity.category, "scenario_button")

    def test_fill_on_state(self):
        self.entity.fill_by_ha_state(HA_STATE_ON)
        self.assertEqual(self.entity.button_event, "click")

    def test_fill_off_state(self):
        self.entity.fill_by_ha_state(HA_STATE_OFF)
        self.assertEqual(self.entity.button_event, "double_click")

    def test_create_features_list(self):
        features = self.entity.create_features_list()
        self.assertIn("button_event", features)

    def test_to_sber_current_state(self):
        self.entity.fill_by_ha_state(HA_STATE_ON)
        result = self.entity.to_sber_current_state()
        states = result["input_boolean.guest_mode"]["states"]
        btn = next(s for s in states if s["key"] == "button_event")
        self.assertEqual(btn["value"]["enum_value"], "click")

    def test_process_cmd_returns_empty(self):
        self.assertEqual(self.entity.process_cmd({}), [])


if __name__ == "__main__":
    unittest.main()
