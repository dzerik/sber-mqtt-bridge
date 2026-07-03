"""Sber Air Quality Sensor entity — maps HA air-quality sensors to Sber sensor_air.

Sber category ``sensor_air`` accepts a bundle of measurements from one
physical device: temperature, humidity, CO2, PM1/2.5/10, TVOC, HCHO.
Any subset is valid — spec marks all 8 measurement features as
conditional (``✔︎*``, "at least one of these").

Наследует от :class:`BaseEntity` напрямую (не от
:class:`~.simple_sensor.SimpleReadOnlySensor`), потому что у
``sensor_air`` нет одной primary-фичи — восемь measurement полей
равноправны и все conditional по спеку Sber. Primary HA entity —
просто «главный» sensor, который пользователь выбрал в wizard; его
``device_class`` определяет, в какое поле пойдёт state. Остальные
семь полей заполняются через linked companion entities
(``update_linked_data``).
"""

from __future__ import annotations

import logging
import math

from ..sber_constants import SberFeature
from ..sber_models import make_bool_value, make_enum_value, make_integer_value, make_state
from .base_entity import (
    ROLE_CO2,
    ROLE_HCHO,
    ROLE_HUMIDITY,
    ROLE_PM1,
    ROLE_PM10,
    ROLE_PM25,
    ROLE_TEMPERATURE,
    ROLE_TVOC,
    SENSOR_LINK_ROLES,
    BaseEntity,
)
from .battery_signal_mixin import BatteryAndSignalLinkMixin

_LOGGER = logging.getLogger(__name__)

SENSOR_AIR_CATEGORY = "sensor_air"
"""Sber device category for the air-quality sensor entity."""


def _fahrenheit_to_celsius(value: float) -> float:
    """Convert Fahrenheit to Celsius.

    Sber's ``temperature`` feature is always transmitted as
    ``°C × 10`` on the wire (see
    https://developers.sber.ru/docs/ru/smarthome/c2c/temperature —
    "The 'integer_value' should be set to the temperature multiplied
    by 10 (e.g., 220 for 22 degrees Celsius)"). ``temp_unit_view`` is
    a display-only hint on the device screen and does NOT reinterpret
    the numeric value. HA sensors that report Fahrenheit therefore need
    an explicit °F→°C conversion before scaling, otherwise a value like
    ``72°F`` becomes ``720`` on the wire and Sber decodes it as
    ``72.0°C`` (a ~50°C misread).

    Args:
        value: Fahrenheit temperature.

    Returns:
        Celsius temperature.
    """
    return (value - 32.0) * 5.0 / 9.0

# Map: HA device_class -> (internal field, parser). Used to route the
# primary HA state (fill_by_ha_state) into the matching measurement field.
_DEVICE_CLASS_ROUTING: dict[str, tuple[str, type]] = {
    "carbon_dioxide": ("_co2", int),
    "pm1": ("_pm1", int),
    "pm25": ("_pm25", int),
    "pm10": ("_pm10", int),
    "volatile_organic_compounds": ("_tvoc", float),
    "volatile_organic_compounds_parts": ("_hcho", float),
    "temperature": ("_temperature", float),
    "humidity": ("_humidity", int),
}

# Map: linked role name -> (internal field, parser). Used by
# update_linked_data to route a companion HA sensor's state into the
# matching measurement field.
_ROLE_ROUTING: dict[str, tuple[str, type]] = {
    "co2": ("_co2", int),
    "pm1": ("_pm1", int),
    "pm25": ("_pm25", int),
    "pm10": ("_pm10", int),
    "tvoc": ("_tvoc", float),
    "hcho": ("_hcho", float),
    "humidity": ("_humidity", int),
    "temperature": ("_temperature", float),
}


def _parse_state(raw: str | None, parser: type) -> object | None:
    """Return ``parser(raw)``, or ``None`` if raw is missing/unavailable/unparseable.

    Args:
        raw: Raw HA state string (e.g. ``"22.5"``, ``"unknown"``).
        parser: Either ``int`` or ``float`` — applied via an intermediate
            ``float()`` conversion so strings like ``"12.4"`` parse
            cleanly into an ``int`` field (truncating, not rounding).

    Returns:
        The parsed value, or ``None`` when the input can't be used.
    """
    if raw in (None, "unknown", "unavailable", ""):
        return None
    try:
        as_float = float(raw)
    except (TypeError, ValueError):
        return None
    # Reject non-finite values BEFORE calling the parser: ``int(inf)``
    # raises ``OverflowError`` (not caught by ValueError below) and
    # ``round(nan * 10)`` blows up further down the emit path.
    if not math.isfinite(as_float):
        return None
    try:
        return parser(as_float)
    except (TypeError, ValueError, OverflowError):
        return None


def _make_float_value(value: float) -> dict:
    """Create a Sber FLOAT value dict.

    ``sber_models`` only ships ``make_bool_value`` / ``make_integer_value``
    / ``make_enum_value`` / ``make_colour_value`` helpers — there is no
    ``make_float_value`` even though the Sber protocol's ``SberValue``
    model supports a ``FLOAT`` type with a ``float_value`` field (used by
    ``tvoc_float`` / ``hcho_float``). Kept local to this module rather
    than added to ``sber_models.py`` to keep this task's footprint
    scoped to the ``sensor_air`` device class.

    Args:
        value: Float value.

    Returns:
        Dict ready for inclusion in a Sber state payload.
    """
    return {"type": "FLOAT", "float_value": value}


class SensorAirEntity(BatteryAndSignalLinkMixin, BaseEntity):
    """Sber air-quality sensor: bundles up to eight measurements per device.

    Sber category: ``sensor_air``.

    Supported (all conditional, ``✔︎*`` — any non-empty subset is valid
    per spec):

    * ``co2`` — CO2 concentration, INTEGER (ppm).
    * ``pm1_0`` / ``pm2_5`` / ``pm10`` — particulate matter, INTEGER (µg/m3).
    * ``tvoc_float`` / ``hcho_float`` — FLOAT (mg/m3).
    * ``temperature`` — INTEGER = °C x 10 (matches ``SensorTempEntity``).
    * ``humidity`` — INTEGER (%).

    Plus the standard ``online`` / ``battery_percentage`` /
    ``battery_low_power`` / ``signal_strength`` features shared with all
    other sensor classes via :class:`BatteryAndSignalLinkMixin`.

    The "primary" HA entity picked in the wizard fills whichever field
    matches its ``device_class``; the remaining fields are populated by
    linked companion sensors through :meth:`update_linked_data`.
    """

    LINKABLE_ROLES = (
        *SENSOR_LINK_ROLES,
        ROLE_CO2,
        ROLE_PM1,
        ROLE_PM25,
        ROLE_PM10,
        ROLE_TVOC,
        ROLE_HCHO,
        ROLE_TEMPERATURE,
        ROLE_HUMIDITY,
    )

    def __init__(self, entity_data: dict) -> None:
        """Initialize the air-quality sensor entity.

        Args:
            entity_data: HA entity registry dict containing entity metadata.
        """
        super().__init__(SENSOR_AIR_CATEGORY, entity_data)
        self._co2: int | None = None
        self._pm1: int | None = None
        self._pm25: int | None = None
        self._pm10: int | None = None
        self._tvoc: float | None = None
        self._hcho: float | None = None
        self._temperature: float | None = None
        self._humidity: int | None = None
        self._temp_unit: str = "c"

    def fill_by_ha_state(self, ha_state: dict) -> None:
        """Route the primary HA sensor's state into the field matching its
        device_class.

        Sensors with an unhandled device_class are ignored — the wizard
        should never wire such a sensor as primary, but if someone does
        we degrade gracefully instead of guessing.

        Args:
            ha_state: HA state dict with ``state`` and ``attributes`` keys.
        """
        super().fill_by_ha_state(ha_state)
        attrs = ha_state.get("attributes") or {}
        device_class = attrs.get("device_class")
        routing = _DEVICE_CLASS_ROUTING.get(device_class)
        if routing is None:
            _LOGGER.debug(
                "sensor_air %s: primary HA device_class %r has no measurement mapping",
                self.entity_id,
                device_class,
            )
            return
        field, parser = routing
        value = _parse_state(ha_state.get("state"), parser)
        # Track temperature unit for temp_unit_view emission + Fahrenheit conversion.
        if device_class == "temperature":
            unit = attrs.get("unit_of_measurement", "")
            self._temp_unit = "f" if unit == "°F" else "c"
            if value is not None and self._temp_unit == "f":
                # Sber wire spec is °C × 10; convert before storing.
                value = _fahrenheit_to_celsius(float(value))
        setattr(self, field, value)

    def update_linked_data(self, role: str, ha_state: dict) -> None:
        """Fill a specific measurement (or battery/signal) from a linked HA sensor.

        Args:
            role: Link role name (e.g. ``"co2"``, ``"battery"``).
            ha_state: HA state dict of the linked entity.
        """
        super().update_linked_data(role, ha_state)
        routing = _ROLE_ROUTING.get(role)
        if routing is None:
            return
        field, parser = routing
        value = _parse_state(ha_state.get("state"), parser)
        # Track temperature unit for temp_unit_view emission + Fahrenheit conversion.
        if role == "temperature":
            attrs = ha_state.get("attributes") or {}
            unit = attrs.get("unit_of_measurement", "")
            self._temp_unit = "f" if unit == "°F" else "c"
            if value is not None and self._temp_unit == "f":
                # Sber wire spec is °C × 10; convert before storing.
                value = _fahrenheit_to_celsius(float(value))
        setattr(self, field, value)

    def _create_features_list(self) -> list[str]:
        """Return Sber feature list including populated measurements and battery/signal.

        Returns:
            List of Sber feature strings supported by this entity instance.
        """
        features = super()._create_features_list()
        if self._co2 is not None:
            features.append("co2")
        if self._pm1 is not None:
            features.append("pm1_0")
        if self._pm25 is not None:
            features.append("pm2_5")
        if self._pm10 is not None:
            features.append("pm10")
        if self._tvoc is not None:
            features.append("tvoc_float")
        if self._hcho is not None:
            features.append("hcho_float")
        if self._temperature is not None:
            features.append("temperature")
            features.append("temp_unit_view")
        if self._humidity is not None:
            features.append("humidity")
        self._append_battery_signal_features(features)
        return features

    def to_sber_current_state(self) -> dict[str, dict]:
        """Build Sber current state payload.

        Emits ``online`` unconditionally + one state entry per populated
        measurement + battery/signal when linked. Nothing else — the
        eight measurement features are conditional (``✔︎*``) per Sber
        spec, missing ones are fine.

        Numeric measurements are clamped to physically-reasonable
        ranges at emit time so a broken HA sensor (negative CO2, PM
        readings in the thousands, humidity > 100 %) cannot poison
        the Sber payload and trigger a silent rejection of the whole
        device. This mirrors the clamp
        :class:`~.humidifier.HumidifierEntity` applies to
        ``water_level``.

        Returns:
            Dict mapping entity_id to its Sber state representation.
        """
        states: list[dict] = [make_state(SberFeature.ONLINE, make_bool_value(self._is_online))]

        if self._co2 is not None:
            states.append(
                make_state(SberFeature.CO2, make_integer_value(max(0, min(5000, self._co2))))
            )
        if self._pm1 is not None:
            states.append(
                make_state(SberFeature.PM1_0, make_integer_value(max(0, min(999, self._pm1))))
            )
        if self._pm25 is not None:
            states.append(
                make_state(SberFeature.PM2_5, make_integer_value(max(0, min(999, self._pm25))))
            )
        if self._pm10 is not None:
            states.append(
                make_state(SberFeature.PM10, make_integer_value(max(0, min(999, self._pm10))))
            )
        if self._tvoc is not None:
            states.append(
                make_state(SberFeature.TVOC_FLOAT, _make_float_value(max(0.0, self._tvoc)))
            )
        if self._hcho is not None:
            states.append(
                make_state(SberFeature.HCHO_FLOAT, _make_float_value(max(0.0, self._hcho)))
            )
        if self._temperature is not None:
            # Sber wire spec: temperature is INTEGER = °C x 10 (same
            # convention as SensorTempEntity).
            states.append(
                make_state(
                    SberFeature.TEMPERATURE,
                    make_integer_value(round(self._temperature * 10)),
                )
            )
            states.append(
                make_state(SberFeature.TEMP_UNIT_VIEW, make_enum_value(self._temp_unit))
            )
        if self._humidity is not None:
            states.append(
                make_state(
                    SberFeature.HUMIDITY,
                    make_integer_value(max(0, min(100, self._humidity))),
                )
            )

        self._append_battery_signal_states(states)

        return {self.entity_id: {"states": states}}
