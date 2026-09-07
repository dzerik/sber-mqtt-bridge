"""Keep numbers and ``allowed_values`` bounds inside the ranges Sber documents.

Sber states a numeric range on every function page ("Тип данных:
INTEGER(5, 50)"), and the ``allowed_values`` page states what a model may
do with it: «диапазон можно только сократить, а шаг можно установить
любой».  Home Assistant knows nothing about either — a thermostat happily
reports ``max_temp`` 75, a water heater ``min_temp`` 0 — so every place
that turns an HA capability into a Sber declaration, or an HA reading into
a Sber value, has to intersect the two.

Doing that intersection per device class is how the same defect appeared
in five of them at once, so it lives here instead:

* :func:`documented_bounds` — the range a category may declare;
* :func:`narrowed_bounds` — «возможности HA ∩ документированный диапазон»;
* :func:`documented_integer_bounds` — the same, rounded inwards to whole
  numbers for an INTEGER ``allowed_values`` block;
* :func:`clamp_to_bounds` — one published number pulled into a range.

The bounds themselves are never re-typed here.  They come from
:func:`~..schema_validator._documented_bounds`, the helper the validator
judges live publishes by, which reads the scraped
:data:`~.._generated.reference_values.FEATURE_RANGES` and applies the one
documented exception — a category whose own reference model is wider than
the function page (``hvac_boiler`` declaring 25…80 °C for a function page
that says 5…50).  Importing it, rather than copying it, is the whole
point: a clamp that disagreed with the validator would produce devices
the bridge itself reports as broken.
"""

from __future__ import annotations

import math

from ...schema_validator import _documented_bounds

__all__ = [
    "clamp_to_bounds",
    "documented_bounds",
    "documented_integer_bounds",
    "narrowed_bounds",
]


def documented_bounds(category: str | None, key: str) -> tuple[float, float] | None:
    """Return the widest range a model of ``category`` may declare for ``key``.

    Thin public alias for the validator's own helper — see the module
    docstring for why the two must not drift apart.

    Args:
        category: Sber category the model is published under.
        key: Sber feature name.

    Returns:
        ``(min, max)`` inclusive, or ``None`` when Sber documents no range
        for this feature.  ``None`` means *unknown*, never *nothing
        allowed*: callers must publish the value unchanged.
    """
    return _documented_bounds(category, key)


def clamp_to_bounds(value: float, bounds: tuple[float, float] | None) -> float:
    """Pull a single number into ``bounds``.

    Args:
        value: Number about to be published.
        bounds: Inclusive range, or ``None`` to leave the value alone.

    Returns:
        ``value`` clamped into the range; unchanged when ``bounds`` is
        ``None`` or the value is not finite (a NaN cannot be clamped, and
        turning it into a bound would invent a reading).
    """
    if bounds is None or not math.isfinite(value):
        return value
    low, high = bounds
    return max(low, min(high, value))


def narrowed_bounds(category: str | None, key: str, low: float, high: float) -> tuple[float, float]:
    """Intersect what HA can do with what Sber documents.

    Args:
        category: Sber category the model is published under.
        key: Sber feature name.
        low: Lower bound the HA entity reports.
        high: Upper bound the HA entity reports.

    Returns:
        The intersection of ``[low, high]`` with the documented range.
        When Sber documents no range, the HA bounds pass through
        untouched.  When the two do not overlap at all — an HA entity
        reporting ``0…0`` because it has no setpoint support, or a
        Fahrenheit-scale range — the documented range is returned whole:
        declaring nothing is still a legal declaration, whereas a
        collapsed ``5…5`` would leave the user a slider that cannot move.
    """
    bounds = documented_bounds(category, key)
    if bounds is None:
        return low, high
    lower = max(low, bounds[0])
    upper = min(high, bounds[1])
    if lower > upper:
        return bounds
    return lower, upper


def documented_integer_bounds(category: str | None, key: str, low: float, high: float) -> tuple[int, int]:
    """Return :func:`narrowed_bounds` rounded inwards to whole numbers.

    An INTEGER ``allowed_values`` block carries whole numbers, and
    rounding the wrong way would widen the very range this module exists
    to narrow — so the lower bound rounds up and the upper bound rounds
    down.

    Args:
        category: Sber category the model is published under.
        key: Sber feature name.
        low: Lower bound the HA entity reports.
        high: Upper bound the HA entity reports.

    Returns:
        ``(min, max)`` as integers, both inside the documented range.
        Should rounding inwards collapse the range (an HA span narrower
        than one degree), the documented range is used instead — same
        reasoning as in :func:`narrowed_bounds`.
    """
    lower, upper = narrowed_bounds(category, key, low, high)
    lower_int, upper_int = math.ceil(lower), math.floor(upper)
    if lower_int <= upper_int:
        return lower_int, upper_int
    bounds = documented_bounds(category, key)
    if bounds is None:
        return round(low), round(high)
    return math.ceil(bounds[0]), math.floor(bounds[1])
