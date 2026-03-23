"""Snapshot tests for Sber protocol JSON responses.

Uses syrupy to capture and verify JSON output stability. Run with
``--snapshot-update`` to regenerate baseline snapshots after intentional
protocol changes.
"""

from __future__ import annotations

import json

from syrupy.assertion import SnapshotAssertion

from custom_components.sber_mqtt_bridge.devices.relay import RelayEntity
from custom_components.sber_mqtt_bridge.devices.sensor_temp import SensorTempEntity
from custom_components.sber_mqtt_bridge.sber_protocol import (
    build_devices_list_json,
    build_hub_device,
    build_states_list_json,
)

RELAY_ENTITY_DATA = {
    "entity_id": "switch.lamp",
    "name": "Lamp",
    "original_name": "Lamp",
    "area_id": "room1",
}

SENSOR_ENTITY_DATA = {
    "entity_id": "sensor.temp",
    "name": "Temperature",
    "original_name": "Temp",
    "device_id": "dev2",
    "area_id": "room1",
}

HA_STATE_ON = {
    "entity_id": "switch.lamp",
    "state": "on",
    "attributes": {"friendly_name": "Lamp"},
}

HA_STATE_TEMP = {
    "entity_id": "sensor.temp",
    "state": "22.5",
    "attributes": {"device_class": "temperature"},
}


def test_hub_device_snapshot(snapshot: SnapshotAssertion) -> None:
    """Hub device descriptor must match stored snapshot."""
    result = build_hub_device("1.0.0")
    assert result == snapshot


def test_devices_list_multiple_entities(snapshot: SnapshotAssertion) -> None:
    """Device list JSON with relay + sensor must match snapshot."""
    relay = RelayEntity(RELAY_ENTITY_DATA)
    relay.fill_by_ha_state(HA_STATE_ON)
    sensor = SensorTempEntity(SENSOR_ENTITY_DATA)
    sensor.fill_by_ha_state(HA_STATE_TEMP)

    entities = {"switch.lamp": relay, "sensor.temp": sensor}
    enabled = ["switch.lamp", "sensor.temp"]

    result = json.loads(build_devices_list_json(entities, enabled))
    assert result == snapshot


def test_states_list_multiple_entities(snapshot: SnapshotAssertion) -> None:
    """States list JSON with relay + sensor must match snapshot."""
    relay = RelayEntity(RELAY_ENTITY_DATA)
    relay.fill_by_ha_state(HA_STATE_ON)
    sensor = SensorTempEntity(SENSOR_ENTITY_DATA)
    sensor.fill_by_ha_state(HA_STATE_TEMP)

    entities = {"switch.lamp": relay, "sensor.temp": sensor}
    enabled = ["switch.lamp", "sensor.temp"]

    result = json.loads(build_states_list_json(entities, None, enabled))
    assert result == snapshot


def test_devices_list_with_redefinitions(snapshot: SnapshotAssertion) -> None:
    """Device list JSON with name/home/room overrides must match snapshot."""
    relay = RelayEntity(RELAY_ENTITY_DATA)
    relay.fill_by_ha_state(HA_STATE_ON)

    entities = {"switch.lamp": relay}
    enabled = ["switch.lamp"]
    redefs = {"switch.lamp": {"home": "My Home", "room": "Kitchen", "name": "New Lamp"}}

    result = json.loads(build_devices_list_json(entities, enabled, redefs))
    assert result == snapshot


def test_states_list_empty_fallback_root(snapshot: SnapshotAssertion) -> None:
    """States list JSON with no entities returns root fallback snapshot."""
    result = json.loads(build_states_list_json({}, None, []))
    assert result == snapshot
