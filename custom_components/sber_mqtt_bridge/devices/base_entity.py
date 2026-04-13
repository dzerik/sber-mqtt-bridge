"""Base entity class for Sber Smart Home device representations.

All device types (light, relay, climate, etc.) inherit from BaseEntity.
It defines the contract for converting between HA states and Sber JSON protocol.
"""

from __future__ import annotations

import copy
import hashlib
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from typing import ClassVar, TypedDict

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN

from ..sber_constants import SERVICE_CALL_TYPE, SERVICE_TURN_OFF, SERVICE_TURN_ON

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

SENSOR_LINK_ROLES: tuple[LinkableRole, ...] = (ROLE_BATTERY, ROLE_BATTERY_LOW, ROLE_SIGNAL)
"""Common linkable roles for battery-powered devices (sensors, covers, valves)."""

ALL_LINKABLE_ROLES: tuple[LinkableRole, ...] = (
    ROLE_BATTERY,
    ROLE_BATTERY_LOW,
    ROLE_SIGNAL,
    ROLE_TEMPERATURE,
    ROLE_HUMIDITY,
)
"""Global registry of all known linkable roles for display in UI."""


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
    for lr in ALL_LINKABLE_ROLES:
        if lr.matches(domain, device_class):
            return lr.role
    return ""


class BaseEntity(ABC):
    """Abstract base class for all Sber device entities.

    Defines the interface that all device types must implement:
    - fill_by_ha_state: Parse HA state into internal representation
    - _create_features_list: Return Sber feature names
    - to_sber_state: Build Sber device config JSON
    - to_sber_current_state: Build Sber current state JSON
    - process_cmd: Handle Sber commands, return HA service calls
    - process_state_change: Handle HA state change events
    """

    LINKABLE_ROLES: ClassVar[tuple[LinkableRole, ...]] = ()
    """Linkable roles this device class accepts. Override in subclasses."""

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

        Appends category suffix to model_id to prevent Sber cloud from
        overriding our category based on its own model database.

        Args:
            device: Device registry data dict (may be empty).
            display_name: Resolved display name for description.

        Returns:
            Model descriptor dict ready for ``to_sber_state`` output.
        """
        raw_model_id = device.get("model_id", "") if self.linked_device else ""
        model_id = f"{raw_model_id}_{self.category}" if raw_model_id else f"Mdl_{self.category}"

        # Instance-specific allowed_values (e.g. TV source_list) must produce
        # a unique model_id — Sber cloud stores one model per id, so devices
        # sharing an id with different allowed_values get silently rejected.
        allowed = self.create_allowed_values_list()
        if allowed and self._has_instance_allowed_values():
            digest = hashlib.md5(str(sorted(allowed.items())).encode(), usedforsecurity=False).hexdigest()[:8]
            model_id = f"{model_id}_{digest}"

        descriptor: dict = {
            "id": model_id,
            "manufacturer": device.get("manufacturer") or "Unknown",
            "model": device.get("model") or "Unknown",
            "description": display_name,
            "category": self.category,
            "features": self.get_final_features_list(),
        }
        if allowed:
            descriptor["allowed_values"] = allowed
        deps = self.create_dependencies()
        if deps:
            descriptor["dependencies"] = deps
        return descriptor

    def _has_instance_allowed_values(self) -> bool:
        """Return True if allowed_values vary per entity instance.

        Override in subclasses where allowed_values depend on runtime data
        (e.g. TV source_list) rather than being static for the category.
        When True, model_id gets an MD5 suffix to avoid Sber cloud
        collisions between devices of the same model but different
        allowed_values.
        """
        return False

    @abstractmethod
    def to_sber_current_state(self) -> dict:
        """Build Sber current state JSON for MQTT publish.

        Returns:
            Dict with entity_id key mapping to {'states': [...]}.
        """

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

    @abstractmethod
    def process_cmd(self, cmd_data: dict) -> list[CommandResult]:
        """Process a command from Sber cloud.

        Args:
            cmd_data: Command payload with 'states' list, or None.

        Returns:
            List of :class:`ServiceCallResult` or :class:`UpdateStateResult`
            items, or empty list if no action needed or cmd_data is None.
        """
        return []

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

    def process_state_change(self, old_state: dict | None, new_state: dict) -> None:
        """Handle a state change event from Home Assistant.

        Default implementation refreshes internal state via fill_by_ha_state.
        Override in subclasses if additional processing is needed.

        Args:
            old_state: Previous HA state dict (may be None).
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

    def mark_state_published(self) -> None:
        """Snapshot current Sber state as the last published state.

        Called after successful MQTT publish to enable value diffing.
        """
        try:
            self._previous_sber_state = self.to_sber_current_state()
        except (RuntimeError, TypeError, ValueError):
            self._previous_sber_state = None
