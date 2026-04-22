"""End-to-end: a publish through the bridge records validation issues.

Protects the one integration promise: every outbound state publish
feeds the bridge's validation collector with a complete per-entity
issue list.  A miss here means the DevTools panel lies about whether
Sber will accept the payload.
"""

from __future__ import annotations

import asyncio
import contextlib
from unittest.mock import AsyncMock, MagicMock

from custom_components.sber_mqtt_bridge.const import (
    CONF_SBER_BROKER,
    CONF_SBER_LOGIN,
    CONF_SBER_PASSWORD,
    CONF_SBER_PORT,
)
from custom_components.sber_mqtt_bridge.devices.relay import RelayEntity
from custom_components.sber_mqtt_bridge.sber_bridge import SberBridge


def _entry():
    entry = MagicMock()
    entry.data = {
        CONF_SBER_LOGIN: "test",
        CONF_SBER_PASSWORD: "pass",
        CONF_SBER_BROKER: "broker.test",
        CONF_SBER_PORT: 8883,
    }
    entry.options = {}
    return entry


def _hass():
    hass = MagicMock()
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock()
    hass.config.location_name = "My Home"
    tasks: list[asyncio.Task] = []

    def capture(coro, **_):
        t = asyncio.ensure_future(coro)
        tasks.append(t)
        return t

    hass.async_create_task = MagicMock(side_effect=capture)
    hass._created_tasks = tasks
    return hass


def _bridge_with_relay(hass):
    bridge = SberBridge(hass, _entry())
    bridge._mqtt_client = AsyncMock()
    bridge._mqtt_service.publish = AsyncMock()
    bridge._connected = True
    bridge._ack_audit.cancel()
    ent = RelayEntity({"entity_id": "switch.lamp", "name": "Lamp"})
    ent.fill_by_ha_state({"entity_id": "switch.lamp", "state": "off", "attributes": {}})
    bridge._entities["switch.lamp"] = ent
    bridge._enabled_entity_ids = ["switch.lamp"]
    return bridge


async def _drain(hass):
    for t in list(getattr(hass, "_created_tasks", [])):
        if not t.done():
            with contextlib.suppress(TimeoutError, Exception):
                await asyncio.wait_for(t, timeout=5)


class TestValidationIntegration:
    async def test_publish_records_per_entity_view(self) -> None:
        hass = _hass()
        bridge = _bridge_with_relay(hass)
        await bridge._publish_states(["switch.lamp"], force=True)
        await _drain(hass)

        snap = bridge.validation_collector.snapshot()
        # The per-entity bucket must contain our entity — otherwise
        # the UI has no data to render for a "current health" view.
        assert "switch.lamp" in snap["by_entity"]

    async def test_validation_collector_exposed_on_bridge(self) -> None:
        # WS handlers reach the collector through this single attribute.
        bridge = _bridge_with_relay(_hass())
        assert bridge.validation_collector is not None
        initial = bridge.validation_collector.snapshot()
        assert initial == {"recent": [], "by_entity": {}}
