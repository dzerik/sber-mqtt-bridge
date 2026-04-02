"""Tests for WaterLeakSensorEntity -- tamper_alarm and alarm_mute features."""

import unittest

from custom_components.sber_mqtt_bridge.devices.water_leak_sensor import WaterLeakSensorEntity


ENTITY_DATA = {"entity_id": "binary_sensor.leak", "name": "Water Leak"}


def _make_ha_state(state="off", **attrs):
    return {
        "entity_id": "binary_sensor.leak",
        "state": state,
        "attributes": attrs,
    }


class TestWaterLeakSensorCreate(unittest.TestCase):
    """Test WaterLeakSensorEntity initialization."""

    def test_category(self):
        entity = WaterLeakSensorEntity(ENTITY_DATA)
        self.assertEqual(entity.category, "sensor_water_leak")

    def test_initial_state(self):
        entity = WaterLeakSensorEntity(ENTITY_DATA)
        self.assertFalse(entity.leak_detected)

    def test_sber_value_key(self):
        entity = WaterLeakSensorEntity(ENTITY_DATA)
        self.assertEqual(entity._sber_value_key, "water_leak_state")


class TestWaterLeakSensorBasicState(unittest.TestCase):
    """Test basic leak detection state."""

    def test_leak_detected(self):
        entity = WaterLeakSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("on"))
        result = entity.to_sber_current_state()
        states = result["binary_sensor.leak"]["states"]
        leak = next(s for s in states if s["key"] == "water_leak_state")
        self.assertTrue(leak["value"]["bool_value"])

    def test_no_leak(self):
        entity = WaterLeakSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("off"))
        result = entity.to_sber_current_state()
        states = result["binary_sensor.leak"]["states"]
        leak = next(s for s in states if s["key"] == "water_leak_state")
        self.assertFalse(leak["value"]["bool_value"])

    def test_online_status(self):
        entity = WaterLeakSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("unavailable"))
        result = entity.to_sber_current_state()
        states = result["binary_sensor.leak"]["states"]
        online = next(s for s in states if s["key"] == "online")
        self.assertFalse(online["value"]["bool_value"])


class TestWaterLeakTamperAlarm(unittest.TestCase):
    """Test tamper_alarm feature in WaterLeakSensorEntity."""

    def test_tamper_feature_present_when_true(self):
        """Entity with tamper=True must include tamper_alarm in features."""
        entity = WaterLeakSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("off", tamper=True))
        features = entity.create_features_list()
        self.assertIn("tamper_alarm", features)

    def test_tamper_feature_present_when_false(self):
        """Entity with tamper=False must still include tamper_alarm in features."""
        entity = WaterLeakSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("off", tamper=False))
        features = entity.create_features_list()
        self.assertIn("tamper_alarm", features)

    def test_tamper_feature_absent_without_attribute(self):
        """Entity without tamper attribute must not include tamper_alarm."""
        entity = WaterLeakSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("off"))
        features = entity.create_features_list()
        self.assertNotIn("tamper_alarm", features)

    def test_tamper_true_in_state(self):
        """tamper=True must produce tamper_alarm=True in Sber state."""
        entity = WaterLeakSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("off", tamper=True))
        result = entity.to_sber_current_state()
        states = result["binary_sensor.leak"]["states"]
        tamper = next(s for s in states if s["key"] == "tamper_alarm")
        self.assertTrue(tamper["value"]["bool_value"])

    def test_tamper_false_in_state(self):
        """tamper=False must produce tamper_alarm=False in Sber state."""
        entity = WaterLeakSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("off", tamper=False))
        result = entity.to_sber_current_state()
        states = result["binary_sensor.leak"]["states"]
        tamper = next(s for s in states if s["key"] == "tamper_alarm")
        self.assertFalse(tamper["value"]["bool_value"])

    def test_tamper_not_in_state_when_absent(self):
        """Without tamper attribute, tamper_alarm must not appear in Sber state."""
        entity = WaterLeakSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("off"))
        result = entity.to_sber_current_state()
        states = result["binary_sensor.leak"]["states"]
        keys = [s["key"] for s in states]
        self.assertNotIn("tamper_alarm", keys)


class TestWaterLeakAlarmMute(unittest.TestCase):
    """Test alarm_mute feature in WaterLeakSensorEntity."""

    def test_alarm_mute_feature_present_when_false(self):
        """Entity with alarm_mute=False must include alarm_mute in features."""
        entity = WaterLeakSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("off", alarm_mute=False))
        features = entity.create_features_list()
        self.assertIn("alarm_mute", features)

    def test_alarm_mute_feature_present_when_true(self):
        """Entity with alarm_mute=True must include alarm_mute in features."""
        entity = WaterLeakSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("off", alarm_mute=True))
        features = entity.create_features_list()
        self.assertIn("alarm_mute", features)

    def test_alarm_mute_feature_absent_without_attribute(self):
        """Entity without alarm_mute attribute must not include it."""
        entity = WaterLeakSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("off"))
        features = entity.create_features_list()
        self.assertNotIn("alarm_mute", features)

    def test_alarm_mute_true_in_state(self):
        """alarm_mute=True must produce alarm_mute=True in Sber state."""
        entity = WaterLeakSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("off", alarm_mute=True))
        result = entity.to_sber_current_state()
        states = result["binary_sensor.leak"]["states"]
        am = next(s for s in states if s["key"] == "alarm_mute")
        self.assertTrue(am["value"]["bool_value"])

    def test_alarm_mute_false_in_state(self):
        """alarm_mute=False must produce alarm_mute=False in Sber state."""
        entity = WaterLeakSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("off", alarm_mute=False))
        result = entity.to_sber_current_state()
        states = result["binary_sensor.leak"]["states"]
        am = next(s for s in states if s["key"] == "alarm_mute")
        self.assertFalse(am["value"]["bool_value"])

    def test_alarm_mute_not_in_state_when_absent(self):
        """Without alarm_mute attribute, it must not appear in Sber state."""
        entity = WaterLeakSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("off"))
        result = entity.to_sber_current_state()
        states = result["binary_sensor.leak"]["states"]
        keys = [s["key"] for s in states]
        self.assertNotIn("alarm_mute", keys)


class TestWaterLeakCombinedFeatures(unittest.TestCase):
    """Test tamper_alarm and alarm_mute together."""

    def test_both_features_present(self):
        """Both tamper_alarm and alarm_mute must appear when both attributes exist."""
        entity = WaterLeakSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("on", tamper=True, alarm_mute=False))
        features = entity.create_features_list()
        self.assertIn("tamper_alarm", features)
        self.assertIn("alarm_mute", features)

    def test_both_in_state(self):
        """Both features must appear in Sber current state."""
        entity = WaterLeakSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("on", tamper=True, alarm_mute=False))
        result = entity.to_sber_current_state()
        states = result["binary_sensor.leak"]["states"]
        keys = [s["key"] for s in states]
        self.assertIn("tamper_alarm", keys)
        self.assertIn("alarm_mute", keys)
        tamper = next(s for s in states if s["key"] == "tamper_alarm")
        self.assertTrue(tamper["value"]["bool_value"])
        am = next(s for s in states if s["key"] == "alarm_mute")
        self.assertFalse(am["value"]["bool_value"])

    def test_only_tamper_no_alarm_mute(self):
        """Only tamper_alarm when only tamper attribute is present."""
        entity = WaterLeakSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("off", tamper=True))
        features = entity.create_features_list()
        self.assertIn("tamper_alarm", features)
        self.assertNotIn("alarm_mute", features)


class TestWaterLeakProcessCmd(unittest.TestCase):
    """Test process_cmd (read-only sensor)."""

    def test_cmd_is_noop(self):
        entity = WaterLeakSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("off"))
        result = entity.process_cmd({"states": []})
        self.assertEqual(result, [])
