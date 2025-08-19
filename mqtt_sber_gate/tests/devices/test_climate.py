import unittest
import os
import json

from devices.climate import ClimateDevice
# from devices.climate import ClimateDevice 

# Путь к тестовым данным
# JSON_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'devices', 'climate.json')

climate_test_data =     {
        "entity_id": "climate.aux_cloud_e87072945e65_ac",
        "state": "off",
        "attributes": {
            "hvac_modes": [
                "off",
                "auto",
                "cool",
                "heat",
                "dry",
                "fan_only"
            ],
            "min_temp": 16,
            "max_temp": 32,
            "target_temp_step": 0.5,
            "fan_modes": [
                "auto",
                "low",
                "medium",
                "high",
                "turbo",
                "silent"
            ],
            "swing_modes": [
                "off",
                "vertical",
                "horizontal",
                "both"
            ],
            "current_temperature": 26.6,
            "temperature": 22.0,
            "fan_mode": "auto",
            "hvac_action": "off",
            "swing_mode": "off",
            "icon": "mdi:air-conditioner",
            "friendly_name": "air conditioner Air Conditioner",
            "supported_features": 425
        },
        "last_changed": "2025-08-18T08:16:00.503857+00:00",
        "last_reported": "2025-08-19T02:33:21.237550+00:00",
        "last_updated": "2025-08-19T02:33:21.237550+00:00",
        "context": {
            "id": "01K302S2JN96H6YBPH1RJ5J7SD",
            "parent_id": {},
            "user_id": {}
        }
    }


class TestClimateDevice(unittest.TestCase):
    device = None

    def setUp(self):
        """Создаем тестовый объект климат-устройства на основе данных из JSON"""
        self.device = ClimateDevice(climate_test_data)

    def test_loading(self):
        """Проверка загрузки данных из JSON"""
        self.assertEqual(self.device.id, "climate.aux_cloud_e87072945e65_ac")
        self.assertEqual(self.device.description, "air conditioner Air Conditioner")
        self.assertEqual(self.device.temperature, 26.6)
        self.assertEqual(self.device.hvac_temp_set, 22.0)
        self.assertEqual(self.device.on_off, False)
        self.assertListEqual(self.device.fan_modes, ["auto", "low", "medium", "high", "turbo", "silent"])
        self.assertListEqual(self.device.swing_modes, ["off", "vertical", "horizontal", "both"])

    def test_to_ha_state(self):
        """Проверка формирования состояния для Home Assistant"""
        ha_state = self.device.to_ha_state()
        
        self.assertEqual(ha_state["id"], "climate.aux_cloud_e87072945e65_ac")
        self.assertEqual(ha_state["temperature"], 26.6)
        self.assertEqual(ha_state["hvac_temp_set"], 22.0)
        self.assertFalse(ha_state["on_off"])
        raise NotImplementedError("Метод to_ha_state должен быть расширен")

    # def test_to_ha_state(self):
    #     """Проверка формирования состояния для Home Assistant"""
    #     ha_state = self.device.to_ha_state()
        
    #     self.assertEqual(ha_state["id"], "climate.aux_cloud_e87072945e65_ac")
    #     self.assertEqual(ha_state["temperature"], 20.0)
    #     self.assertEqual(ha_state["hvac_temp_set"], 20.0)
    #     self.assertTrue(ha_state["on_off"])
    #     self.assertTrue(ha_state["online"])

    # def test_to_sber_state(self):
    #     """Проверка формирования состояния для Sber"""
    #     sber_state = self.device.to_sber_state()
        
    #     self.assertEqual(sber_state["id"], "climate.aux_cloud_e87072945e65_ac")
    #     self.assertEqual(len(sber_state["states"]), 4)
        
    #     states = {item["key"]: item["value"] for item in sber_state["states"]}
    #     self.assertEqual(states["online"]["bool_value"], True)
    #     self.assertEqual(states["on_off"]["bool_value"], True)
    #     self.assertEqual(states["temperature"]["integer_value"], 200)  # 20.0 * 10
    #     self.assertEqual(states["hvac_temp_set"]["integer_value"], 200)  # 20.0 * 10

    # def test_process_cmd_on_off(self):
    #     """Проверка обработки команды включения/выключения"""
    #     # Тестирование включения устройства
    #     changed = self.device.process_cmd("sber", {"on_off": False})
    #     self.assertTrue(changed)
    #     self.assertFalse(self.device.on_off)
        
    #     # Тестирование повторного включения (нет изменений)
    #     changed = self.device.process_cmd("sber", {"on_off": False})
    #     self.assertFalse(changed)
    #     self.assertFalse(self.device.on_off)

    # def test_process_cmd_temperature(self):
    #     """Проверка обработки команды установки температуры"""
    #     # Установка новой температуры
    #     changed = self.device.process_cmd("ha", {"hvac_temp_set": 25.5})
    #     self.assertTrue(changed)
    #     self.assertEqual(self.device.hvac_temp_set, 25.5)
        
    #     # Повторная установка той же температуры (нет изменений)
    #     changed = self.device.process_cmd("ha", {"hvac_temp_set": 25.5})
    #     self.assertFalse(changed)
    #     self.assertEqual(self.device.hvac_temp_set, 25.5)

    # def test_process_multiple_commands(self):
    #     """Проверка обработки нескольких команд одновременно"""
    #     # Изменение и температуры, и состояния включения
    #     changed = self.device.process_cmd("sber", {
    #         "on_off": False,
    #         "hvac_temp_set": 22.0
    #     })
        
    #     self.assertTrue(changed)
    #     self.assertFalse(self.device.on_off)
    #     self.assertEqual(self.device.hvac_temp_set, 22.0)

if __name__ == '__main__':
    unittest.main()
