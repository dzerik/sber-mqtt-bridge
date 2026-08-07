"""Tests for ``async_setup_entry`` rollback semantics.

``SberBridge.async_start()`` is irreversible bookkeeping: it loads
entities, subscribes to ``state_changed`` and starts the MQTT connection
loop.  Everything registered *after* it (WebSocket API, static panel path,
sidebar panel) can still fail, and HA would then mark the entry as failed
while the bridge kept publishing to Sber — and start a *second* bridge on
the next setup retry.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sber_mqtt_bridge import async_setup_entry
from custom_components.sber_mqtt_bridge.const import (
    CONF_SBER_BROKER,
    CONF_SBER_LOGIN,
    CONF_SBER_PASSWORD,
    CONF_SBER_PORT,
    DOMAIN,
)

MOCK_DATA = {
    CONF_SBER_LOGIN: "test_user",
    CONF_SBER_PASSWORD: "test_pass",
    CONF_SBER_BROKER: "mqtt-partners.iot.sberdevices.ru",
    CONF_SBER_PORT: 8883,
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations in all tests."""
    return


@pytest.fixture
def fake_bridge():
    """Replace SberBridge with a mock exposing async start/stop."""
    bridge = MagicMock()
    bridge.async_start = AsyncMock()
    bridge.async_stop = AsyncMock()
    with patch("custom_components.sber_mqtt_bridge.SberBridge", return_value=bridge):
        yield bridge


@pytest.fixture
def fake_http(hass: HomeAssistant):
    """Provide a stub ``hass.http`` so static path registration succeeds."""
    http = MagicMock()
    http.async_register_static_paths = AsyncMock()
    hass.http = http
    return http


def _entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, data=MOCK_DATA, unique_id="test_user")
    entry.add_to_hass(hass)
    return entry


@pytest.mark.asyncio(loop_scope="function")
async def test_setup_registers_panel_and_keeps_bridge(hass: HomeAssistant, fake_bridge, fake_http) -> None:
    """Happy path: the bridge is started, kept, and the panel is registered."""
    entry = _entry(hass)

    with patch("custom_components.sber_mqtt_bridge.async_register_built_in_panel") as panel:
        assert await async_setup_entry(hass, entry) is True

    fake_bridge.async_start.assert_awaited_once()
    fake_bridge.async_stop.assert_not_awaited()
    fake_http.async_register_static_paths.assert_awaited_once()
    assert panel.call_args.kwargs["frontend_url_path"] == "sber-mqtt-bridge"
    assert panel.call_args.kwargs["require_admin"] is True
    assert entry.runtime_data.bridge is fake_bridge


@pytest.mark.asyncio(loop_scope="function")
async def test_panel_failure_stops_the_bridge(hass: HomeAssistant, fake_bridge, fake_http) -> None:
    """A failing sidebar registration must stop the already-started bridge."""
    entry = _entry(hass)

    with (
        patch(
            "custom_components.sber_mqtt_bridge.async_register_built_in_panel",
            side_effect=ValueError("Overwriting panel sber-mqtt-bridge"),
        ),
        pytest.raises(ConfigEntryNotReady),
    ):
        await async_setup_entry(hass, entry)

    fake_bridge.async_start.assert_awaited_once()
    fake_bridge.async_stop.assert_awaited_once()


@pytest.mark.asyncio(loop_scope="function")
async def test_static_path_failure_stops_the_bridge(hass: HomeAssistant, fake_bridge, fake_http) -> None:
    """The rollback also covers the earlier static-path registration."""
    entry = _entry(hass)
    fake_http.async_register_static_paths.side_effect = RuntimeError("http not ready")

    with pytest.raises(ConfigEntryNotReady):
        await async_setup_entry(hass, entry)

    fake_bridge.async_stop.assert_awaited_once()


@pytest.mark.asyncio(loop_scope="function")
async def test_bridge_start_failure_is_not_masked(hass: HomeAssistant, fake_bridge, fake_http) -> None:
    """Failures of ``async_start`` itself propagate unchanged.

    The rollback guard must not widen its scope over the start call, or a
    half-started bridge would be stopped twice and the original error type
    would be lost.
    """
    entry = _entry(hass)
    fake_bridge.async_start.side_effect = OSError("broker unreachable")

    with (
        patch("custom_components.sber_mqtt_bridge.async_register_built_in_panel"),
        pytest.raises(OSError, match="broker unreachable"),
    ):
        await async_setup_entry(hass, entry)

    fake_bridge.async_stop.assert_not_awaited()
