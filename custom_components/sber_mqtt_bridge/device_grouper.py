"""HA device grouping service for the device-centric wizard.

Given a Sber category, walks the HA device + entity + area registries
and returns one :class:`DeviceGroup` per HA device whose primary entity
can be promoted to that category.  Each group carries its classified
siblings — ``linked_native`` (same device_id, LinkableRole match),
``linked_compatible`` (other device_id, compatible role), and
``unsupported`` (firmware, diagnostic).

See ``docs/DEVICE_WIZARD_PLAN.md`` §2.1-2.4 for the design and
``docs/ARCHITECTURE_RESEARCH.md`` §1-4 for the HA registry contract
used here.

This service is stateless.  Callers construct a ``HaDeviceGrouper``
per request, run ``list_for_category`` or ``preview_for_category``,
serialize the result into the WebSocket response, and drop the
instance.  No caching — HA registries are cheap to read in-process.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .devices.base_entity import (
    ENERGY_LINK_ROLES,
    BaseEntity,
    LinkableRole,
    resolve_link_role,
    resolve_link_role_for,
)
from .sber_entity_map import (
    CATEGORY_DOMAIN_MAP,
    CategorySpec,
    categories_for_domain,
    create_sber_entity,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


def effective_device_class(entry: er.RegistryEntry) -> str:
    """Return the device class Home Assistant actually shows for ``entry``.

    HA keeps two values: ``original_device_class`` (what the integration
    reported) and ``device_class`` (the user's "Show as" override in the
    entity settings).  The override wins everywhere in HA, so it must win
    here too — otherwise a user who marks a cover as *Garage* to steer it
    into the Sber ``gate`` category is silently ignored (issues #50/#51).

    Args:
        entry: Entity registry entry.

    Returns:
        The effective device class, or ``""`` when neither is set.
    """
    return entry.device_class or entry.original_device_class or ""


CROSS_DEVICE_EXCLUDED_ROLES: frozenset[str] = frozenset(role.role for role in ENERGY_LINK_ROLES)
"""Roles that are never auto-offered from a *different* HA device.

A battery, a thermometer or a reed contact of another device can
plausibly describe this one — a Zigbee curtain motor whose battery is
published by a separate node, a room sensor next to a radiator — so the
wizard offers those as opt-in cross-device candidates.

Electrical readings are the opposite case: a wattmeter belongs to the
outlet it is wired into and measures nothing else.  Offering every
metering sensor in the house to every relay would fill each card with
dozens of wrong candidates (measured: 20 metering sockets turn every
plain relay's ``linked_compatible`` into 60 rows) and put a neighbour's
wattmeter into the wizard's energy block, where it looks like a
suggestion.  Manual linking through the link dialog stays available for
the rare external-meter setup.
"""


def _object_id(entity_id: str) -> str:
    """Return the object_id part of ``entity_id`` (``switch.plug`` → ``plug``)."""
    return entity_id.partition(".")[2]


def shares_channel_prefix(primary_entity_id: str, candidate_entity_id: str) -> bool:
    """Check whether a candidate entity_id names the primary's own channel.

    Multi-gang hardware (power strips, 2/4-channel relays) exposes every
    channel *and* every per-channel measurement under one HA device, so
    "same device_id" alone cannot say which power sensor belongs to which
    outlet.  Integrations that split channels name them consistently —
    ``switch.strip_l2`` next to ``sensor.strip_l2_power`` — so the
    primary's object_id being a prefix of the candidate's is the one
    reliable signal available.

    This is a *tie-break inside a single HA device only*: it is never
    used to pull in an entity of another device.  Cross-device linking
    stays strictly opt-in (see :meth:`HaDeviceGrouper._find_cross_device_links`),
    so a similarly named sensor of a different appliance can never be
    suggested by name.

    Args:
        primary_entity_id: Entity id of the primary (Sber) entity.
        candidate_entity_id: Entity id of a link candidate on the same device.

    Returns:
        True when the candidate's object_id equals the primary's or
        starts with it followed by ``_``.
    """
    primary_object = _object_id(primary_entity_id)
    if not primary_object:
        return False
    candidate_object = _object_id(candidate_entity_id)
    return candidate_object == primary_object or candidate_object.startswith(f"{primary_object}_")


def pick_role_match(
    primary_entity_id: str,
    candidates: list[er.RegistryEntry],
) -> er.RegistryEntry | None:
    """Choose the single candidate to auto-suggest for one link role.

    A role holds exactly one entity, so when a device offers several
    candidates for the same role (per-channel power sensors, a second
    temperature probe) picking "the first one the registry yields" is a
    coin flip that silently publishes a neighbouring channel's readings
    to Sber.  Guessing is refused instead: the extra candidates are still
    offered in the wizard, just unchecked, and the user decides.

    Args:
        primary_entity_id: Entity id of the primary entity.
        candidates: Entities of the *same HA device* that resolve to one
            and the same link role.

    Returns:
        The candidate to preselect, or ``None`` when the choice is
        ambiguous.
    """
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    same_channel = [entry for entry in candidates if shares_channel_prefix(primary_entity_id, entry.entity_id)]
    if len(same_channel) == 1:
        return same_channel[0]
    return None


def group_candidates_by_role(
    entries: list[er.RegistryEntry],
    accepted_roles: tuple[LinkableRole, ...],
) -> dict[str, list[er.RegistryEntry]]:
    """Bucket entities by the link role they fill for a given primary.

    Args:
        entries: Candidate registry entries (siblings of the primary).
        accepted_roles: ``LINKABLE_ROLES`` declared by the primary's Sber
            device class.  The role names are never hardcoded here, so a
            role added to a device class is picked up automatically.

    Returns:
        Mapping ``role name → candidates``, in registry order.  Entities
        matching no accepted role are omitted.
    """
    by_role: dict[str, list[er.RegistryEntry]] = {}
    for entry in entries:
        role = resolve_link_role_for(accepted_roles, entry.domain, effective_device_class(entry))
        if role:
            by_role.setdefault(role, []).append(entry)
    return by_role


def select_native_links(
    *,
    primary_entity_id: str,
    siblings: list[er.RegistryEntry],
    accepted_roles: tuple[LinkableRole, ...],
) -> dict[str, str]:
    """Pick one sibling per link role for a primary entity.

    Single source of truth shared by the wizard (which turns the result
    into preselected checkboxes) and ``auto_link_all`` (which writes it
    straight into ``entry.options``), so the two can never disagree about
    which sensor belongs to which socket.

    Args:
        primary_entity_id: Entity id of the primary entity.
        siblings: Entities of the same HA device, primary excluded.
        accepted_roles: ``LINKABLE_ROLES`` of the primary's device class.

    Returns:
        Mapping ``role name → entity_id``.  Roles whose candidate set is
        ambiguous are left out rather than guessed.
    """
    resolved: dict[str, str] = {}
    for role, candidates in group_candidates_by_role(siblings, accepted_roles).items():
        chosen = pick_role_match(primary_entity_id, candidates)
        if chosen is not None:
            resolved[role] = chosen.entity_id
    return resolved


class EntityRole(StrEnum):
    """Classification of an entity inside a :class:`DeviceGroup`."""

    PRIMARY = "primary"
    """Main Sber device (light, climate, switch, …)."""

    LINKED_NATIVE = "linked_native"
    """Companion sensor with same ``device_id`` as primary."""

    LINKED_COMPATIBLE = "linked_compatible"
    """Compatible sensor from a DIFFERENT device, offered opt-in."""

    UNSUPPORTED = "unsupported"
    """Entity that cannot be exposed to Sber (firmware, diagnostic, etc.)."""


@dataclass(frozen=True, slots=True)
class GroupedEntity:
    """Single HA entity inside a :class:`DeviceGroup`, with classification."""

    entity_id: str
    domain: str
    device_class: str
    friendly_name: str
    area: str
    role: EntityRole
    sber_category: str | None = None
    link_role: str | None = None
    is_cross_device: bool = False
    origin_device_id: str | None = None
    origin_device_name: str | None = None
    already_exposed: bool = False
    preselected: bool = False

    def to_dict(self) -> dict:
        """Serialize to a JSON-safe dict for the WebSocket response."""
        return {
            "entity_id": self.entity_id,
            "domain": self.domain,
            "device_class": self.device_class,
            "friendly_name": self.friendly_name,
            "area": self.area,
            "role": self.role.value,
            "sber_category": self.sber_category,
            "link_role": self.link_role,
            "is_cross_device": self.is_cross_device,
            "origin_device_id": self.origin_device_id,
            "origin_device_name": self.origin_device_name,
            "already_exposed": self.already_exposed,
            "preselected": self.preselected,
        }


@dataclass(slots=True)
class DeviceGroup:
    """HA device registry entry grouped with its classified entities.

    Mutable by design: :class:`HaDeviceGrouper` builds the group in
    several passes and tweaks fields after primary selection.  Serialized
    as a frozen dict via :meth:`to_dict` before leaving the WebSocket
    boundary.
    """

    device_id: str
    name: str
    manufacturer: str
    model: str
    area: str
    identifiers: list[tuple[str, str]]
    primary: GroupedEntity
    primary_alternatives: list[GroupedEntity] = field(default_factory=list)
    linked_native: list[GroupedEntity] = field(default_factory=list)
    linked_compatible: list[GroupedEntity] = field(default_factory=list)
    unsupported: list[GroupedEntity] = field(default_factory=list)
    already_exposed: bool = False
    accepted_roles: list[str] = field(default_factory=list)
    """Every link role the primary's Sber class accepts, filled or not.

    ``linked_native`` only ever names roles that found a candidate, so it
    cannot tell "this socket has no voltage sensor" from "this category
    has no voltage role" — the difference between an empty slot the user
    can fill by hand and a slot that must not be drawn at all.  The panel
    decides on this list rather than on a hardcoded category list
    (``www/link-roles.js::acceptsEnergyRoles``), so a category that
    starts accepting a role here needs no panel edit."""

    def to_dict(self) -> dict:
        """Serialize to a JSON-safe dict for the WebSocket response."""
        return {
            "device_id": self.device_id,
            "name": self.name,
            "manufacturer": self.manufacturer,
            "model": self.model,
            "area": self.area,
            "identifiers": [list(ident) for ident in self.identifiers],
            "already_exposed": self.already_exposed,
            "primary": self.primary.to_dict(),
            "primary_alternatives": [entity.to_dict() for entity in self.primary_alternatives],
            "linked_native": [entity.to_dict() for entity in self.linked_native],
            "linked_compatible": [entity.to_dict() for entity in self.linked_compatible],
            "unsupported": [entity.to_dict() for entity in self.unsupported],
            "accepted_roles": list(self.accepted_roles),
        }


class HaDeviceGrouper:
    """Classify HA devices and their entities for the device-centric wizard.

    Stateless service, one instance per WebSocket request.  Reads HA
    device / entity / area registries directly; does not cache.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        exposed_ids: set[str] | None = None,
    ) -> None:
        """Initialize the grouper.

        Args:
            hass: Home Assistant core instance.
            exposed_ids: Set of entity IDs already in
                ``config_entry.options[CONF_EXPOSED_ENTITIES]``.  Used to
                set the ``already_exposed`` flag so the UI can skip /
                highlight already-added devices.
        """
        self._hass = hass
        self._exposed = exposed_ids or set()
        self._entity_reg = er.async_get(hass)
        self._device_reg = dr.async_get(hass)
        self._area_reg = ar.async_get(hass)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_for_category(self, sber_category: str) -> list[DeviceGroup]:
        """Return all HA devices matching the given Sber category.

        Filters devices using :attr:`CATEGORY_DOMAIN_MAP[sber_category]`
        against each candidate primary entity.  Devices with no matching
        primary are excluded from the result entirely.

        Args:
            sber_category: Sber category the user picked in Step 1.

        Returns:
            List of :class:`DeviceGroup`, sorted by
            ``(not already_exposed, area, device.name)``.  Empty when no
            devices can be promoted to this category.
        """
        spec = CATEGORY_DOMAIN_MAP.get(sber_category)
        if spec is None:
            _LOGGER.warning("Unknown Sber category: %s", sber_category)
            return []

        # Group all enabled entities by device_id for O(1) sibling lookup
        entities_by_device: dict[str, list[er.RegistryEntry]] = {}
        orphan_entries: list[er.RegistryEntry] = []
        for entry in self._entity_reg.entities.values():
            if entry.disabled_by is not None:
                continue
            if entry.device_id is None:
                orphan_entries.append(entry)
            else:
                entities_by_device.setdefault(entry.device_id, []).append(entry)

        role_index = self._build_role_index(entities_by_device)
        results: list[DeviceGroup] = []

        # Regular device-backed entities
        for device in self._device_reg.devices.values():
            if device.disabled_by is not None:
                continue
            device_entries = entities_by_device.get(device.id, [])
            if not device_entries:
                continue

            group = self._build_group(
                device=device,
                device_entries=device_entries,
                sber_category=sber_category,
                role_index=role_index,
            )
            if group is not None:
                results.append(group)

        # Orphan entities (no device_id) — e.g. SmartIR, template entities.
        # Each becomes its own "virtual" device group.
        for entry in orphan_entries:
            if not spec.matches(entry.domain, effective_device_class(entry)):
                continue
            group = self._build_orphan_group(entry, sber_category)
            if group is not None:
                results.append(group)

        results.sort(
            key=lambda g: (
                1 if g.already_exposed else 0,
                g.area or "~",
                g.name.casefold(),
            )
        )
        return results

    def preview_for_category(
        self,
        device_id: str,
        sber_category: str,
        primary_entity_id: str | None = None,
    ) -> DeviceGroup | None:
        """Return grouping for a single device scoped to the given category.

        Convenience for the UI to re-fetch one device without re-listing
        everything.  Returns ``None`` if the device has no entity
        matching ``sber_category``.

        Args:
            device_id: HA device to preview.
            sber_category: Category to scope the preview to.
            primary_entity_id: Which entity of the device is the primary.
                Pass it whenever the caller already knows (link editing
                of an exposed entity): on a multi-gang device without it
                the preview describes whichever channel comes first,
                i.e. the wrong socket's companion sensors.
        """
        spec = CATEGORY_DOMAIN_MAP.get(sber_category)
        if spec is None:
            return None
        device = self._device_reg.async_get(device_id)
        if device is None or device.disabled_by is not None:
            return None

        device_entries: list[er.RegistryEntry] = []
        entities_by_device: dict[str, list[er.RegistryEntry]] = {}
        for entry in self._entity_reg.entities.values():
            if entry.device_id is None or entry.disabled_by is not None:
                continue
            entities_by_device.setdefault(entry.device_id, []).append(entry)
            if entry.device_id == device_id:
                device_entries.append(entry)

        if not device_entries:
            return None

        return self._build_group(
            device=device,
            device_entries=device_entries,
            sber_category=sber_category,
            role_index=self._build_role_index(entities_by_device),
            primary_entity_id=primary_entity_id,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_group(
        self,
        *,
        device: dr.DeviceEntry,
        device_entries: list[er.RegistryEntry],
        sber_category: str,
        role_index: dict[str, list[tuple[str, er.RegistryEntry]]],
        primary_entity_id: str | None = None,
    ) -> DeviceGroup | None:
        """Assemble one :class:`DeviceGroup` for a device + target category.

        Returns ``None`` when no entity of this device matches the target
        category (device is irrelevant for this wizard step).

        Multi-channel devices (power strips, multi-gang switches) are
        handled by surfacing every still-unexposed matching entity as a
        check-able primary in the wizard; already-exposed channels are
        filtered out so each subsequent wizard pass shows what's left to
        add and the card disables only when nothing remains.

        Args:
            device: HA device registry entry being classified.
            device_entries: Enabled entities of that device.
            sber_category: Target Sber category.
            role_index: Precomputed ``role → [(device_id, entry)]`` index.
            primary_entity_id: Pin the primary to this entity instead of
                letting :meth:`_select_primary` choose.  The link-editing
                flow knows exactly which channel the user opened, and on
                a multi-gang device the auto-picked channel would be a
                different socket with different companion sensors.
        """
        spec = CATEGORY_DOMAIN_MAP[sber_category]

        # 1. Pick primary + alternatives from device entries that match
        primary_entry, alternative_entries = self._select_primary(
            device_entries, spec, primary_entity_id=primary_entity_id
        )
        if primary_entry is None:
            return None

        # 2. Build GroupedEntity for primary
        primary = self._build_grouped_entity(
            entry=primary_entry,
            role=EntityRole.PRIMARY,
            sber_category=sber_category,
            device=device,
            preselected=True,
        )

        # 3. Instantiate Sber entity for primary to read LINKABLE_ROLES
        primary_class = self._instantiate_primary(primary_entry, sber_category)
        accepted_roles: tuple[LinkableRole, ...] = primary_class.LINKABLE_ROLES if primary_class is not None else ()

        # 4. Classify siblings (linked_native + unsupported)
        # Alternative primaries are NOT siblings of the primary — they are
        # peer Sber devices the user can multi-select.  Excluding them
        # keeps multi-gang switches out of the "Not usable" section where
        # they would otherwise leak as duplicates of the alternatives row.
        alternative_ids = {entry.entity_id for entry in alternative_entries}
        sibling_pool = [entry for entry in device_entries if entry.entity_id not in alternative_ids]
        linked_native, unsupported = self._classify_native_siblings(
            device_entries=sibling_pool,
            primary_entity_id=primary_entry.entity_id,
            device=device,
            accepted_roles=accepted_roles,
        )

        # 5. Find cross-device compatible sensors
        native_roles_used = {entity.link_role for entity in linked_native if entity.link_role is not None}
        linked_compatible = self._find_cross_device_links(
            primary_device_id=device.id,
            accepted_roles=accepted_roles,
            already_used_roles=native_roles_used,
            role_index=role_index,
        )

        # 6. Alternatives mapped into GroupedEntity
        alternatives = [
            self._build_grouped_entity(
                entry=alt_entry,
                role=EntityRole.PRIMARY,
                sber_category=sber_category,
                device=device,
                preselected=False,
            )
            for alt_entry in alternative_entries
        ]

        return DeviceGroup(
            device_id=device.id,
            name=device.name_by_user or device.name or device.model or device.id,
            manufacturer=device.manufacturer or "",
            model=device.model or "",
            area=self._resolve_area(device.area_id),
            identifiers=sorted(device.identifiers or set()),
            primary=primary,
            primary_alternatives=alternatives,
            linked_native=linked_native,
            linked_compatible=linked_compatible,
            unsupported=unsupported,
            already_exposed=primary_entry.entity_id in self._exposed,
            accepted_roles=[role.role for role in accepted_roles],
        )

    def _build_orphan_group(
        self,
        entry: er.RegistryEntry,
        sber_category: str,
    ) -> DeviceGroup | None:
        """Build a :class:`DeviceGroup` for an entity without a device_id.

        Orphan entities (SmartIR, template, etc.) have no HA device.
        We treat the entity itself as its own "virtual" device — no linked
        sensors, no alternatives, no cross-device links.  ``accepted_roles``
        is still filled so the panel renders the same link step shape for
        every group and can show the (empty) role slots.
        """
        friendly = entry.name or entry.original_name or entry.entity_id
        area = self._resolve_area(entry.area_id) if hasattr(entry, "area_id") else ""
        primary_class = self._instantiate_primary(entry, sber_category)
        primary = self._build_grouped_entity(
            entry=entry,
            role=EntityRole.PRIMARY,
            sber_category=sber_category,
            device=None,
            preselected=True,
        )
        return DeviceGroup(
            device_id=entry.entity_id,
            name=friendly,
            manufacturer=entry.platform or "",
            model="",
            area=area or "",
            identifiers=[],
            primary=primary,
            primary_alternatives=[],
            linked_native=[],
            linked_compatible=[],
            unsupported=[],
            already_exposed=entry.entity_id in self._exposed,
            accepted_roles=[role.role for role in primary_class.LINKABLE_ROLES] if primary_class is not None else [],
        )

    def _select_primary(
        self,
        device_entries: list[er.RegistryEntry],
        spec: CategorySpec,
        *,
        primary_entity_id: str | None = None,
    ) -> tuple[er.RegistryEntry | None, list[er.RegistryEntry]]:
        """Pick the primary entity for a device + category.

        When ``primary_entity_id`` names a matching entry that entry wins
        outright — the caller already knows which channel it is asking
        about, and picking another one would answer about a different
        socket of the same power strip.

        Returns ``(primary, alternatives)``.  Already-exposed entries are
        filtered out so the wizard surfaces only channels left to add —
        critical for multi-gang devices (power strips, 4-channel relays)
        where the user adds sockets in multiple passes.  When *all*
        matching entries are already exposed, returns ``(matching[0], rest)``
        unchanged so the caller can still flag the device as
        ``already_exposed=True`` instead of dropping it from the list.
        """
        matching = [entry for entry in device_entries if spec.matches(entry.domain, effective_device_class(entry))]
        if not matching:
            return None, []
        if primary_entity_id is not None:
            pinned = next((entry for entry in matching if entry.entity_id == primary_entity_id), None)
            if pinned is not None:
                return pinned, [entry for entry in matching if entry.entity_id != primary_entity_id]
        unexposed = [entry for entry in matching if entry.entity_id not in self._exposed]
        if unexposed:
            return unexposed[0], unexposed[1:]
        # Every channel already added — keep the device visible but flagged.
        return matching[0], matching[1:]

    def _classify_native_siblings(
        self,
        *,
        device_entries: list[er.RegistryEntry],
        primary_entity_id: str,
        device: dr.DeviceEntry,
        accepted_roles: tuple[LinkableRole, ...],
    ) -> tuple[list[GroupedEntity], list[GroupedEntity]]:
        """Classify non-primary siblings into (linked_native, unsupported).

        Every sibling that fills an accepted role is offered, but at most
        one per role is *preselected*: a role holds a single entity, so
        checking both per-channel power sensors of a power strip would
        make ``add_ha_device`` fail with ``role_conflict`` — and silently
        checking whichever came first would publish the neighbouring
        socket's watts.  :func:`select_native_links` decides, and refuses
        to guess when the candidates are indistinguishable.
        """
        linked: list[GroupedEntity] = []
        unsupported: list[GroupedEntity] = []
        accepted_role_names = {role.role for role in accepted_roles}

        siblings = [entry for entry in device_entries if entry.entity_id != primary_entity_id]
        preselected_ids = set(
            select_native_links(
                primary_entity_id=primary_entity_id,
                siblings=siblings,
                accepted_roles=accepted_roles,
            ).values()
        )

        for entry in siblings:
            dc = effective_device_class(entry)
            link_role = resolve_link_role(entry.domain, dc)
            if link_role and link_role in accepted_role_names:
                linked.append(
                    self._build_grouped_entity(
                        entry=entry,
                        role=EntityRole.LINKED_NATIVE,
                        sber_category=None,
                        device=device,
                        link_role=link_role,
                        preselected=entry.entity_id in preselected_ids,
                    )
                )
            else:
                unsupported.append(
                    self._build_grouped_entity(
                        entry=entry,
                        role=EntityRole.UNSUPPORTED,
                        sber_category=None,
                        device=device,
                        preselected=False,
                    )
                )
        return linked, unsupported

    @staticmethod
    def _build_role_index(
        entities_by_device: dict[str, list[er.RegistryEntry]],
    ) -> dict[str, list[tuple[str, er.RegistryEntry]]]:
        """Index linkable entities by role for cross-device lookup.

        Precomputes :func:`resolve_link_role` once per entity so that
        :meth:`_find_cross_device_links` — called once per candidate
        :class:`DeviceGroup` — scans only entities that actually resolve
        to a link role instead of rescanning every entity of every device
        (O(devices × total_entities) worst case on wide categories).

        Args:
            entities_by_device: Enabled registry entries grouped by device.

        Returns:
            Mapping ``link_role → [(device_id, entry), ...]``.
        """
        index: dict[str, list[tuple[str, er.RegistryEntry]]] = {}
        for device_id, entries in entities_by_device.items():
            for entry in entries:
                link_role = resolve_link_role(entry.domain, effective_device_class(entry))
                if link_role:
                    index.setdefault(link_role, []).append((device_id, entry))
        return index

    def _find_cross_device_links(
        self,
        *,
        primary_device_id: str,
        accepted_roles: tuple[LinkableRole, ...],
        already_used_roles: set[str],
        role_index: dict[str, list[tuple[str, er.RegistryEntry]]],
    ) -> list[GroupedEntity]:
        """Walk other devices for sensors that match primary's LinkableRoles.

        Excludes roles that are already filled by native siblings so we
        never offer two candidates for the same role, and roles listed in
        :data:`CROSS_DEVICE_EXCLUDED_ROLES`, which only ever make sense
        on the primary's own device.
        """
        if not accepted_roles:
            return []
        accepted_role_names = {
            role.role
            for role in accepted_roles
            if role.role not in already_used_roles and role.role not in CROSS_DEVICE_EXCLUDED_ROLES
        }
        if not accepted_role_names:
            return []

        results: list[GroupedEntity] = []
        origin_cache: dict[str, dr.DeviceEntry | None] = {}
        for link_role in accepted_role_names:
            for other_device_id, entry in role_index.get(link_role, []):
                if other_device_id == primary_device_id:
                    continue
                if other_device_id not in origin_cache:
                    device = self._device_reg.async_get(other_device_id)
                    origin_cache[other_device_id] = (
                        device if device is not None and device.disabled_by is None else None
                    )
                origin_device = origin_cache[other_device_id]
                if origin_device is None:
                    continue
                origin_name = origin_device.name_by_user or origin_device.name or origin_device.model or other_device_id
                results.append(
                    self._build_grouped_entity(
                        entry=entry,
                        role=EntityRole.LINKED_COMPATIBLE,
                        sber_category=None,
                        device=origin_device,
                        link_role=link_role,
                        preselected=False,
                        is_cross_device=True,
                        origin_device_id=other_device_id,
                        origin_device_name=origin_name,
                    )
                )
        # Sort for UI determinism: role first, then entity_id
        results.sort(key=lambda g: (g.link_role or "", g.entity_id))
        return results

    def _instantiate_primary(self, entry: er.RegistryEntry, sber_category: str) -> BaseEntity | None:
        """Build a stand-in Sber entity to read its ``LINKABLE_ROLES``.

        We don't need a populated state — only the class-level tuple.
        """
        entity_data = {
            "entity_id": entry.entity_id,
            "original_device_class": effective_device_class(entry),
            "name": entry.name or entry.original_name or entry.entity_id,
            "original_name": entry.original_name,
            "platform": entry.platform,
            "unique_id": entry.unique_id,
            "device_id": entry.device_id,
            "disabled_by": entry.disabled_by,
            "hidden_by": entry.hidden_by,
        }
        return create_sber_entity(entry.entity_id, entity_data, sber_category=sber_category)

    def _build_grouped_entity(
        self,
        *,
        entry: er.RegistryEntry,
        role: EntityRole,
        sber_category: str | None,
        device: dr.DeviceEntry | None,
        link_role: str | None = None,
        preselected: bool = False,
        is_cross_device: bool = False,
        origin_device_id: str | None = None,
        origin_device_name: str | None = None,
    ) -> GroupedEntity:
        """Fill a :class:`GroupedEntity` from a registry entry + classification."""
        device_area_id = device.area_id if device is not None else None
        area = self._resolve_area(entry.area_id) or self._resolve_area(device_area_id)
        friendly = self._resolve_friendly_name(entry)
        # Auto-detect category for link-candidate display when the caller
        # hasn't specified one (e.g. UNSUPPORTED entities).
        auto_category = sber_category
        if auto_category is None:
            matches = categories_for_domain(entry.domain, effective_device_class(entry))
            auto_category = matches[0] if matches else None

        return GroupedEntity(
            entity_id=entry.entity_id,
            domain=entry.domain,
            device_class=effective_device_class(entry),
            friendly_name=friendly,
            area=area,
            role=role,
            sber_category=auto_category,
            link_role=link_role,
            is_cross_device=is_cross_device,
            origin_device_id=origin_device_id,
            origin_device_name=origin_device_name,
            already_exposed=entry.entity_id in self._exposed,
            preselected=preselected,
        )

    # ------------------------------------------------------------------
    # Registry resolvers
    # ------------------------------------------------------------------

    def _resolve_area(self, area_id: str | None) -> str:
        """Resolve an area_id slug to its human-readable name."""
        if not area_id:
            return ""
        area = self._area_reg.async_get_area(area_id)
        return area.name if area else ""

    @staticmethod
    def _resolve_friendly_name(entry: er.RegistryEntry) -> str:
        """Return the best available display name for an entity."""
        return entry.name or entry.original_name or entry.entity_id
