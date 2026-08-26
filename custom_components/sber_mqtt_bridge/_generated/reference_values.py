"""AUTO-GENERATED from tests/hacs/__snapshots__/sber_full_spec.json.

DO NOT EDIT BY HAND.  Regenerate with:

    python tools/codegen.py

Source: https://developers.sber.ru/docs/ru/smarthome/c2c
Spec generated at: 2026-08-26T11:22:53.415012+00:00
"""

from __future__ import annotations

FEATURE_ENUM_VALUES: dict[str, frozenset[str]] = {
    "button_10_event": frozenset({"click", "double_click", "long_press"}),
    "button_1_event": frozenset({"click", "double_click", "long_press"}),
    "button_2_event": frozenset({"click", "double_click", "long_press"}),
    "button_3_event": frozenset({"click", "double_click", "long_press"}),
    "button_4_event": frozenset({"click", "double_click", "long_press"}),
    "button_5_event": frozenset({"click", "double_click", "long_press"}),
    "button_6_event": frozenset({"click", "double_click", "long_press"}),
    "button_7_event": frozenset({"click", "double_click", "long_press"}),
    "button_8_event": frozenset({"click", "double_click", "long_press"}),
    "button_9_event": frozenset({"click", "double_click", "long_press"}),
    "button_bottom_left_event": frozenset({"click", "double_click", "long_press"}),
    "button_bottom_right_event": frozenset({"click", "double_click", "long_press"}),
    "button_event": frozenset({"click", "double_click", "long_press"}),
    "button_left_event": frozenset({"click", "double_click", "long_press"}),
    "button_right_event": frozenset({"click", "double_click", "long_press"}),
    "button_top_left_event": frozenset({"click", "double_click", "long_press"}),
    "button_top_right_event": frozenset({"click", "double_click", "long_press"}),
    "channel": frozenset({"+", "-"}),
    "custom_key": frozenset({"back", "confirm", "home", "next", "pause", "play", "previous"}),
    "direction": frozenset({"down", "left", "right", "up"}),
    "hvac_air_flow_direction": frozenset({"auto", "horizontal", "no", "rotation", "swing", "vertical"}),
    "hvac_air_flow_power": frozenset({"auto", "high", "low", "medium", "quiet", "turbo"}),
    "hvac_direction_set": frozenset({"down", "left", "right", "up"}),
    "hvac_heating_rate": frozenset({"auto", "high", "low", "medium"}),
    "hvac_thermostat_mode": frozenset({"auto", "cooling", "eco", "fast_cooling", "fast_heating", "heating", "turbo"}),
    "hvac_work_mode": frozenset(
        {
            "air_purification",
            "auto",
            "comfortable_sleep",
            "cooling",
            "dehumidification",
            "eco",
            "fast_cooling",
            "fast_heating",
            "heating",
            "self_cleaning",
            "turbo",
            "ventilation",
        }
    ),
    "light_mode": frozenset({"colour", "white"}),
    "open_left_set": frozenset({"close", "open", "stop"}),
    "open_left_state": frozenset({"close", "closing", "open", "opening"}),
    "open_rate": frozenset({"auto", "high", "low", "medium"}),
    "open_right_set": frozenset({"close", "open", "stop"}),
    "open_right_state": frozenset({"close", "closing", "open", "opening"}),
    "open_set": frozenset({"close", "open", "stop"}),
    "open_state": frozenset({"close", "closing", "open", "opening"}),
    "pir": frozenset({"pir"}),
    "sensor_sensitive": frozenset({"high", "low", "medium"}),
    "signal_strength": frozenset({"high", "low", "medium"}),
    "source": frozenset({"+", "-", "av", "content", "hdmi1", "hdmi2", "hdmi3", "screencast", "tv"}),
    "temp_unit_view": frozenset({"c", "f"}),
    "vacuum_cleaner_cleaning_type": frozenset({"dry", "mixed", "wet"}),
    "vacuum_cleaner_command": frozenset({"pause", "resume", "return_to_dock", "start"}),
    "vacuum_cleaner_program": frozenset({"perimeter", "random_route", "smart", "spot"}),
    "vacuum_cleaner_status": frozenset({"cleaning", "docked", "pause", "returning_to_dock"}),
    "volume": frozenset({"+", "-"}),
}
"""Every value an ENUM feature accepts, per the function's own page.

This is the authoritative vocabulary, and deliberately NOT the
``allowed_values`` block of a category page: that block is an
illustrative example and is routinely shorter.  ``hvac_air_flow_power``
is the proof — its category examples omit ``quiet``, which the function
page lists and real air purifiers use, so validating against the example
would reject correct devices.

A feature absent from this table has no known vocabulary (every
non-ENUM one, plus the two command-only ENUMs whose pages word things
differently).  Absent means *unknown*, never *nothing allowed* — callers
must skip the check rather than reject."""


FEATURE_RANGES: dict[str, tuple[float, float]] = {
    "air_pressure": (200.0, 800.0),
    "battery_percentage": (0.0, 100.0),
    "channel_int": (0.0, 999.0),
    "co2": (0.0, 10000.0),
    "current": (0.0, 30000.0),
    "hcho_float": (0.0, 1.999),
    "humidity": (0.0, 100.0),
    "hvac_humidity_set": (30.0, 90.0),
    "hvac_temp_set": (5.0, 50.0),
    "hvac_water_level": (0.0, 50.0),
    "hvac_water_percentage": (0.0, 100.0),
    "kitchen_water_level": (0.0, 50.0),
    "kitchen_water_temperature": (0.0, 100.0),
    "kitchen_water_temperature_set": (0.0, 100.0),
    "light_brightness": (50.0, 1000.0),
    "light_colour_temp": (0.0, 1000.0),
    "light_transmission_percentage": (0.0, 100.0),
    "number": (0.0, 9.0),
    "open_left_percentage": (0.0, 100.0),
    "open_percentage": (0.0, 100.0),
    "open_right_percentage": (0.0, 100.0),
    "pm10": (0.0, 1000.0),
    "pm1_0": (0.0, 500.0),
    "pm2_5": (0.0, 500.0),
    "power": (0.0, 50000.0),
    "temperature": (-400.0, 2000.0),
    "tvoc_float": (0.0, 9.999),
    "voltage": (0.0, 5000.0),
    "volume_int": (0.0, 999.0),
}
"""Documented numeric bounds of a feature, inclusive.

Sber states these on the function page ("Тип данных: INTEGER(0, 100)").
A value outside the range is not something the cloud is promised to
handle, so publishing one is worth surfacing — but only as a warning:
the bound describes the *function*, and a device legitimately idling
below it (a socket reporting 0 W against a documented 10 W floor) is
common enough that an error would be noise."""
