"""Mapping from HA entity domains to Sber device entity classes.

Provides factory functions that create the appropriate Sber entity
subclass based on the HA entity domain and device class.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from .devices.base_entity import BaseEntity
from .devices.climate import ClimateEntity
from .devices.curtain import CurtainEntity
from .devices.door_sensor import DoorSensorEntity
from .devices.humidifier import HumidifierEntity
from .devices.humidity_sensor import HumiditySensorEntity
from .devices.hvac_radiator import HvacRadiatorEntity
from .devices.light import LightEntity
from .devices.motion_sensor import MotionSensorEntity
from .devices.relay import RelayEntity
from .devices.scenario_button import ScenarioButtonEntity
from .devices.sensor_temp import SensorTempEntity
from .devices.socket_entity import SocketEntity
from .devices.valve import ValveEntity
from .devices.water_leak_sensor import WaterLeakSensorEntity
from .devices.window_blind import WindowBlindEntity

_LOGGER = logging.getLogger(__name__)


def _create_sensor(entity_data: dict) -> BaseEntity | None:
    """Create a Sber sensor entity based on device class.

    Args:
        entity_data: HA entity registry dict with 'original_device_class' key.

    Returns:
        SensorTempEntity for temperature, HumiditySensorEntity for humidity,
        or None if the device class is not supported.
    """
    dc = entity_data.get("original_device_class", "")
    if dc == "temperature":
        return SensorTempEntity(entity_data)
    if dc == "humidity":
        return HumiditySensorEntity(entity_data)
    return None


def _create_binary_sensor(entity_data: dict) -> BaseEntity | None:
    """Create a Sber binary sensor entity based on device class.

    Args:
        entity_data: HA entity registry dict with 'original_device_class' key.

    Returns:
        MotionSensorEntity for motion, DoorSensorEntity for door/window/garage,
        WaterLeakSensorEntity for moisture, or None if unsupported.
    """
    dc = entity_data.get("original_device_class", "")
    if dc == "motion":
        return MotionSensorEntity(entity_data)
    if dc in ("door", "window", "garage_door"):
        return DoorSensorEntity(entity_data)
    if dc == "moisture":
        return WaterLeakSensorEntity(entity_data)
    return None


def _create_switch(entity_data: dict) -> BaseEntity:
    """Create a Sber switch entity based on device class.

    Args:
        entity_data: HA entity registry dict with 'original_device_class' key.

    Returns:
        SocketEntity for outlets, RelayEntity for all other switches.
    """
    dc = entity_data.get("original_device_class", "")
    if dc == "outlet":
        return SocketEntity(entity_data)
    return RelayEntity(entity_data)


def _create_cover(entity_data: dict) -> BaseEntity:
    """Create a Sber cover entity based on device class.

    Args:
        entity_data: HA entity registry dict with 'original_device_class' key.

    Returns:
        WindowBlindEntity for blind/shade/shutter, CurtainEntity for others.
    """
    dc = entity_data.get("original_device_class", "")
    if dc in ("blind", "shade", "shutter"):
        return WindowBlindEntity(entity_data)
    return CurtainEntity(entity_data)


def _create_climate(entity_data: dict) -> BaseEntity:
    """Create a Sber climate entity based on device class.

    Args:
        entity_data: HA entity registry dict with 'original_device_class' key.

    Returns:
        HvacRadiatorEntity for radiators, ClimateEntity for others.
    """
    dc = entity_data.get("original_device_class", "")
    if dc == "radiator":
        return HvacRadiatorEntity(entity_data)
    return ClimateEntity(entity_data)


ENTITY_CONSTRUCTORS: dict[str, Callable] = {
    "light": lambda data: LightEntity(data),
    "cover": _create_cover,
    "sensor": _create_sensor,
    "binary_sensor": _create_binary_sensor,
    "switch": _create_switch,
    "script": lambda data: RelayEntity(data),
    "button": lambda data: RelayEntity(data),
    "input_boolean": lambda data: ScenarioButtonEntity(data),
    "climate": _create_climate,
    "valve": lambda data: ValveEntity(data),
    "humidifier": lambda data: HumidifierEntity(data),
}
"""Mapping of HA domain names to Sber entity constructor callables."""


def create_sber_entity(entity_id: str, entity_data: dict) -> BaseEntity | None:
    """Create a Sber device entity from HA entity data.

    Args:
        entity_id: HA entity ID (e.g., 'light.living_room').
        entity_data: Dict with entity registry data (entity_id, device_id, area_id, etc.)

    Returns:
        BaseEntity subclass instance or None if domain not supported.
    """
    domain = entity_id.split(".")[0]
    constructor = ENTITY_CONSTRUCTORS.get(domain)
    if constructor is None:
        _LOGGER.debug("Unsupported domain for Sber: %s", domain)
        return None
    entity = constructor(entity_data)
    if entity is None:
        _LOGGER.debug("No Sber mapping for entity %s (device_class=%s)", entity_id, entity_data.get("original_device_class", ""))
    else:
        _LOGGER.debug(
            "Entity %s → Sber %s (domain=%s, device_class=%s)",
            entity_id, entity.category, domain, entity_data.get("original_device_class", ""),
        )
    return entity
