"""Tests for the Sber MQTT Bridge config flow."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import aiomqtt
import pytest
from aiomqtt.exceptions import MqttConnectError
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from paho.mqtt.client import convert_connack_rc_to_reason_code
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sber_mqtt_bridge.config_flow import _validate_sber_connection
from custom_components.sber_mqtt_bridge.const import (
    CONF_SBER_BROKER,
    CONF_SBER_LOGIN,
    CONF_SBER_PASSWORD,
    CONF_SBER_PORT,
    DOMAIN,
    SBER_BROKER_DEFAULT,
    SBER_PORT_DEFAULT,
)

MOCK_USER_INPUT = {
    CONF_SBER_LOGIN: "test_user",
    CONF_SBER_PASSWORD: "test_pass",
    CONF_SBER_BROKER: SBER_BROKER_DEFAULT,
    CONF_SBER_PORT: SBER_PORT_DEFAULT,
    "sber_verify_ssl": True,
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations in all tests."""
    return


@pytest.mark.asyncio(loop_scope="function")
async def test_show_user_form(hass: HomeAssistant) -> None:
    """Test that the user form is shown."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {}


@pytest.mark.asyncio(loop_scope="function")
@patch(
    "custom_components.sber_mqtt_bridge.config_flow._validate_sber_connection",
    return_value=None,
)
async def test_create_entry_success(mock_validate, hass: HomeAssistant) -> None:
    """Test successful entry creation."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})

    result = await hass.config_entries.flow.async_configure(result["flow_id"], MOCK_USER_INPUT)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Sber (test_user)"
    assert result["data"] == MOCK_USER_INPUT


@pytest.mark.asyncio(loop_scope="function")
@patch(
    "custom_components.sber_mqtt_bridge.config_flow._validate_sber_connection",
    return_value="cannot_connect",
)
async def test_connection_error(mock_validate, hass: HomeAssistant) -> None:
    """Test connection error shows form with error."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})

    result = await hass.config_entries.flow.async_configure(result["flow_id"], MOCK_USER_INPUT)

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


@pytest.mark.asyncio(loop_scope="function")
@patch(
    "custom_components.sber_mqtt_bridge.config_flow._validate_sber_connection",
    return_value="invalid_auth",
)
async def test_auth_error(mock_validate, hass: HomeAssistant) -> None:
    """Test auth error shows form with error."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})

    result = await hass.config_entries.flow.async_configure(result["flow_id"], MOCK_USER_INPUT)

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


@pytest.mark.asyncio(loop_scope="function")
async def test_second_user_flow_aborts_single_instance(hass: HomeAssistant) -> None:
    """The integration supports one config entry: a second setup is refused up front."""
    MockConfigEntry(domain=DOMAIN, data=MOCK_USER_INPUT, unique_id="test_user").add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


@pytest.fixture
def no_real_setup():
    """Keep the automatic reload after reauth from starting a real bridge."""
    with (
        patch("custom_components.sber_mqtt_bridge.async_setup_entry", return_value=True),
        patch("custom_components.sber_mqtt_bridge.async_unload_entry", return_value=True),
    ):
        yield


@pytest.mark.asyncio(loop_scope="function")
async def test_reauth_updates_only_the_password(hass: HomeAssistant, no_real_setup) -> None:
    """Reauth revalidates with the stored login and rewrites the password only."""
    entry = MockConfigEntry(domain=DOMAIN, data=MOCK_USER_INPUT, unique_id="test_user")
    entry.add_to_hass(hass)

    with patch(
        "custom_components.sber_mqtt_bridge.config_flow._validate_sber_connection",
        return_value=None,
    ) as validate:
        result = await entry.start_reauth_flow(hass)
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "reauth_confirm"

        result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_SBER_PASSWORD: "new_pass"})
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    # The new password is validated against the *stored* login/broker.
    assert validate.call_args.args[1] == "test_user"
    assert validate.call_args.args[2] == "new_pass"
    assert entry.data[CONF_SBER_PASSWORD] == "new_pass"
    assert entry.data[CONF_SBER_LOGIN] == "test_user"


@pytest.mark.asyncio(loop_scope="function")
async def test_reauth_rejects_wrong_password(hass: HomeAssistant, no_real_setup) -> None:
    """A failing revalidation re-shows the form and keeps the old password."""
    entry = MockConfigEntry(domain=DOMAIN, data=MOCK_USER_INPUT, unique_id="test_user")
    entry.add_to_hass(hass)

    with patch(
        "custom_components.sber_mqtt_bridge.config_flow._validate_sber_connection",
        return_value="invalid_auth",
    ):
        result = await entry.start_reauth_flow(hass)
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_SBER_PASSWORD: "still_wrong"})

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}
    assert entry.data[CONF_SBER_PASSWORD] == "test_pass"


@pytest.mark.asyncio(loop_scope="function")
async def test_reauth_success_reloads_the_entry(hass: HomeAssistant) -> None:
    """A successful reauth restarts the bridge so the new password is used."""
    entry = MockConfigEntry(domain=DOMAIN, data=MOCK_USER_INPUT, unique_id="test_user")
    entry.add_to_hass(hass)

    with (
        patch("custom_components.sber_mqtt_bridge.async_setup_entry", return_value=True) as setup,
        patch("custom_components.sber_mqtt_bridge.async_unload_entry", return_value=True) as unload,
        patch(
            "custom_components.sber_mqtt_bridge.config_flow._validate_sber_connection",
            return_value=None,
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert setup.call_count == 1

        result = await entry.start_reauth_flow(hass)
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_SBER_PASSWORD: "new_pass"})
        await hass.async_block_till_done()

    assert result["reason"] == "reauth_successful"
    assert unload.call_count == 1
    assert setup.call_count == 2
    assert entry.state is config_entries.ConfigEntryState.LOADED
    assert hass.config_entries.flow.async_progress() == []


@pytest.mark.asyncio(loop_scope="function")
async def test_reauth_broker_unreachable_is_cannot_connect(hass: HomeAssistant, no_real_setup) -> None:
    """An unreachable broker during reauth is not reported as a wrong password."""
    entry = MockConfigEntry(domain=DOMAIN, data=MOCK_USER_INPUT, unique_id="test_user")
    entry.add_to_hass(hass)

    with patch(
        "custom_components.sber_mqtt_bridge.config_flow.aiomqtt.Client",
        return_value=_FakeConnectClient(MqttConnectError(3)),
    ):
        result = await entry.start_reauth_flow(hass)
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_SBER_PASSWORD: "new_pass"})

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}
    assert entry.data[CONF_SBER_PASSWORD] == "test_pass"


class _FakeConnectClient:
    """``aiomqtt.Client`` stand-in whose connect raises (or succeeds)."""

    def __init__(self, error: BaseException | None) -> None:
        self.error = error

    async def __aenter__(self) -> _FakeConnectClient:
        if self.error is not None:
            raise self.error
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False


@pytest.mark.asyncio(loop_scope="function")
@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (None, None),
        (MqttConnectError(convert_connack_rc_to_reason_code(4)), "invalid_auth"),
        (MqttConnectError(convert_connack_rc_to_reason_code(5)), "invalid_auth"),
        (MqttConnectError(convert_connack_rc_to_reason_code(3)), "cannot_connect"),
        (aiomqtt.MqttError("Operation timed out"), "cannot_connect"),
        (OSError("Network is unreachable"), "cannot_connect"),
    ],
)
async def test_validate_connection_classifies_errors(
    hass: HomeAssistant, error: BaseException | None, expected: str | None
) -> None:
    """Credential validation shares the auth/transient rule with the runtime."""
    with patch(
        "custom_components.sber_mqtt_bridge.config_flow.aiomqtt.Client",
        return_value=_FakeConnectClient(error),
    ):
        result = await _validate_sber_connection(hass, "login", "password", "broker.test", 8883, verify_ssl=False)

    assert result == expected


@pytest.mark.asyncio(loop_scope="function")
async def test_validate_connection_propagates_cancellation(hass: HomeAssistant) -> None:
    """Cancelling the flow must not be swallowed as a connection error."""
    with (
        patch(
            "custom_components.sber_mqtt_bridge.config_flow.aiomqtt.Client",
            return_value=_FakeConnectClient(asyncio.CancelledError()),
        ),
        pytest.raises(asyncio.CancelledError),
    ):
        await _validate_sber_connection(hass, "login", "password", "broker.test", 8883, verify_ssl=False)


@pytest.mark.asyncio(loop_scope="function")
@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (MqttConnectError(convert_connack_rc_to_reason_code(4)), "invalid_auth"),
        (MqttConnectError(convert_connack_rc_to_reason_code(3)), "cannot_connect"),
    ],
)
async def test_user_step_shows_classified_error(hass: HomeAssistant, error: BaseException, expected: str) -> None:
    """The user step reports a refused password and an unreachable broker differently."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    with patch(
        "custom_components.sber_mqtt_bridge.config_flow.aiomqtt.Client",
        return_value=_FakeConnectClient(error),
    ):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], MOCK_USER_INPUT)

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": expected}
