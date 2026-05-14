"""Tests for SberPublisher — the publish coordinator extracted from SberBridge."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.sber_mqtt_bridge.const import (
    CONF_SBER_BROKER,
    CONF_SBER_LOGIN,
    CONF_SBER_PASSWORD,
    CONF_SBER_PORT,
)
from custom_components.sber_mqtt_bridge.sber_bridge import SberBridge
from custom_components.sber_mqtt_bridge.sber_publisher import SberPublisher


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
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock()
    bridge = SberBridge(hass, _make_entry())
    bridge._mqtt_client = AsyncMock()
    bridge._mqtt_service.publish = AsyncMock()
    bridge._connected = True
    return bridge


class TestSberPublisherSkeleton:
    """Smoke tests for the new publisher class — actual publish logic moves in
    later tasks of v1.38.3."""

    def test_bridge_owns_a_publisher_instance(self) -> None:
        """SberBridge constructs a SberPublisher in __init__."""
        bridge = _make_bridge()
        assert isinstance(bridge._publisher, SberPublisher)

    def test_publisher_holds_back_reference(self) -> None:
        """The publisher's bridge reference points back to its parent."""
        bridge = _make_bridge()
        assert bridge._publisher._bridge is bridge

    def test_last_config_publish_time_starts_none(self) -> None:
        """No publish yet → no recorded timestamp."""
        bridge = _make_bridge()
        assert bridge._publisher.last_config_publish_time is None
