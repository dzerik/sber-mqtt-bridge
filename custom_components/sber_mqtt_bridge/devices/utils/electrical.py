"""Shared HA → Sber normalization of power / voltage / current readings.

Sber names the unit of each electrical function directly on its function
page, and the three units are **not** the same ones Home Assistant hands
out:

* ``power`` — «Принимает значения от 0 до 50 000 ватт с шагом в 1 ватт»
  (https://developers.sber.ru/docs/ru/smarthome/c2c/power);
* ``voltage`` — «от 0 до 5000 вольт с шагом в 1 вольт»
  (https://developers.sber.ru/docs/ru/smarthome/c2c/voltage);
* ``current`` — «от 0 до 30 000 **миллиампер** с шагом в 1 миллиампер»
  (https://developers.sber.ru/docs/ru/smarthome/c2c/current, example
  ``"9000"`` = 9 A).

The last one is the trap this module exists for.  A Home Assistant
current *sensor* reports **amperes** (``0.65``), so publishing the raw
number as an integer ships ``0`` — the Sber app then shows a permanent
zero current, which looks like the whole energy-monitoring feature is
broken.  Power and voltage share HA's base unit, but a plug that reports
kilowatts (``0.12 kW``) or millivolts hits the same class of defect.

Two entry points, because the two sources say different things:

* :func:`to_sber_energy_value` — a linked companion sensor.  It carries a
  ``unit_of_measurement``, so its reading is converted from that unit
  into Sber's.
* :func:`to_sber_energy_attribute` — an attribute of the switch itself.
  It carries **no** unit, and the only integration known to populate
  these attributes (``localtuya``) puts the raw Tuya datapoint there:
  ``switch.py`` divides ``voltage`` and ``current_consumption`` by 10 to
  reach volts and watts, but passes ``current`` through untouched — and
  Tuya's ``cur_current`` datapoint is already in milliamperes.  So an
  attribute is taken to be in Sber's own unit and is only rounded and
  clamped.  Guessing "HA base unit" there would multiply a real 650 mA
  reading by 1000 and park it on the 30 000 mA ceiling forever.

Rather than re-typing conversion factors, the module leans on Home
Assistant's own converters (``PowerConverter``,
``ElectricPotentialConverter``, ``ElectricCurrentConverter``) keyed by
the sensor's ``unit_of_measurement``, and then clamps the result into the
range Sber documents through
:mod:`~.documented_range` — a value outside ``INTEGER(min, max)`` is a
reason for the cloud to reject the device silently.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

from homeassistant.const import (
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfPower,
)
from homeassistant.util.unit_conversion import (
    BaseUnitConverter,
    ElectricCurrentConverter,
    ElectricPotentialConverter,
    PowerConverter,
)

from .documented_range import clamp_to_bounds, documented_bounds

_LOGGER = logging.getLogger(__name__)

__all__ = ["ENERGY_FEATURES", "to_sber_energy_attribute", "to_sber_energy_value"]


@dataclass(frozen=True, slots=True)
class _EnergySpec:
    """How one Sber electrical function maps onto Home Assistant units.

    Attributes:
        converter: Home Assistant unit converter for this quantity.
        sber_unit: Unit Sber documents for the function's INTEGER value.
        ha_default_unit: Unit assumed when the HA sensor carries none —
            Home Assistant's base unit for the quantity (``W`` / ``V`` /
            ``A``), which is what an integration omitting the unit is
            overwhelmingly likely to mean.
    """

    converter: type[BaseUnitConverter]
    sber_unit: str
    ha_default_unit: str


ENERGY_FEATURES: dict[str, _EnergySpec] = {
    "power": _EnergySpec(PowerConverter, UnitOfPower.WATT, UnitOfPower.WATT),
    "voltage": _EnergySpec(
        ElectricPotentialConverter,
        UnitOfElectricPotential.VOLT,
        UnitOfElectricPotential.VOLT,
    ),
    "current": _EnergySpec(
        ElectricCurrentConverter,
        UnitOfElectricCurrent.MILLIAMPERE,
        UnitOfElectricCurrent.AMPERE,
    ),
}
"""Sber feature name → unit handling.  Doubles as the set of link roles
:class:`~..on_off_entity.OnOffEntity` routes into its energy fields, so the
role names and the Sber feature names cannot drift apart."""


def _parse_float(raw: object) -> float | None:
    """Return ``raw`` as a finite float, or ``None`` when unusable.

    Args:
        raw: HA state string (``"0.65"``), number, or one of the
            unavailability markers.

    Returns:
        The parsed value, or ``None`` for a missing / unavailable /
        unparseable / non-finite reading (``NaN`` from a template sensor
        that divided by zero must not become a published ``0``).
    """
    if raw is None or raw in (STATE_UNKNOWN, STATE_UNAVAILABLE, ""):
        return None
    try:
        value = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def to_sber_energy_value(
    feature: str,
    raw_state: object,
    unit: str | None = None,
    category: str | None = None,
) -> int | None:
    """Convert one HA electrical reading into the Sber integer value.

    Args:
        feature: Sber feature name — ``"power"``, ``"voltage"`` or
            ``"current"`` (also the link-role name).
        raw_state: Raw HA state of the sensor (string or number).
        unit: The sensor's ``unit_of_measurement``.  Missing (``None`` or
            empty) means the quantity's HA base unit (``W`` / ``V`` /
            ``A``); a unit that is not one of the quantity's units means
            the sensor measures something else and the reading is
            refused.
        category: Sber category the model is published under, used to
            pick the documented range to clamp into.

    Returns:
        The value in Sber's unit, rounded to a whole number and clamped
        into the documented range, or ``None`` when the reading is
        unusable, its unit belongs to another quantity, or ``feature`` is
        not an electrical one — in which case the caller must not declare
        the feature at all.
    """
    spec = ENERGY_FEATURES.get(feature)
    if spec is None:
        return None
    value = _parse_float(raw_state)
    if value is None:
        return None

    if not unit:
        from_unit = spec.ha_default_unit
    elif unit in spec.converter.VALID_UNITS:
        from_unit = unit
    else:
        # A unit outside the quantity's own VALID_UNITS is not a spelling
        # variant, it is a different quantity: an accumulated-energy
        # sensor (kWh) linked into the `power` role, say.  Guessing watts
        # there would publish kilowatt-hours as instantaneous power, and
        # the number would look entirely plausible.  Publishing nothing
        # leaves the feature undeclared, which is visibly "no data"
        # rather than invisibly wrong.
        _LOGGER.warning(
            "Linked sensor for Sber %s reports %r, which is not a unit of that quantity "
            "(expected one of %s) — the reading is ignored; link a sensor that measures %s",
            feature,
            unit,
            sorted(spec.converter.VALID_UNITS),
            feature,
        )
        return None
    converted = spec.converter.convert(value, from_unit, spec.sber_unit)
    return _finalize(feature, converted, category, spec.sber_unit)


def to_sber_energy_attribute(
    feature: str,
    raw_value: object,
    category: str | None = None,
) -> int | None:
    """Normalize a metering reading taken from the switch's own attributes.

    Unlike a linked sensor, an attribute carries no
    ``unit_of_measurement``, so there is nothing to convert *from* — and
    no licence to guess.  The one integration known to fill these
    attributes, ``localtuya``, already scales them into the units Sber
    documents (its ``switch.py`` divides ``voltage`` and
    ``current_consumption`` by 10, and leaves ``current`` as the raw
    Tuya datapoint, which is milliamperes).  The value is therefore
    treated as already being in Sber's unit and is only rounded and
    clamped.

    Assuming HA base units here instead would take a genuine ``650`` mA
    attribute to 650 000 mA, i.e. a permanent 30 A reading in the Sber
    app after clamping — a plausible-looking number that hides the bug.

    Args:
        feature: Sber feature name — ``"power"``, ``"voltage"`` or
            ``"current"``.
        raw_value: Attribute value as Home Assistant reports it.
        category: Sber category the model is published under, used to
            pick the documented range to clamp into.

    Returns:
        The whole-number value to publish, or ``None`` when the
        attribute is missing / unusable or ``feature`` is not an
        electrical one — the caller must then not declare the feature.
    """
    spec = ENERGY_FEATURES.get(feature)
    if spec is None:
        return None
    value = _parse_float(raw_value)
    if value is None:
        return None
    return _finalize(feature, value, category, spec.sber_unit)


def _finalize(feature: str, value: float, category: str | None, unit: str) -> int:
    """Clamp one converted reading into Sber's range and round it.

    Clamping is not silent: a value that hits a bound is
    indistinguishable from a real reading, so a unit mistake anywhere
    upstream would otherwise surface as a believable constant (a plug
    stuck at exactly 30 A) instead of anything a log could show.

    Rounding is :func:`round`, i.e. banker's rounding — ``2.5`` W
    becomes ``2`` W.  With a documented step of 1 W / 1 V / 1 mA the
    half-way case carries no meaning, so the tie rule is deliberately
    left as Python's default.

    Args:
        feature: Sber feature name, for the log line.
        value: Reading already expressed in Sber's unit.
        category: Sber category, used to look the documented range up.
        unit: Sber's unit for the feature, for the log line.

    Returns:
        The rounded, clamped value.
    """
    bounds = documented_bounds(category, feature)
    clamped = clamp_to_bounds(value, bounds)
    if clamped != value:
        _LOGGER.warning(
            "Sber %s reading %s %s is outside the documented range %s for category %r "
            "and was clamped to %s %s — check the source entity's unit",
            feature,
            value,
            unit,
            bounds,
            category,
            clamped,
            unit,
        )
    return round(clamped)
