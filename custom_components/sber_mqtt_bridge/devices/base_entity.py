"""Base entity class for Sber Smart Home device representations.

All device types (light, relay, climate, etc.) inherit from BaseEntity.
It defines the contract for converting between HA states and Sber JSON protocol.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import math
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import ClassVar, TypedDict

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN

from .._generated.category_features import CATEGORY_REFERENCE_FEATURES
from ..sber_constants import SERVICE_CALL_TYPE, SERVICE_TURN_OFF, SERVICE_TURN_ON
from ..sber_models import normalize_sber_value

_LOGGER = logging.getLogger(__name__)

ALWAYS_PUBLISHED_FEATURES: frozenset[str] = frozenset({"online"})
"""Feature keys that bypass the declared-features publish filter.

``online`` is obligatory for **every** Sber category (see
``_generated/obligatory_features.py`` — it appears in every entry), and
Sber drops a device whose publish lacks it.  Filtering it out because a
buggy ``_create_features_list`` forgot to declare it, or because a user
removed it via ``sber_features_remove``, would be strictly worse than
publishing an undeclared key, so it is always let through.
"""

EXCLUSIVE_SERVICE_DATA: dict[tuple[str, str], tuple[frozenset[str], ...]] = {
    ("light", "turn_on"): (
        # ``vol.Exclusive`` groups of ``LIGHT_TURN_ON_SCHEMA``, verbatim.
        frozenset(
            {
                "color_name",
                "color_temp_kelvin",
                "hs_color",
                "profile",
                "rgb_color",
                "rgbw_color",
                "rgbww_color",
                "white",
                "xy_color",
            }
        ),
        frozenset({"brightness", "brightness_pct", "brightness_step", "brightness_step_pct"}),
    ),
}
"""Service-data fields that one HA service call may not carry together.

Keyed by ``(domain, service)`` because mutual exclusion is a property of
the **HA service schema**, not of the Sber device class: whoever calls
``light.turn_on`` is bound by the same rule.  Voluptuous rejects the whole
call — not the offending field — when two members of a group arrive
together, so :meth:`BaseEntity._merge_service_calls` must never build such
a call out of two individually valid ones.  Only groups the bridge can
actually produce are listed; add an entry when a handler starts emitting
another exclusive pair.
"""


def _breaks_exclusion(domain: str, service: str, current: dict, incoming: dict) -> bool:
    """Check whether folding ``incoming`` into ``current`` makes an illegal call.

    Args:
        domain: HA domain of the call (e.g. ``"light"``).
        service: HA service of the call (e.g. ``"turn_on"``).
        current: ``service_data`` already accumulated in the merge target.
        incoming: ``service_data`` of the call being folded in.

    Returns:
        True when the union would carry two fields of one
        :data:`EXCLUSIVE_SERVICE_DATA` group *because of* ``incoming`` —
        the caller then keeps the two calls apart.
    """
    groups = EXCLUSIVE_SERVICE_DATA.get((domain, service))
    if not groups:
        return False
    return any(group & set(incoming) and len(group & (set(current) | set(incoming))) > 1 for group in groups)


class NoSnapshot:
    """Sentinel type marking an omitted ``snapshot`` argument.

    ``None`` is a meaningful snapshot value ("serialization failed, treat
    as changed"), so :meth:`BaseEntity.mark_state_published` cannot use it
    as its default.  Public because it appears in that method's public
    signature — callers reading the annotation must be able to name it.
    """

    __slots__ = ()


NO_SNAPSHOT = NoSnapshot()
"""Singleton sentinel for :meth:`BaseEntity.mark_state_published`."""

# ---------------------------------------------------------------------------
#  Typed command result types for process_cmd return values
# ---------------------------------------------------------------------------


class ServiceCallUrl(TypedDict, total=False):
    """Descriptor for a single HA service call."""

    type: str
    domain: str
    service: str
    target: dict
    service_data: dict


class ServiceCallResult(TypedDict):
    """A process_cmd result instructing the bridge to call a HA service."""

    url: ServiceCallUrl


class UpdateStateResult(TypedDict):
    """A process_cmd result instructing the bridge to re-publish current state."""

    update_state: bool


CommandResult = ServiceCallResult | UpdateStateResult
"""Union type for all possible process_cmd return items."""


@dataclass(frozen=True, slots=True)
class AttrSpec:
    """Declarative spec for parsing a single HA attribute into an instance field.

    Subclasses of :class:`BaseEntity` can declare a class-level
    ``ATTR_SPECS`` tuple and rely on
    :meth:`BaseEntity._apply_attr_specs` to do the parsing in one line
    instead of hand-rolling ``attrs.get(...) / try-except / int()``
    boilerplate for every attribute.

    Attributes:
        field: Instance attribute name to assign (e.g. ``"_battery_level"``).
        attr_keys: HA attribute key(s) to read in fallback order.  First
            non-``None`` match wins.  Pass a single string for one key.
        parser: Conversion function applied to the raw value.  Defaults to
            identity.  Should raise ``(TypeError, ValueError)`` for bad input.
        default: Value to assign when no key matched or parsing failed.
        preserve_on_missing: When ``True`` and no attr key matched, leave
            the existing field value untouched instead of assigning
            ``default``.  Used by sensors that receive values from linked
            companion entities via ``update_linked_data`` — we don't want
            to clobber those when the primary HA state is refreshed.
    """

    field: str
    attr_keys: tuple[str, ...] = ()
    parser: Callable[[object], object] = lambda v: v
    default: object = None
    preserve_on_missing: bool = False
    converter: Callable[[dict], object] | None = None
    """Full-attrs converter.  When set, receives the entire HA attributes dict
    instead of a single value looked up by ``attr_keys``.  ``parser`` and
    ``attr_keys`` are ignored when ``converter`` is provided."""


def _safe_int_parser(value: object) -> int | None:
    """AttrSpec parser: convert to int via float (handles ``"22.5"`` strings).

    Args:
        value: Raw HA attribute value.

    Returns:
        The integer part of the value, or ``None`` when it is absent or
        not a finite number — see :func:`_safe_float_parser` for why
        ``NaN`` and infinities count as absent.
    """
    parsed = _safe_float_parser(value)
    if parsed is None:
        return None
    return int(parsed)


def _safe_float_parser(value: object) -> float | None:
    """AttrSpec parser: convert to float, rejecting non-finite numbers.

    ``float('nan')`` and ``float('inf')`` reach us from Home Assistant as
    a matter of routine: a template sensor that divided by zero, a modbus
    register full of garbage, an MQTT payload spelling ``"nan"``.  They
    are honest ``float`` objects, so an unguarded ``float()`` lets them
    through — and everything downstream then breaks in ways that are hard
    to trace back to the attribute:

    * ``int(float('nan'))`` raises ``ValueError``.  It is caught by
      ``sber_protocol.build_states_list_json``, which drops the whole
      device from ``up/status``; Sber expects every advertised feature in
      that answer, so a device missing from it reads as broken.  The user
      sees "the climate disappeared" and the log holds one traceback with
      no mention of the attribute.
    * ``int(float('inf'))`` raises ``OverflowError``, which that handler
      does **not** catch — the exception escapes and takes the publish
      with it.
    * a ``NaN`` that survives as a float serializes to the JSON literal
      ``NaN``, which is a Python extension rather than JSON and which the
      broker rejects.

    Treating such a value as "the attribute has no value" keeps the
    device in the publish with its remaining features intact.

    Args:
        value: Raw HA attribute value.

    Returns:
        The value as a finite ``float``, or ``None`` when it is absent,
        unparseable, or not finite.
    """
    if value is None:
        return None
    try:
        parsed = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed):
        _LOGGER.debug("Ignoring non-finite attribute value %r", value)
        return None
    return parsed


def _drop_non_finite(value: object) -> object:
    """Map a non-finite ``float`` to ``None``, pass everything else through.

    :class:`AttrSpec` entries whose attribute is already a number declare
    no ``parser``, so :func:`_safe_float_parser` never sees the value and
    a ``NaN`` coming from Home Assistant lands straight in an entity
    field (``devices/humidifier.py`` reads ``current_humidity`` that
    way).  It then detonates at publish time, far from its origin — see
    :func:`_safe_float_parser` for what that costs.

    Normalising it here makes "not a finite number" mean the same thing
    as "the attribute is absent" for **every** device class at once,
    which is also what lets ``preserve_on_missing`` keep the last good
    reading instead of overwriting it with garbage.

    Args:
        value: Value produced by a spec's parser or converter.

    Returns:
        ``None`` for ``NaN`` / ``±Infinity``, otherwise ``value`` itself.
    """
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _safe_bool_parser(value: object) -> bool | None:
    """AttrSpec parser: convert to bool, preserving ``None``."""
    if value is None:
        return None
    return bool(value)


def _safe_clamped_int_parser(value: object, low: int, high: int) -> int | None:
    """Parse value as int and clamp into ``[low, high]`` inclusive.

    Returns ``None`` when the value cannot be parsed.  Used by command
    handlers that accept integer ranges (e.g. HSV brightness).
    """
    parsed = _safe_int_parser(value)
    if parsed is None:
        return None
    return max(low, min(high, parsed))


class DeviceData(TypedDict, total=False):
    """Typed device registry data linked to an entity.

    All keys are optional because linked device data may come from partial
    HA device registry entries. Missing values fall back to sensible defaults
    in ``BaseEntity.to_sber_state``.
    """

    id: str
    name: str
    area_id: str
    manufacturer: str
    model: str
    model_id: str
    hw_version: str
    sw_version: str
    serial_number: str
    """Real device serial number from HA device registry (empty string if unknown)."""
    mac: str
    """Normalised MAC address pulled from ``DeviceEntry.connections`` (empty if unknown)."""


# ---------------------------------------------------------------------------
#  Linkable Roles — self-describing entity linking registry
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LinkableRole:
    """Describes a linkable sensor role that a device class accepts.

    Each role declares which HA domain + device_class combinations it matches.
    Device classes declare which roles they accept via ``LINKABLE_ROLES``.
    This eliminates the need for separate mapping dicts and domain overrides.

    Attributes:
        role: Link role name (e.g. ``"battery"``, ``"humidity"``).
        domains: Accepted HA entity domains (e.g. ``{"sensor"}``).
        device_classes: Accepted HA device_class values (e.g. ``{"humidity"}``).
    """

    role: str
    domains: frozenset[str]
    device_classes: frozenset[str]

    def matches(self, domain: str, device_class: str) -> bool:
        """Check if an HA entity matches this role.

        Args:
            domain: HA entity domain (e.g. ``"sensor"``).
            device_class: HA original_device_class (e.g. ``"humidity"``).

        Returns:
            True if both domain and device_class match.
        """
        return domain in self.domains and device_class in self.device_classes


# Common reusable LinkableRole instances
ROLE_BATTERY = LinkableRole("battery", frozenset({"sensor"}), frozenset({"battery"}))
"""Battery percentage sensor (sensor domain, battery device_class)."""

ROLE_BATTERY_LOW = LinkableRole("battery_low", frozenset({"binary_sensor"}), frozenset({"battery"}))
"""Low-battery binary sensor (binary_sensor domain, battery device_class)."""

ROLE_SIGNAL = LinkableRole("signal_strength", frozenset({"sensor"}), frozenset({"signal_strength"}))
"""Signal strength sensor (sensor domain, signal_strength device_class)."""

ROLE_TEMPERATURE = LinkableRole("temperature", frozenset({"sensor"}), frozenset({"temperature"}))
"""Temperature sensor (sensor domain, temperature device_class)."""

ROLE_HUMIDITY = LinkableRole("humidity", frozenset({"sensor"}), frozenset({"humidity"}))
"""Humidity sensor (sensor domain, humidity device_class)."""

ROLE_CO2 = LinkableRole("co2", frozenset({"sensor"}), frozenset({"carbon_dioxide"}))
"""Carbon-dioxide concentration link (Sber ``sensor_air.co2``, ppm)."""

ROLE_PM1 = LinkableRole("pm1", frozenset({"sensor"}), frozenset({"pm1"}))
"""PM1.0 particulate matter link (Sber ``sensor_air.pm1_0``, µg/m³)."""

ROLE_PM25 = LinkableRole("pm25", frozenset({"sensor"}), frozenset({"pm25"}))
"""PM2.5 particulate matter link (Sber ``sensor_air.pm2_5``, µg/m³)."""

ROLE_PM10 = LinkableRole("pm10", frozenset({"sensor"}), frozenset({"pm10"}))
"""PM10 particulate matter link (Sber ``sensor_air.pm10``, µg/m³)."""

ROLE_TVOC = LinkableRole("tvoc", frozenset({"sensor"}), frozenset({"volatile_organic_compounds"}))
"""TVOC concentration link (Sber ``sensor_air.tvoc_float``, mg/m³)."""

ROLE_HCHO = LinkableRole("hcho", frozenset({"sensor"}), frozenset({"volatile_organic_compounds_parts"}))
"""Formaldehyde link (Sber ``sensor_air.hcho_float``, mg/m³). HA has no
dedicated device_class for formaldehyde; the closest match is
``volatile_organic_compounds_parts``. Users with a distinct HCHO sensor
will link it manually via the wizard."""

ROLE_OPEN_STATE = LinkableRole(
    "open_state",
    frozenset({"binary_sensor"}),
    frozenset({"garage_door", "door", "opening"}),
)
"""Reed/contact sensor reporting the real position of an impulse-driven gate.

The primary entity of such a gate is the impulse relay (``switch`` /
``button`` / ``script``), whose own HA state is only an echo of the last
written relay value and says nothing about the leaf.  The position must
therefore come from a companion contact sensor linked in this role.

``window`` is deliberately **not** accepted: window contacts are common
and would otherwise become gate candidates in the wizard.
"""

SENSOR_LINK_ROLES: tuple[LinkableRole, ...] = (ROLE_BATTERY, ROLE_BATTERY_LOW, ROLE_SIGNAL)
"""Common linkable roles for battery-powered devices (sensors, covers, valves)."""

GATE_LINK_ROLES: tuple[LinkableRole, ...] = (ROLE_OPEN_STATE, ROLE_SIGNAL)
"""Linkable roles accepted by an impulse gate (the Sber ``gate`` spec has no battery)."""


def _collect_declared_roles() -> tuple[LinkableRole, ...]:
    """Collect every module-level ``LinkableRole`` constant declared above.

    The global registry used to be a hand-maintained tuple and silently
    drifted out of sync with per-class ``LINKABLE_ROLES`` (the six
    air-quality roles were missing, so the wizard classified CO2/PM
    siblings as unsupported while ``auto_link_all`` accepted them).
    Auto-collection makes ``ALL_LINKABLE_ROLES`` a derived value: any new
    ``ROLE_*`` constant defined in this module is registered automatically.

    Scope caveat (enforced by
    ``test_link_roles_registry.TestRegistryConstruction``): the scan
    reads ``globals()`` at call time, so it only sees constants bound
    **above** the :data:`ALL_LINKABLE_ROLES` assignment, and it picks up
    *every* module-level :class:`LinkableRole` — there is no "private
    role" escape hatch.  Declare new roles in the block above together
    with the existing ``ROLE_*`` constants.

    Returns:
        Tuple of unique :class:`LinkableRole` instances in declaration
        order, de-duplicated by role name (aliases bound to the same
        role name collapse into their first binding).
    """
    seen: set[str] = set()
    collected: list[LinkableRole] = []
    for value in globals().values():
        if isinstance(value, LinkableRole) and value.role not in seen:
            seen.add(value.role)
            collected.append(value)
    return tuple(collected)


ALL_LINKABLE_ROLES: tuple[LinkableRole, ...] = _collect_declared_roles()
"""Global registry of all known linkable roles.

Derived automatically from every ``LinkableRole`` constant declared
above in this module.  Device classes are expected to compose their
``LINKABLE_ROLES`` from these constants; as long as they do, the wizard
path (``resolve_link_role``) and per-class matching (``LINKABLE_ROLES``)
stay in sync.  Nothing in this module *enforces* that composition — a
class that builds its own ``LinkableRole`` inline still drifts, which is
why ``test_link_roles_registry`` walks every class in
``CATEGORY_DOMAIN_MAP`` and fails on roles unknown to this registry.
"""


def resolve_link_role_for(accepted_roles: Iterable[LinkableRole], domain: str, device_class: str) -> str:
    """Resolve the link role of an HA entity against a specific role set.

    Shared helper for link-role matching, used by the global
    :func:`resolve_link_role` and available to per-class validation
    (matching an entity against a primary's ``LINKABLE_ROLES``) instead
    of re-implementing the loop.  Not yet a hard single source of truth:
    ``websocket_api/links.py::ws_auto_link_all`` still runs its own
    ``LinkableRole.matches`` loop.  That is safe only because
    ``ALL_LINKABLE_ROLES`` contains no two roles matching the same
    ``(domain, device_class)`` pair — an invariant locked by
    ``test_link_roles_registry.test_registry_has_no_ambiguous_matches``.

    Args:
        accepted_roles: Roles to match against (e.g. a device class's
            ``LINKABLE_ROLES`` or :data:`ALL_LINKABLE_ROLES`).
        domain: HA entity domain.
        device_class: HA original_device_class.

    Returns:
        Role name string of the first match, or empty string if no match.
    """
    for lr in accepted_roles:
        if lr.matches(domain, device_class):
            return lr.role
    return ""


def resolve_link_role(domain: str, device_class: str) -> str:
    """Determine the link role for an HA entity based on domain and device_class.

    Iterates ``ALL_LINKABLE_ROLES`` and returns the role name of the first match.
    Domain-aware disambiguation is built into the role definitions:
    e.g. ``sensor`` + ``battery`` → ``battery``, ``binary_sensor`` + ``battery``
    → ``battery_low``.

    Args:
        domain: HA entity domain.
        device_class: HA original_device_class.

    Returns:
        Role name string, or empty string if no match.
    """
    return resolve_link_role_for(ALL_LINKABLE_ROLES, domain, device_class)


class BaseEntity(ABC):
    """Abstract base class for all Sber device entities.

    Defines the interface that all device types must implement:
    - fill_by_ha_state: Parse HA state into internal representation
    - _create_features_list: Return Sber feature names
    - to_sber_state: Build Sber device config JSON
    - _build_current_state: Build Sber current state JSON (the public
      ``to_sber_current_state`` wraps it with the declared-features filter)
    - process_cmd: Handle Sber commands, return HA service calls
    - process_state_change: Handle HA state change events
    """

    LINKABLE_ROLES: ClassVar[tuple[LinkableRole, ...]] = ()
    """Linkable roles this device class accepts. Override in subclasses."""

    REQUIRED_LINK_ROLES: ClassVar[tuple[str, ...]] = ()
    """Role names this device class cannot work without.

    Empty for every class whose Sber features are derivable from the
    primary HA entity alone.  A non-empty tuple means the device is
    *composite*: without those links it would publish a fabricated state
    (see :class:`~devices.gate.ImpulseGateEntity`, whose position exists
    only in a linked contact sensor).  The wizard refuses to add such a
    device when a required role is unmapped
    (``websocket_api.devices_grouped.ws_add_ha_device`` →
    ``missing_required_role``).
    """

    ENTITY_OPTION_KEYS: ClassVar[tuple[str, ...]] = ()
    """Per-entity user option keys this device class understands.

    Empty for every class whose behaviour is fully derived from the HA
    entity itself.  A non-empty tuple opts the class into the generic
    per-entity options mechanism: the values are persisted in
    ``entry.options[CONF_ENTITY_OPTIONS]`` keyed by entity id, applied at
    load time by :class:`~entity_registry.SberEntityLoader`, edited live
    through the ``update_entity_options`` WebSocket command, reported to
    the panel inside ``device_detail`` and carried by export / import.

    The mechanism is deliberately *class-driven*: nothing outside the
    device class knows what an option means, so adding one to a new
    category needs no change in the loader, the bridge, the WS layer or
    the config round-trip.
    """

    ENTITY_OPTIONS_BLOCK: ClassVar[str] = "entity_options"
    """Key under which ``device_detail`` reports :meth:`entity_options_state`.

    Per class rather than global because the panel renders a *different
    form* per option set, and because
    :class:`~devices.gate.ImpulseGateEntity` shipped its block as
    ``gate_options`` in v1.42 — renaming it would break every panel that
    is still cached in a browser.
    """

    @property
    def supports_entity_options(self) -> bool:
        """Whether this device class accepts per-entity user options."""
        return bool(self.ENTITY_OPTION_KEYS)

    def apply_entity_options(self, options: dict) -> None:  # noqa: B027 — intentional concrete no-op, not abstract
        """Apply persisted per-entity options (default: nothing to apply).

        Implementations are deliberately *lenient*: unknown keys and
        invalid values are ignored rather than raising, because this runs
        on the entity-loading path where a hand-edited (or downgraded)
        config must never take the whole integration down.  Strict
        checking of user input belongs to :meth:`validate_entity_options`.

        Args:
            options: Mapping of :attr:`ENTITY_OPTION_KEYS` to values; only
                the keys present are applied.
        """

    def validate_entity_options(self, options: dict) -> None:
        """Validate user-submitted option values (raises on bad input).

        Called by the ``update_entity_options`` WebSocket command *before*
        anything is persisted, so the user gets a readable message instead
        of a silently ignored setting.  Subclasses override to add
        value-level checks and are expected to call ``super()`` first.

        Args:
            options: Mapping submitted by the panel.

        Raises:
            ValueError: With a human-readable message when the mapping
                contains a key this class does not accept.
        """
        unknown = sorted(set(options) - set(self.ENTITY_OPTION_KEYS))
        if unknown:
            raise ValueError(
                f"{self.entity_id}: unknown option(s) {', '.join(unknown)}; "
                f"accepted: {', '.join(self.ENTITY_OPTION_KEYS) or '(none)'}"
            )

    def entity_options_state(self) -> dict[str, object]:
        """Return the option block the panel renders for this entity.

        Returns:
            Mapping of the current option values (plus any read-only
            context the form needs), or an empty dict for a class without
            options — ``device_detail`` then omits the block entirely.
        """
        return {}

    def register_link(self, role: str, linked_entity_id: str) -> None:
        """Register a linked companion entity for the given role.

        Public API for :class:`SberEntityLoader` — replaces direct mutation
        of ``self._linked_entities`` to preserve encapsulation.

        Args:
            role: The role name (e.g. ``"battery"``, ``"signal_strength"``).
            linked_entity_id: HA entity_id of the linked companion.
        """
        self._linked_entities[role] = linked_entity_id

    ATTR_SPECS: ClassVar[tuple[AttrSpec, ...]] = ()
    """Declarative HA-attribute parsing specs.

    Subclasses can populate this tuple to drive
    :meth:`_apply_attr_specs` instead of hand-rolling per-attribute
    parsing inside ``fill_by_ha_state``.
    """

    category: str
    area_id: str
    categories: list[str]
    config_entry_id: str | None
    config_subentry_id: str | None
    device_id: str | None
    disabled_by: str | None
    entity_category: str | None
    entity_id: str
    has_entity_name: bool | None
    hidden_by: str | None
    icon: str | None
    id: str | None
    labels: list[str]
    name: str
    options: dict
    original_name: str | None
    platform: str | None
    translation_key: str | None
    unique_id: str | None

    # State variables
    state: str | None
    is_filled_by_state: bool
    linked_device: DeviceData | None

    def __init__(self, category: str, entity_data: dict) -> None:
        """Initialize base entity from HA entity registry data.

        Args:
            category: Sber device category (e.g., 'light', 'relay', 'sensor_temp').
            entity_data: Dict with HA entity registry fields.
        """
        self.category = category
        self.attributes: dict = {}
        self.state = None
        self.is_filled_by_state = False
        self.linked_device = None
        self.nicknames: list[str] = []
        self.groups: list[str] = []
        self.parent_entity_id: str | None = None
        self.partner_meta: dict[str, str] = {}
        self.extra_features: list[str] = []
        self.removed_features: list[str] = []
        self._previous_sber_state: dict | None = None
        self._linked_entities: dict[str, str] = {}
        self._undeclared_keys_logged: set[str] = set()
        self._foreign_features_logged: set[str] = set()

        if entity_data:
            self.area_id = entity_data.get("area_id", "")
            self.categories = entity_data.get("categories", [])
            self.config_entry_id = entity_data.get("config_entry_id")
            self.config_subentry_id = entity_data.get("config_subentry_id")
            self.device_id = entity_data.get("device_id")
            self.disabled_by = entity_data.get("disabled_by")
            self.entity_category = entity_data.get("entity_category")
            self.entity_id = entity_data.get("entity_id")
            self.has_entity_name = entity_data.get("has_entity_name")
            self.hidden_by = entity_data.get("hidden_by")
            self.icon = entity_data.get("icon")
            self.id = entity_data.get("id")
            self.labels = entity_data.get("labels", [])
            self.name = entity_data.get("name")
            self.options = entity_data.get("options", {})
            self.original_name = entity_data.get("original_name")
            self.platform = entity_data.get("platform")
            self.translation_key = entity_data.get("translation_key")
            self.unique_id = entity_data.get("unique_id")

            if not self.name:
                self.name = self.original_name or self.entity_id

            if self.area_id is None:
                self.area_id = ""

    def _apply_attr_specs(self, attrs: dict) -> None:
        """Apply all declared :class:`AttrSpec` entries to ``self``.

        For each spec, reads the first non-``None`` key from ``attrs``,
        pipes the value through ``spec.parser`` and assigns the result
        to ``self.<spec.field>``.  When no key matches:

            * if ``spec.preserve_on_missing`` is ``True`` → leave the
              existing value alone (don't touch ``self.<field>``);
            * otherwise → assign ``spec.default``.

        Args:
            attrs: HA attributes dict extracted from a state dict.
        """
        for spec in self.ATTR_SPECS:
            # Full-attrs converter path: receives entire attrs dict
            if spec.converter is not None:
                try:
                    parsed = spec.converter(attrs)
                except (TypeError, ValueError, KeyError):
                    parsed = spec.default
                parsed = _drop_non_finite(parsed)
                if parsed is None and spec.preserve_on_missing:
                    continue
                setattr(self, spec.field, parsed if parsed is not None else spec.default)
                continue

            # Standard path: look up single value by attr_keys
            raw: object = None
            for key in spec.attr_keys:
                candidate = attrs.get(key)
                if candidate is not None:
                    raw = candidate
                    break
            if raw is None:
                if not spec.preserve_on_missing:
                    setattr(self, spec.field, spec.default)
                continue
            try:
                parsed = spec.parser(raw)
            except (TypeError, ValueError):
                parsed = spec.default
            parsed = _drop_non_finite(parsed)
            if parsed is None and spec.preserve_on_missing:
                continue
            setattr(self, spec.field, parsed if parsed is not None else spec.default)

    def fill_by_ha_state(self, ha_entity_state: dict) -> None:
        """Parse HA state dict and update internal state.

        Args:
            ha_entity_state: Dict with 'state' and 'attributes' keys from HA.
        """
        self.state = ha_entity_state.get("state")
        self.attributes = copy.deepcopy(ha_entity_state.get("attributes", {}))
        self.is_filled_by_state = True

        # Use friendly_name from HA state when entity name was not customized
        # by the user (still matches original_name or entity_id).
        # This handles has_entity_name=True entities where original_name is
        # just a suffix ("Temperature") but friendly_name is the full name
        # ("Climate Sensor Temperature").
        friendly = self.attributes.get("friendly_name")
        if friendly and self.name in (self.entity_id, self.original_name):
            self.name = friendly

    @property
    def effective_room(self) -> str:
        """Return the best available room name.

        Priority: entity area_id → device area_id → empty string.
        """
        if self.area_id:
            return self.area_id
        if self.linked_device:
            return self.linked_device.get("area_id", "")
        return ""

    def is_group_state(self) -> bool:
        """Check if this entity represents a group of other entities."""
        entity_list = self.attributes.get("entity_id")
        return entity_list is not None and len(entity_list) > 0

    def _create_features_list(self) -> list[str]:
        """Return the raw feature list contributed by this class (subclass hook).

        Internal extension point — **subclasses override this** to add their
        Sber features, typically returning ``[*super()._create_features_list(), ...]``.

        External consumers must call :meth:`get_final_features_list` instead,
        which applies user ``extra_features`` / ``removed_features`` overrides.

        Base implementation returns ``["online"]`` (obligatory for every
        Sber device per VR-010).
        """
        return ["online"]

    def create_allowed_values_list(self) -> dict[str, dict]:
        """Return allowed values map for Sber model descriptor.

        Override in subclasses to provide allowed_values for features
        that require INTEGER ranges or ENUM value lists.

        Returns:
            Dict mapping feature key to its allowed values descriptor,
            or empty dict if no allowed values needed.
        """
        return {}

    def create_dependencies(self) -> dict[str, dict]:
        """Return feature dependencies map for Sber model descriptor.

        Override in subclasses to declare feature dependencies
        (e.g., light_colour depends on light_mode == 'colour').

        Returns:
            Dict mapping feature key to its dependency descriptor,
            or empty dict if no dependencies needed.
        """
        return {}

    @property
    def declared_features(self) -> list[str]:
        """Return what this entity declares *before* the category gate.

        This is the device classes' own answer plus the user's
        ``sber_features_add`` / ``sber_features_remove``, with nothing
        removed on account of the Sber reference tables.  Nothing on the
        wire uses it — :meth:`get_final_features_list` is what publishes —
        but the compliance suite does, and that is the point: a test that
        read the published list would be comparing the output of
        :meth:`_drop_features_foreign_to_category` against the very table
        that method filters by, and could never fail.  Reading the
        declaration instead keeps the safety net (the runtime filter) and
        the watchdog (the test) independent, so a class that starts
        contributing a foreign function is still caught.

        Returns:
            Feature names as declared, duplicates already removed.
        """
        features = self._create_features_list()
        if self.removed_features:
            features = [f for f in features if f not in self.removed_features]
        if self.extra_features:
            existing = set(features)
            features.extend(f for f in self.extra_features if f not in existing)
        return features

    def get_final_features_list(self) -> list[str]:
        """Return the feature list that goes on the wire.

        User overrides (:attr:`extra_features` / :attr:`removed_features`)
        are applied first, then features our own classes contributed but
        Sber does not document for the category are dropped — see
        :meth:`_drop_features_foreign_to_category`.

        Returns:
            Final list of Sber feature names.
        """
        return self._drop_features_foreign_to_category(self.declared_features)

    def _drop_features_foreign_to_category(self, features: list[str]) -> list[str]:
        """Drop features *we* declared that Sber does not document for the category.

        Every category page carries a closed table of the functions it
        has ("Доступные функции устройства"), scraped into
        :data:`CATEGORY_REFERENCE_FEATURES`.  A function outside it is
        not a function Sber merely ignores: the model is validated as a
        whole, so one foreign name is a reason for the cloud to drop the
        device — silently, with no error anywhere, leaving the user with
        an empty space where the intercom should be.

        This is a **safety net, not the fix**.  Each device class is
        expected to declare only what its category has, and
        ``TestDeclaredFeaturesBelongToTheCategory`` checks
        :attr:`declared_features` — the list *before* this method — against
        the same tables, so a class that regresses is caught by a red test
        rather than quietly patched up here.  The net stays because the
        mistake keeps arriving by inheritance (``intercom`` used to get
        ``on_off`` from :class:`~.on_off_entity.OnOffEntity`) and because a
        category added later would otherwise ship unguarded.

        ``sber_features_add`` is deliberately **not** filtered.  The
        reference tables are a scrape of the documentation, and the scrape
        is demonstrably incomplete: the ``led_strip`` page lists
        ``sleep_timer`` in its own reference example while the function
        table our generator reads does not carry it.  A user copying a
        function off the page they are looking at would then get it
        silently removed with advice to delete a line that is correct.
        They have the Sber app in front of them and we have a snapshot, so
        their word wins; the log says what the risk is and the decision
        stays theirs.

        A category unknown to the reference table (an internal alias, a
        page the scraper has not seen) is passed through unfiltered —
        the table is evidence of what Sber documents, not of what it
        forbids, and silently stripping a device down on missing
        evidence would be worse than the foreign key.

        Args:
            features: Declared feature list, user overrides already applied.

        Returns:
            The same list without names our classes had no right to add.
        """
        reference = CATEGORY_REFERENCE_FEATURES.get(self.category)
        if reference is None:
            return features
        undocumented = [name for name in features if name not in reference]
        if not undocumented:
            return features
        self._log_foreign_features(undocumented)
        kept = set(self.extra_features)
        return [name for name in features if name in reference or name in kept]

    def _log_foreign_features(self, foreign: list[str]) -> None:
        """Report once per entity instance about each undocumented feature.

        The feature list is rebuilt on every publish, so an unguarded
        message would repeat for the life of the bridge.

        The level splits by who is able to act on it.  A name the user put
        into ``sber_features_add`` is their line of configuration and
        their decision, so it is a warning that names the risk and lets
        the feature through.  A name one of our device classes
        contributed is a bug in this integration that no user setting can
        change, and warning about it on every restart would be noise they
        cannot silence; it is dropped and logged at debug level, and
        ``TestDeclaredFeaturesBelongToTheCategory`` is what stops it from
        reaching a release in the first place.

        Args:
            foreign: Feature names Sber does not document for the category.
        """
        fresh = [name for name in foreign if name not in self._foreign_features_logged]
        if not fresh:
            return
        self._foreign_features_logged.update(fresh)
        user_added = sorted(name for name in fresh if name in self.extra_features)
        ours = sorted(name for name in fresh if name not in self.extra_features)
        if user_added:
            _LOGGER.warning(
                "Entity %s: feature(s) %s from sber_features_add are not documented for category '%s' "
                "in our snapshot of the Sber docs. They are published as you asked, but if the cloud "
                "disagrees it can reject the whole device — if it disappears from the Sber app, "
                "remove them from the redefinition.",
                self.entity_id,
                ", ".join(user_added),
                self.category,
            )
        if ours:
            _LOGGER.debug(
                "Entity %s: dropping feature(s) %s — Sber does not document them for category '%s'",
                self.entity_id,
                ", ".join(ours),
                self.category,
            )

    def update_linked_data(self, role: str, ha_state: dict) -> None:  # noqa: B027 — intentional concrete no-op, not abstract
        """Inject state from a linked companion HA entity (default: no-op).

        Device classes that accept linked entities (e.g. a binary battery
        sensor paired with a valve) override this to apply the foreign
        state to their own fields.  The default implementation does
        nothing, which is correct for classes that don't advertise
        :attr:`LINKABLE_ROLES`.

        Providing a universal default also eliminates ``hasattr`` checks
        at every call site -- callers may invoke it unconditionally.

        Args:
            role: The link role (e.g. ``"battery"``, ``"humidity"``).
            ha_state: HA state dict of the linked entity.
        """

    def link_device(self, device_data: DeviceData) -> None:
        """Link this entity to a HA device registry entry.

        Args:
            device_data: Device registry data dict.

        Raises:
            ValueError: If device_id does not match.
        """
        if self.device_id != device_data.get("id"):
            raise ValueError(f"Device ID mismatch: {self.device_id} != {device_data.get('id')}")
        self.linked_device = device_data

    def to_sber_state(self) -> dict:
        """Build Sber device config JSON for MQTT publish.

        Handles both ``device_id is None`` (standalone HA entity) and
        ``device_id is set`` (entity linked to a device registry entry)
        cases through a unified source-resolver approach.

        Returns:
            Dict with device descriptor for Sber (id, name, room, model, features).
            Optionally includes nicknames, groups, parent_id, and partner_meta
            when configured.

        Raises:
            RuntimeError: If fill_by_ha_state was not called first.
            RuntimeError: If device has device_id but linked_device is not set.
        """
        if not self.is_filled_by_state:
            raise RuntimeError(f"Entity {self.entity_id}: fill_by_ha_state must be called before to_sber_state")
        if self.device_id is not None and self.linked_device is None:
            raise RuntimeError(f"Entity {self.entity_id}: linked_device required when device_id is set")

        device: DeviceData = self.linked_device or {}
        display_name = self._resolve_display_name(device)

        res: dict = {
            "id": self.entity_id,
            "name": display_name,
            "default_name": self._resolve_default_name(),
            "room": device.get("area_id") or self.area_id,
            "model": self._build_model_descriptor(device),
            "hw_version": device.get("hw_version") or "1",
            "sw_version": device.get("sw_version") or "1",
        }

        if self.nicknames:
            res["nicknames"] = self.nicknames
        if self.groups:
            res["groups"] = self.groups
        if self.parent_entity_id:
            res["parent_id"] = self.parent_entity_id
        if self.partner_meta:
            res["partner_meta"] = self.partner_meta

        return res

    def _resolve_display_name(self, device: DeviceData) -> str:
        """Resolve the display name for Sber device descriptor.

        Priority:
            1. User-customized name (``self.name != self.original_name``) — wins.
            2. Device name from registry (when linked_device present).
            3. Entity name as last resort.

        Args:
            device: Device registry data dict (may be empty).

        Returns:
            Display name string.
        """
        if not self.linked_device:
            return self.name
        device_name = device.get("name") or self.original_name or self.name
        return self.name if self.name != self.original_name else device_name

    def _resolve_default_name(self) -> str:
        """Resolve the fallback default name for Sber device descriptor."""
        if self.linked_device:
            return self.original_name or self.entity_id
        return self.entity_id

    def _build_model_descriptor(self, device: DeviceData) -> dict:
        """Build the ``model`` block of a Sber device descriptor.

        The emitted ``model.id`` is ``{ha_model_id}_{category}_{digest}``
        (or ``Mdl_{category}_{digest}`` when HA knows no model_id), where
        ``digest`` is :meth:`_capability_digest` over the final feature
        list plus ``allowed_values``.

        **Why the model identity includes the capability set.**  Sber
        cloud stores exactly one model per ``model.id`` and merges the
        interfaces of every device claiming that id.  A multi-channel
        device (issue #44: a Zigbee chandelier exposing
        ``light.*_main_light`` with ``color_temp`` and
        ``light.*_second_light`` with ``onoff``) yields two HA entities
        that share one HA ``model_id``, so the pre-1.44 scheme gave both
        the same Sber model.  The dimmable channel's sliders then leaked
        onto the on/off channel in the Sber app and its commands hung.
        Keying the model on *capabilities* rather than on hardware alone
        fixes that while preserving the point of a "model": two
        identically-capable lamps still hash to the same digest and
        therefore still share one cloud model, no matter which device
        they belong to or in which order they were loaded.

        **Known limitation.**  The feature list is derived from live HA
        attributes, so an entity that is ``unavailable`` at config-publish
        time (no attributes → no capabilities) registers a stripped-down
        model and keeps it until the next config republish.  The advertised
        ``features`` list already had that problem before the digest
        existed; the digest only makes it visible in ``model.id``.  Config
        republish is triggered on (re)connect, on HA start, on redefinition
        changes and on a linked sensor's feature change
        (``ha_state_forwarder``), but not on a feature change of the primary
        entity itself — see the tests in ``TestModelIdStability``.

        Args:
            device: Device registry data dict (may be empty).

        Returns:
            Model descriptor dict ready for ``to_sber_state`` output.
        """
        raw_model_id = device.get("model_id", "") or ""
        model_id = f"{raw_model_id}_{self.category}" if raw_model_id else f"Mdl_{self.category}"

        features = self.get_final_features_list()

        # Reconcile allowed_values with the FINAL features list (issue #44
        # audit): a feature dropped via ``sber_features_remove`` must not
        # leave an orphaned allowed_values key — the pydantic validator
        # rejects such descriptors and the whole device silently disappears
        # from the Sber config payload.
        allowed = {k: v for k, v in self.create_allowed_values_list().items() if k in set(features)}

        # Diagnostics for the reverse mismatch: a user-added INTEGER/ENUM
        # feature without limits renders a dead control in the Sber app.
        for extra in self.extra_features:
            if extra in features and extra not in allowed:
                _LOGGER.warning(
                    "Entity %s: user-added feature '%s' has no allowed_values — "
                    "Sber may render a non-working control for it",
                    self.entity_id,
                    extra,
                )

        hardware = {key: str(device[key]) for key in ("manufacturer", "model") if device.get(key)}
        descriptor: dict = {
            "id": f"{model_id}_{self._capability_digest(features, allowed, hardware)}",
            "manufacturer": device.get("manufacturer") or "Unknown",
            "model": device.get("model") or "Unknown",
            "description": self._model_description(hardware),
            "category": self.category,
            "features": features,
        }
        if allowed:
            descriptor["allowed_values"] = allowed
        deps = self.create_dependencies()
        if deps:
            descriptor["dependencies"] = deps
        return descriptor

    def _model_description(self, hardware: dict[str, str]) -> str:
        """Return the ``model.description`` text — a description of the *model*.

        Sber's ``model`` block describes a product, not an installation:
        ``id`` is "часто product_id", ``manufacturer`` is the vendor and
        ``model`` the product name.  Until 1.51 this field carried the
        entity's **display name**, which is a property of one device and
        already travels in ``device.name``.  Two identical sensors of the
        same vendor named "Кухня" and "Спальня" therefore left in one
        config payload under one ``model.id`` with two different
        descriptions — the same collision issue #63 is about, only inside
        a vendor instead of across vendors, and the more common of the
        two.  Naming the model after the hardware removes it: identical
        hardware now yields an identical descriptor, and renaming a device
        moves nothing.

        The fallback for an entity Home Assistant has no device for names
        the bridge and the category, which is genuinely all that is known
        about such a "model".

        Args:
            hardware: ``manufacturer`` / ``model`` as Home Assistant knows
                them; empty when it knows neither.

        Returns:
            Human-readable model description.
        """
        named = [hardware[key] for key in ("manufacturer", "model") if hardware.get(key)]
        return " ".join(named) if named else f"Home Assistant {self.category}"

    @staticmethod
    def _capability_digest(
        features: Iterable[str],
        allowed_values: dict[str, dict],
        hardware: dict[str, str] | None = None,
    ) -> str:
        """Return a short stable digest of a device's advertised capabilities.

        Two entities produce the same digest **iff** they advertise the
        same feature set and the same ``allowed_values`` — that is the
        definition of "same model" as far as the Sber cloud is
        concerned.  See :meth:`_build_model_descriptor` for why model
        identity is capability-based.

        The digest is computed from a canonical JSON serialization
        (``sort_keys=True`` plus an explicitly sorted feature list), so
        it does not depend on feature declaration order, dict insertion
        order, or entity load order.  ``hashlib`` is used rather than
        :func:`hash` because the value goes on the wire and must survive
        a Home Assistant restart (``PYTHONHASHSEED`` randomizes
        :func:`hash` per process).  MD5 is used purely as a checksum,
        hence ``usedforsecurity=False``.

        **Why the hardware name is part of it.**  Capabilities alone are
        not enough to tell two models apart.  An Aqara ``WSDCGQ11LM`` and
        a Sonoff ``SNZB-02`` are both temperature sensors with the same
        feature set, so before 1.51 they hashed to the same
        ``Mdl_sensor_temp_…`` id while carrying different
        ``manufacturer`` and ``model`` in their descriptors — one config
        payload declaring the same model twice, with conflicting
        contents.  The cloud keeps one model per id, so which of the two
        descriptions survived was undefined (issue #63).

        ``manufacturer`` / ``model`` join the digest only when Home
        Assistant actually knows them.  For an entity with no device
        behind it the descriptor says ``Unknown`` for both, and two such
        entities of one category with one feature set are genuinely
        indistinguishable — adding a constant to the hash would only
        churn their ids for nothing.

        ``description`` is not listed separately because since 1.51 it is
        a function of ``hardware`` already (see
        :meth:`_model_description`): everything the descriptor says about
        the model is either in the digest or derived from something that
        is, so one id can no longer name two different descriptors.  The
        entity's display name is what it must never contain — the user
        renames devices at will, and re-registering a cloud model on every
        rename would cost far more than the collision it avoids.

        **The compromise this makes.**  ``manufacturer`` and ``model``
        come from the HA device registry, and integrations rewrite them:
        a zigbee2mqtt or ZHA database update that turns ``TS0601`` into
        ``Moes ZTRV-…`` moves the digest, and the cloud registers a new
        model for hardware that did not change.  That is accepted rather
        than avoided: dropping ``model`` and keying on ``manufacturer``
        alone would put two different products of one vendor back under a
        single id with conflicting descriptors, which is the very defect
        being fixed.  Such a drift is silent —
        :data:`~.cloud_device_registry.MODEL_IDENTITY_REVISION` marks
        changes to *this formula*, not to the data HA feeds it, so the
        user gets no notice.  A stray re-registration is the price; the
        notice exists for the release that moves every id at once.

        Args:
            features: Final feature names (order irrelevant).
            allowed_values: ``allowed_values`` map already reconciled
                with ``features``.
            hardware: ``manufacturer`` / ``model`` as Home Assistant
                knows them, empty or ``None`` when it knows neither.

        Returns:
            8-character lowercase hex digest.
        """
        identity: dict[str, object] = {
            "features": sorted(set(features)),
            "allowed_values": allowed_values,
        }
        if hardware:
            identity["hardware"] = hardware
        canonical = json.dumps(
            identity,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return hashlib.md5(canonical.encode("utf-8"), usedforsecurity=False).hexdigest()[:8]

    @abstractmethod
    def _build_current_state(self) -> dict:
        """Build the raw Sber current state JSON (subclass hook).

        Internal extension point — **subclasses implement this** instead
        of :meth:`to_sber_current_state`, which wraps it with the
        declared-features filter.

        Returns:
            Dict with entity_id key mapping to {'states': [...]}.
        """

    def to_sber_current_state(self) -> dict:
        """Build the publish-ready Sber current state JSON.

        Calls the subclass hook :meth:`_build_current_state` and then
        drops every state whose key is not advertised in
        :meth:`get_final_features_list` — see
        :meth:`_filter_undeclared_states`.

        Returns:
            Dict with entity_id key mapping to {'states': [...]}.
        """
        return self._filter_undeclared_states(self._build_current_state())

    def sanitize_echo_states(self, states: list[dict], commanded: set[str]) -> list[dict]:
        """Make a command-echo state list publishable.

        The echo answers Sber within milliseconds, long before HA has
        propagated anything, so it is the commanded values laid over the
        entity's current state.  What it must never do is announce a state
        the device cannot be in: the echo used to be the one publish that
        bypassed :meth:`_filter_undeclared_states` and knew nothing about
        :meth:`create_dependencies`, so a ``light_mode: white`` command
        produced a packet carrying ``white`` together with the
        still-current ``light_colour`` — a combination the bridge's own
        model descriptor declares impossible.  Sber saw "done" 8-27 ms
        after the command and the contradicting real state ~1.5 s later,
        which is what made the app's controls flip back.

        Two guards are applied here, so every device class gets them:

        * undeclared keys are dropped, exactly as on the normal state
          publish (:meth:`to_sber_current_state`);
        * command-induced contradictions between a feature and its
          declared selector are reconciled — see
          :meth:`_reconcile_echo_dependencies`.

        Args:
            states: Merged echo states (baseline with the command laid
                over it), in publish order.
            commanded: Feature keys that came from the command itself.

        Returns:
            The filtered, reconciled ``states`` list, ready to publish.
        """
        declared = self._filter_undeclared_states({self.entity_id: {"states": list(states)}})
        kept = declared.get(self.entity_id, {}).get("states", [])
        return self._reconcile_echo_dependencies(kept, commanded)

    def _reconcile_echo_dependencies(self, states: list[dict], commanded: set[str]) -> list[dict]:
        """Resolve command-induced conflicts between a feature and its selector.

        A dependency (:meth:`create_dependencies`) says "this feature only
        applies while that one holds this value".  The echo mixes two
        moments — the commanded keys are the future, everything else is
        the present — so it is the one place where the two sides of a
        dependency can disagree *because of us*:

        * the command moved the **selector** (``light_mode: white``) and
          the dependent value next to it is the pre-command one: the stale
          key is dropped, the command wins;
        * the command carried the **dependent** key (``light_colour``) and
          the selector still holds its pre-command value: the selector is
          moved to the value the dependency requires — the device is on
          its way there by definition of the command, and echoing the old
          mode is exactly what made the app's mode tab jump back.  Only
          done when the descriptor leaves no choice (a single declared
          value); an ambiguous one drops the dependent key instead.

        A contradiction with **neither** side commanded is left untouched
        on purpose: that is the entity's own steady-state payload, which
        deliberately reports every state-holding feature on every publish
        (issue #63), and the echo is not the place to start censoring it.

        ``dependencies`` is the bridge's own extension of the Sber
        ``model`` block — the documented structure lists only id,
        manufacturer, model, hw_version, sw_version, description,
        category, features and allowed_values — so it is used here purely
        as an internal consistency rule, never as a reason to withhold a
        key Sber asked about.

        Args:
            states: Candidate states, already filtered by
                :meth:`_filter_undeclared_states`.
            commanded: Feature keys that came from the command itself.

        Returns:
            The reconciled state list.
        """
        dependencies = self.create_dependencies()
        if not dependencies:
            return states
        values: dict[str, object] = {
            state["key"]: state.get("value", {})
            for state in states
            if isinstance(state, dict) and isinstance(state.get("key"), str)
        }
        drop: set[str] = set()
        override: dict[str, dict] = {}
        for key, dependency in dependencies.items():
            selector = dependency.get("key") if isinstance(dependency, dict) else None
            if key not in values or not isinstance(selector, str) or selector not in values:
                continue
            if self._dependency_satisfied(dependency, values[selector]):
                continue
            if selector in commanded:
                drop.add(key)
            elif key in commanded:
                required = self._required_selector_value(dependency)
                if required is None:
                    drop.add(key)
                else:
                    override[selector] = required
                    values[selector] = required
        if not drop and not override:
            return states
        kept: list[dict] = []
        for state in states:
            key = state.get("key") if isinstance(state, dict) else None
            if key in drop:
                _LOGGER.debug(
                    "Entity %s: dropping stale '%s' from the command echo — '%s' was just commanded",
                    self.entity_id,
                    key,
                    dependencies[key].get("key"),
                )
                continue
            if key in override:
                _LOGGER.debug(
                    "Entity %s: echoing '%s' as %s — required by the commanded feature it governs",
                    self.entity_id,
                    key,
                    override[str(key)],
                )
                kept.append({**state, "value": override[str(key)]})
                continue
            kept.append(state)
        return kept

    @staticmethod
    def _required_selector_value(dependency: dict) -> dict | None:
        """Return the only value a dependency accepts, when there is one.

        Args:
            dependency: Descriptor as returned by
                :meth:`create_dependencies`.

        Returns:
            The single declared value dict, or ``None`` when the
            descriptor declares none or leaves a choice between several.
        """
        values = dependency.get("values")
        if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], dict):
            return None
        return values[0]

    @staticmethod
    def _dependency_satisfied(dependency: dict, selector_value: object) -> bool:
        """Check one declared dependency against the selector's actual value.

        Args:
            dependency: Descriptor as returned by
                :meth:`create_dependencies` — ``{"key": ..., "values": [...]}``.
            selector_value: The Sber value dict currently held by the
                selector feature.

        Returns:
            True when the selector matches one of the declared values (or
            the descriptor declares none, which constrains nothing).
            False when the value is missing or contradicts all of them.
        """
        expected_values = dependency.get("values")
        if not isinstance(expected_values, list) or not expected_values:
            return True
        if not isinstance(selector_value, dict):
            return False
        actual = normalize_sber_value(selector_value)
        return any(
            all(actual.get(field) == value for field, value in expected.items() if field != "type")
            for expected in expected_values
            if isinstance(expected, dict)
        )

    def _filter_undeclared_states(self, payload: dict) -> dict:
        """Drop states whose feature key this device does not advertise.

        Sber's config publish declares a feature list; the state publish
        must stay inside it.  Publishing an undeclared key makes the app
        render a control the device never announced — issue #44: an
        ``onoff``-only light channel published ``light_brightness`` (the
        HA attribute is absent, so the converter floors it to the Sber
        minimum ``100``, which is non-zero and passed the old guard) and
        ``light_mode``, so the Sber app showed a colour lamp whose
        sliders hung.  Enforcing the invariant here rather than in each
        device class closes the whole class of leaks across all
        categories at once, and keeps
        :func:`~custom_components.sber_mqtt_bridge.schema_validator.validate_publish`
        free of ``not_declared`` findings by construction.

        Keys in :data:`ALWAYS_PUBLISHED_FEATURES` are never dropped.
        Filtering uses the **final** feature list, so a feature the user
        dropped via ``sber_features_remove`` stops being published too.

        Dropped keys are logged at DEBUG once per key per entity
        instance (``_undeclared_keys_logged``), because this runs on
        every publish and would otherwise flood the log.

        Args:
            payload: Raw ``{entity_id: {"states": [...]}}`` mapping as
                returned by :meth:`_build_current_state`.

        Returns:
            The same mapping with undeclared states removed.  Entries
            that don't look like a states block are passed through
            untouched.
        """
        declared = set(self.get_final_features_list()) | ALWAYS_PUBLISHED_FEATURES
        for device_id, block in payload.items():
            if not isinstance(block, dict) or not isinstance(block.get("states"), list):
                continue
            kept: list[dict] = []
            for state in block["states"]:
                key = state.get("key") if isinstance(state, dict) else None
                if key is not None and key not in declared:
                    self._log_undeclared(str(key), device_id)
                    continue
                kept.append(state)
            block["states"] = kept
        return payload

    def _log_undeclared(self, key: str, device_id: str) -> None:
        """Log a dropped undeclared state key once per entity instance.

        Args:
            key: The Sber feature key that was filtered out.
            device_id: The Sber device id the state belonged to.
        """
        if key in self._undeclared_keys_logged:
            return
        self._undeclared_keys_logged.add(key)
        _LOGGER.debug(
            "Entity %s (device %s, category %s): dropping state '%s' — not in declared features %s",
            self.entity_id,
            device_id,
            self.category,
            key,
            sorted(self.get_final_features_list()),
        )

    def get_entity_domain(self) -> str:
        """Extract HA domain from entity_id.

        Returns:
            Domain string (e.g., 'climate' from 'climate.living_room').

        Raises:
            ValueError: If entity_id has invalid format.
        """
        entity_id = self.entity_id
        if not isinstance(entity_id, str) or "." not in entity_id:
            raise ValueError(f"entity_id '{entity_id}' has invalid format")
        domain, _ = entity_id.split(".", 1)
        return domain

    @staticmethod
    def _build_service_call(
        domain: str,
        service: str,
        entity_id: str,
        service_data: dict | None = None,
    ) -> ServiceCallResult:
        """Build a HA service call dict for Sber → HA forwarding.

        This is the canonical helper for all device ``process_cmd`` methods.
        It replaces hand-written ``{"url": {"type": "call_service", ...}}``
        literals with a single, typo-safe call.

        Args:
            domain: HA service domain (e.g., 'climate', 'light').
            service: HA service name (e.g., 'set_temperature', 'turn_on').
            entity_id: Target HA entity identifier.
            service_data: Optional service data payload; omitted if None.

        Returns:
            Dict with 'url' key containing the HA service call descriptor.
        """
        url: dict = {
            "type": SERVICE_CALL_TYPE,
            "domain": domain,
            "service": service,
            "target": {"entity_id": entity_id},
        }
        if service_data is not None:
            url["service_data"] = service_data
        return {"url": url}

    @classmethod
    def _build_on_off_service_call(cls, entity_id: str, domain: str, on: bool) -> ServiceCallResult:
        """Build a HA turn_on / turn_off service call dict.

        Convenience wrapper over :meth:`_build_service_call` for the common
        on/off case.

        Args:
            entity_id: HA entity identifier (e.g., 'climate.living_room').
            domain: HA service domain (e.g., 'climate', 'humidifier').
            on: True to turn on, False to turn off.

        Returns:
            Dict with 'url' key containing the HA service call descriptor.
        """
        return cls._build_service_call(domain, SERVICE_TURN_ON if on else SERVICE_TURN_OFF, entity_id)

    def process_cmd(self, cmd_data: dict) -> list[CommandResult]:
        """Process a Sber command via the ``_cmd_handlers`` dispatch table.

        Subclasses declare which Sber feature keys they handle by
        overriding :attr:`_cmd_handlers`.  The base implementation walks
        ``cmd_data["states"]``, routes each entry to its handler, and
        returns the *aggregated* service-call list.

        Two things happen on top of the plain dispatch loop, and both
        exist because of **multi-key** commands — the Sber app sends
        ``light_mode`` and ``light_colour_temp`` in one payload when the
        user switches a lamp to white and moves the temperature slider in
        the same gesture:

        * **Selector keys run first.**  A key that another feature
          declares a dependency on (:meth:`create_dependencies`, e.g.
          ``light_colour`` → ``light_mode``) is a mode selector: its
          handler has no value of its own to apply and can only
          synthesize one from the *pre-command* entity state, which
          ``process_cmd`` never refreshes (that is ``fill_by_ha_state``'s
          job, and it runs later, when HA confirms).  Running selectors
          before the keys that carry a concrete value guarantees the
          stale value can never be the last writer.  Without it,
          ``{light_colour_temp: 900, light_mode: white}`` rolled the
          just-requested temperature back to the previous one.  The
          protection reaches exactly as far as the declarations do: a
          device whose :meth:`create_dependencies` comes out empty — a
          lamp whose ``light_colour`` the user removed via
          ``sber_features_remove``, say — is dispatched in payload order
          and can still be rolled back, which is the behaviour it had
          before.
        * **Calls to the same service are merged.**  Each handler used to
          emit its own ``light.turn_on``, so one Sber command produced
          three HA service calls, three transitions and three
          ``state_changed`` rounds.  Results with the same ``domain`` /
          ``service`` / ``target`` are folded into a single call whose
          ``service_data`` is the union of the contributions — see
          :meth:`_merge_service_calls`.

        Args:
            cmd_data: Command payload with 'states' list. Always a dict —
                the dispatcher rejects ``None`` before reaching here.

        Returns:
            List of :class:`ServiceCallResult` or :class:`UpdateStateResult`
            items, or empty list if no action needed.
        """
        handlers = self._cmd_handlers
        if not handlers:
            return []
        results: list[CommandResult] = []
        for item in self._ordered_cmd_states(cmd_data.get("states", [])):
            handler = handlers.get(item.get("key", ""))
            if handler is None:
                continue
            # Sber omits proto3-default fields: {"type": "INTEGER"} means 0.
            # Normalize here so every handler sees a complete value dict.
            results.extend(handler(normalize_sber_value(item.get("value", {}))))
        return self._merge_service_calls(results)

    def _ordered_cmd_states(self, states: list) -> list:
        """Return one command's states with selector keys moved to the front.

        Stable: keys that nothing depends on keep their payload order, so
        a device that declares no dependencies sees exactly the order Sber
        sent.  See :meth:`process_cmd` for why selectors must go first.

        Args:
            states: The raw ``cmd_data["states"]`` list.

        Returns:
            The same items, selector keys first.  Malformed (non-dict)
            items are passed through untouched — the dispatch loop still
            raises on them exactly as before, and the dispatcher contains
            the failure per entity.
        """
        governing = self._governing_cmd_keys()
        if not governing:
            return list(states)
        return sorted(states, key=lambda s: 0 if isinstance(s, dict) and s.get("key") in governing else 1)

    def _governing_cmd_keys(self) -> frozenset[str]:
        """Return the feature keys other features declare a dependency on.

        Read straight off :meth:`create_dependencies` so a device class
        declares the relationship once, for the Sber model descriptor, and
        both the command ordering and the echo consistency check follow
        from it.  The flip side is that a selector is only recognised
        while the dependency is actually declared: classes build that dict
        from the *final* feature list, so removing the dependent feature
        (``sber_features_remove``) also removes the selector from this set
        and :meth:`process_cmd` falls back to plain payload order.

        Returns:
            Frozen set of selector keys (e.g. ``{"light_mode"}``); empty
            for every device that declares no dependencies.
        """
        return frozenset(
            dep["key"]
            for dep in self.create_dependencies().values()
            if isinstance(dep, dict) and isinstance(dep.get("key"), str) and dep["key"]
        )

    @staticmethod
    def _merge_service_calls(results: list[CommandResult]) -> list[CommandResult]:
        """Fold service calls that address the same HA service into one.

        Two results merge when their ``domain``, ``service`` and
        ``target`` are equal; the merged call keeps the position of the
        first of them and its ``service_data`` is updated with each later
        contribution (last writer wins per field, which is what the
        sequential calls did anyway).  Non-service results
        (:class:`UpdateStateResult`) and calls to different services pass
        through untouched, in order.

        Merging stops short of building a call HA would reject as a
        whole: when the union would hold two fields from one
        :data:`EXCLUSIVE_SERVICE_DATA` group (``light_mode: white`` next
        to ``light_colour`` gives ``color_temp_kelvin`` + ``hs_color``),
        the contribution is left as its own call and becomes the target
        for the ones after it.  That is exactly the sequence of calls the
        bridge made before merging existed, so the outcome stays the old
        "last writer wins" instead of a ``vol.Invalid`` that costs the
        user the whole command, brightness included.

        The input dicts are never mutated: handlers may legitimately hand
        back shared literals.

        Args:
            results: Raw per-handler results, in execution order.

        Returns:
            The same results with same-service calls merged.
        """
        merged: list[CommandResult] = []
        positions: dict[tuple[str, str, str], int] = {}

        def open_call(url: dict, signature: tuple[str, str, str]) -> None:
            """Append ``url`` as a fresh call and make it the merge target."""
            positions[signature] = len(merged)
            copied: dict = dict(url)
            data = url.get("service_data")
            if isinstance(data, dict):
                copied["service_data"] = dict(data)
            merged.append({"url": copied})  # type: ignore[typeddict-item]

        for result in results:
            url = result.get("url") if isinstance(result, dict) else None
            if not isinstance(url, dict):
                merged.append(result)
                continue
            signature = (
                str(url.get("domain")),
                str(url.get("service")),
                json.dumps(url.get("target") or {}, sort_keys=True, default=str),
            )
            first = positions.get(signature)
            if first is None:
                open_call(url, signature)
                continue
            data = url.get("service_data")
            if not isinstance(data, dict) or not data:
                continue
            target_url: dict = merged[first]["url"]  # type: ignore[typeddict-item]
            current = target_url.get("service_data")
            if _breaks_exclusion(signature[0], signature[1], current if isinstance(current, dict) else {}, data):
                _LOGGER.debug(
                    "Keeping %s.%s separate: %s cannot travel with %s in one call",
                    signature[0],
                    signature[1],
                    sorted(data),
                    sorted(current or {}),
                )
                open_call(url, signature)
                continue
            target_url.setdefault("service_data", {}).update(data)
        return merged

    @property
    def _cmd_handlers(self) -> dict[str, Callable[[dict], list[CommandResult]]]:
        """Return dispatch map from Sber feature key to handler method.

        Override in subclasses that accept Sber commands.  Default is an
        empty dict — read-only sensors return ``[]`` automatically.
        """
        return {}

    @property
    def _is_online(self) -> bool:
        """Check if entity is online (reachable).

        By default, ``STATE_UNAVAILABLE``, ``STATE_UNKNOWN``, and ``None``
        (not loaded) all indicate offline. Subclasses for event-based
        sensors (binary_sensor) override this to treat ``STATE_UNKNOWN``
        as online — it means "no event yet", not "device unreachable".

        Returns:
            True if the entity state indicates it is reachable.
        """
        return self.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN, None)

    @property
    def is_online(self) -> bool:
        """Public accessor for entity online status.

        Returns:
            True if the entity state indicates it is reachable.
        """
        return self._is_online

    def process_state_change(self, _old_state: dict | None, new_state: dict) -> None:
        """Handle a state change event from Home Assistant.

        Default implementation refreshes internal state via fill_by_ha_state.
        Override in subclasses if additional processing is needed.

        Args:
            _old_state: Previous HA state dict (may be None). Reserved for
                subclass overrides that need to compare old and new state.
            new_state: New HA state dict.
        """
        self.fill_by_ha_state(new_state)

    def has_significant_change(self) -> bool:
        """Check if current Sber state differs from last published state.

        Used to avoid unnecessary MQTT publishes when only non-relevant
        HA attributes changed (e.g., last_updated, icon, etc.).

        Returns:
            True if the state has changed and should be published.
        """
        if self._previous_sber_state is None:
            return True
        try:
            current = self.to_sber_current_state()
        except (RuntimeError, TypeError, ValueError):
            return True
        return current != self._previous_sber_state

    def mark_state_published(self, *, snapshot: dict | NoSnapshot | None = NO_SNAPSHOT) -> None:
        """Record the state that was just published, for value diffing.

        Called after a successful MQTT publish so
        :meth:`has_significant_change` can suppress redundant publishes.

        Args:
            snapshot: The exact wire state that went out, captured
                *before* the publish awaited.  Passing it is the correct
                form for the publish path: re-serializing here would
                capture changes that raced in during the network
                round-trip and silently swallow them (lost update).
                ``None`` is a valid snapshot value and means "treat the
                entity as changed on the next diff".  When the argument
                is omitted entirely the current state is serialized now,
                which is only safe when no publish await intervened.
        """
        if not isinstance(snapshot, NoSnapshot):
            self._previous_sber_state = snapshot
            return
        try:
            self._previous_sber_state = self.to_sber_current_state()
        except (RuntimeError, TypeError, ValueError):
            self._previous_sber_state = None
