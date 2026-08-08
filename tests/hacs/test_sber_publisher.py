"""Tests for SberPublisher — the publish coordinator extracted from SberBridge.

Focus of this module: the *dependency wiring* between the bridge and the
publisher (W5A refactor).  The publisher no longer holds a bridge
back-reference — it receives a :class:`PublisherDeps` bundle — so these
tests assert that every entry of that bundle is late-bound to live bridge
state and that the bridge-side hooks fire.

Behavioural coverage of the publish flows themselves lives in
``test_publisher_forwarder.py``.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import aiomqtt

from custom_components.sber_mqtt_bridge.ack_audit import AckAudit
from custom_components.sber_mqtt_bridge.const import (
    CONF_HA_SERIAL_NUMBER,
    CONF_HUB_AUTO_PARENT,
    CONF_SBER_BROKER,
    CONF_SBER_LOGIN,
    CONF_SBER_PASSWORD,
    CONF_SBER_PORT,
)
from custom_components.sber_mqtt_bridge.devices.relay import RelayEntity
from custom_components.sber_mqtt_bridge.sber_bridge import SberBridge
from custom_components.sber_mqtt_bridge.sber_publisher import SberPublisher


def _make_entry(options: dict | None = None) -> MagicMock:
    entry = MagicMock()
    entry.data = {
        CONF_SBER_LOGIN: "test",
        CONF_SBER_PASSWORD: "pass",
        CONF_SBER_BROKER: "broker.test",
        CONF_SBER_PORT: 8883,
    }
    entry.options = {} if options is None else options
    return entry


def _make_bridge(options: dict | None = None) -> SberBridge:
    hass = MagicMock()
    hass.config.location_name = "My Home"
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock()
    bridge = SberBridge(hass, _make_entry(options))
    bridge._mqtt_client = AsyncMock()
    bridge._mqtt_service.publish = AsyncMock()
    bridge._connected = True
    return bridge


def _add_relay(bridge: SberBridge, entity_id: str, state: str = "on") -> RelayEntity:
    entity = RelayEntity({"entity_id": entity_id, "name": entity_id})
    entity.fill_by_ha_state({"entity_id": entity_id, "state": state, "attributes": {}})
    bridge._entities[entity_id] = entity
    bridge._enabled_entity_ids.append(entity_id)
    return entity


def _payloads(bridge: SberBridge, topic_suffix: str) -> list[dict]:
    """Return the JSON payloads published to ``up/<topic_suffix>``."""
    return [
        json.loads(call.args[1])
        for call in bridge._mqtt_service.publish.await_args_list
        if call.args[0].endswith(f"/up/{topic_suffix}")
    ]


class TestSberPublisherWiring:
    """The bridge hands the publisher a narrow, late-bound dependency bundle."""

    def test_bridge_owns_a_publisher_instance(self) -> None:
        """SberBridge constructs a SberPublisher in __init__."""
        bridge = _make_bridge()
        assert isinstance(bridge._publisher, SberPublisher)

    def test_publisher_holds_no_bridge_back_reference(self) -> None:
        """The friend-class coupling is gone: no attribute points at the bridge."""
        bridge = _make_bridge()
        publisher = bridge._publisher
        assert not hasattr(publisher, "_bridge")
        assert bridge not in vars(publisher).values()

    def test_last_config_publish_time_starts_none(self) -> None:
        """No publish yet → no recorded timestamp."""
        bridge = _make_bridge()
        assert bridge._publisher.last_config_publish_time is None

    async def test_config_publish_records_a_timestamp(self) -> None:
        """A successful config publish stamps ``last_config_publish_time``."""
        bridge = _make_bridge()
        _add_relay(bridge, "switch.lamp")

        await bridge._publish_config()

        assert bridge._publisher.last_config_publish_time is not None


class TestPublisherDepsAreLateBound:
    """Each dependency must read live bridge state, not an __init__ snapshot."""

    async def test_entities_registered_after_construction_are_published(self) -> None:
        """``get_entities`` is a callable, so post-init registrations show up."""
        bridge = _make_bridge()
        # Registered *after* SberPublisher was constructed in __init__.
        _add_relay(bridge, "switch.lamp", "on")

        await bridge._publish_states(force=True)

        assert "switch.lamp" in _payloads(bridge, "status")[0]["devices"]

    async def test_enabled_ids_shrink_is_respected(self) -> None:
        """Disabling an entity after init removes it from the default publish set."""
        bridge = _make_bridge()
        _add_relay(bridge, "switch.lamp")
        _add_relay(bridge, "switch.fan")
        bridge._enabled_entity_ids.remove("switch.fan")

        await bridge._publish_states(force=True)

        devices = _payloads(bridge, "status")[0]["devices"]
        assert "switch.lamp" in devices
        assert "switch.fan" not in devices

    async def test_redefinitions_written_after_init_reach_the_config(self) -> None:
        """``get_redefinitions`` reads through the store, not a captured dict."""
        bridge = _make_bridge()
        _add_relay(bridge, "switch.lamp")
        bridge._redef_store.replace({"switch.lamp": {"name": "Ночник", "room": "Спальня"}})

        await bridge._publish_config()

        device = next(d for d in _payloads(bridge, "config")[0]["devices"] if d.get("id") == "switch.lamp")
        assert device["name"] == "Ночник"
        assert device["room"] == "Спальня"

    async def test_config_context_carries_ha_location_and_hub_option(self) -> None:
        """``get_config_context`` resolves HA location + the auto-parent option."""
        bridge = _make_bridge(options={CONF_HUB_AUTO_PARENT: True})
        bridge._hass.config.location_name = "Дача"
        _add_relay(bridge, "switch.lamp")

        await bridge._publish_config()

        devices = _payloads(bridge, "config")[0]["devices"]
        device = next(d for d in devices if d.get("id") == "switch.lamp")
        assert device["home"] == "Дача"
        # auto_parent_id=True makes every device hang off a synthesized hub.
        assert device.get("parent_id"), "hub auto-parent option did not reach the payload"

    async def test_default_ha_location_name_falls_back_to_the_sber_default(self) -> None:
        """The stock HA name "Home Assistant" is replaced by "Мой дом"."""
        bridge = _make_bridge()
        # Stock name of an un-onboarded HA install — not a real home name.
        bridge._hass.config.location_name = "Home Assistant"
        _add_relay(bridge, "switch.lamp")

        await bridge._publish_config()

        device = next(d for d in _payloads(bridge, "config")[0]["devices"] if d.get("id") == "switch.lamp")
        assert device["home"] == "Мой дом"
        assert device["room"] == "Мой дом"

    async def test_blank_ha_location_name_falls_back_to_the_sber_default(self) -> None:
        """An empty HA location name must not reach the wire as ""."""
        bridge = _make_bridge()
        bridge._hass.config.location_name = ""
        _add_relay(bridge, "switch.lamp")

        await bridge._publish_config()

        device = next(d for d in _payloads(bridge, "config")[0]["devices"] if d.get("id") == "switch.lamp")
        assert device["home"] == "Мой дом"

    async def test_ha_serial_prefix_marks_the_hub_when_the_option_is_on(self) -> None:
        """``ha_serial_prefix`` reaches ``partner_meta.ha_serial_number``."""
        bridge = _make_bridge(options={CONF_HA_SERIAL_NUMBER: True})
        bridge._ha_instance_id_prefix = "deadbeef"
        _add_relay(bridge, "switch.lamp")

        await bridge._publish_config()

        hub = next(d for d in _payloads(bridge, "config")[0]["devices"] if d.get("id") == "root")
        assert hub["partner_meta"]["ha_serial_number"] == "ha-deadbeef"

    async def test_ha_serial_prefix_is_absent_when_the_option_is_off(self) -> None:
        """Feature off → no loop-detection marker anywhere in the payload."""
        bridge = _make_bridge(options={CONF_HA_SERIAL_NUMBER: False})
        bridge._ha_instance_id_prefix = "deadbeef"
        _add_relay(bridge, "switch.lamp")

        await bridge._publish_config()

        devices = _payloads(bridge, "config")[0]["devices"]
        hub = next(d for d in devices if d.get("id") == "root")
        assert "partner_meta" not in hub
        lamp = next(d for d in devices if d.get("id") == "switch.lamp")
        assert "ha_serial_number" not in lamp.get("partner_meta", {})

    async def test_ha_serial_prefix_also_marks_every_exposed_entity(self) -> None:
        """The per-entity marker rides the same context field as the hub's."""
        bridge = _make_bridge(options={CONF_HA_SERIAL_NUMBER: True})
        bridge._ha_instance_id_prefix = "deadbeef"
        _add_relay(bridge, "switch.lamp")

        await bridge._publish_config()

        lamp = next(d for d in _payloads(bridge, "config")[0]["devices"] if d.get("id") == "switch.lamp")
        assert lamp["partner_meta"]["ha_serial_number"] == "ha-deadbeef"

    async def test_root_topic_dependency_drives_the_wire_topics(self) -> None:
        """``root_topic`` comes from the bridge — no hardcoded topic anywhere."""
        bridge = _make_bridge()
        _add_relay(bridge, "switch.lamp")

        await bridge._publish_states(force=True)
        await bridge._publish_config()
        await bridge._publisher.publish_command_echo(
            {"switch.lamp": {"states": [{"key": "on_off", "value": {"type": "BOOL", "bool_value": True}}]}}
        )

        topics = [call.args[0] for call in bridge._mqtt_service.publish.await_args_list]
        # login is "test" (see _make_entry) → sberdevices/v1/test
        assert topics == [
            "sberdevices/v1/test/up/status",
            "sberdevices/v1/test/up/config",
            "sberdevices/v1/test/up/status",
        ]

    async def test_disconnect_after_init_blocks_publishing(self) -> None:
        """``is_connected`` is polled per publish, not captured at build time."""
        bridge = _make_bridge()
        _add_relay(bridge, "switch.lamp")
        bridge._connected = False

        await bridge._publish_states(force=True)
        await bridge._publish_config()

        bridge._mqtt_service.publish.assert_not_awaited()

    async def test_torn_down_transport_counts_as_publish_error(self) -> None:
        """A ``None`` MQTT service surfaces as a counted failure, not a silent no-op."""
        bridge = _make_bridge()
        bridge._mqtt_service = None

        ok = await bridge._publisher._publish_logged("topic", "{}", "states")

        assert ok is False
        assert bridge._stats.publish_errors == 1
        assert bridge._stats.messages_sent == 0


class TestConfigPublishedHook:
    """``on_config_published`` is the only way the publisher touches the audit."""

    async def test_successful_config_publish_arms_the_ack_audit(self) -> None:
        """The bridge hook schedules the silent-rejection audit."""
        bridge = _make_bridge()
        _add_relay(bridge, "switch.lamp")

        with patch.object(AckAudit, "schedule_audit") as schedule:
            await bridge._publish_config()

        schedule.assert_called_once()

    async def test_failed_config_publish_does_not_arm_the_audit(self) -> None:
        """No wire success → no audit timer (it would fire a false positive)."""
        bridge = _make_bridge()
        _add_relay(bridge, "switch.lamp")
        bridge._mqtt_service.publish.side_effect = aiomqtt.MqttError("broker gone")

        with patch.object(AckAudit, "schedule_audit") as schedule:
            await bridge._publish_config()

        schedule.assert_not_called()
        assert bridge._publisher.last_config_publish_time is None
