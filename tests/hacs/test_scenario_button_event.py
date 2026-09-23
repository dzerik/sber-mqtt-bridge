"""Tests for scenario_button press detection: HA ``event`` domain and ghost-trigger guard."""

from __future__ import annotations

import json
from typing import ClassVar
from unittest.mock import AsyncMock, MagicMock

import pytest
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.sber_mqtt_bridge.const import (
    CONF_SBER_BROKER,
    CONF_SBER_LOGIN,
    CONF_SBER_PASSWORD,
    CONF_SBER_PORT,
)
from custom_components.sber_mqtt_bridge.devices.scenario_button import (
    ScenarioButtonEntity,
    map_event_type,
)
from custom_components.sber_mqtt_bridge.sber_bridge import SberBridge
from custom_components.sber_mqtt_bridge.sber_entity_map import categories_for_domain

EVENT_ID = "event.remote_action"
BOOL_ID = "input_boolean.scene"

TS1 = "2026-09-23T10:00:00.000+00:00"
TS2 = "2026-09-23T10:00:05.000+00:00"
TS3 = "2026-09-23T10:00:09.000+00:00"


def _event_state(state: str, event_type: str | None = "single") -> dict:
    attrs = {"event_types": ["single", "double", "hold", "release"], "device_class": "button"}
    if event_type is not None:
        attrs["event_type"] = event_type
    return {"entity_id": EVENT_ID, "state": state, "attributes": attrs}


def _bool_state(state: str) -> dict:
    return {"entity_id": BOOL_ID, "state": state, "attributes": {}}


def _states(entity: ScenarioButtonEntity) -> dict[str, dict]:
    """Return the published states keyed by feature name."""
    payload = entity.to_sber_current_state()[entity.entity_id]["states"]
    return {s["key"]: s["value"] for s in payload}


def _press(entity: ScenarioButtonEntity, old: dict, new: dict) -> None:
    entity.process_state_change(old, new)


def _publish(entity: ScenarioButtonEntity) -> None:
    """Emulate the publisher: snapshot before the await, mark after."""
    snapshot = entity.to_sber_current_state()
    entity.mark_state_published(snapshot=snapshot)


# ---------------------------------------------------------------------------
# event_type → Sber button_event
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("event_type", "expected"),
    [
        # Zigbee2MQTT
        ("single", "click"),
        ("double", "double_click"),
        ("hold", "long_press"),
        ("release", None),
        ("triple", None),
        ("quadruple", None),
        ("many", None),
        # ZHA
        ("remote_button_short_press", "click"),
        ("remote_button_double_press", "double_click"),
        ("remote_button_long_press", "long_press"),
        ("remote_button_long_release", None),
        ("remote_button_triple_press", None),
        # Hue / misc
        ("short_release", None),
        ("initial_press", "click"),
        ("long_press", "long_press"),
        ("double_click", "double_click"),
        ("click", "click"),
        ("toggle", "click"),
        ("hold_release", None),
        ("Single", "click"),
        # unknown / empty
        ("rotate_left", None),
        ("", None),
        (None, None),
    ],
)
def test_map_event_type(event_type, expected):
    assert map_event_type(event_type) == expected


# ---------------------------------------------------------------------------
# Category mapping
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("device_class", ["button", "doorbell", None])
def test_event_domain_maps_to_scenario_button(device_class):
    assert "scenario_button" in categories_for_domain("event", device_class)


def test_motion_event_is_not_a_button():
    assert "scenario_button" not in categories_for_domain("event", "motion")


def test_input_boolean_still_maps_to_scenario_button():
    assert "scenario_button" in categories_for_domain("input_boolean", None)


# ---------------------------------------------------------------------------
# HA event entity presses
# ---------------------------------------------------------------------------


class TestEventPresses:
    """Presses of a HA ``event`` entity reach Sber, restores and loads do not."""

    def _loaded(self, state: str = TS1) -> ScenarioButtonEntity:
        entity = ScenarioButtonEntity({"entity_id": EVENT_ID, "name": "Remote"})
        entity.fill_by_ha_state(_event_state(state))
        return entity

    def test_initial_load_publishes_only_online(self):
        entity = self._loaded()
        states = _states(entity)
        assert states["online"]["bool_value"] is True
        assert "button_event" not in states

    def test_features_still_declare_button_event(self):
        entity = self._loaded()
        assert "button_event" in entity.get_final_features_list()

    @pytest.mark.parametrize(
        ("event_type", "expected"),
        [("single", "click"), ("double", "double_click"), ("hold", "long_press")],
    )
    def test_press_publishes_mapped_event(self, event_type, expected):
        entity = self._loaded()
        _press(entity, _event_state(TS1), _event_state(TS2, event_type))
        assert entity.has_significant_change()
        assert _states(entity)["button_event"]["enum_value"] == expected

    def test_first_ever_press_from_unknown_counts(self):
        entity = self._loaded("unknown")
        _press(entity, _event_state("unknown", None), _event_state(TS1))
        assert _states(entity)["button_event"]["enum_value"] == "click"

    def test_published_event_is_not_repeated(self):
        entity = self._loaded()
        _press(entity, _event_state(TS1), _event_state(TS2))
        _publish(entity)
        assert not entity.has_significant_change()
        assert "button_event" not in _states(entity)

    def test_second_identical_press_is_published(self):
        entity = self._loaded()
        _press(entity, _event_state(TS1), _event_state(TS2))
        _publish(entity)
        _press(entity, _event_state(TS2), _event_state(TS3))
        assert entity.has_significant_change()
        assert _states(entity)["button_event"]["enum_value"] == "click"

    def test_release_is_ignored(self):
        entity = self._loaded()
        _publish(entity)
        _press(entity, _event_state(TS1), _event_state(TS2, "release"))
        assert not entity.has_significant_change()
        assert "button_event" not in _states(entity)

    def test_restore_after_unavailable_is_not_a_press(self):
        entity = self._loaded()
        _publish(entity)
        _press(entity, _event_state(TS1), _event_state("unavailable"))
        _publish(entity)
        _press(entity, _event_state("unavailable"), _event_state(TS1))
        assert "button_event" not in _states(entity)

    def test_press_after_unavailable_counts(self):
        entity = self._loaded()
        _press(entity, _event_state(TS1), _event_state("unavailable"))
        _press(entity, _event_state("unavailable"), _event_state(TS2))
        assert _states(entity)["button_event"]["enum_value"] == "click"

    def test_restored_timestamp_after_unavailable_load_is_baseline(self):
        entity = self._loaded("unavailable")
        _press(entity, _event_state("unavailable"), _event_state(TS1))
        assert "button_event" not in _states(entity)
        _press(entity, _event_state(TS1), _event_state(TS2))
        assert _states(entity)["button_event"]["enum_value"] == "click"

    def test_never_pressed_event_is_online(self):
        """``unknown`` on an event entity means "no press yet", not unreachable."""
        entity = self._loaded("unknown")
        assert _states(entity)["online"]["bool_value"] is True

    def test_unavailable_goes_offline(self):
        entity = self._loaded()
        _press(entity, _event_state(TS1), _event_state("unavailable"))
        assert _states(entity)["online"]["bool_value"] is False

    def test_reload_via_fill_is_not_a_press(self):
        entity = self._loaded()
        entity.fill_by_ha_state(_event_state(TS2))
        assert "button_event" not in _states(entity)

    def test_event_arriving_during_publish_is_kept(self):
        """A snapshot taken before the press must not consume that press."""
        entity = self._loaded()
        snapshot = entity.to_sber_current_state()
        _press(entity, _event_state(TS1), _event_state(TS2))
        entity.mark_state_published(snapshot=snapshot)
        assert entity.has_significant_change()
        assert _states(entity)["button_event"]["enum_value"] == "click"

    def test_mark_published_without_snapshot_consumes_press(self):
        entity = self._loaded()
        _press(entity, _event_state(TS1), _event_state(TS2))
        entity.mark_state_published()
        assert not entity.has_significant_change()

    def test_failed_snapshot_keeps_press(self):
        entity = self._loaded()
        _press(entity, _event_state(TS1), _event_state(TS2))
        entity.mark_state_published(snapshot=None)
        assert entity.has_significant_change()


# ---------------------------------------------------------------------------
# input_boolean presses (existing behaviour + ghost-trigger fix)
# ---------------------------------------------------------------------------


class TestInputBooleanPresses:
    """``input_boolean`` keeps on→click / off→double_click, without replays."""

    def _loaded(self, state: str = "off") -> ScenarioButtonEntity:
        entity = ScenarioButtonEntity({"entity_id": BOOL_ID, "name": "Scene"})
        entity.fill_by_ha_state(_bool_state(state))
        return entity

    def test_initial_load_does_not_replay_last_press(self):
        entity = self._loaded("on")
        assert "button_event" not in _states(entity)

    def test_turn_on_is_click(self):
        entity = self._loaded("off")
        _press(entity, _bool_state("off"), _bool_state("on"))
        assert _states(entity)["button_event"]["enum_value"] == "click"

    def test_turn_off_is_double_click(self):
        entity = self._loaded("on")
        _press(entity, _bool_state("on"), _bool_state("off"))
        assert _states(entity)["button_event"]["enum_value"] == "double_click"

    def test_attribute_only_change_is_not_a_press(self):
        entity = self._loaded("on")
        _publish(entity)
        _press(entity, _bool_state("on"), _bool_state("on"))
        assert not entity.has_significant_change()


# ---------------------------------------------------------------------------
# Full HA → MQTT path through the real event bus
# ---------------------------------------------------------------------------


class TestEventButtonFlow:
    """A Zigbee button's presses travel state_changed → debounce → up/status."""

    EVENT_ATTRS: ClassVar[dict] = {"event_types": ["single", "double", "hold", "release"], "device_class": "button"}

    async def _make_bridge(self, hass):
        entry = MagicMock()
        entry.data = {
            CONF_SBER_LOGIN: "test",
            CONF_SBER_PASSWORD: "pass",
            CONF_SBER_BROKER: "broker.test",
            CONF_SBER_PORT: 8883,
        }
        entry.options = {}
        bridge = SberBridge(hass, entry)
        bridge._mqtt_client = AsyncMock()
        bridge._mqtt_service.publish = AsyncMock()
        bridge._connected = True
        bridge._ack_audit.cancel()

        hass.states.async_set(EVENT_ID, TS1, {**self.EVENT_ATTRS, "event_type": "single"})
        await hass.async_block_till_done()
        entity = ScenarioButtonEntity({"entity_id": EVENT_ID, "name": "Remote"})
        entity.fill_by_ha_state(_event_state(TS1))
        bridge._entities[EVENT_ID] = entity
        bridge._enabled_entity_ids = [EVENT_ID]
        bridge._subscribe_ha_events()
        return bridge

    @staticmethod
    def _button_events(bridge) -> list[str | None]:
        """Return button_event of every up/status publish (None when absent)."""
        events = []
        for c in bridge._mqtt_service.publish.call_args_list:
            topic, payload = c.args[0], c.args[1]
            if "up/status" not in str(topic):
                continue
            states = json.loads(payload)["devices"][EVENT_ID]["states"]
            value = next((s["value"] for s in states if s["key"] == "button_event"), None)
            events.append(value["enum_value"] if value else None)
        return events

    async def _press(self, hass, ts: str, event_type: str) -> None:
        hass.states.async_set(EVENT_ID, ts, {**self.EVENT_ATTRS, "event_type": event_type})
        await hass.async_block_till_done()
        async_fire_time_changed(hass, fire_all=True)
        await hass.async_block_till_done()

    async def test_repeated_presses_each_publish(self, hass):
        bridge = await self._make_bridge(hass)

        await self._press(hass, TS2, "single")
        await self._press(hass, TS3, "single")
        await self._press(hass, "2026-09-23T10:00:12.000+00:00", "double")
        await self._press(hass, "2026-09-23T10:00:15.000+00:00", "release")

        assert self._button_events(bridge) == ["click", "click", "double_click"]

    async def test_full_republish_does_not_replay_press(self, hass):
        bridge = await self._make_bridge(hass)
        await self._press(hass, TS2, "single")
        bridge._mqtt_service.publish.reset_mock()

        await bridge._publish_states(None, force=True)

        assert self._button_events(bridge) == [None]
