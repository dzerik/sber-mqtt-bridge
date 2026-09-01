"""Sber Vacuum Cleaner entity -- maps HA vacuum entities to Sber vacuum_cleaner category.

Supports start/resume/pause/return_to_dock commands, status reporting,
cleaning program (derived from the HA mode list) and battery level.
Every ENUM value crossing to the cloud comes from Sber's documented
vocabulary in ``_generated/reference_values.py``; HA names that denote
nothing Sber knows are dropped rather than translated by guesswork.
Battery is sourced from
the deprecated HA vacuum ``battery_level`` attribute (legacy fallback,
removal planned in HA 2026.8) or from a linked battery sensor entity via
the ``battery`` link role.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Callable
from typing import ClassVar

from .._generated.reference_values import FEATURE_ENUM_VALUES
from ..sber_constants import SberFeature, SberValueType
from ..sber_models import make_bool_value, make_enum_value, make_integer_value, make_state
from .base_entity import ROLE_BATTERY, AttrSpec, BaseEntity, CommandResult, _safe_int_parser
from .utils.enum_matcher import invert_value_map, map_ha_values, match_enum_value

_LOGGER = logging.getLogger(__name__)

VACUUM_CLEANER_CATEGORY = "vacuum_cleaner"
"""Sber device category for vacuum cleaner entities."""

PROGRAM_VALUES: frozenset[str] = FEATURE_ENUM_VALUES["vacuum_cleaner_program"]
"""Cleaning routes Sber documents: ``perimeter``, ``spot``, ``smart``, ``random_route``.

**Known mismatch, deliberately accepted.**  These are cleaning *routes*,
but the only list Home Assistant's ``vacuum`` entity offers is
``fan_speed_list``, which is suction power.  The two coincide only by
name, so:

* a robot whose modes read ``Silent / Standard / Turbo`` — the common
  case — matches nothing and gets no route control at all, which is
  honest but means the Sber app shows no program selector;
* a robot that happens to spell a mode ``Spot`` or ``Smart`` gets the
  control, and choosing that route in the app calls
  ``vacuum.set_fan_speed`` — i.e. it changes **suction, not route**.

Both beat the previous behaviour (publishing raw HA fan-speed names,
which Sber cannot route at all), and neither can be fixed here: HA has no
route-carrying attribute to read.  Fixing it properly needs a per-device
mapping the user configures, which is why no synonym is invented for
``auto`` — that is a common fan-speed name and would silently hand the
route control to every robot that has it."""

CLEANING_TYPE_VALUES: frozenset[str] = FEATURE_ENUM_VALUES["vacuum_cleaner_cleaning_type"]
"""Cleaning types Sber documents: ``dry``, ``wet``, ``mixed``."""

_HA_STATE_TO_SBER_STATUS: dict[str, str] = {
    "cleaning": "cleaning",
    "returning": "returning_to_dock",
    "docked": "docked",
    "paused": "pause",
    "idle": "pause",
    "error": "pause",
}
"""Mapping from HA vacuum state to the Sber ``vacuum_cleaner_status`` ENUM.

Sber documents exactly four values — ``cleaning``, ``docked``, ``pause``,
``returning_to_dock`` — and nothing else routes.  Three HA states have no
counterpart, so each is mapped to the least wrong of the four:

* ``idle`` → ``pause``.  HA has a separate ``docked`` state for "sitting
  on the base", so ``idle`` means the robot has stopped *off* the dock
  with a job it can still resume.  That is what ``pause`` describes;
  reporting ``docked`` would tell the app the robot is home and charging
  when it is stranded in the middle of the floor.
* ``error`` → ``pause``.  Sber's vocabulary cannot express a fault at
  all.  ``pause`` at least reports the two things that are certainly
  true — not cleaning, not on the dock — and leaves the app's resume
  action pointing at the robot the user has to rescue anyway.
* anything else (``unknown``, an integration-specific state) →
  :data:`_DEFAULT_SBER_STATUS`.
"""

_DEFAULT_SBER_STATUS = "docked"
"""Status reported for an HA state we cannot interpret.

The resting value: it claims no activity that may not be happening.  An
unavailable robot is separately reported through ``online: false``, so the
app does not act on this value anyway.
"""

_SBER_CMD_TO_HA_SERVICE: dict[str, str] = {
    "start": "start",
    "resume": "start",
    "pause": "pause",
    "return_to_dock": "return_to_base",
}
"""Mapping from the Sber ``vacuum_cleaner_command`` ENUM to an HA vacuum service.

The keys are exactly Sber's documented vocabulary
(``start, resume, pause, return_to_dock``) because they double as the
published ``allowed_values``.  ``stop`` used to be declared here and is
gone: it is not in the vocabulary, so the cloud would never send it while
the app rendered a button for it.  ``resume`` maps to ``vacuum.start``,
which is HA's own way of continuing a paused job.
"""

_PROGRAM_SYNONYMS: dict[str, str] = {
    "edge": "perimeter",
    "edgeclean": "perimeter",
    "edgecleaning": "perimeter",
    "random": "random_route",
}
"""HA mode names that denote a documented Sber route under another word.

Keyed by the normalized HA token (see
:func:`~.utils.enum_matcher.normalize_enum_token`).  "Edge" is what most
vendors call cleaning along the walls, i.e. Sber's ``perimeter``.
Everything not listed and not spelled like a Sber value is left
unmapped — an invented program is a dead control.
"""


class VacuumCleanerEntity(BaseEntity):
    """Sber vacuum cleaner entity for robot vacuum devices.

    Maps HA vacuum entities to the Sber 'vacuum_cleaner' category with support for:
    - start / resume / pause / return_to_dock commands
    - Status reporting, folded onto Sber's four documented values
      (see :data:`_HA_STATE_TO_SBER_STATUS`)
    - Cleaning program, when the HA mode list names a documented Sber
      route (:data:`PROGRAM_VALUES`)
    - Battery percentage (legacy ``battery_level`` attribute or linked
      battery sensor via the ``battery`` link role)

    Every ENUM this class emits is taken from
    :data:`~custom_components.sber_mqtt_bridge._generated.reference_values.FEATURE_ENUM_VALUES`.
    HA's own vocabulary (fan-speed names, ``STATE_*`` constants) overlaps
    it only by accident, and a value outside the documented set is one the
    cloud cannot route — it renders a control that never works.

    Command handlers address the entity in **its own** HA domain
    (:meth:`get_entity_domain`) rather than a hard-coded ``vacuum``, so an
    entity forced into this category by a user type override is driven
    through services that actually exist for it.  For a ``vacuum.*``
    entity — the only domain this category maps to — the emitted calls
    are unchanged.
    """

    LINKABLE_ROLES = (ROLE_BATTERY,)
    """Linked companion roles: a battery sensor supplies ``battery_percentage``.

    HA deprecated the vacuum ``battery_level`` attribute (removal in
    2026.8); migrated integrations expose battery as a separate sensor
    entity, which users link here.
    """

    ATTR_SPECS: ClassVar[tuple[AttrSpec, ...]] = (
        AttrSpec(
            field="_fan_speed",
            attr_keys=("fan_speed",),
        ),
        AttrSpec(
            field="_fan_speed_list",
            # ``None`` (not ``[]``) when absent, so ``preserve_on_missing``
            # keeps the list we already had.  Same reasoning as the TV's
            # ``_source_list``: an integration that momentarily reports no
            # modes would otherwise erase the program mapping, silently
            # dropping every ``vacuum_cleaner_program`` command and
            # churning ``model.id``.
            converter=lambda attrs: attrs.get("fan_speed_list") or None,
            default=[],
            preserve_on_missing=True,
        ),
        AttrSpec(
            field="_battery_level",
            attr_keys=("battery_level",),
            parser=_safe_int_parser,
            preserve_on_missing=True,
        ),
        AttrSpec(
            field="_cleaning_type",
            attr_keys=("cleaning_type",),
        ),
    )

    def __init__(self, entity_data: dict) -> None:
        """Initialize vacuum cleaner entity.

        Args:
            entity_data: HA entity registry dict containing entity metadata.
        """
        super().__init__(VACUUM_CLEANER_CATEGORY, entity_data)
        self._status: str = _DEFAULT_SBER_STATUS
        self._fan_speed: str | None = None
        self._fan_speed_list: list[str] = []
        self._battery_level: int | None = None
        self._cleaning_type: str | None = None
        self._program_to_sber: dict[str, str] = {}
        self._program_to_ha: dict[str, str] = {}

    def fill_by_ha_state(self, ha_state: dict) -> None:
        """Parse HA state and update vacuum cleaner attributes.

        Args:
            ha_state: HA state dict with 'state' and 'attributes' keys.
        """
        super().fill_by_ha_state(ha_state)
        attrs = ha_state.get("attributes", {})
        self._apply_attr_specs(attrs)
        self._program_to_sber = map_ha_values(self._fan_speed_list, PROGRAM_VALUES, synonyms=_PROGRAM_SYNONYMS)
        self._program_to_ha = invert_value_map(self._program_to_sber)
        ha_status = ha_state.get("state", "")
        self._status = _HA_STATE_TO_SBER_STATUS.get(ha_status, _DEFAULT_SBER_STATUS)

    def update_linked_data(self, role: str, ha_state: dict) -> None:
        """Inject battery percentage from a linked battery sensor entity.

        HA deprecated the vacuum ``battery_level`` attribute; migrated
        integrations publish battery as a separate sensor entity. When
        such a sensor is linked with the ``battery`` role, its state
        feeds the Sber ``battery_percentage`` feature.

        Args:
            role: Link role name (only ``battery`` is handled).
            ha_state: HA state dict with 'state' containing the reading.
        """
        if role == "battery":
            state_val = ha_state.get("state")
            if state_val not in (None, "unknown", "unavailable"):
                with contextlib.suppress(TypeError, ValueError):
                    self._battery_level = int(float(state_val))

    @property
    def _sber_cleaning_type(self) -> str | None:
        """Return the HA ``cleaning_type`` attribute as a documented Sber value.

        Returns:
            One of :data:`CLEANING_TYPE_VALUES`, or ``None`` when the
            attribute is absent or names something Sber has no value for.
        """
        if not self._cleaning_type:
            return None
        return match_enum_value(self._cleaning_type, CLEANING_TYPE_VALUES)

    def _create_features_list(self) -> list[str]:
        """Return Sber feature list for vacuum capabilities.

        ``vacuum_cleaner_program`` and ``vacuum_cleaner_cleaning_type``
        are advertised only when the HA side offers at least one value
        that Sber documents.  Declaring either with home-grown values
        (fan-speed names such as ``turbo``) produced a control the cloud
        could not route.

        Returns:
            List of Sber feature strings supported by this entity.
        """
        features = [
            *super()._create_features_list(),
            "vacuum_cleaner_command",
            "vacuum_cleaner_status",
        ]
        if self._program_to_sber:
            features.append("vacuum_cleaner_program")
        if self._sber_cleaning_type is not None:
            features.append("vacuum_cleaner_cleaning_type")
        if self._battery_level is not None:
            features.append("battery_percentage")
        return features

    def create_allowed_values_list(self) -> dict[str, dict]:
        """Build allowed values map for vacuum features.

        Both entries carry Sber's own vocabulary, never HA's: the app
        renders exactly what is declared and echoes it back as a command,
        so an undocumented value is a dead button.

        Returns:
            Dict mapping feature key to its allowed ENUM values descriptor.
        """
        allowed: dict[str, dict] = {
            "vacuum_cleaner_command": {
                "type": "ENUM",
                "enum_values": {"values": list(_SBER_CMD_TO_HA_SERVICE.keys())},
            },
        }
        if self._program_to_sber:
            allowed["vacuum_cleaner_program"] = {
                "type": "ENUM",
                "enum_values": {"values": list(self._program_to_sber.values())},
            }
        # vacuum_cleaner_status and vacuum_cleaner_cleaning_type are read-only:
        # not included in allowed_values to prevent Sber from sending commands
        # for features that have no HA service handler.
        return allowed

    def _build_current_state(self) -> dict[str, dict]:
        """Build Sber current state payload with vacuum attributes.

        Returns:
            Dict mapping entity_id to its Sber state representation.
        """
        states = [
            make_state(SberFeature.ONLINE, make_bool_value(self._is_online)),
            make_state(SberFeature.VACUUM_CLEANER_STATUS, make_enum_value(self._status)),
        ]
        sber_program = self._program_to_sber.get(self._fan_speed or "")
        if sber_program:
            states.append(make_state(SberFeature.VACUUM_CLEANER_PROGRAM, make_enum_value(sber_program)))
        sber_cleaning_type = self._sber_cleaning_type
        if sber_cleaning_type:
            states.append(make_state(SberFeature.VACUUM_CLEANER_CLEANING_TYPE, make_enum_value(sber_cleaning_type)))
        if self._battery_level is not None:
            states.append(make_state(SberFeature.BATTERY_PERCENTAGE, make_integer_value(self._battery_level)))
        return {self.entity_id: {"states": states}}

    @property
    def _cmd_handlers(self) -> dict[str, Callable[[dict], list[CommandResult]]]:
        """Return dispatch map for vacuum cleaner commands."""
        return {
            SberFeature.VACUUM_CLEANER_COMMAND: self._cmd_vacuum_command,
            SberFeature.VACUUM_CLEANER_PROGRAM: self._cmd_vacuum_program,
        }

    def _cmd_vacuum_command(self, value: dict) -> list[CommandResult]:
        """Handle ``vacuum_cleaner_command``: start / resume / pause / return_to_dock.

        Args:
            value: Sber value dict from the command payload.

        Returns:
            List of HA service call dicts to execute.
        """
        if value.get("type") != SberValueType.ENUM:
            return []
        ha_service = _SBER_CMD_TO_HA_SERVICE.get(value.get("enum_value") or "")
        if ha_service is None:
            return []
        return [self._build_service_call(self.get_entity_domain(), ha_service, self.entity_id)]

    def _cmd_vacuum_program(self, value: dict) -> list[CommandResult]:
        """Handle ``vacuum_cleaner_program``: vacuum.set_fan_speed.

        The Sber route name is translated back to the HA mode it was
        derived from — ``vacuum.set_fan_speed`` only accepts a member of
        ``fan_speed_list``, so forwarding ``perimeter`` verbatim would be
        rejected by HA.  A value this device never advertised is dropped.

        Args:
            value: Sber value dict from the command payload.

        Returns:
            List of HA service call dicts to execute.
        """
        if value.get("type") != SberValueType.ENUM:
            return []
        program = value.get("enum_value")
        if not program:
            return []
        fan_speed = self._program_to_ha.get(program)
        if fan_speed is None:
            # Warning, not debug — see the matching note in ``TvEntity``:
            # a dropped command is a dead button in the Sber app.
            _LOGGER.warning(
                "Sber asked %s for program '%s', which maps to no current HA mode (known: %s) — ignoring",
                self.entity_id,
                program,
                sorted(self._program_to_ha),
            )
            return []
        return [
            self._build_service_call(
                self.get_entity_domain(), "set_fan_speed", self.entity_id, {"fan_speed": fan_speed}
            )
        ]
