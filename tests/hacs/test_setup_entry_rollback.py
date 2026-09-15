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
from homeassistant.exceptions import ConfigEntryError, ConfigEntryNotReady
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sber_mqtt_bridge import ACTIVE_ENTRY_KEY, PLATFORMS, async_setup_entry, async_unload_entry
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
    bridge.async_connect = AsyncMock()
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

    with (
        patch("custom_components.sber_mqtt_bridge.async_register_built_in_panel") as panel,
        patch.object(hass.config_entries, "async_forward_entry_setups", AsyncMock()) as forward,
    ):
        assert await async_setup_entry(hass, entry) is True

    # The bridge's own diagnostic entities are set up with it.
    forward.assert_awaited_once_with(entry, PLATFORMS)

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
    """Failures of ``async_start`` itself propagate unchanged, and the bridge is stopped once.

    The setup's connection check has already opened the MQTT session the
    bridge runs on, so a failing start must not leave it open; the original
    error type must still reach HA.
    """
    entry = _entry(hass)
    fake_bridge.async_start.side_effect = OSError("broker unreachable")

    with (
        patch("custom_components.sber_mqtt_bridge.async_register_built_in_panel"),
        pytest.raises(OSError, match="broker unreachable"),
    ):
        await async_setup_entry(hass, entry)

    fake_bridge.async_stop.assert_awaited_once()
    assert ACTIVE_ENTRY_KEY not in hass.data[DOMAIN]


@pytest.mark.asyncio(loop_scope="function")
async def test_failing_stop_does_not_mask_start_failure(
    hass: HomeAssistant, fake_bridge, fake_http, caplog: pytest.LogCaptureFixture
) -> None:
    """A rollback stop that raises is logged; HA still gets the start error."""
    entry = _entry(hass)
    fake_bridge.async_start.side_effect = OSError("storage broken")
    fake_bridge.async_stop.side_effect = RuntimeError("stop broken")

    with pytest.raises(OSError, match="storage broken"):
        await async_setup_entry(hass, entry)

    assert "after a failed start raised" in caplog.text


# ---------------------------------------------------------------------------
# Single config entry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio(loop_scope="function")
async def test_extra_entry_fails_setup_with_explanation(
    hass: HomeAssistant, fake_bridge, fake_http, caplog: pytest.LogCaptureFixture
) -> None:
    """An installation that still has two entries runs one bridge, not a retry loop.

    ``single_config_entry`` only stops HA from creating new entries; existing
    extra entries are still set up.  The extra one must fail permanently
    (``ConfigEntryError`` — no retries) with a clear message, and must not
    start a bridge or touch the panel of the running entry.
    """
    first = _entry(hass)
    second = MockConfigEntry(domain=DOMAIN, data={**MOCK_DATA, CONF_SBER_LOGIN: "other"}, unique_id="other")
    second.add_to_hass(hass)

    with (
        patch("custom_components.sber_mqtt_bridge.async_register_built_in_panel") as panel,
        patch.object(hass.config_entries, "async_forward_entry_setups", AsyncMock()),
    ):
        assert await async_setup_entry(hass, first) is True
        with pytest.raises(ConfigEntryError) as err:
            await async_setup_entry(hass, second)

    assert err.value.translation_key == "single_entry_only"
    assert err.value.translation_placeholders == {"active": first.title}
    assert "supports a single config entry" in caplog.text
    fake_bridge.async_start.assert_awaited_once()
    panel.assert_called_once()


@pytest.mark.asyncio(loop_scope="function")
async def test_single_entry_claim_is_released_on_unload_and_failures(
    hass: HomeAssistant, fake_bridge, fake_http
) -> None:
    """Unloading (e.g. the reload after reauth) or a failed setup frees the slot."""
    entry = _entry(hass)

    fake_bridge.async_start.side_effect = OSError("broker unreachable")
    with pytest.raises(OSError, match="broker unreachable"):
        await async_setup_entry(hass, entry)
    assert ACTIVE_ENTRY_KEY not in hass.data[DOMAIN]
    fake_bridge.async_start.side_effect = None

    with (
        patch(
            "custom_components.sber_mqtt_bridge.async_register_built_in_panel",
            side_effect=ValueError("Overwriting panel sber-mqtt-bridge"),
        ),
        pytest.raises(ConfigEntryNotReady),
    ):
        await async_setup_entry(hass, entry)
    assert ACTIVE_ENTRY_KEY not in hass.data[DOMAIN]

    with (
        patch("custom_components.sber_mqtt_bridge.async_register_built_in_panel"),
        patch("custom_components.sber_mqtt_bridge.async_remove_panel"),
        patch.object(hass.config_entries, "async_forward_entry_setups", AsyncMock()),
        patch.object(hass.config_entries, "async_unload_platforms", AsyncMock(return_value=True)),
    ):
        assert await async_setup_entry(hass, entry) is True
        assert hass.data[DOMAIN][ACTIVE_ENTRY_KEY] == entry.entry_id
        assert await async_unload_entry(hass, entry) is True
    assert ACTIVE_ENTRY_KEY not in hass.data[DOMAIN]

    # Another entry can now take over.
    other = MockConfigEntry(domain=DOMAIN, data={**MOCK_DATA, CONF_SBER_LOGIN: "other"}, unique_id="other")
    other.add_to_hass(hass)
    with (
        patch("custom_components.sber_mqtt_bridge.async_register_built_in_panel"),
        patch.object(hass.config_entries, "async_forward_entry_setups", AsyncMock()),
    ):
        assert await async_setup_entry(hass, other) is True
