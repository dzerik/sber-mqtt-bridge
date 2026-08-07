"""Tests for the Sber MQTT Bridge config flow."""

from unittest.mock import patch

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

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
@patch(
    "custom_components.sber_mqtt_bridge.config_flow._validate_sber_connection",
    return_value=None,
)
async def test_duplicate_entry(mock_validate, hass: HomeAssistant) -> None:
    """Test duplicate unique_id aborts."""
    # Create first entry
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    await hass.config_entries.flow.async_configure(result["flow_id"], MOCK_USER_INPUT)

    # Try to create second with same login
    result2 = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result2 = await hass.config_entries.flow.async_configure(result2["flow_id"], MOCK_USER_INPUT)

    assert result2["type"] is FlowResultType.ABORT
    assert result2["reason"] == "already_configured"


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
