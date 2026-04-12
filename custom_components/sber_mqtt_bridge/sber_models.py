"""Pydantic models for Sber Smart Home MQTT protocol.

Provides **strict** typed schemas for Sber protocol payloads (device config,
states, commands) and helper functions for constructing protocol values.

All models use ``extra="forbid"`` to reject unexpected fields — this catches
protocol violations like the TV ``allowed_values`` bug (extra keys caused
Sber cloud to silently reject devices).

These models serve as:
- Executable specification of the Sber C2C JSON protocol
- Pre-publish validation layer (invalid devices excluded from payload)
- Type-safe constructors for Sber state values

Source of truth: https://developers.sber.ru/docs/ru/smarthome/c2c/
"""

from __future__ import annotations

import json
import logging
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, field_validator

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Value types
# ---------------------------------------------------------------------------


class SberColourValue(BaseModel):
    """HSV colour value per Sber spec.

    Ranges:
        h: 0-360 (hue degrees)
        s: 0-1000 (saturation, 0.1% steps)
        v: 100-1000 (value/brightness, min 100 per Sber spec VR-004)
    """

    model_config = ConfigDict(extra="forbid")

    h: int
    s: int
    v: int


class SberValue(BaseModel):
    """A typed value in Sber state or command payload.

    Sber protocol uses tagged unions: the ``type`` field selects which
    ``*_value`` field carries the actual data.

    Per Sber C2C spec:
    - ``integer_value`` is always a **string** (e.g. ``"220"``, not ``220``)
    - ``colour_value`` is an HSV object with h/s/v integer fields
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["BOOL", "INTEGER", "FLOAT", "STRING", "ENUM", "COLOUR"]
    bool_value: bool | None = None
    integer_value: str | None = None
    float_value: float | None = None
    string_value: str | None = None
    enum_value: str | None = None
    colour_value: SberColourValue | None = None


class SberState(BaseModel):
    """Single state key-value pair in the Sber protocol."""

    model_config = ConfigDict(extra="forbid")

    key: str
    value: SberValue


# ---------------------------------------------------------------------------
# Allowed values (model descriptor)
# ---------------------------------------------------------------------------


class SberAllowedIntegerValues(BaseModel):
    """INTEGER allowed values with min/max/step as strings."""

    model_config = ConfigDict(extra="forbid")

    min: str
    max: str
    step: str


class SberAllowedFloatValues(BaseModel):
    """FLOAT allowed values with numeric min/max."""

    model_config = ConfigDict(extra="forbid")

    min: float
    max: float


class SberAllowedEnumValues(BaseModel):
    """ENUM allowed values with list of valid strings."""

    model_config = ConfigDict(extra="forbid")

    values: list[str]


class SberAllowedValue(BaseModel):
    """Single allowed_values entry for a feature.

    Type discriminator selects which ``*_values`` field is present.
    ``COLOUR`` type has no additional constraints — just ``{"type": "COLOUR"}``.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["INTEGER", "FLOAT", "ENUM", "COLOUR"]
    integer_values: SberAllowedIntegerValues | None = None
    float_values: SberAllowedFloatValues | None = None
    enum_values: SberAllowedEnumValues | None = None


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------


class SberDependencyCondition(BaseModel):
    """Single condition value in a dependency declaration."""

    model_config = ConfigDict(extra="forbid")

    type: str
    enum_value: str | None = None
    bool_value: bool | None = None


class SberDependency(BaseModel):
    """Feature dependency: feature X is available only when key Y has given values."""

    model_config = ConfigDict(extra="forbid")

    key: str
    values: list[SberDependencyCondition]


# ---------------------------------------------------------------------------
# Device descriptors
# ---------------------------------------------------------------------------


class SberDeviceModel(BaseModel):
    """Device model descriptor within a Sber device config.

    Per Sber spec, ``allowed_values`` should only contain keys that are
    in ``features`` and need non-default ranges.  Extra keys cause silent
    device rejection.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    manufacturer: str = "Unknown"
    model: str = "Unknown"
    description: str = ""
    category: str
    features: list[str]
    hw_version: str | None = None
    sw_version: str | None = None
    allowed_values: dict[str, SberAllowedValue] | None = None
    dependencies: dict[str, SberDependency] | None = None

    @field_validator("features")
    @classmethod
    def must_have_online(cls, v: list[str]) -> list[str]:
        """All Sber devices must include 'online' feature (VR-010)."""
        if "online" not in v:
            raise ValueError("'online' must be in features (VR-010)")
        return v

    @field_validator("allowed_values")
    @classmethod
    def allowed_values_keys_must_be_known(
        cls, v: dict[str, SberAllowedValue] | None, info: Any
    ) -> dict[str, SberAllowedValue] | None:
        """allowed_values keys must be subset of features (TV bug prevention)."""
        if v is None:
            return v
        features = info.data.get("features", [])
        extra_keys = set(v.keys()) - set(features)
        if extra_keys:
            raise ValueError(f"allowed_values contains keys not in features: {extra_keys}")
        return v


class SberDevice(BaseModel):
    """Full device descriptor for Sber config publish.

    Per Sber spec (VR-001), ``model_id`` and ``model`` are mutually exclusive.
    This integration always uses inline ``model``; ``model_id`` is not emitted.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    default_name: str | None = None
    room: str = ""
    home: str | None = None
    model: SberDeviceModel
    hw_version: str = "1"
    sw_version: str = "1"
    parent_id: str | None = None
    nicknames: list[str] | None = None
    groups: list[str] | None = None
    partner_meta: dict[str, Any] | None = None

    @field_validator("partner_meta")
    @classmethod
    def partner_meta_max_size(cls, v: dict | None) -> dict | None:
        """partner_meta JSON must be under 1024 chars (VR-003)."""
        if v is not None and len(json.dumps(v)) > 1024:
            raise ValueError("partner_meta JSON exceeds 1024 chars (VR-003)")
        return v


# ---------------------------------------------------------------------------
# MQTT payloads
# ---------------------------------------------------------------------------


class SberDeviceState(BaseModel):
    """Current state of a single device."""

    model_config = ConfigDict(extra="forbid")

    states: list[SberState]


class SberConfigPayload(BaseModel):
    """Config publish payload (``up/config`` topic)."""

    model_config = ConfigDict(extra="forbid")

    devices: list[SberDevice]


class SberStatusPayload(BaseModel):
    """Status publish payload (``up/status`` topic)."""

    model_config = ConfigDict(extra="forbid")

    devices: dict[str, SberDeviceState]


class SberCommandPayload(BaseModel):
    """Incoming command payload from Sber cloud (``down/commands`` topic)."""

    model_config = ConfigDict(extra="forbid")

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
        s: Saturation component (0-1000).
        v: Value/brightness component (100-1000).

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


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def validate_device(device_data: dict[str, Any]) -> tuple[bool, str]:
    """Validate a single device dict against SberDevice schema.

    Args:
        device_data: Raw device dict from ``to_sber_state()``.

    Returns:
        Tuple ``(valid, error_message)``.  ``error_message`` is empty on success.
    """
    try:
        SberDevice.model_validate(device_data)
    except (ValueError, TypeError) as exc:
        return False, str(exc)[:500]
    return True, ""


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


# ---------------------------------------------------------------------------
# Category compliance validation (Context7-verified per Sber C2C docs)
# ---------------------------------------------------------------------------

# Required features per category — verified against
# https://developers.sber.ru/docs/ru/smarthome/c2c/{category}
# via Context7 on 2026-04-12.
CATEGORY_REQUIRED_FEATURES: dict[str, frozenset[str]] = {
    # Control devices (on_off required)
    "light": frozenset({"online", "on_off"}),
    "led_strip": frozenset({"online", "on_off"}),
    "relay": frozenset({"online", "on_off"}),
    "socket": frozenset({"online", "on_off"}),
    "tv": frozenset({"online", "on_off"}),
    # intercom uses unlock/incoming_call/reject_call, NOT on_off (Sber spec)
    "intercom": frozenset({"online"}),
    # HVAC (on_off required)
    "hvac_ac": frozenset({"online", "on_off"}),
    "hvac_radiator": frozenset({"online", "on_off"}),
    "hvac_heater": frozenset({"online", "on_off"}),
    "hvac_boiler": frozenset({"online", "on_off"}),
    "hvac_underfloor_heating": frozenset({"online", "on_off"}),
    "hvac_fan": frozenset({"online", "on_off"}),
    "hvac_air_purifier": frozenset({"online", "on_off"}),
    "hvac_humidifier": frozenset({"online", "on_off"}),
    "kettle": frozenset({"online", "on_off"}),
    # Covers (open_set/open_state, NO on_off)
    "curtain": frozenset({"online"}),
    "window_blind": frozenset({"online"}),
    "gate": frozenset({"online"}),
    "valve": frozenset({"online"}),
    # Sensors (category-specific primary feature)
    "sensor_temp": frozenset({"online", "temperature"}),
    "sensor_pir": frozenset({"online", "pir"}),
    "sensor_door": frozenset({"online", "doorcontact_state"}),
    "sensor_water_leak": frozenset({"online", "water_leak_state"}),
    "sensor_smoke": frozenset({"online", "smoke_state"}),
    "sensor_gas": frozenset({"online", "gas_leak_state"}),
    # Automation — button_event OR button_1_event..button_10_event all valid
    # per Sber spec, so we only require 'online' here and let the device class
    # choose which button_* variant fits.
    "scenario_button": frozenset({"online"}),
    # Appliances
    "vacuum_cleaner": frozenset({"online"}),
    # Hub
    "hub": frozenset({"online"}),
}
"""Required features per Sber category, verified via Context7."""


def validate_category_compliance(device: dict[str, Any]) -> list[str]:
    """Check a device descriptor for Sber category-specific violations.

    Returns a list of human-readable violation messages (empty = compliant).
    Does NOT raise — callers decide how to handle violations.

    Args:
        device: Raw device dict (already passed SberDevice schema validation).
    """
    violations: list[str] = []
    model = device.get("model", {})
    category = model.get("category", "")
    features = set(model.get("features", []))

    # VR-010..VR-016: required features per category
    required = CATEGORY_REQUIRED_FEATURES.get(category)
    if required is not None:
        missing = required - features
        if missing:
            violations.append(f"Missing required features for {category}: {missing}")

    # TV bug prevention: allowed_values keys must be subset of features
    allowed_values = model.get("allowed_values") or {}
    extra_av = set(allowed_values.keys()) - features
    if extra_av:
        violations.append(f"allowed_values contains keys not in features: {extra_av}")

    return violations
