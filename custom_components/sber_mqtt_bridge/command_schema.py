"""Commands an exposed entity accepts, for the DevTools command builder.

Derived from what the entity declares to Sber (features + allowed values)
and from the documented feature catalogue (value type, usage mode, ranges),
so the builder can only compose a ``down/commands`` payload Sber itself
could send.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ._generated import (
    COLOUR_COMPONENT_RANGES,
    FEATURE_ENUM_VALUES,
    FEATURE_RANGES,
    FEATURE_TYPES,
    FEATURE_USAGE_MODES,
    VALUE_FIELD_BY_TYPE,
)

if TYPE_CHECKING:
    from .devices.base_entity import BaseEntity

WRITABLE_USAGE_MODES = frozenset({"command_only", "state_read_write"})
"""Usage modes of features Sber may send a command for."""


def _number(raw: Any) -> float | int | None:
    """Parse an allowed-values bound (Sber sends them as strings)."""
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return int(value) if value.is_integer() else value


def build_command_schema(entity: BaseEntity) -> list[dict[str, Any]]:
    """List the features of ``entity`` that accept a command, with their value shape.

    Args:
        entity: A loaded bridge entity.

    Returns:
        One entry per writable feature, sorted by key:
        ``{"key", "type", "field"}`` plus ``min``/``max``/``step`` for numbers,
        ``enum_values`` for enums and ``components`` for colours.
    """
    allowed = entity.create_allowed_values_list()
    schema: list[dict[str, Any]] = []
    for key in sorted(set(entity.get_final_features_list())):
        if FEATURE_USAGE_MODES.get(key) not in WRITABLE_USAGE_MODES:
            continue
        value_type = FEATURE_TYPES.get(key)
        if value_type is None:
            continue
        item: dict[str, Any] = {"key": key, "type": value_type, "field": VALUE_FIELD_BY_TYPE[value_type]}
        spec = allowed.get(key) or {}
        if value_type in ("INTEGER", "FLOAT"):
            box = spec.get("integer_values") or spec.get("float_values") or {}
            low, high = _number(box.get("min")), _number(box.get("max"))
            if low is None or high is None:
                low, high = FEATURE_RANGES.get(key, (None, None))
            if low is not None and high is not None:
                item["min"], item["max"] = _number(low), _number(high)
            step = _number(box.get("step"))
            if step is not None:
                item["step"] = step
        elif value_type == "ENUM":
            values = (spec.get("enum_values") or {}).get("values") or FEATURE_ENUM_VALUES.get(key) or ()
            item["enum_values"] = sorted(values)
        elif value_type == "COLOUR":
            item["components"] = {name: list(bounds) for name, bounds in COLOUR_COMPONENT_RANGES.items()}
        schema.append(item)
    return schema
