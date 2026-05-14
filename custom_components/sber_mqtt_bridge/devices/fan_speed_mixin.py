"""FanSpeedMixin — shared Sber HVAC fan-speed logic.

Reused by :class:`HvacFanEntity` and :class:`HvacAirPurifierEntity`,
which both expose an HA fan platform via the Sber ``hvac_air_flow_power``
feature with the same set of speed enum values.
"""

from __future__ import annotations

import logging

_LOGGER = logging.getLogger(__name__)

SBER_SPEED_VALUES = ["auto", "high", "low", "medium", "quiet", "turbo"]
"""Allowed Sber ENUM values for hvac_air_flow_power (per Sber C2C spec)."""

_SBER_SPEED_TO_PERCENTAGE: dict[str, int] = {
    "quiet": 10,
    "low": 25,
    "medium": 50,
    "high": 75,
    "turbo": 100,
    "auto": 0,
}
"""Reverse mapping: Sber speed ENUM to HA percentage. 'auto' maps to 0 (turn_on)."""

_PERCENTAGE_TO_SPEED = [
    (0, "quiet"),
    (20, "low"),
    (40, "medium"),
    (67, "high"),
    (90, "turbo"),
]
"""Mapping thresholds from HA percentage to Sber speed ENUM."""


def _percentage_to_sber_speed(percentage: int) -> str:
    """Convert HA fan percentage (0-100) to Sber speed ENUM.

    Args:
        percentage: Fan speed percentage (0-100).

    Returns:
        Sber speed ENUM string.
    """
    for threshold, speed in reversed(_PERCENTAGE_TO_SPEED):
        if percentage >= threshold:
            return speed
    return "low"


class FanSpeedMixin:
    """Reusable Sber fan-speed helpers.

    Requires the host entity to expose:
    * ``self.preset_mode: str | None``
    * ``self.preset_modes: list[str]``
    * ``self.percentage: int | None``
    * ``self.entity_id: str``
    * ``self._build_service_call(domain, service, entity_id, data)`` from BaseEntity

    The mixin does not define its own state — it only delegates between
    Sber speed enum values and HA fan platform calls.
    """

    def _get_sber_speed(self) -> str | None:
        """Get current fan speed as Sber ENUM value.

        Uses preset_mode if it matches Sber values, otherwise converts
        percentage to a speed ENUM.

        Returns:
            Sber speed string or None if not determinable.
        """
        if self.preset_mode and self.preset_mode in SBER_SPEED_VALUES:
            return self.preset_mode
        if self.percentage is not None:
            return _percentage_to_sber_speed(self.percentage)
        return None

    def _cmd_fan_speed(self, speed: str | None) -> list[dict]:
        """Handle Sber fan speed ENUM → HA preset_mode or percentage."""
        if not speed:
            return []
        if speed in self.preset_modes:
            return [self._build_service_call("fan", "set_preset_mode", self.entity_id, {"preset_mode": speed})]
        pct = _SBER_SPEED_TO_PERCENTAGE.get(speed)
        if pct is None:
            return []
        if pct == 0:
            # 'auto' mode -- turn on without specific speed
            return [self._build_service_call("fan", "turn_on", self.entity_id)]
        return [self._build_service_call("fan", "set_percentage", self.entity_id, {"percentage": pct})]
