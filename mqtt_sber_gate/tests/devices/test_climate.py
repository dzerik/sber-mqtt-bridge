import unittest
import os
import json

from devices.climate import ClimateDevice
# from devices.climate import ClimateDevice 

# Путь к тестовым данным
# JSON_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'devices', 'climate.json')

climate_test_data_sber =  {
   "id": "climate.aux_cloud_e87072945e65_ac",
   "manufacturer": "Unknown",
   "model": "Unknown",
   "hw_version": "Unknown",
   "sw_version": "Unknown",
   "description": "air conditioner Air Conditioner",
   "category": "hvac_ac",
   "features": [
      "online",
      "on_off",
      "temperature",
      "hvac_temp_set",
      "hvac_air_flow_direction",
      "hvac_air_flow_power",
      "hvac_work_mode",
   ],
   "allowed_values": {
      "hvac_air_flow_direction": {
         "type": "ENUM",
         "enum_values": {
            "values": [
                "off",
               "vertical",
               "horizontal",
               "both"
            ]
         }
      },
      "hvac_air_flow_power":{
         "type": "ENUM",
         "enum_values": {
            "values": [
               "auto",
               "low",
               "medium",
               "high",
               "turbo",
               "silent"
            ]
         }
      },
      "hvac_work_mode":{
         "type": "ENUM",
         "enum_values": {
            "values": [
               "off",
               "auto",
               "cool",
               "heat",
               "dry",
               "fan_only"
            ]
         }
      }
   }
}

climate_test_data_ha =     {
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
        self.device = ClimateDevice(climate_test_data_ha)

    def test_loading(self):
        """Проверка загрузки данных из JSON"""
        self.assertEqual(self.device.id, "climate.aux_cloud_e87072945e65_ac")
        self.assertEqual(self.device.description, "air conditioner Air Conditioner")
        self.assertEqual(self.device.temperature, 26.6)
        self.assertEqual(self.device.hvac_temp_set, 22.0)
        self.assertEqual(self.device.online, False)
        self.assertListEqual(self.device.fan_modes, ["auto", "low", "medium", "high", "turbo", "silent"])
        self.assertListEqual(self.device.swing_modes, ["off", "vertical", "horizontal", "both"])

    def test_to_ha_state(self):
        """Проверка формирования состояния для Home Assistant"""
        ha_state = self.device.to_ha_state()
       
        assert ha_state == climate_test_data_ha

    def test_to_sber(self):
        """Проверка формирования состояния для Sber"""
        sber_state = self.device.to_sber_state()

        assert sber_state == climate_test_data_sber

    def test_process_cmd_on_off(self):
        """Проверка обработки команды включения/выключения"""
        # Тестирование включения устройства
        cmd = self.device.process_cmd("sber", {"on_off": True})
        self.assertIsNotNone(cmd)
        self.assertEqual(cmd["url"], "/api/services/climate/turn_on")
        self.assertEqual(cmd["data"], {"entity_id": "climate.aux_cloud_e87072945e65_ac"})

        cmd = self.device.process_cmd("sber", {"on_off": False})
        self.assertIsNotNone(cmd)
        self.assertEqual(cmd["url"], "/api/services/climate/turn_off")
        self.assertEqual(cmd["data"], {"entity_id": "climate.aux_cloud_e87072945e65_ac"})

        cmd = self.device.process_cmd("sber", {"on_off": False})
        self.assertIsNotNone(cmd)
        self.assertEqual(cmd["url"], "/api/services/climate/turn_off")
        self.assertEqual(cmd["data"], {"entity_id": "climate.aux_cloud_e87072945e65_ac"})

    def test_process_cmd_hvac_temp_set(self):
        """Проверка обработки команды установки температуры"""
        old_state = self.device.on_off

        self.device.on_off = False
        cmd = self.device.process_cmd("sber", {"hvac_temp_set": 25.5})
        self.assertIsNotNone(cmd)
        self.assertEqual(cmd["url"], "/api/services/climate/set_temperature")
        self.assertEqual(cmd["data"], {"entity_id": "climate.aux_cloud_e87072945e65_ac", "temperature": 25.5, "hvac_mode": "heat"})

        self.device.on_off = True
        cmd = self.device.process_cmd("sber", {"hvac_temp_set": 29.9})
        self.assertIsNotNone(cmd)
        self.assertEqual(cmd["url"], "/api/services/climate/set_temperature")
        self.assertEqual(cmd["data"], {"entity_id": "climate.aux_cloud_e87072945e65_ac", "temperature": 29.9, "hvac_mode": "cool"})
    
    def test_process_wrong_cmd(self):
        """Проверка обработки неправильной команды"""
        cmd = self.device.process_cmd("sber", {"wrong_cmd": True})
        self.assertIsNone(cmd)
        cmd = self.device.process_cmd("ha", None)
        self.assertIsNone(cmd)

        
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
