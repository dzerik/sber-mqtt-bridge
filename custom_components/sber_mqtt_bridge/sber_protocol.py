"""Sber Smart Home MQTT protocol serialization.

Handles conversion of internal device entities to Sber JSON formats
for MQTT communication (device config, state lists, command parsing).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from .devices.base_entity import BaseEntity
from .name_utils import warn_if_suspicious_id, warn_if_suspicious_name
from .sber_models import validate_config_payload, validate_device, validate_status_payload

_LOGGER = logging.getLogger(__name__)

VERSION = "1.37.0"
"""Protocol version string included in the hub device descriptor."""


def build_hub_device(
    version: str = VERSION,
    home: str = "",
    room: str = "",
    ha_serial_prefix: str | None = None,
) -> dict:
    """Build the root hub device descriptor for Sber.

    Args:
        version: Protocol version string.
        home: Home name for the hub device.
        room: Room name for the hub device.
        ha_serial_prefix: When set, the hub device gets a
            ``partner_meta.ha_serial_number`` value of ``f"ha-{prefix}"``
            (typically the first 8 chars of the HA instance UUID).  Used
            by sister integrations that mirror Sber devices back into HA
            to detect their own loop.  ``None`` disables the marker.
    """
    descriptor: dict = {
        "id": "root",
        "name": "Home Assistant Bridge",
        "default_name": "HA-SberBridge Hub",
        "home": home or "Мой дом",
        "room": room or "Мой дом",
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
    if ha_serial_prefix:
        descriptor["partner_meta"] = {"ha_serial_number": f"ha-{ha_serial_prefix}"}
    return descriptor


def resolve_ha_serial_number(entity: BaseEntity, ha_serial_prefix: str) -> str:
    """Resolve the ``ha_serial_number`` marker for one entity.

    Priority:
        1. Real ``DeviceEntry.serial_number`` if linked to a device.
        2. Normalised MAC from ``DeviceEntry.connections``.
        3. Fallback ``f"ha-{ha_serial_prefix}"`` (per-HA-instance marker).

    Args:
        entity: Entity whose ``linked_device`` may carry HA registry data.
        ha_serial_prefix: First N chars of the HA instance UUID (used as
            fallback when the device has no real serial / MAC).

    Returns:
        Non-empty string suitable for ``partner_meta.ha_serial_number``.
    """
    device = entity.linked_device or {}
    real_serial = (device.get("serial_number") or "").strip()
    if real_serial:
        return real_serial
    mac = (device.get("mac") or "").strip()
    if mac:
        return mac
    return f"ha-{ha_serial_prefix}"


def _inject_ha_serial(device_data: dict, serial: str) -> None:
    """Merge ``ha_serial_number`` into the ``partner_meta`` of a device dict."""
    meta = dict(device_data.get("partner_meta") or {})
    meta["ha_serial_number"] = serial
    device_data["partner_meta"] = meta


def build_devices_list_json(
    entities: dict[str, BaseEntity],
    enabled_entity_ids: list[str],
    redefinitions: dict[str, dict] | None = None,
    default_home: str = "",
    default_room: str = "",
    auto_parent_id: bool = True,
    ha_serial_prefix: str | None = None,
) -> tuple[str, bool, list[str]]:
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
        auto_parent_id: When True, automatically set ``parent_id`` to the hub
            ID (``"root"``) for all child devices that don't have an explicit
            parent_id.  This creates a proper hierarchy in Sber cloud.
        ha_serial_prefix: Per-HA-instance serial prefix.  When provided,
            every device (including the hub) receives a
            ``partner_meta.ha_serial_number`` marker; sister integrations
            use it for loop-detection.  Pass ``None`` to omit markers.

    Returns:
        Tuple ``(json_string, validation_passed, invalid_entity_ids)``.
        ``invalid_entity_ids`` lists entities that failed per-device
        validation and were excluded from the payload.
    """
    device_list: dict[str, Any] = {
        "devices": [build_hub_device(home=default_home, room=default_room, ha_serial_prefix=ha_serial_prefix)]
    }
    invalid_ids: list[str] = []

    for entity_id in enabled_entity_ids:
        entity = entities.get(entity_id)
        if entity is None or not entity.is_filled_by_state:
            continue

        try:
            device_data = entity.to_sber_state()
        except (TypeError, ValueError, KeyError, AttributeError):
            _LOGGER.exception("Error building Sber state for %s", entity_id)
            invalid_ids.append(entity_id)
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

        if auto_parent_id and "parent_id" not in device_data:
            device_data["parent_id"] = "root"

        if ha_serial_prefix:
            _inject_ha_serial(device_data, resolve_ha_serial_number(entity, ha_serial_prefix))

        filtered = {k: v for k, v in device_data.items() if v is not None}

        # Advisory: surface names/ids that Sber is known to silently
        # reject or that Salut voice will not recognise.  Non-fatal,
        # we still publish — user sees a clear WARN in the log.
        warn_if_suspicious_id(filtered.get("id", ""))
        warn_if_suspicious_name(filtered.get("id", ""), filtered.get("name", ""))

        # Per-device strict pydantic validation — exclude invalid devices
        # instead of poisoning the entire config payload.
        device_valid, error_msg = validate_device(filtered)
        if not device_valid:
            _LOGGER.warning(
                "Device %s excluded from config (validation failed): %s",
                entity_id,
                error_msg,
            )
            invalid_ids.append(entity_id)
            continue

        device_list["devices"].append(filtered)

    valid = validate_config_payload(device_list)

    return json.dumps(device_list), valid, invalid_ids


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
