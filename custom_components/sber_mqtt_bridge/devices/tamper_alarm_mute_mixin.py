"""TamperAlarmMuteMixin -- shared ``tamper`` + ``alarm_mute`` parsing for binary sensors.

Used by door / motion / water-leak / smoke / gas sensors that the Sber
spec allows to report a tamper-detected flag and (for smoke / gas / water-leak)
an alarm-mute flag.
"""

from __future__ import annotations

from ..sber_constants import SberFeature
from ..sber_models import make_bool_value, make_state


class TamperAlarmMuteMixin:
    """Owns the optional ``_tamper`` and ``_alarm_mute`` fields for binary sensors.

    Subclasses opt into alarm_mute by setting the class attribute
    ``SUPPORTS_ALARM_MUTE = True``; tamper is always parsed (sensors
    without a physical tamper switch simply leave the field ``None``).

    Reset semantics: both fields are reset to ``None`` whenever the
    corresponding HA attribute is absent from a ``fill_by_ha_state`` call.
    This avoids stale state after the attribute disappears (e.g. entity
    reconfiguration).  All five sensors that use this mixin behave
    consistently regardless of the original per-class inconsistency.

    Host class must call ``super().__init__()`` so that the fields are
    initialised before any other code runs.
    """

    SUPPORTS_ALARM_MUTE: bool = False
    """Set to ``True`` in subclasses that expose an ``alarm_mute`` feature."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        """Initialise tamper and alarm_mute fields, then delegate to MRO.

        Args:
            *args: Positional arguments forwarded to the next class in MRO.
            **kwargs: Keyword arguments forwarded to the next class in MRO.
        """
        super().__init__(*args, **kwargs)
        self._tamper: bool | None = None
        self._alarm_mute: bool | None = None

    def _parse_tamper_alarm_mute(self, attrs: dict) -> None:
        """Parse ``tamper`` (always) and ``alarm_mute`` (when SUPPORTS_ALARM_MUTE).

        Both fields reset to ``None`` when the corresponding key is absent,
        preventing stale values from a previous ``fill_by_ha_state`` call.

        Args:
            attrs: HA entity attribute dict extracted from the HA state payload.
        """
        tamper = attrs.get("tamper")
        self._tamper = bool(tamper) if tamper is not None else None

        if self.SUPPORTS_ALARM_MUTE:
            alarm_mute = attrs.get("alarm_mute")
            self._alarm_mute = bool(alarm_mute) if alarm_mute is not None else None

    def _append_tamper_alarm_mute_features(self, features: list[str]) -> None:
        """Append tamper_alarm and alarm_mute feature strings when fields are set.

        Args:
            features: Mutable feature list to extend in-place.
        """
        if self._tamper is not None:
            features.append("tamper_alarm")
        if self.SUPPORTS_ALARM_MUTE and self._alarm_mute is not None:
            features.append("alarm_mute")

    def _append_tamper_alarm_mute_states(self, states: list) -> None:
        """Append tamper_alarm and alarm_mute Sber state dicts when fields are set.

        Args:
            states: Mutable Sber state list to extend in-place.
        """
        if self._tamper is not None:
            states.append(make_state(SberFeature.TAMPER_ALARM, make_bool_value(self._tamper)))
        if self.SUPPORTS_ALARM_MUTE and self._alarm_mute is not None:
            states.append(make_state(SberFeature.ALARM_MUTE, make_bool_value(self._alarm_mute)))
