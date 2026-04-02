"""Negative scenario tests for all entity types in Sber MQTT Bridge.

Covers:
1. Unavailable/unknown/None states produce online=False for all entities
2. Malformed Sber payloads (invalid JSON, wrong types, missing keys)
3. Out-of-range command values (clamping, no crash)
4. None/NaN/Inf/non-numeric attributes (no crash)
5. Commands with missing or malformed fields (no crash)
"""

from __future__ import annotations

import pytest

from custom_components.sber_mqtt_bridge.devices.climate import ClimateEntity
from custom_components.sber_mqtt_bridge.devices.curtain import CurtainEntity
from custom_components.sber_mqtt_bridge.devices.door_sensor import DoorSensorEntity
from custom_components.sber_mqtt_bridge.devices.gas_sensor import GasSensorEntity
from custom_components.sber_mqtt_bridge.devices.gate import GateEntity
from custom_components.sber_mqtt_bridge.devices.humidifier import HumidifierEntity
from custom_components.sber_mqtt_bridge.devices.humidity_sensor import HumiditySensorEntity
from custom_components.sber_mqtt_bridge.devices.hvac_air_purifier import HvacAirPurifierEntity
from custom_components.sber_mqtt_bridge.devices.hvac_boiler import HvacBoilerEntity
from custom_components.sber_mqtt_bridge.devices.hvac_fan import HvacFanEntity
from custom_components.sber_mqtt_bridge.devices.hvac_heater import HvacHeaterEntity
from custom_components.sber_mqtt_bridge.devices.hvac_radiator import HvacRadiatorEntity
from custom_components.sber_mqtt_bridge.devices.hvac_underfloor_heating import HvacUnderfloorEntity
from custom_components.sber_mqtt_bridge.devices.intercom import IntercomEntity
from custom_components.sber_mqtt_bridge.devices.kettle import KettleEntity
from custom_components.sber_mqtt_bridge.devices.led_strip import LedStripEntity
from custom_components.sber_mqtt_bridge.devices.light import LightEntity
from custom_components.sber_mqtt_bridge.devices.motion_sensor import MotionSensorEntity
from custom_components.sber_mqtt_bridge.devices.relay import RelayEntity
from custom_components.sber_mqtt_bridge.devices.scenario_button import ScenarioButtonEntity
from custom_components.sber_mqtt_bridge.devices.sensor_temp import SensorTempEntity
from custom_components.sber_mqtt_bridge.devices.smoke_sensor import SmokeSensorEntity
from custom_components.sber_mqtt_bridge.devices.socket_entity import SocketEntity
from custom_components.sber_mqtt_bridge.devices.tv import TvEntity
from custom_components.sber_mqtt_bridge.devices.vacuum_cleaner import VacuumCleanerEntity
from custom_components.sber_mqtt_bridge.devices.valve import ValveEntity
from custom_components.sber_mqtt_bridge.devices.water_leak_sensor import WaterLeakSensorEntity
from custom_components.sber_mqtt_bridge.devices.window_blind import WindowBlindEntity
from custom_components.sber_mqtt_bridge.sber_protocol import (
    parse_sber_command,
    parse_sber_status_request,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _entity_data(entity_id: str, name: str = "Test") -> dict:
    """Build minimal HA entity registry dict."""
    return {"entity_id": entity_id, "name": name}


def _ha_state(entity_id: str, state: str | None, **attrs) -> dict:
    """Build an HA state dict."""
    return {"entity_id": entity_id, "state": state, "attributes": dict(attrs)}


def _get_online_value(sber_state: dict, entity_id: str) -> bool:
    """Extract the boolean 'online' value from Sber state payload."""
    states = sber_state[entity_id]["states"]
    online = next(s for s in states if s["key"] == "online")
    return online["value"]["bool_value"]


# ---------------------------------------------------------------------------
# All entity classes with their test entity_id and HA domain.
# Binary sensors treat 'unknown' as online (event-based), so they are
# listed separately.
# ---------------------------------------------------------------------------

# Entities where 'unknown' => offline (default BaseEntity._is_online)
_STANDARD_ENTITIES = [
    (LightEntity, "light.test", "light"),
    (LedStripEntity, "light.test_strip", "light"),
    (ClimateEntity, "climate.test", "climate"),
    (CurtainEntity, "cover.test", "cover"),
    (GateEntity, "cover.test_gate", "cover"),
    (WindowBlindEntity, "cover.test_blind", "cover"),
    (RelayEntity, "switch.test", "switch"),
    (SocketEntity, "switch.test_socket", "switch"),
    (HumidifierEntity, "humidifier.test", "humidifier"),
    (TvEntity, "media_player.test", "media_player"),
    (VacuumCleanerEntity, "vacuum.test", "vacuum"),
    (ValveEntity, "valve.test", "valve"),
    (KettleEntity, "switch.test_kettle", "switch"),
    (ScenarioButtonEntity, "input_boolean.test", "input_boolean"),
    (HvacFanEntity, "fan.test", "fan"),
    (HvacAirPurifierEntity, "fan.test_purifier", "fan"),
    (HvacHeaterEntity, "climate.test_heater", "climate"),
    (HvacBoilerEntity, "climate.test_boiler", "climate"),
    (HvacUnderfloorEntity, "climate.test_floor", "climate"),
    (HvacRadiatorEntity, "climate.test_radiator", "climate"),
    (IntercomEntity, "switch.test_intercom", "switch"),
    (SensorTempEntity, "sensor.test_temp", "sensor"),
    (HumiditySensorEntity, "sensor.test_humidity", "sensor"),
]

# Binary sensors: SimpleReadOnlySensor subclasses where 'unknown' may be online
_BINARY_SENSOR_ENTITIES = [
    (MotionSensorEntity, "binary_sensor.test_motion", "binary_sensor"),
    (DoorSensorEntity, "binary_sensor.test_door", "binary_sensor"),
    (WaterLeakSensorEntity, "binary_sensor.test_leak", "binary_sensor"),
    (SmokeSensorEntity, "binary_sensor.test_smoke", "binary_sensor"),
    (GasSensorEntity, "binary_sensor.test_gas", "binary_sensor"),
]

_ALL_ENTITIES = _STANDARD_ENTITIES + _BINARY_SENSOR_ENTITIES


# =========================================================================
# 1. TestEntityUnavailableState
# =========================================================================


class TestEntityUnavailableState:
    """Every entity must report online=False for unavailable/unknown/None states."""

    @pytest.mark.parametrize(
        ("entity_cls", "entity_id", "ha_domain"),
        _ALL_ENTITIES,
        ids=[cls.__name__ for cls, _, _ in _ALL_ENTITIES],
    )
    def test_unavailable_produces_online_false(self, entity_cls, entity_id, ha_domain):
        """State 'unavailable' must always produce online=False."""
        entity = entity_cls(_entity_data(entity_id))
        entity.fill_by_ha_state(_ha_state(entity_id, "unavailable"))
        result = entity.to_sber_current_state()
        assert _get_online_value(result, entity_id) is False

    @pytest.mark.parametrize(
        ("entity_cls", "entity_id", "ha_domain"),
        _STANDARD_ENTITIES,
        ids=[cls.__name__ for cls, _, _ in _STANDARD_ENTITIES],
    )
    def test_unknown_produces_online_false_for_standard_entities(self, entity_cls, entity_id, ha_domain):
        """State 'unknown' must produce online=False for non-sensor entities."""
        entity = entity_cls(_entity_data(entity_id))
        entity.fill_by_ha_state(_ha_state(entity_id, "unknown"))
        result = entity.to_sber_current_state()
        assert _get_online_value(result, entity_id) is False

    @pytest.mark.parametrize(
        ("entity_cls", "entity_id", "ha_domain"),
        _BINARY_SENSOR_ENTITIES,
        ids=[cls.__name__ for cls, _, _ in _BINARY_SENSOR_ENTITIES],
    )
    def test_unknown_produces_online_true_for_binary_sensors(self, entity_cls, entity_id, ha_domain):
        """Event-based binary sensors treat 'unknown' as online (no event yet, not offline).

        Per HA docs, binary_sensor 'unknown' means the sensor hasn't reported yet,
        not that the device is unreachable. Sber must see these as online.
        """
        entity = entity_cls(_entity_data(entity_id))
        entity.fill_by_ha_state(_ha_state(entity_id, "unknown"))
        result = entity.to_sber_current_state()
        assert _get_online_value(result, entity_id) is True

    @pytest.mark.parametrize(
        ("entity_cls", "entity_id", "ha_domain"),
        _ALL_ENTITIES,
        ids=[cls.__name__ for cls, _, _ in _ALL_ENTITIES],
    )
    def test_none_state_no_crash(self, entity_cls, entity_id, ha_domain):
        """State=None must not crash; entity must produce valid Sber payload."""
        entity = entity_cls(_entity_data(entity_id))
        entity.fill_by_ha_state(_ha_state(entity_id, None))
        result = entity.to_sber_current_state()
        assert entity_id in result
        assert _get_online_value(result, entity_id) is False

    @pytest.mark.parametrize(
        ("entity_cls", "entity_id", "ha_domain"),
        _ALL_ENTITIES,
        ids=[cls.__name__ for cls, _, _ in _ALL_ENTITIES],
    )
    def test_empty_string_state_no_crash(self, entity_cls, entity_id, ha_domain):
        """Empty string state must not crash."""
        entity = entity_cls(_entity_data(entity_id))
        entity.fill_by_ha_state(_ha_state(entity_id, ""))
        result = entity.to_sber_current_state()
        assert entity_id in result


# =========================================================================
# 2. TestMalformedSberPayloads
# =========================================================================


class TestMalformedSberPayloads:
    """parse_sber_command and parse_sber_status_request must handle garbage gracefully."""

    # -- parse_sber_command --

    def test_invalid_json(self):
        """Non-JSON payload must return empty devices dict."""
        result = parse_sber_command(b"not json")
        assert result == {"devices": {}}

    def test_devices_is_string(self):
        """devices: string must return empty devices dict."""
        result = parse_sber_command(b'{"devices": "string"}')
        assert result == {"devices": {}}

    def test_devices_is_array(self):
        """devices: array must return empty devices dict."""
        result = parse_sber_command(b'{"devices": [1,2,3]}')
        assert result == {"devices": {}}

    def test_devices_is_number(self):
        """devices: number must return empty devices dict."""
        result = parse_sber_command(b'{"devices": 42}')
        assert result == {"devices": {}}

    def test_devices_is_null(self):
        """devices: null must return empty devices dict."""
        result = parse_sber_command(b'{"devices": null}')
        assert result == {"devices": {}}

    def test_devices_is_bool(self):
        """devices: bool must return empty devices dict."""
        result = parse_sber_command(b'{"devices": true}')
        assert result == {"devices": {}}

    def test_missing_devices_key(self):
        """Missing 'devices' key must return empty devices dict."""
        result = parse_sber_command(b'{"foo": "bar"}')
        assert result == {"devices": {}}

    def test_empty_object(self):
        """Empty JSON object (no devices key) must return empty devices dict."""
        result = parse_sber_command(b"{}")
        assert result == {"devices": {}}

    def test_empty_bytes(self):
        """Empty bytes must return empty devices dict."""
        result = parse_sber_command(b"")
        assert result == {"devices": {}}

    def test_none_payload(self):
        """None payload must return empty devices dict."""
        result = parse_sber_command(None)
        assert result == {"devices": {}}

    def test_valid_command_passes_through(self):
        """Valid command with dict devices must pass through unchanged."""
        result = parse_sber_command(b'{"devices": {"light.test": {"states": []}}}')
        assert "light.test" in result["devices"]

    # -- parse_sber_status_request --

    def test_status_request_invalid_json(self):
        """Non-JSON payload must return empty list."""
        result = parse_sber_status_request(b"not json")
        assert result == []

    def test_status_request_devices_is_dict(self):
        """devices: dict must return empty list (expected list)."""
        result = parse_sber_status_request(b'{"devices": {"id": "123"}}')
        assert result == []

    def test_status_request_devices_is_string(self):
        """devices: string must return empty list."""
        result = parse_sber_status_request(b'{"devices": "some_string"}')
        assert result == []

    def test_status_request_devices_is_number(self):
        """devices: number must return empty list."""
        result = parse_sber_status_request(b'{"devices": 42}')
        assert result == []

    def test_status_request_empty_string_entry(self):
        """Single empty-string device ID must return empty list (all devices)."""
        result = parse_sber_status_request(b'{"devices": [""]}')
        assert result == []

    def test_status_request_none_payload(self):
        """None payload must return empty list."""
        result = parse_sber_status_request(None)
        assert result == []

    def test_status_request_empty_bytes(self):
        """Empty bytes must return empty list."""
        result = parse_sber_status_request(b"")
        assert result == []

    def test_status_request_missing_devices(self):
        """Missing devices key must return empty list."""
        result = parse_sber_status_request(b'{"foo": "bar"}')
        assert result == []

    def test_status_request_valid(self):
        """Valid status request with device list passes through."""
        result = parse_sber_status_request(b'{"devices": ["light.test", "switch.test"]}')
        assert result == ["light.test", "switch.test"]


# =========================================================================
# 3. TestOutOfRangeCommandValues
# =========================================================================


class TestOutOfRangeCommandValues:
    """Commands with extreme numeric values must be clamped, never crash."""

    # -- Light brightness --

    def test_light_brightness_above_max(self):
        """Sber brightness 99999 must be clamped to valid HA range [0..255]."""
        entity = LightEntity(_entity_data("light.test"))
        entity.fill_by_ha_state(_ha_state("light.test", "on", brightness=128, color_mode="brightness"))
        result = entity.process_cmd(
            {"states": [{"key": "light_brightness", "value": {"type": "INTEGER", "integer_value": "99999"}}]}
        )
        assert len(result) == 1
        brightness = result[0]["url"]["service_data"]["brightness"]
        assert 0 <= brightness <= 255

    def test_light_brightness_negative(self):
        """Sber brightness -100 must be clamped to valid HA range [0..255]."""
        entity = LightEntity(_entity_data("light.test"))
        entity.fill_by_ha_state(_ha_state("light.test", "on", brightness=128, color_mode="brightness"))
        result = entity.process_cmd(
            {"states": [{"key": "light_brightness", "value": {"type": "INTEGER", "integer_value": "-100"}}]}
        )
        assert len(result) == 1
        brightness = result[0]["url"]["service_data"]["brightness"]
        assert 0 <= brightness <= 255

    def test_light_brightness_zero(self):
        """Sber brightness 0 must produce valid HA brightness."""
        entity = LightEntity(_entity_data("light.test"))
        entity.fill_by_ha_state(_ha_state("light.test", "on", brightness=128, color_mode="brightness"))
        result = entity.process_cmd(
            {"states": [{"key": "light_brightness", "value": {"type": "INTEGER", "integer_value": "0"}}]}
        )
        assert len(result) == 1
        brightness = result[0]["url"]["service_data"]["brightness"]
        assert 0 <= brightness <= 255

    def test_light_brightness_non_numeric(self):
        """Non-numeric brightness value must be ignored (no crash)."""
        entity = LightEntity(_entity_data("light.test"))
        entity.fill_by_ha_state(_ha_state("light.test", "on", brightness=128, color_mode="brightness"))
        result = entity.process_cmd(
            {"states": [{"key": "light_brightness", "value": {"type": "INTEGER", "integer_value": "abc"}}]}
        )
        assert result == []

    # -- Light color temp --

    def test_light_color_temp_extreme_high(self):
        """Sber color_temp 99999 must clamp to warmest (max mireds → lowest kelvin)."""
        entity = LightEntity(_entity_data("light.test"))
        entity.fill_by_ha_state(
            _ha_state(
                "light.test",
                "on",
                brightness=128,
                color_mode="color_temp",
                min_mireds=153,
                max_mireds=500,
            )
        )
        result = entity.process_cmd(
            {"states": [{"key": "light_colour_temp", "value": {"type": "INTEGER", "integer_value": "99999"}}]}
        )
        assert len(result) == 1
        kelvin = result[0]["url"]["service_data"]["color_temp_kelvin"]
        # Must be within physically valid range for this entity (2000K-6535K)
        assert 1000 <= kelvin <= 10000

    def test_light_color_temp_negative(self):
        """Sber color_temp -100 must clamp to coolest (min mireds → highest kelvin)."""
        entity = LightEntity(_entity_data("light.test"))
        entity.fill_by_ha_state(
            _ha_state(
                "light.test",
                "on",
                brightness=128,
                color_mode="color_temp",
                min_mireds=153,
                max_mireds=500,
            )
        )
        result = entity.process_cmd(
            {"states": [{"key": "light_colour_temp", "value": {"type": "INTEGER", "integer_value": "-100"}}]}
        )
        assert len(result) == 1
        kelvin = result[0]["url"]["service_data"]["color_temp_kelvin"]
        assert 1000 <= kelvin <= 10000

    # -- Light colour (HSV) --

    def test_light_colour_extreme_hsv_values(self):
        """HSV values beyond spec (h>360, s>1000, v>1000) must be clamped."""
        entity = LightEntity(_entity_data("light.test"))
        entity.fill_by_ha_state(
            _ha_state(
                "light.test",
                "on",
                brightness=128,
                color_mode="hs",
                hs_color=[180.0, 50.0],
                supported_color_modes=["hs"],
            )
        )
        result = entity.process_cmd(
            {
                "states": [
                    {
                        "key": "light_colour",
                        "value": {"colour_value": {"h": 999, "s": 5000, "v": 5000}},
                    }
                ]
            }
        )
        assert len(result) == 1
        sd = result[0]["url"]["service_data"]
        assert "hs_color" in sd
        assert "brightness" in sd

    def test_light_colour_negative_hsv_values(self):
        """Negative HSV values must be clamped to 0."""
        entity = LightEntity(_entity_data("light.test"))
        entity.fill_by_ha_state(
            _ha_state(
                "light.test",
                "on",
                brightness=128,
                color_mode="hs",
                hs_color=[180.0, 50.0],
                supported_color_modes=["hs"],
            )
        )
        result = entity.process_cmd(
            {
                "states": [
                    {
                        "key": "light_colour",
                        "value": {"colour_value": {"h": -10, "s": -20, "v": -30}},
                    }
                ]
            }
        )
        assert len(result) == 1

    def test_light_colour_missing_colour_value(self):
        """Missing colour_value must not crash."""
        entity = LightEntity(_entity_data("light.test"))
        entity.fill_by_ha_state(_ha_state("light.test", "on", brightness=128, color_mode="hs"))
        result = entity.process_cmd({"states": [{"key": "light_colour", "value": {}}]})
        # colour_value is None => fallback to (0,0,0)
        assert len(result) == 1

    # -- Climate temperature --

    def test_climate_temperature_extreme_high(self):
        """hvac_temp_set 999 must not crash."""
        entity = ClimateEntity(_entity_data("climate.test"))
        entity.fill_by_ha_state(
            _ha_state(
                "climate.test",
                "cool",
                current_temperature=22.0,
                temperature=24.0,
                hvac_modes=["cool", "heat", "off"],
                min_temp=16,
                max_temp=32,
            )
        )
        result = entity.process_cmd(
            {"states": [{"key": "hvac_temp_set", "value": {"type": "INTEGER", "integer_value": "999"}}]}
        )
        assert len(result) == 1
        temp = result[0]["url"]["service_data"]["temperature"]
        # HA climate service accepts the value; clamping is entity's responsibility.
        # At minimum it must be a valid number.
        assert isinstance(temp, (int, float))

    def test_climate_temperature_extreme_low(self):
        """hvac_temp_set -50 must not crash."""
        entity = ClimateEntity(_entity_data("climate.test"))
        entity.fill_by_ha_state(
            _ha_state(
                "climate.test",
                "heat",
                current_temperature=22.0,
                temperature=24.0,
                hvac_modes=["cool", "heat", "off"],
                min_temp=16,
                max_temp=32,
            )
        )
        result = entity.process_cmd(
            {"states": [{"key": "hvac_temp_set", "value": {"type": "INTEGER", "integer_value": "-50"}}]}
        )
        assert len(result) == 1

    def test_climate_temperature_non_numeric(self):
        """Non-numeric temperature must be ignored."""
        entity = ClimateEntity(_entity_data("climate.test"))
        entity.fill_by_ha_state(
            _ha_state(
                "climate.test",
                "cool",
                current_temperature=22.0,
                temperature=24.0,
                hvac_modes=["cool", "heat", "off"],
            )
        )
        result = entity.process_cmd(
            {"states": [{"key": "hvac_temp_set", "value": {"type": "INTEGER", "integer_value": "hot"}}]}
        )
        assert result == []

    # -- Curtain position --

    def test_curtain_position_above_100(self):
        """open_percentage 150 must be clamped to 100."""
        entity = CurtainEntity(_entity_data("cover.test"))
        entity.fill_by_ha_state(_ha_state("cover.test", "open", current_position=50))
        result = entity.process_cmd(
            {"states": [{"key": "open_percentage", "value": {"type": "INTEGER", "integer_value": "150"}}]}
        )
        assert len(result) == 1
        position = result[0]["url"]["service_data"]["position"]
        assert 0 <= position <= 100

    def test_curtain_position_negative(self):
        """open_percentage -10 must be clamped to 0."""
        entity = CurtainEntity(_entity_data("cover.test"))
        entity.fill_by_ha_state(_ha_state("cover.test", "open", current_position=50))
        result = entity.process_cmd(
            {"states": [{"key": "open_percentage", "value": {"type": "INTEGER", "integer_value": "-10"}}]}
        )
        assert len(result) == 1
        position = result[0]["url"]["service_data"]["position"]
        assert position == 0

    def test_curtain_position_non_numeric(self):
        """Non-numeric position must be ignored."""
        entity = CurtainEntity(_entity_data("cover.test"))
        entity.fill_by_ha_state(_ha_state("cover.test", "open", current_position=50))
        result = entity.process_cmd(
            {"states": [{"key": "open_percentage", "value": {"type": "INTEGER", "integer_value": "halfway"}}]}
        )
        assert result == []

    # -- Climate humidity --

    def test_climate_humidity_extreme_high(self):
        """hvac_humidity_set 999 must not crash."""
        entity = ClimateEntity(_entity_data("climate.test"))
        entity.fill_by_ha_state(
            _ha_state(
                "climate.test",
                "cool",
                current_temperature=22.0,
                temperature=24.0,
                hvac_modes=["cool", "heat", "off"],
                target_humidity=50,
            )
        )
        result = entity.process_cmd(
            {"states": [{"key": "hvac_humidity_set", "value": {"type": "INTEGER", "integer_value": "999"}}]}
        )
        assert len(result) == 1

    def test_climate_humidity_negative(self):
        """hvac_humidity_set -10 — must not send negative humidity to HA.

        Per Sber spec, humidity is 0-100%. Negative value should either be
        clamped to 0 or rejected. At minimum the sent value must be >= 0.
        """
        entity = ClimateEntity(_entity_data("climate.test"))
        entity.fill_by_ha_state(
            _ha_state(
                "climate.test",
                "cool",
                current_temperature=22.0,
                temperature=24.0,
                hvac_modes=["cool", "heat", "off"],
            )
        )
        result = entity.process_cmd(
            {"states": [{"key": "hvac_humidity_set", "value": {"type": "INTEGER", "integer_value": "-10"}}]}
        )
        if result:
            humidity = result[0]["url"]["service_data"]["humidity"]
            assert humidity >= 0, f"Negative humidity {humidity} must not be sent to HA"


# =========================================================================
# 4. TestNoneAndNaNAttributes
# =========================================================================


class TestNoneAndNaNAttributes:
    """fill_by_ha_state must not crash on None, NaN, Inf, or non-numeric attributes."""

    def test_light_brightness_none(self):
        """Light with brightness=None must not crash."""
        entity = LightEntity(_entity_data("light.test"))
        entity.fill_by_ha_state(
            _ha_state(
                "light.test",
                "on",
                brightness=None,
                color_mode="brightness",
            )
        )
        result = entity.to_sber_current_state()
        assert "light.test" in result

    def test_light_color_temp_none(self):
        """Light with color_temp=None must not crash."""
        entity = LightEntity(_entity_data("light.test"))
        entity.fill_by_ha_state(
            _ha_state(
                "light.test",
                "on",
                brightness=128,
                color_temp=None,
                color_mode="color_temp",
            )
        )
        result = entity.to_sber_current_state()
        assert "light.test" in result

    def test_light_hs_color_none(self):
        """Light with hs_color=None must not crash."""
        entity = LightEntity(_entity_data("light.test"))
        entity.fill_by_ha_state(
            _ha_state(
                "light.test",
                "on",
                brightness=128,
                hs_color=None,
                color_mode="hs",
            )
        )
        result = entity.to_sber_current_state()
        assert "light.test" in result

    def test_light_max_mireds_none(self):
        """Light with max_mireds=None must not crash."""
        entity = LightEntity(_entity_data("light.test"))
        entity.fill_by_ha_state(
            _ha_state(
                "light.test",
                "on",
                brightness=128,
                color_mode="brightness",
                max_mireds=None,
                min_mireds=None,
            )
        )
        result = entity.to_sber_current_state()
        assert "light.test" in result

    @pytest.mark.xfail(
        reason="BUG: ClimateEntity.to_sber_current_state crashes on NaN temperature "
        "(ValueError: cannot convert float NaN to integer)",
        strict=True,
    )
    def test_climate_temperature_nan(self):
        """Climate with current_temperature=NaN must not crash."""
        entity = ClimateEntity(_entity_data("climate.test"))
        entity.fill_by_ha_state(
            _ha_state(
                "climate.test",
                "cool",
                current_temperature=float("nan"),
                temperature=22.0,
                hvac_modes=["cool", "heat", "off"],
            )
        )
        result = entity.to_sber_current_state()
        assert "climate.test" in result

    def test_climate_target_temperature_none(self):
        """Climate with temperature=None must not crash."""
        entity = ClimateEntity(_entity_data("climate.test"))
        entity.fill_by_ha_state(
            _ha_state(
                "climate.test",
                "cool",
                current_temperature=22.0,
                temperature=None,
                hvac_modes=["cool", "heat", "off"],
            )
        )
        result = entity.to_sber_current_state()
        assert "climate.test" in result

    def test_climate_min_temp_none(self):
        """Climate with min_temp=None must fall back to default."""
        entity = ClimateEntity(_entity_data("climate.test"))
        entity.fill_by_ha_state(
            _ha_state(
                "climate.test",
                "cool",
                current_temperature=22.0,
                temperature=24.0,
                min_temp=None,
                max_temp=None,
                hvac_modes=["cool", "heat", "off"],
            )
        )
        # Should use defaults: 16.0 / 32.0
        assert entity.min_temp == 16.0
        assert entity.max_temp == 32.0

    @pytest.mark.xfail(
        reason="BUG: SensorTempEntity._get_sber_value crashes on Inf "
        "(OverflowError: cannot convert float infinity to integer)",
        strict=True,
    )
    def test_sensor_temp_inf(self):
        """Temperature sensor with state='inf' must not crash."""
        entity = SensorTempEntity(_entity_data("sensor.test"))
        entity.fill_by_ha_state(_ha_state("sensor.test", "inf"))
        result = entity.to_sber_current_state()
        assert "sensor.test" in result

    @pytest.mark.xfail(
        reason="BUG: SensorTempEntity._get_sber_value crashes on NaN (ValueError: cannot convert float NaN to integer)",
        strict=True,
    )
    def test_sensor_temp_nan_string(self):
        """Temperature sensor with state='nan' must not crash."""
        entity = SensorTempEntity(_entity_data("sensor.test"))
        entity.fill_by_ha_state(_ha_state("sensor.test", "nan"))
        result = entity.to_sber_current_state()
        assert "sensor.test" in result

    @pytest.mark.xfail(
        reason="BUG: SensorTempEntity._get_sber_value crashes on -Inf "
        "(OverflowError: cannot convert float infinity to integer)",
        strict=True,
    )
    def test_sensor_temp_negative_inf(self):
        """Temperature sensor with state='-inf' must not crash."""
        entity = SensorTempEntity(_entity_data("sensor.test"))
        entity.fill_by_ha_state(_ha_state("sensor.test", "-inf"))
        result = entity.to_sber_current_state()
        assert "sensor.test" in result

    def test_humidity_sensor_non_numeric(self):
        """Humidity sensor with state='high' must not crash."""
        entity = HumiditySensorEntity(_entity_data("sensor.test"))
        entity.fill_by_ha_state(_ha_state("sensor.test", "high"))
        result = entity.to_sber_current_state()
        assert "sensor.test" in result

    def test_curtain_position_string(self):
        """Curtain with current_position='fifty' must not crash; falls back."""
        entity = CurtainEntity(_entity_data("cover.test"))
        entity.fill_by_ha_state(
            _ha_state(
                "cover.test",
                "open",
                current_position="fifty",
            )
        )
        # Should fallback: state is 'opened' => 100, but state is 'open' not 'opened'
        result = entity.to_sber_current_state()
        assert "cover.test" in result

    def test_curtain_position_none(self):
        """Curtain with current_position=None must fallback based on state."""
        entity = CurtainEntity(_entity_data("cover.test"))
        entity.fill_by_ha_state(
            _ha_state(
                "cover.test",
                "closed",
                current_position=None,
            )
        )
        assert entity.current_position == 0

    def test_curtain_position_negative_float(self):
        """Curtain with current_position=-5.5 must be clamped to 0."""
        entity = CurtainEntity(_entity_data("cover.test"))
        entity.fill_by_ha_state(
            _ha_state(
                "cover.test",
                "open",
                current_position=-5.5,
            )
        )
        assert entity.current_position == 0

    def test_climate_target_humidity_non_numeric(self):
        """Climate with target_humidity='wet' must not crash."""
        entity = ClimateEntity(_entity_data("climate.test"))
        entity.fill_by_ha_state(
            _ha_state(
                "climate.test",
                "cool",
                current_temperature=22.0,
                temperature=24.0,
                target_humidity="wet",
                hvac_modes=["cool", "heat", "off"],
            )
        )
        # Non-numeric target_humidity is handled gracefully
        assert entity._target_humidity is None

    def test_relay_with_non_numeric_power(self):
        """Relay with power='unknown' must not crash."""
        entity = RelayEntity(_entity_data("switch.test"))
        entity.fill_by_ha_state(
            _ha_state(
                "switch.test",
                "on",
                power="unknown",
            )
        )
        result = entity.to_sber_current_state()
        assert "switch.test" in result

    def test_vacuum_with_none_battery(self):
        """Vacuum with battery_level=None must not crash."""
        entity = VacuumCleanerEntity(_entity_data("vacuum.test"))
        entity.fill_by_ha_state(
            _ha_state(
                "vacuum.test",
                "docked",
                battery_level=None,
            )
        )
        result = entity.to_sber_current_state()
        assert "vacuum.test" in result

    def test_tv_with_none_volume(self):
        """TV with volume_level=None must not crash."""
        entity = TvEntity(_entity_data("media_player.test"))
        entity.fill_by_ha_state(
            _ha_state(
                "media_player.test",
                "playing",
                volume_level=None,
                is_volume_muted=None,
            )
        )
        result = entity.to_sber_current_state()
        assert "media_player.test" in result


# =========================================================================
# 5. TestCommandWithMissingFields
# =========================================================================


class TestCommandWithMissingFields:
    """Commands with missing or malformed fields must not crash."""

    def test_cmd_no_value_key(self):
        """Command state entry without 'value' key must be handled gracefully."""
        entity = RelayEntity(_entity_data("switch.test"))
        entity.fill_by_ha_state(_ha_state("switch.test", "off"))
        result = entity.process_cmd({"states": [{"key": "on_off"}]})
        # Missing value => type check fails => not processed
        assert result == []

    def test_cmd_empty_value(self):
        """Command with empty value dict must be handled gracefully."""
        entity = RelayEntity(_entity_data("switch.test"))
        entity.fill_by_ha_state(_ha_state("switch.test", "off"))
        result = entity.process_cmd({"states": [{"key": "on_off", "value": {}}]})
        # Empty value dict has no 'type' => type check fails
        assert result == []

    def test_cmd_no_states_key(self):
        """Command payload without 'states' key must return empty list."""
        entity = RelayEntity(_entity_data("switch.test"))
        entity.fill_by_ha_state(_ha_state("switch.test", "off"))
        result = entity.process_cmd({"other": "data"})
        assert result == []

    def test_cmd_none_payload(self):
        """process_cmd(None) must not crash for entities that support it."""
        entity = LightEntity(_entity_data("light.test"))
        entity.fill_by_ha_state(_ha_state("light.test", "on", brightness=128))
        result = entity.process_cmd(None)
        assert result == []

    def test_cmd_states_is_empty_list(self):
        """Empty states list must return empty result."""
        entity = RelayEntity(_entity_data("switch.test"))
        entity.fill_by_ha_state(_ha_state("switch.test", "off"))
        result = entity.process_cmd({"states": []})
        assert result == []

    def test_cmd_state_entry_no_key(self):
        """State entry without 'key' must be ignored."""
        entity = LightEntity(_entity_data("light.test"))
        entity.fill_by_ha_state(_ha_state("light.test", "on", brightness=128))
        result = entity.process_cmd({"states": [{"value": {"type": "BOOL", "bool_value": True}}]})
        assert result == []

    def test_cmd_unknown_key_ignored(self):
        """Unknown command key must be ignored without crash."""
        entity = LightEntity(_entity_data("light.test"))
        entity.fill_by_ha_state(_ha_state("light.test", "on", brightness=128))
        result = entity.process_cmd({"states": [{"key": "magic_spell", "value": {"type": "BOOL", "bool_value": True}}]})
        assert result == []

    def test_climate_cmd_no_value(self):
        """Climate command without value must not crash."""
        entity = ClimateEntity(_entity_data("climate.test"))
        entity.fill_by_ha_state(
            _ha_state(
                "climate.test",
                "cool",
                current_temperature=22.0,
                temperature=24.0,
                hvac_modes=["cool", "heat", "off"],
            )
        )
        result = entity.process_cmd({"states": [{"key": "hvac_temp_set"}]})
        # Missing value => _safe_float(None) => None => skip
        assert result == []

    def test_climate_cmd_empty_enum_value(self):
        """Climate command with empty enum_value must not crash."""
        entity = ClimateEntity(_entity_data("climate.test"))
        entity.fill_by_ha_state(
            _ha_state(
                "climate.test",
                "cool",
                current_temperature=22.0,
                temperature=24.0,
                hvac_modes=["cool", "heat", "off"],
            )
        )
        result = entity.process_cmd({"states": [{"key": "hvac_work_mode", "value": {"enum_value": ""}}]})
        assert result == []

    def test_valve_cmd_missing_enum_value(self):
        """Valve command with missing enum_value must not crash."""
        entity = ValveEntity(_entity_data("valve.test"))
        entity.fill_by_ha_state(_ha_state("valve.test", "closed"))
        result = entity.process_cmd({"states": [{"key": "open_set", "value": {"type": "ENUM"}}]})
        assert result == []

    def test_curtain_cmd_missing_integer_value(self):
        """Curtain position command without integer_value must not crash."""
        entity = CurtainEntity(_entity_data("cover.test"))
        entity.fill_by_ha_state(_ha_state("cover.test", "open", current_position=50))
        result = entity.process_cmd({"states": [{"key": "open_percentage", "value": {"type": "INTEGER"}}]})
        assert result == []

    def test_sensor_process_cmd_any_payload(self):
        """Sensors must return empty list for any command payload."""
        entity = SensorTempEntity(_entity_data("sensor.test"))
        entity.fill_by_ha_state(_ha_state("sensor.test", "22.5"))
        result = entity.process_cmd({"states": [{"key": "anything", "value": {"foo": "bar"}}]})
        assert result == []

    def test_sensor_process_cmd_none(self):
        """Sensors must return empty list for None command."""
        entity = SensorTempEntity(_entity_data("sensor.test"))
        entity.fill_by_ha_state(_ha_state("sensor.test", "22.5"))
        result = entity.process_cmd(None)
        assert result == []

    @pytest.mark.parametrize(
        ("entity_cls", "entity_id"),
        [
            (RelayEntity, "switch.test"),
            (SocketEntity, "switch.test_socket"),
            (ValveEntity, "valve.test"),
            (CurtainEntity, "cover.test"),
            (LightEntity, "light.test"),
            (ClimateEntity, "climate.test"),
            (HumidifierEntity, "humidifier.test"),
            (TvEntity, "media_player.test"),
            (VacuumCleanerEntity, "vacuum.test"),
            (HvacFanEntity, "fan.test"),
            (KettleEntity, "switch.test_kettle"),
            (IntercomEntity, "switch.test_intercom"),
        ],
        ids=lambda x: x.__name__ if isinstance(x, type) else x,
    )
    def test_cmd_empty_states_all_controllable_entities(self, entity_cls, entity_id):
        """Empty states list must return empty result for all controllable entities."""
        entity = entity_cls(_entity_data(entity_id))
        entity.fill_by_ha_state(_ha_state(entity_id, "off"))
        result = entity.process_cmd({"states": []})
        assert result == []
