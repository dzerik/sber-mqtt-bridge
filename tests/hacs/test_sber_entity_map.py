"""Tests for sber_entity_map module."""

import unittest

from custom_components.sber_mqtt_bridge.sber_entity_map import (
    ENTITY_CONSTRUCTORS,
    create_sber_entity,
)
from custom_components.sber_mqtt_bridge.devices.light import LightEntity
from custom_components.sber_mqtt_bridge.devices.relay import RelayEntity
from custom_components.sber_mqtt_bridge.devices.socket_entity import SocketEntity
from custom_components.sber_mqtt_bridge.devices.climate import ClimateEntity
from custom_components.sber_mqtt_bridge.devices.curtain import CurtainEntity
from custom_components.sber_mqtt_bridge.devices.window_blind import WindowBlindEntity
from custom_components.sber_mqtt_bridge.devices.sensor_temp import SensorTempEntity
from custom_components.sber_mqtt_bridge.devices.humidity_sensor import HumiditySensorEntity
from custom_components.sber_mqtt_bridge.devices.motion_sensor import MotionSensorEntity
from custom_components.sber_mqtt_bridge.devices.door_sensor import DoorSensorEntity
from custom_components.sber_mqtt_bridge.devices.water_leak_sensor import WaterLeakSensorEntity
from custom_components.sber_mqtt_bridge.devices.scenario_button import ScenarioButtonEntity
from custom_components.sber_mqtt_bridge.devices.valve import ValveEntity
from custom_components.sber_mqtt_bridge.devices.humidifier import HumidifierEntity
from custom_components.sber_mqtt_bridge.devices.hvac_radiator import HvacRadiatorEntity


def _data(entity_id, **kwargs):
    return {"entity_id": entity_id, "name": "Test", **kwargs}


class TestEntityConstructorsMap(unittest.TestCase):

    def test_all_supported_domains(self):
        expected = {"light", "cover", "sensor", "binary_sensor", "switch",
                    "script", "button", "input_boolean", "climate", "valve", "humidifier"}
        self.assertEqual(set(ENTITY_CONSTRUCTORS.keys()), expected)


class TestCreateSberEntity(unittest.TestCase):

    def test_light(self):
        e = create_sber_entity("light.room", _data("light.room"))
        self.assertIsInstance(e, LightEntity)
        self.assertEqual(e.category, "light")

    def test_switch_default_relay(self):
        e = create_sber_entity("switch.lamp", _data("switch.lamp"))
        self.assertIsInstance(e, RelayEntity)
        self.assertEqual(e.category, "relay")

    def test_switch_outlet_socket(self):
        e = create_sber_entity("switch.plug", _data("switch.plug", original_device_class="outlet"))
        self.assertIsInstance(e, SocketEntity)
        self.assertEqual(e.category, "socket")

    def test_script(self):
        e = create_sber_entity("script.reboot", _data("script.reboot"))
        self.assertIsInstance(e, RelayEntity)

    def test_button(self):
        e = create_sber_entity("button.restart", _data("button.restart"))
        self.assertIsInstance(e, RelayEntity)

    def test_input_boolean(self):
        e = create_sber_entity("input_boolean.mode", _data("input_boolean.mode"))
        self.assertIsInstance(e, ScenarioButtonEntity)
        self.assertEqual(e.category, "scenario_button")

    def test_cover_default_curtain(self):
        e = create_sber_entity("cover.blinds", _data("cover.blinds"))
        self.assertIsInstance(e, CurtainEntity)
        self.assertEqual(e.category, "curtain")

    def test_cover_blind_class(self):
        e = create_sber_entity("cover.blinds", _data("cover.blinds", original_device_class="blind"))
        self.assertIsInstance(e, WindowBlindEntity)
        self.assertEqual(e.category, "window_blind")

    def test_cover_shade_class(self):
        e = create_sber_entity("cover.shade", _data("cover.shade", original_device_class="shade"))
        self.assertIsInstance(e, WindowBlindEntity)

    def test_sensor_temperature(self):
        e = create_sber_entity("sensor.temp", _data("sensor.temp", original_device_class="temperature"))
        self.assertIsInstance(e, SensorTempEntity)
        self.assertEqual(e.category, "sensor_temp")

    def test_sensor_humidity(self):
        e = create_sber_entity("sensor.hum", _data("sensor.hum", original_device_class="humidity"))
        self.assertIsInstance(e, HumiditySensorEntity)

    def test_sensor_unsupported_class(self):
        e = create_sber_entity("sensor.power", _data("sensor.power", original_device_class="power"))
        self.assertIsNone(e)

    def test_binary_sensor_motion(self):
        e = create_sber_entity("binary_sensor.pir", _data("binary_sensor.pir", original_device_class="motion"))
        self.assertIsInstance(e, MotionSensorEntity)
        self.assertEqual(e.category, "sensor_pir")

    def test_binary_sensor_door(self):
        e = create_sber_entity("binary_sensor.door", _data("binary_sensor.door", original_device_class="door"))
        self.assertIsInstance(e, DoorSensorEntity)
        self.assertEqual(e.category, "sensor_door")

    def test_binary_sensor_window(self):
        e = create_sber_entity("binary_sensor.win", _data("binary_sensor.win", original_device_class="window"))
        self.assertIsInstance(e, DoorSensorEntity)

    def test_binary_sensor_moisture(self):
        e = create_sber_entity("binary_sensor.leak", _data("binary_sensor.leak", original_device_class="moisture"))
        self.assertIsInstance(e, WaterLeakSensorEntity)
        self.assertEqual(e.category, "sensor_water_leak")

    def test_binary_sensor_unsupported(self):
        e = create_sber_entity("binary_sensor.bat", _data("binary_sensor.bat", original_device_class="battery"))
        self.assertIsNone(e)

    def test_climate_default(self):
        e = create_sber_entity("climate.ac", _data("climate.ac"))
        self.assertIsInstance(e, ClimateEntity)
        self.assertEqual(e.category, "hvac_ac")

    def test_climate_radiator(self):
        e = create_sber_entity("climate.rad", _data("climate.rad", original_device_class="radiator"))
        self.assertIsInstance(e, HvacRadiatorEntity)
        self.assertEqual(e.category, "hvac_radiator")

    def test_valve(self):
        e = create_sber_entity("valve.water", _data("valve.water"))
        self.assertIsInstance(e, ValveEntity)
        self.assertEqual(e.category, "valve")

    def test_humidifier(self):
        e = create_sber_entity("humidifier.room", _data("humidifier.room"))
        self.assertIsInstance(e, HumidifierEntity)
        self.assertEqual(e.category, "hvac_humidifier")

    def test_unsupported_domain(self):
        e = create_sber_entity("camera.front", _data("camera.front"))
        self.assertIsNone(e)

    def test_automation_unsupported(self):
        e = create_sber_entity("automation.test", _data("automation.test"))
        self.assertIsNone(e)


if __name__ == "__main__":
    unittest.main()
