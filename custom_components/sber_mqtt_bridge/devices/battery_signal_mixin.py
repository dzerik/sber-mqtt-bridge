"""BatteryAndSignalLinkMixin — shared battery + signal-strength handling.

Reused by entity classes that may accept linked sensors via the bridge
``LINKABLE_ROLES`` system: ``battery``, ``battery_low``,
``signal_strength``. The mixin owns the three state fields, the
``update_linked_data`` role dispatch, the feature contributions, and
the per-state output block.

Two ATTR_SPECS tuples are provided:

* :data:`BATTERY_SIGNAL_ATTR_SPECS` — for entities where primary-state
  refreshes should overwrite battery/signal values (curtain, valve).
* :data:`BATTERY_SIGNAL_ATTR_SPECS_PRESERVE` — same specs with
  ``preserve_on_missing=True``, for read-only sensors whose battery/
  signal is typically injected by linked companion entities and must not
  be clobbered on every primary state update.
"""

from __future__ import annotations

import contextlib
import logging

from ..sber_constants import SberFeature
from ..sber_models import make_bool_value, make_enum_value, make_integer_value, make_state
from .base_entity import AttrSpec, _safe_int_parser
from .utils.signal import rssi_to_signal_strength

_LOGGER = logging.getLogger(__name__)


BATTERY_SIGNAL_ATTR_SPECS: tuple[AttrSpec, ...] = (
    AttrSpec(
        field="_battery_level",
        attr_keys=("battery", "battery_level"),
        parser=_safe_int_parser,
    ),
    AttrSpec(
        field="_signal_strength_raw",
        attr_keys=("signal_strength", "rssi", "linkquality"),
        parser=_safe_int_parser,
    ),
)
"""ATTR_SPECS covering battery_level and signal_strength (no preserve_on_missing).

Use for entities such as :class:`~devices.curtain.CurtainEntity` and
:class:`~devices.valve.ValveEntity` where primary-state refreshes may
overwrite previously populated fields.

Concatenate with entity-specific specs::

    ATTR_SPECS: ClassVar[tuple[AttrSpec, ...]] = (
        *BATTERY_SIGNAL_ATTR_SPECS,
        AttrSpec(field="_tilt_position", attr_keys=("current_tilt_position",), parser=_safe_int_parser),
    )
"""

BATTERY_SIGNAL_ATTR_SPECS_PRESERVE: tuple[AttrSpec, ...] = (
    AttrSpec(
        field="_battery_level",
        attr_keys=("battery", "battery_level"),
        parser=_safe_int_parser,
        preserve_on_missing=True,
    ),
    AttrSpec(
        field="_signal_strength_raw",
        attr_keys=("signal_strength", "rssi", "linkquality"),
        parser=_safe_int_parser,
        preserve_on_missing=True,
    ),
)
"""ATTR_SPECS covering battery_level and signal_strength with ``preserve_on_missing=True``.

Use for read-only sensor entities (e.g. :class:`~devices.simple_sensor.SimpleReadOnlySensor`)
where values are primarily injected by linked companion sensors and must not
be overwritten on every primary-state refresh when the primary entity's
attributes do not carry battery/signal data.
"""


class BatteryAndSignalLinkMixin:
    """Owns battery + signal-strength state extracted from a primary entity or linked sensors.

    Host class must define ``self.entity_id`` and call ``super().__init__``
    to initialize the three fields below. Mixin provides:

    * ``update_linked_data`` — route linked sensor states into the fields.
    * ``_append_battery_signal_features`` — extend a features list.
    * ``_append_battery_signal_states`` — extend a Sber states list.

    The ``_battery_low`` field is set exclusively by ``update_linked_data``
    (not via :data:`BATTERY_SIGNAL_ATTR_SPECS`) because none of the three
    original implementations had an AttrSpec for it — only linked
    ``binary_sensor`` entities of class ``battery`` trigger it.
    """

    def __init__(self, *args: object, **kwargs: object) -> None:
        """Initialize battery and signal fields."""
        super().__init__(*args, **kwargs)
        self._battery_level: int | None = None
        self._battery_low: bool | None = None
        self._signal_strength_raw: int | None = None

    def update_linked_data(self, role: str, ha_state: dict) -> None:
        """Route a linked sensor state-change into the matching field.

        Args:
            role: Link role name (``battery``, ``battery_low``,
                ``signal_strength``).
            ha_state: HA state dict with a ``'state'`` key.
        """
        state_val = ha_state.get("state")
        if state_val in (None, "unknown", "unavailable"):
            return
        if role == "battery":
            with contextlib.suppress(TypeError, ValueError):
                self._battery_level = int(float(state_val))
        elif role == "battery_low":
            self._battery_low = state_val == "on"
        elif role == "signal_strength":
            with contextlib.suppress(TypeError, ValueError):
                self._signal_strength_raw = int(float(state_val))

    def _append_battery_signal_features(self, features: list[str]) -> None:
        """Extend ``features`` with battery/signal feature keys when data is present.

        Appends ``battery_percentage`` and ``battery_low_power`` if either
        ``_battery_level`` or ``_battery_low`` is set.  Appends
        ``signal_strength`` if ``_signal_strength_raw`` is set.

        Args:
            features: Mutable feature list to extend in-place.
        """
        if self._battery_level is not None or self._battery_low is not None:
            features.append("battery_percentage")
            features.append("battery_low_power")
        if self._signal_strength_raw is not None:
            features.append("signal_strength")

    def _append_battery_signal_states(self, states: list) -> None:
        """Extend ``states`` with Sber battery/signal state entries when values are known.

        Battery logic:

        * If ``_battery_level`` is available, emit both
          ``battery_percentage`` and ``battery_low_power``; derive
          ``battery_low_power`` from ``_battery_level < 20`` when the
          linked binary sensor has not provided a value.
        * If only ``_battery_low`` is available (linked binary sensor,
          no percentage sensor), emit ``battery_low_power`` alone.

        Args:
            states: Mutable states list to extend in-place.
        """
        if self._battery_level is not None:
            states.append(make_state(SberFeature.BATTERY_PERCENTAGE, make_integer_value(self._battery_level)))
            battery_low = self._battery_low if self._battery_low is not None else self._battery_level < 20
            states.append(make_state(SberFeature.BATTERY_LOW_POWER, make_bool_value(battery_low)))
        elif self._battery_low is not None:
            states.append(make_state(SberFeature.BATTERY_LOW_POWER, make_bool_value(self._battery_low)))
        if self._signal_strength_raw is not None:
            states.append(
                make_state(
                    SberFeature.SIGNAL_STRENGTH,
                    make_enum_value(rssi_to_signal_strength(self._signal_strength_raw)),
                )
            )
