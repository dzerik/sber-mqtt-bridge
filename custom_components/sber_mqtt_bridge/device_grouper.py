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

from .devices.base_entity import BaseEntity, LinkableRole, resolve_link_role
from .sber_entity_map import (
    CATEGORY_DOMAIN_MAP,
    categories_for_domain,
    create_sber_entity,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


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
                all_entities_by_device=entities_by_device,
            )
            if group is not None:
                results.append(group)

        # Orphan entities (no device_id) — e.g. SmartIR, template entities.
        # Each becomes its own "virtual" device group.
        for entry in orphan_entries:
            if not spec.matches(entry.domain, entry.original_device_class or ""):
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

    def preview_for_category(self, device_id: str, sber_category: str) -> DeviceGroup | None:
        """Return grouping for a single device scoped to the given category.

        Convenience for the UI to re-fetch one device without re-listing
        everything.  Returns ``None`` if the device has no entity
        matching ``sber_category``.
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
            all_entities_by_device=entities_by_device,
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
        all_entities_by_device: dict[str, list[er.RegistryEntry]],
    ) -> DeviceGroup | None:
        """Assemble one :class:`DeviceGroup` for a device + target category.

        Returns ``None`` when no entity of this device matches the target
        category (device is irrelevant for this wizard step).

        Multi-channel devices (power strips, multi-gang switches) are
        handled by surfacing every still-unexposed matching entity as a
        check-able primary in the wizard; already-exposed channels are
        filtered out so each subsequent wizard pass shows what's left to
        add and the card disables only when nothing remains.
        """
        spec = CATEGORY_DOMAIN_MAP[sber_category]

        # 1. Pick primary + alternatives from device entries that match
        primary_entry, alternative_entries = self._select_primary(device_entries, spec)
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
            all_entities_by_device=all_entities_by_device,
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
        )

    def _build_orphan_group(
        self,
        entry: er.RegistryEntry,
        sber_category: str,
    ) -> DeviceGroup | None:
        """Build a :class:`DeviceGroup` for an entity without a device_id.

        Orphan entities (SmartIR, template, etc.) have no HA device.
        We treat the entity itself as its own "virtual" device — no linked
        sensors, no alternatives, no cross-device links.
        """
        friendly = entry.name or entry.original_name or entry.entity_id
        area = self._resolve_area(entry.area_id) if hasattr(entry, "area_id") else ""
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
        )

    def _select_primary(
        self,
        device_entries: list[er.RegistryEntry],
        spec,  # CategorySpec, avoid circular import
    ) -> tuple[er.RegistryEntry | None, list[er.RegistryEntry]]:
        """Pick the primary entity for a device + category.

        Returns ``(primary, alternatives)``.  Already-exposed entries are
        filtered out so the wizard surfaces only channels left to add —
        critical for multi-gang devices (power strips, 4-channel relays)
        where the user adds sockets in multiple passes.  When *all*
        matching entries are already exposed, returns ``(matching[0], rest)``
        unchanged so the caller can still flag the device as
        ``already_exposed=True`` instead of dropping it from the list.
        """
        matching = [entry for entry in device_entries if spec.matches(entry.domain, entry.original_device_class or "")]
        if not matching:
            return None, []
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
        """Classify non-primary siblings into (linked_native, unsupported)."""
        linked: list[GroupedEntity] = []
        unsupported: list[GroupedEntity] = []
        accepted_role_names = {role.role for role in accepted_roles}

        for entry in device_entries:
            if entry.entity_id == primary_entity_id:
                continue
            dc = entry.original_device_class or ""
            link_role = resolve_link_role(entry.domain, dc)
            if link_role and link_role in accepted_role_names:
                linked.append(
                    self._build_grouped_entity(
                        entry=entry,
                        role=EntityRole.LINKED_NATIVE,
                        sber_category=None,
                        device=device,
                        link_role=link_role,
                        preselected=True,
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

    def _find_cross_device_links(
        self,
        *,
        primary_device_id: str,
        accepted_roles: tuple[LinkableRole, ...],
        already_used_roles: set[str],
        all_entities_by_device: dict[str, list[er.RegistryEntry]],
    ) -> list[GroupedEntity]:
        """Walk other devices for sensors that match primary's LinkableRoles.

        Excludes roles that are already filled by native siblings so we
        never offer two candidates for the same role.
        """
        if not accepted_roles:
            return []
        accepted_role_names = {role.role for role in accepted_roles if role.role not in already_used_roles}
        if not accepted_role_names:
            return []

        results: list[GroupedEntity] = []
        for other_device_id, entries in all_entities_by_device.items():
            if other_device_id == primary_device_id:
                continue
            origin_device = self._device_reg.async_get(other_device_id)
            if origin_device is None or origin_device.disabled_by is not None:
                continue
            origin_name = origin_device.name_by_user or origin_device.name or origin_device.model or other_device_id
            for entry in entries:
                dc = entry.original_device_class or ""
                link_role = resolve_link_role(entry.domain, dc)
                if not link_role or link_role not in accepted_role_names:
                    continue
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
            "original_device_class": entry.original_device_class or "",
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
            matches = categories_for_domain(entry.domain, entry.original_device_class)
            auto_category = matches[0] if matches else None

        return GroupedEntity(
            entity_id=entry.entity_id,
            domain=entry.domain,
            device_class=entry.original_device_class or "",
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
