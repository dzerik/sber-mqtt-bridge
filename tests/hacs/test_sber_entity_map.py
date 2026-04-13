"""Tests for sber_entity_map module."""

import unittest

from custom_components.sber_mqtt_bridge.sber_entity_map import (
    CATEGORY_DOMAIN_MAP,
    create_sber_entity,
)
from custom_components.sber_mqtt_bridge.devices.light import LightEntity
from custom_components.sber_mqtt_bridge.devices.led_strip import LedStripEntity
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
from custom_components.sber_mqtt_bridge.devices.smoke_sensor import SmokeSensorEntity
from custom_components.sber_mqtt_bridge.devices.gas_sensor import GasSensorEntity
from custom_components.sber_mqtt_bridge.devices.scenario_button import ScenarioButtonEntity
from custom_components.sber_mqtt_bridge.devices.valve import ValveEntity
from custom_components.sber_mqtt_bridge.devices.humidifier import HumidifierEntity
from custom_components.sber_mqtt_bridge.devices.hvac_radiator import HvacRadiatorEntity
from custom_components.sber_mqtt_bridge.devices.hvac_heater import HvacHeaterEntity
from custom_components.sber_mqtt_bridge.devices.hvac_boiler import HvacBoilerEntity
from custom_components.sber_mqtt_bridge.devices.hvac_underfloor_heating import HvacUnderfloorEntity
from custom_components.sber_mqtt_bridge.devices.hvac_fan import HvacFanEntity


def _data(entity_id, **kwargs):
    return {"entity_id": entity_id, "name": "Test", **kwargs}


class TestEntityConstructorsMap(unittest.TestCase):
    """Which HA domains does auto-detection cover? The answer is derived from
    the union of ``domains`` across all entries in ``CATEGORY_DOMAIN_MAP``.

    This list is the promised auto-detection surface -- anything missing here
    means users in that domain get silently skipped.
    """

    def test_all_supported_domains(self):
        expected = {"light", "cover", "sensor", "binary_sensor", "switch",
                    "script", "button", "input_boolean", "climate", "valve",
                    "humidifier", "fan", "water_heater", "media_player", "vacuum",
                    "lock"}
        supported = {d for spec in CATEGORY_DOMAIN_MAP.values() for d in spec.domains}
        self.assertEqual(supported, expected)


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

    def test_binary_sensor_smoke(self):
        e = create_sber_entity("binary_sensor.smoke", _data("binary_sensor.smoke", original_device_class="smoke"))
        self.assertIsInstance(e, SmokeSensorEntity)
        self.assertEqual(e.category, "sensor_smoke")

    def test_binary_sensor_gas(self):
        e = create_sber_entity("binary_sensor.gas", _data("binary_sensor.gas", original_device_class="gas"))
        self.assertIsInstance(e, GasSensorEntity)
        self.assertEqual(e.category, "sensor_gas")

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

    def test_climate_heater(self):
        e = create_sber_entity("climate.heat", _data("climate.heat", original_device_class="heater"))
        self.assertIsInstance(e, HvacHeaterEntity)
        self.assertEqual(e.category, "hvac_heater")

    def test_valve(self):
        e = create_sber_entity("valve.water", _data("valve.water"))
        self.assertIsInstance(e, ValveEntity)
        self.assertEqual(e.category, "valve")

    def test_humidifier(self):
        e = create_sber_entity("humidifier.room", _data("humidifier.room"))
        self.assertIsInstance(e, HumidifierEntity)
        self.assertEqual(e.category, "hvac_humidifier")

    def test_fan(self):
        e = create_sber_entity("fan.room", _data("fan.room"))
        self.assertIsInstance(e, HvacFanEntity)
        self.assertEqual(e.category, "hvac_fan")

    def test_water_heater(self):
        e = create_sber_entity("water_heater.boiler", _data("water_heater.boiler"))
        self.assertIsInstance(e, HvacBoilerEntity)
        self.assertEqual(e.category, "hvac_boiler")

    def test_unsupported_domain(self):
        e = create_sber_entity("camera.front", _data("camera.front"))
        self.assertIsNone(e)

    def test_automation_unsupported(self):
        e = create_sber_entity("automation.test", _data("automation.test"))
        self.assertIsNone(e)


class TestCategoryOverrides(unittest.TestCase):
    """Test sber_category override functionality."""

    def test_override_led_strip(self):
        e = create_sber_entity("light.strip", _data("light.strip"), sber_category="led_strip")
        self.assertIsInstance(e, LedStripEntity)
        self.assertEqual(e.category, "led_strip")

    def test_override_hvac_fan(self):
        e = create_sber_entity("switch.fan", _data("switch.fan"), sber_category="hvac_fan")
        self.assertIsInstance(e, HvacFanEntity)
        self.assertEqual(e.category, "hvac_fan")

    def test_override_hvac_heater(self):
        e = create_sber_entity("climate.heat", _data("climate.heat"), sber_category="hvac_heater")
        self.assertIsInstance(e, HvacHeaterEntity)
        self.assertEqual(e.category, "hvac_heater")

    def test_override_hvac_boiler(self):
        e = create_sber_entity("climate.boiler", _data("climate.boiler"), sber_category="hvac_boiler")
        self.assertIsInstance(e, HvacBoilerEntity)
        self.assertEqual(e.category, "hvac_boiler")

    def test_override_hvac_underfloor(self):
        e = create_sber_entity("climate.floor", _data("climate.floor"), sber_category="hvac_underfloor_heating")
        self.assertIsInstance(e, HvacUnderfloorEntity)
        self.assertEqual(e.category, "hvac_underfloor_heating")

    def test_override_sensor_smoke(self):
        e = create_sber_entity("binary_sensor.x", _data("binary_sensor.x"), sber_category="sensor_smoke")
        self.assertIsInstance(e, SmokeSensorEntity)

    def test_override_sensor_gas(self):
        e = create_sber_entity("binary_sensor.x", _data("binary_sensor.x"), sber_category="sensor_gas")
        self.assertIsInstance(e, GasSensorEntity)


if __name__ == "__main__":
    unittest.main()
