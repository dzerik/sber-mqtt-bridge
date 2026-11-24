"""Behavioral contract for stateful input_boolean exports and command confirmation."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.sber_mqtt_bridge.const import (
    CONF_SBER_BROKER,
    CONF_SBER_LOGIN,
    CONF_SBER_PASSWORD,
    CONF_SBER_PORT,
)
from custom_components.sber_mqtt_bridge.devices.relay import RelayEntity
from custom_components.sber_mqtt_bridge.devices.scenario_button import ScenarioButtonEntity
from custom_components.sber_mqtt_bridge.sber_bridge import SberBridge
from custom_components.sber_mqtt_bridge.sber_entity_map import create_sber_entity

ENTITY_ID = "input_boolean.guest_mode"


def _state(value):
    """Return the HA state dictionary consumed by an adapter."""
    return {"entity_id": ENTITY_ID, "state": value, "attributes": {}}


def _command(value):
    """Return the Sber on/off request for one boolean value."""
    return {"states": [{"key": "on_off", "value": {"type": "BOOL", "bool_value": value}}]}


def _values(entity):
    """Index the actual published state by feature name."""
    return {item["key"]: item["value"] for item in entity.to_sber_current_state()[ENTITY_ID]["states"]}


@pytest.mark.parametrize(
    ("initial", "value", "service"), [("off", True, "turn_on"), ("on", False, "turn_off"), ("on", True, "turn_on")]
)
def test_command_sets_boolean_target_without_toggling(initial, value, service):
    """Repeated on remains on; a command never turns a helper into a pulse."""
    entity = create_sber_entity(ENTITY_ID, {"entity_id": ENTITY_ID}, sber_category="relay")
    assert isinstance(entity, RelayEntity)
    entity.fill_by_ha_state(_state(initial))
    results = entity.process_cmd(_command(value))
    assert len(results) == 1
    assert results[0]["url"]["domain"] == "input_boolean"
    assert results[0]["url"]["service"] == service
    assert results[0]["url"]["target"]["entity_id"] == ENTITY_ID
    assert _values(entity)["on_off"]["bool_value"] is (initial == "on")
    assert "button_event" not in _values(entity)


@pytest.mark.parametrize(
    ("ha_state", "online"), [("on", True), ("off", True), ("unknown", False), ("unavailable", False), (None, False)]
)
def test_boolean_state_and_availability_are_distinct(ha_state, online):
    """Unknown states do not announce an available off switch or a button press."""
    entity = RelayEntity({"entity_id": ENTITY_ID})
    entity.fill_by_ha_state(_state(ha_state))
    values = _values(entity)
    assert values["online"]["bool_value"] is online
    assert "button_event" not in values
    if online:
        assert values["on_off"]["bool_value"] is (ha_state == "on")


def test_restoring_legacy_and_explicit_exports_preserves_their_semantics():
    """Reading a restored state creates neither a command nor a press."""
    legacy = create_sber_entity(ENTITY_ID, {"entity_id": ENTITY_ID})
    assert isinstance(legacy, ScenarioButtonEntity)
    legacy.fill_by_ha_state(_state("on"))
    assert "button_event" not in _values(legacy)
    relay = create_sber_entity(ENTITY_ID, {"entity_id": ENTITY_ID}, sber_category="relay")
    relay.fill_by_ha_state(_state("on"))
    assert _values(relay)["on_off"]["bool_value"] is True
    assert "button_event" not in _values(relay)


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_service", [False, True], ids=["state-not-yet-changed", "service-failed"])
async def test_command_echo_waits_for_actual_boolean_state(hass, fail_service, caplog):
    """Even a failed service must not make echo falsely confirm the requested on."""
    entry = MagicMock()
    entry.data = {
        CONF_SBER_LOGIN: "test",
        CONF_SBER_PASSWORD: "pass",
        CONF_SBER_BROKER: "broker.test",
        CONF_SBER_PORT: 8883,
    }
    entry.options = {}
    bridge = SberBridge(hass, entry)
    bridge._connected = True
    bridge._mqtt_service.publish = AsyncMock()
    # These tests inspect the immediate response. Timer behavior is covered by
    # the integration-flow suite; do not leave a delayed task in HA's loop.
    bridge.schedule_confirm = MagicMock()
    entity = RelayEntity({"entity_id": ENTITY_ID})
    entity.fill_by_ha_state(_state("off"))
    bridge._entities[ENTITY_ID] = entity
    bridge._enabled_entity_ids = [ENTITY_ID]
    calls = []

    async def service(call):
        calls.append(call)
        if fail_service:
            raise HomeAssistantError("service refused")

    hass.services.async_register("input_boolean", "turn_on", service)

    await bridge._handle_sber_command(json.dumps({"devices": {ENTITY_ID: _command(True)}}).encode())
    bridge._cancel_confirm(ENTITY_ID)
    await hass.async_block_till_done()

    assert len(calls) == 1
    assert calls[0].data["entity_id"] == ENTITY_ID
    payloads = [
        json.loads(call.args[1])
        for call in bridge._mqtt_service.publish.call_args_list
        if call.args[0].endswith("up/status")
    ]
    for payload in payloads:
        values = {item["key"]: item["value"] for item in payload["devices"][ENTITY_ID]["states"]}
        assert values["on_off"]["bool_value"] is False, "A received command is not an observed HA state"
    assert _values(entity)["on_off"]["bool_value"] is False

    if fail_service:
        assert "service refused" in caplog.text

    if not fail_service:
        # A subsequent real HA observation is allowed to confirm the command.
        entity.process_state_change(_state("off"), _state("on"))
        assert _values(entity)["on_off"]["bool_value"] is True
        assert "button_event" not in _values(entity)


@pytest.mark.asyncio
async def test_mixed_command_batch_keeps_physical_relay_optimistic_echo(hass):
    """An unchanged helper must not suppress the ack needed by a physical relay."""
    entry = MagicMock()
    entry.data = {
        CONF_SBER_LOGIN: "test",
        CONF_SBER_PASSWORD: "pass",
        CONF_SBER_BROKER: "broker.test",
        CONF_SBER_PORT: 8883,
    }
    entry.options = {}
    bridge = SberBridge(hass, entry)
    bridge._connected = True
    bridge._mqtt_service.publish = AsyncMock()
    devices = {}
    for entity_id in (ENTITY_ID, "switch.physical"):
        entity = RelayEntity({"entity_id": entity_id})
        entity.fill_by_ha_state({"entity_id": entity_id, "state": "off", "attributes": {}})
        bridge._entities[entity_id] = entity
        devices[entity_id] = _command(True)
    bridge._enabled_entity_ids = list(devices)

    async def unchanged(call):
        """Accept the service without providing a new state yet."""

    hass.services.async_register("input_boolean", "turn_on", unchanged)
    hass.services.async_register("switch", "turn_on", unchanged)
    await bridge._handle_sber_command(json.dumps({"devices": devices}).encode())
    for entity_id in devices:
        bridge._cancel_confirm(entity_id)
    await hass.async_block_till_done()

    published = [
        json.loads(call.args[1])["devices"]
        for call in bridge._mqtt_service.publish.call_args_list
        if call.args[0].endswith("up/status")
    ]
    assert published
    latest = published[-1]
    for entity_id, expected in ((ENTITY_ID, False), ("switch.physical", True)):
        values = {item["key"]: item["value"] for item in latest[entity_id]["states"]}
        assert values["on_off"]["bool_value"] is expected
