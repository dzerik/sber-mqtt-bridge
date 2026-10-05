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
    CONF_SBER_BROKER,
    CONF_SBER_PORT,
    CONF_SBER_TRUSTED_CERTIFICATE,
    CONF_SBER_VERIFY_SSL,
    CONF_SILENT_REJECTION_ALERTS,
    SETTINGS_DEFAULTS,
)
from ..ssl_utils import entry_trusted_certificate, entry_verify_ssl, inspect_server_certificate
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
    # ``not isinstance(int)`` comes first so the surviving branch narrows to
    # ``int``; the ``bool`` test then rejects the one int subclass we refuse.
    if not isinstance(value, int) or isinstance(value, bool):
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


def _numeric_limits(schema: vol.Schema) -> dict[str, dict[str, Any]]:
    """Collect the ``vol.Range`` bounds of every numeric setting in ``schema``.

    Args:
        schema: A settings value schema built from ``vol.All(..., vol.Range)``.

    Returns:
        ``{key: {"min": ..., "max": ...}}`` for each key that has a range.
    """
    limits: dict[str, dict[str, Any]] = {}
    for key, validator in schema.schema.items():
        for part in getattr(validator, "validators", ()):
            if isinstance(part, vol.Range):
                limits[str(key)] = {"min": part.min, "max": part.max}
    return limits


SETTINGS_LIMITS: dict[str, dict[str, Any]] = _numeric_limits(SETTINGS_VALUES_SCHEMA)
"""Numeric bounds :data:`SETTINGS_VALUES_SCHEMA` enforces, sent to the panel.

The settings form takes its input bounds from here instead of keeping its
own copy, which had drifted to narrower ranges than the backend accepts."""

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
    """Return current bridge operational settings with defaults and limits."""
    settings: dict[str, Any] = {}
    for key, default in SETTINGS_DEFAULTS.items():
        if key == CONF_SBER_VERIFY_SSL:
            settings[key] = entry_verify_ssl(entry.data, entry.options)
        else:
            settings[key] = entry.options.get(key, default)

    connection.send_result(
        msg["id"],
        {"settings": settings, "defaults": dict(SETTINGS_DEFAULTS), "limits": SETTINGS_LIMITS},
    )


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


@websocket_api.websocket_command(
    {vol.Required("type"): "sber_mqtt_bridge/inspect_certificate"}
)
@websocket_api.async_response
@requires_entry
async def ws_inspect_certificate(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    entry: Any,
) -> None:
    """Inspect the current broker certificate without trusting it."""
    try:
        certificate = await hass.async_add_executor_job(
            inspect_server_certificate,
            entry.data[CONF_SBER_BROKER],
            entry.data[CONF_SBER_PORT],
        )
    except (OSError, TimeoutError, ValueError) as err:
        connection.send_error(msg["id"], "certificate_unavailable", str(err))
        return
    trusted = entry_trusted_certificate(entry.data, entry.options)
    result = certificate.as_dict()
    result["trusted"] = bool(trusted and trusted == certificate.pem)
    connection.send_result(msg["id"], {"certificate": result})


@websocket_api.websocket_command(
    {vol.Required("type"): "sber_mqtt_bridge/download_certificate"}
)
@websocket_api.async_response
@requires_entry
async def ws_download_certificate(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    entry: Any,
) -> None:
    """Return the current broker certificate PEM for a deliberate download."""
    try:
        certificate = await hass.async_add_executor_job(
            inspect_server_certificate,
            entry.data[CONF_SBER_BROKER],
            entry.data[CONF_SBER_PORT],
        )
    except (OSError, TimeoutError, ValueError) as err:
        connection.send_error(msg["id"], "certificate_unavailable", str(err))
        return
    connection.send_result(msg["id"], {"certificate": certificate.as_dict(include_pem=True)})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "sber_mqtt_bridge/trust_certificate",
        # Optional keeps the command schema valid for HA's authorization
        # guard: non-admin users must receive ``unauthorized`` before any
        # certificate-specific validation is attempted.
        vol.Optional("fingerprint", default=""): str,
    }
)
@websocket_api.async_response
@requires_entry
async def ws_trust_certificate(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    entry: Any,
) -> None:
    """Pin the freshly inspected certificate after fingerprint confirmation."""
    try:
        certificate = await hass.async_add_executor_job(
            inspect_server_certificate,
            entry.data[CONF_SBER_BROKER],
            entry.data[CONF_SBER_PORT],
        )
    except (OSError, TimeoutError, ValueError) as err:
        connection.send_error(msg["id"], "certificate_unavailable", str(err))
        return
    if msg["fingerprint"].replace(" ", "").upper() != certificate.fingerprint:
        connection.send_error(
            msg["id"],
            "certificate_changed",
            "The broker certificate changed since it was inspected",
        )
        return
    if not certificate.valid_now or not certificate.hostname_matches:
        connection.send_error(
            msg["id"],
            "certificate_invalid",
            "The broker certificate is expired or does not match the broker hostname",
        )
        return
    new_options = dict(entry.options)
    new_options[CONF_SBER_TRUSTED_CERTIFICATE] = certificate.pem
    # Pinning is useful only while certificate verification is enabled.  A
    # deliberate trust action therefore restores the secure mode if the user
    # had previously disabled verification as an emergency workaround.
    new_options[CONF_SBER_VERIFY_SSL] = True
    hass.config_entries.async_update_entry(entry, options=new_options)
    bridge = get_bridge(hass)
    if bridge is not None:
        bridge.apply_settings(new_options)
    connection.send_result(msg["id"], {"success": True, "certificate": certificate.as_dict()})


@websocket_api.websocket_command(
    {vol.Required("type"): "sber_mqtt_bridge/remove_trusted_certificate"}
)
@websocket_api.async_response
@requires_entry
async def ws_remove_trusted_certificate(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    entry: Any,
) -> None:
    """Remove the pinned certificate and return to system CA verification."""
    new_options = dict(entry.options)
    new_options.pop(CONF_SBER_TRUSTED_CERTIFICATE, None)
    hass.config_entries.async_update_entry(entry, options=new_options)
    bridge = get_bridge(hass)
    if bridge is not None:
        bridge.apply_settings(new_options)
    connection.send_result(msg["id"], {"success": True})
