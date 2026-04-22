"""Tests for the correlation-timeline WebSocket commands.

The WS surface is what the DevTools panel talks to, so these tests
guard the shape of the response payloads (``traces``, ``trace``,
``snapshot``, ``kind``) — renaming any of those fields silently breaks
the frontend without a pytest failure elsewhere.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from custom_components.sber_mqtt_bridge.trace_collector import TraceCollector
from custom_components.sber_mqtt_bridge.websocket_api.traces import (
    ws_clear_traces,
    ws_get_trace,
    ws_list_traces,
    ws_subscribe_traces,
)


@pytest.fixture
def connection():
    conn = MagicMock()
    conn.send_result = MagicMock()
    conn.send_error = MagicMock()
    conn.send_message = MagicMock()
    conn.subscriptions = {}
    return conn


@pytest.fixture
def hass():
    return MagicMock()


def _bridge_with_collector() -> MagicMock:
    bridge = MagicMock()
    bridge.trace_collector = TraceCollector()
    return bridge


class TestListTraces:
    def test_returns_snapshot(self, hass, connection):
        bridge = _bridge_with_collector()
        bridge.trace_collector.begin(trace_id="c", trigger="sber_command", entity_ids=["light.x"])
        with patch(
            "custom_components.sber_mqtt_bridge.websocket_api.traces.get_bridge",
            return_value=bridge,
        ):
            ws_list_traces(hass, connection, {"id": 1, "include_active": True})
        # The panel renders the returned array directly; missing "traces" key
        # means the UI sees undefined and shows an empty timeline.
        payload = connection.send_result.call_args[0][1]
        assert "traces" in payload
        assert len(payload["traces"]) == 1
        assert payload["traces"][0]["trigger"] == "sber_command"

    def test_bridge_missing_sends_error(self, hass, connection):
        with patch(
            "custom_components.sber_mqtt_bridge.websocket_api.traces.get_bridge",
            return_value=None,
        ):
            ws_list_traces(hass, connection, {"id": 1, "include_active": True})
        connection.send_error.assert_called_once()


class TestGetTrace:
    def test_returns_single_trace(self, hass, connection):
        bridge = _bridge_with_collector()
        bridge.trace_collector.begin(trace_id="abc", trigger="sber_command", entity_ids=["light.x"])
        with patch(
            "custom_components.sber_mqtt_bridge.websocket_api.traces.get_bridge",
            return_value=bridge,
        ):
            ws_get_trace(hass, connection, {"id": 2, "trace_id": "abc"})
        payload = connection.send_result.call_args[0][1]
        assert payload["trace"]["trace_id"] == "abc"

    def test_unknown_trace_id_sends_trace_not_found(self, hass, connection):
        bridge = _bridge_with_collector()
        with patch(
            "custom_components.sber_mqtt_bridge.websocket_api.traces.get_bridge",
            return_value=bridge,
        ):
            ws_get_trace(hass, connection, {"id": 3, "trace_id": "nope"})
        # Generic "unknown error" leaves the user guessing; the explicit
        # code lets the UI show "Trace no longer available".
        err = connection.send_error.call_args
        assert err[0][1] == "trace_not_found"


class TestClearTraces:
    def test_clears_collector(self, hass, connection):
        bridge = _bridge_with_collector()
        bridge.trace_collector.begin(trace_id="c", trigger="sber_command", entity_ids=["light.x"])
        with patch(
            "custom_components.sber_mqtt_bridge.websocket_api.traces.get_bridge",
            return_value=bridge,
        ):
            ws_clear_traces(hass, connection, {"id": 4})
        assert bridge.trace_collector.snapshot() == []


class TestSubscribeTraces:
    def test_subscribe_sends_initial_snapshot_and_live_updates(self, hass, connection):
        bridge = _bridge_with_collector()
        bridge.trace_collector.begin(trace_id="seed", trigger="sber_command", entity_ids=["light.x"])
        with patch(
            "custom_components.sber_mqtt_bridge.websocket_api.traces.get_bridge",
            return_value=bridge,
        ):
            ws_subscribe_traces(hass, connection, {"id": 5})
            # First live event after subscribe must reach the frontend.
            bridge.trace_collector.record("seed", type_="ha_service_call", entity_id="light.x")

        # Two messages: the initial snapshot and the trace_updated event.
        assert connection.send_message.call_count >= 2
        # Subscription handle recorded so HA can auto-unsub on disconnect.
        assert 5 in connection.subscriptions
