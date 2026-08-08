"""Tests for SberBridge core logic."""

import asyncio
import json
from unittest.mock import ANY, AsyncMock, MagicMock

import pytest
from homeassistant.core import Context

from custom_components.sber_mqtt_bridge.const import (
    CONF_SBER_BROKER,
    CONF_SBER_LOGIN,
    CONF_SBER_PASSWORD,
    CONF_SBER_PORT,
)
from custom_components.sber_mqtt_bridge.sber_bridge import SberBridge


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


def _state_changed_event(entity_id: str, old: str, new: str, context: Context) -> MagicMock:
    """Build a minimal HA ``state_changed`` event object.

    Args:
        entity_id: Entity whose state changed.
        old: Previous HA state string.
        new: New HA state string.
        context: HA Context attached to the event (Sber-originated or not).

    Returns:
        A mock event exposing ``data`` / ``context`` like the real one.
    """

    def _state(value: str) -> MagicMock:
        state = MagicMock()
        state.entity_id = entity_id
        state.state = value
        state.attributes = {}
        return state

    event = MagicMock()
    event.context = context
    event.data = {"entity_id": entity_id, "old_state": _state(old), "new_state": _state(new)}
    return event


async def _flush_status_publishes(bridge) -> list[dict]:
    """Flush the debounce timer and return every published ``up/status`` payload.

    Waits for the fire-and-forget publish tasks the bridge creates, so the
    assertion sees the real MQTT transport calls rather than an internal
    collaborator.
    """
    bridge._state_forwarder.flush_pending()
    results = await asyncio.wait_for(
        asyncio.gather(*bridge._hass._created_tasks, return_exceptions=True),
        timeout=5,
    )
    for result in results:
        if isinstance(result, BaseException) and not isinstance(result, asyncio.CancelledError):
            raise result
    return [
        json.loads(call.args[1])
        for call in bridge._mqtt_service.publish.call_args_list
        if "up/status" in str(call.args[0])
    ]


class TestSberBridgeInit:
    """Test SberBridge initialization."""

    def test_init_sets_topics(self):
        bridge = SberBridge(MagicMock(), _make_entry())

        # Topics are derived from the Sber login — a wrong root topic means
        # publishing into another tenant's namespace.
        assert bridge._root_topic == "sberdevices/v1/test"
        assert bridge._down_topic == "sberdevices/v1/test/down"
        assert bridge.is_connected is False

    def test_init_empty_entities(self):
        bridge = SberBridge(MagicMock(), _make_entry())

        assert bridge._entities == {}
        assert bridge._enabled_entity_ids == []


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
        payload = b'{"devices": {}}'
        await bridge._handle_mqtt_message("sberdevices/v1/test/down/commands", payload)
        # The raw payload must be forwarded verbatim: handlers parse it themselves.
        bridge._handle_sber_command.assert_called_once_with(payload)
        bridge._handle_sber_status_request.assert_not_called()

    @pytest.mark.asyncio
    async def test_route_status_request(self, bridge):
        payload = b'{"devices": []}'
        await bridge._handle_mqtt_message("sberdevices/v1/test/down/status_request", payload)
        bridge._handle_sber_status_request.assert_called_once_with(payload)

    @pytest.mark.asyncio
    async def test_route_config_request(self, bridge):
        await bridge._handle_mqtt_message("sberdevices/v1/test/down/config_request", b"")
        bridge._handle_sber_config_request.assert_called_once()

    @pytest.mark.asyncio
    async def test_route_change_group(self, bridge):
        payload = b'{"device_id": "light.a"}'
        await bridge._handle_mqtt_message("sberdevices/v1/test/down/change_group_device_request", payload)
        bridge._handle_change_group.assert_called_once_with(payload)

    @pytest.mark.asyncio
    async def test_route_rename(self, bridge):
        payload = b'{"device_id": "light.a", "new_name": "New"}'
        await bridge._handle_mqtt_message("sberdevices/v1/test/down/rename_device_request", payload)
        bridge._handle_rename_device.assert_called_once_with(payload)

    @pytest.mark.asyncio
    async def test_route_global_config(self, bridge):
        payload = b'{"http_api_endpoint": "https://test"}'
        await bridge._handle_mqtt_message("sberdevices/v1/__config", payload)
        bridge._handle_global_config.assert_called_once_with(payload)

    @pytest.mark.asyncio
    async def test_unknown_topic_routes_nowhere(self, bridge):
        # A topic we do not understand must be ignored, not fed to a handler
        # that would misinterpret the payload.
        await bridge._handle_mqtt_message("sberdevices/v1/test/down/unknown_suffix", b"{}")

        for handler in (
            bridge._handle_sber_command,
            bridge._handle_sber_status_request,
            bridge._handle_sber_config_request,
            bridge._handle_change_group,
            bridge._handle_rename_device,
            bridge._handle_global_config,
        ):
            handler.assert_not_called()


class TestSberBridgeCommandHandling:
    """Test Sber command → HA service call."""

    @pytest.fixture
    def bridge(self):
        hass = MagicMock()
        hass.services = MagicMock()
        hass.services.async_call = AsyncMock()
        return SberBridge(hass, _make_entry())

    @pytest.mark.asyncio
    async def test_handle_command_turn_on(self, bridge):
        from custom_components.sber_mqtt_bridge.devices.relay import RelayEntity

        entity = RelayEntity({"entity_id": "switch.lamp", "name": "Lamp"})
        entity.fill_by_ha_state({"entity_id": "switch.lamp", "state": "off", "attributes": {}})
        bridge._entities["switch.lamp"] = entity

        payload = json.dumps(
            {"devices": {"switch.lamp": {"states": [{"key": "on_off", "value": {"type": "BOOL", "bool_value": True}}]}}}
        )

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
        payload = json.dumps({"devices": {"unknown.entity": {"states": []}}})
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
        payload = json.dumps(
            {
                "device_id": "light.room",
                "home": "My House",
                "room": "Bedroom",
            }
        )
        await bridge._handle_change_group(payload.encode())

        assert bridge._redefinitions["light.room"]["home"] == "My House"
        assert bridge._redefinitions["light.room"]["room"] == "Bedroom"
        # No re-publish to avoid infinite loop with Sber
        bridge._publish_config.assert_not_called()

    @pytest.mark.asyncio
    async def test_rename_device(self, bridge):
        payload = json.dumps(
            {
                "device_id": "switch.lamp",
                "new_name": "Night Lamp",
            }
        )
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
        hass.config.location_name = "My Home"
        entry = _make_entry()
        b = SberBridge(hass, entry)
        b._mqtt_client = AsyncMock()
        b._mqtt_service.publish = AsyncMock()
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

        bridge._mqtt_service.publish.assert_called_once()
        call_args = bridge._mqtt_service.publish.call_args
        assert "up/status" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_publish_skips_when_disconnected(self, bridge):
        bridge._connected = False
        await bridge._publish_states(["switch.lamp"])
        bridge._mqtt_service.publish.assert_not_called()

    @pytest.mark.asyncio
    async def test_publish_config(self, bridge):
        from custom_components.sber_mqtt_bridge.devices.relay import RelayEntity

        entity = RelayEntity({"entity_id": "switch.lamp", "name": "Lamp"})
        entity.fill_by_ha_state({"entity_id": "switch.lamp", "state": "on", "attributes": {}})
        bridge._entities["switch.lamp"] = entity
        bridge._enabled_entity_ids = ["switch.lamp"]

        await bridge._publish_config()

        bridge._mqtt_service.publish.assert_called_once()
        call_args = bridge._mqtt_service.publish.call_args
        assert "up/config" in call_args[0][0]
        payload = json.loads(call_args[0][1])
        assert len(payload["devices"]) == 2  # hub + lamp


class TestSberBridgeEchoFix:
    """Test that echo suppression was removed (GitHub issue #3).

    Sber cloud expects a state confirmation on up/status after every command
    it sends on down/commands. The old code suppressed the publish for
    state changes whose Context matched a Sber-originated command, causing
    the Salute app to show stale state. The fix removed _sber_context_ids
    tracking entirely.
    """

    @pytest.fixture
    async def bridge(self):
        """Create a bridge with a relay entity in 'off' state.

        The mock hass is wired to the *real* event loop and really creates
        tasks, so a state change can be followed all the way to an MQTT
        publish instead of stopping at an internal collaborator.
        """
        from custom_components.sber_mqtt_bridge.devices.relay import RelayEntity

        hass = MagicMock()
        hass.services = MagicMock()
        hass.services.async_call = AsyncMock()
        hass.config.location_name = "My Home"

        loop = asyncio.get_running_loop()
        hass.loop = loop
        created_tasks: list[asyncio.Task] = []

        def _create_task(coro, **_kwargs):
            task = loop.create_task(coro)
            created_tasks.append(task)
            return task

        hass.async_create_task = MagicMock(side_effect=_create_task)
        hass._created_tasks = created_tasks

        entry = _make_entry()
        b = SberBridge(hass, entry)
        b._mqtt_client = AsyncMock()
        b._mqtt_service.publish = AsyncMock()
        b._connected = True
        b._ack_audit.cancel()

        entity = RelayEntity({"entity_id": "switch.lamp", "name": "Lamp"})
        entity.fill_by_ha_state({"entity_id": "switch.lamp", "state": "off", "attributes": {}})
        b._entities["switch.lamp"] = entity
        b._enabled_entity_ids = ["switch.lamp"]

        yield b

        b._ack_audit.cancel()
        b._state_forwarder.unsubscribe_all()

    @pytest.mark.asyncio
    async def test_sber_command_state_change_is_published(self, bridge):
        """State change triggered by Sber command must NOT be suppressed.

        Reproduces the scenario from issue #3: Sber sends turn_on command,
        HA fires state_changed with the same Context, and the bridge must
        still publish the state confirmation back to Sber.
        """
        # Arrange: send Sber command to turn on the relay
        payload = json.dumps(
            {"devices": {"switch.lamp": {"states": [{"key": "on_off", "value": {"type": "BOOL", "bool_value": True}}]}}}
        )
        await bridge._handle_sber_command(payload.encode())

        # Capture the Context that was passed to async_call
        call_kwargs = bridge._hass.services.async_call.call_args
        sber_context = call_kwargs.kwargs.get("context") or call_kwargs[1].get("context")
        assert isinstance(sber_context, Context)

        # The delayed-confirm re-publish is a separate mechanism (covered by
        # TestBridgeFlowDelayedConfirm); cancel it so the count assertion
        # below isolates the state-change → publish path.
        for task in list(bridge._confirm_tasks.values()):
            task.cancel()
        bridge._mqtt_service.publish.reset_mock()

        # Act: simulate HA firing state_changed with the same context
        bridge._state_forwarder._on_ha_state_changed(_state_changed_event("switch.lamp", "off", "on", sber_context))
        payloads = await _flush_status_publishes(bridge)

        # Assert: the confirmation really reached the MQTT transport
        assert len(payloads) == 1, "Sber-originated state change must produce exactly one up/status publish"
        states = payloads[0]["devices"]["switch.lamp"]["states"]
        on_off = next((s["value"] for s in states if s["key"] == "on_off"), None)
        assert on_off == {"type": "BOOL", "bool_value": True}, f"expected on_off=true confirmation, got {states}"

    @pytest.mark.asyncio
    async def test_ha_originated_state_change_is_published(self, bridge):
        """State change from HA UI (random context) must be published."""
        bridge._state_forwarder._on_ha_state_changed(_state_changed_event("switch.lamp", "off", "on", Context()))
        payloads = await _flush_status_publishes(bridge)

        assert len(payloads) == 1
        states = payloads[0]["devices"]["switch.lamp"]["states"]
        on_off = next((s["value"] for s in states if s["key"] == "on_off"), None)
        assert on_off == {"type": "BOOL", "bool_value": True}, f"expected on_off=true publish, got {states}"

    @pytest.mark.asyncio
    async def test_sber_command_creates_ha_context(self, bridge):
        """Sber command must create an HA Context for logbook attribution."""
        payload = json.dumps(
            {"devices": {"switch.lamp": {"states": [{"key": "on_off", "value": {"type": "BOOL", "bool_value": True}}]}}}
        )

        await bridge._handle_sber_command(payload.encode())

        bridge._hass.services.async_call.assert_called_once()
        call_kwargs = bridge._hass.services.async_call.call_args
        context_arg = call_kwargs.kwargs.get("context") or call_kwargs[1].get("context")
        assert isinstance(context_arg, Context), "async_call must receive a Context instance for HA logbook attribution"
