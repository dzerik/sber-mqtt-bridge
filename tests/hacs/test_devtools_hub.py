"""Tests for DevToolsHub — extracted from SberBridge in v1.38.5."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.sber_mqtt_bridge.const import (
    CONF_SBER_BROKER,
    CONF_SBER_LOGIN,
    CONF_SBER_PASSWORD,
    CONF_SBER_PORT,
)
from custom_components.sber_mqtt_bridge.devtools_hub import DevToolsHub
from custom_components.sber_mqtt_bridge.message_logger import MessageLogger
from custom_components.sber_mqtt_bridge.sber_bridge import SberBridge
from custom_components.sber_mqtt_bridge.schema_validator import ValidationCollector
from custom_components.sber_mqtt_bridge.state_diff import DiffCollector
from custom_components.sber_mqtt_bridge.trace_collector import TraceCollector


def _make_entry() -> MagicMock:
    entry = MagicMock()
    entry.data = {
        CONF_SBER_LOGIN: "test",
        CONF_SBER_PASSWORD: "pass",
        CONF_SBER_BROKER: "broker.test",
        CONF_SBER_PORT: 8883,
    }
    entry.options = {}
    return entry


def _make_bridge() -> SberBridge:
    hass = MagicMock()
    hass.config.location_name = "My Home"
    return SberBridge(hass, _make_entry())


class TestDevToolsHubSkeleton:
    """Smoke tests for the new hub."""

    def test_bridge_owns_a_hub(self) -> None:
        bridge = _make_bridge()
        assert isinstance(bridge._devtools, DevToolsHub)

    def test_hub_holds_four_collectors(self) -> None:
        bridge = _make_bridge()
        hub = bridge._devtools
        assert isinstance(hub.message_logger, MessageLogger)
        assert isinstance(hub.trace_collector, TraceCollector)
        assert isinstance(hub.diff_collector, DiffCollector)
        assert isinstance(hub.validation_collector, ValidationCollector)

    def test_resize_propagates_to_all_collectors(self) -> None:
        hub = DevToolsHub(message_log_size=50)
        hub.resize(200)
        # Each collector's maxlen should now be 200; we sample one as a smoke check.
        assert hub.message_logger._log.maxlen == 200  # type: ignore[attr-defined]

    def test_log_message_appends_entry(self) -> None:
        hub = DevToolsHub(message_log_size=10)
        hub.log_message("out", "test/topic", "{}")
        assert len(hub.message_log) == 1

    def test_clear_message_log_empties_buffer(self) -> None:
        hub = DevToolsHub(message_log_size=10)
        hub.log_message("out", "t", "{}")
        hub.clear_message_log()
        assert hub.message_log == []
