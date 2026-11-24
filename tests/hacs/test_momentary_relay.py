"""One-shot HA actions controlled through a Sber relay."""

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
from custom_components.sber_mqtt_bridge.sber_bridge import SberBridge
from custom_components.sber_mqtt_bridge.sber_entity_map import categories_for_domain


def _command(value: dict) -> dict:
    return {"states": [{"key": "on_off", "value": value}]}


@pytest.fixture(params=[("input_button", "press"), ("scene", "turn_on")])
def action(request):
    """Use both HA domains against the same one-shot control contract."""
    domain, service = request.param
    entity = RelayEntity({"entity_id": f"{domain}.sber_action"})
    entity.fill_by_ha_state({"state": "unknown", "attributes": {}})
    return entity, service


def test_explicit_relay_keeps_existing_automatic_event_export(action):
    entity, _ = action
    assert categories_for_domain(entity.get_entity_domain()) == ["scenario_button", "relay"]


def test_repeated_on_invokes_the_correct_service(action):
    entity, service = action
    for _ in range(2):
        calls = entity.process_cmd(_command({"type": "BOOL", "bool_value": True}))
        assert len(calls) == 1
        assert calls[0]["url"]["domain"] == entity.get_entity_domain()
        assert calls[0]["url"]["service"] == service
        assert calls[0]["url"]["target"] == {"entity_id": entity.entity_id}


@pytest.mark.parametrize(
    "value", [{"type": "BOOL", "bool_value": False}, {"type": "BOOL"}, {"type": "ENUM", "enum_value": "on"}]
)
def test_off_and_wrong_types_never_execute_an_action(action, value):
    entity, _ = action
    assert entity.process_cmd(_command(value)) == []


@pytest.mark.parametrize(
    ("state", "online"), [("unknown", True), ("2026-11-25T00:00:00+00:00", True), ("unavailable", False), (None, False)]
)
def test_availability_does_not_turn_a_timestamp_into_power(action, state, online):
    entity, _ = action
    entity.fill_by_ha_state({"state": state, "attributes": {}})
    values = {s["key"]: s["value"] for s in entity.to_sber_current_state()[entity.entity_id]["states"]}
    assert values["online"]["bool_value"] is online
    assert values.get("on_off", {}).get("bool_value", False) is False
    assert "button_event" not in values


def test_echo_never_latches_a_momentary_action_on(action):
    entity, _ = action
    states = entity.sanitize_echo_states(
        [
            {"key": "online", "value": {"type": "BOOL", "bool_value": True}},
            {"key": "on_off", "value": {"type": "BOOL", "bool_value": True}},
        ],
        {"on_off"},
    )
    values = {state["key"]: state["value"] for state in states}
    assert values["online"]["bool_value"] is True
    assert values["on_off"]["bool_value"] is False


@pytest.mark.parametrize("fail", [False, True])
async def test_dispatcher_echo_does_not_claim_on_or_wait_for_it(hass, action, fail, caplog):
    """Failed and delayed services must not latch the app or false-confirm power."""
    entity, service = action
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
    bridge.schedule_confirm = MagicMock()
    bridge._entities[entity.entity_id] = entity
    bridge._enabled_entity_ids = [entity.entity_id]
    calls = []

    async def invoke(call):
        calls.append(call.data["entity_id"])
        if fail:
            raise HomeAssistantError("test action refused")

    hass.services.async_register(entity.get_entity_domain(), service, invoke)
    await bridge._handle_sber_command(
        json.dumps({"devices": {entity.entity_id: _command({"type": "BOOL", "bool_value": True})}}).encode()
    )
    bridge._cancel_confirm(entity.entity_id)
    await hass.async_block_till_done()
    assert calls == [entity.entity_id]
    payloads = [
        json.loads(call.args[1])
        for call in bridge._mqtt_service.publish.call_args_list
        if call.args[0].endswith("up/status")
    ]
    assert payloads
    for payload in payloads:
        values = {s["key"]: s["value"] for s in payload["devices"][entity.entity_id]["states"]}
        assert values["on_off"]["bool_value"] is False
    assert bridge._devtools.command_confirm.snapshot() == []
    if fail:
        assert "test action refused" in caplog.text
