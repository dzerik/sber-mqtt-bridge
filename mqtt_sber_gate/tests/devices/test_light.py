import os
import unittest
import json
import copy

from devices.device_data import DeviceData
from devices.light import LightEntity
from devices_db import CDevicesDB, json_read
from mqtt_sber_gate.tests.devices.test_device_base import TestDevicesBase


class TestLightDevice(TestDevicesBase):

    def test_loading(self):
        entity = self.entities_list.get("light.liustra_sp_1")
        assert entity is not None
        assert entity.entity_id == "light.liustra_sp_1"
        assert entity.id == "0fced0c6b9560b346903450d934ee348"
        assert entity.device_id is not None
        device = self.devices_list.get(entity.device_id)
        assert device is not None
        assert device.area_id == "spalnia"
        assert device.manufacturer == "_TZ3210_zck1cpsj"

    def test_sber_data(self):
        entity = self.entities_list.get("light.liustra_sp_1")
        assert entity is not None
        device = self.devices_list.get(entity.device_id)
        assert device is not None
        entity.link_device(device)
        sber_state = entity.to_sber_state()
        sample_path = os.path.join(self.data_devices_path, "lights", "sber_device_light.json")
        abs_path = os.path.abspath(sample_path)
        if not os.path.exists(abs_path):
            assert False
        sber_state_sample = json_read(sample_path, None)
        assert sber_state_sample is not None
        self.assertDictEqual(sber_state_sample[0], sber_state)


    #     self.assertEqual(self.device.id, "light.example_light")
    #     self.assertTrue(self.device.is_on)
    #     self.assertEqual(self.device.brightness, 50)  # 128 → 50%
    #     self.assertEqual(self.device.color, "#ffccaa")
    #     self.assertEqual(self.device.color_temperature, 300)

    # def test_to_ha_state(self):
    #     ha_state = self.device.to_ha_state()
    #     assert ha_state == light_test_data_ha

    # def test_to_sber(self):
    #     sber_state = self.device.to_sber_state()
    #     self.assertEqual(sber_state, light_test_data_sber)

    # def test_process_cmd_on_off(self):
    #     cmd = self.device.process_cmd("sber", {"on_off": False})
    #     self.assertEqual(cmd["url"], "/api/services/light/turn_off")

    # def test_process_cmd_brightness(self):
    #     cmd = self.device.process_cmd("sber", {"brightness": 75})
    #     self.assertEqual(cmd["url"], "/api/services/light/set_brightness")
    #     self.assertEqual(cmd["data"]["brightness"], 191)  # 75% → 191

    # def test_process_cmd_color(self):
    #     cmd = self.device.process_cmd("sber", {"color": "#00ff00"})
    #     self.assertEqual(cmd["url"], "/api/services/light/turn_on")
    #     self.assertEqual(cmd["data"]["rgb_color"], (0, 255, 0))

    # def test_process_cmd_color_temperature(self):
    #     cmd = self.device.process_cmd("sber", {"color_temperature": 400})
    #     self.assertEqual(cmd["url"], "/api/services/light/turn_on")
    #     self.assertEqual(cmd["data"]["color_temp"], 400)

    # def test_unsupported_features(self):
    #     # Устройство без поддержки цвета
    #     ha_state_no_color = copy.deepcopy(light_test_data_ha)
    #     ha_state_no_color["attributes"]["supported_features"] = 1  # Только яркость
    #     device = LightEntity(ha_state_no_color)

    #     self.assertIsNone(device.color)
    #     # Попытка установить цвет
    #     with self.assertRaises(ValueError):
    #         device.color = "#00ff00"

    # def test_color_attribute_handling(self):
    #     """Проверка обработки атрибута 'color'"""
    #     ha_state_with_color = copy.deepcopy(light_test_data_ha)
    #     ha_state_with_color["attributes"]["color"] = "#aabbcc"
    #     # del ha_state_with_color["attributes"]["rgb_color"]
    #     device = LightEntity(ha_state_with_color)
    #     self.assertEqual(device.color, "#aabbcc")

    #     ha_state_with_invalid_color = copy.deepcopy(light_test_data_ha)
    #     ha_state_with_invalid_color["attributes"]["color"] = "invalid"
    #     device = LightEntity(ha_state_with_invalid_color)
    #     self.assertIsNone(device.color)


if __name__ == '__main__':
    unittest.main()
