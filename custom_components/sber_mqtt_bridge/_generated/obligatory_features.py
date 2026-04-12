"""AUTO-GENERATED from tests/hacs/__snapshots__/sber_full_spec.json.

DO NOT EDIT BY HAND.  Regenerate with:

    python tools/codegen.py

Source: https://developers.sber.ru/docs/ru/smarthome/c2c
Spec generated at: 2026-04-12T21:42:23.056807+00:00
"""

from __future__ import annotations

CATEGORY_OBLIGATORY_FEATURES: dict[str, frozenset[str]] = {
    "curtain": frozenset({"online", "open_percentage", "open_set", "open_state"}),
    "gate": frozenset({"online", "open_percentage", "open_set", "open_state"}),
    "hub": frozenset({"online"}),
    "hvac_ac": frozenset({"hvac_temp_set", "on_off", "online"}),
    "hvac_air_purifier": frozenset({"on_off", "online"}),
    "hvac_boiler": frozenset({"on_off", "online"}),
    "hvac_fan": frozenset({"on_off", "online"}),
    "hvac_heater": frozenset({"on_off", "online"}),
    "hvac_humidifier": frozenset({"on_off", "online"}),
    "hvac_radiator": frozenset({"on_off", "online"}),
    "hvac_underfloor_heating": frozenset({"on_off", "online"}),
    "intercom": frozenset({"online"}),
    "kettle": frozenset({"on_off", "online"}),
    "led_strip": frozenset({"on_off", "online"}),
    "light": frozenset({"on_off", "online"}),
    "relay": frozenset({"on_off", "online"}),
    "scenario_button": frozenset({"online"}),
    "sensor_door": frozenset({"doorcontact_state", "online"}),
    "sensor_gas": frozenset({"gas_leak_state", "online"}),
    "sensor_pir": frozenset({"online", "pir"}),
    "sensor_smoke": frozenset({"online", "smoke_state"}),
    "sensor_temp": frozenset({"humidity", "online", "temperature"}),
    "sensor_water_leak": frozenset({"online", "water_leak_state"}),
    "socket": frozenset({"on_off", "online"}),
    "tv": frozenset({"on_off", "online"}),
    "vacuum_cleaner": frozenset({"online"}),
    "valve": frozenset({"online", "open_percentage", "open_set", "open_state"}),
    "window_blind": frozenset({"online", "open_percentage", "open_set", "open_state"}),
}
"""Features marked obligatory (``✔︎``) in Sber docs per category.

Extracted from the "Доступные функции устройства" table on each
category page.  These are the features every device of this category
MUST emit to be accepted by Sber cloud — emitting fewer is a likely
cause of silent rejection."""
