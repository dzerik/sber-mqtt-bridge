"""Sber Temperature Sensor entity -- maps HA temperature sensors to Sber sensor_temp."""

from __future__ import annotations

import contextlib
import logging
import math
from typing import ClassVar

from .._generated.reference_values import FEATURE_RANGES
from ..sber_constants import SberFeature
from ..sber_models import make_enum_value, make_integer_value, make_state
from .base_entity import ROLE_HUMIDITY, SENSOR_LINK_ROLES
from .simple_sensor import SimpleReadOnlySensor
from .utils.temperature import detect_temp_unit, to_celsius

_LOGGER = logging.getLogger(__name__)

SENSOR_TEMP_CATEGORY = "sensor_temp"
"""Sber device category for temperature sensor entities."""

SENSOR_TEMP_OPTION_TEMP_UNIT_VIEW = "temp_unit_view"
"""Per-entity option key toggling the ``temp_unit_view`` feature."""

PRESSURE_TO_MMHG: dict[str, float] = {
    # Sber's own unit — nothing to do.
    "mmhg": 1.0,
    "mm hg": 1.0,
    "torr": 1.0,
    "мм рт. ст.": 1.0,
    "мм рт.ст.": 1.0,
    "ммрт.ст.": 1.0,
    # Metric units HA integrations actually emit.
    "hpa": 0.750062,
    "mbar": 0.750062,
    "millibar": 0.750062,
    "pa": 0.00750062,
    "kpa": 7.50062,
    "bar": 750.062,
    # Imperial, for completeness (US weather integrations).
    "inhg": 25.4,
    "psi": 51.7149,
}
"""Multipliers converting one HA pressure unit into millimetres of mercury.

Sber's ``air_pressure`` is documented as ``INTEGER(200, 800)`` **in
millimetres of mercury**
(https://developers.sber.ru/docs/ru/smarthome/c2c/air_pressure), while
every common HA source (zigbee2mqtt BME280, ESPHome, weather platforms)
reports hectopascals.  Passing those through unconverted shipped ``1013``
— outside Sber's range by 27 % — as a real reading.
"""

_HPA_HEURISTIC_RANGE: tuple[float, float] = (801.0, 1200.0)
"""Magnitude window in which an *unlabelled* pressure is read as hPa.

Attributes rarely carry a unit: a HA temperature sensor's own
``unit_of_measurement`` is ``°C``, and the ``pressure`` attribute it
piggybacks usually names no unit at all.  The window starts one unit
above Sber's mmHg maximum, so nothing that could have been a valid mmHg
reading is ever reinterpreted; its top covers sea-level hectopascals with
margin.  Outside it the value is passed through untouched rather than
guessed at.
"""


def _pressure_unit(attrs: dict) -> str | None:
    """Return the pressure unit named by HA attributes, if it is a known one.

    ``pressure_unit`` (weather platforms) wins over
    ``unit_of_measurement`` (a plain pressure sensor).  Unknown strings —
    including the ``°C`` / ``°F`` that a *temperature* sensor carries in
    ``unit_of_measurement`` — yield ``None``, so a temperature unit can
    never be mistaken for a pressure one.

    Args:
        attrs: HA state attributes.

    Returns:
        A key of :data:`PRESSURE_TO_MMHG`, or ``None``.
    """
    raw = attrs.get("pressure_unit") or attrs.get("unit_of_measurement")
    if raw is None:
        return None
    unit = str(raw).replace("\xa0", " ").strip().lower()
    return unit if unit in PRESSURE_TO_MMHG else None


def _to_mmhg(raw: object, attrs: dict) -> int | None:
    """Convert an HA pressure reading into the mmHg integer Sber expects.

    Args:
        raw: Raw value of the ``pressure`` attribute.
        attrs: The full attribute dict, inspected for the unit.

    Returns:
        Pressure in millimetres of mercury, clamped to the documented
        ``air_pressure`` range, or ``None`` when the value cannot be read.
    """
    try:
        value = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value):
        return None
    unit = _pressure_unit(attrs)
    if unit is not None:
        value *= PRESSURE_TO_MMHG[unit]
    elif _HPA_HEURISTIC_RANGE[0] <= value <= _HPA_HEURISTIC_RANGE[1]:
        value *= PRESSURE_TO_MMHG["hpa"]
    low, high = FEATURE_RANGES["air_pressure"]
    return int(max(low, min(high, round(value))))


class SensorTempEntity(SimpleReadOnlySensor):
    """Sber temperature sensor entity.

    Reports temperature readings from HA sensor entities to the Sber cloud.
    Temperature is transmitted as an integer value multiplied by 10
    (e.g. 22.5 C becomes 225).
    """

    LINKABLE_ROLES = (*SENSOR_LINK_ROLES, ROLE_HUMIDITY)

    ENTITY_OPTION_KEYS: ClassVar[tuple[str, ...]] = (SENSOR_TEMP_OPTION_TEMP_UNIT_VIEW,)
    ENTITY_OPTIONS_BLOCK: ClassVar[str] = "sensor_temp_options"
    """Own block name — the base ``entity_options`` is generic.

    Two categories sharing one block key would make the panel render the
    form of the first one for the second (the key in ``device_detail`` is
    the same, the fields inside are foreign)."""

    _sber_value_key = "temperature"
    _sber_value_type = "INTEGER"

    def __init__(self, entity_data: dict) -> None:
        """Initialize temperature sensor entity.

        Args:
            entity_data: HA entity registry dict containing entity metadata.
        """
        super().__init__(SENSOR_TEMP_CATEGORY, entity_data)
        self.temperature = 0.0
        self._air_pressure: int | None = None
        self._linked_humidity: int | None = None
        self._temp_unit: str = "c"
        self._temp_unit_view: bool = True

    # -- user options -------------------------------------------------

    def apply_entity_options(self, options: dict) -> None:
        """Apply per-entity options from ``entry.options``.

        Args:
            options: Mapping with an optional ``temp_unit_view`` (bool)
                key.  Unknown keys and non-boolean values are ignored so
                a hand-edited config cannot break entity loading.
        """
        super().apply_entity_options(options)
        if not options:
            return
        enabled = options.get(SENSOR_TEMP_OPTION_TEMP_UNIT_VIEW)
        if isinstance(enabled, bool):
            self._temp_unit_view = enabled

    def validate_entity_options(self, options: dict) -> None:
        """Reject anything but a boolean for ``temp_unit_view``.

        Args:
            options: Mapping submitted by the panel.

        Raises:
            ValueError: With a human-readable message when the mapping
                carries an unknown key or a non-boolean value.
        """
        super().validate_entity_options(options)
        if SENSOR_TEMP_OPTION_TEMP_UNIT_VIEW in options and not isinstance(
            options[SENSOR_TEMP_OPTION_TEMP_UNIT_VIEW], bool
        ):
            raise ValueError(f"{self.entity_id}: {SENSOR_TEMP_OPTION_TEMP_UNIT_VIEW} must be true or false")

    def entity_options_state(self) -> dict[str, object]:
        """Return the option block rendered by the panel.

        Returns:
            The current ``temp_unit_view`` flag.
        """
        return {SENSOR_TEMP_OPTION_TEMP_UNIT_VIEW: self._temp_unit_view}

    def fill_by_ha_state(self, ha_state: dict) -> None:
        """Parse HA state and update temperature and air pressure values.

        When the HA sensor reports Fahrenheit (``unit_of_measurement == "°F"``),
        the incoming value is converted to Celsius before storage. Sber's
        ``temperature`` feature is always transmitted as ``°C × 10`` on the
        wire (see
        https://developers.sber.ru/docs/ru/smarthome/c2c/temperature —
        "The 'integer_value' should be set to the temperature multiplied
        by 10 (e.g., 220 for 22 degrees Celsius)"); ``temp_unit_view`` is
        a display-only hint. Without conversion, ``72°F`` would ship as
        ``720`` and be decoded as ``72°C``.

        The ``pressure`` attribute goes through :func:`_to_mmhg`, because
        Sber's ``air_pressure`` is millimetres of mercury while HA sources
        overwhelmingly report hectopascals.

        Args:
            ha_state: HA state dict with 'state' containing the temperature reading.
                Attributes may include 'pressure' for air pressure.
        """
        super().fill_by_ha_state(ha_state)
        try:
            temp = float(ha_state.get("state", 0))
            self.temperature = temp if math.isfinite(temp) else 0.0
        except (ValueError, TypeError):
            self.temperature = 0.0
        attrs = ha_state.get("attributes", {})
        # Unit detection + °F→°C share one implementation with
        # SensorAirEntity (devices/utils/temperature.py) so the two
        # categories that emit ``temperature`` cannot drift apart.
        self._temp_unit = detect_temp_unit(attrs)
        self.temperature = to_celsius(self.temperature, self._temp_unit)
        pressure = attrs.get("pressure")
        self._air_pressure = _to_mmhg(pressure, attrs) if pressure is not None else None

    def update_linked_data(self, role: str, ha_state: dict) -> None:
        """Inject data from a linked entity (humidity, battery, signal).

        Args:
            role: Link role name.
            ha_state: HA state dict.
        """
        super().update_linked_data(role, ha_state)
        if role == "humidity":
            state_val = ha_state.get("state")
            if state_val not in (None, "unknown", "unavailable"):
                with contextlib.suppress(TypeError, ValueError):
                    self._linked_humidity = round(float(state_val))

    def _create_features_list(self) -> list[str]:
        """Return Sber feature list including humidity and air_pressure when available.

        ``temp_unit_view`` is documented for "датчиков с экраном, которые
        умеют показывать температуру в разных температурных шкалах"
        (https://developers.sber.ru/docs/ru/smarthome/c2c/temp_unit_view),
        which a headless HA sensor is not.  It stays on by default anyway:
        dropping a feature changes the capability digest inside
        ``model.id``, and the cloud then re-registers the device and
        forgets its room (issue #44).  Users who want the strictly minimal
        descriptor turn it off per entity — see
        :attr:`ENTITY_OPTION_KEYS`.

        Returns:
            List of Sber feature strings supported by this entity.
        """
        features = super()._create_features_list()
        if self._temp_unit_view:
            features.append("temp_unit_view")
        if self._linked_humidity is not None:
            features.append("humidity")
        if self._air_pressure is not None:
            features.append("air_pressure")
        return features

    def _build_current_state(self) -> dict[str, dict]:
        """Build Sber current state payload with linked humidity and air_pressure.

        Returns:
            Dict mapping entity_id to its Sber state representation.
        """
        result = super()._build_current_state()
        if self._temp_unit_view:
            result[self.entity_id]["states"].append(
                make_state(SberFeature.TEMP_UNIT_VIEW, make_enum_value(self._temp_unit))
            )
        if self._linked_humidity is not None:
            result[self.entity_id]["states"].append(
                make_state(SberFeature.HUMIDITY, make_integer_value(self._linked_humidity))
            )
        if self._air_pressure is not None:
            result[self.entity_id]["states"].append(
                make_state(SberFeature.AIR_PRESSURE, make_integer_value(self._air_pressure))
            )
        return result

    def _get_sber_value(self) -> int:
        """Return temperature as integer scaled by 10."""
        return int(self.temperature * 10)
