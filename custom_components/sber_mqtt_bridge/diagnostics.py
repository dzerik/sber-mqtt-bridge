"""Diagnostics support for Sber MQTT Bridge."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import SberBridgeConfigEntry
from .const import CONF_SBER_LOGIN, CONF_SBER_PASSWORD

if TYPE_CHECKING:
    from .sber_bridge import SberBridge

TO_REDACT = {CONF_SBER_PASSWORD, CONF_SBER_LOGIN}
"""Set of config keys whose values should be redacted in diagnostics output.

The Sber login doubles as the MQTT username **and** the root MQTT topic
segment (``sberdevices/v1/<login>/...``) — diagnostics files are routinely
attached to public GitHub issues, so it must not leak in clear text.
"""


DEVTOOLS_MESSAGES = 100
"""Most recent MQTT messages included in the diagnostics file."""

DEVTOOLS_RECORDS = 50
"""Most recent diffs, command confirmations and validation issues included."""

DEVTOOLS_TRACES = 30
"""Most recent correlation traces included (each carries several events)."""

PAYLOAD_MAX_CHARS = 2000
"""Payload strings longer than this are cut, keeping the file attachable."""

REDACTED = "**REDACTED**"


def _truncate(value: Any) -> Any:
    """Cut an over-long payload string, marking the cut."""
    if isinstance(value, str) and len(value) > PAYLOAD_MAX_CHARS:
        return value[:PAYLOAD_MAX_CHARS] + "…[truncated]"
    return value


def _scrub(value: Any, secrets: list[str]) -> Any:
    """Replace every occurrence of ``secrets`` in any string of ``value``.

    Key-based redaction is not enough here: the login is a segment of every
    MQTT topic (``sberdevices/v1/<login>/…``) and may appear in error texts.
    """
    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, REDACTED)
        return value
    if isinstance(value, dict):
        return {_scrub(k, secrets): _scrub(v, secrets) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_scrub(v, secrets) for v in value]
    return value


def _build_devtools_diagnostics(bridge: SberBridge) -> dict[str, Any]:
    """Recent DevTools data, so a bug report does not need tab-by-tab screenshots.

    Args:
        bridge: Running bridge.

    Returns:
        The latest messages, traces, state diffs, command confirmations and
        validation issues, bounded in count and payload size.
    """
    messages = [{**m, "payload": _truncate(m.get("payload"))} for m in bridge.message_log[-DEVTOOLS_MESSAGES:]]
    traces = [
        {**t, "events": [{**e, "payload": _truncate(json.dumps(e.get("payload"), default=str))} for e in t["events"]]}
        for t in bridge.trace_collector.snapshot()[-DEVTOOLS_TRACES:]
    ]
    validation = bridge.validation_collector.snapshot()
    return {
        "message_log": messages,
        "traces": traces,
        "state_diffs": bridge.diff_collector.snapshot()[-DEVTOOLS_RECORDS:],
        "command_confirmations": bridge.command_confirm.snapshot()[-DEVTOOLS_RECORDS:],
        "validation": {
            "by_entity": validation.get("by_entity", {}),
            "recent": list(validation.get("recent", []))[-DEVTOOLS_RECORDS:],
        },
    }


def _build_entity_diagnostics(bridge: SberBridge) -> list[dict[str, Any]]:
    """Build per-entity diagnostic info.

    Args:
        bridge: SberBridge instance with loaded entities.

    Returns:
        List of dicts with entity diagnostic details.
    """
    missing_links = bridge.entities_missing_required_links
    result: list[dict[str, Any]] = []
    for entity_id, entity in bridge.entities.items():
        entry: dict[str, Any] = {
            "entity_id": entity_id,
            "sber_category": entity.category,
            "sber_features": entity.get_final_features_list(),
            "is_filled_by_state": entity.is_filled_by_state,
            "has_linked_device": entity.linked_device is not None,
            # Non-empty means the device is composite and mis-configured:
            # it publishes a fabricated state (see the matching repair).
            "missing_required_links": missing_links.get(entity_id, []),
        }

        # Current state summary
        if entity.is_filled_by_state:
            entry["current_state"] = {
                "state": entity.state,
                "is_online": entity.is_online,
            }
        else:
            entry["current_state"] = None

        result.append(entry)
    return result


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: SberBridgeConfigEntry) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    bridge = entry.runtime_data.bridge

    report = {
        "entry_data": async_redact_data(dict(entry.data), TO_REDACT),
        "options": dict(entry.options),
        "bridge": {
            "connected": bridge.is_connected,
            "phase": bridge.connection_phase,
            "auth_failed": bridge.auth_failed,
            "entities_loaded": bridge.entities_count,
            "enabled_entity_ids": bridge.enabled_entity_ids,
            "redefinitions": bridge.redefinitions,
            "unacknowledged_entities": bridge.unacknowledged_entities,
            "entities_missing_required_links": bridge.entities_missing_required_links,
            "stats": bridge.stats,
        },
        # Its own block, not just a key buried in ``options``: "known to
        # Sber: 0" on a working bridge (issue #57) is answered by comparing
        # the live set, the persisted one and whether a config publish has
        # succeeded this session — three facts that were nowhere in the
        # dump, so the report could only be chased by guesswork.
        "cloud_device_registry": bridge.cloud_device_registry_state,
        "entities": _build_entity_diagnostics(bridge),
        "devtools": _build_devtools_diagnostics(bridge),
    }
    # Last pass over the whole report: short values could collide with
    # ordinary words, so only credentials of a meaningful length are scrubbed.
    secrets = [
        str(entry.data.get(k)) for k in (CONF_SBER_LOGIN, CONF_SBER_PASSWORD) if len(str(entry.data.get(k) or "")) >= 4
    ]
    scrubbed: dict[str, Any] = _scrub(report, secrets)
    return scrubbed
