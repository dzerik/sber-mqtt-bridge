"""Color conversion utilities between Home Assistant and Sber HSV color spaces.

The Sber side of the mapping is **not** written out here: the bounds of
``colour_value`` come from
:data:`custom_components.sber_mqtt_bridge._generated.value_envelope.COLOUR_COMPONENT_RANGES`,
scraped from https://developers.sber.ru/docs/ru/smarthome/c2c/value.  A
retyped copy of those numbers would be a second source of truth that goes
stale silently — and a colour converter that has silently diverged from the
protocol shows up as lamps lighting the wrong colour, never as an error.
"""

from __future__ import annotations

from ..._generated.value_envelope import COLOUR_COMPONENT_RANGES

HA_HUE_RANGE: tuple[float, float] = (0.0, 360.0)
"""Home Assistant hue scale, in degrees (``hs_color[0]``)."""

HA_SATURATION_RANGE: tuple[float, float] = (0.0, 100.0)
"""Home Assistant saturation scale, in percent (``hs_color[1]``)."""

HA_BRIGHTNESS_RANGE: tuple[float, float] = (0.0, 255.0)
"""Home Assistant brightness scale (``brightness`` attribute)."""

SBER_HUE_RANGE: tuple[int, int] = COLOUR_COMPONENT_RANGES["h"]
"""Documented inclusive bounds of ``colour_value.h``."""

SBER_SATURATION_RANGE: tuple[int, int] = COLOUR_COMPONENT_RANGES["s"]
"""Documented inclusive bounds of ``colour_value.s``."""

SBER_VALUE_RANGE: tuple[int, int] = COLOUR_COMPONENT_RANGES["v"]
"""Documented inclusive bounds of ``colour_value.v``.

Its floor is **not** zero: Sber documents ``v`` as starting at 100, so
"brightness 0" on the HA side still has to be published as the documented
minimum rather than as a bare 0."""


def _clamp(value: float, bounds: tuple[float, float]) -> float:
    """Pull a value into an inclusive range.

    Args:
        value: Value to constrain.
        bounds: ``(low, high)`` inclusive bounds.

    Returns:
        ``value`` limited to ``bounds``.
    """
    low, high = bounds
    return max(low, min(high, value))


def _rescale(value: float, source: tuple[float, float], target: tuple[float, float]) -> float:
    """Map a value linearly from one inclusive range onto another.

    The value is clamped to ``source`` first, so the result can never leave
    ``target`` — a rounding step applied afterwards is the only remaining
    way out, and callers clamp again after rounding.

    Args:
        value: Value on the ``source`` scale.
        source: ``(low, high)`` bounds of the incoming scale.
        target: ``(low, high)`` bounds of the outgoing scale.

    Returns:
        The corresponding value on the ``target`` scale.
    """
    source_low, source_high = source
    target_low, target_high = target
    span = source_high - source_low
    if span <= 0:  # pragma: no cover — degenerate spec, guards a ZeroDivisionError
        return target_low
    ratio = (_clamp(value, source) - source_low) / span
    return target_low + ratio * (target_high - target_low)


class ColorConverter:
    """Bidirectional HSV color converter between HA and Sber color spaces.

    HA uses:
    - Hue: 0-360 degrees
    - Saturation: 0-100%
    - Brightness (Value): 0-255

    Sber uses the bounds documented for ``colour_value`` and re-exported
    here as :data:`SBER_HUE_RANGE`, :data:`SBER_SATURATION_RANGE` and
    :data:`SBER_VALUE_RANGE`.  At the time of writing those are 0-360,
    0-1000 and **100**-1000 respectively; the code reads them rather than
    repeating them, so a change upstream reaches the conversion instead of
    quietly contradicting it.
    """

    @staticmethod
    def ha_to_sber_hsv(
        ha_hue: float | None,
        ha_saturation: float | None,
        ha_brightness: float | None,
    ) -> tuple[int, int, int]:
        """Convert HA HSV color values to Sber HSV format.

        Each component is rescaled linearly from its HA scale onto the
        documented Sber scale and clamped again after rounding, so no input
        — including the very edges 0 and 255 — can produce a component
        outside the documented range.

        Args:
            ha_hue: Hue in degrees (0-360), or None for default 0.
            ha_saturation: Saturation percentage (0-100), or None for default 0.
            ha_brightness: Brightness value (0-255), or None for default 0.

        Returns:
            Tuple of (sber_hue, sber_saturation, sber_value) as integers,
            each inside its documented range.
        """
        hue = _rescale(ha_hue if ha_hue is not None else 0.0, HA_HUE_RANGE, SBER_HUE_RANGE)
        saturation = _rescale(
            ha_saturation if ha_saturation is not None else 0.0,
            HA_SATURATION_RANGE,
            SBER_SATURATION_RANGE,
        )
        value = _rescale(
            ha_brightness if ha_brightness is not None else 0.0,
            HA_BRIGHTNESS_RANGE,
            SBER_VALUE_RANGE,
        )

        return (
            int(_clamp(round(hue), SBER_HUE_RANGE)),
            int(_clamp(round(saturation), SBER_SATURATION_RANGE)),
            int(_clamp(round(value), SBER_VALUE_RANGE)),
        )

    @staticmethod
    def sber_to_ha_hsv(
        sber_hue: float | None,
        sber_saturation: float | None,
        sber_value: float | None,
    ) -> tuple[int, int, int]:
        """Convert Sber HSV color values to HA HSV format.

        The inverse mapping is deliberately more forgiving than the
        outgoing one: a ``v`` below the documented floor is not something
        we may publish, but if the cloud sends one anyway it is read as
        "fully dimmed" rather than rejected.

        Args:
            sber_hue: Hue in degrees, or None for default 0.
            sber_saturation: Saturation, or None for default 0.
            sber_value: Value/brightness, or None for default 0.

        Returns:
            Tuple of (ha_hue, ha_saturation, ha_brightness) as integers,
            each inside its HA scale.
        """
        hue = _rescale(sber_hue if sber_hue is not None else 0.0, SBER_HUE_RANGE, HA_HUE_RANGE)
        saturation = _rescale(
            sber_saturation if sber_saturation is not None else 0.0,
            SBER_SATURATION_RANGE,
            HA_SATURATION_RANGE,
        )
        # Values under the documented floor mean "off" rather than an error.
        raw_value = sber_value if sber_value is not None else 0.0
        brightness = _rescale(max(raw_value, float(SBER_VALUE_RANGE[0])), SBER_VALUE_RANGE, HA_BRIGHTNESS_RANGE)

        return (
            int(_clamp(round(hue), HA_HUE_RANGE)),
            int(_clamp(round(saturation), HA_SATURATION_RANGE)),
            int(_clamp(round(brightness), HA_BRIGHTNESS_RANGE)),
        )
