"""Typed constants for Sber Smart Home C2C protocol.

Provides StrEnum classes for Sber feature keys, value types, MQTT topic
suffixes, and HA state strings. Eliminates raw string literals throughout
the codebase, enabling IDE autocomplete and compile-time typo detection.
"""

from __future__ import annotations

from enum import StrEnum


class SberValueType(StrEnum):
    """Sber C2C protocol value types used in state and command payloads."""

    BOOL = "BOOL"
    INTEGER = "INTEGER"
    ENUM = "ENUM"
    COLOUR = "COLOUR"
    FLOAT = "FLOAT"


class SberFeature(StrEnum):
    """Sber C2C feature key names used in device models and state payloads.

    Each value corresponds to a feature in the Sber Smart Home protocol.
    See https://developers.sber.ru/docs/ru/smarthome/c2c/ for reference.
    """

    # Common
    ONLINE = "online"
    ON_OFF = "on_off"

    # Light
    LIGHT_BRIGHTNESS = "light_brightness"
    LIGHT_COLOUR = "light_colour"
    LIGHT_COLOUR_TEMP = "light_colour_temp"
    LIGHT_MODE = "light_mode"

    # Climate / HVAC
    TEMPERATURE = "temperature"
    HVAC_TEMP_SET = "hvac_temp_set"
    HVAC_WORK_MODE = "hvac_work_mode"
    HVAC_THERMOSTAT_MODE = "hvac_thermostat_mode"
    HVAC_AIR_FLOW_POWER = "hvac_air_flow_power"
    HVAC_AIR_FLOW_DIRECTION = "hvac_air_flow_direction"
    HVAC_HUMIDITY_SET = "hvac_humidity_set"
    HVAC_NIGHT_MODE = "hvac_night_mode"
    HVAC_IONIZATION = "hvac_ionization"
    HVAC_AROMATIZATION = "hvac_aromatization"
    HVAC_REPLACE_FILTER = "hvac_replace_filter"
    HVAC_REPLACE_IONIZATOR = "hvac_replace_ionizator"
    HVAC_DECONTAMINATE = "hvac_decontaminate"
    HVAC_WATER_LOW_LEVEL = "hvac_water_low_level"
    HVAC_WATER_PERCENTAGE = "hvac_water_percentage"
    HVAC_HEATING_RATE = "hvac_heating_rate"
    HUMIDITY = "humidity"

    # Cover / Curtain / Blind / Gate
    OPEN_PERCENTAGE = "open_percentage"
    OPEN_SET = "open_set"
    OPEN_STATE = "open_state"
    OPEN_RATE = "open_rate"
    OPEN_LEFT_PERCENTAGE = "open_left_percentage"
    OPEN_RIGHT_PERCENTAGE = "open_right_percentage"

    # Sensors
    AIR_PRESSURE = "air_pressure"
    PIR = "pir"
    DOORCONTACT_STATE = "doorcontact_state"
    WATER_LEAK_STATE = "water_leak_state"
    SMOKE_STATE = "smoke_state"
    GAS_LEAK_STATE = "gas_leak_state"
    TAMPER_ALARM = "tamper_alarm"
    ALARM_MUTE = "alarm_mute"
    SENSOR_SENSITIVE = "sensor_sensitive"
    TEMP_UNIT_VIEW = "temp_unit_view"

    # Battery / Signal
    BATTERY_PERCENTAGE = "battery_percentage"
    BATTERY_LOW_POWER = "battery_low_power"
    SIGNAL_STRENGTH = "signal_strength"

    # Energy monitoring
    POWER = "power"
    VOLTAGE = "voltage"
    CURRENT = "current"
    CHILD_LOCK = "child_lock"

    # Scenario button
    BUTTON_EVENT = "button_event"

    # TV / Media
    VOLUME_INT = "volume_int"
    MUTE = "mute"
    SOURCE = "source"
    CHANNEL_INT = "channel_int"

    # Kettle
    KITCHEN_WATER_TEMPERATURE = "kitchen_water_temperature"
    KITCHEN_WATER_TEMPERATURE_SET = "kitchen_water_temperature_set"
    KITCHEN_WATER_LEVEL = "kitchen_water_level"
    KITCHEN_WATER_LOW_LEVEL = "kitchen_water_low_level"

    # Vacuum
    VACUUM_CLEANER_COMMAND = "vacuum_cleaner_command"
    VACUUM_CLEANER_STATUS = "vacuum_cleaner_status"
    VACUUM_CLEANER_PROGRAM = "vacuum_cleaner_program"

    # Intercom
    INCOMING_CALL = "incoming_call"
    REJECT_CALL = "reject_call"
    UNLOCK = "unlock"


class HAState(StrEnum):
    """Home Assistant entity state string constants."""

    ON = "on"
    OFF = "off"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"
    OPEN = "open"
    CLOSED = "closed"
    OPENING = "opening"
    CLOSING = "closing"


class MqttTopicSuffix(StrEnum):
    """Sber MQTT topic suffixes for message routing."""

    COMMANDS = "commands"
    STATUS_REQUEST = "status_request"
    CONFIG_REQUEST = "config_request"
    ERRORS = "errors"
    CHANGE_GROUP = "change_group_device_request"
    RENAME_DEVICE = "rename_device_request"


# Service call constants
SERVICE_CALL_TYPE = "call_service"
"""Service call type identifier used in command results."""

SERVICE_TURN_ON = "turn_on"
"""HA service name for turning devices on."""

SERVICE_TURN_OFF = "turn_off"
"""HA service name for turning devices off."""

SERVICE_PRESS = "press"
"""HA service name for button press."""
