"""Tests for SberBridge core logic."""

import json
import unittest
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest

from custom_components.sber_mqtt_bridge.sber_bridge import SberBridge
from custom_components.sber_mqtt_bridge.const import (
    CONF_EXPOSED_ENTITIES,
    CONF_SBER_BROKER,
    CONF_SBER_LOGIN,
    CONF_SBER_PASSWORD,
    CONF_SBER_PORT,
)


def _make_entry(config=None, options=None):
    """Create a mock config entry."""
    entry = MagicMock()
    entry.data = config or {
        CONF_SBER_LOGIN: "test",
        CONF_SBER_PASSWORD: "pass",
        CONF_SBER_BROKER: "broker.test",
        CONF_SBER_PORT: 8883,
    }
    entry.options = options or {}
    return entry


class TestSberBridgeInit(unittest.TestCase):
    """Test SberBridge initialization."""

    def test_init_sets_topics(self):
        hass = MagicMock()
        entry = _make_entry()
        bridge = SberBridge(hass, entry)

        self.assertEqual(bridge._root_topic, "sberdevices/v1/test")
        self.assertEqual(bridge._down_topic, "sberdevices/v1/test/down")
        self.assertFalse(bridge.is_connected)

    def test_init_empty_entities(self):
        hass = MagicMock()
        entry = _make_entry()
        bridge = SberBridge(hass, entry)

        self.assertEqual(bridge._entities, {})
        self.assertEqual(bridge._enabled_entity_ids, [])


class TestSberBridgeMessageRouting:
    """Test MQTT message routing."""

    @pytest.fixture
    def bridge(self):
        hass = MagicMock()
        entry = _make_entry()
        b = SberBridge(hass, entry)
        b._handle_sber_command = AsyncMock()
        b._handle_sber_status_request = AsyncMock()
        b._handle_sber_config_request = AsyncMock()
        b._handle_change_group = AsyncMock()
        b._handle_rename_device = AsyncMock()
        b._handle_global_config = MagicMock()
        return b

    @pytest.mark.asyncio
    async def test_route_commands(self, bridge):
        await bridge._handle_mqtt_message(
            "sberdevices/v1/test/down/commands", b'{"devices": {}}'
        )
        bridge._handle_sber_command.assert_called_once()

    @pytest.mark.asyncio
    async def test_route_status_request(self, bridge):
        await bridge._handle_mqtt_message(
            "sberdevices/v1/test/down/status_request", b'{"devices": []}'
        )
        bridge._handle_sber_status_request.assert_called_once()

    @pytest.mark.asyncio
    async def test_route_config_request(self, bridge):
        await bridge._handle_mqtt_message(
            "sberdevices/v1/test/down/config_request", b''
        )
        bridge._handle_sber_config_request.assert_called_once()

    @pytest.mark.asyncio
    async def test_route_change_group(self, bridge):
        await bridge._handle_mqtt_message(
            "sberdevices/v1/test/down/change_group_device_request",
            b'{"device_id": "light.a"}'
        )
        bridge._handle_change_group.assert_called_once()

    @pytest.mark.asyncio
    async def test_route_rename(self, bridge):
        await bridge._handle_mqtt_message(
            "sberdevices/v1/test/down/rename_device_request",
            b'{"device_id": "light.a", "new_name": "New"}'
        )
        bridge._handle_rename_device.assert_called_once()

    @pytest.mark.asyncio
    async def test_route_global_config(self, bridge):
        await bridge._handle_mqtt_message(
            "sberdevices/v1/__config",
            b'{"http_api_endpoint": "https://test"}'
        )
        bridge._handle_global_config.assert_called_once()


class TestSberBridgeCommandHandling:
    """Test Sber command → HA service call."""

    @pytest.fixture
    def bridge(self):
        hass = MagicMock()
        hass.services = MagicMock()
        hass.services.async_call = AsyncMock()
        entry = _make_entry()
        b = SberBridge(hass, entry)
        return b

    @pytest.mark.asyncio
    async def test_handle_command_turn_on(self, bridge):
        from custom_components.sber_mqtt_bridge.devices.relay import RelayEntity

        entity = RelayEntity({"entity_id": "switch.lamp", "name": "Lamp"})
        entity.fill_by_ha_state({"entity_id": "switch.lamp", "state": "off", "attributes": {}})
        bridge._entities["switch.lamp"] = entity

        payload = json.dumps({
            "devices": {
                "switch.lamp": {
                    "states": [{"key": "on_off", "value": {"type": "BOOL", "bool_value": True}}]
                }
            }
        })

        await bridge._handle_sber_command(payload.encode())

        bridge._hass.services.async_call.assert_called_once_with(
            domain="switch",
            service="turn_on",
            service_data={},
            target={"entity_id": "switch.lamp"},
            blocking=False,
            context=ANY,
        )

    @pytest.mark.asyncio
    async def test_handle_command_unknown_entity(self, bridge):
        payload = json.dumps({
            "devices": {"unknown.entity": {"states": []}}
        })
        await bridge._handle_sber_command(payload.encode())
        bridge._hass.services.async_call.assert_not_called()


class TestSberBridgeRedefinitions:
    """Test device group/rename handling."""

    @pytest.fixture
    def bridge(self):
        hass = MagicMock()
        entry = _make_entry()
        b = SberBridge(hass, entry)
        b._publish_config = AsyncMock()
        return b

    @pytest.mark.asyncio
    async def test_change_group(self, bridge):
        payload = json.dumps({
            "device_id": "light.room",
            "home": "My House",
            "room": "Bedroom",
        })
        await bridge._handle_change_group(payload.encode())

        assert bridge._redefinitions["light.room"]["home"] == "My House"
        assert bridge._redefinitions["light.room"]["room"] == "Bedroom"
        # No re-publish to avoid infinite loop with Sber
        bridge._publish_config.assert_not_called()

    @pytest.mark.asyncio
    async def test_rename_device(self, bridge):
        payload = json.dumps({
            "device_id": "switch.lamp",
            "new_name": "Night Lamp",
        })
        await bridge._handle_rename_device(payload.encode())

        assert bridge._redefinitions["switch.lamp"]["name"] == "Night Lamp"
        # No re-publish to avoid infinite loop with Sber
        bridge._publish_config.assert_not_called()

    @pytest.mark.asyncio
    async def test_change_group_invalid_json(self, bridge):
        await bridge._handle_change_group(b"not json")
        assert len(bridge._redefinitions) == 0

    @pytest.mark.asyncio
    async def test_rename_missing_fields(self, bridge):
        payload = json.dumps({"device_id": "light.a"})
        await bridge._handle_rename_device(payload.encode())
        bridge._publish_config.assert_not_called()


class TestSberBridgePublish:
    """Test publishing to Sber MQTT."""

    @pytest.fixture
    def bridge(self):
        hass = MagicMock()
        entry = _make_entry()
        b = SberBridge(hass, entry)
        b._mqtt_client = AsyncMock()
        b._connected = True
        return b

    @pytest.mark.asyncio
    async def test_publish_states(self, bridge):
        from custom_components.sber_mqtt_bridge.devices.relay import RelayEntity

        entity = RelayEntity({"entity_id": "switch.lamp", "name": "Lamp"})
        entity.fill_by_ha_state({"entity_id": "switch.lamp", "state": "on", "attributes": {}})
        bridge._entities["switch.lamp"] = entity
        bridge._enabled_entity_ids = ["switch.lamp"]

        await bridge._publish_states(["switch.lamp"])

        bridge._mqtt_client.publish.assert_called_once()
        call_args = bridge._mqtt_client.publish.call_args
        assert "up/status" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_publish_skips_when_disconnected(self, bridge):
        bridge._connected = False
        await bridge._publish_states(["switch.lamp"])
        bridge._mqtt_client.publish.assert_not_called()

    @pytest.mark.asyncio
    async def test_publish_config(self, bridge):
        from custom_components.sber_mqtt_bridge.devices.relay import RelayEntity

        entity = RelayEntity({"entity_id": "switch.lamp", "name": "Lamp"})
        entity.fill_by_ha_state({"entity_id": "switch.lamp", "state": "on", "attributes": {}})
        bridge._entities["switch.lamp"] = entity
        bridge._enabled_entity_ids = ["switch.lamp"]

        await bridge._publish_config()

        bridge._mqtt_client.publish.assert_called_once()
        call_args = bridge._mqtt_client.publish.call_args
        assert "up/config" in call_args[0][0]
        payload = json.loads(call_args[0][1])
        assert len(payload["devices"]) == 2  # hub + lamp
