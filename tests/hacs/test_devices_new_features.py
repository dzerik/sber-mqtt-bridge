"""Tests for new features: air_pressure, signal_strength, tamper_alarm,
battery_low_power, child_lock, hvac_humidity_set, hvac_night_mode.
"""

import unittest

from custom_components.sber_mqtt_bridge.devices.climate import ClimateEntity
from custom_components.sber_mqtt_bridge.devices.curtain import CurtainEntity
from custom_components.sber_mqtt_bridge.devices.door_sensor import DoorSensorEntity
from custom_components.sber_mqtt_bridge.devices.humidifier import HumidifierEntity
from custom_components.sber_mqtt_bridge.devices.humidity_sensor import HumiditySensorEntity
from custom_components.sber_mqtt_bridge.devices.motion_sensor import MotionSensorEntity
from custom_components.sber_mqtt_bridge.devices.relay import RelayEntity
from custom_components.sber_mqtt_bridge.devices.sensor_temp import SensorTempEntity
from custom_components.sber_mqtt_bridge.devices.socket_entity import SocketEntity
from custom_components.sber_mqtt_bridge.devices.water_leak_sensor import WaterLeakSensorEntity

DOOR_DATA = {"entity_id": "binary_sensor.door", "name": "Door"}
MOTION_DATA = {"entity_id": "binary_sensor.motion", "name": "Motion"}
TEMP_DATA = {"entity_id": "sensor.temp", "name": "Temp"}
HUMIDITY_DATA = {"entity_id": "sensor.humidity", "name": "Humidity"}
LEAK_DATA = {"entity_id": "binary_sensor.leak", "name": "Leak"}
CURTAIN_DATA = {"entity_id": "cover.curtain", "name": "Curtain"}
RELAY_DATA = {"entity_id": "switch.relay", "name": "Relay"}
SOCKET_DATA = {"entity_id": "switch.socket", "name": "Socket"}
CLIMATE_DATA = {"entity_id": "climate.ac", "name": "AC"}
HUMIDIFIER_DATA = {"entity_id": "humidifier.hum", "name": "Humidifier"}


def _sensor_state(state="22.5", **attrs):
    return {"entity_id": "sensor.temp", "state": state, "attributes": attrs}


def _binary_state(entity_id, state="off", **attrs):
    return {"entity_id": entity_id, "state": state, "attributes": attrs}


def _cover_state(state="open", **attrs):
    return {"entity_id": "cover.curtain", "state": state, "attributes": attrs}


def _switch_state(entity_id="switch.relay", state="on", **attrs):
    return {"entity_id": entity_id, "state": state, "attributes": attrs}


def _climate_state(state="cool", **extra_attrs):
    attrs = {
        "current_temperature": 24.5,
        "temperature": 22.0,
        "fan_modes": ["auto", "low", "high"],
        "swing_modes": ["off", "vertical"],
        "hvac_modes": ["off", "cool", "heat"],
        "fan_mode": "auto",
        "swing_mode": "off",
        "min_temp": 16.0,
        "max_temp": 32.0,
    }
    attrs.update(extra_attrs)
    return {"entity_id": "climate.ac", "state": state, "attributes": attrs}


def _humidifier_state(state="on", **extra_attrs):
    attrs = {
        "humidity": 50,
        "current_humidity": 40,
        "available_modes": ["normal", "sleep", "turbo"],
        "mode": "normal",
    }
    attrs.update(extra_attrs)
    return {"entity_id": "humidifier.hum", "state": state, "attributes": attrs}


# === Task 1: air_pressure for sensor_temp ===


class TestAirPressure(unittest.TestCase):
    """Test air_pressure feature in SensorTempEntity."""

    def test_air_pressure_feature_present(self):
        entity = SensorTempEntity(TEMP_DATA)
        entity.fill_by_ha_state(_sensor_state(pressure=1013))
        features = entity.get_final_features_list()
        self.assertIn("air_pressure", features)

    def test_air_pressure_feature_absent(self):
        entity = SensorTempEntity(TEMP_DATA)
        entity.fill_by_ha_state(_sensor_state())
        features = entity.get_final_features_list()
        self.assertNotIn("air_pressure", features)

    def test_air_pressure_in_state(self):
        entity = SensorTempEntity(TEMP_DATA)
        entity.fill_by_ha_state(_sensor_state(pressure=1013))
        result = entity.to_sber_current_state()
        states = result["sensor.temp"]["states"]
        ap = next(s for s in states if s["key"] == "air_pressure")
        self.assertEqual(ap["value"]["type"], "INTEGER")
        self.assertEqual(ap["value"]["integer_value"], "1013")

    def test_air_pressure_not_in_state_when_absent(self):
        entity = SensorTempEntity(TEMP_DATA)
        entity.fill_by_ha_state(_sensor_state())
        result = entity.to_sber_current_state()
        states = result["sensor.temp"]["states"]
        keys = [s["key"] for s in states]
        self.assertNotIn("air_pressure", keys)

    def test_air_pressure_invalid_value(self):
        entity = SensorTempEntity(TEMP_DATA)
        entity.fill_by_ha_state(_sensor_state(pressure="invalid"))
        features = entity.get_final_features_list()
        self.assertNotIn("air_pressure", features)


# === Task 2: signal_strength for sensors ===


class TestSignalStrengthSensors(unittest.TestCase):
    """Test signal_strength feature in SimpleReadOnlySensor subclasses."""

    def test_signal_from_rssi(self):
        entity = DoorSensorEntity(DOOR_DATA)
        entity.fill_by_ha_state(_binary_state("binary_sensor.door", rssi=-45))
        features = entity.get_final_features_list()
        self.assertIn("signal_strength", features)

    def test_signal_from_linkquality(self):
        entity = MotionSensorEntity(MOTION_DATA)
        entity.fill_by_ha_state(_binary_state("binary_sensor.motion", linkquality=-60))
        features = entity.get_final_features_list()
        self.assertIn("signal_strength", features)

    def test_signal_from_signal_strength_attr(self):
        entity = WaterLeakSensorEntity(LEAK_DATA)
        entity.fill_by_ha_state(_binary_state("binary_sensor.leak", signal_strength=-80))
        features = entity.get_final_features_list()
        self.assertIn("signal_strength", features)

    def test_signal_absent(self):
        entity = DoorSensorEntity(DOOR_DATA)
        entity.fill_by_ha_state(_binary_state("binary_sensor.door"))
        features = entity.get_final_features_list()
        self.assertNotIn("signal_strength", features)

    def test_signal_high(self):
        entity = DoorSensorEntity(DOOR_DATA)
        entity.fill_by_ha_state(_binary_state("binary_sensor.door", rssi=-30))
        result = entity.to_sber_current_state()
        states = result["binary_sensor.door"]["states"]
        sig = next(s for s in states if s["key"] == "signal_strength")
        self.assertEqual(sig["value"]["enum_value"], "high")

    def test_signal_medium(self):
        entity = DoorSensorEntity(DOOR_DATA)
        entity.fill_by_ha_state(_binary_state("binary_sensor.door", rssi=-60))
        result = entity.to_sber_current_state()
        states = result["binary_sensor.door"]["states"]
        sig = next(s for s in states if s["key"] == "signal_strength")
        self.assertEqual(sig["value"]["enum_value"], "medium")

    def test_signal_low(self):
        entity = DoorSensorEntity(DOOR_DATA)
        entity.fill_by_ha_state(_binary_state("binary_sensor.door", rssi=-80))
        result = entity.to_sber_current_state()
        states = result["binary_sensor.door"]["states"]
        sig = next(s for s in states if s["key"] == "signal_strength")
        self.assertEqual(sig["value"]["enum_value"], "low")

    def test_signal_invalid_ignored(self):
        entity = DoorSensorEntity(DOOR_DATA)
        entity.fill_by_ha_state(_binary_state("binary_sensor.door", rssi="invalid"))
        features = entity.get_final_features_list()
        self.assertNotIn("signal_strength", features)


class TestSignalStrengthCurtain(unittest.TestCase):
    """Test signal_strength feature in CurtainEntity."""

    def test_signal_present(self):
        entity = CurtainEntity(CURTAIN_DATA)
        entity.fill_by_ha_state(_cover_state(rssi=-55))
        features = entity.get_final_features_list()
        self.assertIn("signal_strength", features)

    def test_signal_absent(self):
        entity = CurtainEntity(CURTAIN_DATA)
        entity.fill_by_ha_state(_cover_state())
        features = entity.get_final_features_list()
        self.assertNotIn("signal_strength", features)

    def test_signal_in_state(self):
        entity = CurtainEntity(CURTAIN_DATA)
        entity.fill_by_ha_state(_cover_state(rssi=-55, current_position=50))
        result = entity.to_sber_current_state()
        states = result["cover.curtain"]["states"]
        sig = next(s for s in states if s["key"] == "signal_strength")
        self.assertEqual(sig["value"]["enum_value"], "medium")

    def test_signal_not_in_state_when_absent(self):
        entity = CurtainEntity(CURTAIN_DATA)
        entity.fill_by_ha_state(_cover_state(current_position=50))
        result = entity.to_sber_current_state()
        states = result["cover.curtain"]["states"]
        keys = [s["key"] for s in states]
        self.assertNotIn("signal_strength", keys)


# === Task 3: tamper_alarm for door and motion sensors ===


class TestTamperAlarmDoor(unittest.TestCase):
    """Test tamper_alarm feature in DoorSensorEntity."""

    def test_tamper_feature_present(self):
        entity = DoorSensorEntity(DOOR_DATA)
        entity.fill_by_ha_state(_binary_state("binary_sensor.door", tamper=True))
        features = entity.get_final_features_list()
        self.assertIn("tamper_alarm", features)

    def test_tamper_feature_absent(self):
        entity = DoorSensorEntity(DOOR_DATA)
        entity.fill_by_ha_state(_binary_state("binary_sensor.door"))
        features = entity.get_final_features_list()
        self.assertNotIn("tamper_alarm", features)

    def test_tamper_true_in_state(self):
        entity = DoorSensorEntity(DOOR_DATA)
        entity.fill_by_ha_state(_binary_state("binary_sensor.door", tamper=True))
        result = entity.to_sber_current_state()
        states = result["binary_sensor.door"]["states"]
        tamper = next(s for s in states if s["key"] == "tamper_alarm")
        self.assertTrue(tamper["value"]["bool_value"])

    def test_tamper_false_in_state(self):
        entity = DoorSensorEntity(DOOR_DATA)
        entity.fill_by_ha_state(_binary_state("binary_sensor.door", tamper=False))
        result = entity.to_sber_current_state()
        states = result["binary_sensor.door"]["states"]
        tamper = next(s for s in states if s["key"] == "tamper_alarm")
        self.assertFalse(tamper["value"]["bool_value"])


class TestTamperAlarmMotion(unittest.TestCase):
    """Test tamper_alarm feature in MotionSensorEntity."""

    def test_tamper_feature_present(self):
        entity = MotionSensorEntity(MOTION_DATA)
        entity.fill_by_ha_state(_binary_state("binary_sensor.motion", tamper=True))
        features = entity.get_final_features_list()
        self.assertIn("tamper_alarm", features)

    def test_tamper_feature_absent(self):
        entity = MotionSensorEntity(MOTION_DATA)
        entity.fill_by_ha_state(_binary_state("binary_sensor.motion"))
        features = entity.get_final_features_list()
        self.assertNotIn("tamper_alarm", features)

    def test_tamper_in_state(self):
        entity = MotionSensorEntity(MOTION_DATA)
        entity.fill_by_ha_state(_binary_state("binary_sensor.motion", tamper=True))
        result = entity.to_sber_current_state()
        states = result["binary_sensor.motion"]["states"]
        tamper = next(s for s in states if s["key"] == "tamper_alarm")
        self.assertTrue(tamper["value"]["bool_value"])


# === Task 4: battery_low_power for sensors ===


class TestBatteryLowPower(unittest.TestCase):
    """Test battery_low_power feature in SimpleReadOnlySensor subclasses."""

    def test_battery_low_feature_present(self):
        entity = DoorSensorEntity(DOOR_DATA)
        entity.fill_by_ha_state(_binary_state("binary_sensor.door", battery=15))
        features = entity.get_final_features_list()
        self.assertIn("battery_low_power", features)

    def test_battery_low_true_when_below_20(self):
        entity = DoorSensorEntity(DOOR_DATA)
        entity.fill_by_ha_state(_binary_state("binary_sensor.door", battery=15))
        result = entity.to_sber_current_state()
        states = result["binary_sensor.door"]["states"]
        blp = next(s for s in states if s["key"] == "battery_low_power")
        self.assertTrue(blp["value"]["bool_value"])

    def test_battery_low_false_when_above_20(self):
        entity = DoorSensorEntity(DOOR_DATA)
        entity.fill_by_ha_state(_binary_state("binary_sensor.door", battery=80))
        result = entity.to_sber_current_state()
        states = result["binary_sensor.door"]["states"]
        blp = next(s for s in states if s["key"] == "battery_low_power")
        self.assertFalse(blp["value"]["bool_value"])

    def test_battery_low_absent_without_battery(self):
        entity = DoorSensorEntity(DOOR_DATA)
        entity.fill_by_ha_state(_binary_state("binary_sensor.door"))
        features = entity.get_final_features_list()
        self.assertNotIn("battery_low_power", features)

    def test_battery_low_at_boundary(self):
        entity = DoorSensorEntity(DOOR_DATA)
        entity.fill_by_ha_state(_binary_state("binary_sensor.door", battery=20))
        result = entity.to_sber_current_state()
        states = result["binary_sensor.door"]["states"]
        blp = next(s for s in states if s["key"] == "battery_low_power")
        # 20 is NOT < 20, so should be False
        self.assertFalse(blp["value"]["bool_value"])

    def test_battery_low_with_motion_sensor(self):
        entity = MotionSensorEntity(MOTION_DATA)
        entity.fill_by_ha_state(_binary_state("binary_sensor.motion", battery=5))
        result = entity.to_sber_current_state()
        states = result["binary_sensor.motion"]["states"]
        blp = next(s for s in states if s["key"] == "battery_low_power")
        self.assertTrue(blp["value"]["bool_value"])


# === Task 5: child_lock for OnOffEntity (relay/socket) ===


class TestChildLock(unittest.TestCase):
    """Test child_lock feature in OnOffEntity."""

    def test_child_lock_feature_present(self):
        entity = SocketEntity(SOCKET_DATA)
        entity.fill_by_ha_state(_switch_state("switch.socket", child_lock=True))
        features = entity.get_final_features_list()
        self.assertIn("child_lock", features)

    def test_child_lock_feature_absent(self):
        entity = SocketEntity(SOCKET_DATA)
        entity.fill_by_ha_state(_switch_state("switch.socket"))
        features = entity.get_final_features_list()
        self.assertNotIn("child_lock", features)

    def test_child_lock_true_in_state(self):
        entity = SocketEntity(SOCKET_DATA)
        entity.fill_by_ha_state(_switch_state("switch.socket", child_lock=True))
        result = entity.to_sber_current_state()
        states = result["switch.socket"]["states"]
        cl = next(s for s in states if s["key"] == "child_lock")
        self.assertTrue(cl["value"]["bool_value"])

    def test_child_lock_false_in_state(self):
        entity = SocketEntity(SOCKET_DATA)
        entity.fill_by_ha_state(_switch_state("switch.socket", child_lock=False))
        result = entity.to_sber_current_state()
        states = result["switch.socket"]["states"]
        cl = next(s for s in states if s["key"] == "child_lock")
        self.assertFalse(cl["value"]["bool_value"])

    def test_child_lock_on_relay(self):
        entity = RelayEntity(RELAY_DATA)
        entity.fill_by_ha_state(_switch_state("switch.relay", child_lock=True))
        features = entity.get_final_features_list()
        self.assertIn("child_lock", features)


# === Task 7: hvac_humidity_set for climate ===


class TestClimateHumiditySet(unittest.TestCase):
    """Test hvac_humidity_set feature in ClimateEntity."""

    def test_humidity_set_feature_present(self):
        entity = ClimateEntity(CLIMATE_DATA)
        entity.fill_by_ha_state(_climate_state(target_humidity=50))
        features = entity.get_final_features_list()
        self.assertIn("hvac_humidity_set", features)

    def test_humidity_set_feature_absent(self):
        entity = ClimateEntity(CLIMATE_DATA)
        entity.fill_by_ha_state(_climate_state())
        features = entity.get_final_features_list()
        self.assertNotIn("hvac_humidity_set", features)

    def test_humidity_set_in_state(self):
        entity = ClimateEntity(CLIMATE_DATA)
        entity.fill_by_ha_state(_climate_state(target_humidity=60))
        result = entity.to_sber_current_state()
        states = result["climate.ac"]["states"]
        hs = next(s for s in states if s["key"] == "hvac_humidity_set")
        self.assertEqual(hs["value"]["type"], "INTEGER")
        self.assertEqual(hs["value"]["integer_value"], "60")

    def test_humidity_set_not_in_state_when_absent(self):
        entity = ClimateEntity(CLIMATE_DATA)
        entity.fill_by_ha_state(_climate_state())
        result = entity.to_sber_current_state()
        states = result["climate.ac"]["states"]
        keys = [s["key"] for s in states]
        self.assertNotIn("hvac_humidity_set", keys)

    def test_humidity_set_process_cmd(self):
        entity = ClimateEntity(CLIMATE_DATA)
        entity.fill_by_ha_state(_climate_state())
        cmd = {"states": [{"key": "hvac_humidity_set", "value": {"type": "INTEGER", "integer_value": "55"}}]}
        results = entity.process_cmd(cmd)
        self.assertEqual(len(results), 1)
        svc = results[0]["url"]
        self.assertEqual(svc["service"], "set_humidity")
        self.assertEqual(svc["service_data"]["humidity"], 55)


# === Task 8: hvac_night_mode for climate and humidifier ===


class TestClimateNightMode(unittest.TestCase):
    """Test hvac_night_mode feature in ClimateEntity."""

    def test_night_mode_feature_present(self):
        entity = ClimateEntity(CLIMATE_DATA)
        entity.fill_by_ha_state(_climate_state(preset_modes=["none", "sleep", "eco"]))
        features = entity.get_final_features_list()
        self.assertIn("hvac_night_mode", features)

    def test_night_mode_feature_absent(self):
        entity = ClimateEntity(CLIMATE_DATA)
        entity.fill_by_ha_state(_climate_state(preset_modes=["none", "eco"]))
        features = entity.get_final_features_list()
        self.assertNotIn("hvac_night_mode", features)

    def test_night_mode_feature_absent_no_presets(self):
        entity = ClimateEntity(CLIMATE_DATA)
        entity.fill_by_ha_state(_climate_state())
        features = entity.get_final_features_list()
        self.assertNotIn("hvac_night_mode", features)

    def test_night_mode_true_in_state(self):
        entity = ClimateEntity(CLIMATE_DATA)
        entity.fill_by_ha_state(_climate_state(preset_modes=["none", "sleep"], preset_mode="sleep"))
        result = entity.to_sber_current_state()
        states = result["climate.ac"]["states"]
        nm = next(s for s in states if s["key"] == "hvac_night_mode")
        self.assertTrue(nm["value"]["bool_value"])

    def test_night_mode_false_in_state(self):
        entity = ClimateEntity(CLIMATE_DATA)
        entity.fill_by_ha_state(_climate_state(preset_modes=["none", "sleep"], preset_mode="none"))
        result = entity.to_sber_current_state()
        states = result["climate.ac"]["states"]
        nm = next(s for s in states if s["key"] == "hvac_night_mode")
        self.assertFalse(nm["value"]["bool_value"])

    def test_night_mode_process_cmd_on(self):
        entity = ClimateEntity(CLIMATE_DATA)
        entity.fill_by_ha_state(_climate_state(preset_modes=["none", "sleep"]))
        cmd = {"states": [{"key": "hvac_night_mode", "value": {"type": "BOOL", "bool_value": True}}]}
        results = entity.process_cmd(cmd)
        self.assertEqual(len(results), 1)
        svc = results[0]["url"]
        self.assertEqual(svc["service"], "set_preset_mode")
        self.assertEqual(svc["service_data"]["preset_mode"], "sleep")

    def test_night_mode_process_cmd_off(self):
        entity = ClimateEntity(CLIMATE_DATA)
        entity.fill_by_ha_state(_climate_state(preset_modes=["none", "sleep"]))
        cmd = {"states": [{"key": "hvac_night_mode", "value": {"type": "BOOL", "bool_value": False}}]}
        results = entity.process_cmd(cmd)
        self.assertEqual(len(results), 1)
        svc = results[0]["url"]
        self.assertEqual(svc["service"], "set_preset_mode")
        self.assertEqual(svc["service_data"]["preset_mode"], "none")

    def test_night_mode_with_night_keyword(self):
        entity = ClimateEntity(CLIMATE_DATA)
        entity.fill_by_ha_state(_climate_state(preset_modes=["none", "night"]))
        features = entity.get_final_features_list()
        self.assertIn("hvac_night_mode", features)
        cmd = {"states": [{"key": "hvac_night_mode", "value": {"type": "BOOL", "bool_value": True}}]}
        results = entity.process_cmd(cmd)
        svc = results[0]["url"]
        self.assertEqual(svc["service_data"]["preset_mode"], "night")


class TestHumidifierNightMode(unittest.TestCase):
    """Test hvac_night_mode feature in HumidifierEntity."""

    def test_night_mode_feature_present(self):
        entity = HumidifierEntity(HUMIDIFIER_DATA)
        entity.fill_by_ha_state(_humidifier_state())  # has "sleep" in modes
        features = entity.get_final_features_list()
        self.assertIn("hvac_night_mode", features)

    def test_night_mode_feature_absent(self):
        entity = HumidifierEntity(HUMIDIFIER_DATA)
        entity.fill_by_ha_state(_humidifier_state(available_modes=["normal", "turbo"]))
        features = entity.get_final_features_list()
        self.assertNotIn("hvac_night_mode", features)

    def test_night_mode_true_in_state(self):
        entity = HumidifierEntity(HUMIDIFIER_DATA)
        entity.fill_by_ha_state(_humidifier_state(mode="sleep"))
        result = entity.to_sber_current_state()
        states = result["humidifier.hum"]["states"]
        nm = next(s for s in states if s["key"] == "hvac_night_mode")
        self.assertTrue(nm["value"]["bool_value"])

    def test_night_mode_false_in_state(self):
        entity = HumidifierEntity(HUMIDIFIER_DATA)
        entity.fill_by_ha_state(_humidifier_state(mode="normal"))
        result = entity.to_sber_current_state()
        states = result["humidifier.hum"]["states"]
        nm = next(s for s in states if s["key"] == "hvac_night_mode")
        self.assertFalse(nm["value"]["bool_value"])

    def test_night_mode_process_cmd_on(self):
        entity = HumidifierEntity(HUMIDIFIER_DATA)
        entity.fill_by_ha_state(_humidifier_state())
        cmd = {"states": [{"key": "hvac_night_mode", "value": {"type": "BOOL", "bool_value": True}}]}
        results = entity.process_cmd(cmd)
        self.assertEqual(len(results), 1)
        svc = results[0]["url"]
        self.assertEqual(svc["service"], "set_mode")
        self.assertEqual(svc["service_data"]["mode"], "sleep")

    def test_night_mode_process_cmd_off(self):
        entity = HumidifierEntity(HUMIDIFIER_DATA)
        entity.fill_by_ha_state(_humidifier_state())
        cmd = {"states": [{"key": "hvac_night_mode", "value": {"type": "BOOL", "bool_value": False}}]}
        results = entity.process_cmd(cmd)
        self.assertEqual(len(results), 1)
        svc = results[0]["url"]
        self.assertEqual(svc["service"], "set_mode")
        # Should pick first non-night mode
        self.assertEqual(svc["service_data"]["mode"], "normal")
