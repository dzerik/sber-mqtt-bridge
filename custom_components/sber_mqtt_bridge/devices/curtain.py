"""Sber Curtain entity -- maps HA cover entities to Sber curtain category."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import ClassVar

from .._generated.obligatory_features import CATEGORY_OBLIGATORY_FEATURES
from ..sber_constants import SberFeature
from ..sber_models import make_bool_value, make_enum_value, make_integer_value, make_state
from .base_entity import (
    SENSOR_LINK_ROLES,
    AttrSpec,
    BaseEntity,
    CommandResult,
    _safe_clamped_int_parser,
    _safe_int_parser,
)
from .battery_signal_mixin import BATTERY_SIGNAL_ATTR_SPECS, BatteryAndSignalLinkMixin

CURTAIN_ENTITY_CATEGORY = "curtain"
"""Sber device category for curtain/cover entities."""

HA_TO_SBER_OPEN_STATE: dict[str, str] = {
    "open": "open",
    "opening": "opening",
    "closed": "close",
    "closing": "closing",
}
"""HA cover state -> Sber ``open_state`` enum value."""

TRANSITIONAL_OPEN_STATES: frozenset[str] = frozenset({"opening", "closing"})
"""``open_state`` values that mean "the leaf is moving right now".

The Sber app greys the control button out while one of these is
published (verified on live gate hardware), so a value from this set
must never survive into a publish that is not backed by a live HA
state."""

OFFLINE_OPEN_STATE_FALLBACK = "close"
"""``open_state`` published for a drive that has never reported a position.

``open_state`` is obligatory for ``curtain`` / ``gate`` /
``window_blind`` (:data:`CATEGORY_OBLIGATORY_FEATURES`), so silence is
not an option, and there is no honest third value — Sber documents only
``open`` / ``close`` / ``opening`` / ``closing``.  Of the two stable
ones ``close`` is the safe guess: a user acting on a wrong ``close``
sends "open", which at worst opens an already-open gate, while a user
acting on a wrong ``open`` sends "close" — possibly onto a car in the
gateway.  :class:`~devices.gate.ImpulseGateEntity` already guesses the
same way for a gate with no contact sensor linked."""

_LOGGER = logging.getLogger(__name__)


class CurtainEntity(BatteryAndSignalLinkMixin, BaseEntity):
    """Sber curtain entity for cover control with position support.

    Maps HA cover entities to the Sber 'curtain' category with support for:
    - Position control (0-100%)
    - Open/close/stop commands
    - Open state reporting
    """

    LINKABLE_ROLES = SENSOR_LINK_ROLES

    ATTR_SPECS: ClassVar[tuple[AttrSpec, ...]] = (
        *BATTERY_SIGNAL_ATTR_SPECS,
        AttrSpec(
            field="_tilt_position",
            attr_keys=("current_tilt_position",),
            parser=_safe_int_parser,
        ),
    )

    current_position: int = 0
    """Current cover position (0-100%)."""

    min_position: int = 0
    """Minimum allowed position (0-100%)."""

    max_position: int = 100
    """Maximum allowed position (0-100%)."""

    battery_level: int = 0
    """Battery level percentage (0-100%)."""

    def __init__(self, entity_data: dict, category: str = CURTAIN_ENTITY_CATEGORY) -> None:
        """Initialize curtain entity.

        Args:
            entity_data: HA entity registry dict containing entity metadata.
            category: Sber device category (override in subclasses).
        """
        super().__init__(category, entity_data)
        self.current_position = 0
        self._open_rate: str | None = None
        self._tilt_position: int | None = None
        self._last_open_state: str | None = None

    def fill_by_ha_state(self, ha_state: dict) -> None:
        """Update state from Home Assistant data.

        Battery level, tilt position and signal strength are parsed via
        :class:`AttrSpec`.  ``current_position`` and ``open_rate`` have
        custom fallback / mapping logic and stay imperative.

        A resting position seen here is remembered for the offline
        publish — see :meth:`_remember_open_state`.

        Args:
            ha_state: HA state dict with 'state' and 'attributes' keys.
        """
        super().fill_by_ha_state(ha_state)
        attrs = ha_state.get("attributes", {})
        self._apply_attr_specs(attrs)
        self.current_position = self._parse_current_position(attrs)
        self._open_rate = self._parse_open_rate(attrs)
        self._remember_open_state()

    def _remember_open_state(self) -> None:
        """Latch the last *resting* ``open_state`` reported by HA.

        Only stable values are latched.  ``opening`` / ``closing`` say
        where the leaf is going, not where it is, and the Sber app blocks
        the control button for as long as one of them is published
        (:data:`TRANSITIONAL_OPEN_STATES`) — republishing a frozen
        ``closing`` for a drive that has already dropped off the network
        would take the gate out of the user's hands until HA comes back.
        """
        if not self._is_online:
            return
        value = self._compute_open_state()
        if value in TRANSITIONAL_OPEN_STATES:
            return
        self._last_open_state = value

    def _compute_open_state(self) -> str:
        """Derive ``open_state`` from the live HA state and position.

        Keeps ``open_state`` and ``open_percentage`` consistent: for a
        resting cover a non-zero percentage always reads ``open`` and a
        zero one always ``close``, whatever the HA state string says.

        Returns:
            One of ``open`` / ``close`` / ``opening`` / ``closing``.
        """
        sber_pos = self._convert_position(self.current_position)
        open_state = HA_TO_SBER_OPEN_STATE.get(self.state, "close" if sber_pos == 0 else "open")
        if open_state in TRANSITIONAL_OPEN_STATES:
            return open_state
        return "open" if sber_pos > 0 else "close"

    def _offline_open_state(self) -> str:
        """``open_state`` to publish while the cover is unreachable.

        The last resting position, or :data:`OFFLINE_OPEN_STATE_FALLBACK`
        when the drive has never reported one.

        Returns:
            A stable ``open_state`` enum value — never a transitional one.
        """
        return self._last_open_state or OFFLINE_OPEN_STATE_FALLBACK

    def _parse_current_position(self, attrs: dict) -> int:
        """Parse ``current_position`` with fallback based on HA state."""
        position = attrs.get("current_position")
        if position is not None:
            try:
                return max(0, min(100, int(float(position))))
            except (TypeError, ValueError):
                pass
        return 100 if self.state in ("open", "opening") else 0

    @staticmethod
    def _parse_open_rate(attrs: dict) -> str | None:
        """Parse ``speed`` / ``motor_speed`` into a Sber ``open_rate`` value."""
        speed = attrs.get("speed") or attrs.get("motor_speed")
        if speed is None:
            return None
        speed_str = str(speed).lower()
        if speed_str not in ("auto", "low", "high"):
            return None
        return speed_str

    def _convert_position(self, ha_position: int) -> int:
        """Convert HA position (0-100) to Sber position (0-100).

        Currently a 1:1 mapping; override in subclasses if needed.

        Args:
            ha_position: Position value from Home Assistant.

        Returns:
            Position value for Sber protocol.
        """
        return int(ha_position)

    _OPEN_SET_SERVICE_MAP: ClassVar[dict[str, str]] = {
        "open": "open_cover",
        "close": "close_cover",
        "stop": "stop_cover",
    }
    """Map Sber ``open_set`` enum values to HA cover services."""

    @property
    def _cmd_handlers(self) -> dict[str, Callable[[dict], list[CommandResult]]]:
        """Return dispatch map from Sber feature key to handler method.

        Handles ``open_percentage`` (and legacy ``cover_position``) for
        set_cover_position, and ``open_set`` for open/close/stop.
        """
        return {
            SberFeature.OPEN_PERCENTAGE: self._cmd_set_position,
            "cover_position": self._cmd_set_position,
            SberFeature.OPEN_SET: self._cmd_open_set,
        }

    def _cmd_set_position(self, value: dict) -> list[dict]:
        """Handle ``open_percentage`` — drive the cover to an absolute position.

        The service domain is taken from the entity id rather than
        hard-coded to ``cover`` (same pattern as ``intercom``): subclasses
        promoted from another HA domain must not emit a ``cover.*`` call
        for, say, a ``switch``.  For ``cover`` entities the result is
        byte-for-byte identical to the previous hard-coded form.
        """
        ha_position = _safe_clamped_int_parser(value.get("integer_value"), 0, 100)
        if ha_position is None:
            return []
        return [
            self._build_service_call(
                self.get_entity_domain(),
                "set_cover_position",
                self.entity_id,
                {"position": ha_position},
            )
        ]

    def _cmd_open_set(self, value: dict) -> list[dict]:
        """Handle ``open_set`` — open / close / stop the cover.

        Uses :meth:`get_entity_domain` for the same reason as
        :meth:`_cmd_set_position`.
        """
        action = value.get("enum_value")
        service = self._OPEN_SET_SERVICE_MAP.get(action or "")
        if service is None:
            return []
        return [self._build_service_call(self.get_entity_domain(), service, self.entity_id)]

    _TILT_CATEGORIES = frozenset({"window_blind"})
    """Sber categories whose spec includes ``light_transmission_percentage``."""

    _BATTERY_CATEGORIES = frozenset({"curtain", "window_blind"})
    """Sber categories whose spec includes battery features (gate has none)."""

    def _create_features_list(self) -> list[str]:
        """Return Sber feature list for curtain capabilities.

        Includes open_percentage, open_set, open_state, and optionally
        signal_strength features.  Battery and tilt features are gated by
        category: the Sber spec has no battery features for ``gate`` and
        declares ``light_transmission_percentage`` only for
        ``window_blind`` (issue #44 audit — off-spec features risk silent
        device rejection).

        Returns:
            List of Sber feature strings supported by this entity.
        """
        features = [
            *super()._create_features_list(),
            "open_percentage",
            "open_set",
            "open_state",
        ]
        if self.category in self._BATTERY_CATEGORIES:
            self._append_battery_signal_features(features)
        elif self._signal_strength_raw is not None:
            features.append("signal_strength")
        if self._open_rate is not None:
            features.append("open_rate")
        if self._tilt_position is not None and self.category in self._TILT_CATEGORIES:
            features.append("light_transmission_percentage")
        return features

    def create_allowed_values_list(self) -> dict[str, dict]:
        """Return allowed values for the controllable cover features.

        Built from the final features list so user overrides
        (``sber_features_add`` / ``sber_features_remove``) stay in sync
        with the advertised limits.  ``open_rate`` values follow the
        Sber curtain reference example.
        """
        features = set(self.get_final_features_list())
        allowed: dict[str, dict] = {}
        if "open_set" in features:
            allowed["open_set"] = {
                "type": "ENUM",
                "enum_values": {"values": ["open", "close", "stop"]},
            }
        if "open_percentage" in features:
            allowed["open_percentage"] = {
                "type": "INTEGER",
                "integer_values": {"min": "0", "max": "100", "step": "1"},
            }
        if "open_rate" in features:
            allowed["open_rate"] = {
                "type": "ENUM",
                "enum_values": {"values": ["auto", "low", "high"]},
            }
        if "light_transmission_percentage" in features:
            allowed["light_transmission_percentage"] = {
                "type": "INTEGER",
                "integer_values": {"min": "0", "max": "100", "step": "1"},
            }
        return allowed

    def _offline_obligatory_features(self) -> frozenset[str]:
        """Features this category must publish even with ``online=false``.

        Read from the generated documentation tables rather than
        hard-coded: a category that gains an obligatory feature upstream
        starts keeping it offline without a code change here.

        Returns:
            Obligatory feature keys of :attr:`category`.
        """
        return CATEGORY_OBLIGATORY_FEATURES.get(self.category, frozenset())

    def _build_current_state(self) -> dict[str, dict]:
        """Build Sber current state payload with position, open state, and signal.

        Per Sber C2C specification, ``integer_value`` is serialized as a string.

        While the cover is unreachable only ``online=false`` and the
        obligatory ``open_state`` go out.  ``open_state`` is obligatory
        for ``curtain`` / ``gate`` / ``window_blind``, and Sber treats a
        publish that omits an obligatory feature as a broken device — the
        same reasoning that keeps alarm states flowing for offline
        sensors.  ``open_percentage`` is *not* obligatory and is a
        reading, so it is dropped instead of being fabricated: the cloud
        keeps the last real percentage.

        Returns:
            Dict mapping entity_id to its Sber state representation.
        """
        if not self._is_online:
            states = [
                make_state(SberFeature.ONLINE, make_bool_value(False)),
            ]
            if SberFeature.OPEN_STATE.value in self._offline_obligatory_features():
                states.append(make_state(SberFeature.OPEN_STATE, make_enum_value(self._offline_open_state())))
            return {self.entity_id: {"states": states}}

        states = [
            make_state(SberFeature.ONLINE, make_bool_value(True)),
        ]

        states.append(
            make_state(SberFeature.OPEN_PERCENTAGE, make_integer_value(self._convert_position(self.current_position)))
        )
        states.append(make_state(SberFeature.OPEN_STATE, make_enum_value(self._compute_open_state())))

        if self.category in self._BATTERY_CATEGORIES:
            self._append_battery_signal_states(states)
        elif self._signal_strength_raw is not None:
            self._append_signal_strength_state(states)
        if self._open_rate is not None:
            states.append(make_state(SberFeature.OPEN_RATE, make_enum_value(self._open_rate)))
        if self._tilt_position is not None and self.category in self._TILT_CATEGORIES:
            states.append(
                make_state(SberFeature.LIGHT_TRANSMISSION_PERCENTAGE, make_integer_value(self._tilt_position))
            )

        return {self.entity_id: {"states": states}}
