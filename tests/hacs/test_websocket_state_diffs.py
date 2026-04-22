"""Tests for the state-diff WebSocket commands.

Protect the contract between the DevTools panel and the bridge: the
payload shape (``diffs``, ``diff``, ``snapshot``) and error codes are
what the UI reads directly.  A silent rename here breaks the panel
with no pytest failure elsewhere.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from custom_components.sber_mqtt_bridge.state_diff import DiffCollector
from custom_components.sber_mqtt_bridge.websocket_api.diffs import (
    ws_clear_state_diffs,
    ws_list_state_diffs,
    ws_subscribe_state_diffs,
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


def _prime_bridge_with_diff() -> MagicMock:
    bridge = MagicMock()
    bridge.diff_collector = DiffCollector(include_initial=True)
    bridge.diff_collector.update("light.x", [{"key": "on_off", "value": {"type": "BOOL", "bool_value": True}}])
    return bridge


class TestListStateDiffs:
    def test_returns_snapshot(self, hass, connection):
        bridge = _prime_bridge_with_diff()
        with patch(
            "custom_components.sber_mqtt_bridge.websocket_api.diffs.get_bridge",
            return_value=bridge,
        ):
            ws_list_state_diffs(hass, connection, {"id": 1})
        payload = connection.send_result.call_args[0][1]
        assert "diffs" in payload
        assert payload["diffs"][0]["entity_id"] == "light.x"

    def test_missing_bridge_sends_error(self, hass, connection):
        with patch(
            "custom_components.sber_mqtt_bridge.websocket_api.diffs.get_bridge",
            return_value=None,
        ):
            ws_list_state_diffs(hass, connection, {"id": 1})
        connection.send_error.assert_called_once()


class TestClearStateDiffs:
    def test_clears_collector(self, hass, connection):
        bridge = _prime_bridge_with_diff()
        with patch(
            "custom_components.sber_mqtt_bridge.websocket_api.diffs.get_bridge",
            return_value=bridge,
        ):
            ws_clear_state_diffs(hass, connection, {"id": 2})
        assert bridge.diff_collector.snapshot() == []


class TestSubscribeStateDiffs:
    def test_subscribe_sends_snapshot_then_live_updates(self, hass, connection):
        bridge = _prime_bridge_with_diff()
        with patch(
            "custom_components.sber_mqtt_bridge.websocket_api.diffs.get_bridge",
            return_value=bridge,
        ):
            ws_subscribe_state_diffs(hass, connection, {"id": 3})
            # A subsequent real change must reach the subscriber.
            bridge.diff_collector.update(
                "light.x",
                [{"key": "on_off", "value": {"type": "BOOL", "bool_value": False}}],
            )

        # One initial snapshot + one live diff.
        assert connection.send_message.call_count >= 2
        # Subscription tracked for HA auto-unsub on disconnect.
        assert 3 in connection.subscriptions
