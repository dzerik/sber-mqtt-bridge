import unittest
import json
import copy

from devices.light import LightDevice


light_test_data_sber = {
    "id": "light.example_light",
    "manufacturer": "Unknown",
    "model": "Unknown",
    "hw_version": "Unknown",
    "sw_version": "Unknown",
    "description": "Example Light",
    "category": "light",
    "features": [
        "online",
        "on_off",
        "brightness",
        "color",
        "color_temperature"
    ],
    "allowed_values": {
        "brightness": {
            "type": "RANGE",
            "range_values": {"min": 0, "max": 100}
        },
        "color": {
            "type": "STRING",
            "string_values": {"format": "hex"}
        },
        "color_temperature": {
            "type": "RANGE",
            "range_values": {"min": 153, "max": 500}
        }
    }
}

light_test_data_ha = {
    "entity_id": "light.example_light",
    "state": "on",
    "attributes": {
        "brightness": 128,
        "color": "#ffccaa",
        "color_temp": 300,
        "supported_features": 7,  # 1 + 2 + 4
        "max_mireds": 500,
        "min_mireds": 153,
        "friendly_name": "Example Light"
    },
    "last_changed": "2025-08-18T02:00:05.350154+00:00",
    "last_reported": "2025-08-18T02:00:05.350154+00:00",
    "last_updated": "2025-08-18T02:00:05.350154+00:00",
    "context": {
        "id": "01K2XEFE8ZHSAAW109GZHEEDS2",
        "parent_id": None,
        "user_id": "1056ceca4bb04cab9885845a35d1d696"
    }
}


class TestLightDevice(unittest.TestCase):
    device = None

    def setUp(self):
        self.device = LightDevice(light_test_data_ha)

    def test_loading(self):
        self.assertEqual(self.device.id, "light.example_light")
        self.assertTrue(self.device.is_on)
        self.assertEqual(self.device.brightness, 50)  # 128 → 50%
        self.assertEqual(self.device.color, "#ffccaa")
        self.assertEqual(self.device.color_temperature, 300)

    def test_to_ha_state(self):
        ha_state = self.device.to_ha_state()
        assert ha_state == light_test_data_ha

    def test_to_sber(self):
        sber_state = self.device.to_sber_state()
        self.assertEqual(sber_state, light_test_data_sber)

    def test_process_cmd_on_off(self):
        cmd = self.device.process_cmd("sber", {"on_off": False})
        self.assertEqual(cmd["url"], "/api/services/light/turn_off")

    def test_process_cmd_brightness(self):
        cmd = self.device.process_cmd("sber", {"brightness": 75})
        self.assertEqual(cmd["url"], "/api/services/light/set_brightness")
        self.assertEqual(cmd["data"]["brightness"], 191)  # 75% → 191

    def test_process_cmd_color(self):
        cmd = self.device.process_cmd("sber", {"color": "#00ff00"})
        self.assertEqual(cmd["url"], "/api/services/light/turn_on")
        self.assertEqual(cmd["data"]["rgb_color"], (0, 255, 0))

    def test_process_cmd_color_temperature(self):
        cmd = self.device.process_cmd("sber", {"color_temperature": 400})
        self.assertEqual(cmd["url"], "/api/services/light/turn_on")
        self.assertEqual(cmd["data"]["color_temp"], 400)

    def test_unsupported_features(self):
        # Устройство без поддержки цвета
        ha_state_no_color = copy.deepcopy(light_test_data_ha)
        ha_state_no_color["attributes"]["supported_features"] = 1  # Только яркость
        device = LightDevice(ha_state_no_color)

        self.assertIsNone(device.color)
        # Попытка установить цвет
        with self.assertRaises(ValueError):
            device.color = "#00ff00"

    def test_color_attribute_handling(self):
        """Проверка обработки атрибута 'color'"""
        ha_state_with_color = copy.deepcopy(light_test_data_ha)
        ha_state_with_color["attributes"]["color"] = "#aabbcc"
        # del ha_state_with_color["attributes"]["rgb_color"]
        device = LightDevice(ha_state_with_color)
        self.assertEqual(device.color, "#aabbcc")

        ha_state_with_invalid_color = copy.deepcopy(light_test_data_ha)
        ha_state_with_invalid_color["attributes"]["color"] = "invalid"
        device = LightDevice(ha_state_with_invalid_color)
        self.assertIsNone(device.color)


if __name__ == '__main__':
    unittest.main()
