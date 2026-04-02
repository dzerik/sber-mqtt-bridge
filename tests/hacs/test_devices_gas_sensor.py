"""Tests for GasSensorEntity -- Sber gas sensor device mapping."""

import unittest

from custom_components.sber_mqtt_bridge.devices.gas_sensor import GasSensorEntity


ENTITY_DATA = {"entity_id": "binary_sensor.gas", "name": "Gas Detector"}


def _make_ha_state(state="off", **attrs):
    return {
        "entity_id": "binary_sensor.gas",
        "state": state,
        "attributes": attrs,
    }


class TestGasSensorCreate(unittest.TestCase):
    """Test GasSensorEntity initialization."""

    def test_category(self):
        entity = GasSensorEntity(ENTITY_DATA)
        self.assertEqual(entity.category, "sensor_gas")

    def test_initial_state(self):
        entity = GasSensorEntity(ENTITY_DATA)
        self.assertFalse(entity.gas_detected)

    def test_sber_value_key(self):
        entity = GasSensorEntity(ENTITY_DATA)
        self.assertEqual(entity._sber_value_key, "gas_leak_state")


class TestGasSensorToSberCurrentState(unittest.TestCase):
    """Test to_sber_current_state."""

    def test_gas_detected(self):
        entity = GasSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("on"))
        result = entity.to_sber_current_state()
        states = result["binary_sensor.gas"]["states"]
        gas = next(s for s in states if s["key"] == "gas_leak_state")
        self.assertEqual(gas["value"]["type"], "BOOL")
        self.assertTrue(gas["value"]["bool_value"])

    def test_no_gas(self):
        entity = GasSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("off"))
        result = entity.to_sber_current_state()
        states = result["binary_sensor.gas"]["states"]
        gas = next(s for s in states if s["key"] == "gas_leak_state")
        self.assertFalse(gas["value"]["bool_value"])

    def test_online_status(self):
        entity = GasSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("unavailable"))
        result = entity.to_sber_current_state()
        states = result["binary_sensor.gas"]["states"]
        online = next(s for s in states if s["key"] == "online")
        self.assertFalse(online["value"]["bool_value"])


class TestGasSensorTamperAlarm(unittest.TestCase):
    """Test tamper_alarm feature in GasSensorEntity."""

    def test_tamper_feature_present_when_true(self):
        """Entity with tamper=True must include tamper_alarm in features."""
        entity = GasSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("off", tamper=True))
        features = entity.create_features_list()
        self.assertIn("tamper_alarm", features)

    def test_tamper_feature_present_when_false(self):
        """Entity with tamper=False must still include tamper_alarm in features."""
        entity = GasSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("off", tamper=False))
        features = entity.create_features_list()
        self.assertIn("tamper_alarm", features)

    def test_tamper_feature_absent_without_attribute(self):
        """Entity without tamper attribute must not include tamper_alarm."""
        entity = GasSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("off"))
        features = entity.create_features_list()
        self.assertNotIn("tamper_alarm", features)

    def test_tamper_true_in_state(self):
        """tamper=True must produce tamper_alarm=True in Sber state."""
        entity = GasSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("off", tamper=True))
        result = entity.to_sber_current_state()
        states = result["binary_sensor.gas"]["states"]
        tamper = next(s for s in states if s["key"] == "tamper_alarm")
        self.assertTrue(tamper["value"]["bool_value"])

    def test_tamper_false_in_state(self):
        """tamper=False must produce tamper_alarm=False in Sber state."""
        entity = GasSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("off", tamper=False))
        result = entity.to_sber_current_state()
        states = result["binary_sensor.gas"]["states"]
        tamper = next(s for s in states if s["key"] == "tamper_alarm")
        self.assertFalse(tamper["value"]["bool_value"])

    def test_tamper_not_in_state_when_absent(self):
        """Without tamper attribute, tamper_alarm must not appear in Sber state."""
        entity = GasSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("off"))
        result = entity.to_sber_current_state()
        states = result["binary_sensor.gas"]["states"]
        keys = [s["key"] for s in states]
        self.assertNotIn("tamper_alarm", keys)


class TestGasSensorAlarmMute(unittest.TestCase):
    """Test alarm_mute feature in GasSensorEntity."""

    def test_alarm_mute_feature_present(self):
        """Entity with alarm_mute attribute must include alarm_mute in features."""
        entity = GasSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("off", alarm_mute=False))
        features = entity.create_features_list()
        self.assertIn("alarm_mute", features)

    def test_alarm_mute_feature_absent(self):
        """Entity without alarm_mute must not include it."""
        entity = GasSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("off"))
        features = entity.create_features_list()
        self.assertNotIn("alarm_mute", features)

    def test_alarm_mute_in_state(self):
        """alarm_mute=True must appear in Sber state."""
        entity = GasSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("off", alarm_mute=True))
        result = entity.to_sber_current_state()
        states = result["binary_sensor.gas"]["states"]
        am = next(s for s in states if s["key"] == "alarm_mute")
        self.assertTrue(am["value"]["bool_value"])


class TestGasSensorProcessCmd(unittest.TestCase):
    """Test process_cmd (read-only)."""

    def test_cmd_is_noop(self):
        entity = GasSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("off"))
        result = entity.process_cmd({"states": []})
        self.assertEqual(result, [])
