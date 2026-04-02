"""Tests for SimpleReadOnlySensor -- sensor_sensitive feature."""

import unittest

from custom_components.sber_mqtt_bridge.devices.motion_sensor import MotionSensorEntity
from custom_components.sber_mqtt_bridge.devices.sensor_temp import SensorTempEntity


TEMP_DATA = {"entity_id": "sensor.temp", "name": "Temperature"}
MOTION_DATA = {"entity_id": "binary_sensor.motion", "name": "Motion"}


def _temp_state(state="22.5", **attrs):
    return {"entity_id": "sensor.temp", "state": state, "attributes": attrs}


def _motion_state(state="off", **attrs):
    return {"entity_id": "binary_sensor.motion", "state": state, "attributes": attrs}


class TestSensorSensitiveMotion(unittest.TestCase):
    """Test sensor_sensitive feature via MotionSensorEntity."""

    def test_sensitivity_high_in_features(self):
        """sensitivity=high must add sensor_sensitive to features."""
        entity = MotionSensorEntity(MOTION_DATA)
        entity.fill_by_ha_state(_motion_state(sensitivity="high"))
        features = entity.create_features_list()
        self.assertIn("sensor_sensitive", features)

    def test_sensitivity_high_in_state(self):
        """sensitivity=high must map to sensor_sensitive=high in Sber state."""
        entity = MotionSensorEntity(MOTION_DATA)
        entity.fill_by_ha_state(_motion_state(sensitivity="high"))
        result = entity.to_sber_current_state()
        states = result["binary_sensor.motion"]["states"]
        ss = next(s for s in states if s["key"] == "sensor_sensitive")
        self.assertEqual(ss["value"]["enum_value"], "high")

    def test_sensitivity_auto_in_state(self):
        """sensitivity=auto must map to sensor_sensitive=auto."""
        entity = MotionSensorEntity(MOTION_DATA)
        entity.fill_by_ha_state(_motion_state(sensitivity="auto"))
        result = entity.to_sber_current_state()
        states = result["binary_sensor.motion"]["states"]
        ss = next(s for s in states if s["key"] == "sensor_sensitive")
        self.assertEqual(ss["value"]["enum_value"], "auto")

    def test_sensitivity_medium_maps_to_auto(self):
        """sensitivity=medium must map to sensor_sensitive=auto (Sber only supports auto/high/low)."""
        entity = MotionSensorEntity(MOTION_DATA)
        entity.fill_by_ha_state(_motion_state(sensitivity="medium"))
        result = entity.to_sber_current_state()
        states = result["binary_sensor.motion"]["states"]
        ss = next(s for s in states if s["key"] == "sensor_sensitive")
        self.assertEqual(ss["value"]["enum_value"], "auto")

    def test_sensitivity_low_in_state(self):
        """sensitivity=low must map to sensor_sensitive=low."""
        entity = MotionSensorEntity(MOTION_DATA)
        entity.fill_by_ha_state(_motion_state(sensitivity="low"))
        result = entity.to_sber_current_state()
        states = result["binary_sensor.motion"]["states"]
        ss = next(s for s in states if s["key"] == "sensor_sensitive")
        self.assertEqual(ss["value"]["enum_value"], "low")

    def test_sensitivity_absent_no_feature(self):
        """Without sensitivity attribute, sensor_sensitive must not be in features."""
        entity = MotionSensorEntity(MOTION_DATA)
        entity.fill_by_ha_state(_motion_state())
        features = entity.create_features_list()
        self.assertNotIn("sensor_sensitive", features)

    def test_sensitivity_absent_not_in_state(self):
        """Without sensitivity, sensor_sensitive must not appear in Sber state."""
        entity = MotionSensorEntity(MOTION_DATA)
        entity.fill_by_ha_state(_motion_state())
        result = entity.to_sber_current_state()
        states = result["binary_sensor.motion"]["states"]
        keys = [s["key"] for s in states]
        self.assertNotIn("sensor_sensitive", keys)

    def test_sensitivity_invalid_value_ignored(self):
        """Unrecognized sensitivity value must not produce sensor_sensitive."""
        entity = MotionSensorEntity(MOTION_DATA)
        entity.fill_by_ha_state(_motion_state(sensitivity="ultra_high"))
        features = entity.create_features_list()
        self.assertNotIn("sensor_sensitive", features)

    def test_sensitivity_case_insensitive(self):
        """Sensitivity values must be handled case-insensitively."""
        entity = MotionSensorEntity(MOTION_DATA)
        entity.fill_by_ha_state(_motion_state(sensitivity="High"))
        result = entity.to_sber_current_state()
        states = result["binary_sensor.motion"]["states"]
        ss = next(s for s in states if s["key"] == "sensor_sensitive")
        self.assertEqual(ss["value"]["enum_value"], "high")


class TestSensorSensitiveMotionSensitivity(unittest.TestCase):
    """Test motion_sensitivity attribute (alternative attribute name)."""

    def test_motion_sensitivity_attribute(self):
        """motion_sensitivity attribute must also be recognized."""
        entity = MotionSensorEntity(MOTION_DATA)
        entity.fill_by_ha_state(_motion_state(motion_sensitivity="high"))
        features = entity.create_features_list()
        self.assertIn("sensor_sensitive", features)
        result = entity.to_sber_current_state()
        states = result["binary_sensor.motion"]["states"]
        ss = next(s for s in states if s["key"] == "sensor_sensitive")
        self.assertEqual(ss["value"]["enum_value"], "high")

    def test_sensitivity_takes_precedence_over_motion_sensitivity(self):
        """When both attributes exist, sensitivity takes precedence."""
        entity = MotionSensorEntity(MOTION_DATA)
        entity.fill_by_ha_state(_motion_state(sensitivity="low", motion_sensitivity="high"))
        result = entity.to_sber_current_state()
        states = result["binary_sensor.motion"]["states"]
        ss = next(s for s in states if s["key"] == "sensor_sensitive")
        self.assertEqual(ss["value"]["enum_value"], "low")


class TestSensorSensitiveTemp(unittest.TestCase):
    """Test sensor_sensitive via SensorTempEntity (inherits SimpleReadOnlySensor)."""

    def test_sensitivity_in_features(self):
        """SensorTempEntity with sensitivity must include sensor_sensitive."""
        entity = SensorTempEntity(TEMP_DATA)
        entity.fill_by_ha_state(_temp_state(sensitivity="auto"))
        features = entity.create_features_list()
        self.assertIn("sensor_sensitive", features)

    def test_sensitivity_absent(self):
        """SensorTempEntity without sensitivity must not include sensor_sensitive."""
        entity = SensorTempEntity(TEMP_DATA)
        entity.fill_by_ha_state(_temp_state())
        features = entity.create_features_list()
        self.assertNotIn("sensor_sensitive", features)
