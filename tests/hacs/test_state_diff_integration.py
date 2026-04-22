"""End-to-end tests: a Sber command → publish path produces state diffs.

Guards the single important promise of this module at the bridge
level: every outbound publish that changes a device's Sber-visible
state registers a non-empty diff in ``bridge.diff_collector``.  A
missing diff here means DevTools will never surface what actually
changed between two publishes.
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


def _relay_bridge(hass):
    bridge = SberBridge(hass, _entry())
    bridge._mqtt_client = AsyncMock()
    bridge._mqtt_service.publish = AsyncMock()
    bridge._connected = True
    bridge._ack_audit.cancel()
    rel = RelayEntity({"entity_id": "switch.lamp", "name": "Lamp"})
    rel.fill_by_ha_state({"entity_id": "switch.lamp", "state": "off", "attributes": {}})
    bridge._entities["switch.lamp"] = rel
    bridge._enabled_entity_ids = ["switch.lamp"]
    return bridge


async def _drain(hass):
    for t in list(getattr(hass, "_created_tasks", [])):
        if not t.done():
            with contextlib.suppress(TimeoutError, Exception):
                await asyncio.wait_for(t, timeout=5)


class TestPublishProducesDiffs:
    async def test_state_change_between_publishes_is_recorded(self) -> None:
        hass = _hass()
        bridge = _relay_bridge(hass)
        # First publish seeds the baseline (default: initial publish is silent).
        await bridge._publish_states(["switch.lamp"], force=True)
        await _drain(hass)
        assert bridge.diff_collector.snapshot() == []

        # Flip the HA state — every subsequent publish must carry the
        # new value, and the diff collector must notice.
        bridge._entities["switch.lamp"].fill_by_ha_state({"entity_id": "switch.lamp", "state": "on", "attributes": {}})
        await bridge._publish_states(["switch.lamp"], force=True)
        await _drain(hass)

        diffs = bridge.diff_collector.snapshot()
        # Exactly one diff — the "on_off False → True" transition.  Missing
        # this is precisely the regression DevTools must not ship with.
        assert len(diffs) == 1
        d = diffs[0]
        assert d["entity_id"] == "switch.lamp"
        assert "on_off" in d["changed"]
        assert d["changed"]["on_off"]["before"]["bool_value"] is False
        assert d["changed"]["on_off"]["after"]["bool_value"] is True

    async def test_no_state_change_produces_no_diff(self) -> None:
        hass = _hass()
        bridge = _relay_bridge(hass)
        # Prime the baseline.
        await bridge._publish_states(["switch.lamp"], force=True)
        before = len(bridge.diff_collector.snapshot())
        # Another publish with the same state must not create a diff —
        # otherwise the UI would spam identical entries every republish cycle.
        await bridge._publish_states(["switch.lamp"], force=True)
        assert len(bridge.diff_collector.snapshot()) == before


class TestDiffCollectorExposedOnBridge:
    def test_bridge_exposes_diff_collector_property(self) -> None:
        hass = _hass()
        bridge = _relay_bridge(hass)
        # WS handlers reach the collector through this one attribute.
        # Renaming it would silently break the panel.
        assert bridge.diff_collector is not None
        assert bridge.diff_collector.snapshot() == []
