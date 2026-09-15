"""Bridge health numbers: connection phase, what Sber knows, errors."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass

from .entity import SberBridgeDiagnosticEntity
from .message_logger import parse_sber_error

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from . import SberBridgeConfigEntry
    from .sber_bridge import SberBridge

__all__ = ["PARALLEL_UPDATES", "async_setup_entry"]

PARALLEL_UPDATES = 0
"""No limit: read-only entities pushed from the bridge's memory, nothing is requested."""

PHASES = ["starting", "connecting", "awaiting_ack", "ready", "auth_failed", "disconnected"]
"""Every value :attr:`SberBridge.connection_phase` can take."""


def _last_error_code(bridge: SberBridge) -> int | None:
    error = parse_sber_error(bridge.stats.get("last_error_detail", ""))
    return error["code"] if error else None


@dataclass(frozen=True, slots=True, kw_only=True)
class BridgeSensorDescription:
    """How one bridge sensor reads its value."""

    key: str
    value: Callable[[SberBridge], Any]
    device_class: SensorDeviceClass | None = None
    state_class: SensorStateClass | None = None
    options: list[str] | None = None


SENSORS: tuple[BridgeSensorDescription, ...] = (
    BridgeSensorDescription(
        key="phase", value=lambda b: b.connection_phase, device_class=SensorDeviceClass.ENUM, options=PHASES
    ),
    BridgeSensorDescription(
        key="known_to_sber", value=lambda b: len(b.cloud_known_entities), state_class=SensorStateClass.MEASUREMENT
    ),
    BridgeSensorDescription(
        key="never_confirmed",
        value=lambda b: len(b.never_confirmed_entities),
        state_class=SensorStateClass.MEASUREMENT,
    ),
    BridgeSensorDescription(
        key="sber_errors",
        value=lambda b: b.stats.get("errors_from_sber", 0),
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    BridgeSensorDescription(key="last_sber_error", value=_last_error_code),
)
"""Sensors created for every bridge entry."""


async def async_setup_entry(
    hass: HomeAssistant, entry: SberBridgeConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Create the bridge sensors."""
    bridge = entry.runtime_data.bridge
    async_add_entities(SberBridgeSensor(bridge, entry, description) for description in SENSORS)


class SberBridgeSensor(SberBridgeDiagnosticEntity, SensorEntity):
    """One number or enum describing the bridge."""

    def __init__(self, bridge: SberBridge, entry: SberBridgeConfigEntry, description: BridgeSensorDescription) -> None:
        """Bind the sensor to its description."""
        super().__init__(bridge, entry, description.key)
        self._description = description
        self._attr_device_class = description.device_class
        self._attr_state_class = description.state_class
        self._attr_options = description.options

    @property
    def native_value(self) -> Any:
        """Return the value read from the bridge."""
        return self._description.value(self._bridge)
