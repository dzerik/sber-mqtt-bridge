"""AUTO-GENERATED from tests/hacs/__snapshots__/sber_full_spec.json.

DO NOT EDIT BY HAND.  Regenerate with:

    python tools/codegen.py

Source: https://developers.sber.ru/docs/ru/smarthome/c2c
Spec generated at: 2026-09-07T12:06:54.143165+00:00
"""

from __future__ import annotations

FEATURE_USAGE_MODES: dict[str, str] = {
    "air_pressure": "state_read_only",
    "alarm_mute": "state_read_only",
    "battery_low_power": "state_read_only",
    "battery_percentage": "state_read_only",
    "button_10_event": "state_read_write",
    "button_1_event": "state_read_write",
    "button_2_event": "state_read_write",
    "button_3_event": "state_read_write",
    "button_4_event": "state_read_write",
    "button_5_event": "state_read_write",
    "button_6_event": "state_read_write",
    "button_7_event": "state_read_write",
    "button_8_event": "state_read_write",
    "button_9_event": "state_read_write",
    "button_bottom_left_event": "state_read_write",
    "button_bottom_right_event": "state_read_write",
    "button_event": "state_read_write",
    "button_left_event": "state_read_write",
    "button_right_event": "state_read_write",
    "button_top_left_event": "state_read_write",
    "button_top_right_event": "state_read_write",
    "channel": "command_only",
    "channel_int": "state_read_write",
    "child_lock": "state_read_write",
    "co2": "state_read_only",
    "current": "state_read_only",
    "custom_key": "command_only",
    "direction": "command_only",
    "doorcontact_state": "state_read_only",
    "gas_leak_state": "state_read_only",
    "hcho_float": "state_read_only",
    "humidity": "state_read_only",
    "hvac_air_flow_direction": "state_read_write",
    "hvac_air_flow_power": "state_read_write",
    "hvac_aromatization": "state_read_write",
    "hvac_decontaminate": "state_read_write",
    "hvac_direction_set": "command_only",
    "hvac_heating_rate": "state_read_write",
    "hvac_humidity_set": "state_read_write",
    "hvac_ionization": "state_read_write",
    "hvac_night_mode": "state_read_write",
    "hvac_replace_filter": "state_read_only",
    "hvac_replace_ionizator": "state_read_only",
    "hvac_temp_set": "state_read_write",
    "hvac_thermostat_mode": "state_read_write",
    "hvac_water_level": "state_read_only",
    "hvac_water_low_level": "state_read_only",
    "hvac_water_percentage": "state_read_only",
    "hvac_work_mode": "state_read_write",
    "incoming_call": "state_read_only",
    "kitchen_water_level": "state_read_only",
    "kitchen_water_low_level": "state_read_only",
    "kitchen_water_temperature": "state_read_only",
    "kitchen_water_temperature_set": "state_read_write",
    "light_brightness": "state_read_write",
    "light_colour": "state_read_write",
    "light_colour_temp": "state_read_write",
    "light_mode": "state_read_write",
    "light_transmission_percentage": "state_read_write",
    "mute": "command_only",
    "number": "command_only",
    "on_off": "state_read_write",
    "online": "state_read_only",
    "open_left_percentage": "state_read_write",
    "open_left_set": "command_only",
    "open_left_state": "state_read_only",
    "open_percentage": "state_read_write",
    "open_rate": "state_read_write",
    "open_right_percentage": "state_read_write",
    "open_right_set": "command_only",
    "open_right_state": "state_read_only",
    "open_set": "command_only",
    "open_state": "state_read_only",
    "pir": "event_only",
    "pm10": "state_read_only",
    "pm1_0": "state_read_only",
    "pm2_5": "state_read_only",
    "power": "state_read_only",
    "reject_call": "command_only",
    "sensor_sensitive": "state_read_only",
    "signal_strength": "state_read_only",
    "smoke_state": "state_read_only",
    "source": "state_read_write",
    "tamper_alarm": "state_read_only",
    "temp_unit_view": "state_read_only",
    "temperature": "state_read_only",
    "tvoc_float": "state_read_only",
    "unlock": "command_only",
    "vacuum_cleaner_cleaning_type": "state_read_write",
    "vacuum_cleaner_command": "state_read_write",
    "vacuum_cleaner_program": "state_read_write",
    "vacuum_cleaner_status": "state_read_write",
    "voltage": "state_read_only",
    "volume": "command_only",
    "volume_int": "state_read_write",
    "water_leak_state": "state_read_only",
}
"""Feature name → what Sber says the feature is *for*.

Straight off the "Способ использования" line of each function page,
which words it in exactly four ways:

- ``state_read_write`` — "хранит состояние устройства и может менять его"
- ``state_read_only`` — "хранит состояние устройства, менять его не может"
- ``command_only`` — "не хранит состояние устройства, может менять его"
- ``event_only`` — "уведомляет о состоянии устройства, менять его не может"

A feature missing from this table has a wording the scraper did not
recognise — treat that as *unknown*, never as "no restriction"."""


COMMAND_ONLY_FEATURES: frozenset[str] = frozenset(
    {
        "channel",
        "custom_key",
        "direction",
        "hvac_direction_set",
        "mute",
        "number",
        "open_left_set",
        "open_right_set",
        "open_set",
        "reject_call",
        "unlock",
        "volume",
    }
)
"""Features that hold no state and exist only to accept a command.

``open_set`` is the archetype: a curtain must *declare* it, yet it can
never show up in a state publish because there is no state to report.
Any check that walks a publish looking for declared features has to
exempt this set, or it reports healthy devices as incomplete."""


EVENT_ONLY_FEATURES: frozenset[str] = frozenset({"pir"})
"""Features that only ever report that something *happened*.

Sber words these as "уведомляет о состоянии устройства": ``pir`` is
sent when motion is detected and silent otherwise, so silence is the
quiet state rather than a missing value (issue #61)."""


STATE_BEARING_FEATURES: frozenset[str] = frozenset(
    {
        "air_pressure",
        "alarm_mute",
        "battery_low_power",
        "battery_percentage",
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
        "channel_int",
        "child_lock",
        "co2",
        "current",
        "doorcontact_state",
        "gas_leak_state",
        "hcho_float",
        "humidity",
        "hvac_air_flow_direction",
        "hvac_air_flow_power",
        "hvac_aromatization",
        "hvac_decontaminate",
        "hvac_heating_rate",
        "hvac_humidity_set",
        "hvac_ionization",
        "hvac_night_mode",
        "hvac_replace_filter",
        "hvac_replace_ionizator",
        "hvac_temp_set",
        "hvac_thermostat_mode",
        "hvac_water_level",
        "hvac_water_low_level",
        "hvac_water_percentage",
        "hvac_work_mode",
        "incoming_call",
        "kitchen_water_level",
        "kitchen_water_low_level",
        "kitchen_water_temperature",
        "kitchen_water_temperature_set",
        "light_brightness",
        "light_colour",
        "light_colour_temp",
        "light_mode",
        "light_transmission_percentage",
        "on_off",
        "online",
        "open_left_percentage",
        "open_left_state",
        "open_percentage",
        "open_rate",
        "open_right_percentage",
        "open_right_state",
        "open_state",
        "pm10",
        "pm1_0",
        "pm2_5",
        "power",
        "sensor_sensitive",
        "signal_strength",
        "smoke_state",
        "source",
        "tamper_alarm",
        "temp_unit_view",
        "temperature",
        "tvoc_float",
        "vacuum_cleaner_cleaning_type",
        "vacuum_cleaner_command",
        "vacuum_cleaner_program",
        "vacuum_cleaner_status",
        "voltage",
        "volume_int",
        "water_leak_state",
    }
)
"""Features that do carry device state, readable or writable.

The complement of :data:`COMMAND_ONLY_FEATURES` and
:data:`EVENT_ONLY_FEATURES` among the classified functions — these are
the only ones a state publish can legitimately be asked to contain."""
