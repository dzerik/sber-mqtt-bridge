"""AUTO-GENERATED from tests/hacs/__snapshots__/sber_full_spec.json.

DO NOT EDIT BY HAND.  Regenerate with:

    python tools/codegen.py

Source: https://developers.sber.ru/docs/ru/smarthome/c2c
Spec generated at: 2026-04-12T21:05:04.890060+00:00
"""

from __future__ import annotations

CATEGORY_REFERENCE_FEATURES: dict[str, frozenset[str]] = {
    "curtain": frozenset(
        {
            "battery_low_power",
            "battery_percentage",
            "online",
            "open_left_percentage",
            "open_rate",
            "open_right_percentage",
            "open_right_set",
            "open_right_state",
            "open_set",
            "open_state",
            "signal_strength",
        }
    ),
    "gate": frozenset(
        {
            "online",
            "open_left_percentage",
            "open_left_set",
            "open_left_state",
            "open_rate",
            "open_right_percentage",
            "open_right_set",
            "open_right_state",
            "open_set",
            "open_state",
            "signal_strength",
        }
    ),
    "hub": frozenset({"online"}),
    "hvac_ac": frozenset(
        {
            "hvac_air_flow_direction",
            "hvac_air_flow_power",
            "hvac_humidity_set",
            "hvac_night_mode",
            "hvac_temp_set",
            "hvac_work_mode",
            "on_off",
            "online",
        }
    ),
    "hvac_air_purifier": frozenset(
        {
            "hvac_air_flow_power",
            "hvac_aromatization",
            "hvac_ionization",
            "hvac_night_mode",
            "hvac_replace_filter",
            "hvac_replace_ionizator",
            "on_off",
            "online",
        }
    ),
    "hvac_boiler": frozenset({"hvac_temp_set", "hvac_thermostat_mode", "on_off", "online", "temperature"}),
    "hvac_fan": frozenset({"hvac_air_flow_power", "on_off", "online"}),
    "hvac_heater": frozenset(
        {"hvac_air_flow_power", "hvac_temp_set", "hvac_thermostat_mode", "on_off", "online", "temperature"}
    ),
    "hvac_humidifier": frozenset(
        {
            "humidity",
            "hvac_air_flow_power",
            "hvac_humidity_set",
            "hvac_ionization",
            "hvac_night_mode",
            "hvac_replace_filter",
            "hvac_replace_ionizator",
            "hvac_water_low_level",
            "hvac_water_percentage",
            "on_off",
            "online",
        }
    ),
    "hvac_radiator": frozenset({"hvac_temp_set", "on_off", "online", "temperature"}),
    "hvac_underfloor_heating": frozenset({"hvac_temp_set", "hvac_thermostat_mode", "on_off", "online", "temperature"}),
    "intercom": frozenset({"incoming_call", "online", "reject_call", "unlock"}),
    "kettle": frozenset(
        {
            "child_lock",
            "kitchen_water_level",
            "kitchen_water_low_level",
            "kitchen_water_temperature",
            "kitchen_water_temperature_set",
            "on_off",
            "online",
        }
    ),
    "led_strip": frozenset(
        {"light_brightness", "light_colour", "light_colour_temp", "light_mode", "on_off", "online", "sleep_timer"}
    ),
    "light": frozenset({"light_brightness", "light_colour", "light_colour_temp", "light_mode", "on_off", "online"}),
    "relay": frozenset({"current", "on_off", "online", "power", "voltage"}),
    "scenario_button": frozenset(
        {"battery_percentag", "button_1_event", "button_2_event", "online", "signal_strength"}
    ),
    "sensor_door": frozenset(
        {
            "battery_low_power",
            "battery_percentage",
            "doorcontact_state",
            "online",
            "sensor_sensitive",
            "signal_strength",
            "tamper_alarm",
        }
    ),
    "sensor_gas": frozenset(
        {
            "alarm_mute",
            "battery_low_power",
            "battery_percentage",
            "gas_leak_state",
            "online",
            "sensor_sensitive",
            "signal_strength",
        }
    ),
    "sensor_pir": frozenset(
        {"battery_low_power", "battery_percentage", "online", "pir", "sensor_sensitive", "signal_strength"}
    ),
    "sensor_smoke": frozenset(
        {"alarm_mute", "battery_low_power", "battery_percentage", "online", "signal_strength", "smoke_state"}
    ),
    "sensor_temp": frozenset(
        {
            "air_pressure",
            "battery_low_power",
            "battery_percentage",
            "humidity",
            "online",
            "sensor_sensitive",
            "signal_strength",
            "temp_unit_view",
            "temperature",
        }
    ),
    "sensor_water_leak": frozenset(
        {"battery_low_power", "battery_percentage", "online", "signal_strength", "water_leak_state"}
    ),
    "socket": frozenset({"child_lock", "current", "on_off", "online", "power", "voltage"}),
    "tv": frozenset(
        {
            "channel",
            "channel_int",
            "custom_key",
            "direction",
            "mute",
            "number",
            "on_off",
            "online",
            "source",
            "volume",
            "volume_int",
        }
    ),
    "vacuum_cleaner": frozenset(
        {
            "battery_percentage",
            "child_lock",
            "online",
            "vacuum_cleaner_cleaning_type",
            "vacuum_cleaner_command",
            "vacuum_cleaner_program",
            "vacuum_cleaner_status",
        }
    ),
    "valve": frozenset(
        {"battery_low_power", "battery_percentage", "online", "open_set", "open_state", "signal_strength"}
    ),
    "window_blind": frozenset(
        {
            "battery_low_power",
            "battery_percentage",
            "online",
            "open_percentage",
            "open_rate",
            "open_set",
            "open_state",
            "signal_strength",
        }
    ),
}
"""All features listed in the Sber reference model for each category.

This is the *widest* known-valid feature set per category.  Use for
compliance checks: features we emit outside this set are unknown to
Sber cloud and likely cause silent rejection (see the TV allowed_values
bug that motivated this module)."""
