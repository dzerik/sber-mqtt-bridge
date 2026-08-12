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
from ..devices.gate import MAX_TRAVEL_TIME_SECONDS
from ..sber_entity_map import OVERRIDABLE_CATEGORIES as OVERRIDABLE_CATEGORIES

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

# OVERRIDABLE_CATEGORIES is re-exported (see import above) so WS modules
# keep their historical ``from ._common import OVERRIDABLE_CATEGORIES``
# path while the single definition lives in sber_entity_map (derived
# from CATEGORY_DOMAIN_MAP — no drift possible).

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


def _reject_bool(value: Any) -> Any:
    """Refuse a ``bool`` before any numeric coercion sees it.

    ``bool`` is a subclass of ``int`` in Python, so ``vol.Coerce(float)``
    happily turns ``True`` into ``1.0`` and ``False`` into ``0.0``.  For
    ``travel_time`` that silently means "one second of travel", which is
    exactly the value :meth:`ImpulseGateEntity._apply_travel_time`
    refuses — but the schema runs first, so the entity never gets to see
    the ``bool`` and the guard is bypassed.

    ``vol.NotIn([True, False])`` cannot be used instead: it compares by
    equality, so it would also reject the perfectly valid ``0`` and ``1``.

    Args:
        value: Raw value from the WS / import payload.

    Returns:
        ``value`` unchanged when it is not a ``bool``.

    Raises:
        vol.Invalid: When ``value`` is ``True`` or ``False``.
    """
    if isinstance(value, bool):
        raise vol.Invalid("expected a number, got a boolean")
    return value


WS_TRAVEL_TIME = vol.All(
    _reject_bool,
    vol.Coerce(float),
    vol.Range(min=0, max=MAX_TRAVEL_TIME_SECONDS),
)
"""Validator for the impulse gate's ``travel_time`` option (issue #53).

Shared by ``update_gate_options`` and the ``import`` payload schema so
both entry points enforce the same bounds *and* the same ``bool``
rejection — a value that survives one path but not the other would make
an exported config fail to import back."""


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


def _make_requires(
    lookup_name: str,
    error_code: str,
    error_message: str,
) -> Callable[
    [Callable[..., Any]],
    Callable[[HomeAssistant, websocket_api.ActiveConnection, dict[str, Any]], Any],
]:
    """Build a dependency-injecting decorator for WS handlers.

    Shared implementation behind :func:`requires_bridge` /
    :func:`requires_entry` — resolves a dependency (bridge or config
    entry) at call time, sends ``error_code`` when it is missing, and
    otherwise calls the handler with the dependency as 4th positional
    argument.  Works for both ``@callback`` (sync) and
    ``@websocket_api.async_response`` (async) handlers.

    The lookup is performed at call time through the handler's module
    namespace so that test-level patches on ``module.get_bridge`` /
    ``module.get_config_entry`` are respected (late binding, not closure
    over the import at decoration time); modules that don't re-export
    the lookup fall back to the canonical function in this module.

    Args:
        lookup_name: Name of the lookup function (``"get_bridge"`` or
            ``"get_config_entry"``).
        error_code: WS error code sent when the dependency is missing.
        error_message: Human-readable error message for that code.

    Returns:
        A decorator with the same contract as ``requires_bridge``.
    """

    def decorator(
        handler: Callable[..., Any],
    ) -> Callable[[HomeAssistant, websocket_api.ActiveConnection, dict[str, Any]], Any]:
        _module_name = handler.__module__

        def _resolve(hass: HomeAssistant) -> Any:
            _mod = sys.modules.get(_module_name)
            _lookup = getattr(_mod, lookup_name, None) if _mod is not None else None
            _fn = _lookup if _lookup is not None else globals()[lookup_name]
            return _fn(hass)

        if inspect.iscoroutinefunction(handler):

            @wraps(handler)
            async def async_wrapped(
                hass: HomeAssistant,
                connection: websocket_api.ActiveConnection,
                msg: dict[str, Any],
            ) -> None:
                dependency = _resolve(hass)
                if dependency is None:
                    connection.send_error(msg["id"], error_code, error_message)
                    return
                await handler(hass, connection, msg, dependency)

            return async_wrapped  # type: ignore[return-value]

        @wraps(handler)
        def sync_wrapped(
            hass: HomeAssistant,
            connection: websocket_api.ActiveConnection,
            msg: dict[str, Any],
        ) -> None:
            dependency = _resolve(hass)
            if dependency is None:
                connection.send_error(msg["id"], error_code, error_message)
                return
            handler(hass, connection, msg, dependency)

        return sync_wrapped  # type: ignore[return-value]

    return decorator


def requires_bridge(
    handler: Callable[..., Any],
) -> Callable[[HomeAssistant, websocket_api.ActiveConnection, dict[str, Any]], Any]:
    """Decorate a WS handler that needs the active :class:`SberBridge`.

    Replaces the ``bridge = get_bridge(hass); if bridge is None: send_error``
    boilerplate.  The decorated function gains a 4th positional argument
    ``bridge`` and only runs when the bridge is available.

    Usage::

        @websocket_api.websocket_command({...})
        @websocket_api.async_response
        @requires_bridge
        async def ws_foo(hass, connection, msg, bridge):
            ...
    """
    return _make_requires("get_bridge", "bridge_not_found", "Bridge not available")(handler)


def requires_entry(
    handler: Callable[..., Any],
) -> Callable[[HomeAssistant, websocket_api.ActiveConnection, dict[str, Any]], Any]:
    """Decorate a WS handler that needs the active integration :class:`ConfigEntry`.

    Replaces the ``entry = get_config_entry(hass); if entry is None: send_error``
    boilerplate.  The decorated function gains a 4th positional argument
    ``entry`` and only runs when the config entry is loaded.

    Usage::

        @websocket_api.websocket_command({...})
        @websocket_api.async_response
        @requires_entry
        async def ws_foo(hass, connection, msg, entry):
            ...
    """
    return _make_requires("get_config_entry", "entry_not_found", "Config entry not found")(handler)
