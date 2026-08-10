"""Bridge-settings WebSocket commands (get / update)."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from ..const import (
    CONF_ACK_AUDIT_DELAY,
    CONF_CONFIG_MAX_WAIT,
    CONF_CONFIG_SETTLE_DELAY,
    CONF_CONFIRM_DELAY,
    CONF_DEBOUNCE_DELAY,
    CONF_HA_SERIAL_NUMBER,
    CONF_HUB_AUTO_PARENT,
    CONF_MAX_MQTT_PAYLOAD,
    CONF_MESSAGE_LOG_SIZE,
    CONF_RECONNECT_MAX,
    CONF_RECONNECT_MIN,
    CONF_SBER_VERIFY_SSL,
    CONF_SILENT_REJECTION_ALERTS,
    SETTINGS_DEFAULTS,
)
from ._common import (  # noqa: F401 — get_config_entry re-exported for test patching
    get_bridge,
    get_config_entry,
    requires_entry,
)

_LOGGER = logging.getLogger(__name__)


def _strict_bool(value: Any) -> bool:
    """Validate that ``value`` is a real boolean (no string/int coercion).

    Args:
        value: Raw value from the WS payload.

    Returns:
        The boolean value unchanged.

    Raises:
        vol.Invalid: If the value is not a ``bool``.
    """
    if not isinstance(value, bool):
        raise vol.Invalid("expected a boolean")
    return value


def _strict_number(value: Any) -> float:
    """Validate that ``value`` is a real number (bool/str rejected).

    Args:
        value: Raw value from the WS payload.

    Returns:
        The value coerced to ``float``.

    Raises:
        vol.Invalid: If the value is not an ``int`` or ``float``.
    """
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise vol.Invalid("expected a number")
    return float(value)


def _strict_int(value: Any) -> int:
    """Validate that ``value`` is a real integer (bool/str/float rejected).

    Args:
        value: Raw value from the WS payload.

    Returns:
        The integer value unchanged.

    Raises:
        vol.Invalid: If the value is not an ``int``.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise vol.Invalid("expected an integer")
    return value


SETTINGS_VALUES_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_RECONNECT_MIN): vol.All(_strict_int, vol.Range(min=1, max=3600)),
        vol.Optional(CONF_RECONNECT_MAX): vol.All(_strict_int, vol.Range(min=1, max=86400)),
        vol.Optional(CONF_DEBOUNCE_DELAY): vol.All(_strict_number, vol.Range(min=0, max=60)),
        vol.Optional(CONF_MESSAGE_LOG_SIZE): vol.All(_strict_int, vol.Range(min=1, max=10_000)),
        vol.Optional(CONF_MAX_MQTT_PAYLOAD): vol.All(_strict_int, vol.Range(min=1024, max=10_000_000)),
        vol.Optional(CONF_SBER_VERIFY_SSL): _strict_bool,
        vol.Optional(CONF_HUB_AUTO_PARENT): _strict_bool,
        vol.Optional(CONF_CONFIRM_DELAY): vol.All(_strict_number, vol.Range(min=0, max=60)),
        vol.Optional(CONF_ACK_AUDIT_DELAY): vol.All(_strict_number, vol.Range(min=1, max=3600)),
        # Settle window may legitimately be 0 (publish as soon as quiet is
        # meaningless — fire immediately); the cap must stay above it.
        vol.Optional(CONF_CONFIG_SETTLE_DELAY): vol.All(_strict_number, vol.Range(min=0, max=300)),
        vol.Optional(CONF_CONFIG_MAX_WAIT): vol.All(_strict_number, vol.Range(min=1, max=900)),
        vol.Optional(CONF_HA_SERIAL_NUMBER): _strict_bool,
        vol.Optional(CONF_SILENT_REJECTION_ALERTS): _strict_bool,
    },
    extra=vol.REMOVE_EXTRA,
)
"""Per-key value schema for ``update_settings``.

Types and ranges guard the bridge against poisoned ``entry.options``:
non-numeric strings would crash ``_load_settings_from_options`` on every
subsequent ``async_setup_entry`` (entry never loads again), while
out-of-range numbers cause silent message drops
(``max_mqtt_payload_size=0``), tight reconnect loops
(``reconnect_interval_min=0``) or ``deque(maxlen=-1)`` crashes
(``message_log_size=-1``).  Unknown keys are dropped, matching the
historical key filter.  Every key from :data:`SETTINGS_DEFAULTS` must
have an entry here — enforced by an import-time assertion below.
"""

_missing = set(SETTINGS_DEFAULTS) - {str(key) for key in SETTINGS_VALUES_SCHEMA.schema}
if _missing:  # pragma: no cover — import-time self-check
    msg = f"SETTINGS_VALUES_SCHEMA is missing validators for: {sorted(_missing)}"
    raise RuntimeError(msg)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "sber_mqtt_bridge/get_settings",
    }
)
@callback
@requires_entry
def ws_get_settings(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    entry: Any,
) -> None:
    """Return current bridge operational settings with their defaults."""
    settings: dict[str, Any] = {}
    for key, default in SETTINGS_DEFAULTS.items():
        if key == CONF_SBER_VERIFY_SSL:
            settings[key] = entry.options.get(key, entry.data.get(key, default))
        else:
            settings[key] = entry.options.get(key, default)

    connection.send_result(msg["id"], {"settings": settings, "defaults": dict(SETTINGS_DEFAULTS)})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "sber_mqtt_bridge/update_settings",
        vol.Required("settings"): dict,
    }
)
@websocket_api.async_response
@requires_entry
async def ws_update_settings(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    entry: Any,
) -> None:
    """Save bridge operational settings to config entry options.

    Values are validated against :data:`SETTINGS_VALUES_SCHEMA` *before*
    anything is persisted — an invalid type or out-of-range value
    rejects the whole request atomically (``invalid_settings`` error)
    and leaves ``entry.options`` untouched.
    """
    try:
        validated: dict[str, Any] = SETTINGS_VALUES_SCHEMA(msg["settings"])
    except vol.Invalid as err:
        connection.send_error(msg["id"], "invalid_settings", f"Invalid settings: {err}")
        return

    new_options = dict(entry.options)
    new_options.update(validated)

    hass.config_entries.async_update_entry(entry, options=new_options)

    bridge = get_bridge(hass)
    if bridge is not None:
        bridge.apply_settings(new_options)

    connection.send_result(msg["id"], {"success": True})
