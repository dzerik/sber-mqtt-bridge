"""Tests for Sber MQTT Bridge diagnostics."""

import json
from unittest.mock import MagicMock

import pytest
from homeassistant.core import HomeAssistant

from custom_components.sber_mqtt_bridge.const import (
    CONF_SBER_BROKER,
    CONF_SBER_LOGIN,
    CONF_SBER_PASSWORD,
    CONF_SBER_PORT,
)
from custom_components.sber_mqtt_bridge.diagnostics import (
    async_get_config_entry_diagnostics,
)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations in all tests."""
    return


@pytest.mark.asyncio(loop_scope="function")
async def test_diagnostics_redacts_password(hass: HomeAssistant) -> None:
    """Test that the password is redacted in diagnostics output."""
    mock_bridge = MagicMock()
    mock_bridge.is_connected = True
    mock_bridge.entities_count = 1
    mock_bridge.enabled_entity_ids = ["light.room"]
    mock_bridge.redefinitions = {}

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

    # Login must be redacted too: it doubles as the MQTT username AND the
    # root topic segment (sberdevices/v1/<login>/...), and diagnostics are
    # routinely attached to public GitHub issues (review remediation).
    assert result["entry_data"][CONF_SBER_LOGIN] == "**REDACTED**"
    # Whole-report check, not just entry_data: any future branch that starts
    # echoing the entry title, an MQTT topic or the raw credentials fails here.
    assert "test_user" not in json.dumps(result, default=str)

    # Non-secret data preserved
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
    mock_bridge.entities_count = 0
    mock_bridge.enabled_entity_ids = []
    mock_bridge.redefinitions = {}

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


def _bridge_with_devtools(login: str) -> MagicMock:
    """A bridge whose DevTools collectors hold real traffic mentioning the login."""
    from custom_components.sber_mqtt_bridge.devtools_hub import DevToolsHub

    hub = DevToolsHub(message_log_size=500)
    topic = f"sberdevices/v1/{login}/down/commands"
    for i in range(150):
        hub.log_message("in", topic, json.dumps({"devices": {"light.room": {"n": i, "pad": "x" * 3000}}}))
    hub.trace_collector.begin(trace_id="t1", trigger="sber_command", entity_ids=["light.room"], topic=topic)
    hub.command_confirm.record_command("light.room", [{"key": "on_off", "value": {"type": "BOOL", "bool_value": True}}])

    bridge = MagicMock()
    bridge.is_connected = True
    bridge.entities_count = 0
    bridge.entities = {}
    bridge.enabled_entity_ids = []
    bridge.redefinitions = {}
    bridge.stats = {"last_error_detail": f"403 for {login}"}
    bridge.message_log = hub.message_log
    bridge.trace_collector = hub.trace_collector
    bridge.diff_collector = hub.diff_collector
    bridge.validation_collector = hub.validation_collector
    bridge.command_confirm = hub.command_confirm
    return bridge


@pytest.mark.asyncio(loop_scope="function")
async def test_diagnostics_carries_devtools_for_bug_reports(hass: HomeAssistant) -> None:
    """A bug report needs the recent traffic, not only the configuration.

    Until now the user had to screenshot DevTools tab by tab (issue #63);
    the diagnostics file itself carried none of it.
    """
    entry = MagicMock()
    entry.data = {CONF_SBER_LOGIN: "acc-login-42", CONF_SBER_PASSWORD: "pw-secret-77"}
    entry.options = {}
    entry.runtime_data = MagicMock(bridge=_bridge_with_devtools("acc-login-42"))

    result = await async_get_config_entry_diagnostics(hass, entry)

    devtools = result["devtools"]
    assert len(devtools["message_log"]) == 100, "only the most recent messages"
    assert devtools["message_log"][-1]["payload"].startswith('{"devices": {"light.room": {"n": 149')
    assert all(len(m["payload"]) <= 2000 + len("…[truncated]") for m in devtools["message_log"])
    assert devtools["traces"][0]["trace_id"] == "t1"
    assert devtools["command_confirmations"][0]["entity_id"] == "light.room"
    assert "state_diffs" in devtools
    assert "validation" in devtools

    dumped = json.dumps(result, default=str)
    assert "acc-login-42" not in dumped, "the login is in every MQTT topic and must be scrubbed everywhere"
    assert "pw-secret-77" not in dumped
    assert "sberdevices/v1/**REDACTED**/down/commands" in dumped
