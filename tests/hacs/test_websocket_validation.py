"""Tests for the schema-validation WebSocket commands.

Guards the shape of WS payloads the DevTools panel reads directly
(``recent`` / ``by_entity`` / ``issues`` / ``snapshot``).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from custom_components.sber_mqtt_bridge.schema_validator import (
    ValidationCollector,
    ValidationIssue,
)
from custom_components.sber_mqtt_bridge.websocket_api.validation import (
    ws_clear_validation_issues,
    ws_list_validation_issues,
    ws_subscribe_validation_issues,
)


def _seeded_bridge() -> MagicMock:
    bridge = MagicMock()
    bridge.validation_collector = ValidationCollector()
    issue = ValidationIssue(
        ts=0,
        entity_id="light.x",
        category="light",
        type="missing_obligatory",
        severity="error",
        key="online",
        description="online required",
        details={"missing": "online"},
    )
    bridge.validation_collector.record("light.x", [issue])
    return bridge


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


class TestListValidationIssues:
    def test_returns_recent_and_by_entity(self, hass, connection):
        bridge = _seeded_bridge()
        with patch(
            "custom_components.sber_mqtt_bridge.websocket_api.validation.get_bridge",
            return_value=bridge,
        ):
            ws_list_validation_issues(hass, connection, {"id": 1})
        payload = connection.send_result.call_args[0][1]
        # Both views returned in one round-trip — splitting would force
        # the UI to correlate them on its own.
        assert "recent" in payload
        assert "by_entity" in payload
        assert payload["by_entity"]["light.x"][0]["severity"] == "error"

    def test_missing_bridge_sends_error(self, hass, connection):
        with patch(
            "custom_components.sber_mqtt_bridge.websocket_api.validation.get_bridge",
            return_value=None,
        ):
            ws_list_validation_issues(hass, connection, {"id": 1})
        connection.send_error.assert_called_once()


class TestClearValidationIssues:
    def test_clear_empties_collector(self, hass, connection):
        bridge = _seeded_bridge()
        with patch(
            "custom_components.sber_mqtt_bridge.websocket_api.validation.get_bridge",
            return_value=bridge,
        ):
            ws_clear_validation_issues(hass, connection, {"id": 2})
        snap = bridge.validation_collector.snapshot()
        assert snap == {"recent": [], "by_entity": {}}


class TestSubscribeValidationIssues:
    def test_subscribe_sends_snapshot_then_live(self, hass, connection):
        bridge = _seeded_bridge()
        with patch(
            "custom_components.sber_mqtt_bridge.websocket_api.validation.get_bridge",
            return_value=bridge,
        ):
            ws_subscribe_validation_issues(hass, connection, {"id": 3})
            # Emit a fresh batch — subscriber must see it as {"issues": [...]}.
            issue = ValidationIssue(
                ts=0,
                entity_id="light.y",
                category="light",
                type="type_mismatch",
                severity="error",
                key="on_off",
                description="wrong type",
                details={"expected": "BOOL", "actual": "INTEGER"},
            )
            bridge.validation_collector.record("light.y", [issue])

        # One snapshot + one live batch.
        assert connection.send_message.call_count >= 2
        # Subscription tracked for HA auto-unsub.
        assert 3 in connection.subscriptions
