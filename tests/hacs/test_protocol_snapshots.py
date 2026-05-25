"""Snapshot tests for Sber protocol JSON responses.

Uses syrupy to capture and verify JSON output stability. Run with
``--snapshot-update`` to regenerate baseline snapshots after intentional
protocol changes.
"""

from __future__ import annotations

import json

import pytest
from syrupy.assertion import SnapshotAssertion

from custom_components.sber_mqtt_bridge import sber_protocol
from custom_components.sber_mqtt_bridge.devices.relay import RelayEntity
from custom_components.sber_mqtt_bridge.devices.sensor_temp import SensorTempEntity
from custom_components.sber_mqtt_bridge.sber_protocol import (
    build_devices_list_json,
    build_hub_device,
    build_states_list_json,
)


@pytest.fixture(autouse=True)
def _pin_version_for_snapshots(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the hub-device version so snapshots don't drift on every release bump.

    ``build_hub_device(version: str = VERSION, ...)`` binds ``VERSION`` to the
    default argument at import time, so monkeypatching the module constant
    has no effect. We wrap the function itself and force ``version="1.0.0"``,
    which makes the hub descriptor's ``hw_version`` / ``sw_version`` stable
    across patch/minor/major bumps. Without this the snapshot had to be
    regenerated after every release — historically that was forgotten and CI
    went red on each bump.
    """
    original = sber_protocol.build_hub_device

    def _frozen(*args: object, **kwargs: object) -> dict:
        kwargs.setdefault("version", "1.0.0")
        return original(*args, **kwargs)

    monkeypatch.setattr(sber_protocol, "build_hub_device", _frozen)

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

    result = json.loads(build_devices_list_json(entities, enabled)[0])
    assert result == snapshot


def test_states_list_multiple_entities(snapshot: SnapshotAssertion) -> None:
    """States list JSON with relay + sensor must match snapshot."""
    relay = RelayEntity(RELAY_ENTITY_DATA)
    relay.fill_by_ha_state(HA_STATE_ON)
    sensor = SensorTempEntity(SENSOR_ENTITY_DATA)
    sensor.fill_by_ha_state(HA_STATE_TEMP)

    entities = {"switch.lamp": relay, "sensor.temp": sensor}
    enabled = ["switch.lamp", "sensor.temp"]

    result = json.loads(build_states_list_json(entities, None, enabled)[0])
    assert result == snapshot


def test_devices_list_with_redefinitions(snapshot: SnapshotAssertion) -> None:
    """Device list JSON with name/home/room overrides must match snapshot."""
    relay = RelayEntity(RELAY_ENTITY_DATA)
    relay.fill_by_ha_state(HA_STATE_ON)

    entities = {"switch.lamp": relay}
    enabled = ["switch.lamp"]
    redefs = {"switch.lamp": {"home": "My Home", "room": "Kitchen", "name": "New Lamp"}}

    result = json.loads(build_devices_list_json(entities, enabled, redefs)[0])
    assert result == snapshot


def test_states_list_empty_fallback_root(snapshot: SnapshotAssertion) -> None:
    """States list JSON with no entities returns root fallback snapshot."""
    result = json.loads(build_states_list_json({}, None, [])[0])
    assert result == snapshot
