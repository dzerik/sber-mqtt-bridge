"""Base entity class for Sber Smart Home device representations.

All device types (light, relay, climate, etc.) inherit from BaseEntity.
It defines the contract for converting between HA states and Sber JSON protocol.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import ClassVar, TypedDict

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN

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
    """AttrSpec parser: convert to int via float (handles ``"22.5"`` strings)."""
    if value is None:
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _safe_float_parser(value: object) -> float | None:
    """AttrSpec parser: convert to float."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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

    def get_final_features_list(self) -> list[str]:
        """Return features list with user overrides applied.

        Removes features from ``removed_features`` and appends features
        from ``extra_features``.  Duplicate-safe.

        Returns:
            Final list of Sber feature names.
        """
        features = self._create_features_list()
        if self.removed_features:
            features = [f for f in features if f not in self.removed_features]
        if self.extra_features:
            existing = set(features)
            features.extend(f for f in self.extra_features if f not in existing)
        return features

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
            "model": self._build_model_descriptor(device, display_name),
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

    def _build_model_descriptor(self, device: DeviceData, display_name: str) -> dict:
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
            display_name: Resolved display name for description.

        Returns:
            Model descriptor dict ready for ``to_sber_state`` output.
        """
        raw_model_id = device.get("model_id", "") if self.linked_device else ""
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

        descriptor: dict = {
            "id": f"{model_id}_{self._capability_digest(features, allowed)}",
            "manufacturer": device.get("manufacturer") or "Unknown",
            "model": device.get("model") or "Unknown",
            "description": display_name,
            "category": self.category,
            "features": features,
        }
        if allowed:
            descriptor["allowed_values"] = allowed
        deps = self.create_dependencies()
        if deps:
            descriptor["dependencies"] = deps
        return descriptor

    @staticmethod
    def _capability_digest(features: Iterable[str], allowed_values: dict[str, dict]) -> str:
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

        Args:
            features: Final feature names (order irrelevant).
            allowed_values: ``allowed_values`` map already reconciled
                with ``features``.

        Returns:
            8-character lowercase hex digest.
        """
        canonical = json.dumps(
            {"features": sorted(set(features)), "allowed_values": allowed_values},
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
        returns the concatenated service-call list.

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
        for item in cmd_data.get("states", []):
            handler = handlers.get(item.get("key", ""))
            if handler is None:
                continue
            # Sber omits proto3-default fields: {"type": "INTEGER"} means 0.
            # Normalize here so every handler sees a complete value dict.
            results.extend(handler(normalize_sber_value(item.get("value", {}))))
        return results

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
