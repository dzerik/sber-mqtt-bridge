"""Tests for the per-entity diagnose WebSocket command.

Guards the single payload shape the DevTools panel reads
(``{"report": {...}}``) and the error paths (missing bridge, unknown
entity_id still produces a valid broken-verdict report instead of a
send_error).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from custom_components.sber_mqtt_bridge.schema_validator import ValidationCollector
from custom_components.sber_mqtt_bridge.state_diff import DiffCollector
from custom_components.sber_mqtt_bridge.trace_collector import TraceCollector
from custom_components.sber_mqtt_bridge.websocket_api.diagnose import (
    ws_diagnose_entity,
)


def _bridge_clean() -> MagicMock:
    bridge = MagicMock()
    entity = MagicMock()
    entity.category = "light"
    entity.is_filled_by_state = True
    entity.get_final_features_list = MagicMock(return_value=["on_off", "online"])
    bridge._entities = {"light.x": entity}
    bridge._enabled_entity_ids = ["light.x"]
    bridge._linked_reverse = {}
    stats = MagicMock()
    stats.acknowledged_entities = {"light.x"}
    bridge._stats = stats
    bridge.trace_collector = TraceCollector()
    bridge.diff_collector = DiffCollector()
    bridge.validation_collector = ValidationCollector()
    return bridge


@pytest.fixture
def connection():
    conn = MagicMock()
    conn.send_result = MagicMock()
    conn.send_error = MagicMock()
    return conn


@pytest.fixture
def hass():
    return MagicMock()


class TestDiagnoseEntity:
    def test_clean_entity_returns_ok_verdict(self, hass, connection):
        with patch(
            "custom_components.sber_mqtt_bridge.websocket_api.diagnose.get_bridge",
            return_value=_bridge_clean(),
        ):
            ws_diagnose_entity(hass, connection, {"id": 1, "entity_id": "light.x"})
        payload = connection.send_result.call_args[0][1]
        assert "report" in payload
        # UI reads these three top-level fields.
        assert set(payload["report"].keys()) >= {"entity_id", "verdict", "findings", "summary"}
        assert payload["report"]["verdict"] == "ok"

    def test_unknown_entity_returns_broken_verdict_not_error(self, hass, connection):
        # Typing a non-existent entity_id is a legit diagnostic path —
        # we must return the "not_known_to_bridge" finding, not a
        # WebSocket error that hides the diagnosis from the user.
        with patch(
            "custom_components.sber_mqtt_bridge.websocket_api.diagnose.get_bridge",
            return_value=_bridge_clean(),
        ):
            ws_diagnose_entity(hass, connection, {"id": 2, "entity_id": "nope.nope"})
        payload = connection.send_result.call_args[0][1]
        assert payload["report"]["verdict"] == "broken"
        connection.send_error.assert_not_called()

    def test_missing_bridge_sends_error(self, hass, connection):
        with patch(
            "custom_components.sber_mqtt_bridge.websocket_api.diagnose.get_bridge",
            return_value=None,
        ):
            ws_diagnose_entity(hass, connection, {"id": 3, "entity_id": "light.x"})
        connection.send_error.assert_called_once()
        assert connection.send_error.call_args[0][1] == "bridge_not_found"
