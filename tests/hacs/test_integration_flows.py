"""Integration flow tests for the Sber MQTT Bridge.

Verify the full command -> state -> publish cycle including
race conditions, delayed confirms, reconnect guards, and timing edge cases.
"""

from __future__ import annotations

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.sber_mqtt_bridge.const import (
    CONF_SBER_BROKER,
    CONF_SBER_LOGIN,
    CONF_SBER_PASSWORD,
    CONF_SBER_PORT,
)
from custom_components.sber_mqtt_bridge.devices.climate import ClimateEntity
from custom_components.sber_mqtt_bridge.devices.curtain import CurtainEntity
from custom_components.sber_mqtt_bridge.devices.humidifier import HumidifierEntity
from custom_components.sber_mqtt_bridge.devices.hvac_fan import HvacFanEntity
from custom_components.sber_mqtt_bridge.devices.light import LightEntity
from custom_components.sber_mqtt_bridge.devices.motion_sensor import MotionSensorEntity
from custom_components.sber_mqtt_bridge.devices.relay import RelayEntity
from custom_components.sber_mqtt_bridge.devices.sensor_temp import SensorTempEntity
from custom_components.sber_mqtt_bridge.devices.tv import TvEntity
from custom_components.sber_mqtt_bridge.devices.vacuum_cleaner import VacuumCleanerEntity
from custom_components.sber_mqtt_bridge.devices.valve import ValveEntity
from custom_components.sber_mqtt_bridge.sber_bridge import SberBridge


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entry(options=None):
    """Create a mock ConfigEntry with Sber credentials."""
    entry = MagicMock()
    entry.data = {
        CONF_SBER_LOGIN: "test",
        CONF_SBER_PASSWORD: "pass",
        CONF_SBER_BROKER: "broker.test",
        CONF_SBER_PORT: 8883,
    }
    entry.options = options or {}
    return entry


def _make_hass():
    """Create a MagicMock hass with async services and states."""
    hass = MagicMock()
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock()
    hass.config.location_name = "My Home"
    created_tasks: list[asyncio.Task] = []

    def _capture_task(coro, **kwargs):
        task = asyncio.ensure_future(coro)
        created_tasks.append(task)
        return task

    hass.async_create_task = MagicMock(side_effect=_capture_task)
    hass._created_tasks = created_tasks
    return hass


def _make_bridge(hass, entity_cls, entity_id, ha_state, ha_attrs=None, *, cls_kwargs=None):
    """Create bridge with one entity already filled with HA state."""
    entry = _make_entry()
    bridge = SberBridge(hass, entry)
    bridge._mqtt_client = AsyncMock()
    bridge._connected = True
    bridge._awaiting_sber_ack = False

    kwargs = cls_kwargs or {}
    entity = entity_cls({"entity_id": entity_id, "name": "Test"}, **kwargs) if kwargs else entity_cls({"entity_id": entity_id, "name": "Test"})
    entity.fill_by_ha_state({
        "entity_id": entity_id,
        "state": ha_state,
        "attributes": ha_attrs or {},
    })
    bridge._entities[entity_id] = entity
    bridge._enabled_entity_ids = [entity_id]
    return bridge


def _sber_cmd_payload(devices_dict: dict) -> bytes:
    """Build Sber command payload bytes from devices dict.

    Args:
        devices_dict: Mapping of entity_id to {"states": [...]}.
    """
    return json.dumps({"devices": devices_dict}).encode()


def _get_published_payloads(bridge) -> list[dict]:
    """Extract all published state payloads from the mqtt mock."""
    results = []
    for c in bridge._mqtt_client.publish.call_args_list:
        args = c.args if c.args else c[0]
        topic = args[0]
        if "up/status" in str(topic):
            results.append(json.loads(args[1]))
    return results


def _get_published_config_payloads(bridge) -> list[dict]:
    """Extract all published config payloads from the mqtt mock."""
    results = []
    for c in bridge._mqtt_client.publish.call_args_list:
        args = c.args if c.args else c[0]
        topic = args[0]
        if "up/config" in str(topic):
            results.append(json.loads(args[1]))
    return results


def _find_state_value(states_list: list[dict], key: str) -> dict | None:
    """Find a specific state key in a Sber states list."""
    for s in states_list:
        if s.get("key") == key:
            return s.get("value", {})
    return None


def _find_state_entry(states_list: list[dict], key: str) -> dict | None:
    """Find a full state entry dict by key."""
    for s in states_list:
        if s.get("key") == key:
            return s
    return None


async def _drain_tasks(hass):
    """Wait for all created background tasks to complete."""
    for task in getattr(hass, "_created_tasks", []):
        if not task.done():
            try:
                await asyncio.wait_for(task, timeout=5)
            except (asyncio.TimeoutError, Exception):
                pass


def _mock_ha_state(state: str, attributes: dict | None = None):
    """Create a mock HA state object."""
    mock = MagicMock()
    mock.state = state
    mock.attributes = attributes or {}
    return mock


# ---------------------------------------------------------------------------
# TestBridgeFlowBasic
# ---------------------------------------------------------------------------


class TestBridgeFlowBasic:
    """Basic command -> service call -> publish flow tests."""

    async def test_command_to_service_call_to_publish(self):
        """Relay on_off=true triggers switch.turn_on and publishes on_off=true."""
        hass = _make_hass()
        bridge = _make_bridge(hass, RelayEntity, "switch.lamp", "off")

        ha_state_after = _mock_ha_state("on")
        hass.states.get = MagicMock(return_value=ha_state_after)

        payload = _sber_cmd_payload({
            "switch.lamp": {
                "states": [
                    {"key": "on_off", "value": {"type": "BOOL", "bool_value": True}},
                ],
            },
        })

        with patch(
            "custom_components.sber_mqtt_bridge.sber_bridge.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            await bridge._handle_sber_command(payload)
            await _drain_tasks(hass)

        # Verify service call
        hass.services.async_call.assert_called()
        call_kwargs = hass.services.async_call.call_args
        assert call_kwargs.kwargs["domain"] == "switch"
        assert call_kwargs.kwargs["service"] == "turn_on"

        # Verify MQTT publish contains on_off=true
        payloads = _get_published_payloads(bridge)
        assert len(payloads) >= 1
        last_payload = payloads[-1]
        device_states = last_payload["devices"]["switch.lamp"]["states"]
        on_off_val = _find_state_value(device_states, "on_off")
        assert on_off_val is not None
        assert on_off_val["bool_value"] is True

    async def test_on_off_state_confirmation(self):
        """Relay on_off=false produces published state with on_off=false."""
        hass = _make_hass()
        bridge = _make_bridge(hass, RelayEntity, "switch.lamp", "on")

        ha_state_after = _mock_ha_state("off")
        hass.states.get = MagicMock(return_value=ha_state_after)

        payload = _sber_cmd_payload({
            "switch.lamp": {
                "states": [
                    {"key": "on_off", "value": {"type": "BOOL", "bool_value": False}},
                ],
            },
        })

        with patch(
            "custom_components.sber_mqtt_bridge.sber_bridge.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            await bridge._handle_sber_command(payload)
            await _drain_tasks(hass)

        payloads = _get_published_payloads(bridge)
        assert len(payloads) >= 1
        device_states = payloads[-1]["devices"]["switch.lamp"]["states"]
        on_off_val = _find_state_value(device_states, "on_off")
        assert on_off_val is not None
        assert on_off_val["bool_value"] is False


# ---------------------------------------------------------------------------
# TestBridgeFlowDelayedConfirm
# ---------------------------------------------------------------------------


class TestBridgeFlowDelayedConfirm:
    """Delayed state confirmation after command execution."""

    async def test_delayed_confirm_publishes_after_command(self):
        """Light brightness command triggers delayed confirm with updated state."""
        hass = _make_hass()
        bridge = _make_bridge(
            hass,
            LightEntity,
            "light.lamp",
            "on",
            {
                "brightness": 255,
                "color_mode": "color_temp",
                "supported_color_modes": ["color_temp", "hs"],
                "color_temp": 300,
            },
        )

        ha_state_after = _mock_ha_state("on", {
            "brightness": 128,
            "color_mode": "color_temp",
            "supported_color_modes": ["color_temp", "hs"],
            "color_temp": 300,
        })
        hass.states.get = MagicMock(return_value=ha_state_after)

        payload = _sber_cmd_payload({
            "light.lamp": {
                "states": [
                    {"key": "light_brightness", "value": {"type": "INTEGER", "integer_value": 500}},
                ],
            },
        })

        with patch(
            "custom_components.sber_mqtt_bridge.sber_bridge.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            await bridge._handle_sber_command(payload)
            await _drain_tasks(hass)

        # Delayed confirm should have been created and completed
        payloads = _get_published_payloads(bridge)
        assert len(payloads) >= 1
        device_states = payloads[-1]["devices"]["light.lamp"]["states"]
        brightness_val = _find_state_value(device_states, "light_brightness")
        assert brightness_val is not None

    async def test_async_device_stale_then_correct(self):
        """Delayed confirm picks up HA's updated color_mode after ESPHome delay."""
        hass = _make_hass()
        bridge = _make_bridge(
            hass,
            LightEntity,
            "light.lamp",
            "on",
            {
                "brightness": 255,
                "color_mode": "color_temp",
                "supported_color_modes": ["color_temp", "hs", "rgb"],
                "color_temp": 300,
                "hs_color": (45.0, 60.0),
            },
        )
        # Mark current state as published (simulating "white" mode already sent)
        bridge._entities["light.lamp"].mark_state_published()

        # After command, HA now reports color mode as "rgb" with a TUPLE hs_color
        ha_state_after = _mock_ha_state("on", {
            "brightness": 255,
            "color_mode": "rgb",
            "supported_color_modes": ["color_temp", "hs", "rgb"],
            "hs_color": (283.0, 100.0),
            "color_temp": 300,
        })
        hass.states.get = MagicMock(return_value=ha_state_after)

        payload = _sber_cmd_payload({
            "light.lamp": {
                "states": [
                    {
                        "key": "light_colour",
                        "value": {
                            "type": "COLOUR",
                            "colour_value": {"h": 283, "s": 1000, "v": 1000},
                        },
                    },
                ],
            },
        })

        with patch(
            "custom_components.sber_mqtt_bridge.sber_bridge.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            await bridge._handle_sber_command(payload)
            await _drain_tasks(hass)

        payloads = _get_published_payloads(bridge)
        assert len(payloads) >= 1
        device_states = payloads[-1]["devices"]["light.lamp"]["states"]
        mode_val = _find_state_value(device_states, "light_mode")
        assert mode_val is not None
        assert mode_val["enum_value"] == "colour"

    async def test_rgb_mode_switch_delayed_confirm(self):
        """CRITICAL: RGB mode switch via delayed confirm produces light_mode=colour.

        Regression test for a real bug where delayed confirm sent 'white'
        because HA hadn't updated color_mode yet.
        """
        hass = _make_hass()
        bridge = _make_bridge(
            hass,
            LightEntity,
            "light.lamp",
            "on",
            {
                "brightness": 255,
                "color_mode": "color_temp",
                "supported_color_modes": ["color_temp", "hs", "rgb"],
                "hs_color": (45.0, 60.0),
                "color_temp": 300,
            },
        )
        bridge._entities["light.lamp"].mark_state_published()

        # After command, HA reports rgb mode with TUPLE hs_color
        ha_state_after = _mock_ha_state("on", {
            "brightness": 255,
            "color_mode": "rgb",
            "supported_color_modes": ["color_temp", "hs", "rgb"],
            "hs_color": (283.0, 100.0),
            "color_temp": 300,
        })
        hass.states.get = MagicMock(return_value=ha_state_after)

        payload = _sber_cmd_payload({
            "light.lamp": {
                "states": [
                    {"key": "light_mode", "value": {"type": "ENUM", "enum_value": "colour"}},
                    {
                        "key": "light_colour",
                        "value": {
                            "type": "COLOUR",
                            "colour_value": {"h": 283, "s": 1000, "v": 1000},
                        },
                    },
                ],
            },
        })

        with patch(
            "custom_components.sber_mqtt_bridge.sber_bridge.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            await bridge._handle_sber_command(payload)
            await _drain_tasks(hass)

        payloads = _get_published_payloads(bridge)
        assert len(payloads) >= 1
        device_states = payloads[-1]["devices"]["light.lamp"]["states"]
        mode_val = _find_state_value(device_states, "light_mode")
        assert mode_val is not None
        assert mode_val["enum_value"] == "colour", (
            "Delayed confirm must publish 'colour' mode, not 'white'"
        )


# ---------------------------------------------------------------------------
# TestBridgeFlowDebounce
# ---------------------------------------------------------------------------


class TestBridgeFlowDebounce:
    """Debounce and significant change detection tests."""

    async def test_significant_change_on_color_only(self):
        """Color change while state remains 'on' is detected as significant."""
        entity = LightEntity({"entity_id": "light.lamp", "name": "Test"})

        # First fill: color_temp mode
        entity.fill_by_ha_state({
            "entity_id": "light.lamp",
            "state": "on",
            "attributes": {
                "brightness": 255,
                "color_mode": "color_temp",
                "supported_color_modes": ["color_temp", "hs"],
                "color_temp": 300,
            },
        })
        entity.mark_state_published()

        # Second fill: rgb mode, different hs_color
        entity.fill_by_ha_state({
            "entity_id": "light.lamp",
            "state": "on",
            "attributes": {
                "brightness": 255,
                "color_mode": "rgb",
                "supported_color_modes": ["color_temp", "hs"],
                "hs_color": (283.0, 100.0),
            },
        })

        assert entity.has_significant_change() is True

    async def test_rapid_commands_final_state_published(self):
        """Three rapid on/off commands result in final state being published."""
        hass = _make_hass()
        bridge = _make_bridge(hass, RelayEntity, "switch.lamp", "off")

        ha_state_after = _mock_ha_state("on")
        hass.states.get = MagicMock(return_value=ha_state_after)

        commands = [True, False, True]
        with patch(
            "custom_components.sber_mqtt_bridge.sber_bridge.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            for on_val in commands:
                payload = _sber_cmd_payload({
                    "switch.lamp": {
                        "states": [
                            {"key": "on_off", "value": {"type": "BOOL", "bool_value": on_val}},
                        ],
                    },
                })
                await bridge._handle_sber_command(payload)
            await _drain_tasks(hass)

        payloads = _get_published_payloads(bridge)
        assert len(payloads) >= 1
        device_states = payloads[-1]["devices"]["switch.lamp"]["states"]
        on_off_val = _find_state_value(device_states, "on_off")
        assert on_off_val is not None
        assert on_off_val["bool_value"] is True


# ---------------------------------------------------------------------------
# TestBridgeFlowReconnect
# ---------------------------------------------------------------------------


class TestBridgeFlowReconnect:
    """Reconnect guard: reject stale commands after reconnect."""

    async def test_reconnect_guard_rejects_then_accepts(self):
        """Commands rejected during reconnect guard, accepted after clear."""
        hass = _make_hass()
        bridge = _make_bridge(hass, RelayEntity, "switch.lamp", "on")

        ha_state_after = _mock_ha_state("off")
        hass.states.get = MagicMock(return_value=ha_state_after)

        # Activate reconnect guard
        bridge._awaiting_sber_ack = True
        bridge._awaiting_sber_ack_deadline = time.monotonic() + 30

        payload = _sber_cmd_payload({
            "switch.lamp": {
                "states": [
                    {"key": "on_off", "value": {"type": "BOOL", "bool_value": False}},
                ],
            },
        })

        with patch(
            "custom_components.sber_mqtt_bridge.sber_bridge.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            await bridge._handle_sber_command(payload)

        # Service should NOT have been called (command rejected)
        hass.services.async_call.assert_not_called()

        # Verify states were re-published (force=True during rejection)
        payloads = _get_published_payloads(bridge)
        assert len(payloads) >= 1

        # Clear reconnect guard
        bridge._awaiting_sber_ack = False
        hass.services.async_call.reset_mock()
        bridge._mqtt_client.publish.reset_mock()

        with patch(
            "custom_components.sber_mqtt_bridge.sber_bridge.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            await bridge._handle_sber_command(payload)
            await _drain_tasks(hass)

        # Now service SHOULD have been called
        hass.services.async_call.assert_called()


# ---------------------------------------------------------------------------
# TestBridgeFlowEdgeCases
# ---------------------------------------------------------------------------


class TestBridgeFlowEdgeCases:
    """Edge cases: unknown entities, concurrent commands."""

    async def test_command_for_unknown_entity_no_crash(self):
        """Command for an entity not in bridge does not crash."""
        hass = _make_hass()
        bridge = _make_bridge(hass, RelayEntity, "switch.lamp", "on")

        payload = _sber_cmd_payload({
            "switch.unknown": {
                "states": [
                    {"key": "on_off", "value": {"type": "BOOL", "bool_value": False}},
                ],
            },
        })

        with patch(
            "custom_components.sber_mqtt_bridge.sber_bridge.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            # Should not raise
            await bridge._handle_sber_command(payload)

        # No service call for unknown entity
        hass.services.async_call.assert_not_called()

    async def test_concurrent_entities_both_published(self):
        """Commands for two entities in one payload both get processed."""
        hass = _make_hass()
        entry = _make_entry()
        bridge = SberBridge(hass, entry)
        bridge._mqtt_client = AsyncMock()
        bridge._connected = True
        bridge._awaiting_sber_ack = False

        entity_a = RelayEntity({"entity_id": "switch.a", "name": "A"})
        entity_a.fill_by_ha_state({"entity_id": "switch.a", "state": "off", "attributes": {}})
        entity_b = RelayEntity({"entity_id": "switch.b", "name": "B"})
        entity_b.fill_by_ha_state({"entity_id": "switch.b", "state": "on", "attributes": {}})

        bridge._entities = {"switch.a": entity_a, "switch.b": entity_b}
        bridge._enabled_entity_ids = ["switch.a", "switch.b"]

        ha_state_a = _mock_ha_state("on")
        ha_state_b = _mock_ha_state("off")

        def _states_get(eid):
            if eid == "switch.a":
                return ha_state_a
            return ha_state_b

        hass.states.get = MagicMock(side_effect=_states_get)

        payload = _sber_cmd_payload({
            "switch.a": {
                "states": [{"key": "on_off", "value": {"type": "BOOL", "bool_value": True}}],
            },
            "switch.b": {
                "states": [{"key": "on_off", "value": {"type": "BOOL", "bool_value": False}}],
            },
        })

        with patch(
            "custom_components.sber_mqtt_bridge.sber_bridge.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            await bridge._handle_sber_command(payload)
            await _drain_tasks(hass)

        assert hass.services.async_call.call_count >= 2

        payloads = _get_published_payloads(bridge)
        assert len(payloads) >= 1
        last = payloads[-1]
        assert "switch.a" in last["devices"]
        assert "switch.b" in last["devices"]


# ---------------------------------------------------------------------------
# TestClimateFlows
# ---------------------------------------------------------------------------


class TestClimateFlows:
    """Climate entity command flows."""

    async def test_climate_mode_change_cascade(self):
        """hvac_work_mode=heating triggers set_hvac_mode(heat)."""
        hass = _make_hass()
        bridge = _make_bridge(
            hass,
            ClimateEntity,
            "climate.ac",
            "cool",
            {
                "fan_modes": ["auto", "low", "medium", "high"],
                "hvac_modes": ["off", "cool", "heat", "auto"],
                "fan_mode": "auto",
                "temperature": 24,
                "current_temperature": 22,
                "preset_modes": [],
            },
        )

        ha_state_after = _mock_ha_state("heat", {
            "fan_modes": ["auto", "low", "medium", "high"],
            "hvac_modes": ["off", "cool", "heat", "auto"],
            "fan_mode": "auto",
            "temperature": 24,
            "current_temperature": 22,
        })
        hass.states.get = MagicMock(return_value=ha_state_after)

        payload = _sber_cmd_payload({
            "climate.ac": {
                "states": [
                    {"key": "hvac_work_mode", "value": {"type": "ENUM", "enum_value": "heating"}},
                ],
            },
        })

        with patch(
            "custom_components.sber_mqtt_bridge.sber_bridge.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            await bridge._handle_sber_command(payload)
            await _drain_tasks(hass)

        # Verify set_hvac_mode was called
        calls = hass.services.async_call.call_args_list
        hvac_mode_calls = [
            c for c in calls
            if c.kwargs.get("service") == "set_hvac_mode"
        ]
        assert len(hvac_mode_calls) == 1
        assert hvac_mode_calls[0].kwargs["service_data"]["hvac_mode"] == "heat"

    async def test_climate_temp_and_mode_single_command(self):
        """Temperature + mode in one command produces two service calls."""
        hass = _make_hass()
        bridge = _make_bridge(
            hass,
            ClimateEntity,
            "climate.ac",
            "cool",
            {
                "fan_modes": ["auto"],
                "hvac_modes": ["off", "cool", "heat"],
                "fan_mode": "auto",
                "temperature": 24,
                "current_temperature": 22,
                "preset_modes": [],
            },
        )

        ha_state_after = _mock_ha_state("cool", {"temperature": 25})
        hass.states.get = MagicMock(return_value=ha_state_after)

        payload = _sber_cmd_payload({
            "climate.ac": {
                "states": [
                    {"key": "hvac_temp_set", "value": {"type": "INTEGER", "integer_value": 25}},
                    {"key": "hvac_work_mode", "value": {"type": "ENUM", "enum_value": "cooling"}},
                ],
            },
        })

        with patch(
            "custom_components.sber_mqtt_bridge.sber_bridge.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            await bridge._handle_sber_command(payload)
            await _drain_tasks(hass)

        services_called = [
            c.kwargs.get("service") for c in hass.services.async_call.call_args_list
        ]
        assert "set_temperature" in services_called
        assert "set_hvac_mode" in services_called

    async def test_climate_night_mode_toggle(self):
        """hvac_night_mode=true triggers set_preset_mode(sleep)."""
        hass = _make_hass()
        bridge = _make_bridge(
            hass,
            ClimateEntity,
            "climate.ac",
            "cool",
            {
                "fan_modes": ["auto"],
                "hvac_modes": ["off", "cool"],
                "fan_mode": "auto",
                "temperature": 24,
                "current_temperature": 22,
                "preset_modes": ["sleep", "boost"],
                "preset_mode": "none",
            },
        )

        ha_state_after = _mock_ha_state("cool", {"preset_mode": "sleep"})
        hass.states.get = MagicMock(return_value=ha_state_after)

        payload = _sber_cmd_payload({
            "climate.ac": {
                "states": [
                    {"key": "hvac_night_mode", "value": {"type": "BOOL", "bool_value": True}},
                ],
            },
        })

        with patch(
            "custom_components.sber_mqtt_bridge.sber_bridge.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            await bridge._handle_sber_command(payload)
            await _drain_tasks(hass)

        calls = hass.services.async_call.call_args_list
        preset_calls = [c for c in calls if c.kwargs.get("service") == "set_preset_mode"]
        assert len(preset_calls) == 1
        assert preset_calls[0].kwargs["service_data"]["preset_mode"] == "sleep"


# ---------------------------------------------------------------------------
# TestHumidifierFlows
# ---------------------------------------------------------------------------


class TestHumidifierFlows:
    """Humidifier entity command flows."""

    async def test_humidifier_mode_and_humidity(self):
        """Humidity + air flow power in one command produces two service calls."""
        hass = _make_hass()
        bridge = _make_bridge(
            hass,
            HumidifierEntity,
            "humidifier.room",
            "on",
            {
                "available_modes": ["auto", "low", "high"],
                "mode": "auto",
                "humidity": 50,
            },
        )

        ha_state_after = _mock_ha_state("on", {"humidity": 60, "mode": "high"})
        hass.states.get = MagicMock(return_value=ha_state_after)

        payload = _sber_cmd_payload({
            "humidifier.room": {
                "states": [
                    {"key": "hvac_humidity_set", "value": {"type": "INTEGER", "integer_value": "60"}},
                    {"key": "hvac_air_flow_power", "value": {"type": "ENUM", "enum_value": "high"}},
                ],
            },
        })

        with patch(
            "custom_components.sber_mqtt_bridge.sber_bridge.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            await bridge._handle_sber_command(payload)
            await _drain_tasks(hass)

        services_called = [
            c.kwargs.get("service") for c in hass.services.async_call.call_args_list
        ]
        assert "set_humidity" in services_called
        assert "set_mode" in services_called


# ---------------------------------------------------------------------------
# TestCurtainFlows
# ---------------------------------------------------------------------------


class TestCurtainFlows:
    """Curtain entity command flows."""

    async def test_curtain_position_and_state_consistency(self):
        """Position 0 produces open_state=close (NOT 'closed')."""
        hass = _make_hass()
        bridge = _make_bridge(
            hass,
            CurtainEntity,
            "cover.blinds",
            "open",
            {"current_position": 75},
        )

        ha_state_after = _mock_ha_state("closed", {"current_position": 0})
        hass.states.get = MagicMock(return_value=ha_state_after)

        payload = _sber_cmd_payload({
            "cover.blinds": {
                "states": [
                    {"key": "open_percentage", "value": {"type": "INTEGER", "integer_value": "0"}},
                ],
            },
        })

        with patch(
            "custom_components.sber_mqtt_bridge.sber_bridge.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            await bridge._handle_sber_command(payload)
            await _drain_tasks(hass)

        payloads = _get_published_payloads(bridge)
        assert len(payloads) >= 1
        device_states = payloads[-1]["devices"]["cover.blinds"]["states"]
        open_state_val = _find_state_value(device_states, "open_state")
        assert open_state_val is not None
        assert open_state_val["enum_value"] == "close"

        open_pct_val = _find_state_value(device_states, "open_percentage")
        assert open_pct_val is not None

    async def test_curtain_open_close_stop_commands(self):
        """open_set enum commands map to cover.open/close/stop_cover."""
        hass = _make_hass()
        bridge = _make_bridge(
            hass,
            CurtainEntity,
            "cover.blinds",
            "closed",
            {"current_position": 0},
        )
        hass.states.get = MagicMock(return_value=_mock_ha_state("open", {"current_position": 100}))

        test_cases = [
            ("open", "open_cover"),
            ("close", "close_cover"),
            ("stop", "stop_cover"),
        ]
        for enum_val, expected_service in test_cases:
            hass.services.async_call.reset_mock()
            payload = _sber_cmd_payload({
                "cover.blinds": {
                    "states": [
                        {"key": "open_set", "value": {"type": "ENUM", "enum_value": enum_val}},
                    ],
                },
            })

            with patch(
                "custom_components.sber_mqtt_bridge.sber_bridge.asyncio.sleep",
                new_callable=AsyncMock,
            ):
                await bridge._handle_sber_command(payload)

            calls = hass.services.async_call.call_args_list
            service_calls = [c for c in calls if c.kwargs.get("service") == expected_service]
            assert len(service_calls) >= 1, (
                f"Expected {expected_service} for open_set={enum_val}"
            )


# ---------------------------------------------------------------------------
# TestTvFlows
# ---------------------------------------------------------------------------


class TestTvFlows:
    """TV entity command flows."""

    async def test_tv_volume_source_in_one_command(self):
        """volume_int + source in one command produces volume_set + select_source."""
        hass = _make_hass()
        bridge = _make_bridge(
            hass,
            TvEntity,
            "media_player.tv",
            "playing",
            {
                "volume_level": 0.5,
                "source_list": ["HDMI", "TV"],
                "source": "TV",
            },
        )
        hass.states.get = MagicMock(
            return_value=_mock_ha_state("playing", {"volume_level": 0.3, "source": "HDMI"})
        )

        payload = _sber_cmd_payload({
            "media_player.tv": {
                "states": [
                    {"key": "volume_int", "value": {"type": "INTEGER", "integer_value": 30}},
                    {"key": "source", "value": {"type": "ENUM", "enum_value": "HDMI"}},
                ],
            },
        })

        with patch(
            "custom_components.sber_mqtt_bridge.sber_bridge.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            await bridge._handle_sber_command(payload)
            await _drain_tasks(hass)

        services_called = [
            c.kwargs.get("service") for c in hass.services.async_call.call_args_list
        ]
        assert "volume_set" in services_called
        assert "select_source" in services_called

        # Verify volume level = 30/100 = 0.3
        vol_calls = [
            c for c in hass.services.async_call.call_args_list
            if c.kwargs.get("service") == "volume_set"
        ]
        assert vol_calls[0].kwargs["service_data"]["volume_level"] == pytest.approx(0.3, abs=0.01)

    async def test_tv_channel_int_and_direction(self):
        """channel_int, direction=ok, channel=+ map to correct services."""
        hass = _make_hass()
        bridge = _make_bridge(
            hass,
            TvEntity,
            "media_player.tv",
            "playing",
            {"volume_level": 0.5},
        )
        hass.states.get = MagicMock(
            return_value=_mock_ha_state("playing", {"volume_level": 0.5})
        )

        # channel_int=5 -> play_media
        payload = _sber_cmd_payload({
            "media_player.tv": {
                "states": [
                    {"key": "channel_int", "value": {"type": "INTEGER", "integer_value": 5}},
                ],
            },
        })
        with patch(
            "custom_components.sber_mqtt_bridge.sber_bridge.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            await bridge._handle_sber_command(payload)
            await _drain_tasks(hass)

        calls = hass.services.async_call.call_args_list
        play_media_calls = [c for c in calls if c.kwargs.get("service") == "play_media"]
        assert len(play_media_calls) == 1
        assert play_media_calls[0].kwargs["service_data"]["media_content_type"] == "channel"
        assert play_media_calls[0].kwargs["service_data"]["media_content_id"] == "5"

        # direction=ok -> media_play_pause
        hass.services.async_call.reset_mock()
        hass._created_tasks.clear()
        payload = _sber_cmd_payload({
            "media_player.tv": {
                "states": [
                    {"key": "direction", "value": {"type": "ENUM", "enum_value": "ok"}},
                ],
            },
        })
        with patch(
            "custom_components.sber_mqtt_bridge.sber_bridge.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            await bridge._handle_sber_command(payload)
            await _drain_tasks(hass)

        calls = hass.services.async_call.call_args_list
        pause_calls = [c for c in calls if c.kwargs.get("service") == "media_play_pause"]
        assert len(pause_calls) == 1

        # channel="+" -> media_next_track
        hass.services.async_call.reset_mock()
        hass._created_tasks.clear()
        payload = _sber_cmd_payload({
            "media_player.tv": {
                "states": [
                    {"key": "channel", "value": {"type": "ENUM", "enum_value": "+"}},
                ],
            },
        })
        with patch(
            "custom_components.sber_mqtt_bridge.sber_bridge.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            await bridge._handle_sber_command(payload)
            await _drain_tasks(hass)

        calls = hass.services.async_call.call_args_list
        next_calls = [c for c in calls if c.kwargs.get("service") == "media_next_track"]
        assert len(next_calls) == 1


# ---------------------------------------------------------------------------
# TestVacuumFlows
# ---------------------------------------------------------------------------


class TestVacuumFlows:
    """Vacuum cleaner entity command flows."""

    async def test_vacuum_full_lifecycle(self):
        """Start -> cleaning status -> return_to_base -> go_home status."""
        hass = _make_hass()
        bridge = _make_bridge(
            hass,
            VacuumCleanerEntity,
            "vacuum.robo",
            "docked",
            {"fan_speed_list": ["quiet", "standard", "turbo"]},
        )

        # Command: start
        hass.states.get = MagicMock(
            return_value=_mock_ha_state("cleaning", {"fan_speed": "standard", "fan_speed_list": ["quiet", "standard", "turbo"]})
        )
        payload = _sber_cmd_payload({
            "vacuum.robo": {
                "states": [
                    {"key": "vacuum_cleaner_command", "value": {"type": "ENUM", "enum_value": "start"}},
                ],
            },
        })

        with patch(
            "custom_components.sber_mqtt_bridge.sber_bridge.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            await bridge._handle_sber_command(payload)
            await _drain_tasks(hass)

        calls = hass.services.async_call.call_args_list
        start_calls = [c for c in calls if c.kwargs.get("service") == "start"]
        assert len(start_calls) == 1

        # Verify "cleaning" status after fill
        payloads = _get_published_payloads(bridge)
        assert len(payloads) >= 1
        device_states = payloads[-1]["devices"]["vacuum.robo"]["states"]
        status_val = _find_state_value(device_states, "vacuum_cleaner_status")
        assert status_val is not None
        assert status_val["enum_value"] == "cleaning"

        # Command: return_to_dock
        hass.services.async_call.reset_mock()
        hass._created_tasks.clear()
        bridge._mqtt_client.publish.reset_mock()

        hass.states.get = MagicMock(
            return_value=_mock_ha_state("returning", {"fan_speed": "standard", "fan_speed_list": ["quiet", "standard", "turbo"]})
        )
        payload = _sber_cmd_payload({
            "vacuum.robo": {
                "states": [
                    {"key": "vacuum_cleaner_command", "value": {"type": "ENUM", "enum_value": "return_to_dock"}},
                ],
            },
        })

        with patch(
            "custom_components.sber_mqtt_bridge.sber_bridge.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            await bridge._handle_sber_command(payload)
            await _drain_tasks(hass)

        calls = hass.services.async_call.call_args_list
        return_calls = [c for c in calls if c.kwargs.get("service") == "return_to_base"]
        assert len(return_calls) == 1

        # Verify "go_home" status (NOT "returning"!)
        payloads = _get_published_payloads(bridge)
        assert len(payloads) >= 1
        device_states = payloads[-1]["devices"]["vacuum.robo"]["states"]
        status_val = _find_state_value(device_states, "vacuum_cleaner_status")
        assert status_val is not None
        assert status_val["enum_value"] == "go_home", (
            "Sber expects 'go_home', not 'returning'"
        )


# ---------------------------------------------------------------------------
# TestFanFlows
# ---------------------------------------------------------------------------


class TestFanFlows:
    """Fan entity command flows."""

    async def test_simple_fan_no_speed_command(self):
        """Fan without preset_modes handles on_off and hvac_air_flow_power without crash."""
        hass = _make_hass()
        bridge = _make_bridge(
            hass,
            HvacFanEntity,
            "fan.ceiling",
            "on",
            {"percentage": 50},
        )
        hass.states.get = MagicMock(
            return_value=_mock_ha_state("on", {"percentage": 75})
        )

        # on_off=true
        payload = _sber_cmd_payload({
            "fan.ceiling": {
                "states": [
                    {"key": "on_off", "value": {"type": "BOOL", "bool_value": True}},
                ],
            },
        })

        with patch(
            "custom_components.sber_mqtt_bridge.sber_bridge.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            await bridge._handle_sber_command(payload)
            await _drain_tasks(hass)

        calls = hass.services.async_call.call_args_list
        on_calls = [c for c in calls if c.kwargs.get("service") == "turn_on"]
        assert len(on_calls) >= 1

        # hvac_air_flow_power=high -> set_percentage (no preset_modes available)
        hass.services.async_call.reset_mock()
        hass._created_tasks.clear()
        bridge._mqtt_client.publish.reset_mock()

        payload = _sber_cmd_payload({
            "fan.ceiling": {
                "states": [
                    {"key": "hvac_air_flow_power", "value": {"type": "ENUM", "enum_value": "high"}},
                ],
            },
        })

        with patch(
            "custom_components.sber_mqtt_bridge.sber_bridge.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            await bridge._handle_sber_command(payload)
            await _drain_tasks(hass)

        calls = hass.services.async_call.call_args_list
        pct_calls = [c for c in calls if c.kwargs.get("service") == "set_percentage"]
        assert len(pct_calls) >= 1
        assert pct_calls[0].kwargs["service_data"]["percentage"] == 75


# ---------------------------------------------------------------------------
# TestSensorFlows
# ---------------------------------------------------------------------------


class TestSensorFlows:
    """Sensor entity state flows."""

    async def test_linked_sensor_propagation(self):
        """Linked humidity update triggers significant change and appears in state."""
        entity = SensorTempEntity({"entity_id": "sensor.temp", "name": "Temperature"})
        entity.fill_by_ha_state({
            "entity_id": "sensor.temp",
            "state": "22.5",
            "attributes": {},
        })
        entity.mark_state_published()

        # Update linked humidity
        entity.update_linked_data("humidity", {"state": "60", "attributes": {}})
        assert entity.has_significant_change() is True

        # Build state: check both temperature and humidity present
        state = entity.to_sber_current_state()
        states_list = state["sensor.temp"]["states"]
        temp_val = _find_state_value(states_list, "temperature")
        assert temp_val is not None
        humidity_val = _find_state_value(states_list, "humidity")
        assert humidity_val is not None

    async def test_pir_event_based_no_idle_state(self):
        """PIR sensor: 'on' emits pir key, 'off' omits it entirely."""
        entity = MotionSensorEntity({"entity_id": "binary_sensor.motion", "name": "Motion"})

        # Motion detected
        entity.fill_by_ha_state({
            "entity_id": "binary_sensor.motion",
            "state": "on",
            "attributes": {},
        })
        state = entity.to_sber_current_state()
        states_list = state["binary_sensor.motion"]["states"]
        pir_entry = _find_state_entry(states_list, "pir")
        assert pir_entry is not None, "pir key must be present when motion detected"

        # No motion
        entity.fill_by_ha_state({
            "entity_id": "binary_sensor.motion",
            "state": "off",
            "attributes": {},
        })
        state = entity.to_sber_current_state()
        states_list = state["binary_sensor.motion"]["states"]
        pir_entry = _find_state_entry(states_list, "pir")
        assert pir_entry is None, "pir key must be ABSENT when no motion"

    async def test_temp_humidity_same_device(self):
        """Temperature sensor with linked humidity reports both in state."""
        entity = SensorTempEntity({"entity_id": "sensor.temp", "name": "TempSensor"})
        entity.fill_by_ha_state({
            "entity_id": "sensor.temp",
            "state": "21.0",
            "attributes": {},
        })

        # Link humidity
        entity.update_linked_data("humidity", {"state": "55", "attributes": {}})

        state = entity.to_sber_current_state()
        states_list = state["sensor.temp"]["states"]
        temp_val = _find_state_value(states_list, "temperature")
        assert temp_val is not None
        humidity_val = _find_state_value(states_list, "humidity")
        assert humidity_val is not None


# ---------------------------------------------------------------------------
# TestValveFlows
# ---------------------------------------------------------------------------


class TestValveFlows:
    """Valve entity command flows."""

    async def test_valve_open_close_with_battery(self):
        """Valve close command and battery level reporting."""
        hass = _make_hass()
        bridge = _make_bridge(
            hass,
            ValveEntity,
            "valve.water",
            "open",
        )

        hass.states.get = MagicMock(return_value=_mock_ha_state("closed"))

        payload = _sber_cmd_payload({
            "valve.water": {
                "states": [
                    {"key": "open_set", "value": {"type": "ENUM", "enum_value": "close"}},
                ],
            },
        })

        with patch(
            "custom_components.sber_mqtt_bridge.sber_bridge.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            await bridge._handle_sber_command(payload)
            await _drain_tasks(hass)

        calls = hass.services.async_call.call_args_list
        close_calls = [c for c in calls if c.kwargs.get("service") == "close_valve"]
        assert len(close_calls) == 1

        # Test battery level linking
        entity = bridge._entities["valve.water"]

        # Battery 85% -> battery_low_power=false
        entity.update_linked_data("battery", {"state": "85"})
        state = entity.to_sber_current_state()
        states_list = state["valve.water"]["states"]
        battery_pct = _find_state_value(states_list, "battery_percentage")
        assert battery_pct is not None
        battery_low = _find_state_value(states_list, "battery_low_power")
        assert battery_low is not None
        assert battery_low["bool_value"] is False

        # Battery 15% -> battery_low_power=true (< 20%)
        entity.update_linked_data("battery", {"state": "15"})
        state = entity.to_sber_current_state()
        states_list = state["valve.water"]["states"]
        battery_low = _find_state_value(states_list, "battery_low_power")
        assert battery_low is not None
        assert battery_low["bool_value"] is True


# ---------------------------------------------------------------------------
# TestRedefinitionsFlows
# ---------------------------------------------------------------------------


class TestRedefinitionsFlows:
    """Redefinitions in config publish."""

    async def test_redefinitions_in_config_publish(self):
        """Redefinitions override name and room in published config."""
        hass = _make_hass()
        bridge = _make_bridge(hass, RelayEntity, "switch.lamp", "on")

        bridge._redefinitions = {
            "switch.lamp": {"name": "New Name", "room": "Bedroom"},
        }

        await bridge._publish_config()

        config_payloads = _get_published_config_payloads(bridge)
        assert len(config_payloads) == 1

        devices = config_payloads[0]["devices"]
        # Find our device (skip hub device at index 0)
        target_device = None
        for d in devices:
            if d.get("id") == "switch.lamp":
                target_device = d
                break

        assert target_device is not None, "switch.lamp not found in config"
        assert target_device["name"] == "New Name"
        assert target_device["room"] == "Bedroom"
