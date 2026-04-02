"""Sber C2C protocol compliance tests for sensors, covers, TV, and fan entities.

Validates JSON output against the Sber C2C documentation specification:
- Config JSON (to_sber_state): required fields, category, features, allowed_values
- State JSON (to_sber_current_state): integer_value as string, ENUM values, BOOL values
- Command processing (process_cmd): correct HA service calls, no crashes on unknown commands
"""

from __future__ import annotations

import pytest

from custom_components.sber_mqtt_bridge.devices.curtain import CurtainEntity
from custom_components.sber_mqtt_bridge.devices.door_sensor import DoorSensorEntity
from custom_components.sber_mqtt_bridge.devices.gas_sensor import GasSensorEntity
from custom_components.sber_mqtt_bridge.devices.humidity_sensor import (
    HumiditySensorEntity,
)
from custom_components.sber_mqtt_bridge.devices.hvac_fan import HvacFanEntity
from custom_components.sber_mqtt_bridge.devices.motion_sensor import MotionSensorEntity
from custom_components.sber_mqtt_bridge.devices.sensor_temp import SensorTempEntity
from custom_components.sber_mqtt_bridge.devices.smoke_sensor import SmokeSensorEntity
from custom_components.sber_mqtt_bridge.devices.tv import TvEntity
from custom_components.sber_mqtt_bridge.devices.water_leak_sensor import (
    WaterLeakSensorEntity,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_state(states: list[dict], key: str) -> dict | None:
    """Find a state entry by key in the Sber states list."""
    for s in states:
        if s.get("key") == key:
            return s
    return None


def _get_states(entity, entity_id: str) -> list[dict]:
    """Extract states list from to_sber_current_state for the given entity_id."""
    result = entity.to_sber_current_state()
    assert entity_id in result, f"entity_id {entity_id} not in result keys"
    return result[entity_id]["states"]


def _assert_integer_value_is_string(states: list[dict], key: str) -> None:
    """Assert that the integer_value for a given key is serialized as a string."""
    entry = _find_state(states, key)
    assert entry is not None, f"key '{key}' not found in states"
    value = entry["value"]
    assert value["type"] == "INTEGER", f"Expected INTEGER type for '{key}', got {value['type']}"
    assert isinstance(value["integer_value"], str), (
        f"integer_value for '{key}' must be str, got {type(value['integer_value']).__name__}: "
        f"{value['integer_value']!r}"
    )


def _assert_bool_value(states: list[dict], key: str, expected: bool) -> None:
    """Assert that a BOOL state entry has the expected value."""
    entry = _find_state(states, key)
    assert entry is not None, f"key '{key}' not found in states"
    value = entry["value"]
    assert value["type"] == "BOOL", f"Expected BOOL type for '{key}', got {value['type']}"
    assert value["bool_value"] is expected, (
        f"Expected bool_value={expected} for '{key}', got {value['bool_value']}"
    )


def _assert_enum_value(states: list[dict], key: str, expected: str) -> None:
    """Assert that an ENUM state entry has the expected value."""
    entry = _find_state(states, key)
    assert entry is not None, f"key '{key}' not found in states"
    value = entry["value"]
    assert value["type"] == "ENUM", f"Expected ENUM type for '{key}', got {value['type']}"
    assert value["enum_value"] == expected, (
        f"Expected enum_value='{expected}' for '{key}', got '{value['enum_value']}'"
    )


def _assert_config_has_required_fields(config: dict) -> None:
    """Assert the Sber config JSON has all required top-level fields."""
    for field in ("id", "name", "room", "model", "hw_version", "sw_version"):
        assert field in config, f"Missing required field '{field}' in config"
    model = config["model"]
    for field in ("id", "manufacturer", "model", "category", "features"):
        assert field in model, f"Missing required field '{field}' in model"


# ---------------------------------------------------------------------------
# SensorTempEntity -- category: sensor_temp
# ---------------------------------------------------------------------------

class TestSensorTempCompliance:
    """Sber C2C compliance tests for SensorTempEntity."""

    ENTITY_ID = "sensor.living_temp"
    ENTITY_DATA = {"entity_id": ENTITY_ID, "name": "Living Temperature"}

    def _make_entity(self, state="22.5", **attrs) -> SensorTempEntity:
        entity = SensorTempEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state({
            "entity_id": self.ENTITY_ID,
            "state": state,
            "attributes": attrs,
        })
        return entity

    def test_category_is_sensor_temp(self):
        """Category must be 'sensor_temp' per Sber spec."""
        entity = SensorTempEntity(self.ENTITY_DATA)
        assert entity.category == "sensor_temp"

    def test_features_minimal(self):
        """Minimal features: online, temperature, temp_unit_view."""
        entity = self._make_entity()
        features = entity.create_features_list()
        assert "online" in features
        assert "temperature" in features
        assert "temp_unit_view" in features

    def test_features_with_linked_humidity(self):
        """When humidity is linked, 'humidity' feature must appear."""
        entity = self._make_entity()
        entity.update_linked_data("humidity", {"state": "55"})
        features = entity.create_features_list()
        assert "humidity" in features

    def test_features_no_humidity_without_link(self):
        """Without linked humidity, 'humidity' feature must not appear."""
        entity = self._make_entity()
        features = entity.create_features_list()
        assert "humidity" not in features

    def test_features_with_battery(self):
        """When battery attr present, battery_percentage + battery_low_power appear."""
        entity = self._make_entity(battery=85)
        features = entity.create_features_list()
        assert "battery_percentage" in features
        assert "battery_low_power" in features

    def test_features_with_sensitivity(self):
        """When sensitivity attr present, sensor_sensitive feature appears."""
        entity = self._make_entity(sensitivity="high")
        features = entity.create_features_list()
        assert "sensor_sensitive" in features

    def test_temperature_integer_value_is_string(self):
        """CRITICAL: temperature integer_value must be a string per Sber spec."""
        entity = self._make_entity("22.5")
        states = _get_states(entity, self.ENTITY_ID)
        _assert_integer_value_is_string(states, "temperature")

    def test_temperature_scaled_by_10(self):
        """Temperature must be multiplied by 10: 22.5C -> '225'."""
        entity = self._make_entity("22.5")
        states = _get_states(entity, self.ENTITY_ID)
        entry = _find_state(states, "temperature")
        assert entry["value"]["integer_value"] == "225"

    def test_temperature_negative(self):
        """Negative temperature: -5.3C -> '-53'."""
        entity = self._make_entity("-5.3")
        states = _get_states(entity, self.ENTITY_ID)
        entry = _find_state(states, "temperature")
        assert entry["value"]["integer_value"] == "-53"

    def test_temperature_zero(self):
        """Zero temperature: 0C -> '0'."""
        entity = self._make_entity("0")
        states = _get_states(entity, self.ENTITY_ID)
        entry = _find_state(states, "temperature")
        assert entry["value"]["integer_value"] == "0"

    def test_humidity_linked_integer_value_is_string(self):
        """Linked humidity integer_value must be a string."""
        entity = self._make_entity()
        entity.update_linked_data("humidity", {"state": "55"})
        states = _get_states(entity, self.ENTITY_ID)
        _assert_integer_value_is_string(states, "humidity")

    def test_humidity_linked_value(self):
        """Linked humidity 55% -> '55'."""
        entity = self._make_entity()
        entity.update_linked_data("humidity", {"state": "55.2"})
        states = _get_states(entity, self.ENTITY_ID)
        entry = _find_state(states, "humidity")
        assert entry["value"]["integer_value"] == "55"

    def test_temp_unit_celsius(self):
        """Default temp_unit_view must be 'c' for Celsius."""
        entity = self._make_entity("20", unit_of_measurement="°C")
        states = _get_states(entity, self.ENTITY_ID)
        _assert_enum_value(states, "temp_unit_view", "c")

    def test_temp_unit_fahrenheit(self):
        """Fahrenheit unit must produce temp_unit_view='f'."""
        entity = self._make_entity("72", unit_of_measurement="°F")
        states = _get_states(entity, self.ENTITY_ID)
        _assert_enum_value(states, "temp_unit_view", "f")

    def test_battery_integer_value_is_string(self):
        """Battery percentage integer_value must be string."""
        entity = self._make_entity(battery=85)
        states = _get_states(entity, self.ENTITY_ID)
        _assert_integer_value_is_string(states, "battery_percentage")

    def test_online_true_when_available(self):
        """Online must be true when sensor has valid state."""
        entity = self._make_entity("22.5")
        states = _get_states(entity, self.ENTITY_ID)
        _assert_bool_value(states, "online", True)

    def test_online_false_when_unavailable(self):
        """Online must be false when sensor state is 'unavailable'."""
        entity = self._make_entity("unavailable")
        states = _get_states(entity, self.ENTITY_ID)
        _assert_bool_value(states, "online", False)

    def test_read_only_no_commands(self):
        """Temperature sensor must not process any commands (read-only)."""
        entity = self._make_entity()
        result = entity.process_cmd({"states": [{"key": "temperature", "value": {}}]})
        assert result == []

    def test_config_json_required_fields(self):
        """Config JSON must have all required Sber fields."""
        entity = self._make_entity()
        config = entity.to_sber_state()
        _assert_config_has_required_fields(config)
        assert config["model"]["category"] == "sensor_temp"

    def test_air_pressure_when_available(self):
        """When pressure attribute present, air_pressure feature and state appear."""
        entity = self._make_entity("22.5", pressure=1013)
        features = entity.create_features_list()
        assert "air_pressure" in features
        states = _get_states(entity, self.ENTITY_ID)
        _assert_integer_value_is_string(states, "air_pressure")

    def test_invalid_state_no_crash(self):
        """Invalid state value must not crash, temperature defaults to 0."""
        entity = self._make_entity("not_a_number")
        states = _get_states(entity, self.ENTITY_ID)
        entry = _find_state(states, "temperature")
        assert entry["value"]["integer_value"] == "0"


# ---------------------------------------------------------------------------
# HumiditySensorEntity -- category: sensor_temp
# ---------------------------------------------------------------------------

class TestHumiditySensorCompliance:
    """Sber C2C compliance tests for HumiditySensorEntity."""

    ENTITY_ID = "sensor.living_humidity"
    ENTITY_DATA = {"entity_id": ENTITY_ID, "name": "Living Humidity"}

    def _make_entity(self, state="55", **attrs) -> HumiditySensorEntity:
        entity = HumiditySensorEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state({
            "entity_id": self.ENTITY_ID,
            "state": state,
            "attributes": attrs,
        })
        return entity

    def test_category_is_sensor_temp(self):
        """HumiditySensor uses category 'sensor_temp' (shared with temp sensor)."""
        entity = HumiditySensorEntity(self.ENTITY_DATA)
        assert entity.category == "sensor_temp"

    def test_features_minimal(self):
        """Minimal features: online, humidity."""
        entity = self._make_entity()
        features = entity.create_features_list()
        assert "online" in features
        assert "humidity" in features

    def test_features_with_linked_temperature(self):
        """When temperature is linked, 'temperature' feature must appear."""
        entity = self._make_entity()
        entity.update_linked_data("temperature", {"state": "22.5"})
        features = entity.create_features_list()
        assert "temperature" in features

    def test_features_with_battery(self):
        """Battery features when battery attr present."""
        entity = self._make_entity(battery=60)
        features = entity.create_features_list()
        assert "battery_percentage" in features
        assert "battery_low_power" in features

    def test_humidity_integer_value_is_string(self):
        """CRITICAL: humidity integer_value must be a string."""
        entity = self._make_entity("55")
        states = _get_states(entity, self.ENTITY_ID)
        _assert_integer_value_is_string(states, "humidity")

    def test_humidity_rounded_to_int(self):
        """Humidity 55.7% -> '56' (rounded)."""
        entity = self._make_entity("55.7")
        states = _get_states(entity, self.ENTITY_ID)
        entry = _find_state(states, "humidity")
        assert entry["value"]["integer_value"] == "56"

    def test_humidity_zero(self):
        """Humidity 0% -> '0'."""
        entity = self._make_entity("0")
        states = _get_states(entity, self.ENTITY_ID)
        entry = _find_state(states, "humidity")
        assert entry["value"]["integer_value"] == "0"

    def test_linked_temperature_scaled_by_10(self):
        """Linked temperature 22.5C must appear as '225' (scaled by 10)."""
        entity = self._make_entity()
        entity.update_linked_data("temperature", {"state": "22.5"})
        states = _get_states(entity, self.ENTITY_ID)
        entry = _find_state(states, "temperature")
        assert entry is not None
        assert entry["value"]["integer_value"] == "225"

    def test_linked_temperature_integer_value_is_string(self):
        """Linked temperature integer_value must be a string."""
        entity = self._make_entity()
        entity.update_linked_data("temperature", {"state": "20"})
        states = _get_states(entity, self.ENTITY_ID)
        _assert_integer_value_is_string(states, "temperature")

    def test_read_only_no_commands(self):
        """Humidity sensor must not process any commands."""
        entity = self._make_entity()
        result = entity.process_cmd({"states": [{"key": "humidity", "value": {}}]})
        assert result == []

    def test_config_json_category(self):
        """Config category must be 'sensor_temp'."""
        entity = self._make_entity()
        config = entity.to_sber_state()
        assert config["model"]["category"] == "sensor_temp"


# ---------------------------------------------------------------------------
# MotionSensorEntity -- category: sensor_pir
# ---------------------------------------------------------------------------

class TestMotionSensorCompliance:
    """Sber C2C compliance tests for MotionSensorEntity."""

    ENTITY_ID = "binary_sensor.hallway_motion"
    ENTITY_DATA = {"entity_id": ENTITY_ID, "name": "Hallway Motion"}

    def _make_entity(self, state="off", **attrs) -> MotionSensorEntity:
        entity = MotionSensorEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state({
            "entity_id": self.ENTITY_ID,
            "state": state,
            "attributes": attrs,
        })
        return entity

    def test_category_is_sensor_pir(self):
        """Category must be 'sensor_pir'."""
        entity = MotionSensorEntity(self.ENTITY_DATA)
        assert entity.category == "sensor_pir"

    def test_features_minimal(self):
        """Minimal features: online, pir."""
        entity = self._make_entity()
        features = entity.create_features_list()
        assert "online" in features
        assert "pir" in features

    def test_features_with_tamper(self):
        """When tamper attr present, tamper_alarm feature appears."""
        entity = self._make_entity(tamper=False)
        features = entity.create_features_list()
        assert "tamper_alarm" in features

    def test_features_with_battery(self):
        """Battery features when battery available."""
        entity = self._make_entity(battery=80)
        features = entity.create_features_list()
        assert "battery_percentage" in features
        assert "battery_low_power" in features

    def test_pir_present_when_motion_detected(self):
        """CRITICAL: pir key must be present with enum_value='pir' when motion detected."""
        entity = self._make_entity("on")
        states = _get_states(entity, self.ENTITY_ID)
        _assert_enum_value(states, "pir", "pir")

    def test_pir_absent_when_no_motion(self):
        """CRITICAL: pir key must be ABSENT from state when no motion (event-based)."""
        entity = self._make_entity("off")
        states = _get_states(entity, self.ENTITY_ID)
        pir_entry = _find_state(states, "pir")
        assert pir_entry is None, (
            f"pir key must NOT be in state when motion_detected=False, "
            f"but found: {pir_entry}"
        )

    def test_pir_absent_when_unknown(self):
        """pir key must be absent when state is 'unknown' (no event yet)."""
        entity = self._make_entity("unknown")
        states = _get_states(entity, self.ENTITY_ID)
        pir_entry = _find_state(states, "pir")
        assert pir_entry is None, "pir key must not appear when state is 'unknown'"

    def test_online_true_when_unknown(self):
        """Motion sensor treats 'unknown' as online (event-based, no event yet)."""
        entity = self._make_entity("unknown")
        states = _get_states(entity, self.ENTITY_ID)
        _assert_bool_value(states, "online", True)

    def test_online_false_when_unavailable(self):
        """Online must be false when state is 'unavailable'."""
        entity = self._make_entity("unavailable")
        states = _get_states(entity, self.ENTITY_ID)
        _assert_bool_value(states, "online", False)

    def test_tamper_alarm_bool_in_state(self):
        """tamper_alarm must be BOOL in state."""
        entity = self._make_entity("off", tamper=True)
        states = _get_states(entity, self.ENTITY_ID)
        _assert_bool_value(states, "tamper_alarm", True)

    def test_tamper_alarm_false(self):
        """tamper_alarm=false when tamper attribute is falsy."""
        entity = self._make_entity("off", tamper=False)
        states = _get_states(entity, self.ENTITY_ID)
        _assert_bool_value(states, "tamper_alarm", False)

    def test_read_only_no_commands(self):
        """Motion sensor must not process commands."""
        entity = self._make_entity()
        result = entity.process_cmd({"states": [{"key": "pir", "value": {}}]})
        assert result == []

    def test_no_pir_enum_value_is_never_used(self):
        """There must never be a 'no_pir' or empty enum value in state output."""
        entity = self._make_entity("off")
        states = _get_states(entity, self.ENTITY_ID)
        for s in states:
            if s.get("key") == "pir":
                pytest.fail("pir key found in state when motion not detected")
            if s.get("value", {}).get("enum_value") == "no_pir":
                pytest.fail("'no_pir' enum value must never appear in Sber protocol")


# ---------------------------------------------------------------------------
# DoorSensorEntity -- category: sensor_door
# ---------------------------------------------------------------------------

class TestDoorSensorCompliance:
    """Sber C2C compliance tests for DoorSensorEntity."""

    ENTITY_ID = "binary_sensor.front_door"
    ENTITY_DATA = {"entity_id": ENTITY_ID, "name": "Front Door"}

    def _make_entity(self, state="off", **attrs) -> DoorSensorEntity:
        entity = DoorSensorEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state({
            "entity_id": self.ENTITY_ID,
            "state": state,
            "attributes": attrs,
        })
        return entity

    def test_category_is_sensor_door(self):
        """Category must be 'sensor_door'."""
        entity = DoorSensorEntity(self.ENTITY_DATA)
        assert entity.category == "sensor_door"

    def test_features_minimal(self):
        """Minimal features: online, doorcontact_state."""
        entity = self._make_entity()
        features = entity.create_features_list()
        assert "online" in features
        assert "doorcontact_state" in features

    def test_features_with_tamper(self):
        """tamper_alarm feature when tamper attribute present."""
        entity = self._make_entity(tamper=False)
        features = entity.create_features_list()
        assert "tamper_alarm" in features

    def test_doorcontact_state_true_when_open(self):
        """doorcontact_state must be BOOL true when door is open (HA state='on')."""
        entity = self._make_entity("on")
        states = _get_states(entity, self.ENTITY_ID)
        _assert_bool_value(states, "doorcontact_state", True)

    def test_doorcontact_state_false_when_closed(self):
        """doorcontact_state must be BOOL false when door is closed (HA state='off')."""
        entity = self._make_entity("off")
        states = _get_states(entity, self.ENTITY_ID)
        _assert_bool_value(states, "doorcontact_state", False)

    def test_online_true_when_unknown(self):
        """Door sensor treats 'unknown' as online (event-based binary_sensor)."""
        entity = self._make_entity("unknown")
        states = _get_states(entity, self.ENTITY_ID)
        _assert_bool_value(states, "online", True)

    def test_tamper_alarm_bool(self):
        """tamper_alarm must be BOOL type."""
        entity = self._make_entity("off", tamper=True)
        states = _get_states(entity, self.ENTITY_ID)
        _assert_bool_value(states, "tamper_alarm", True)

    def test_read_only_no_commands(self):
        """Door sensor must not process commands."""
        entity = self._make_entity()
        result = entity.process_cmd({"states": []})
        assert result == []


# ---------------------------------------------------------------------------
# WaterLeakSensorEntity -- category: sensor_water_leak
# ---------------------------------------------------------------------------

class TestWaterLeakSensorCompliance:
    """Sber C2C compliance tests for WaterLeakSensorEntity."""

    ENTITY_ID = "binary_sensor.kitchen_leak"
    ENTITY_DATA = {"entity_id": ENTITY_ID, "name": "Kitchen Leak"}

    def _make_entity(self, state="off", **attrs) -> WaterLeakSensorEntity:
        entity = WaterLeakSensorEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state({
            "entity_id": self.ENTITY_ID,
            "state": state,
            "attributes": attrs,
        })
        return entity

    def test_category_is_sensor_water_leak(self):
        """Category must be 'sensor_water_leak'."""
        entity = WaterLeakSensorEntity(self.ENTITY_DATA)
        assert entity.category == "sensor_water_leak"

    def test_features_minimal(self):
        """Minimal features: online, water_leak_state."""
        entity = self._make_entity()
        features = entity.create_features_list()
        assert "online" in features
        assert "water_leak_state" in features

    def test_features_with_tamper_and_alarm_mute(self):
        """tamper_alarm and alarm_mute features when attrs present."""
        entity = self._make_entity(tamper=False, alarm_mute=False)
        features = entity.create_features_list()
        assert "tamper_alarm" in features
        assert "alarm_mute" in features

    def test_water_leak_state_true_when_detected(self):
        """water_leak_state must be BOOL true when leak detected (HA state='on')."""
        entity = self._make_entity("on")
        states = _get_states(entity, self.ENTITY_ID)
        _assert_bool_value(states, "water_leak_state", True)

    def test_water_leak_state_false_when_dry(self):
        """water_leak_state must be BOOL false when no leak (HA state='off')."""
        entity = self._make_entity("off")
        states = _get_states(entity, self.ENTITY_ID)
        _assert_bool_value(states, "water_leak_state", False)

    def test_tamper_alarm_in_state(self):
        """tamper_alarm must appear as BOOL when attr set."""
        entity = self._make_entity("off", tamper=True)
        states = _get_states(entity, self.ENTITY_ID)
        _assert_bool_value(states, "tamper_alarm", True)

    def test_alarm_mute_in_state(self):
        """alarm_mute must appear as BOOL when attr set."""
        entity = self._make_entity("off", alarm_mute=True)
        states = _get_states(entity, self.ENTITY_ID)
        _assert_bool_value(states, "alarm_mute", True)

    def test_read_only_no_commands(self):
        """Water leak sensor must not process commands."""
        entity = self._make_entity()
        result = entity.process_cmd({"states": []})
        assert result == []


# ---------------------------------------------------------------------------
# SmokeSensorEntity -- category: sensor_smoke
# ---------------------------------------------------------------------------

class TestSmokeSensorCompliance:
    """Sber C2C compliance tests for SmokeSensorEntity."""

    ENTITY_ID = "binary_sensor.kitchen_smoke"
    ENTITY_DATA = {"entity_id": ENTITY_ID, "name": "Kitchen Smoke"}

    def _make_entity(self, state="off", **attrs) -> SmokeSensorEntity:
        entity = SmokeSensorEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state({
            "entity_id": self.ENTITY_ID,
            "state": state,
            "attributes": attrs,
        })
        return entity

    def test_category_is_sensor_smoke(self):
        """Category must be 'sensor_smoke'."""
        entity = SmokeSensorEntity(self.ENTITY_DATA)
        assert entity.category == "sensor_smoke"

    def test_features_minimal(self):
        """Minimal features: online, smoke_state."""
        entity = self._make_entity()
        features = entity.create_features_list()
        assert "online" in features
        assert "smoke_state" in features

    def test_features_with_tamper_and_alarm_mute(self):
        """tamper_alarm and alarm_mute features when attrs present."""
        entity = self._make_entity(tamper=False, alarm_mute=True)
        features = entity.create_features_list()
        assert "tamper_alarm" in features
        assert "alarm_mute" in features

    def test_smoke_state_true_when_detected(self):
        """smoke_state must be BOOL true when smoke detected."""
        entity = self._make_entity("on")
        states = _get_states(entity, self.ENTITY_ID)
        _assert_bool_value(states, "smoke_state", True)

    def test_smoke_state_false_when_clear(self):
        """smoke_state must be BOOL false when no smoke."""
        entity = self._make_entity("off")
        states = _get_states(entity, self.ENTITY_ID)
        _assert_bool_value(states, "smoke_state", False)

    def test_tamper_alarm_bool(self):
        """tamper_alarm as BOOL in state."""
        entity = self._make_entity("off", tamper=True)
        states = _get_states(entity, self.ENTITY_ID)
        _assert_bool_value(states, "tamper_alarm", True)

    def test_alarm_mute_bool(self):
        """alarm_mute as BOOL in state."""
        entity = self._make_entity("off", alarm_mute=True)
        states = _get_states(entity, self.ENTITY_ID)
        _assert_bool_value(states, "alarm_mute", True)

    def test_read_only_no_commands(self):
        """Smoke sensor must not process commands."""
        entity = self._make_entity()
        result = entity.process_cmd({"states": []})
        assert result == []


# ---------------------------------------------------------------------------
# GasSensorEntity -- category: sensor_gas
# ---------------------------------------------------------------------------

class TestGasSensorCompliance:
    """Sber C2C compliance tests for GasSensorEntity."""

    ENTITY_ID = "binary_sensor.kitchen_gas"
    ENTITY_DATA = {"entity_id": ENTITY_ID, "name": "Kitchen Gas"}

    def _make_entity(self, state="off", **attrs) -> GasSensorEntity:
        entity = GasSensorEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state({
            "entity_id": self.ENTITY_ID,
            "state": state,
            "attributes": attrs,
        })
        return entity

    def test_category_is_sensor_gas(self):
        """Category must be 'sensor_gas'."""
        entity = GasSensorEntity(self.ENTITY_DATA)
        assert entity.category == "sensor_gas"

    def test_features_minimal(self):
        """Minimal features: online, gas_leak_state."""
        entity = self._make_entity()
        features = entity.create_features_list()
        assert "online" in features
        assert "gas_leak_state" in features

    def test_features_with_tamper_and_alarm_mute(self):
        """tamper_alarm and alarm_mute features when attrs present."""
        entity = self._make_entity(tamper=False, alarm_mute=False)
        features = entity.create_features_list()
        assert "tamper_alarm" in features
        assert "alarm_mute" in features

    def test_gas_leak_state_true_when_detected(self):
        """gas_leak_state must be BOOL true when gas leak detected."""
        entity = self._make_entity("on")
        states = _get_states(entity, self.ENTITY_ID)
        _assert_bool_value(states, "gas_leak_state", True)

    def test_gas_leak_state_false_when_clear(self):
        """gas_leak_state must be BOOL false when no gas leak."""
        entity = self._make_entity("off")
        states = _get_states(entity, self.ENTITY_ID)
        _assert_bool_value(states, "gas_leak_state", False)

    def test_tamper_alarm_bool(self):
        """tamper_alarm as BOOL in state."""
        entity = self._make_entity("off", tamper=True)
        states = _get_states(entity, self.ENTITY_ID)
        _assert_bool_value(states, "tamper_alarm", True)

    def test_alarm_mute_bool(self):
        """alarm_mute as BOOL in state."""
        entity = self._make_entity("off", alarm_mute=True)
        states = _get_states(entity, self.ENTITY_ID)
        _assert_bool_value(states, "alarm_mute", True)

    def test_read_only_no_commands(self):
        """Gas sensor must not process commands."""
        entity = self._make_entity()
        result = entity.process_cmd({"states": []})
        assert result == []


# ---------------------------------------------------------------------------
# CurtainEntity -- category: curtain
# ---------------------------------------------------------------------------

class TestCurtainCompliance:
    """Sber C2C compliance tests for CurtainEntity."""

    ENTITY_ID = "cover.living_curtain"
    ENTITY_DATA = {"entity_id": ENTITY_ID, "name": "Living Curtain"}

    def _make_entity(self, state="open", position=100, **attrs) -> CurtainEntity:
        entity = CurtainEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state({
            "entity_id": self.ENTITY_ID,
            "state": state,
            "attributes": {"current_position": position, **attrs},
        })
        return entity

    def test_category_is_curtain(self):
        """Category must be 'curtain'."""
        entity = CurtainEntity(self.ENTITY_DATA)
        assert entity.category == "curtain"

    def test_features_minimal(self):
        """Minimal features: online, open_percentage, open_set, open_state."""
        entity = self._make_entity()
        features = entity.create_features_list()
        assert "online" in features
        assert "open_percentage" in features
        assert "open_set" in features
        assert "open_state" in features

    def test_features_with_battery(self):
        """Battery features when battery attr present."""
        entity = self._make_entity(battery=75)
        features = entity.create_features_list()
        assert "battery_percentage" in features
        assert "battery_low_power" in features

    def test_features_with_signal_strength(self):
        """signal_strength feature when rssi attr present."""
        entity = self._make_entity(signal_strength=-60)
        features = entity.create_features_list()
        assert "signal_strength" in features

    def test_features_with_open_rate(self):
        """open_rate feature when speed attr present."""
        entity = self._make_entity(speed="low")
        features = entity.create_features_list()
        assert "open_rate" in features

    def test_features_with_tilt(self):
        """light_transmission_percentage feature when tilt position attr present."""
        entity = self._make_entity(current_tilt_position=50)
        features = entity.create_features_list()
        assert "light_transmission_percentage" in features

    def test_open_percentage_integer_value_is_string(self):
        """CRITICAL: open_percentage integer_value must be a string."""
        entity = self._make_entity(position=75)
        states = _get_states(entity, self.ENTITY_ID)
        _assert_integer_value_is_string(states, "open_percentage")

    def test_open_percentage_value(self):
        """open_percentage 75 -> '75'."""
        entity = self._make_entity(position=75)
        states = _get_states(entity, self.ENTITY_ID)
        entry = _find_state(states, "open_percentage")
        assert entry["value"]["integer_value"] == "75"

    def test_open_state_open_when_position_above_zero(self):
        """CRITICAL: open_state must be 'open' when position > 0."""
        entity = self._make_entity(state="open", position=50)
        states = _get_states(entity, self.ENTITY_ID)
        _assert_enum_value(states, "open_state", "open")

    def test_open_state_close_when_position_zero(self):
        """CRITICAL: open_state must be 'close' when position == 0."""
        entity = self._make_entity(state="closed", position=0)
        states = _get_states(entity, self.ENTITY_ID)
        _assert_enum_value(states, "open_state", "close")

    def test_open_state_consistency_pos_above_zero_forces_open(self):
        """CRITICAL: even if HA state is 'closed' but position > 0, open_state must be 'open'."""
        entity = self._make_entity(state="closed", position=50)
        states = _get_states(entity, self.ENTITY_ID)
        _assert_enum_value(states, "open_state", "open")

    def test_open_state_consistency_pos_zero_forces_close(self):
        """CRITICAL: even if HA state is 'open' but position == 0, open_state must be 'close'."""
        entity = self._make_entity(state="open", position=0)
        states = _get_states(entity, self.ENTITY_ID)
        _assert_enum_value(states, "open_state", "close")

    def test_open_state_opening(self):
        """Transitional state 'opening' must be preserved."""
        entity = self._make_entity(state="opening", position=30)
        states = _get_states(entity, self.ENTITY_ID)
        _assert_enum_value(states, "open_state", "opening")

    def test_open_state_closing(self):
        """Transitional state 'closing' must be preserved."""
        entity = self._make_entity(state="closing", position=70)
        states = _get_states(entity, self.ENTITY_ID)
        _assert_enum_value(states, "open_state", "closing")

    def test_allowed_values_open_set_enum(self):
        """open_set allowed_values must have ENUM with open/close/stop."""
        entity = self._make_entity()
        allowed = entity.create_allowed_values_list()
        assert "open_set" in allowed
        assert allowed["open_set"]["type"] == "ENUM"
        assert set(allowed["open_set"]["enum_values"]["values"]) == {"open", "close", "stop"}

    def test_allowed_values_open_percentage_integer(self):
        """open_percentage allowed_values must be INTEGER 0/100/1."""
        entity = self._make_entity()
        allowed = entity.create_allowed_values_list()
        assert "open_percentage" in allowed
        assert allowed["open_percentage"]["type"] == "INTEGER"
        iv = allowed["open_percentage"]["integer_values"]
        assert iv["min"] == "0"
        assert iv["max"] == "100"
        assert iv["step"] == "1"

    def test_cmd_open_percentage_set_cover_position(self):
        """open_percentage command must produce set_cover_position service call."""
        entity = self._make_entity()
        result = entity.process_cmd({
            "states": [{
                "key": "open_percentage",
                "value": {"type": "INTEGER", "integer_value": "50"},
            }],
        })
        assert len(result) == 1
        call = result[0]["url"]
        assert call["service"] == "set_cover_position"
        assert call["service_data"]["position"] == 50
        assert call["target"]["entity_id"] == self.ENTITY_ID

    def test_cmd_open_set_open(self):
        """open_set=open must produce open_cover service call."""
        entity = self._make_entity()
        result = entity.process_cmd({
            "states": [{"key": "open_set", "value": {"enum_value": "open"}}],
        })
        assert len(result) == 1
        assert result[0]["url"]["service"] == "open_cover"

    def test_cmd_open_set_close(self):
        """open_set=close must produce close_cover service call."""
        entity = self._make_entity()
        result = entity.process_cmd({
            "states": [{"key": "open_set", "value": {"enum_value": "close"}}],
        })
        assert len(result) == 1
        assert result[0]["url"]["service"] == "close_cover"

    def test_cmd_open_set_stop(self):
        """open_set=stop must produce stop_cover service call."""
        entity = self._make_entity()
        result = entity.process_cmd({
            "states": [{"key": "open_set", "value": {"enum_value": "stop"}}],
        })
        assert len(result) == 1
        assert result[0]["url"]["service"] == "stop_cover"

    def test_cmd_unknown_key_no_crash(self):
        """Unknown command key must not crash, returns empty list."""
        entity = self._make_entity()
        result = entity.process_cmd({
            "states": [{"key": "nonexistent_key", "value": {"enum_value": "test"}}],
        })
        assert result == []

    def test_cmd_open_percentage_clamped_to_100(self):
        """Position above 100 must be clamped to 100."""
        entity = self._make_entity()
        result = entity.process_cmd({
            "states": [{
                "key": "open_percentage",
                "value": {"type": "INTEGER", "integer_value": "150"},
            }],
        })
        assert result[0]["url"]["service_data"]["position"] == 100

    def test_cmd_open_percentage_clamped_to_0(self):
        """Negative position must be clamped to 0."""
        entity = self._make_entity()
        result = entity.process_cmd({
            "states": [{
                "key": "open_percentage",
                "value": {"type": "INTEGER", "integer_value": "-10"},
            }],
        })
        assert result[0]["url"]["service_data"]["position"] == 0

    def test_cmd_empty_states_no_crash(self):
        """Empty states list must not crash."""
        entity = self._make_entity()
        result = entity.process_cmd({"states": []})
        assert result == []

    def test_online_false_when_unavailable(self):
        """Online must be false when state is 'unavailable'."""
        entity = self._make_entity(state="unavailable", position=0)
        states = _get_states(entity, self.ENTITY_ID)
        _assert_bool_value(states, "online", False)

    def test_config_json_required_fields(self):
        """Config JSON must have all required Sber fields."""
        entity = self._make_entity()
        config = entity.to_sber_state()
        _assert_config_has_required_fields(config)
        assert config["model"]["category"] == "curtain"

    def test_tilt_position_integer_value_is_string(self):
        """light_transmission_percentage integer_value must be string."""
        entity = self._make_entity(current_tilt_position=45)
        states = _get_states(entity, self.ENTITY_ID)
        _assert_integer_value_is_string(states, "light_transmission_percentage")


# ---------------------------------------------------------------------------
# TvEntity -- category: tv
# ---------------------------------------------------------------------------

class TestTvCompliance:
    """Sber C2C compliance tests for TvEntity."""

    ENTITY_ID = "media_player.living_tv"
    ENTITY_DATA = {"entity_id": ENTITY_ID, "name": "Living TV"}

    def _make_entity(self, state="playing", **attrs) -> TvEntity:
        entity = TvEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state({
            "entity_id": self.ENTITY_ID,
            "state": state,
            "attributes": attrs,
        })
        return entity

    def test_category_is_tv(self):
        """Category must be 'tv'."""
        entity = TvEntity(self.ENTITY_DATA)
        assert entity.category == "tv"

    def test_features_minimal(self):
        """Minimal features: online, on_off, volume_int, mute, channel, channel_int, direction."""
        entity = self._make_entity()
        features = entity.create_features_list()
        for feat in ("online", "on_off", "volume_int", "mute", "channel", "channel_int", "direction"):
            assert feat in features, f"Missing feature '{feat}'"

    def test_features_source_when_source_list(self):
        """source feature only when source_list is available."""
        entity = self._make_entity(source_list=["HDMI 1", "TV"])
        features = entity.create_features_list()
        assert "source" in features

    def test_features_no_source_without_list(self):
        """source feature must not appear without source_list."""
        entity = self._make_entity()
        features = entity.create_features_list()
        assert "source" not in features

    def test_volume_int_integer_value_is_string(self):
        """CRITICAL: volume_int integer_value must be a string."""
        entity = self._make_entity(volume_level=0.5)
        states = _get_states(entity, self.ENTITY_ID)
        _assert_integer_value_is_string(states, "volume_int")

    def test_volume_conversion_ha_to_sber(self):
        """HA volume 0.5 (50%) must produce Sber volume_int '50'."""
        entity = self._make_entity(volume_level=0.5)
        states = _get_states(entity, self.ENTITY_ID)
        entry = _find_state(states, "volume_int")
        assert entry["value"]["integer_value"] == "50"

    def test_volume_zero(self):
        """HA volume 0.0 must produce Sber volume_int '0'."""
        entity = self._make_entity(volume_level=0.0)
        states = _get_states(entity, self.ENTITY_ID)
        entry = _find_state(states, "volume_int")
        assert entry["value"]["integer_value"] == "0"

    def test_volume_max(self):
        """HA volume 1.0 must produce Sber volume_int '100'."""
        entity = self._make_entity(volume_level=1.0)
        states = _get_states(entity, self.ENTITY_ID)
        entry = _find_state(states, "volume_int")
        assert entry["value"]["integer_value"] == "100"

    def test_mute_bool(self):
        """mute must be BOOL type."""
        entity = self._make_entity(is_volume_muted=True)
        states = _get_states(entity, self.ENTITY_ID)
        _assert_bool_value(states, "mute", True)

    def test_mute_false(self):
        """mute false when not muted."""
        entity = self._make_entity(is_volume_muted=False)
        states = _get_states(entity, self.ENTITY_ID)
        _assert_bool_value(states, "mute", False)

    def test_on_off_true_when_playing(self):
        """on_off must be true when TV is playing."""
        entity = self._make_entity("playing")
        states = _get_states(entity, self.ENTITY_ID)
        _assert_bool_value(states, "on_off", True)

    def test_on_off_false_when_off(self):
        """on_off must be false when TV is off."""
        entity = self._make_entity("off")
        states = _get_states(entity, self.ENTITY_ID)
        _assert_bool_value(states, "on_off", False)

    def test_on_off_false_when_standby(self):
        """on_off must be false when TV is in standby."""
        entity = self._make_entity("standby")
        states = _get_states(entity, self.ENTITY_ID)
        _assert_bool_value(states, "on_off", False)

    def test_source_enum_in_state(self):
        """source must be ENUM in state when set."""
        entity = self._make_entity(source="HDMI 1", source_list=["HDMI 1", "TV"])
        states = _get_states(entity, self.ENTITY_ID)
        _assert_enum_value(states, "source", "HDMI 1")

    def test_source_absent_when_none(self):
        """source must not appear in state when not set."""
        entity = self._make_entity(source_list=["HDMI 1"])
        states = _get_states(entity, self.ENTITY_ID)
        assert _find_state(states, "source") is None

    def test_allowed_values_volume_int(self):
        """volume_int allowed_values must be INTEGER 0/100/1."""
        entity = self._make_entity()
        allowed = entity.create_allowed_values_list()
        assert "volume_int" in allowed
        assert allowed["volume_int"]["type"] == "INTEGER"
        iv = allowed["volume_int"]["integer_values"]
        assert iv["min"] == "0"
        assert iv["max"] == "100"
        assert iv["step"] == "1"

    def test_allowed_values_channel_enum(self):
        """channel allowed_values must have ENUM with +/-."""
        entity = self._make_entity()
        allowed = entity.create_allowed_values_list()
        assert "channel" in allowed
        assert set(allowed["channel"]["enum_values"]["values"]) == {"+", "-"}

    def test_allowed_values_direction_enum(self):
        """direction allowed_values must have ENUM with up/down/left/right/ok."""
        entity = self._make_entity()
        allowed = entity.create_allowed_values_list()
        assert "direction" in allowed
        assert set(allowed["direction"]["enum_values"]["values"]) == {
            "up", "down", "left", "right", "ok",
        }

    def test_allowed_values_source_enum(self):
        """source allowed_values must list source_list entries."""
        entity = self._make_entity(source_list=["HDMI 1", "TV", "AV"])
        allowed = entity.create_allowed_values_list()
        assert "source" in allowed
        assert allowed["source"]["enum_values"]["values"] == ["HDMI 1", "TV", "AV"]

    def test_cmd_on_off_turn_on(self):
        """on_off=true must produce media_player.turn_on."""
        entity = self._make_entity()
        result = entity.process_cmd({
            "states": [{
                "key": "on_off",
                "value": {"type": "BOOL", "bool_value": True},
            }],
        })
        assert len(result) == 1
        assert result[0]["url"]["domain"] == "media_player"
        assert result[0]["url"]["service"] == "turn_on"

    def test_cmd_on_off_turn_off(self):
        """on_off=false must produce media_player.turn_off."""
        entity = self._make_entity()
        result = entity.process_cmd({
            "states": [{
                "key": "on_off",
                "value": {"type": "BOOL", "bool_value": False},
            }],
        })
        assert len(result) == 1
        assert result[0]["url"]["service"] == "turn_off"

    def test_cmd_volume_int_conversion(self):
        """CRITICAL: Sber volume_int 50 must convert to HA volume_level 0.5."""
        entity = self._make_entity()
        result = entity.process_cmd({
            "states": [{
                "key": "volume_int",
                "value": {"type": "INTEGER", "integer_value": "50"},
            }],
        })
        assert len(result) == 1
        call = result[0]["url"]
        assert call["service"] == "volume_set"
        assert call["service_data"]["volume_level"] == pytest.approx(0.5)

    def test_cmd_volume_int_zero(self):
        """Sber volume_int 0 -> HA volume_level 0.0."""
        entity = self._make_entity()
        result = entity.process_cmd({
            "states": [{
                "key": "volume_int",
                "value": {"type": "INTEGER", "integer_value": "0"},
            }],
        })
        assert result[0]["url"]["service_data"]["volume_level"] == pytest.approx(0.0)

    def test_cmd_volume_int_100(self):
        """Sber volume_int 100 -> HA volume_level 1.0."""
        entity = self._make_entity()
        result = entity.process_cmd({
            "states": [{
                "key": "volume_int",
                "value": {"type": "INTEGER", "integer_value": "100"},
            }],
        })
        assert result[0]["url"]["service_data"]["volume_level"] == pytest.approx(1.0)

    def test_cmd_mute_on(self):
        """mute=true must produce volume_mute with is_volume_muted=true."""
        entity = self._make_entity()
        result = entity.process_cmd({
            "states": [{
                "key": "mute",
                "value": {"type": "BOOL", "bool_value": True},
            }],
        })
        assert len(result) == 1
        call = result[0]["url"]
        assert call["service"] == "volume_mute"
        assert call["service_data"]["is_volume_muted"] is True

    def test_cmd_source_select(self):
        """source ENUM must produce select_source."""
        entity = self._make_entity(source_list=["HDMI 1", "TV"])
        result = entity.process_cmd({
            "states": [{
                "key": "source",
                "value": {"type": "ENUM", "enum_value": "HDMI 1"},
            }],
        })
        assert len(result) == 1
        call = result[0]["url"]
        assert call["service"] == "select_source"
        assert call["service_data"]["source"] == "HDMI 1"

    def test_cmd_channel_plus_next_track(self):
        """channel '+' must produce media_next_track."""
        entity = self._make_entity()
        result = entity.process_cmd({
            "states": [{
                "key": "channel",
                "value": {"type": "ENUM", "enum_value": "+"},
            }],
        })
        assert len(result) == 1
        assert result[0]["url"]["service"] == "media_next_track"

    def test_cmd_channel_minus_previous_track(self):
        """channel '-' must produce media_previous_track."""
        entity = self._make_entity()
        result = entity.process_cmd({
            "states": [{
                "key": "channel",
                "value": {"type": "ENUM", "enum_value": "-"},
            }],
        })
        assert len(result) == 1
        assert result[0]["url"]["service"] == "media_previous_track"

    def test_cmd_channel_int_play_media(self):
        """channel_int must produce play_media with media_content_type=channel."""
        entity = self._make_entity()
        result = entity.process_cmd({
            "states": [{
                "key": "channel_int",
                "value": {"type": "INTEGER", "integer_value": "42"},
            }],
        })
        assert len(result) == 1
        call = result[0]["url"]
        assert call["service"] == "play_media"
        assert call["service_data"]["media_content_type"] == "channel"
        assert call["service_data"]["media_content_id"] == "42"

    def test_cmd_direction_up_volume_up(self):
        """direction 'up' must produce volume_up."""
        entity = self._make_entity()
        result = entity.process_cmd({
            "states": [{
                "key": "direction",
                "value": {"type": "ENUM", "enum_value": "up"},
            }],
        })
        assert len(result) == 1
        assert result[0]["url"]["service"] == "volume_up"

    def test_cmd_direction_down_volume_down(self):
        """direction 'down' must produce volume_down."""
        entity = self._make_entity()
        result = entity.process_cmd({
            "states": [{
                "key": "direction",
                "value": {"type": "ENUM", "enum_value": "down"},
            }],
        })
        assert len(result) == 1
        assert result[0]["url"]["service"] == "volume_down"

    def test_cmd_direction_unknown_no_crash(self):
        """Unknown direction (left/right/ok) must not crash, may produce no service calls."""
        entity = self._make_entity()
        for direction in ("left", "right", "ok"):
            result = entity.process_cmd({
                "states": [{
                    "key": "direction",
                    "value": {"type": "ENUM", "enum_value": direction},
                }],
            })
            # left/right/ok are not mapped to services in current implementation
            assert isinstance(result, list)

    def test_cmd_unknown_key_no_crash(self):
        """Unknown command key must not crash."""
        entity = self._make_entity()
        result = entity.process_cmd({
            "states": [{"key": "unknown_key", "value": {"type": "BOOL", "bool_value": True}}],
        })
        assert result == []

    def test_cmd_empty_states_no_crash(self):
        """Empty states list must not crash."""
        entity = self._make_entity()
        result = entity.process_cmd({"states": []})
        assert result == []

    def test_config_json_required_fields(self):
        """Config JSON must have all required Sber fields."""
        entity = self._make_entity()
        config = entity.to_sber_state()
        _assert_config_has_required_fields(config)
        assert config["model"]["category"] == "tv"


# ---------------------------------------------------------------------------
# HvacFanEntity -- category: hvac_fan
# ---------------------------------------------------------------------------

class TestHvacFanCompliance:
    """Sber C2C compliance tests for HvacFanEntity."""

    ENTITY_ID = "fan.living_fan"
    ENTITY_DATA = {"entity_id": ENTITY_ID, "name": "Living Fan"}

    def _make_entity(self, state="on", **attrs) -> HvacFanEntity:
        entity = HvacFanEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state({
            "entity_id": self.ENTITY_ID,
            "state": state,
            "attributes": attrs,
        })
        return entity

    def test_category_is_hvac_fan(self):
        """Category must be 'hvac_fan'."""
        entity = HvacFanEntity(self.ENTITY_DATA)
        assert entity.category == "hvac_fan"

    def test_features_simple_on_off_fan(self):
        """Simple fan (no speed support) must have online + on_off only."""
        entity = self._make_entity()
        features = entity.create_features_list()
        assert "online" in features
        assert "on_off" in features
        assert "hvac_air_flow_power" not in features, (
            "hvac_air_flow_power must NOT appear for a simple on/off fan"
        )

    def test_features_with_preset_modes(self):
        """Fan with preset_modes must include hvac_air_flow_power."""
        entity = self._make_entity(preset_modes=["low", "medium", "high"])
        features = entity.create_features_list()
        assert "hvac_air_flow_power" in features

    def test_features_with_percentage(self):
        """Fan with percentage must include hvac_air_flow_power."""
        entity = self._make_entity(percentage=50)
        features = entity.create_features_list()
        assert "hvac_air_flow_power" in features

    def test_no_speed_no_allowed_values(self):
        """Simple on/off fan must return empty allowed_values."""
        entity = self._make_entity()
        allowed = entity.create_allowed_values_list()
        assert allowed == {}

    def test_speed_allowed_values_enum(self):
        """Fan with speed must have hvac_air_flow_power ENUM allowed values."""
        entity = self._make_entity(preset_modes=["low", "high"])
        allowed = entity.create_allowed_values_list()
        assert "hvac_air_flow_power" in allowed
        assert allowed["hvac_air_flow_power"]["type"] == "ENUM"
        values = allowed["hvac_air_flow_power"]["enum_values"]["values"]
        assert set(values) == {"auto", "high", "low", "medium", "quiet", "turbo"}

    def test_state_on_off_bool(self):
        """on_off must be BOOL in state."""
        entity = self._make_entity("on")
        states = _get_states(entity, self.ENTITY_ID)
        _assert_bool_value(states, "on_off", True)

    def test_state_off(self):
        """on_off must be false when fan is off."""
        entity = self._make_entity("off")
        states = _get_states(entity, self.ENTITY_ID)
        _assert_bool_value(states, "on_off", False)

    def test_state_no_speed_no_hvac_air_flow_power(self):
        """Simple on/off fan must NOT have hvac_air_flow_power in state."""
        entity = self._make_entity()
        states = _get_states(entity, self.ENTITY_ID)
        assert _find_state(states, "hvac_air_flow_power") is None

    def test_state_speed_from_preset_mode(self):
        """Fan with preset_mode=low must report hvac_air_flow_power='low'."""
        entity = self._make_entity(preset_modes=["low", "high"], preset_mode="low")
        states = _get_states(entity, self.ENTITY_ID)
        _assert_enum_value(states, "hvac_air_flow_power", "low")

    def test_state_speed_from_percentage(self):
        """Fan with percentage=50 must report a valid Sber speed ENUM."""
        entity = self._make_entity(percentage=50)
        states = _get_states(entity, self.ENTITY_ID)
        entry = _find_state(states, "hvac_air_flow_power")
        assert entry is not None
        assert entry["value"]["type"] == "ENUM"
        assert entry["value"]["enum_value"] in ("auto", "high", "low", "medium", "quiet", "turbo")

    @pytest.mark.parametrize("percentage,expected_speed", [
        (0, "quiet"),
        (10, "quiet"),
        (25, "low"),
        (50, "medium"),
        (75, "high"),
        (100, "turbo"),
    ])
    def test_percentage_to_speed_mapping(self, percentage, expected_speed):
        """Percentage must map to correct Sber speed ENUM."""
        entity = self._make_entity(percentage=percentage)
        states = _get_states(entity, self.ENTITY_ID)
        _assert_enum_value(states, "hvac_air_flow_power", expected_speed)

    def test_state_speed_defaults_to_auto_when_unknown(self):
        """When speed cannot be determined, must default to 'auto'."""
        entity = self._make_entity(preset_modes=["low"], preset_mode=None, percentage=None)
        # preset_modes is not empty so _supports_speed is True, but neither
        # preset_mode nor percentage are set => _get_sber_speed returns None => fallback "auto"
        states = _get_states(entity, self.ENTITY_ID)
        _assert_enum_value(states, "hvac_air_flow_power", "auto")

    def test_cmd_on_off_turn_on(self):
        """on_off=true must produce fan.turn_on."""
        entity = self._make_entity()
        result = entity.process_cmd({
            "states": [{
                "key": "on_off",
                "value": {"type": "BOOL", "bool_value": True},
            }],
        })
        assert len(result) == 1
        assert result[0]["url"]["domain"] == "fan"
        assert result[0]["url"]["service"] == "turn_on"

    def test_cmd_on_off_turn_off(self):
        """on_off=false must produce fan.turn_off."""
        entity = self._make_entity()
        result = entity.process_cmd({
            "states": [{
                "key": "on_off",
                "value": {"type": "BOOL", "bool_value": False},
            }],
        })
        assert len(result) == 1
        assert result[0]["url"]["service"] == "turn_off"

    def test_cmd_speed_preset_mode(self):
        """Speed command matching preset_mode must produce set_preset_mode."""
        entity = self._make_entity(preset_modes=["low", "medium", "high"])
        result = entity.process_cmd({
            "states": [{
                "key": "hvac_air_flow_power",
                "value": {"type": "ENUM", "enum_value": "medium"},
            }],
        })
        assert len(result) == 1
        call = result[0]["url"]
        assert call["service"] == "set_preset_mode"
        assert call["service_data"]["preset_mode"] == "medium"

    def test_cmd_speed_percentage_fallback(self):
        """Speed command not matching preset_mode must produce set_percentage."""
        entity = self._make_entity(preset_modes=[])
        result = entity.process_cmd({
            "states": [{
                "key": "hvac_air_flow_power",
                "value": {"type": "ENUM", "enum_value": "high"},
            }],
        })
        assert len(result) == 1
        call = result[0]["url"]
        assert call["service"] == "set_percentage"
        assert call["service_data"]["percentage"] == 75

    def test_cmd_speed_auto_turn_on(self):
        """Speed 'auto' (percentage=0) must produce fan.turn_on."""
        entity = self._make_entity(preset_modes=[])
        result = entity.process_cmd({
            "states": [{
                "key": "hvac_air_flow_power",
                "value": {"type": "ENUM", "enum_value": "auto"},
            }],
        })
        assert len(result) == 1
        assert result[0]["url"]["service"] == "turn_on"

    def test_cmd_unknown_key_no_crash(self):
        """Unknown command key must not crash."""
        entity = self._make_entity()
        result = entity.process_cmd({
            "states": [{"key": "unknown", "value": {"type": "BOOL", "bool_value": True}}],
        })
        assert result == []

    def test_cmd_empty_states_no_crash(self):
        """Empty states list must not crash."""
        entity = self._make_entity()
        result = entity.process_cmd({"states": []})
        assert result == []

    def test_config_json_required_fields(self):
        """Config JSON must have all required Sber fields."""
        entity = self._make_entity()
        config = entity.to_sber_state()
        _assert_config_has_required_fields(config)
        assert config["model"]["category"] == "hvac_fan"

    def test_config_no_speed_no_allowed_values_in_model(self):
        """Simple fan config must not have allowed_values in model."""
        entity = self._make_entity()
        config = entity.to_sber_state()
        assert "allowed_values" not in config["model"]


# ---------------------------------------------------------------------------
# Cross-entity compliance: integer_value always string
# ---------------------------------------------------------------------------

class TestIntegerValueAlwaysString:
    """Verify that ALL integer_value fields across all entity types are strings.

    This is a critical Sber C2C protocol requirement -- the cloud rejects
    payloads where integer_value is a number instead of a string.
    """

    def _collect_integer_values(self, states: list[dict]) -> list[tuple[str, object]]:
        """Collect all integer_value entries from a states list."""
        result = []
        for s in states:
            value = s.get("value", {})
            if value.get("type") == "INTEGER":
                result.append((s["key"], value.get("integer_value")))
        return result

    def test_sensor_temp_all_integers_are_strings(self):
        """All integer_value in SensorTempEntity state must be strings."""
        entity = SensorTempEntity({"entity_id": "sensor.t", "name": "T"})
        entity.fill_by_ha_state({"entity_id": "sensor.t", "state": "22.5", "attributes": {"battery": 80, "pressure": 1013}})
        entity.update_linked_data("humidity", {"state": "55"})
        states = _get_states(entity, "sensor.t")
        for key, val in self._collect_integer_values(states):
            assert isinstance(val, str), f"integer_value for '{key}' is {type(val).__name__}, must be str"

    def test_curtain_all_integers_are_strings(self):
        """All integer_value in CurtainEntity state must be strings."""
        entity = CurtainEntity({"entity_id": "cover.c", "name": "C"})
        entity.fill_by_ha_state({
            "entity_id": "cover.c", "state": "open",
            "attributes": {"current_position": 50, "battery": 60, "current_tilt_position": 30},
        })
        states = _get_states(entity, "cover.c")
        for key, val in self._collect_integer_values(states):
            assert isinstance(val, str), f"integer_value for '{key}' is {type(val).__name__}, must be str"

    def test_tv_all_integers_are_strings(self):
        """All integer_value in TvEntity state must be strings."""
        entity = TvEntity({"entity_id": "media_player.tv", "name": "TV"})
        entity.fill_by_ha_state({
            "entity_id": "media_player.tv", "state": "playing",
            "attributes": {"volume_level": 0.75},
        })
        states = _get_states(entity, "media_player.tv")
        for key, val in self._collect_integer_values(states):
            assert isinstance(val, str), f"integer_value for '{key}' is {type(val).__name__}, must be str"

    def test_humidity_sensor_all_integers_are_strings(self):
        """All integer_value in HumiditySensorEntity state must be strings."""
        entity = HumiditySensorEntity({"entity_id": "sensor.h", "name": "H"})
        entity.fill_by_ha_state({"entity_id": "sensor.h", "state": "65", "attributes": {"battery": 90}})
        entity.update_linked_data("temperature", {"state": "21.5"})
        states = _get_states(entity, "sensor.h")
        for key, val in self._collect_integer_values(states):
            assert isinstance(val, str), f"integer_value for '{key}' is {type(val).__name__}, must be str"
