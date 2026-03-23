"""Tests for SmokeSensorEntity -- Sber smoke sensor device mapping."""

import unittest

from custom_components.sber_mqtt_bridge.devices.smoke_sensor import SmokeSensorEntity


ENTITY_DATA = {"entity_id": "binary_sensor.smoke", "name": "Smoke Detector"}


def _make_ha_state(state="off", **attrs):
    return {
        "entity_id": "binary_sensor.smoke",
        "state": state,
        "attributes": attrs,
    }


class TestSmokeSensorCreate(unittest.TestCase):
    """Test SmokeSensorEntity initialization."""

    def test_category(self):
        entity = SmokeSensorEntity(ENTITY_DATA)
        self.assertEqual(entity.category, "sensor_smoke")

    def test_initial_state(self):
        entity = SmokeSensorEntity(ENTITY_DATA)
        self.assertFalse(entity.smoke_detected)

    def test_sber_value_key(self):
        entity = SmokeSensorEntity(ENTITY_DATA)
        self.assertEqual(entity._sber_value_key, "smoke_state")


class TestSmokeSensorToSberCurrentState(unittest.TestCase):
    """Test to_sber_current_state."""

    def test_smoke_detected(self):
        entity = SmokeSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("on"))
        result = entity.to_sber_current_state()
        states = result["binary_sensor.smoke"]["states"]
        smoke = next(s for s in states if s["key"] == "smoke_state")
        self.assertEqual(smoke["value"]["type"], "BOOL")
        self.assertTrue(smoke["value"]["bool_value"])

    def test_no_smoke(self):
        entity = SmokeSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("off"))
        result = entity.to_sber_current_state()
        states = result["binary_sensor.smoke"]["states"]
        smoke = next(s for s in states if s["key"] == "smoke_state")
        self.assertFalse(smoke["value"]["bool_value"])

    def test_online_status(self):
        entity = SmokeSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("unavailable"))
        result = entity.to_sber_current_state()
        states = result["binary_sensor.smoke"]["states"]
        online = next(s for s in states if s["key"] == "online")
        self.assertFalse(online["value"]["bool_value"])


class TestSmokeSensorProcessCmd(unittest.TestCase):
    """Test process_cmd (read-only)."""

    def test_cmd_is_noop(self):
        entity = SmokeSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("off"))
        result = entity.process_cmd({"states": [{"key": "smoke_state", "value": {}}]})
        self.assertEqual(result, [])


class TestSmokeSensorBattery(unittest.TestCase):
    """Test battery feature support."""

    def test_battery_in_features(self):
        entity = SmokeSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("off", battery=85))
        features = entity.create_features_list()
        self.assertIn("battery_percentage", features)

    def test_battery_in_state(self):
        entity = SmokeSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("off", battery=85))
        result = entity.to_sber_current_state()
        states = result["binary_sensor.smoke"]["states"]
        batt = next(s for s in states if s["key"] == "battery_percentage")
        self.assertEqual(batt["value"]["integer_value"], "85")

    def test_no_battery(self):
        entity = SmokeSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("off"))
        features = entity.create_features_list()
        self.assertNotIn("battery_percentage", features)
