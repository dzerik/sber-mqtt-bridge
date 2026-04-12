"""Device-centric wizard WebSocket commands (v1.26.0).

Replaces the legacy entity-first ``ws_add_device_wizard`` /
``ws_suggest_links`` / ``ws_get_available_entities`` / ``ws_bulk_add``
pipeline with a type-first flow:

1. ``sber_mqtt_bridge/list_categories`` — Step 1 grid data
2. ``sber_mqtt_bridge/list_devices_for_category`` — Step 2 device list
3. ``sber_mqtt_bridge/add_ha_device`` — Step 3 atomic add

See ``docs/DEVICE_WIZARD_PLAN.md`` §2.3 for the contract + edge cases.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from ..const import (
    CONF_ENTITY_LINKS,
    CONF_ENTITY_TYPE_OVERRIDES,
    CONF_EXPOSED_ENTITIES,
)
from ..device_grouper import HaDeviceGrouper
from ..devices.base_entity import resolve_link_role
from ..sber_entity_map import (
    CATEGORY_DOMAIN_MAP,
    CATEGORY_GROUPS,
    CATEGORY_UI_META,
    create_sber_entity,
)
from ._common import get_bridge, get_config_entry

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Command 1: list_categories
# ---------------------------------------------------------------------------


@websocket_api.websocket_command({vol.Required("type"): "sber_mqtt_bridge/list_categories"})
@callback
def ws_list_categories(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return the Sber category registry for wizard Step 1.

    Serializes :data:`CATEGORY_DOMAIN_MAP` + :data:`CATEGORY_UI_META` +
    :data:`CATEGORY_GROUPS` into a single frontend-friendly payload.

    Only categories with ``CategoryUiMeta.user_selectable=True`` end up
    in the ``categories`` list — internal subcategories like
    ``sensor_humidity`` are filtered out (users pick a parent category
    and classification picks the subcategory at add time).
    """
    categories: list[dict[str, Any]] = []
    for cat_id, spec in CATEGORY_DOMAIN_MAP.items():
        meta = CATEGORY_UI_META.get(cat_id)
        if meta is None or not meta.user_selectable:
            continue
        categories.append(
            {
                "id": cat_id,
                "group": meta.group,
                "icon": meta.icon,
                "label": meta.label_key,
                "domains": list(spec.domains),
                "device_classes": (list(spec.device_classes) if spec.device_classes else None),
                "preferred_rank": spec.preferred_rank,
            }
        )
    categories.sort(key=lambda c: (c["group"], c["preferred_rank"], c["label"]))

    connection.send_result(
        msg["id"],
        {
            "categories": categories,
            "groups": [{"id": group_id, "label": label} for group_id, label in CATEGORY_GROUPS],
        },
    )


# ---------------------------------------------------------------------------
# Command 2: list_devices_for_category
# ---------------------------------------------------------------------------


@websocket_api.websocket_command(
    {
        vol.Required("type"): "sber_mqtt_bridge/list_devices_for_category",
        vol.Required("category"): str,
    }
)
@websocket_api.async_response
async def ws_list_devices_for_category(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """List HA devices whose primary entity promotes to the given category."""
    category: str = msg["category"]
    if category not in CATEGORY_DOMAIN_MAP:
        connection.send_error(msg["id"], "unknown_category", f"Sber category {category!r} is not registered")
        return

    entry = get_config_entry(hass)
    exposed: set[str] = set(entry.options.get(CONF_EXPOSED_ENTITIES, [])) if entry else set()
    grouper = HaDeviceGrouper(hass, exposed_ids=exposed)
    groups = grouper.list_for_category(category)

    serialized = [group.to_dict() for group in groups]
    exposed_count = sum(1 for g in groups if g.already_exposed)
    connection.send_result(
        msg["id"],
        {
            "category": category,
            "devices": serialized,
            "summary": {
                "total": len(serialized),
                "already_exposed": exposed_count,
                "unexposed": len(serialized) - exposed_count,
            },
        },
    )


# ---------------------------------------------------------------------------
# Command 3: add_ha_device
# ---------------------------------------------------------------------------


@websocket_api.websocket_command(
    {
        vol.Required("type"): "sber_mqtt_bridge/add_ha_device",
        vol.Required("device_id"): str,
        vol.Required("primary_entity_id"): str,
        vol.Required("category"): str,
        vol.Optional("linked_entity_ids", default=[]): [str],
        vol.Optional("name"): str,
        vol.Optional("room"): str,
    }
)
@websocket_api.async_response
async def ws_add_ha_device(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Atomically add a HA device to the Sber exposed set.

    Validates the payload, builds a single config-entry options patch
    (exposed_entities + type_overrides + entity_links + redefinitions)
    and triggers one entry reload.  Replaces the legacy
    ``ws_add_device_wizard`` endpoint.
    """
    entry = get_config_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "entry_not_found", "Config entry not found")
        return

    category: str = msg["category"]
    spec = CATEGORY_DOMAIN_MAP.get(category)
    if spec is None:
        connection.send_error(msg["id"], "unknown_category", f"Sber category {category!r} is not registered")
        return

    from homeassistant.helpers import entity_registry as er

    entity_reg = er.async_get(hass)
    primary_id: str = msg["primary_entity_id"]
    primary_entry = entity_reg.async_get(primary_id)
    if primary_entry is None:
        connection.send_error(msg["id"], "primary_not_found", f"Entity {primary_id} not in registry")
        return

    device_id: str = msg["device_id"]
    if primary_entry.device_id != device_id:
        connection.send_error(
            msg["id"],
            "primary_device_mismatch",
            f"Entity {primary_id} does not belong to device {device_id}",
        )
        return

    if not spec.matches(primary_entry.domain, primary_entry.original_device_class or ""):
        connection.send_error(
            msg["id"],
            "primary_category_mismatch",
            f"Entity {primary_id} cannot be promoted to category {category!r}",
        )
        return

    # ------------------------------------------------------------------
    # Resolve linked sensors → role mapping via the primary's Sber class.
    # ------------------------------------------------------------------
    primary_sber = create_sber_entity(
        primary_id,
        {
            "entity_id": primary_entry.entity_id,
            "original_device_class": primary_entry.original_device_class or "",
            "device_id": primary_entry.device_id,
            "name": primary_entry.name or primary_entry.original_name or primary_id,
            "original_name": primary_entry.original_name,
            "platform": primary_entry.platform,
            "unique_id": primary_entry.unique_id,
        },
        sber_category=category,
    )
    accepted_role_names = {r.role for r in primary_sber.LINKABLE_ROLES} if primary_sber is not None else set()

    linked_entity_ids: list[str] = list(msg.get("linked_entity_ids", []))
    role_mapping: dict[str, str] = {}
    for linked_id in linked_entity_ids:
        linked_entry = entity_reg.async_get(linked_id)
        if linked_entry is None:
            connection.send_error(msg["id"], "linked_not_found", f"Entity {linked_id} not in registry")
            return
        link_role = resolve_link_role(linked_entry.domain, linked_entry.original_device_class or "")
        if not link_role or link_role not in accepted_role_names:
            connection.send_error(
                msg["id"],
                "linked_role_not_accepted",
                f"Entity {linked_id} does not map to a role accepted by {category}",
            )
            return
        if link_role in role_mapping:
            connection.send_error(
                msg["id"],
                "role_conflict",
                f"Two linked entities claim role {link_role!r}",
            )
            return
        role_mapping[link_role] = linked_id

    # ------------------------------------------------------------------
    # Build the atomic options patch
    # ------------------------------------------------------------------
    new_options = dict(entry.options)

    exposed: list[str] = list(new_options.get(CONF_EXPOSED_ENTITIES, []))
    if primary_id not in exposed:
        exposed.append(primary_id)
    new_options[CONF_EXPOSED_ENTITIES] = exposed

    overrides: dict[str, str] = dict(new_options.get(CONF_ENTITY_TYPE_OVERRIDES, {}))
    overrides[primary_id] = category
    new_options[CONF_ENTITY_TYPE_OVERRIDES] = overrides

    all_links: dict[str, dict] = dict(new_options.get(CONF_ENTITY_LINKS, {}))
    if role_mapping:
        all_links[primary_id] = role_mapping
    else:
        all_links.pop(primary_id, None)
    new_options[CONF_ENTITY_LINKS] = all_links

    name = (msg.get("name") or "").strip()
    room = (msg.get("room") or "").strip()
    if name or room:
        redefs: dict[str, dict] = dict(new_options.get("redefinitions", {}))
        entity_redef = dict(redefs.get(primary_id, {}))
        if name:
            entity_redef["name"] = name
        if room:
            entity_redef["room"] = room
        redefs[primary_id] = entity_redef
        new_options["redefinitions"] = redefs

    hass.config_entries.async_update_entry(entry, options=new_options)
    await hass.config_entries.async_reload(entry.entry_id)

    connection.send_result(
        msg["id"],
        {
            "success": True,
            "device_id": device_id,
            "primary_entity_id": primary_id,
            "category": category,
            "linked_count": len(role_mapping),
        },
    )


# ---------------------------------------------------------------------------
# Command 4: suggest_links (post-add edit flow)
# ---------------------------------------------------------------------------


@websocket_api.websocket_command(
    {
        vol.Required("type"): "sber_mqtt_bridge/suggest_links",
        vol.Required("entity_id"): str,
        vol.Optional("category"): str,
    }
)
@websocket_api.async_response
async def ws_suggest_links(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return link candidates for an already-exposed primary entity.

    Used by ``sber-link-dialog`` to let the user re-edit linked sensors
    after a device has been added.  Thin wrapper over
    :class:`HaDeviceGrouper.preview_for_category` that flattens
    ``linked_native`` + ``linked_compatible`` into the legacy
    ``candidates`` list shape the frontend expects.
    """
    from homeassistant.helpers import entity_registry as er

    entity_id: str = msg["entity_id"]
    entity_reg = er.async_get(hass)
    primary_entry = entity_reg.async_get(entity_id)
    if not primary_entry or not primary_entry.device_id:
        connection.send_result(msg["id"], {"candidates": [], "allowed_roles": [], "category": ""})
        return

    bridge = get_bridge(hass)
    primary_category = msg.get("category") or ""
    if not primary_category and bridge is not None:
        entity = bridge.entities.get(entity_id)
        if entity is not None:
            primary_category = entity.category
    if not primary_category:
        # Fallback to auto-detect via create_sber_entity
        sber = create_sber_entity(
            entity_id,
            {
                "entity_id": entity_id,
                "original_device_class": primary_entry.original_device_class or "",
            },
        )
        primary_category = sber.category if sber is not None else ""
    if primary_category not in CATEGORY_DOMAIN_MAP:
        connection.send_result(msg["id"], {"candidates": [], "allowed_roles": [], "category": primary_category})
        return

    grouper = HaDeviceGrouper(hass)
    group = grouper.preview_for_category(primary_entry.device_id, primary_category)
    if group is None:
        connection.send_result(msg["id"], {"candidates": [], "allowed_roles": [], "category": primary_category})
        return

    existing_links: dict[str, str] = {}
    if bridge is not None:
        existing_links = bridge.entity_links.get(entity_id, {})

    candidates: list[dict[str, Any]] = []
    allowed_roles: set[str] = set()
    for link in [*group.linked_native, *group.linked_compatible]:
        if link.link_role:
            allowed_roles.add(link.link_role)
        candidates.append(
            {
                "entity_id": link.entity_id,
                "domain": link.domain,
                "device_class": link.device_class,
                "friendly_name": link.friendly_name,
                "suggested_role": link.link_role or "",
                "compatible": True,
                "same_device": not link.is_cross_device,
                "currently_linked": link.entity_id in existing_links.values(),
                "linked_role": next(
                    (role for role, eid in existing_links.items() if eid == link.entity_id),
                    "",
                ),
            }
        )
    candidates.sort(key=lambda c: (not c["same_device"], c["friendly_name"]))

    connection.send_result(
        msg["id"],
        {
            "candidates": candidates,
            "allowed_roles": sorted(allowed_roles),
            "category": primary_category,
        },
    )
