"""Tests for Sber MQTT Bridge diagnostics."""

from unittest.mock import MagicMock, patch

import pytest

from homeassistant.core import HomeAssistant

from custom_components.sber_mqtt_bridge.const import (
    CONF_SBER_BROKER,
    CONF_SBER_LOGIN,
    CONF_SBER_PASSWORD,
    CONF_SBER_PORT,
    DOMAIN,
)
from custom_components.sber_mqtt_bridge.diagnostics import (
    async_get_config_entry_diagnostics,
)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations in all tests."""
    yield


@pytest.mark.asyncio(loop_scope="function")
async def test_diagnostics_redacts_password(hass: HomeAssistant) -> None:
    """Test that the password is redacted in diagnostics output."""
    mock_bridge = MagicMock()
    mock_bridge.is_connected = True
    mock_bridge._entities = {"light.room": MagicMock()}
    mock_bridge._enabled_entity_ids = ["light.room"]
    mock_bridge._redefinitions = {}

    mock_runtime_data = MagicMock()
    mock_runtime_data.bridge = mock_bridge

    mock_entry = MagicMock()
    mock_entry.data = {
        CONF_SBER_LOGIN: "test_user",
        CONF_SBER_PASSWORD: "super_secret_password",
        CONF_SBER_BROKER: "mqtt-partners.iot.sberdevices.ru",
        CONF_SBER_PORT: 8883,
    }
    mock_entry.options = {"exposed_entities": ["light.room"]}
    mock_entry.runtime_data = mock_runtime_data

    result = await async_get_config_entry_diagnostics(hass, mock_entry)

    # Password must be redacted
    assert result["entry_data"][CONF_SBER_PASSWORD] == "**REDACTED**"

    # Other data preserved
    assert result["entry_data"][CONF_SBER_LOGIN] == "test_user"
    assert result["entry_data"][CONF_SBER_BROKER] == "mqtt-partners.iot.sberdevices.ru"

    # Bridge info present
    assert result["bridge"]["connected"] is True
    assert result["bridge"]["entities_loaded"] == 1
    assert result["bridge"]["enabled_entity_ids"] == ["light.room"]

    # Options preserved
    assert result["options"]["exposed_entities"] == ["light.room"]


@pytest.mark.asyncio(loop_scope="function")
async def test_diagnostics_disconnected_bridge(hass: HomeAssistant) -> None:
    """Test diagnostics with a disconnected bridge."""
    mock_bridge = MagicMock()
    mock_bridge.is_connected = False
    mock_bridge._entities = {}
    mock_bridge._enabled_entity_ids = []
    mock_bridge._redefinitions = {}

    mock_runtime_data = MagicMock()
    mock_runtime_data.bridge = mock_bridge

    mock_entry = MagicMock()
    mock_entry.data = {
        CONF_SBER_LOGIN: "user",
        CONF_SBER_PASSWORD: "pass",
    }
    mock_entry.options = {}
    mock_entry.runtime_data = mock_runtime_data

    result = await async_get_config_entry_diagnostics(hass, mock_entry)

    assert result["bridge"]["connected"] is False
    assert result["bridge"]["entities_loaded"] == 0
