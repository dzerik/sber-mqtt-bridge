"""Entity loader / registry for Sber MQTT Bridge.

Extracted from ``SberBridge`` to isolate HA entity registry lookups,
YAML overrides, link resolution, and conflict detection from the
bridge's transport and lifecycle concerns (SRP).

Usage::

    loader = SberEntityLoader(hass, entry)
    result = loader.load()
    # result.entities: dict[entity_id, BaseEntity]
    # result.enabled_entity_ids: list[str]
    # result.entity_links: dict[primary, dict[role, linked_id]]
    # result.linked_reverse: dict[linked_id, (primary, role)]
    # result.redefinitions: dict[entity_id, dict]
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_ENTITY_LINKS,
    CONF_ENTITY_TYPE_OVERRIDES,
    CONF_EXPOSED_ENTITIES,
)
from .custom_capabilities import get_custom_config
from .devices.base_entity import BaseEntity
from .sber_entity_map import create_sber_entity

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant


def _extract_mac(connections: set[tuple[str, str]] | None) -> str:
    """Pick a normalised MAC address from ``DeviceEntry.connections``.

    Returns the first ``CONNECTION_NETWORK_MAC`` entry (already normalised
    by HA) or empty string when none present.
    """
    if not connections:
        return ""
    for kind, value in connections:
        if kind == dr.CONNECTION_NETWORK_MAC and value:
            return value
    return ""


_LOGGER = logging.getLogger(__name__)


@dataclass
class EntityLoadResult:
    """Result of a full entity reload pass.

    Attributes:
        entities: Fresh dict of ``entity_id → BaseEntity``.
        enabled_entity_ids: Ordered list of exposed entity IDs.
        entity_links: Mapping primary entity → {role: linked_entity_id}.
        linked_reverse: Reverse mapping linked_entity_id → (primary, role).
        redefinitions: Updated redefinitions dict (pruned of stale entries).
    """

    entities: dict[str, BaseEntity] = field(default_factory=dict)
    enabled_entity_ids: list[str] = field(default_factory=list)
    entity_links: dict[str, dict[str, str]] = field(default_factory=dict)
    linked_reverse: dict[str, tuple[str, str]] = field(default_factory=dict)
    redefinitions: dict[str, dict] = field(default_factory=dict)


class SberEntityLoader:
    """Build Sber ``BaseEntity`` instances from HA registry and YAML config.

    This class owns the read-only lookup logic that turns HA entity
    registry entries into Sber-friendly entity objects.  It does NOT own
    runtime state (debouncing, MQTT, acknowledgments) — those stay in
    ``SberBridge``.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the loader.

        Args:
            hass: Home Assistant core instance.
            entry: Config entry providing options (exposed IDs, overrides).
        """
        self._hass = hass
        self._entry = entry

    def load(self, existing_redefinitions: dict[str, dict] | None = None) -> EntityLoadResult:
        """Perform a full entity reload pass.

        Uses a swap-on-replace pattern: callers receive a new result set
        and should atomically replace their previous state to avoid race
        conditions with concurrent readers.

        Args:
            existing_redefinitions: Current in-memory redefinitions; merged
                with persisted options before pruning stale entries.

        Returns:
            :class:`EntityLoadResult` ready for atomic swap.
        """
        result = EntityLoadResult()
        new_enabled = list(dict.fromkeys(self._entry.options.get(CONF_EXPOSED_ENTITIES, [])))
        custom_config = get_custom_config(self._hass)

        # Merge persisted + in-memory redefinitions (persisted wins when conflict
        # because it reflects user's most recent explicit edit).
        merged_redefs: dict[str, dict] = dict(existing_redefinitions or {})
        saved_redefs: dict[str, dict] = self._entry.options.get("redefinitions", {})
        if saved_redefs:
            merged_redefs.update(saved_redefs)
            _LOGGER.debug("Loaded %d persisted redefinitions from options", len(saved_redefs))

        result.entities = self._create_entities(new_enabled, custom_config)
        result.entity_links, result.linked_reverse = self._apply_entity_links(result.entities)
        self._check_device_conflicts(result.entities, result.linked_reverse)
        result.enabled_entity_ids = list(result.entities.keys())
        result.redefinitions = self._apply_room_overrides(merged_redefs, result.enabled_entity_ids, custom_config)
        # Prune stale redefinitions: keep only entries for still-enabled entities
        result.redefinitions = {k: v for k, v in result.redefinitions.items() if k in set(new_enabled)}
        _LOGGER.info(
            "Loaded %d Sber entities from %d exposed: %s",
            len(result.entities),
            len(result.enabled_entity_ids),
            ", ".join(result.enabled_entity_ids) if result.enabled_entity_ids else "(none)",
        )
        return result

    def _create_entities(
        self,
        enabled_ids: list[str],
        custom_config: dict,
    ) -> dict[str, BaseEntity]:
        """Create Sber entity objects from HA registry and fill initial state.

        Args:
            enabled_ids: Ordered list of entity IDs to expose.
            custom_config: YAML custom config dict.

        Returns:
            Dict mapping entity_id to the created BaseEntity subclass.
        """
        type_overrides: dict[str, str] = self._entry.options.get(CONF_ENTITY_TYPE_OVERRIDES, {})
        new_entities: dict[str, BaseEntity] = {}
        entity_reg = er.async_get(self._hass)
        device_reg = dr.async_get(self._hass)
        area_reg = ar.async_get(self._hass)

        for entity_id in enabled_ids:
            entry = entity_reg.async_get(entity_id)
            if entry is None:
                _LOGGER.warning("Entity %s not found in registry", entity_id)
                continue

            entity_area = area_reg.async_get_area(entry.area_id) if entry.area_id else None
            entity_data = {
                "entity_id": entry.entity_id,
                "area_id": entity_area.name if entity_area else "",
                "device_id": entry.device_id,
                "name": entry.name or entry.original_name or entry.entity_id,
                "original_name": entry.original_name,
                "platform": entry.platform,
                "unique_id": entry.unique_id,
                "original_device_class": entry.original_device_class or "",
                "entity_category": entry.entity_category,
                "icon": entry.icon,
                "disabled_by": entry.disabled_by,
                "hidden_by": entry.hidden_by,
            }

            yaml_cfg = custom_config.get(entity_id)
            sber_category = type_overrides.get(entity_id)
            if sber_category is None and yaml_cfg is not None and yaml_cfg.sber_type is not None:
                sber_category = yaml_cfg.sber_type
                _LOGGER.debug("YAML sber_type override for %s: %s", entity_id, sber_category)

            sber_entity = create_sber_entity(entity_id, entity_data, sber_category=sber_category)
            if sber_entity is None:
                continue

            new_entities[entity_id] = sber_entity
            self._apply_yaml_overrides(sber_entity, entity_id, yaml_cfg)
            self._link_device_registry(sber_entity, entry, device_reg, area_reg)

            state = self._hass.states.get(entity_id)
            if state is not None:
                ha_state_dict = {
                    "entity_id": state.entity_id,
                    "state": state.state,
                    "attributes": dict(state.attributes),
                }
                sber_entity.fill_by_ha_state(ha_state_dict)

        return new_entities

    @staticmethod
    def _apply_yaml_overrides(sber_entity: BaseEntity, entity_id: str, yaml_cfg: object | None) -> None:
        """Apply YAML config overrides (name, nicknames, groups, features)."""
        if yaml_cfg is None:
            return
        if yaml_cfg.sber_name is not None:
            sber_entity.name = yaml_cfg.sber_name
            _LOGGER.debug("YAML sber_name override for %s: %s", entity_id, yaml_cfg.sber_name)
        if yaml_cfg.sber_nicknames is not None:
            sber_entity.nicknames = yaml_cfg.sber_nicknames
        if yaml_cfg.sber_groups is not None:
            sber_entity.groups = yaml_cfg.sber_groups
        if yaml_cfg.sber_parent_id is not None:
            sber_entity.parent_entity_id = yaml_cfg.sber_parent_id
        if yaml_cfg.sber_partner_meta is not None:
            sber_entity.partner_meta = yaml_cfg.sber_partner_meta
        if yaml_cfg.sber_features_add is not None:
            sber_entity.extra_features = yaml_cfg.sber_features_add
            _LOGGER.debug("YAML sber_features_add for %s: %s", entity_id, yaml_cfg.sber_features_add)
        if yaml_cfg.sber_features_remove is not None:
            sber_entity.removed_features = yaml_cfg.sber_features_remove
            _LOGGER.debug("YAML sber_features_remove for %s: %s", entity_id, yaml_cfg.sber_features_remove)

    @staticmethod
    def _link_device_registry(
        sber_entity: BaseEntity,
        entry: object,
        device_reg: dr.DeviceRegistry,
        area_reg: ar.AreaRegistry | None = None,
    ) -> None:
        """Link device registry data to entity if it belongs to a device."""
        if entry.device_id is None:
            return
        device = device_reg.async_get(entry.device_id)
        if device is None:
            return
        device_area = area_reg.async_get_area(device.area_id) if area_reg and device.area_id else None
        device_data = {
            "id": device.id,
            "name": device.name_by_user or device.name,
            "area_id": device_area.name if device_area else (device.area_id or ""),
            "manufacturer": device.manufacturer or "Unknown",
            "model": device.model or "Unknown",
            "model_id": device.model_id or "",
            "hw_version": device.hw_version or "1",
            "sw_version": device.sw_version or "1",
            "serial_number": device.serial_number or "",
            "mac": _extract_mac(device.connections),
        }
        try:
            sber_entity.link_device(device_data)
        except ValueError:
            _LOGGER.warning("Device ID mismatch for %s", sber_entity.entity_id)

    def _apply_entity_links(
        self, new_entities: dict[str, BaseEntity]
    ) -> tuple[dict[str, dict[str, str]], dict[str, tuple[str, str]]]:
        """Resolve and apply entity links (linked sensors) from config options."""
        raw_links: dict[str, dict[str, str]] = self._entry.options.get(CONF_ENTITY_LINKS, {})
        new_links: dict[str, dict[str, str]] = {}
        new_reverse: dict[str, tuple[str, str]] = {}
        for primary_id, roles in raw_links.items():
            if primary_id not in new_entities:
                continue
            primary_entity = new_entities[primary_id]
            valid_roles: dict[str, str] = {}
            for role, linked_id in roles.items():
                # Guard: prevent linking an entity that is itself a primary —
                # would cause duplicate publication to Sber cloud.
                if linked_id in new_entities:
                    _LOGGER.warning(
                        "Entity %s is both a primary and a linked sensor for %s "
                        "(role=%s) — link ignored to prevent duplicate publication",
                        linked_id,
                        primary_id,
                        role,
                    )
                    continue
                valid_roles[role] = linked_id
                new_reverse[linked_id] = (primary_id, role)
                linked_state = self._hass.states.get(linked_id)
                if linked_state is None:
                    log_fn = _LOGGER.debug if not self._hass.is_running else _LOGGER.warning
                    log_fn(
                        "Linked entity %s (role=%s) for %s — state not yet available",
                        linked_id,
                        role,
                        primary_id,
                    )
                    continue
                ha_state_dict = {
                    "entity_id": linked_state.entity_id,
                    "state": linked_state.state,
                    "attributes": dict(linked_state.attributes),
                }
                primary_entity.update_linked_data(role, ha_state_dict)
                primary_entity.register_link(role, linked_id)
            if valid_roles:
                new_links[primary_id] = valid_roles
                _LOGGER.info("Entity links for %s: %s", primary_id, valid_roles)
        return new_links, new_reverse

    @staticmethod
    def _check_device_conflicts(
        new_entities: dict[str, BaseEntity],
        new_reverse: dict[str, tuple[str, str]],
    ) -> None:
        """Warn about multiple entities sharing the same physical device."""
        linked_ids = set(new_reverse.keys())
        device_entities: dict[str, list[str]] = {}
        for eid, ent in new_entities.items():
            if eid in linked_ids:
                continue
            did = getattr(ent, "device_id", None)
            if did:
                device_entities.setdefault(did, []).append(eid)
        for did, eids in device_entities.items():
            if len(eids) > 1:
                _LOGGER.warning(
                    "Device %s has %d entities in Sber (may cause duplicates): %s",
                    did,
                    len(eids),
                    ", ".join(eids),
                )

    @staticmethod
    def _apply_room_overrides(
        redefinitions: dict[str, dict],
        enabled_ids: list[str],
        custom_config: dict,
    ) -> dict[str, dict]:
        """Merge YAML room overrides into redefinitions."""
        redefinitions = dict(redefinitions)
        for entity_id in enabled_ids:
            yaml_cfg = custom_config.get(entity_id)
            if yaml_cfg is None or yaml_cfg.sber_room is None:
                continue
            if entity_id not in redefinitions:
                redefinitions[entity_id] = {"room": yaml_cfg.sber_room}
            elif "room" not in redefinitions[entity_id]:
                redefinitions[entity_id]["room"] = yaml_cfg.sber_room
            _LOGGER.debug("YAML sber_room override for %s: %s", entity_id, yaml_cfg.sber_room)
        return redefinitions
