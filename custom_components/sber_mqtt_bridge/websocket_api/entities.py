"""Entity management commands (add, remove, override, clear).

Raw entity-level operations preserved for the Options Flow fallback
path and CLI scripting.  The device-centric wizard lives in
:mod:`.devices_grouped`.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from ..const import (
    CONF_ENTITY_LINKS,
    CONF_ENTITY_OPTIONS,
    CONF_ENTITY_TYPE_OVERRIDES,
    CONF_EXPOSED_ENTITIES,
)
from ..devices.gate import (
    GATE_OPTION_AUTO_CLOSE_TIME,
    GATE_OPTION_IMPULSE_SERVICE,
    GATE_OPTION_INVERT_CONTACT,
    GATE_OPTION_TRAVEL_TIME,
    IMPULSE_SERVICE_OPTIONS,
)
from ._common import (  # noqa: F401 — get_bridge / get_config_entry re-exported for test patching
    ENTITY_OPTIONS_SCHEMA,
    OVERRIDABLE_CATEGORIES,
    WS_AUTO_CLOSE_TIME,
    WS_ENTITY_ID,
    WS_ENTITY_IDS,
    WS_TRAVEL_TIME,
    get_bridge,
    get_config_entry,
    requires_bridge,
    requires_entry,
)

_LOGGER = logging.getLogger(__name__)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "sber_mqtt_bridge/add_entities",
        vol.Required("entity_ids"): vol.All(WS_ENTITY_IDS, vol.Length(min=1)),
    }
)
@websocket_api.async_response
@requires_entry
async def ws_add_entities(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    entry: Any,
) -> None:
    """Add entities to the exposed list and reload the integration."""
    current: list[str] = list(entry.options.get(CONF_EXPOSED_ENTITIES, []))
    current_set = set(current)
    added: list[str] = []

    for eid in msg["entity_ids"]:
        if eid not in current_set:
            current.append(eid)
            current_set.add(eid)
            added.append(eid)

    if added:
        new_options = dict(entry.options)
        new_options[CONF_EXPOSED_ENTITIES] = current
        hass.config_entries.async_update_entry(entry, options=new_options)
        await hass.config_entries.async_reload(entry.entry_id)

    connection.send_result(msg["id"], {"added": added, "total": len(current)})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "sber_mqtt_bridge/remove_entities",
        vol.Required("entity_ids"): vol.All(WS_ENTITY_IDS, vol.Length(min=1)),
    }
)
@websocket_api.async_response
@requires_entry
async def ws_remove_entities(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    entry: Any,
) -> None:
    """Remove entities from the exposed list and reload the integration."""
    to_remove = set(msg["entity_ids"])
    current: list[str] = list(entry.options.get(CONF_EXPOSED_ENTITIES, []))
    new_list = [eid for eid in current if eid not in to_remove]
    removed = len(current) - len(new_list)

    overrides: dict[str, str] = dict(entry.options.get(CONF_ENTITY_TYPE_OVERRIDES, {}))
    entity_links: dict[str, dict] = dict(entry.options.get(CONF_ENTITY_LINKS, {}))
    entity_options: dict[str, dict] = dict(entry.options.get(CONF_ENTITY_OPTIONS, {}))
    for eid in to_remove:
        overrides.pop(eid, None)
        entity_links.pop(eid, None)
        # Per-entity device settings are removed together with the entity:
        # left behind, an inverted contact polarity would silently come
        # back the day the same entity is added again through the wizard.
        entity_options.pop(eid, None)

    if removed > 0:
        new_options = dict(entry.options)
        new_options[CONF_EXPOSED_ENTITIES] = new_list
        new_options[CONF_ENTITY_TYPE_OVERRIDES] = overrides
        new_options[CONF_ENTITY_LINKS] = entity_links
        new_options[CONF_ENTITY_OPTIONS] = entity_options
        hass.config_entries.async_update_entry(entry, options=new_options)
        await hass.config_entries.async_reload(entry.entry_id)

    connection.send_result(msg["id"], {"removed": removed, "total": len(new_list)})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "sber_mqtt_bridge/set_override",
        vol.Required("entity_id"): WS_ENTITY_ID,
        vol.Required("category"): vol.In(["auto", *OVERRIDABLE_CATEGORIES]),
    }
)
@websocket_api.async_response
@requires_entry
async def ws_set_type_override(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    entry: Any,
) -> None:
    """Set or clear the Sber category override for an entity.

    Pass ``category`` as ``"auto"`` to remove the override and use
    automatic detection.
    """
    entity_id: str = msg["entity_id"]
    category: str = msg["category"]

    overrides: dict[str, str] = dict(entry.options.get(CONF_ENTITY_TYPE_OVERRIDES, {}))
    if category == "auto":
        overrides.pop(entity_id, None)
    else:
        overrides[entity_id] = category

    new_options = dict(entry.options)
    new_options[CONF_ENTITY_TYPE_OVERRIDES] = overrides
    hass.config_entries.async_update_entry(entry, options=new_options)
    await hass.config_entries.async_reload(entry.entry_id)

    connection.send_result(msg["id"], {"entity_id": entity_id, "category": category})


GATE_OPTION_KEYS: tuple[str, ...] = (
    GATE_OPTION_INVERT_CONTACT,
    GATE_OPTION_IMPULSE_SERVICE,
    GATE_OPTION_TRAVEL_TIME,
    GATE_OPTION_AUTO_CLOSE_TIME,
)
"""Gate option fields ``update_gate_options`` accepts, in payload order."""


@websocket_api.websocket_command(
    {
        vol.Required("type"): "sber_mqtt_bridge/update_entity_options",
        vol.Required("entity_id"): WS_ENTITY_ID,
        vol.Required("options"): ENTITY_OPTIONS_SCHEMA,
    }
)
@websocket_api.async_response
@requires_bridge
async def ws_update_entity_options(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    bridge: Any,
) -> None:
    """Update per-entity device options for a single entity.

    The category-agnostic successor of ``update_gate_options``: the
    payload carries whatever keys the entity's class declares in
    ``ENTITY_OPTION_KEYS`` (a gate's contact polarity and timers, a
    kettle's operation-mode names, …).  Only the keys present are
    changed, so a form can submit one field without resending the rest;
    an empty mapping is refused with ``invalid_format`` rather than
    persisting nothing and republishing everything.

    Value-level checks happen in two places on purpose:
    :data:`~._common.ENTITY_OPTIONS_SCHEMA` guards the *config entry*
    against structurally impossible values, and the entity itself
    (``validate_entity_options``) rejects values that are well-formed but
    wrong for this particular device — a kettle mode it does not offer.
    The latter comes back as ``invalid_option`` with the entity's own
    message, so the panel can show why the save was refused.

    Delegates to :meth:`SberBridge.async_update_entity_options`, which
    persists the options **and** pushes them into the running entity — no
    reload, so the MQTT session survives a checkbox.
    """
    entity_id: str = msg["entity_id"]
    fields: dict[str, Any] = msg["options"]
    if not fields:
        connection.send_error(
            msg["id"],
            websocket_api.const.ERR_INVALID_FORMAT,
            "at least one option is required",
        )
        return

    try:
        merged = await bridge.async_update_entity_options(entity_id, fields)
    except KeyError:
        connection.send_error(msg["id"], "not_found", f"Entity {entity_id} not in bridge")
        return
    except TypeError as err:
        connection.send_error(msg["id"], "not_supported", str(err))
        return
    except ValueError as err:
        connection.send_error(msg["id"], "invalid_option", str(err))
        return
    except HomeAssistantError:
        _LOGGER.exception("Re-publish after entity options update failed")
        connection.send_error(msg["id"], "publish_failed", "Republish after update failed")
        return

    connection.send_result(msg["id"], {"entity_id": entity_id, "options": merged})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "sber_mqtt_bridge/update_gate_options",
        vol.Required("entity_id"): WS_ENTITY_ID,
        vol.Optional(GATE_OPTION_INVERT_CONTACT): bool,
        vol.Optional(GATE_OPTION_IMPULSE_SERVICE): vol.In(IMPULSE_SERVICE_OPTIONS),
        vol.Optional(GATE_OPTION_TRAVEL_TIME): WS_TRAVEL_TIME,
        vol.Optional(GATE_OPTION_AUTO_CLOSE_TIME): WS_AUTO_CLOSE_TIME,
    }
)
@websocket_api.async_response
@requires_bridge
async def ws_update_gate_options(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    bridge: Any,
) -> None:
    """Update impulse-gate options for a single entity (issue #53).

    Only the keys present in the payload are changed, so the panel can
    submit one toggle without resending the rest — but a payload with *no*
    option at all is refused with ``invalid_format``: it used to store an
    empty option dict and reload the whole integration for nothing.

    That "at least one option" rule is checked here rather than in the
    schema on purpose: a voluptuous *dict* schema cannot express it, and
    wrapping the command in ``vol.All`` would break the command-table
    invariant that every handler carries a ``type``-anchored dict schema.
    The error code is the one the schema would have produced, so clients
    cannot tell the difference.

    Kept as the gate-shaped face of the generic
    :func:`ws_update_entity_options`: the panel and every user script
    written against v1.42 call this name, and its ``not_a_gate`` error
    code is part of that contract.  New option sets get the generic
    command instead of a second copy of this one.

    Delegates to :meth:`SberBridge.async_update_gate_options`, which
    persists the options **and** pushes them into the running entity — no
    reload, so the MQTT session survives a checkbox.
    """
    entity_id: str = msg["entity_id"]
    fields = {key: msg[key] for key in GATE_OPTION_KEYS if key in msg}
    if not fields:
        connection.send_error(
            msg["id"],
            websocket_api.const.ERR_INVALID_FORMAT,
            f"at least one of {', '.join(GATE_OPTION_KEYS)} is required",
        )
        return

    try:
        merged = await bridge.async_update_gate_options(entity_id, fields)
    except KeyError:
        connection.send_error(msg["id"], "not_found", f"Entity {entity_id} not in bridge")
        return
    except TypeError:
        connection.send_error(msg["id"], "not_a_gate", f"Entity {entity_id} is not an impulse gate")
        return
    except ValueError:
        # An entity that has options *of its own* (a kettle's mode names)
        # rejects the gate keys with ValueError instead of the TypeError
        # raised for an entity with no options at all.  Both mean the same
        # thing to this command — the target is not an impulse gate — and
        # the panel keys its "hide the gate form" behaviour off that one
        # code, so the v1.42 contract must not depend on which of the two
        # the bridge happened to raise.  The schema above only ever lets
        # gate keys through, so no other ValueError can reach here.
        connection.send_error(msg["id"], "not_a_gate", f"Entity {entity_id} is not an impulse gate")
        return
    except HomeAssistantError:
        _LOGGER.exception("Re-publish after gate options update failed")
        connection.send_error(msg["id"], "publish_failed", "Republish after update failed")
        return

    connection.send_result(msg["id"], {"entity_id": entity_id, "gate_options": merged})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "sber_mqtt_bridge/clear_all",
    }
)
@websocket_api.async_response
@requires_entry
async def ws_clear_all(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    entry: Any,
) -> None:
    """Remove all entities from the exposed list and clear overrides."""
    new_options = dict(entry.options)
    previous_count = len(new_options.get(CONF_EXPOSED_ENTITIES, []))
    new_options[CONF_EXPOSED_ENTITIES] = []
    new_options[CONF_ENTITY_TYPE_OVERRIDES] = {}
    new_options[CONF_ENTITY_LINKS] = {}
    new_options[CONF_ENTITY_OPTIONS] = {}
    hass.config_entries.async_update_entry(entry, options=new_options)
    await hass.config_entries.async_reload(entry.entry_id)

    connection.send_result(msg["id"], {"removed": previous_count})
