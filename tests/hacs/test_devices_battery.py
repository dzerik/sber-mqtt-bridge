"""Tests for battery_percentage feature in SimpleReadOnlySensor."""

import unittest

from custom_components.sber_mqtt_bridge.devices.door_sensor import DoorSensorEntity
from custom_components.sber_mqtt_bridge.devices.motion_sensor import MotionSensorEntity
from custom_components.sber_mqtt_bridge.devices.water_leak_sensor import WaterLeakSensorEntity


DOOR_DATA = {"entity_id": "binary_sensor.door", "name": "Door"}


def _make_ha_state(state="off", **attrs):
    return {
        "entity_id": "binary_sensor.door",
        "state": state,
        "attributes": attrs,
    }


class TestBatteryFeature(unittest.TestCase):
    """Test battery_percentage in SimpleReadOnlySensor subclasses."""

    def test_battery_from_battery_attr(self):
        entity = DoorSensorEntity(DOOR_DATA)
        entity.fill_by_ha_state(_make_ha_state("off", battery=90))
        features = entity.create_features_list()
        self.assertIn("battery_percentage", features)

    def test_battery_from_battery_level_attr(self):
        entity = DoorSensorEntity(DOOR_DATA)
        entity.fill_by_ha_state(_make_ha_state("off", battery_level=75))
        features = entity.create_features_list()
        self.assertIn("battery_percentage", features)

    def test_battery_in_sber_state(self):
        entity = DoorSensorEntity(DOOR_DATA)
        entity.fill_by_ha_state(_make_ha_state("off", battery=80))
        result = entity.to_sber_current_state()
        states = result["binary_sensor.door"]["states"]
        batt = next(s for s in states if s["key"] == "battery_percentage")
        self.assertEqual(batt["value"]["type"], "INTEGER")
        self.assertEqual(batt["value"]["integer_value"], "80")

    def test_no_battery_no_feature(self):
        entity = DoorSensorEntity(DOOR_DATA)
        entity.fill_by_ha_state(_make_ha_state("off"))
        features = entity.create_features_list()
        self.assertNotIn("battery_percentage", features)

    def test_no_battery_no_state(self):
        entity = DoorSensorEntity(DOOR_DATA)
        entity.fill_by_ha_state(_make_ha_state("off"))
        result = entity.to_sber_current_state()
        states = result["binary_sensor.door"]["states"]
        keys = [s["key"] for s in states]
        self.assertNotIn("battery_percentage", keys)

    def test_battery_invalid_value_ignored(self):
        entity = DoorSensorEntity(DOOR_DATA)
        entity.fill_by_ha_state(_make_ha_state("off", battery="invalid"))
        features = entity.create_features_list()
        self.assertNotIn("battery_percentage", features)

    def test_motion_sensor_battery(self):
        data = {"entity_id": "binary_sensor.motion", "name": "Motion"}
        entity = MotionSensorEntity(data)
        entity.fill_by_ha_state({
            "entity_id": "binary_sensor.motion",
            "state": "off",
            "attributes": {"battery": 50},
        })
        features = entity.create_features_list()
        self.assertIn("battery_percentage", features)

    def test_water_leak_sensor_battery(self):
        data = {"entity_id": "binary_sensor.leak", "name": "Leak"}
        entity = WaterLeakSensorEntity(data)
        entity.fill_by_ha_state({
            "entity_id": "binary_sensor.leak",
            "state": "off",
            "attributes": {"battery_level": 60},
        })
        features = entity.create_features_list()
        self.assertIn("battery_percentage", features)
