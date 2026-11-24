"""Behavior of input_button and scene exports as Sber scenario buttons."""

from __future__ import annotations

import pytest

from custom_components.sber_mqtt_bridge.devices.scenario_button import ScenarioButtonEntity
from custom_components.sber_mqtt_bridge.sber_entity_map import categories_for_domain

TS1 = "2026-11-24T10:00:00+00:00"
TS2 = "2026-11-24T10:00:02+00:00"
TS3 = "2026-11-24T10:00:04+00:00"


def _state(state: str, **attrs) -> dict:
    return {"state": state, "attributes": attrs}


def _wire(entity: ScenarioButtonEntity) -> dict:
    return {item["key"]: item["value"] for item in entity.to_sber_current_state()[entity.entity_id]["states"]}


@pytest.fixture(params=["input_button", "scene"])
def action_entity(request) -> ScenarioButtonEntity:
    """Use the same behavioral contract for both timestamp-based domains."""
    return ScenarioButtonEntity({"entity_id": f"{request.param}.sber_test", "name": "Sber test"})


@pytest.mark.parametrize("domain", ["input_button", "scene"])
def test_action_can_be_selected_as_scenario_button(domain):
    """Missing domain registration would hide these actions from the wizard."""
    assert categories_for_domain(domain)[0] == "scenario_button"


def test_model_advertises_only_single_click(action_entity):
    """Actions cannot truthfully provide long/double press or on/off state."""
    assert action_entity.create_allowed_values_list() == {
        "button_event": {"type": "ENUM", "enum_values": {"values": ["click"]}}
    }
    assert set(action_entity.get_final_features_list()) == {"online", "button_event"}


@pytest.mark.parametrize("initial", ["unknown", TS1])
def test_initial_state_is_online_without_replaying_a_click(action_entity, initial):
    action_entity.fill_by_ha_state(_state(initial))
    assert _wire(action_entity) == {"online": {"type": "BOOL", "bool_value": True}}


def test_each_new_activation_after_publication_produces_a_click(action_entity):
    """Using boolean mapping for timestamps would wrongly emit double_click."""
    previous = _state("unknown")
    action_entity.fill_by_ha_state(previous)
    for timestamp in (TS1, TS2, TS3):
        current = _state(timestamp)
        action_entity.process_state_change(previous, current)
        assert _wire(action_entity)["button_event"] == {"type": "ENUM", "enum_value": "click"}
        action_entity.mark_state_published(snapshot=action_entity.to_sber_current_state())
        assert "button_event" not in _wire(action_entity)
        assert not action_entity.has_significant_change()
        previous = current


def test_attribute_changes_do_not_create_clicks(action_entity):
    action_entity.fill_by_ha_state(_state(TS1))
    action_entity.process_state_change(_state(TS1), _state(TS1, friendly_name="Renamed"))
    assert "button_event" not in _wire(action_entity)


def test_unavailable_load_and_recovery_establish_a_baseline(action_entity):
    action_entity.fill_by_ha_state(_state("unavailable"))
    assert _wire(action_entity)["online"]["bool_value"] is False
    action_entity.process_state_change(_state("unavailable"), _state(TS1))
    assert "button_event" not in _wire(action_entity)
    action_entity.process_state_change(_state(TS1), _state(TS2))
    assert _wire(action_entity)["button_event"]["enum_value"] == "click"


def test_loading_another_timestamp_is_not_a_press(action_entity):
    action_entity.fill_by_ha_state(_state(TS1))
    action_entity.fill_by_ha_state(_state(TS2))
    assert "button_event" not in _wire(action_entity)


def test_incoming_click_does_not_execute_a_ha_action(action_entity):
    assert (
        action_entity.process_cmd(
            {"states": [{"key": "button_event", "value": {"type": "ENUM", "enum_value": "click"}}]}
        )
        == []
    )
