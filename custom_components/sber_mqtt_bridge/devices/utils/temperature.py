"""Shared HA → Sber temperature normalization.

Sber's ``temperature`` feature is always transmitted as ``°C × 10`` on
the wire (see https://developers.sber.ru/docs/ru/smarthome/c2c/temperature
— "The 'integer_value' should be set to the temperature multiplied by 10
(e.g., 220 for 22 degrees Celsius)").  ``temp_unit_view`` is a
display-only hint on the device screen and does NOT reinterpret the
numeric value: an HA sensor reporting Fahrenheit must be converted to
Celsius *before* scaling, otherwise ``72°F`` ships as ``720`` and Sber
decodes it as ``72.0°C`` (a ~50°C misread).

Two device classes emit ``temperature`` + ``temp_unit_view``
(:class:`~..sensor_temp.SensorTempEntity` and
:class:`~..sensor_air.SensorAirEntity`, the latter through two ingestion
paths).  The unit-detection rule and the conversion live here so
changing them stays a single edit.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

FAHRENHEIT_UNIT = "°F"
"""HA ``unit_of_measurement`` string that triggers the °F → °C conversion."""

UNIT_FAHRENHEIT = "f"
"""Sber ``temp_unit_view`` ENUM value for Fahrenheit display."""

UNIT_CELSIUS = "c"
"""Sber ``temp_unit_view`` ENUM value for Celsius display."""


def detect_temp_unit(attributes: Mapping[str, Any] | None) -> str:
    """Derive the Sber ``temp_unit_view`` value from HA attributes.

    Args:
        attributes: HA state attributes (may be ``None`` / empty).

    Returns:
        :data:`UNIT_FAHRENHEIT` when the HA sensor reports ``°F``,
        :data:`UNIT_CELSIUS` otherwise (including a missing unit — Sber
        devices default to Celsius display).
    """
    unit = (attributes or {}).get("unit_of_measurement", "")
    return UNIT_FAHRENHEIT if unit == FAHRENHEIT_UNIT else UNIT_CELSIUS


def to_celsius(value: float, unit: str) -> float:
    """Convert a reading to Celsius for the Sber wire format.

    Args:
        value: Numeric reading as published by HA.
        unit: Unit marker from :func:`detect_temp_unit`.

    Returns:
        ``value`` converted from Fahrenheit when ``unit`` is
        :data:`UNIT_FAHRENHEIT`, otherwise ``value`` unchanged.
    """
    if unit != UNIT_FAHRENHEIT:
        return value
    return (value - 32.0) * 5.0 / 9.0
