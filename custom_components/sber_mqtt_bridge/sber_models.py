"""Pydantic models for Sber Smart Home MQTT protocol.

Provides typed schemas for Sber protocol payloads (device config, states,
commands) and helper functions for constructing protocol values.

These models serve as:
- Reference documentation for the Sber JSON protocol
- Optional validation layer for outgoing MQTT payloads
- Type-safe constructors for Sber state values
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from pydantic import BaseModel

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Value types
# ---------------------------------------------------------------------------


class SberValue(BaseModel):
    """A typed value in Sber state or command payload.

    Sber protocol uses tagged unions: the ``type`` field selects which
    ``*_value`` field carries the actual data.

    Attributes:
        type: Value type discriminator.
        bool_value: Boolean payload (for ``BOOL`` type).
        integer_value: Integer payload (for ``INTEGER`` type).
        enum_value: Enum string payload (for ``ENUM`` type).
        colour_value: HSV colour dict (for ``COLOUR`` type).
    """

    type: Literal["BOOL", "INTEGER", "ENUM", "COLOUR"]
    bool_value: bool | None = None
    integer_value: int | None = None
    enum_value: str | None = None
    colour_value: dict[str, int] | None = None


class SberState(BaseModel):
    """Single state key-value pair in the Sber protocol.

    Attributes:
        key: State key name (e.g. ``"online"``, ``"on_off"``, ``"brightness"``).
        value: Typed value for the key.
    """

    key: str
    value: SberValue


# ---------------------------------------------------------------------------
# Device descriptors
# ---------------------------------------------------------------------------


class SberDeviceModel(BaseModel):
    """Device model descriptor within a Sber device config.

    Attributes:
        id: Model identifier string.
        manufacturer: Device manufacturer name.
        model: Device model name.
        description: Human-readable description.
        category: Sber device category (e.g. ``"light"``, ``"relay"``).
        features: List of supported feature keys.
        allowed_values: Optional dict of feature constraints.
    """

    id: str
    manufacturer: str = "Unknown"
    model: str = "Unknown"
    description: str = ""
    category: str
    features: list[str]
    allowed_values: dict[str, Any] = {}


class SberDevice(BaseModel):
    """Full device descriptor for Sber config publish.

    Attributes:
        id: Device / entity identifier.
        name: Display name.
        default_name: Fallback name (usually entity_id).
        room: Room / area identifier.
        home: Home / location name (e.g. "Мой дом").
        model: Nested device model descriptor.
        hw_version: Hardware version string.
        sw_version: Software version string.
        model_id: Optional model identifier.
        nicknames: Alternative voice names.
        groups: Device groups.
        parent_id: Parent device entity_id for hub hierarchy.
        partner_meta: Arbitrary key-value metadata for partner integrations.
    """

    id: str
    name: str
    default_name: str | None = None
    room: str = ""
    home: str | None = None
    model: SberDeviceModel
    hw_version: str = "Unknown"
    sw_version: str = "Unknown"
    model_id: str = ""
    nicknames: list[str] | None = None
    groups: list[str] | None = None
    parent_id: str | None = None
    partner_meta: dict[str, str] | None = None


# ---------------------------------------------------------------------------
# MQTT payloads
# ---------------------------------------------------------------------------


class SberDeviceState(BaseModel):
    """Current state of a single device.

    Attributes:
        states: List of state key-value pairs.
    """

    states: list[SberState]


class SberConfigPayload(BaseModel):
    """Config publish payload (device list).

    Attributes:
        devices: List of device descriptors (SberDevice or raw dict).
    """

    devices: list[SberDevice | dict[str, Any]]


class SberStatusPayload(BaseModel):
    """Status publish payload (device states).

    Attributes:
        devices: Mapping of device_id to its current state.
    """

    devices: dict[str, SberDeviceState]


class SberCommandPayload(BaseModel):
    """Incoming command payload from Sber cloud.

    Attributes:
        devices: Mapping of device_id to command states.
    """

    devices: dict[str, SberDeviceState]


# ---------------------------------------------------------------------------
# Helper constructors
# ---------------------------------------------------------------------------


def make_bool_value(value: bool) -> dict[str, Any]:
    """Create a Sber BOOL value dict.

    Args:
        value: Boolean value.

    Returns:
        Dict ready for inclusion in a Sber state payload.
    """
    return {"type": "BOOL", "bool_value": value}


def make_integer_value(value: int) -> dict[str, Any]:
    """Create a Sber INTEGER value dict.

    Per Sber C2C specification, ``integer_value`` is serialized as a string.

    Args:
        value: Integer value.

    Returns:
        Dict ready for inclusion in a Sber state payload.
    """
    return {"type": "INTEGER", "integer_value": str(value)}


def make_enum_value(value: str) -> dict[str, Any]:
    """Create a Sber ENUM value dict.

    Args:
        value: Enum string value.

    Returns:
        Dict ready for inclusion in a Sber state payload.
    """
    return {"type": "ENUM", "enum_value": value}


def make_colour_value(h: int, s: int, v: int) -> dict[str, Any]:
    """Create a Sber COLOUR value dict.

    Args:
        h: Hue component (0-360).
        s: Saturation component (0-100).
        v: Value/brightness component (0-100).

    Returns:
        Dict ready for inclusion in a Sber state payload.
    """
    return {"type": "COLOUR", "colour_value": {"h": h, "s": s, "v": v}}


def make_state(key: str, value: dict[str, Any]) -> dict[str, Any]:
    """Create a Sber state entry dict.

    Args:
        key: State key name.
        value: Typed value dict (from ``make_*_value`` helpers).

    Returns:
        Dict with ``key`` and ``value`` keys.
    """
    return {"key": key, "value": value}


def validate_config_payload(data: dict[str, Any]) -> bool:
    """Validate a config payload dict against the SberConfigPayload schema.

    This is an optional validation step — failures are logged as warnings
    but do not prevent publishing (the raw dict is still valid JSON).

    Args:
        data: Raw dict to validate.

    Returns:
        True if validation passed, False otherwise.
    """
    try:
        SberConfigPayload.model_validate(data)
    except (ValueError, TypeError):
        _LOGGER.warning("Config payload validation failed", exc_info=True)
        return False
    return True


def validate_status_payload(data: dict[str, Any]) -> bool:
    """Validate a status payload dict against the SberStatusPayload schema.

    Args:
        data: Raw dict to validate.

    Returns:
        True if validation passed, False otherwise.
    """
    try:
        SberStatusPayload.model_validate(data)
    except (ValueError, TypeError):
        _LOGGER.warning("Status payload validation failed", exc_info=True)
        return False
    return True
