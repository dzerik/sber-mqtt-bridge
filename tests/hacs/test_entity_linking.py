"""Tests for Entity Linking — linking auxiliary HA entities to primary Sber devices."""

import unittest

from custom_components.sber_mqtt_bridge.devices.relay import RelayEntity
from custom_components.sber_mqtt_bridge.devices.sensor_temp import SensorTempEntity
from custom_components.sber_mqtt_bridge.devices.humidity_sensor import HumiditySensorEntity
from custom_components.sber_mqtt_bridge.devices.motion_sensor import MotionSensorEntity
from custom_components.sber_mqtt_bridge.devices.water_leak_sensor import WaterLeakSensorEntity


ENTITY_DATA = {"entity_id": "sensor.temp", "name": "Temperature"}
HUMIDITY_DATA = {"entity_id": "sensor.hum", "name": "Humidity"}
MOTION_DATA = {"entity_id": "binary_sensor.motion", "name": "Motion"}
WATER_LEAK_DATA = {"entity_id": "binary_sensor.leak", "name": "Leak"}


def _make_ha_state(state="22.5", **attrs):
    return {"state": state, "attributes": attrs}


class TestSensorTempLinkedHumidity(unittest.TestCase):
    """Test linking humidity sensor to temperature sensor."""

    def test_no_linked_humidity_by_default(self):
        entity = SensorTempEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state())
        features = entity.get_final_features_list()
        self.assertNotIn("humidity", features)

    def test_linked_humidity_adds_feature(self):
        entity = SensorTempEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state())
        entity.update_linked_data("humidity", {"state": "55", "attributes": {}})
        features = entity.get_final_features_list()
        self.assertIn("humidity", features)
        self.assertIn("temperature", features)

    def test_linked_humidity_in_state(self):
        entity = SensorTempEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state())
        entity.update_linked_data("humidity", {"state": "55", "attributes": {}})
        result = entity.to_sber_current_state()
        states = result["sensor.temp"]["states"]
        keys = [s["key"] for s in states]
        self.assertIn("humidity", keys)
        hum = next(s for s in states if s["key"] == "humidity")
        self.assertEqual(hum["value"]["integer_value"], "55")

    def test_linked_humidity_unavailable_ignored(self):
        entity = SensorTempEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state())
        entity.update_linked_data("humidity", {"state": "unavailable", "attributes": {}})
        features = entity.get_final_features_list()
        self.assertNotIn("humidity", features)


class TestHumiditySensorLinkedTemperature(unittest.TestCase):
    """Test linking temperature sensor to humidity sensor."""

    def test_linked_temperature_adds_feature(self):
        entity = HumiditySensorEntity(HUMIDITY_DATA)
        entity.fill_by_ha_state({"state": "55", "attributes": {}})
        entity.update_linked_data("temperature", {"state": "22.5", "attributes": {}})
        features = entity.get_final_features_list()
        self.assertIn("temperature", features)
        self.assertIn("humidity", features)

    def test_linked_temperature_in_state(self):
        entity = HumiditySensorEntity(HUMIDITY_DATA)
        entity.fill_by_ha_state({"state": "55", "attributes": {}})
        entity.update_linked_data("temperature", {"state": "22.5", "attributes": {}})
        result = entity.to_sber_current_state()
        states = result["sensor.hum"]["states"]
        temp = next(s for s in states if s["key"] == "temperature")
        self.assertEqual(temp["value"]["integer_value"], "225")  # 22.5 * 10


class TestLinkedBattery(unittest.TestCase):
    """Test linking battery sensor to any SimpleReadOnlySensor."""

    def test_battery_adds_features(self):
        entity = MotionSensorEntity(MOTION_DATA)
        entity.fill_by_ha_state({"state": "off", "attributes": {}})
        self.assertNotIn("battery_percentage", entity.get_final_features_list())

        entity.update_linked_data("battery", {"state": "85", "attributes": {}})
        features = entity.get_final_features_list()
        self.assertIn("battery_percentage", features)
        self.assertIn("battery_low_power", features)

    def test_battery_in_state(self):
        entity = WaterLeakSensorEntity(WATER_LEAK_DATA)
        entity.fill_by_ha_state({"state": "off", "attributes": {}})
        entity.update_linked_data("battery", {"state": "15", "attributes": {}})
        result = entity.to_sber_current_state()
        states = result["binary_sensor.leak"]["states"]
        bat = next(s for s in states if s["key"] == "battery_percentage")
        self.assertEqual(bat["value"]["integer_value"], "15")
        low = next(s for s in states if s["key"] == "battery_low_power")
        self.assertTrue(low["value"]["bool_value"])  # 15 < 20

    def test_battery_not_low(self):
        entity = WaterLeakSensorEntity(WATER_LEAK_DATA)
        entity.fill_by_ha_state({"state": "off", "attributes": {}})
        entity.update_linked_data("battery", {"state": "85", "attributes": {}})
        result = entity.to_sber_current_state()
        states = result["binary_sensor.leak"]["states"]
        low = next(s for s in states if s["key"] == "battery_low_power")
        self.assertFalse(low["value"]["bool_value"])


class TestLinkedSignalStrength(unittest.TestCase):
    """Test linking signal strength sensor."""

    def test_signal_adds_feature(self):
        entity = MotionSensorEntity(MOTION_DATA)
        entity.fill_by_ha_state({"state": "off", "attributes": {}})
        entity.update_linked_data("signal_strength", {"state": "-45", "attributes": {}})
        features = entity.get_final_features_list()
        self.assertIn("signal_strength", features)

    def test_signal_in_state(self):
        entity = MotionSensorEntity(MOTION_DATA)
        entity.fill_by_ha_state({"state": "off", "attributes": {}})
        entity.update_linked_data("signal_strength", {"state": "-45", "attributes": {}})
        result = entity.to_sber_current_state()
        states = result["binary_sensor.motion"]["states"]
        sig = next(s for s in states if s["key"] == "signal_strength")
        self.assertEqual(sig["value"]["enum_value"], "high")  # -45 > -50


class TestFeaturesChangeDetection(unittest.TestCase):
    """Test that features list changes when linked data first arrives."""

    def test_features_change_on_first_link(self):
        entity = SensorTempEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state())
        before = entity.get_final_features_list()
        entity.update_linked_data("humidity", {"state": "55", "attributes": {}})
        after = entity.get_final_features_list()
        self.assertNotEqual(before, after)
        self.assertNotIn("humidity", before)
        self.assertIn("humidity", after)

    def test_features_stable_on_same_link(self):
        entity = SensorTempEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state())
        entity.update_linked_data("humidity", {"state": "55", "attributes": {}})
        first = entity.get_final_features_list()
        entity.update_linked_data("humidity", {"state": "60", "attributes": {}})
        second = entity.get_final_features_list()
        self.assertEqual(first, second)


class TestBaseEntityDefaultLinkedData(unittest.TestCase):
    """BaseEntity.update_linked_data default is a no-op.

    This contract exists so callers (ha_state_forwarder, entity_registry)
    can invoke the method unconditionally instead of probing with
    ``hasattr``.  If this test regresses, every device class that has
    no LINKABLE_ROLES will start blowing up when HA emits state events
    for whatever happens to be linked to it.
    """

    def test_default_update_linked_data_does_not_raise(self):
        # RelayEntity defines no update_linked_data override -- it must
        # inherit the silent no-op and leave its state untouched.
        entity = RelayEntity({"entity_id": "switch.lamp", "name": "Lamp"})
        entity.fill_by_ha_state({"state": "on", "attributes": {}})
        before = entity.to_sber_current_state()
        entity.update_linked_data("battery", {"state": "50", "attributes": {}})
        after = entity.to_sber_current_state()
        self.assertEqual(before, after)

    def test_default_update_linked_data_returns_none(self):
        entity = RelayEntity({"entity_id": "switch.lamp", "name": "Lamp"})
        result = entity.update_linked_data("any_role", {"state": "on"})
        self.assertIsNone(result)
