"""Sber Kettle entity -- maps HA water_heater entities to Sber kettle category.

Supports on/off control, water temperature reading, and target temperature
setting.

Two very different kinds of HA entity end up in this category (see
``CATEGORY_DOMAIN_MAP``):

* a plain ``switch`` — a dumb kettle on a smart socket.  It has
  ``turn_on`` / ``turn_off`` and nothing else.
* a ``water_heater`` — a real smart kettle.  Here ``turn_on`` /
  ``turn_off`` are **optional** in Home Assistant: an integration only
  gets them by declaring ``WaterHeaterEntityFeature.ON_OFF``, and the
  SkyKettle-style integrations do not.  Such a kettle is driven purely
  through ``set_operation_mode`` with model-specific mode names taken
  from its ``operation_list`` attribute ("Boil", "Heat", "off", …), and a
  bare ``set_temperature`` only moves the setpoint without ever starting
  the heater.

:class:`KettleEntity` therefore prefers operation modes whenever a
``water_heater`` advertises an ``operation_list``, and falls back to the
historical ``turn_on`` / ``turn_off`` / ``set_temperature`` calls
otherwise — for a ``switch`` always, since no ``switch.set_operation_mode``
service exists in Home Assistant.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import ClassVar

from ..sber_constants import SberFeature, SberValueType
from ..sber_models import make_bool_value, make_integer_value, make_state, normalize_sber_value
from .base_entity import AttrSpec, BaseEntity, CommandResult, _safe_int_parser

_LOGGER = logging.getLogger(__name__)

KETTLE_CATEGORY = "kettle"
"""Sber device category for kettle entities."""

KETTLE_TEMPERATURE_MIN = 60
"""Lowest target temperature offered to Sber, in °C."""

KETTLE_TEMPERATURE_MAX = 100
"""Highest target temperature offered to Sber, in °C (i.e. "boil")."""

KETTLE_TEMPERATURE_STEP = 10
"""Step of the Sber target-temperature slider, in °C."""

MODE_DRIVEN_DOMAIN = "water_heater"
"""The only HA domain that can be driven through ``set_operation_mode``.

``water_heater`` is the sole domain in Home Assistant that both publishes
an ``operation_list`` attribute and registers a ``set_operation_mode``
service.  The ``kettle`` category also accepts a plain ``switch`` (a dumb
kettle on a smart socket, see ``CATEGORY_DOMAIN_MAP``), and a template
``switch`` is free to carry an ``operation_list`` attribute of its own —
routing that entity through ``switch.set_operation_mode`` would raise
``ServiceNotFound`` on every single Sber command."""

KETTLE_OPTION_OFF_MODE = "off_mode"
"""Entity-option key naming the HA operation mode that switches the kettle off."""

KETTLE_OPTION_BOIL_MODE = "boil_mode"
"""Entity-option key naming the HA operation mode that boils the water."""

KETTLE_OPTION_HEAT_MODE = "heat_mode"
"""Entity-option key naming the HA operation mode that heats to a setpoint."""

OFF_MODE_CANDIDATES: tuple[str, ...] = ("off",)
"""Mode names auto-detected as "switch the kettle off" (case-insensitive)."""

BOIL_MODE_CANDIDATES: tuple[str, ...] = ("boil",)
"""Mode names auto-detected as "boil" (case-insensitive)."""

HEAT_MODE_CANDIDATES: tuple[str, ...] = (
    "heat",
    "electric",
    "eco",
    "gas",
    "heat_pump",
    "high_demand",
    "performance",
)
"""Mode names auto-detected as "heat to the setpoint", best match first.

``heat`` is what SkyKettle-style kettles use; the rest are Home
Assistant's own ``water_heater`` constants, which a generic integration
is likely to reuse.  Order is preference order, not alphabetical."""


def _child_lock_parser(value: object) -> bool:
    """Parse child_lock attribute, defaulting to False."""
    return bool(value) if value is not None else False


def _operation_list_parser(value: object) -> tuple[str, ...]:
    """Parse the HA ``operation_list`` attribute into a tuple of mode names.

    Args:
        value: Raw attribute value; anything that is not a list/tuple of
            strings yields an empty tuple (the kettle is then driven the
            legacy way).

    Returns:
        Mode names in the order the integration reported them.
    """
    if not isinstance(value, list | tuple):
        return ()
    return tuple(item for item in value if isinstance(item, str) and item)


def _optional_str(value: object) -> str | None:
    """Normalise an option value into a mode name or ``None``.

    Args:
        value: Raw option value.

    Returns:
        The stripped string, or ``None`` for anything empty / non-string
        (which means "auto-detect this mode").
    """
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


class KettleEntity(BaseEntity):
    """Sber kettle entity for smart kettle devices.

    Maps HA water_heater entities to the Sber 'kettle' category with support for:
    - On/off control
    - Current water temperature reading
    - Target temperature setting (60-100, step 10)
    - Child lock (read-only from HA attributes)
    - Water level and low water level indicators

    The Sber ``kettle`` spec has no notion of a "mode": the whole mapping
    from Sber's ``on_off`` + ``kitchen_water_temperature_set`` onto a
    kettle's own operation modes lives here.
    """

    ENTITY_OPTION_KEYS: ClassVar[tuple[str, ...]] = (
        KETTLE_OPTION_OFF_MODE,
        KETTLE_OPTION_BOIL_MODE,
        KETTLE_OPTION_HEAT_MODE,
    )

    ENTITY_OPTIONS_BLOCK: ClassVar[str] = "kettle_options"

    ATTR_SPECS: ClassVar[tuple[AttrSpec, ...]] = (
        AttrSpec(
            field="_current_temperature",
            attr_keys=("current_temperature",),
            parser=_safe_int_parser,
        ),
        AttrSpec(
            field="_target_temperature",
            attr_keys=("temperature",),
            parser=_safe_int_parser,
        ),
        AttrSpec(
            field="_child_lock",
            attr_keys=("child_lock",),
            parser=_child_lock_parser,
            default=False,
        ),
        AttrSpec(
            field="_water_level",
            attr_keys=("water_level",),
            parser=_safe_int_parser,
        ),
        AttrSpec(
            field="_operation_list",
            attr_keys=("operation_list",),
            parser=_operation_list_parser,
            default=(),
        ),
        AttrSpec(
            field="_operation_mode",
            attr_keys=("operation_mode",),
        ),
        AttrSpec(
            field="_ha_max_temperature",
            attr_keys=("max_temp",),
            parser=_safe_int_parser,
        ),
    )

    def __init__(self, entity_data: dict) -> None:
        """Initialize kettle entity.

        Args:
            entity_data: HA entity registry dict containing entity metadata.
        """
        super().__init__(KETTLE_CATEGORY, entity_data)
        self.current_state: bool = False
        self._current_temperature: int | None = None
        self._target_temperature: int | None = None
        self._child_lock: bool = False
        self._water_level: int | None = None
        self._operation_list: tuple[str, ...] = ()
        self._operation_mode: str | None = None
        self._ha_max_temperature: int | None = None
        # User-chosen mode names; None means "auto-detect from operation_list".
        self._off_mode: str | None = None
        self._boil_mode: str | None = None
        self._heat_mode: str | None = None
        self._missing_mode_logged: set[str] = set()

    # -- user options ---------------------------------------------------

    def apply_entity_options(self, options: dict) -> None:
        """Apply per-entity kettle options from ``entry.options``.

        Args:
            options: Mapping with optional ``off_mode`` / ``boil_mode`` /
                ``heat_mode`` keys, each naming one entry of the entity's
                HA ``operation_list``.  An empty value restores
                auto-detection.  Invalid values are ignored here (a
                hand-edited config must not break entity loading) — the
                WebSocket command validates them up front instead, see
                :meth:`validate_entity_options`.
        """
        if not options:
            return
        if KETTLE_OPTION_OFF_MODE in options:
            self._off_mode = _optional_str(options[KETTLE_OPTION_OFF_MODE])
        if KETTLE_OPTION_BOIL_MODE in options:
            self._boil_mode = _optional_str(options[KETTLE_OPTION_BOIL_MODE])
        if KETTLE_OPTION_HEAT_MODE in options:
            self._heat_mode = _optional_str(options[KETTLE_OPTION_HEAT_MODE])
        self._missing_mode_logged.clear()
        _LOGGER.debug(
            "Kettle options for %s: off=%r boil=%r heat=%r",
            self.entity_id,
            self._off_mode,
            self._boil_mode,
            self._heat_mode,
        )

    def validate_entity_options(self, options: dict) -> None:
        """Reject mode names this entity does not actually offer.

        A mode that is not in the entity's ``operation_list`` would be
        silently dropped by the HA service call, leaving the user with a
        kettle that acknowledges commands and never heats — so the
        mismatch is reported at the moment they save it.

        Args:
            options: Mapping submitted by the panel.

        Raises:
            ValueError: When a key is unknown to this class, when a value
                is not a string, or when it names a mode the entity does
                not report.
        """
        super().validate_entity_options(options)
        chosen = {key: options[key] for key in self.ENTITY_OPTION_KEYS if key in options}
        wanted = {key: _optional_str(value) for key, value in chosen.items()}
        for key, value in chosen.items():
            if value is not None and not isinstance(value, str):
                raise ValueError(f"{self.entity_id}: {key} must be a mode name, got {value!r}")
        if not any(wanted.values()):
            return
        available = self.available_operation_modes
        if not available:
            raise ValueError(
                f"{self.entity_id} reports no operation modes (HA attribute 'operation_list' is empty) — "
                "leave the mode fields empty; the bridge will use turn_on / turn_off instead"
            )
        for key, mode in wanted.items():
            if mode is not None and mode not in available:
                raise ValueError(
                    f"{self.entity_id}: '{mode}' is not one of this kettle's operation modes "
                    f"({', '.join(available)}) — pick one of them for {key}"
                )

    def entity_options_state(self) -> dict[str, object]:
        """Return the kettle option block rendered by the panel.

        The panel needs three things: what the user picked (empty string
        means "auto"), what the entity actually offers so the dropdowns
        are not free text, and what the bridge resolved — the last one is
        what a user who configured nothing must be able to check.

        Returns:
            Explicit ``off_mode`` / ``boil_mode`` / ``heat_mode`` choices,
            the entity's ``operation_list``, and the ``resolved_*``
            counterparts (empty string when nothing could be resolved).
        """
        return {
            KETTLE_OPTION_OFF_MODE: self._off_mode or "",
            KETTLE_OPTION_BOIL_MODE: self._boil_mode or "",
            KETTLE_OPTION_HEAT_MODE: self._heat_mode or "",
            "operation_list": list(self.available_operation_modes),
            "resolved_off_mode": self._resolve_mode(self._off_mode, OFF_MODE_CANDIDATES) or "",
            "resolved_boil_mode": self._resolve_mode(self._boil_mode, BOIL_MODE_CANDIDATES) or "",
            "resolved_heat_mode": self._resolve_mode(self._heat_mode, HEAT_MODE_CANDIDATES) or "",
        }

    # -- operation modes ------------------------------------------------

    @property
    def available_operation_modes(self) -> tuple[str, ...]:
        """Operation modes this entity can actually be driven with.

        The raw ``operation_list`` attribute filtered by the one thing it
        cannot tell us: whether a ``set_operation_mode`` service exists
        for this entity at all.  Only :data:`MODE_DRIVEN_DOMAIN` has one,
        so for every other domain the answer is "no modes", no matter
        what the attribute says.

        Returns:
            Mode names in the order the integration reported them, or an
            empty tuple when this entity is not mode-driven.
        """
        if self.get_entity_domain() != MODE_DRIVEN_DOMAIN:
            return ()
        return self._operation_list

    @property
    def supports_operation_modes(self) -> bool:
        """True when the HA entity is driven through ``set_operation_mode``.

        Decided by the entity itself: a ``switch`` kettle (and any
        ``water_heater`` that reports no ``operation_list``) keeps the
        historical ``turn_on`` / ``turn_off`` path untouched.
        """
        return bool(self.available_operation_modes)

    def _resolve_mode(self, explicit: str | None, candidates: tuple[str, ...]) -> str | None:
        """Resolve one logical mode to a real name from ``operation_list``.

        The user's explicit choice wins, provided the entity still offers
        it — a kettle can change its mode list after a firmware update,
        and pushing a mode that no longer exists would do nothing at all.
        Otherwise the known names are matched case-insensitively, which is
        what makes the feature work with no configuration for the common
        ``off`` / ``Boil`` / ``Heat`` lists.

        Args:
            explicit: Mode chosen by the user, or ``None`` for auto-detect.
            candidates: Known names in preference order.

        Returns:
            A name present in ``operation_list``, or ``None`` when nothing
            matched.
        """
        available = self.available_operation_modes
        if not available:
            return None
        if explicit is not None:
            if explicit in available:
                return explicit
            self._log_missing_mode_once(
                f"explicit:{explicit}",
                "configured mode %r is not offered by %s any more (available: %s) — falling back to auto-detection",
                explicit,
                self.entity_id,
                ", ".join(available),
            )
        lowered: dict[str, str] = {}
        for mode in available:
            lowered.setdefault(mode.lower(), mode)
        for candidate in candidates:
            match = lowered.get(candidate)
            if match is not None:
                return match
        return None

    def _log_missing_mode_once(self, token: str, message: str, *args: object) -> None:
        """Emit a mode-related warning at most once per entity instance.

        The command path runs on every Sber request, so an unconditional
        warning would flood the log for a kettle whose mode names we
        cannot recognise.

        Args:
            token: De-duplication key.
            message: ``%``-style log message.
            *args: Message arguments.
        """
        if token in self._missing_mode_logged:
            return
        self._missing_mode_logged.add(token)
        _LOGGER.warning(message, *args)

    @property
    def _boil_temperature(self) -> int:
        """Target temperature at which "heat" becomes "boil", in °C.

        Normally the top of the Sber slider
        (:data:`KETTLE_TEMPERATURE_MAX`).  A kettle that reports a lower
        ``max_temp`` in Home Assistant cannot be asked for anything above
        it, so its own maximum is the boil point instead — otherwise the
        top of the Sber slider would set a temperature the kettle never
        reaches and never announce that it is boiling.
        """
        ha_max = self._ha_max_temperature
        if ha_max is not None and KETTLE_TEMPERATURE_MIN < ha_max < KETTLE_TEMPERATURE_MAX:
            return ha_max
        return KETTLE_TEMPERATURE_MAX

    # -- HA state -------------------------------------------------------

    def fill_by_ha_state(self, ha_state: dict) -> None:
        """Parse HA state and update kettle attributes.

        Args:
            ha_state: HA state dict with 'state' and 'attributes' keys.
        """
        super().fill_by_ha_state(ha_state)
        attrs = ha_state.get("attributes", {})
        self._apply_attr_specs(attrs)
        state_str = ha_state.get("state", "")
        self.current_state = state_str not in ("off", "idle", "unavailable", "unknown")
        # A mode-driven kettle reports its *mode* as the HA state, and an
        # "off" mode may be named anything ("Выключен"), so the generic
        # word list above cannot recognise it.
        off_mode = self._resolve_mode(self._off_mode, OFF_MODE_CANDIDATES)
        if off_mode is not None and self._current_mode == off_mode:
            self.current_state = False

    @property
    def _current_mode(self) -> str | None:
        """Operation mode the kettle is in right now, if it reports one.

        ``WaterHeaterEntity`` exposes the current operation as the HA
        *state*; the ``operation_mode`` attribute is read first anyway
        because some integrations mirror it there.
        """
        if isinstance(self._operation_mode, str) and self._operation_mode:
            return self._operation_mode
        return self.state if isinstance(self.state, str) else None

    def _create_features_list(self) -> list[str]:
        """Return Sber feature list for kettle capabilities.

        Returns:
            List of Sber feature strings supported by this entity.
        """
        features = [*super()._create_features_list(), "on_off"]
        features.append("kitchen_water_temperature")
        features.append("kitchen_water_temperature_set")
        features.append("kitchen_water_level")
        features.append("kitchen_water_low_level")
        features.append("child_lock")
        return features

    def create_allowed_values_list(self) -> dict[str, dict]:
        """Build allowed values map for temperature setting.

        The range is deliberately **not** derived from the entity's HA
        ``min_temp`` / ``max_temp``: ``model.id`` is a digest of the
        advertised capabilities, so making the range device-specific would
        hand every existing user a brand-new Sber model for a kettle that
        did not change.

        Returns:
            Dict mapping feature key to its allowed INTEGER values descriptor.
        """
        return {
            "kitchen_water_temperature_set": {
                "type": "INTEGER",
                "integer_values": {
                    "min": str(KETTLE_TEMPERATURE_MIN),
                    "max": str(KETTLE_TEMPERATURE_MAX),
                    "step": str(KETTLE_TEMPERATURE_STEP),
                },
            }
        }

    def _build_current_state(self) -> dict[str, dict]:
        """Build Sber current state payload with kettle attributes.

        Returns:
            Dict mapping entity_id to its Sber state representation.
        """
        states = [
            make_state(SberFeature.ONLINE, make_bool_value(self._is_online)),
            make_state(SberFeature.ON_OFF, make_bool_value(self.current_state)),
        ]
        if self._current_temperature is not None:
            states.append(
                make_state(SberFeature.KITCHEN_WATER_TEMPERATURE, make_integer_value(self._current_temperature))
            )
            # Low water level heuristic: temperature below 30 indicates no/little water
            low_level = self._current_temperature < 30
            states.append(make_state(SberFeature.KITCHEN_WATER_LOW_LEVEL, make_bool_value(low_level)))
        if self._water_level is not None:
            states.append(make_state(SberFeature.KITCHEN_WATER_LEVEL, make_integer_value(self._water_level)))
        if self._target_temperature is not None:
            states.append(
                make_state(SberFeature.KITCHEN_WATER_TEMPERATURE_SET, make_integer_value(self._target_temperature))
            )
        states.append(make_state(SberFeature.CHILD_LOCK, make_bool_value(self._child_lock)))
        return {self.entity_id: {"states": states}}

    # -- commands -------------------------------------------------------

    def process_cmd(self, cmd_data: dict) -> list[CommandResult]:
        """Turn a Sber command into HA service calls.

        Mode-driven kettles are handled as a whole payload rather than
        key by key, because ``on_off`` and
        ``kitchen_water_temperature_set`` describe **one** intent when
        they arrive together ("heat this water to 80") and would
        otherwise produce two contradictory mode switches.

        Falls back to :meth:`BaseEntity.process_cmd` — i.e. to the
        historical ``turn_on`` / ``turn_off`` / ``set_temperature`` calls
        — for a kettle without operation modes, and for a mode-driven one
        whose relevant mode could not be resolved.

        Args:
            cmd_data: Command payload with a ``states`` list.

        Returns:
            List of HA service call dicts to execute.
        """
        if not self.supports_operation_modes:
            return super().process_cmd(cmd_data)

        on_off: bool | None = None
        temperature: int | None = None
        understood = False
        for item in cmd_data.get("states", []):
            key = item.get("key", "")
            value = normalize_sber_value(item.get("value", {}))
            if key == SberFeature.ON_OFF and value.get("type") == SberValueType.BOOL:
                on_off = bool(value.get("bool_value", False))
                understood = True
            elif key == SberFeature.KITCHEN_WATER_TEMPERATURE_SET and value.get("type") == SberValueType.INTEGER:
                parsed = _safe_int_parser(value.get("integer_value"))
                if parsed is not None and self._is_requestable_temperature(parsed):
                    temperature = parsed
                    understood = True

        if not understood:
            return super().process_cmd(cmd_data)
        plan = self._plan_mode_calls(on_off, temperature)
        if plan is None:
            return super().process_cmd(cmd_data)
        return plan

    def _is_requestable_temperature(self, temperature: int) -> bool:
        """Whether a target temperature can be a real user request.

        The Sber slider for this category is declared in
        :meth:`create_allowed_values_list` as
        ``KETTLE_TEMPERATURE_MIN..KETTLE_TEMPERATURE_MAX``, so a value
        outside that range never came from a user moving it.  The one that
        actually arrives is ``0``: Sber speaks proto3 and omits fields
        holding the default, so a payload item of ``{"type": "INTEGER"}``
        with no ``integer_value`` reads as zero.  Starting a heating cycle
        on that would be acting on a field the cloud meant to say nothing
        about — and ``set_temperature(0)`` is also the call most likely to
        be refused by the integration, which is precisely when the mode
        must not be switched (see :meth:`_plan_mode_calls`).

        Args:
            temperature: Parsed target in °C.

        Returns:
            ``True`` when the value lies inside the advertised range.
        """
        if KETTLE_TEMPERATURE_MIN <= temperature <= KETTLE_TEMPERATURE_MAX:
            return True
        _LOGGER.debug(
            "Kettle %s: ignoring target temperature %d °C — outside the advertised %d-%d °C range",
            self.entity_id,
            temperature,
            KETTLE_TEMPERATURE_MIN,
            KETTLE_TEMPERATURE_MAX,
        )
        return False

    def _plan_mode_calls(self, on_off: bool | None, temperature: int | None) -> list[CommandResult] | None:
        """Build the mode-driven service calls for one Sber command.

        Rules:

        * ``on_off=False`` → the off mode, whatever the payload also says:
          "switch it off" is never ambiguous.
        * a target at (or above) the boil point, or no target at all →
          the boil mode, or — when no mode name reads as "boil" — the
          heat mode.  Sber's own slider tops out at
          :data:`KETTLE_TEMPERATURE_MAX`, and a kettle asked to reach
          100 °C is a kettle asked to boil; but a kettle whose list is
          ``off / eco / electric / performance`` (Home Assistant's own
          names) or ``off / Boil+Heat / Heat`` has no literal "boil" and
          would otherwise degrade to ``turn_on`` — the one service a
          mode-driven kettle does **not** implement, i.e. "on" would do
          nothing at all.  Heating with the kettle's own setpoint is a
          far better answer than silence.
        * a lower target → ``set_temperature`` **first**, then the heat
          mode.  The order matters: a kettle starts heating the instant
          the mode is set, and it heats towards whatever setpoint it
          holds at that moment.  Setting the mode first would run a full
          cycle against the *previous* setpoint and only then accept the
          new one — a kettle asked for 60 °C would boil once before
          obeying.

          The order is *not* a guarantee, and the residual risk is real:
          the bridge issues both calls fire-and-forget
          (``SberCommandDispatcher._call_ha_service`` uses
          ``blocking=False`` and only logs a failure), so a rejected
          ``set_temperature`` — routine on a BLE kettle — still lets the
          mode switch through and the kettle then runs one cycle against
          its stored setpoint, which on a SkyKettle-style device is
          typically the boil point.  Folding the pair into a single
          ``set_temperature(temperature=…, operation_mode=…)`` call does
          not help: those integrations read only ``ATTR_TEMPERATURE`` and
          ignore ``operation_mode``.  The alternative ordering trades
          this rare case for a *certain* wrong cycle on every command,
          so it stays as it is.

        Args:
            on_off: Requested power state, or ``None`` when the payload
                carried no ``on_off``.
            temperature: Requested target in °C, or ``None``.

        Returns:
            The service calls to execute, or ``None`` when the mode this
            command needs is unknown — the caller then falls back to the
            legacy calls.
        """
        domain = self.get_entity_domain()
        if on_off is False:
            off_mode = self._resolve_mode(self._off_mode, OFF_MODE_CANDIDATES)
            if off_mode is None:
                self._warn_unresolved(KETTLE_OPTION_OFF_MODE)
                return None
            return [self._build_set_operation_mode(domain, off_mode)]

        if on_off is None and temperature is None:
            return []

        if temperature is None or temperature >= self._boil_temperature:
            boil_mode = self._resolve_mode(self._boil_mode, BOIL_MODE_CANDIDATES)
            if boil_mode is None:
                boil_mode = self._resolve_mode(self._heat_mode, HEAT_MODE_CANDIDATES)
                if boil_mode is not None:
                    self._log_missing_mode_once(
                        f"boil_as_heat:{boil_mode}",
                        "Kettle %s: no operation mode reads as 'boil' (available: %s) — using the heat mode %r "
                        "instead; set the '%s' option if this kettle boils in a different mode",
                        self.entity_id,
                        ", ".join(self.available_operation_modes),
                        boil_mode,
                        KETTLE_OPTION_BOIL_MODE,
                    )
            if boil_mode is None:
                self._warn_unresolved(KETTLE_OPTION_BOIL_MODE)
                return None
            return [self._build_set_operation_mode(domain, boil_mode)]

        heat_mode = self._resolve_mode(self._heat_mode, HEAT_MODE_CANDIDATES)
        if heat_mode is None:
            self._warn_unresolved(KETTLE_OPTION_HEAT_MODE)
            return None
        return [
            self._build_service_call(domain, "set_temperature", self.entity_id, {"temperature": temperature}),
            self._build_set_operation_mode(domain, heat_mode),
        ]

    def _warn_unresolved(self, option: str) -> None:
        """Warn once that a needed operation mode could not be determined.

        Args:
            option: The entity option that would fix it.
        """
        self._log_missing_mode_once(
            f"unresolved:{option}",
            "Kettle %s: cannot tell which operation mode means '%s' (available: %s) — "
            "using turn_on / turn_off instead; set the '%s' option to pick one",
            self.entity_id,
            option.removesuffix("_mode"),
            ", ".join(self.available_operation_modes),
            option,
        )

    def _build_set_operation_mode(self, domain: str, mode: str) -> CommandResult:
        """Build a ``set_operation_mode`` service call.

        Args:
            domain: HA domain of this entity.
            mode: Mode name taken from the entity's ``operation_list``.

        Returns:
            Service-call descriptor for the bridge.
        """
        return self._build_service_call(domain, "set_operation_mode", self.entity_id, {"operation_mode": mode})

    @property
    def _cmd_handlers(self) -> dict[str, Callable[[dict], list[CommandResult]]]:
        """Return dispatch map for kettle commands (legacy, mode-less path)."""
        return {
            SberFeature.ON_OFF: self._cmd_on_off,
            SberFeature.KITCHEN_WATER_TEMPERATURE_SET: self._cmd_water_temp_set,
        }

    def _cmd_on_off(self, value: dict) -> list[CommandResult]:
        """Handle ``on_off``: turn_on / turn_off (domain auto-detected from entity_id).

        Args:
            value: Sber value dict from the command payload.

        Returns:
            List of HA service call dicts to execute.
        """
        if value.get("type") != SberValueType.BOOL:
            return []
        on = value.get("bool_value", False)
        domain = self.get_entity_domain()
        return [self._build_on_off_service_call(self.entity_id, domain, on)]

    def _cmd_water_temp_set(self, value: dict) -> list[CommandResult]:
        """Handle ``kitchen_water_temperature_set``: water_heater.set_temperature.

        Args:
            value: Sber value dict from the command payload.

        Returns:
            List of HA service call dicts to execute.
        """
        if value.get("type") != SberValueType.INTEGER:
            return []
        temp = _safe_int_parser(value.get("integer_value"))
        if temp is None:
            return []
        domain = self.get_entity_domain()
        return [self._build_service_call(domain, "set_temperature", self.entity_id, {"temperature": temp})]
