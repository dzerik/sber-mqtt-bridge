"""Schema of the commands an exposed entity accepts — feeds the DevTools command builder.

Hand-writing a ``down/commands`` payload meant knowing each feature's value
type, its payload key and its allowed range by heart; a typo made the
bridge silently ignore the test.  The schema is derived from what the
entity actually declares to Sber, so the builder can only offer commands
Sber could send.
"""

from __future__ import annotations

from custom_components.sber_mqtt_bridge.command_schema import build_command_schema
from custom_components.sber_mqtt_bridge.devices.light import LightEntity
from custom_components.sber_mqtt_bridge.devices.sensor_temp import SensorTempEntity


def _lamp() -> LightEntity:
    lamp = LightEntity({"entity_id": "light.lamp", "name": "Lamp"})
    lamp.fill_by_ha_state(
        {
            "entity_id": "light.lamp",
            "state": "on",
            "attributes": {
                "supported_color_modes": ["hs", "color_temp"],
                "color_mode": "hs",
                "brightness": 128,
                "hs_color": [120, 50],
                "min_color_temp_kelvin": 2700,
                "max_color_temp_kelvin": 6500,
            },
        }
    )
    return lamp


def _by_key(schema: list[dict]) -> dict[str, dict]:
    return {f["key"]: f for f in schema}


def test_lamp_offers_its_writable_features_with_types_and_bounds() -> None:
    schema = _by_key(build_command_schema(_lamp()))
    assert schema["on_off"] == {"key": "on_off", "type": "BOOL", "field": "bool_value"}
    assert schema["light_brightness"]["type"] == "INTEGER"
    assert (schema["light_brightness"]["min"], schema["light_brightness"]["max"]) == (100, 900)
    assert schema["light_mode"]["enum_values"] == ["colour", "white"]
    assert schema["light_colour"]["type"] == "COLOUR"
    assert schema["light_colour"]["components"] == {"h": [0, 360], "s": [0, 1000], "v": [100, 1000]}


def test_read_only_features_are_not_offered() -> None:
    schema = _by_key(build_command_schema(_lamp()))
    assert "online" not in schema


def test_sensor_has_nothing_to_command() -> None:
    sensor = SensorTempEntity({"entity_id": "sensor.t", "name": "T"})
    sensor.fill_by_ha_state({"entity_id": "sensor.t", "state": "21.5", "attributes": {"device_class": "temperature"}})
    assert build_command_schema(sensor) == []


def test_schema_is_sorted_by_key() -> None:
    keys = [f["key"] for f in build_command_schema(_lamp())]
    assert keys == sorted(keys)
