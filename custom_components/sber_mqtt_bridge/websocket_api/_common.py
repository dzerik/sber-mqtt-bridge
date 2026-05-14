"""Shared helpers for the Sber MQTT Bridge WebSocket API package."""

from __future__ import annotations

import inspect
import sys
from collections.abc import Callable
from functools import wraps
from typing import TYPE_CHECKING, Any

import voluptuous as vol  # type: ignore[import-untyped]
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv

from ..const import CONF_MAX_MQTT_PAYLOAD, DOMAIN, SETTINGS_DEFAULTS
from ..sber_entity_map import CATEGORY_DOMAIN_MAP

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

    from ..sber_bridge import SberBridge

WS_ENTITY_ID = vol.All(cv.string, cv.entity_id)
"""Validator for a single entity_id field in a WS schema.

Use as ``vol.Required("entity_id"): WS_ENTITY_ID`` so HA rejects
malformed strings before they reach the handler and risk poisoning
``entry.options``.
"""

WS_ENTITY_IDS = vol.All(cv.ensure_list, [cv.entity_id])
"""Validator for an entity_ids list field — every element must look
like a real entity_id (``domain.object_id``)."""

OVERRIDABLE_CATEGORIES = sorted(CATEGORY_DOMAIN_MAP.keys())
"""Sorted list of valid Sber category strings, used to validate
``category`` fields in WS schemas."""

_MAX_PAYLOAD = SETTINGS_DEFAULTS[CONF_MAX_MQTT_PAYLOAD]
"""Frozen at import; runtime option changes require HA restart
to update WS schema caps."""


def _payload_byte_cap(value: str) -> str:
    """Reject WS payloads whose UTF-8 byte length exceeds the MQTT cap.

    ``vol.Length`` would count Unicode code points instead of bytes,
    which diverges from the inbound MQTT guard in
    :meth:`SberBridge._handle_mqtt_message` (it sees raw ``bytes``).
    This validator preserves byte-level parity between both paths.
    """
    if len(value.encode("utf-8")) > _MAX_PAYLOAD:
        raise vol.Invalid(f"payload exceeds {_MAX_PAYLOAD} bytes")
    return value


WS_PAYLOAD = vol.All(cv.string, _payload_byte_cap)
"""Validator for a Sber-bound JSON payload in DevTools WS commands.

Enforces the same byte-length cap as the inbound MQTT guard so a
payload accepted by the schema cannot be rejected at publish time."""


def get_config_entry(hass: HomeAssistant) -> ConfigEntry | None:
    """Return the first loaded config entry for this integration (or None)."""
    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    return entries[0] if entries else None


def get_bridge(hass: HomeAssistant) -> SberBridge | None:
    """Return the active ``SberBridge`` from ``ConfigEntry.runtime_data``.

    Returns:
        The bridge instance, or ``None`` if not available.
    """
    entry = get_config_entry(hass)
    if entry is None or not hasattr(entry, "runtime_data") or entry.runtime_data is None:
        return None
    return entry.runtime_data.bridge


def requires_bridge(
    handler: Callable[..., Any],
) -> Callable[[HomeAssistant, websocket_api.ActiveConnection, dict[str, Any]], Any]:
    """Decorate a WS handler that needs the active :class:`SberBridge`.

    Replaces the ``bridge = get_bridge(hass); if bridge is None: send_error``
    boilerplate.  The decorated function gains a 4th positional argument
    ``bridge`` and only runs when the bridge is available.

    Works for both ``@callback`` (sync) and ``@websocket_api.async_response``
    (async) handlers — the wrapper preserves the calling convention.

    The lookup is performed at call time through the handler's module
    namespace so that test-level patches on ``module.get_bridge`` are
    respected (late binding, not closure over the import at decoration
    time).

    Usage::

        @websocket_api.websocket_command({...})
        @websocket_api.async_response
        @requires_bridge
        async def ws_foo(hass, connection, msg, bridge):
            ...
    """
    # Capture a reference to the handler's module for late-binding lookup.
    _module_name = handler.__module__

    if inspect.iscoroutinefunction(handler):

        @wraps(handler)
        async def async_wrapped(
            hass: HomeAssistant,
            connection: websocket_api.ActiveConnection,
            msg: dict[str, Any],
        ) -> None:
            _mod = sys.modules.get(_module_name)
            _lookup = getattr(_mod, "get_bridge", None) if _mod is not None else None
            _bridge_fn = _lookup if _lookup is not None else get_bridge
            bridge = _bridge_fn(hass)
            if bridge is None:
                connection.send_error(msg["id"], "bridge_not_found", "Bridge not available")
                return
            await handler(hass, connection, msg, bridge)

        return async_wrapped  # type: ignore[return-value]

    @wraps(handler)
    def sync_wrapped(
        hass: HomeAssistant,
        connection: websocket_api.ActiveConnection,
        msg: dict[str, Any],
    ) -> None:
        _mod = sys.modules.get(_module_name)
        _lookup = getattr(_mod, "get_bridge", None) if _mod is not None else None
        _bridge_fn = _lookup if _lookup is not None else get_bridge
        bridge = _bridge_fn(hass)
        if bridge is None:
            connection.send_error(msg["id"], "bridge_not_found", "Bridge not available")
            return
        handler(hass, connection, msg, bridge)

    return sync_wrapped  # type: ignore[return-value]


def requires_entry(
    handler: Callable[..., Any],
) -> Callable[[HomeAssistant, websocket_api.ActiveConnection, dict[str, Any]], Any]:
    """Decorate a WS handler that needs the active integration :class:`ConfigEntry`.

    Replaces the ``entry = get_config_entry(hass); if entry is None: send_error``
    boilerplate.  The decorated function gains a 4th positional argument
    ``entry`` and only runs when the config entry is loaded.

    Works for both ``@callback`` (sync) and ``@websocket_api.async_response``
    (async) handlers.

    The lookup is performed at call time through the handler's module
    namespace so that test-level patches on ``module.get_config_entry`` are
    respected (late binding, not closure over the import at decoration time).

    Usage::

        @websocket_api.websocket_command({...})
        @websocket_api.async_response
        @requires_entry
        async def ws_foo(hass, connection, msg, entry):
            ...
    """
    _module_name = handler.__module__

    if inspect.iscoroutinefunction(handler):

        @wraps(handler)
        async def async_wrapped(
            hass: HomeAssistant,
            connection: websocket_api.ActiveConnection,
            msg: dict[str, Any],
        ) -> None:
            _mod = sys.modules.get(_module_name)
            _lookup = getattr(_mod, "get_config_entry", None) if _mod is not None else None
            _entry_fn = _lookup if _lookup is not None else get_config_entry
            entry = _entry_fn(hass)
            if entry is None:
                connection.send_error(msg["id"], "entry_not_found", "Config entry not found")
                return
            await handler(hass, connection, msg, entry)

        return async_wrapped  # type: ignore[return-value]

    @wraps(handler)
    def sync_wrapped(
        hass: HomeAssistant,
        connection: websocket_api.ActiveConnection,
        msg: dict[str, Any],
    ) -> None:
        _mod = sys.modules.get(_module_name)
        _lookup = getattr(_mod, "get_config_entry", None) if _mod is not None else None
        _entry_fn = _lookup if _lookup is not None else get_config_entry
        entry = _entry_fn(hass)
        if entry is None:
            connection.send_error(msg["id"], "entry_not_found", "Config entry not found")
            return
        handler(hass, connection, msg, entry)

    return sync_wrapped  # type: ignore[return-value]
