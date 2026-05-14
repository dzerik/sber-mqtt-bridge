"""Tests for RedefinitionsStore — extracted from SberBridge in v1.38.4."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.sber_mqtt_bridge.const import (
    CONF_SBER_BROKER,
    CONF_SBER_LOGIN,
    CONF_SBER_PASSWORD,
    CONF_SBER_PORT,
)
from custom_components.sber_mqtt_bridge.redefinitions_store import RedefinitionsStore
from custom_components.sber_mqtt_bridge.sber_bridge import SberBridge


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
    bridge = SberBridge(hass, _make_entry())
    return bridge


class TestRedefinitionsStoreSkeleton:
    """Smoke tests — actual flush/persist behaviour moves in later tasks."""

    def test_bridge_owns_a_store(self) -> None:
        bridge = _make_bridge()
        assert isinstance(bridge._redef_store, RedefinitionsStore)

    def test_store_starts_empty(self) -> None:
        bridge = _make_bridge()
        assert bridge._redef_store.redefinitions == {}

    def test_redefinitions_property_returns_copy(self) -> None:
        bridge = _make_bridge()
        bridge._redef_store._redefinitions["foo"] = {"x": 1}
        snap = bridge._redef_store.redefinitions
        snap["bar"] = {"y": 2}
        assert "bar" not in bridge._redef_store._redefinitions
