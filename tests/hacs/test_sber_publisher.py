"""Tests for SberPublisher — the publish coordinator extracted from SberBridge."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

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


class TestSberPublisherWiring:
    """The bridge delegates its publish flows to a :class:`SberPublisher`.

    Behavioural coverage of the publish flows themselves lives in
    ``test_publisher_forwarder.py``.
    """

    def test_bridge_owns_a_publisher_instance(self) -> None:
        """SberBridge constructs a SberPublisher in __init__."""
        bridge = _make_bridge()
        assert isinstance(bridge._publisher, SberPublisher)

    def test_last_config_publish_time_starts_none(self) -> None:
        """No publish yet → no recorded timestamp."""
        bridge = _make_bridge()
        assert bridge._publisher.last_config_publish_time is None

    def test_bridge_proxy_reflects_publisher_timestamp(self) -> None:
        """``bridge._last_config_publish_time`` reads through to the publisher."""
        bridge = _make_bridge()
        bridge._publisher._last_config_publish_time = 1234.5
        assert bridge._last_config_publish_time == 1234.5

    def test_bridge_proxy_writes_through_to_the_publisher(self) -> None:
        """The backward-compat setter must not shadow the publisher's field."""
        bridge = _make_bridge()
        bridge._last_config_publish_time = 99.0
        assert bridge._publisher.last_config_publish_time == 99.0
