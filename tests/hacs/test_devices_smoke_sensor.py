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


class TestSmokeSensorTamperAlarm(unittest.TestCase):
    """Test tamper_alarm feature in SmokeSensorEntity."""

    def test_tamper_feature_present_when_true(self):
        """Entity with tamper=True must include tamper_alarm in features."""
        entity = SmokeSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("off", tamper=True))
        features = entity.get_final_features_list()
        self.assertIn("tamper_alarm", features)

    def test_tamper_feature_present_when_false(self):
        """Entity with tamper=False must still include tamper_alarm in features."""
        entity = SmokeSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("off", tamper=False))
        features = entity.get_final_features_list()
        self.assertIn("tamper_alarm", features)

    def test_tamper_feature_absent_without_attribute(self):
        """Entity without tamper attribute must not include tamper_alarm."""
        entity = SmokeSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("off"))
        features = entity.get_final_features_list()
        self.assertNotIn("tamper_alarm", features)

    def test_tamper_true_in_state(self):
        """tamper=True must produce tamper_alarm=True in Sber state."""
        entity = SmokeSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("off", tamper=True))
        result = entity.to_sber_current_state()
        states = result["binary_sensor.smoke"]["states"]
        tamper = next(s for s in states if s["key"] == "tamper_alarm")
        self.assertTrue(tamper["value"]["bool_value"])

    def test_tamper_false_in_state(self):
        """tamper=False must produce tamper_alarm=False in Sber state."""
        entity = SmokeSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("off", tamper=False))
        result = entity.to_sber_current_state()
        states = result["binary_sensor.smoke"]["states"]
        tamper = next(s for s in states if s["key"] == "tamper_alarm")
        self.assertFalse(tamper["value"]["bool_value"])

    def test_tamper_not_in_state_when_absent(self):
        """Without tamper attribute, tamper_alarm must not appear in Sber state."""
        entity = SmokeSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("off"))
        result = entity.to_sber_current_state()
        states = result["binary_sensor.smoke"]["states"]
        keys = [s["key"] for s in states]
        self.assertNotIn("tamper_alarm", keys)


class TestSmokeSensorAlarmMute(unittest.TestCase):
    """Test alarm_mute feature in SmokeSensorEntity."""

    def test_alarm_mute_feature_present(self):
        """Entity with alarm_mute attribute must include alarm_mute in features."""
        entity = SmokeSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("off", alarm_mute=False))
        features = entity.get_final_features_list()
        self.assertIn("alarm_mute", features)

    def test_alarm_mute_feature_absent(self):
        """Entity without alarm_mute attribute must not include it."""
        entity = SmokeSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("off"))
        features = entity.get_final_features_list()
        self.assertNotIn("alarm_mute", features)

    def test_alarm_mute_true_in_state(self):
        """alarm_mute=True must produce alarm_mute=True in Sber state."""
        entity = SmokeSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("off", alarm_mute=True))
        result = entity.to_sber_current_state()
        states = result["binary_sensor.smoke"]["states"]
        am = next(s for s in states if s["key"] == "alarm_mute")
        self.assertTrue(am["value"]["bool_value"])

    def test_alarm_mute_false_in_state(self):
        """alarm_mute=False must produce alarm_mute=False in Sber state."""
        entity = SmokeSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("off", alarm_mute=False))
        result = entity.to_sber_current_state()
        states = result["binary_sensor.smoke"]["states"]
        am = next(s for s in states if s["key"] == "alarm_mute")
        self.assertFalse(am["value"]["bool_value"])

    def test_both_tamper_and_alarm_mute(self):
        """Both features must appear when both attributes are present."""
        entity = SmokeSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("on", tamper=True, alarm_mute=False))
        features = entity.get_final_features_list()
        self.assertIn("tamper_alarm", features)
        self.assertIn("alarm_mute", features)
        result = entity.to_sber_current_state()
        states = result["binary_sensor.smoke"]["states"]
        keys = [s["key"] for s in states]
        self.assertIn("tamper_alarm", keys)
        self.assertIn("alarm_mute", keys)


class TestSmokeSensorBattery(unittest.TestCase):
    """Test battery feature support."""

    def test_battery_in_features(self):
        entity = SmokeSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("off", battery=85))
        features = entity.get_final_features_list()
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
        features = entity.get_final_features_list()
        self.assertNotIn("battery_percentage", features)
