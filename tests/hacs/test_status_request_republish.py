"""Behaviour of ``down/status_request`` handling.

Sber sends ``status_request`` to learn the current state of devices it
believes we expose.  Two user-visible rules are pinned here:

* If Sber asks about a device we no longer expose, our config is stale in
  the cloud — the bridge must re-publish ``up/config`` *before* the
  ``up/status`` payload, otherwise Sber drops states for a device it does
  not know yet.
* A ``status_request`` is also an implicit acknowledgment, so the
  post-reconnect guard must release.

Assertions are made on the MQTT transport (topic + payload), not on
internal publisher helpers.  Moved out of the former ``test_p4_tasks.py``
grab-bag.
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
from custom_components.sber_mqtt_bridge.devices.relay import RelayEntity
from custom_components.sber_mqtt_bridge.sber_bridge import SberBridge


def _make_entry():
    """Create a mock config entry with Sber credentials."""
    entry = MagicMock()
    entry.data = {
        CONF_SBER_LOGIN: "test",
        CONF_SBER_PASSWORD: "pass",
        CONF_SBER_BROKER: "broker.test",
        CONF_SBER_PORT: 8883,
    }
    entry.options = {}
    return entry


def _published_kinds(bridge) -> list[str]:
    """Return ``"config"`` / ``"status"`` per publish, in publish order."""
    kinds = []
    for call in bridge._mqtt_service.publish.call_args_list:
        topic = str(call.args[0])
        kinds.append(topic.rsplit("/", 1)[-1])
    return kinds


def _published_payload(bridge, kind: str) -> dict:
    """Return the first published payload for ``up/<kind>``."""
    for call in bridge._mqtt_service.publish.call_args_list:
        if str(call.args[0]).endswith(f"up/{kind}"):
            return json.loads(call.args[1])
    raise AssertionError(f"no up/{kind} publish among {_published_kinds(bridge)}")


@pytest.fixture
def bridge():
    """Bridge exposing a single known relay, with MQTT mocked at transport."""
    hass = MagicMock()
    # Repair-issue refresh is fire-and-forget; drop the coroutine instead of
    # leaving it un-awaited on the MagicMock hass.
    hass.async_create_task = MagicMock(side_effect=lambda coro, **_kw: (coro.close(), MagicMock())[1])
    hass.config.location_name = "My Home"

    b = SberBridge(hass, _make_entry())
    b._mqtt_client = AsyncMock()
    b._mqtt_service.publish = AsyncMock()
    b._connected = True

    entity = RelayEntity({"entity_id": "light.known", "name": "Known"})
    entity.fill_by_ha_state({"entity_id": "light.known", "state": "on", "attributes": {}})
    b._entities = {"light.known": entity}
    b._enabled_entity_ids = ["light.known"]
    return b


async def test_unknown_entity_triggers_config_republish_before_states(bridge):
    """Stale cloud config is refreshed, and config goes out before states."""
    await bridge._handle_sber_status_request(json.dumps({"devices": ["light.unknown"]}).encode())

    assert _published_kinds(bridge) == ["config", "status"]
    device_ids = {d["id"] for d in _published_payload(bridge, "config")["devices"]}
    assert "light.known" in device_ids


async def test_known_entity_does_not_trigger_config_republish(bridge):
    """A request for a device we already expose must not spam ``up/config``."""
    await bridge._handle_sber_status_request(json.dumps({"devices": ["light.known"]}).encode())

    assert _published_kinds(bridge) == ["status"]
    assert "light.known" in _published_payload(bridge, "status")["devices"]


async def test_root_pseudo_id_does_not_trigger_config_republish(bridge):
    """``root`` is the hub pseudo-device, never present in ``_entities``."""
    await bridge._handle_sber_status_request(json.dumps({"devices": ["root"]}).encode())

    assert _published_kinds(bridge) == ["status"]


async def test_request_for_all_entities_does_not_trigger_config_republish(bridge):
    """An empty device id means "all devices" — nothing is unknown there."""
    await bridge._handle_sber_status_request(json.dumps({"devices": [""]}).encode())

    assert _published_kinds(bridge) == ["status"]


async def test_status_request_acknowledges_the_reconnect_guard(bridge):
    """status_request is an implicit ack: inbound commands may flow again."""
    bridge._ack_audit.activate_post_connect()
    assert bridge._ack_audit.is_awaiting is True

    await bridge._handle_sber_status_request(json.dumps({"devices": ["light.known"]}).encode())

    assert bridge._ack_audit.is_awaiting is False
    bridge._ack_audit.cancel()
