"""Tests for immediate command echo after Sber → HA dispatch.

Background — GitHub issue #35 (WLED 16.0.0):
    When HA WLED integration delays or omits state_changed events for
    no-op color commands, the only state confirmation Sber receives is
    via the 1.5s ``_delayed_confirm``. If that exceeds Sber's internal
    ack timeout, Sber marks the command "unconfirmed" and the next
    voice request returns the NLU fallback
    «у этого устройства нет такой возможности».

Fix:
    Right after :meth:`SberCommandDispatcher.handle_command` dispatches
    HA service calls, the bridge publishes an immediate echo of the
    received command states (merged with the entity's current baseline)
    to ``up/status``.  The existing ``_delayed_confirm`` still runs and
    refreshes the authoritative state once HA propagates it.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.sber_mqtt_bridge.const import (
    CONF_SBER_BROKER,
    CONF_SBER_LOGIN,
    CONF_SBER_PASSWORD,
    CONF_SBER_PORT,
)
from custom_components.sber_mqtt_bridge.devices.light import LightEntity
from custom_components.sber_mqtt_bridge.devices.relay import RelayEntity
from custom_components.sber_mqtt_bridge.sber_bridge import SberBridge


def _make_entry(options: dict | None = None) -> MagicMock:
    entry = MagicMock()
    entry.data = {
        CONF_SBER_LOGIN: "test",
        CONF_SBER_PASSWORD: "pass",
        CONF_SBER_BROKER: "broker.test",
        CONF_SBER_PORT: 8883,
    }
    entry.options = options or {}
    return entry


def _make_bridge() -> SberBridge:
    hass = MagicMock()
    hass.config.location_name = "My Home"
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock()
    bridge = SberBridge(hass, _make_entry())
    bridge._mqtt_client = AsyncMock()
    bridge._mqtt_service.publish = AsyncMock()
    bridge._connected = True
    return bridge


def _publishes(bridge: SberBridge, topic_suffix: str) -> list[dict]:
    """Return decoded payloads published to topics ending with ``topic_suffix``."""
    out: list[dict] = []
    for call in bridge._mqtt_service.publish.call_args_list:
        topic = call[0][0]
        if topic.endswith(topic_suffix):
            out.append(json.loads(call[0][1]))
    return out


def _states_by_key(payload: dict, entity_id: str) -> dict[str, dict]:
    states = payload["devices"][entity_id]["states"]
    return {s["key"]: s["value"] for s in states}


class TestCommandEcho:
    """Immediate echo of received Sber commands as fast state ack."""

    @pytest.mark.asyncio
    async def test_light_colour_command_echoes_immediately(self) -> None:
        """light_colour + light_mode command produces an instant up/status echo
        with command values merged on top of the entity's baseline state."""
        bridge = _make_bridge()
        entity = LightEntity({"entity_id": "light.wled", "name": "WLED"})
        entity.fill_by_ha_state(
            {
                "entity_id": "light.wled",
                "state": "on",
                "attributes": {
                    "supported_color_modes": ["rgb"],
                    "color_mode": "rgb",
                    "hs_color": [0, 100],
                    "rgb_color": [255, 0, 0],
                    "brightness": 255,
                },
            }
        )
        bridge._entities["light.wled"] = entity
        bridge._enabled_entity_ids = ["light.wled"]

        cmd = json.dumps(
            {
                "devices": {
                    "light.wled": {
                        "states": [
                            {
                                "key": "light_colour",
                                "value": {
                                    "type": "COLOUR",
                                    "colour_value": {"h": 240, "s": 1000, "v": 1000},
                                },
                            },
                            {
                                "key": "light_mode",
                                "value": {"type": "ENUM", "enum_value": "colour"},
                            },
                        ]
                    }
                }
            }
        )
        await bridge._handle_sber_command(cmd.encode())

        published = _publishes(bridge, "up/status")
        assert published, "Echo publish to up/status must happen synchronously after the command"

        echo = published[0]
        states = _states_by_key(echo, "light.wled")

        # Baseline keys preserved from current entity state.
        assert states["online"]["bool_value"] is True
        assert states["on_off"]["bool_value"] is True

        # Command keys override the baseline.
        assert states["light_colour"]["colour_value"] == {"h": 240, "s": 1000, "v": 1000}
        assert states["light_mode"]["enum_value"] == "colour"

    @pytest.mark.asyncio
    async def test_on_off_command_echoes_immediately(self) -> None:
        """A plain on_off command produces an echo with on_off overridden."""
        bridge = _make_bridge()
        entity = RelayEntity({"entity_id": "switch.lamp", "name": "Lamp"})
        entity.fill_by_ha_state({"entity_id": "switch.lamp", "state": "off", "attributes": {}})
        bridge._entities["switch.lamp"] = entity
        bridge._enabled_entity_ids = ["switch.lamp"]

        cmd = json.dumps(
            {"devices": {"switch.lamp": {"states": [{"key": "on_off", "value": {"type": "BOOL", "bool_value": True}}]}}}
        )
        await bridge._handle_sber_command(cmd.encode())

        published = _publishes(bridge, "up/status")
        assert published, "Echo publish must occur for relay on_off command"

        states = _states_by_key(published[0], "switch.lamp")
        # Command overrode baseline off → on.
        assert states["on_off"]["bool_value"] is True
        assert states["online"]["bool_value"] is True

    @pytest.mark.asyncio
    async def test_echo_skipped_when_disconnected(self) -> None:
        """No echo is sent if the MQTT transport is not connected."""
        bridge = _make_bridge()
        bridge._connected = False
        entity = RelayEntity({"entity_id": "switch.lamp", "name": "Lamp"})
        entity.fill_by_ha_state({"entity_id": "switch.lamp", "state": "off", "attributes": {}})
        bridge._entities["switch.lamp"] = entity
        bridge._enabled_entity_ids = ["switch.lamp"]

        cmd = json.dumps(
            {"devices": {"switch.lamp": {"states": [{"key": "on_off", "value": {"type": "BOOL", "bool_value": True}}]}}}
        )
        await bridge._handle_sber_command(cmd.encode())

        assert _publishes(bridge, "up/status") == []

    @pytest.mark.asyncio
    async def test_echo_skipped_for_unknown_entity(self) -> None:
        """Echo only covers entities the bridge actually owns."""
        bridge = _make_bridge()
        cmd = json.dumps({"devices": {"light.ghost": {"states": []}}})
        await bridge._handle_sber_command(cmd.encode())
        assert _publishes(bridge, "up/status") == []
