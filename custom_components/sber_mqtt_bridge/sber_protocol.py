"""Sber Smart Home MQTT protocol serialization.

Handles conversion of internal device entities to Sber JSON formats
for MQTT communication (device config, state lists, command parsing).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from .devices.base_entity import BaseEntity
from .sber_models import validate_config_payload, validate_status_payload

_LOGGER = logging.getLogger(__name__)

VERSION = "1.5.3"
"""Protocol version string included in the hub device descriptor."""


def build_hub_device(version: str = VERSION) -> dict:
    """Build the root hub device descriptor for Sber."""
    return {
        "id": "root",
        "name": "Home Assistant Bridge",
        "hw_version": version,
        "sw_version": version,
        "model": {
            "id": "ID_root_hub",
            "manufacturer": "HA-SberBridge",
            "model": "VHub",
            "description": "HA MQTT Sber Bridge HUB",
            "category": "hub",
            "features": ["online"],
        },
    }


def build_devices_list_json(
    entities: dict[str, BaseEntity],
    enabled_entity_ids: list[str],
    redefinitions: dict[str, dict] | None = None,
) -> str:
    """Build Sber device config JSON for MQTT publish.

    The resulting payload is validated against :class:`SberConfigPayload`
    (pydantic) before serialisation.  Validation failures are logged as
    warnings but do **not** prevent publishing.

    Args:
        entities: Dict of entity_id -> BaseEntity instances.
        enabled_entity_ids: List of entity_ids to include.
        redefinitions: Optional dict of entity_id -> {home, room, name} overrides.

    Returns:
        JSON string with the Sber device list payload.
    """
    device_list: dict[str, Any] = {"devices": [build_hub_device()]}

    for entity_id in enabled_entity_ids:
        entity = entities.get(entity_id)
        if entity is None or not entity.is_filled_by_state:
            continue

        try:
            device_data = entity.to_sber_state()
        except Exception:
            _LOGGER.exception("Error building Sber state for %s", entity_id)
            continue

        if device_data is None:
            continue

        if redefinitions and entity_id in redefinitions:
            redef = redefinitions[entity_id]
            if redef.get("home"):
                device_data["home"] = redef["home"]
            if redef.get("room"):
                device_data["room"] = redef["room"]
            if redef.get("name"):
                device_data["name"] = redef["name"]

        filtered = {k: v for k, v in device_data.items() if v is not None}
        device_list["devices"].append(filtered)

    validate_config_payload(device_list)

    return json.dumps(device_list)


def build_states_list_json(
    entities: dict[str, BaseEntity],
    entity_ids: list[str] | None = None,
    enabled_entity_ids: list[str] | None = None,
) -> str:
    """Build Sber state list JSON for MQTT publish.

    The resulting payload is validated against :class:`SberStatusPayload`
    (pydantic) before serialisation.  Validation failures are logged as
    warnings but do **not** prevent publishing.

    Args:
        entities: Dict of entity_id -> BaseEntity instances.
        entity_ids: Specific entity_ids to include (None = all enabled).
        enabled_entity_ids: List of enabled entity_ids (used when entity_ids is None).

    Returns:
        JSON string with the Sber states payload.
    """
    states: dict[str, Any] = {"devices": {}}

    if entity_ids is None or len(entity_ids) == 0:
        entity_ids = enabled_entity_ids or list(entities.keys())

    for entity_id in entity_ids:
        entity = entities.get(entity_id)
        if entity is None:
            continue

        if enabled_entity_ids and entity_id not in enabled_entity_ids:
            continue

        try:
            entity_state = entity.to_sber_current_state()
            if entity_state is not None:
                states["devices"] |= entity_state
        except Exception:
            _LOGGER.exception("Error building Sber current state for %s", entity_id)

    if not states["devices"]:
        # Fallback: report hub as online but with no device states.
        # This happens when no entities have state yet (e.g. all unavailable).
        has_entities = bool(entities)
        states["devices"] = {
            "root": {"states": [{"key": "online", "value": {"type": "BOOL", "bool_value": has_entities}}]}
        }

    validate_status_payload(states)

    return json.dumps(states)


def parse_sber_command(payload: bytes | str) -> dict[str, Any]:
    """Parse Sber MQTT command payload.

    Args:
        payload: Raw MQTT payload (bytes or str).

    Returns:
        Parsed dict with 'devices' key, or empty dict on parse error.
    """
    try:
        return json.loads(payload)
    except (json.JSONDecodeError, TypeError):
        _LOGGER.warning(
            "Failed to parse Sber command payload: %s", payload[:200] if isinstance(payload, (str, bytes)) else payload
        )
        return {"devices": {}}


def parse_sber_status_request(payload: bytes | str) -> list[str]:
    """Parse Sber status request payload.

    Returns list of requested entity_ids (empty = all).
    """
    try:
        data = json.loads(payload).get("devices", [])
    except (json.JSONDecodeError, AttributeError):
        return []
    else:
        if len(data) == 1 and data[0] == "":
            return []
        return data
