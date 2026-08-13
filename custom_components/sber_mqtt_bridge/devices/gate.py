"""Sber Gate entities -- HA cover gates and impulse-relay gates.

Two very different physical devices share the Sber ``gate`` category:

* :class:`GateEntity` — a real HA ``cover`` with position support
  (``open_cover`` / ``close_cover`` / ``stop_cover``).  Unchanged since
  v1.x, it stays the path for anything in the ``cover`` domain.
* :class:`ImpulseGateEntity` — the "one button + one reed contact"
  topology (issue #53): an impulse relay (``switch`` / ``button`` /
  ``script``) that pulses the gate motor, plus a ``binary_sensor``
  contact that is the *only* source of truth about the leaf position.

:func:`make_gate_entity` routes between them by HA domain and is what
``CATEGORY_DOMAIN_MAP`` registers for the ``gate`` category.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import ClassVar

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN

from ..sber_constants import (
    SERVICE_PRESS,
    SERVICE_TOGGLE,
    SERVICE_TURN_ON,
    HAState,
    SberFeature,
    SberValueType,
)
from ..sber_models import make_bool_value, make_enum_value, make_state
from .base_entity import (
    GATE_LINK_ROLES,
    AttrSpec,
    BaseEntity,
    CommandResult,
)
from .battery_signal_mixin import BATTERY_SIGNAL_ATTR_SPECS_PRESERVE, BatteryAndSignalLinkMixin
from .curtain import CurtainEntity

GATE_ENTITY_CATEGORY = "gate"
"""Sber device category for gate/garage door entities."""

IMPULSE_COOLDOWN_SECONDS = 2.0
"""Minimum gap (seconds) between two impulses sent to the same gate.

Anti-bounce only: it swallows the burst of *back-to-back* commands (a
double-tap in the app, a repeated voice command, a retry after a lost
ack), which is the classic way to make an impulse controller pile up
pulses.  A command arriving inside the window is acknowledged with a
state republish instead of a second pulse.

It is deliberately **not** a travel-time lock: the leaf needs 15-25 s to
move, and a command arriving after the window — but before the leaf has
arrived — is a legitimate "stop / reverse" request.  Guarding the whole
travel is the job of the opt-in :data:`GATE_OPTION_TRAVEL_TIME` motion
emulation, not of this window."""

GATE_OPTION_INVERT_CONTACT = "invert_contact"
"""``gate_options`` key flipping the polarity of the linked reed contact."""

GATE_OPTION_IMPULSE_SERVICE = "impulse_service"
"""``gate_options`` key choosing the HA service used to pulse the relay."""

GATE_OPTION_TRAVEL_TIME = "travel_time"
"""``gate_options`` key holding the leaf travel time in seconds.

``0`` / ``None`` (the default) disables the motion emulation entirely and
keeps the historical behaviour: the published ``open_state`` only ever
switches between ``open`` and ``close``, driven by the contact alone."""

MAX_TRAVEL_TIME_SECONDS = 600.0
"""Upper bound accepted for :data:`GATE_OPTION_TRAVEL_TIME` (10 minutes).

A hand-edited config with a wild value (or a UI sending milliseconds)
would otherwise pin the gate in a fake ``opening`` state for hours."""

TRAVEL_CONFIRM_MARGIN_SECONDS = 0.5
"""Extra delay added to the deadline republish requested from the bridge.

:attr:`ImpulseGateEntity.pending_confirm_delay` is consumed by
``SberBridge.schedule_confirm``, which sleeps on the event loop while the
entity measures the deadline with its own injectable clock.  The margin
makes sure the republish observes an *expired* deadline instead of racing
it by a few milliseconds and publishing ``opening`` one last time."""

IMPULSE_SERVICE_AUTO = "auto"
"""``impulse_service`` option value: pick the service from the HA domain."""

IMPULSE_SERVICE_TOGGLE = "toggle"
"""``impulse_service`` option value: force ``switch.toggle``."""

IMPULSE_SERVICE_TURN_ON = "turn_on"
"""``impulse_service`` option value: force ``switch.turn_on``."""

IMPULSE_SERVICE_OPTIONS: tuple[str, ...] = (
    IMPULSE_SERVICE_AUTO,
    IMPULSE_SERVICE_TOGGLE,
    IMPULSE_SERVICE_TURN_ON,
)
"""Accepted values of the per-entity ``impulse_service`` gate option."""

OPEN_STATE_OPEN = "open"
"""Sber ``open_state`` / ``open_set`` enum value for an open gate."""

OPEN_STATE_CLOSE = "close"
"""Sber ``open_state`` / ``open_set`` enum value for a closed gate."""

OPEN_STATE_OPENING = "opening"
"""Sber ``open_state`` enum value published while the leaf is opening.

Only ever published when the travel-time emulation is switched on, and
then always together with an ``allowed_values.open_state`` declaration —
Sber silently drops a state value it was not told about (issue #44)."""

OPEN_STATE_CLOSING = "closing"
"""Sber ``open_state`` enum value published while the leaf is closing."""

TRAVEL_OPEN_STATE_VALUES: tuple[str, ...] = (
    OPEN_STATE_OPEN,
    OPEN_STATE_CLOSE,
    OPEN_STATE_OPENING,
    OPEN_STATE_CLOSING,
)
"""``open_state`` enum values declared while the travel emulation is on."""

_PRESS_DOMAINS: frozenset[str] = frozenset({"button", "input_button"})
"""HA domains whose impulse is a ``press`` service call."""

_TURN_ON_DOMAINS: frozenset[str] = frozenset({"script"})
"""HA domains whose impulse is a ``turn_on`` service call (no toggle semantics)."""

_TOGGLE_DOMAINS: frozenset[str] = frozenset({"switch"})
"""HA domains whose impulse is a ``toggle`` (or, by option, ``turn_on``) call."""

IMPULSE_DOMAINS: frozenset[str] = _PRESS_DOMAINS | _TURN_ON_DOMAINS | _TOGGLE_DOMAINS
"""Every HA domain an impulse can actually be sent to.

Anything else gets **no** service call: the ``gate`` category can be
forced onto an arbitrary entity with ``set_override`` (which bypasses
:meth:`~sber_entity_map.CategorySpec.matches`), and inventing
``<domain>.toggle`` for, say, a ``lock`` would turn every Sber command
into a ``ServiceNotFound``."""

_LOGGER = logging.getLogger(__name__)


class GateEntity(CurtainEntity):
    """Sber gate entity for gate/garage door control.

    Inherits all curtain functionality (position, open/close/stop) but uses
    the Sber 'gate' category instead of 'curtain'.

    Maps HA cover entities with device_class 'gate' or 'garage_door'.
    """

    def __init__(self, entity_data: dict) -> None:
        """Initialize gate entity.

        Args:
            entity_data: HA entity registry dict containing entity metadata.
        """
        super().__init__(entity_data, category=GATE_ENTITY_CATEGORY)


class ImpulseGateEntity(BatteryAndSignalLinkMixin, BaseEntity):
    """Sber ``gate`` device built from an impulse relay + a reed contact.

    The primary HA entity is the relay that pulses the gate motor
    (``switch``, ``button``, ``input_button`` or ``script``).  Its own HA
    state is merely an echo of the last value written to the relay — it
    "sticks" and must **never** be read as a position.  The position comes
    exclusively from a ``binary_sensor`` linked in the
    :data:`~devices.base_entity.ROLE_OPEN_STATE` role, hence
    :attr:`REQUIRED_LINK_ROLES`.

    Sber features: ``online`` (obligatory), ``open_set`` (ENUM
    ``open``/``close``), ``open_state`` (obligatory) and
    ``signal_strength`` when a signal sensor is linked.  There is
    deliberately **no** ``open_percentage``: an impulse drive has no
    position, and the Sber spec marks that feature conditional.  ``stop``
    is not declared either — a single button cannot stop the leaf.

    With the opt-in :data:`GATE_OPTION_TRAVEL_TIME` option the entity also
    emulates the movement itself: after an impulse it publishes
    ``opening`` / ``closing`` (declared in ``allowed_values.open_state``
    for exactly as long as the option is on) until either the contact
    reports — the contact always wins — or the travel time elapses without
    confirmation, which logs a warning and falls back to the last known
    position.  With the option off (the default) nothing about the device
    changes: same features, same ``allowed_values``, same ``model.id``.
    """

    LINKABLE_ROLES = GATE_LINK_ROLES

    REQUIRED_LINK_ROLES: ClassVar[tuple[str, ...]] = ("open_state",)

    ATTR_SPECS: ClassVar[tuple[AttrSpec, ...]] = BATTERY_SIGNAL_ATTR_SPECS_PRESERVE
    """Signal strength is preserved across primary refreshes.

    The relay toggles constantly and usually carries no ``linkquality``
    of its own, so a non-preserving spec would wipe the value injected by
    the linked signal sensor on every pulse (and flip the advertised
    feature set back and forth with it).
    """

    def __init__(self, entity_data: dict, category: str = GATE_ENTITY_CATEGORY) -> None:
        """Initialize an impulse gate entity.

        Args:
            entity_data: HA entity registry dict containing entity metadata.
            category: Sber device category (override in subclasses).
        """
        super().__init__(category, entity_data)
        self._open: bool = False
        self._contact_seen: bool = False
        self._contact_stale: bool = False
        self._invert_contact: bool = False
        self._impulse_service: str = IMPULSE_SERVICE_AUTO
        self._last_impulse_at: float | None = None
        self._missing_link_logged: bool = False
        self._unknown_domain_logged: bool = False
        # Travel-time emulation (opt-in, see ``travel_time``).  Both fields
        # are None while the leaf is considered at rest.
        self._travel_time: float = 0.0
        self._travel_direction: str | None = None
        self._travel_deadline: float | None = None
        # Anti-bounce window (seconds) between two impulses.
        self.impulse_cooldown: float = IMPULSE_COOLDOWN_SECONDS
        # Injectable monotonic clock — tests replace it; the command logic
        # never calls ``time.monotonic()`` directly.
        self._now: Callable[[], float] = time.monotonic

    # -- user options -------------------------------------------------

    def apply_gate_options(self, options: dict) -> None:
        """Apply per-entity gate options from ``entry.options``.

        Args:
            options: Mapping with optional ``invert_contact`` (bool),
                ``impulse_service`` (one of :data:`IMPULSE_SERVICE_OPTIONS`)
                and ``travel_time`` (seconds, see :meth:`travel_time`)
                keys.  Unknown keys and invalid values are ignored, so a
                hand-edited config cannot break entity loading.
        """
        if not options:
            return
        invert = options.get(GATE_OPTION_INVERT_CONTACT)
        if isinstance(invert, bool):
            self._invert_contact = invert
        service = options.get(GATE_OPTION_IMPULSE_SERVICE)
        if service in IMPULSE_SERVICE_OPTIONS:
            self._impulse_service = service
        if GATE_OPTION_TRAVEL_TIME in options:
            self._apply_travel_time(options[GATE_OPTION_TRAVEL_TIME])
        _LOGGER.debug(
            "Gate options for %s: invert_contact=%s impulse_service=%s travel_time=%s",
            self.entity_id,
            self._invert_contact,
            self._impulse_service,
            self._travel_time,
        )

    def _apply_travel_time(self, raw: object) -> None:
        """Validate and store the ``travel_time`` option.

        ``None`` and ``0`` both mean "emulation off"; anything outside
        ``[0, MAX_TRAVEL_TIME_SECONDS]`` — or of the wrong type, ``bool``
        included (``True`` would silently become one second) — is ignored
        so a hand-edited config cannot pin the gate in a fake moving
        state.

        Args:
            raw: Value read from ``gate_options['travel_time']``.
        """
        if raw is None:
            self._set_travel_time(0.0)
            return
        if isinstance(raw, bool) or not isinstance(raw, int | float):
            _LOGGER.debug("Gate %s: ignoring non-numeric travel_time %r", self.entity_id, raw)
            return
        value = float(raw)
        if not 0.0 <= value <= MAX_TRAVEL_TIME_SECONDS:
            _LOGGER.warning(
                "Gate %s: travel_time %.1fs is out of range (0-%.0fs) — option ignored",
                self.entity_id,
                value,
                MAX_TRAVEL_TIME_SECONDS,
            )
            return
        self._set_travel_time(value)

    def _set_travel_time(self, value: float) -> None:
        """Store a validated travel time, cancelling emulation when disabled.

        Args:
            value: Travel time in seconds; ``0`` disables the emulation.
        """
        self._travel_time = value
        if value <= 0.0:
            self._cancel_travel("travel_time disabled")

    @property
    def invert_contact(self) -> bool:
        """Whether the linked contact reports ``on`` for a *closed* gate."""
        return self._invert_contact

    @property
    def impulse_service_option(self) -> str:
        """Current ``impulse_service`` option (see :data:`IMPULSE_SERVICE_OPTIONS`)."""
        return self._impulse_service

    @property
    def travel_time(self) -> float:
        """Configured leaf travel time in seconds (``0`` = emulation off)."""
        return self._travel_time

    @property
    def contact_stale(self) -> bool:
        """True when the contact sensor stopped reporting a usable value.

        The last known position is kept published in that case (losing
        control of a gate is worse than showing a slightly stale
        position); this flag surfaces the fact in diagnostics.
        """
        return self._contact_stale

    # -- travel-time emulation ------------------------------------------

    @property
    def travel_direction(self) -> str | None:
        """Direction currently emulated, or ``None`` when the leaf is at rest.

        One of :data:`OPEN_STATE_OPENING` / :data:`OPEN_STATE_CLOSING`.
        Reading this settles an expired deadline first, so the value never
        outlives :attr:`travel_time`.
        """
        self._expire_travel_if_due()
        return self._travel_direction

    @property
    def pending_confirm_delay(self) -> float | None:
        """Seconds after which the bridge should republish this gate's state.

        Read by ``SberBridge.schedule_confirm`` right after a command: the
        emulated ``opening`` / ``closing`` value has to be replaced by a
        real one when the travel deadline passes, and only the bridge owns
        timers.  ``None`` means "nothing to schedule" — the default,
        travel-emulation-off case.

        Returns:
            Remaining travel time plus :data:`TRAVEL_CONFIRM_MARGIN_SECONDS`,
            or ``None`` when no motion is being emulated.
        """
        if self._travel_direction is None or self._travel_deadline is None:
            return None
        return max(0.0, self._travel_deadline - self._now()) + TRAVEL_CONFIRM_MARGIN_SECONDS

    def _start_travel(self) -> None:
        """Arm the motion emulation right after an impulse was issued.

        The direction is derived from the *last known position*, not from
        the requested one: the hardware has a single button, so the leaf
        can only move away from where it currently is.  No-op while the
        feature is off (:attr:`travel_time` == 0), which keeps the default
        behaviour byte-for-byte identical to the pre-emulation one.

        That derivation is only legitimate while the position is actually
        *known*.  With a contact that never reported, or one whose reading
        went stale, ``self._open`` is a placeholder — emulating from it
        publishes the direction **opposite** to the one the user asked for
        as often as not (``open`` on a gate wrongly believed open becomes
        ``closing``).  Sitting the travel out and letting the contact
        speak is the honest answer; the deadline machinery has nothing to
        settle either way.
        """
        if self._travel_time <= 0.0:
            return
        if not self._contact_seen or self._contact_stale:
            _LOGGER.debug(
                "Gate %s: position unknown (seen=%s stale=%s) — no motion emulated after the impulse",
                self.entity_id,
                self._contact_seen,
                self._contact_stale,
            )
            return
        self._travel_direction = OPEN_STATE_CLOSING if self._open else OPEN_STATE_OPENING
        self._travel_deadline = self._now() + self._travel_time
        _LOGGER.debug(
            "Gate %s: emulating %s for %.1fs after the impulse",
            self.entity_id,
            self._travel_direction,
            self._travel_time,
        )

    def _cancel_travel(self, reason: str) -> None:
        """Drop the motion emulation and fall back to the known position.

        Args:
            reason: Short human-readable cause, logged at debug level.
        """
        if self._travel_direction is None:
            return
        _LOGGER.debug(
            "Gate %s: motion emulation (%s) cancelled — %s",
            self.entity_id,
            self._travel_direction,
            reason,
        )
        self._travel_direction = None
        self._travel_deadline = None

    def _expire_travel_if_due(self) -> None:
        """Settle an emulated movement whose deadline has passed.

        Called from every read of the published position and from the
        command path, so the emulation cannot survive its deadline even if
        the bridge's republish never runs (entity unloaded, MQTT down).
        The leaf is assumed *not* to have moved: with no confirmation from
        the contact, the last known position is the only honest answer.
        """
        if self._travel_direction is None or self._travel_deadline is None:
            return
        if self._now() < self._travel_deadline:
            return
        _LOGGER.warning(
            "Gate %s: movement (%s) not confirmed by the contact sensor within %.1fs — "
            "falling back to the last known position '%s'",
            self.entity_id,
            self._travel_direction,
            self._travel_time,
            OPEN_STATE_OPEN if self._open else OPEN_STATE_CLOSE,
        )
        self._travel_direction = None
        self._travel_deadline = None

    # -- HA state of the relay -----------------------------------------

    def fill_by_ha_state(self, ha_state: dict) -> None:
        """Refresh from the HA state of the impulse relay.

        Only the relay's *attributes* are of interest: its ``state`` is an
        echo of the last written value and is never a position (see
        :meth:`update_linked_data`).  Applying :attr:`ATTR_SPECS` here is
        what lets a Zigbee relay advertise its own ``linkquality`` /
        ``rssi`` as ``signal_strength``; the specs preserve on missing, so
        a value injected by a linked signal sensor survives every relay
        refresh.

        Args:
            ha_state: HA state dict with ``state`` and ``attributes`` keys.
        """
        super().fill_by_ha_state(ha_state)
        self._apply_attr_specs(ha_state.get("attributes", {}))

    # -- linked contact ------------------------------------------------

    @property
    def _has_open_state_link(self) -> bool:
        """True when a contact sensor is linked in the ``open_state`` role."""
        return "open_state" in self._linked_entities

    def update_linked_data(self, role: str, ha_state: dict) -> None:
        """Apply a linked companion state.

        ``open_state`` is handled here (it *is* this device's position);
        every other role falls through to
        :class:`~devices.battery_signal_mixin.BatteryAndSignalLinkMixin`.

        A running travel emulation is cancelled only when the contact
        brings genuinely **new** knowledge: a position different from the
        one already known (the leaf arrived), a first-ever reading, or a
        drop-out that makes confirmation impossible for good.  A reading
        that merely repeats the current position carries no information —
        while a 20-second leaf is opening, the reed contact legitimately
        still reads "closed" for the first part of the travel — and it
        reaches this method for reasons that have nothing to do with the
        gate at all:

        * ``HaStateForwarder`` forwards *every* ``state_changed`` event of
          a linked entity, including attribute-only ones, so a Zigbee
          contact reporting ``battery`` / ``linkquality`` used to kill the
          emulation seconds after the impulse;
        * an MQTT binding with ``force_update: true`` re-fires the same
          state on every message;
        * ``SberBridge._refresh_entity_from_ha`` (used when gate options
          are saved) feeds the *current* contact state back in, so saving
          an unrelated checkbox mid-travel used to cancel the movement.

        A gate that really is stuck reports nothing at all, and is settled
        by the travel deadline with a warning — not by this method.

        Args:
            role: Link role name.
            ha_state: HA state dict of the linked entity.
        """
        if role != "open_state":
            super().update_linked_data(role, ha_state)
            return
        raw = ha_state.get("state")
        if raw in (None, STATE_UNKNOWN, STATE_UNAVAILABLE):
            # Hold the last known position — see :attr:`contact_stale`.
            self._cancel_travel("contact sensor dropped out")
            self._contact_stale = True
            return
        was_known = self._contact_seen and not self._contact_stale
        was_open = self._open
        self._open = (raw == HAState.ON) != self._invert_contact
        self._contact_seen = True
        self._contact_stale = False
        if not was_known or self._open != was_open:
            self._cancel_travel("contact sensor reported a new position")

    @property
    def _open_state_value(self) -> str:
        """Sber ``open_state`` enum value to publish.

        While a movement is being emulated (opt-in ``travel_time``) the
        direction wins over the last known position — that is the whole
        point of the emulation.  Otherwise falls back to ``close`` when no
        contact is linked at all: claiming an unknown gate is open is the
        dangerous direction of the guess.
        """
        self._expire_travel_if_due()
        if self._travel_direction is not None:
            return self._travel_direction
        if not self._has_open_state_link and not self._missing_link_logged:
            self._missing_link_logged = True
            _LOGGER.warning(
                "Gate %s has no linked contact sensor (role 'open_state') — "
                "publishing open_state='close'; link a binary_sensor to report the real position",
                self.entity_id,
            )
        return OPEN_STATE_OPEN if self._open else OPEN_STATE_CLOSE

    @property
    def _relay_reachable(self) -> bool:
        """True when the HA state of the impulse relay means "reachable".

        Same rule as :attr:`BaseEntity._is_online` with one exception:
        a ``button`` / ``input_button`` sits at ``unknown`` until its very
        first press, which says nothing about reachability — treating it
        as offline would keep such a gate permanently offline in Sber.
        """
        if self.state in (STATE_UNAVAILABLE, None):
            return False
        if self.state == STATE_UNKNOWN:
            return self.entity_id.split(".", 1)[0] in _PRESS_DOMAINS
        return True

    @property
    def _is_online(self) -> bool:
        """Online only when the relay is reachable and the position is known.

        A linked contact that has never reported anything means the
        position is unknown; reporting ``online`` with a fabricated
        ``close`` would be a lie, so the device is marked offline until
        the contact speaks.  With no link at all the relay stays online —
        it is still controllable.
        """
        if not self._relay_reachable:
            return False
        return self._contact_seen or not self._has_open_state_link

    # -- Sber model / state --------------------------------------------

    def _create_features_list(self) -> list[str]:
        """Return the Sber feature list for an impulse gate.

        ``open_state`` is unconditional: it is obligatory for the ``gate``
        category, and :meth:`BaseEntity._filter_undeclared_states` would
        silently drop the published value if it were missing here.

        Returns:
            List of Sber feature strings supported by this entity.
        """
        features = [
            *super()._create_features_list(),
            SberFeature.OPEN_SET.value,
            SberFeature.OPEN_STATE.value,
        ]
        if self._signal_strength_raw is not None:
            features.append(SberFeature.SIGNAL_STRENGTH.value)
        return features

    def create_allowed_values_list(self) -> dict[str, dict]:
        """Return allowed values for ``open_set`` (and ``open_state`` when moving).

        ``open_set`` offers only ``open`` and ``close``.  ``stop`` is
        omitted on purpose: the hardware has a single button, so a "stop
        the gate" voice command would be accepted by Sber and then do
        nothing.  The spec explicitly allows shortening the ENUM list.

        ``open_state`` is declared **only** while the travel emulation is
        on, and then with the two transient values it can publish.  Sber
        silently ignores a state value the device never declared (the
        root cause behind issue #44), so ``opening`` / ``closing`` and
        their declaration must appear and disappear together.  Leaving
        the key out while the feature is off keeps the model descriptor —
        and therefore the capability digest behind ``model.id`` — exactly
        as it was before the feature existed.

        Returns:
            Allowed-values map for the Sber model descriptor.
        """
        features = set(self.get_final_features_list())
        allowed: dict[str, dict] = {}
        if SberFeature.OPEN_SET.value in features:
            allowed[SberFeature.OPEN_SET.value] = {
                "type": SberValueType.ENUM.value,
                "enum_values": {"values": [OPEN_STATE_OPEN, OPEN_STATE_CLOSE]},
            }
        if self._travel_time > 0.0 and SberFeature.OPEN_STATE.value in features:
            allowed[SberFeature.OPEN_STATE.value] = {
                "type": SberValueType.ENUM.value,
                "enum_values": {"values": list(TRAVEL_OPEN_STATE_VALUES)},
            }
        return allowed

    def _build_current_state(self) -> dict[str, dict]:
        """Build the Sber current-state payload.

        Both ``online`` and ``open_state`` are always present — the latter
        is obligatory for the category, and omitting it (even while
        offline) is a known cause of silent device rejection.

        Returns:
            Dict mapping entity_id to its Sber state representation.
        """
        states = [
            make_state(SberFeature.ONLINE, make_bool_value(self._is_online)),
            make_state(SberFeature.OPEN_STATE, make_enum_value(self._open_state_value)),
        ]
        self._append_signal_strength_state(states)
        return {self.entity_id: {"states": states}}

    # -- commands -------------------------------------------------------

    @property
    def _cmd_handlers(self) -> dict[str, Callable[[dict], list[CommandResult]]]:
        """Return dispatch map from Sber feature key to handler method."""
        return {SberFeature.OPEN_SET: self._cmd_open_set}

    def _cmd_open_set(self, value: dict) -> list[CommandResult]:
        """Handle the ``open_set`` ENUM command.

        Sber sends a *directed* command (``open`` / ``close``) while the
        hardware only has one button, so the direction is enforced here:

        * the gate is *travelling* (emulated, opt-in ``travel_time``) in
          the requested direction → no service call: it is already going
          there, and a second pulse would stop it mid-way.  A command in
          the opposite direction does pulse — physically that stops or
          reverses the leaf, which is exactly what the user asked for.
        * the gate is at rest and the requested direction already matches
          the known position → no service call at all, just an
          acknowledging republish.  Without this guard "open the gate" on
          an already-open gate would close it — possibly onto a car.  The
          guard only applies while the position is actually *known*: a
          contact that never reported, or one whose reading went stale
          (:attr:`contact_stale`), gives no such guarantee, and blocking a
          direction on a guess would leave the user unable to close the
          gate from Sber at all.
        * a second command inside :attr:`impulse_cooldown` → acknowledged
          without a pulse (anti-bounce).

        Values other than ``open`` / ``close`` (notably ``stop``, which is
        not declared in ``allowed_values``) are ignored.

        Args:
            value: Sber value dict from the command payload.

        Returns:
            Single-item list with either the impulse service call or an
            update-state acknowledgement; empty list for values this
            device does not handle.
        """
        if value.get("type") != SberValueType.ENUM:
            return []
        action = value.get("enum_value")
        if action not in (OPEN_STATE_OPEN, OPEN_STATE_CLOSE):
            _LOGGER.debug("Gate %s: unsupported open_set value %r — ignored", self.entity_id, action)
            return []

        self._expire_travel_if_due()
        travelling = self._travel_direction
        if travelling is not None:
            if (action == OPEN_STATE_OPEN) == (travelling == OPEN_STATE_OPENING):
                _LOGGER.debug(
                    "Gate %s: open_set=%s but the gate is already %s — no impulse sent",
                    self.entity_id,
                    action,
                    travelling,
                )
                return [{"update_state": True}]
        elif self._contact_seen and not self._contact_stale and (action == OPEN_STATE_OPEN) == self._open:
            _LOGGER.debug(
                "Gate %s: open_set=%s but gate is already %s — no impulse sent",
                self.entity_id,
                action,
                self._open_state_value,
            )
            return [{"update_state": True}]

        now = self._now()
        if self._last_impulse_at is not None and (now - self._last_impulse_at) < self.impulse_cooldown:
            _LOGGER.debug(
                "Gate %s: open_set=%s suppressed by the %.1fs impulse cooldown",
                self.entity_id,
                action,
                self.impulse_cooldown,
            )
            return [{"update_state": True}]

        call = self._build_impulse_call()
        if call is None:
            return []
        self._last_impulse_at = now
        if travelling is not None:
            # Counter-command mid-travel: the drive either stops or reverses
            # and we have no way to tell which.  Guessing a new direction
            # would be a second lie on top of an unknown position, so the
            # emulation is dropped and the contact becomes the only source
            # of truth again.
            self._cancel_travel("counter-command during travel")
        else:
            self._start_travel()
        return [call]

    def _build_impulse_call(self) -> CommandResult | None:
        """Build the single HA service call that pulses the relay.

        Service selection by primary domain:

        ================ ==========================================
        Domain           Service
        ================ ==========================================
        ``switch``       ``toggle`` (default) / ``turn_on`` (option)
        ``button``       ``press``
        ``input_button`` ``press``
        ``script``       ``turn_on``
        ================ ==========================================

        Returns:
            A :class:`ServiceCallResult` for the impulse, or ``None`` when
            the primary entity lives in a domain with no known impulse
            service (see :data:`IMPULSE_DOMAINS`) — better no call at all
            than a fabricated one that raises ``ServiceNotFound`` on every
            Sber command.
        """
        domain = self.get_entity_domain()
        if domain not in IMPULSE_DOMAINS:
            if not self._unknown_domain_logged:
                self._unknown_domain_logged = True
                _LOGGER.warning(
                    "Gate %s: HA domain %r has no impulse service — open_set commands are ignored; "
                    "use a switch, button or script entity as the gate relay",
                    self.entity_id,
                    domain,
                )
            return None
        if domain in _PRESS_DOMAINS:
            service = SERVICE_PRESS
        elif domain in _TURN_ON_DOMAINS:
            service = SERVICE_TURN_ON
        else:
            service = SERVICE_TURN_ON if self._impulse_service == IMPULSE_SERVICE_TURN_ON else SERVICE_TOGGLE
        return self._build_service_call(domain, service, self.entity_id)


def make_gate_entity(entity_data: dict) -> BaseEntity:
    """Create the right ``gate`` entity for an HA entity.

    Registered as ``CategorySpec.cls`` for the ``gate`` category.  HA
    ``cover`` entities keep the historical :class:`GateEntity`
    (position-aware, unchanged ``model.id`` for existing users); every
    other domain gets the impulse-relay implementation.

    Args:
        entity_data: HA entity registry dict containing entity metadata.

    Returns:
        :class:`GateEntity` for ``cover.*``, :class:`ImpulseGateEntity`
        otherwise.
    """
    entity_id = entity_data.get("entity_id") or ""
    domain = entity_id.split(".", 1)[0] if "." in entity_id else ""
    if domain == "cover":
        return GateEntity(entity_data)
    return ImpulseGateEntity(entity_data)


make_gate_entity.produces = (GateEntity, ImpulseGateEntity)  # type: ignore[attr-defined]
"""Classes :func:`make_gate_entity` can return.

Read by :attr:`~sber_entity_map.CategorySpec.entity_classes`: a factory
registered as ``CategorySpec.cls`` is not a class, so introspecting code
(and the structural tests that walk every device class) needs this
declaration to reach the real implementations."""
