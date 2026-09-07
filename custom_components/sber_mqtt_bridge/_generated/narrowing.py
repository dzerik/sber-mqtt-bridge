"""AUTO-GENERATED from tests/hacs/__snapshots__/sber_full_spec.json.

DO NOT EDIT BY HAND.  Regenerate with:

    python tools/codegen.py

Source: https://developers.sber.ru/docs/ru/smarthome/c2c
Spec generated at: 2026-09-07T15:07:37.367121+00:00
"""

from __future__ import annotations

FEATURE_NARROWING: dict[str, str] = {
    "air_pressure": "range_and_step",
    "battery_percentage": "range_and_step",
    "button_10_event": "enum_subset",
    "button_1_event": "enum_subset",
    "button_2_event": "enum_subset",
    "button_3_event": "enum_subset",
    "button_4_event": "enum_subset",
    "button_5_event": "enum_subset",
    "button_6_event": "enum_subset",
    "button_7_event": "enum_subset",
    "button_8_event": "enum_subset",
    "button_9_event": "enum_subset",
    "button_bottom_left_event": "enum_subset",
    "button_bottom_right_event": "enum_subset",
    "button_event": "enum_subset",
    "button_left_event": "enum_subset",
    "button_right_event": "enum_subset",
    "button_top_left_event": "enum_subset",
    "button_top_right_event": "enum_subset",
    "channel": "enum_subset",
    "channel_int": "range_and_step",
    "co2": "range_and_step",
    "current": "range_and_step",
    "custom_key": "enum_subset",
    "direction": "enum_subset",
    "humidity": "range_and_step",
    "hvac_air_flow_direction": "enum_subset",
    "hvac_air_flow_power": "enum_subset",
    "hvac_direction_set": "enum_subset",
    "hvac_heating_rate": "enum_subset",
    "hvac_humidity_set": "range_and_step",
    "hvac_temp_set": "range_and_step",
    "hvac_thermostat_mode": "enum_subset",
    "hvac_water_level": "range_only",
    "hvac_water_percentage": "range_and_step",
    "hvac_work_mode": "enum_subset",
    "kitchen_water_level": "range_only",
    "kitchen_water_temperature": "range_and_step",
    "kitchen_water_temperature_set": "range_and_step",
    "light_brightness": "range_and_step",
    "light_colour_temp": "range_and_step",
    "light_transmission_percentage": "range_and_step",
    "number": "range_and_step",
    "open_left_percentage": "range_and_step",
    "open_left_set": "enum_subset",
    "open_left_state": "enum_subset",
    "open_percentage": "range_and_step",
    "open_rate": "enum_subset",
    "open_right_percentage": "range_and_step",
    "open_right_set": "enum_subset",
    "open_right_state": "enum_subset",
    "open_set": "enum_subset",
    "open_state": "enum_subset",
    "pm10": "range_and_step",
    "pm1_0": "range_and_step",
    "pm2_5": "range_and_step",
    "power": "range_and_step",
    "sensor_sensitive": "enum_subset",
    "signal_strength": "enum_subset",
    "source": "enum_subset",
    "temperature": "range_and_step",
    "vacuum_cleaner_cleaning_type": "enum_subset",
    "vacuum_cleaner_command": "enum_subset",
    "vacuum_cleaner_program": "enum_subset",
    "vacuum_cleaner_status": "enum_subset",
    "voltage": "range_and_step",
    "volume": "enum_subset",
    "volume_int": "range_and_step",
}
"""How far a model may narrow a feature, per the feature's own page.

Sber states it once per function, always opening with "При
описании модели устройства":

- ``enum_subset`` — "перечень … можно сократить"
- ``range_and_step`` — "можно уменьшить диапазон … либо изменить их шаг"
- ``range_only`` — the range may shrink; no step is mentioned

A feature **absent from this table** is one whose page never
mentions narrowing.  That is all it means: no page anywhere states
that a feature may *not* be narrowed, so an ``allowed_values``
entry for an unlisted feature is unconfirmed by the documentation,
not a known violation.

The direction, in contrast, is stated outright — the
``allowed_values`` page says "диапазон можно только сократить" — so
a bound wider than :data:`FEATURE_RANGES` contradicts the docs,
except where Sber's own category example is wider (the reference
``hvac_boiler`` model declares a hotter ``hvac_temp_set`` than the
function page allows)."""


NARROWABLE_ENUM_FEATURES: frozenset[str] = frozenset(
    {
        "button_10_event",
        "button_1_event",
        "button_2_event",
        "button_3_event",
        "button_4_event",
        "button_5_event",
        "button_6_event",
        "button_7_event",
        "button_8_event",
        "button_9_event",
        "button_bottom_left_event",
        "button_bottom_right_event",
        "button_event",
        "button_left_event",
        "button_right_event",
        "button_top_left_event",
        "button_top_right_event",
        "channel",
        "custom_key",
        "direction",
        "hvac_air_flow_direction",
        "hvac_air_flow_power",
        "hvac_direction_set",
        "hvac_heating_rate",
        "hvac_thermostat_mode",
        "hvac_work_mode",
        "open_left_set",
        "open_left_state",
        "open_rate",
        "open_right_set",
        "open_right_state",
        "open_set",
        "open_state",
        "sensor_sensitive",
        "signal_strength",
        "source",
        "vacuum_cleaner_cleaning_type",
        "vacuum_cleaner_command",
        "vacuum_cleaner_program",
        "vacuum_cleaner_status",
        "volume",
    }
)
"""ENUM features whose published vocabulary may be a subset."""


NARROWABLE_RANGE_FEATURES: frozenset[str] = frozenset(
    {
        "air_pressure",
        "battery_percentage",
        "channel_int",
        "co2",
        "current",
        "humidity",
        "hvac_humidity_set",
        "hvac_temp_set",
        "hvac_water_level",
        "hvac_water_percentage",
        "kitchen_water_level",
        "kitchen_water_temperature",
        "kitchen_water_temperature_set",
        "light_brightness",
        "light_colour_temp",
        "light_transmission_percentage",
        "number",
        "open_left_percentage",
        "open_percentage",
        "open_right_percentage",
        "pm10",
        "pm1_0",
        "pm2_5",
        "power",
        "temperature",
        "voltage",
        "volume_int",
    }
)
"""Numeric features whose published range may be shrunk."""
