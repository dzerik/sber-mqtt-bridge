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

VERSION = "1.23.0"
"""Protocol version string included in the hub device descriptor."""


def build_hub_device(version: str = VERSION, home: str = "", room: str = "") -> dict:
    """Build the root hub device descriptor for Sber.

    Args:
        version: Protocol version string.
        home: Home name for the hub device.
        room: Room name for the hub device.
    """
    return {
        "id": "root",
        "name": "Home Assistant Bridge",
        "default_name": "HA-SberBridge Hub",
        "home": home,
        "room": room,
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
    default_home: str = "",
    default_room: str = "",
) -> str:
    """Build Sber device config JSON for MQTT publish.

    The resulting payload is validated against :class:`SberConfigPayload`
    (pydantic) before serialisation.  Validation failures are logged as
    warnings but do **not** prevent publishing.

    Args:
        entities: Dict of entity_id -> BaseEntity instances.
        enabled_entity_ids: List of entity_ids to include.
        redefinitions: Optional dict of entity_id -> {home, room, name} overrides.
        default_home: Fallback home name (from HA location_name) when not
            set via redefinitions.  Sber cloud may reject devices without it.
        default_room: Fallback room name when device has no area assigned.
            Sber cloud may reject devices without a room.

    Returns:
        JSON string with the Sber device list payload.
    """
    device_list: dict[str, Any] = {"devices": [build_hub_device(home=default_home, room=default_room)]}

    for entity_id in enabled_entity_ids:
        entity = entities.get(entity_id)
        if entity is None or not entity.is_filled_by_state:
            continue

        try:
            device_data = entity.to_sber_state()
        except (TypeError, ValueError, KeyError, AttributeError):
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

        if "home" not in device_data and default_home:
            device_data["home"] = default_home

        if not device_data.get("room") and default_room:
            device_data["room"] = default_room

        filtered = {k: v for k, v in device_data.items() if v is not None}
        device_list["devices"].append(filtered)

    validate_config_payload(device_list)

    return json.dumps(device_list)


def build_states_list_json(
    entities: dict[str, BaseEntity],
    entity_ids: list[str] | None = None,
    enabled_entity_ids: list[str] | None = None,
) -> tuple[str, bool]:
    """Build Sber state list JSON for MQTT publish.

    The resulting payload is validated against :class:`SberStatusPayload`
    (pydantic) before serialisation.  Validation failures are logged as
    warnings but do **not** prevent publishing — Sber may still accept
    a partially valid payload.

    Args:
        entities: Dict of entity_id -> BaseEntity instances.
        entity_ids: Specific entity_ids to include (None = all enabled).
        enabled_entity_ids: List of enabled entity_ids (used when entity_ids is None).

    Returns:
        Tuple of (JSON string, validation_passed bool).
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
        except (TypeError, ValueError, KeyError, AttributeError):
            _LOGGER.exception("Error building Sber current state for %s", entity_id)

    if not states["devices"]:
        # Fallback: report hub as online but with no device states.
        # This happens when no entities have state yet (e.g. all unavailable).
        has_entities = bool(entities)
        states["devices"] = {
            "root": {"states": [{"key": "online", "value": {"type": "BOOL", "bool_value": has_entities}}]}
        }

    valid = validate_status_payload(states)

    return json.dumps(states), valid


def parse_sber_command(payload: bytes | str) -> dict[str, Any]:
    """Parse Sber MQTT command payload.

    Per spec (VR-032), ``devices`` must be a dict keyed by device_id.

    Args:
        payload: Raw MQTT payload (bytes or str).

    Returns:
        Parsed dict with 'devices' key, or empty dict on parse error.
    """
    try:
        data = json.loads(payload)
    except (json.JSONDecodeError, TypeError):
        _LOGGER.warning(
            "Failed to parse Sber command payload: %s", payload[:200] if isinstance(payload, (str, bytes)) else payload
        )
        return {"devices": {}}
    devices = data.get("devices")
    if not isinstance(devices, dict):
        _LOGGER.warning(
            "Invalid command payload: 'devices' must be dict, got %s",
            type(devices).__name__,
        )
        return {"devices": {}}
    return data


def parse_sber_status_request(payload: bytes | str) -> list[str]:
    """Parse Sber status request payload.

    Returns list of requested entity_ids (empty = all).
    """
    try:
        data = json.loads(payload).get("devices") or []
    except (json.JSONDecodeError, AttributeError, TypeError):
        return []
    else:
        if not isinstance(data, list):
            return []
        if len(data) == 1 and data[0] == "":
            return []
        return data
