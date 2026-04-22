"""End-to-end tests for the correlation-timeline trace.

Verifies that a full Sber -> HA -> Sber cycle produces a trace with all
four canonical events (``sber_command``, ``ha_service_call``,
``publish_out``, and — via the silent-rejection path — ``silent_rejection``).
These tests guard the integration between TraceCollector, the dispatcher,
the forwarder, and the publish path: an event missing from the timeline
is the whole point of this feature breaking.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.sber_mqtt_bridge.const import (
    CONF_SBER_BROKER,
    CONF_SBER_LOGIN,
    CONF_SBER_PASSWORD,
    CONF_SBER_PORT,
)
from custom_components.sber_mqtt_bridge.devices.relay import RelayEntity
from custom_components.sber_mqtt_bridge.sber_bridge import SberBridge


def _make_entry(options=None):
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
    hass = MagicMock()
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock()
    hass.config.location_name = "My Home"
    created: list[asyncio.Task] = []

    def _capture(coro, **_):
        t = asyncio.ensure_future(coro)
        created.append(t)
        return t

    hass.async_create_task = MagicMock(side_effect=_capture)
    hass._created_tasks = created
    return hass


def _make_bridge_with_relay(hass, entity_id="switch.lamp"):
    entry = _make_entry()
    bridge = SberBridge(hass, entry)
    bridge._mqtt_client = AsyncMock()
    bridge._mqtt_service.publish = AsyncMock()
    bridge._connected = True
    bridge._ack_audit.cancel()

    entity = RelayEntity({"entity_id": entity_id, "name": "Lamp"})
    entity.fill_by_ha_state({"entity_id": entity_id, "state": "off", "attributes": {}})
    bridge._entities[entity_id] = entity
    bridge._enabled_entity_ids = [entity_id]
    return bridge


async def _drain(hass):
    for t in list(getattr(hass, "_created_tasks", [])):
        if not t.done():
            with contextlib.suppress(TimeoutError, Exception):
                await asyncio.wait_for(t, timeout=5)


def _cmd(entity_id: str) -> bytes:
    return json.dumps(
        {
            "devices": {
                entity_id: {
                    "states": [
                        {"key": "on_off", "value": {"type": "BOOL", "bool_value": True}},
                    ],
                }
            }
        }
    ).encode()


class TestSberCommandTrace:
    """Sber command opens a trace and ha_service_call + publish_out attach to it."""

    async def test_full_cycle_produces_single_trace_with_all_events(self) -> None:
        hass = _make_hass()
        bridge = _make_bridge_with_relay(hass)

        with patch(
            "custom_components.sber_mqtt_bridge.sber_bridge.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            await bridge._handle_sber_command(_cmd("switch.lamp"))
            await _drain(hass)

        traces = bridge.trace_collector.snapshot()
        # Exactly one trace — multiple traces here would mean context.id
        # propagation broke and HA calls leaked into a separate trace.
        assert len(traces) == 1
        trace = traces[0]
        assert trace["trigger"] == "sber_command"
        assert "switch.lamp" in trace["entity_ids"]

        types = [e["type"] for e in trace["events"]]
        # sber_command opens, ha_service_call is the bridge reacting,
        # publish_out is the state confirmation flying back to Sber.
        assert "sber_command" in types
        assert "ha_service_call" in types
        assert "publish_out" in types

    async def test_service_call_event_carries_domain_and_service(self) -> None:
        hass = _make_hass()
        bridge = _make_bridge_with_relay(hass)
        with patch(
            "custom_components.sber_mqtt_bridge.sber_bridge.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            await bridge._handle_sber_command(_cmd("switch.lamp"))
            await _drain(hass)

        trace = bridge.trace_collector.snapshot()[0]
        svc_evs = [e for e in trace["events"] if e["type"] == "ha_service_call"]
        # Without domain/service the DevTools UI can't show what was called.
        assert svc_evs, "ha_service_call missing from trace"
        assert svc_evs[0]["payload"]["domain"] == "switch"
        assert svc_evs[0]["payload"]["service"] == "turn_on"


class TestSilentRejectionIntegration:
    """Silent-rejection audit must flip the trace status on the bridge."""

    async def test_silent_rejection_marks_active_trace_failed(self) -> None:
        hass = _make_hass()
        bridge = _make_bridge_with_relay(hass)

        with patch(
            "custom_components.sber_mqtt_bridge.sber_bridge.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            await bridge._handle_sber_command(_cmd("switch.lamp"))
            await _drain(hass)

        # Strip the entity from acknowledged set — simulates Sber never
        # responding to a published state (the whole point of the audit).
        bridge._stats.acknowledged_entities.discard("switch.lamp")
        with patch(
            "custom_components.sber_mqtt_bridge.sber_bridge.check_and_create_issues",
            new_callable=AsyncMock,
        ):
            bridge._run_ack_audit()
            await _drain(hass)

        trace = bridge.trace_collector.snapshot()[0]
        assert trace["status"] == "failed"
        # A specific silent_rejection event must be appended so DevTools
        # can render the red marker at the exact timeline position.
        assert any(e["type"] == "silent_rejection" for e in trace["events"])


class TestTraceCollectorExposedOnBridge:
    """Simple plumbing test — public API stable for WS consumers."""

    def test_bridge_exposes_trace_collector_property(self) -> None:
        hass = _make_hass()
        bridge = _make_bridge_with_relay(hass)
        # WS commands reach the collector through this one attribute.
        # Renaming it would break the whole DevTools panel.
        assert bridge.trace_collector is not None
        assert bridge.trace_collector.snapshot() == []
