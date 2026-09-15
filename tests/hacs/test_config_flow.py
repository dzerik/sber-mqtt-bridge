"""Tests for the Sber MQTT Bridge config flow."""

from __future__ import annotations

import asyncio
import ssl
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

    # The created entry is set up right away; a real bridge would start an
    # MQTT client whose socket attempt races the test teardown (flaky
    # "the test opens sockets" error under a loaded xdist run).
    with (
        patch("custom_components.sber_mqtt_bridge.async_setup_entry", return_value=True),
        patch("custom_components.sber_mqtt_bridge.async_unload_entry", return_value=True),
    ):
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


@pytest.mark.asyncio(loop_scope="function")
@pytest.mark.parametrize(
    ("data_verify", "options", "expected_mode"),
    [
        # Turned off later in the panel: the setting lives in options only.
        (True, {"sber_verify_ssl": False}, ssl.CERT_NONE),
        # Turned back on in the panel over an entry created without verification.
        (False, {"sber_verify_ssl": True}, ssl.CERT_REQUIRED),
        # Never touched in the panel: the value from the setup form applies.
        (False, {}, ssl.CERT_NONE),
    ],
)
async def test_reauth_uses_the_certificate_check_the_bridge_uses(
    hass: HomeAssistant, no_real_setup, data_verify: bool, options: dict, expected_mode: ssl.VerifyMode
) -> None:
    """Reauth connects with the same "Verify SSL certificate" setting as the running bridge.

    The panel stores the setting in the entry options; a broker with its own
    certificate must accept the new password without a certificate check.
    """
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={**MOCK_USER_INPUT, "sber_verify_ssl": data_verify},
        options=options,
        unique_id="test_user",
    )
    entry.add_to_hass(hass)

    with patch(
        "custom_components.sber_mqtt_bridge.config_flow.aiomqtt.Client",
        return_value=_FakeConnectClient(None),
    ) as client:
        result = await entry.start_reauth_flow(hass)
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_SBER_PASSWORD: "new_pass"})
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert client.call_args.kwargs["tls_context"].verify_mode == expected_mode
    assert entry.data[CONF_SBER_PASSWORD] == "new_pass"


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


# ---------------------------------------------------------------------------
# Recovery and duplicates — the user must be able to fix a mistake in place
# ---------------------------------------------------------------------------


@pytest.mark.asyncio(loop_scope="function")
@pytest.mark.parametrize("error", ["cannot_connect", "invalid_auth"])
async def test_user_flow_recovers_after_an_error(hass: HomeAssistant, no_real_setup, error: str) -> None:
    """A failed attempt keeps the form open and a corrected retry creates the entry.

    The form is refilled with what the user typed, so a wrong password does
    not cost them the login and broker they already entered.
    """
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})

    with patch(
        "custom_components.sber_mqtt_bridge.config_flow._validate_sber_connection",
        side_effect=[error, None],
    ) as validate:
        result = await hass.config_entries.flow.async_configure(result["flow_id"], MOCK_USER_INPUT)
        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {"base": error}
        suggested = {
            str(key): key.description["suggested_value"]
            for key in result["data_schema"].schema
            if key.description and "suggested_value" in key.description
        }
        assert suggested[CONF_SBER_LOGIN] == "test_user"

        retry = {**MOCK_USER_INPUT, CONF_SBER_PASSWORD: "right_pass"}
        result = await hass.config_entries.flow.async_configure(result["flow_id"], retry)
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_SBER_PASSWORD] == "right_pass"
    assert validate.call_count == 2
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1


@pytest.mark.asyncio(loop_scope="function")
async def test_reauth_recovers_after_an_error(hass: HomeAssistant, no_real_setup) -> None:
    """A rejected password during reauth can be retried in the same flow."""
    entry = MockConfigEntry(domain=DOMAIN, data=MOCK_USER_INPUT, unique_id="test_user")
    entry.add_to_hass(hass)

    with patch(
        "custom_components.sber_mqtt_bridge.config_flow._validate_sber_connection",
        side_effect=["invalid_auth", None],
    ):
        result = await entry.start_reauth_flow(hass)
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_SBER_PASSWORD: "typo"})
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "reauth_confirm"
        assert result["errors"] == {"base": "invalid_auth"}

        result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_SBER_PASSWORD: "new_pass"})
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_SBER_PASSWORD] == "new_pass"


@pytest.mark.asyncio(loop_scope="function")
async def test_same_account_added_while_the_form_was_open_is_refused(hass: HomeAssistant) -> None:
    """The login is the unique id: an account configured meanwhile is not added twice.

    The single-entry guard only runs when a flow starts, so a form left
    open while the account got configured elsewhere is caught by the
    unique-id check — before the broker is even contacted.
    """
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    MockConfigEntry(domain=DOMAIN, data=MOCK_USER_INPUT, unique_id="test_user").add_to_hass(hass)

    with patch("custom_components.sber_mqtt_bridge.config_flow._validate_sber_connection") as validate:
        result = await hass.config_entries.flow.async_configure(result["flow_id"], MOCK_USER_INPUT)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    validate.assert_not_called()
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1


@pytest.mark.asyncio(loop_scope="function")
async def test_same_account_in_two_open_forms_is_refused_in_the_second(hass: HomeAssistant) -> None:
    """Two setup dialogs for one login: the second submit is aborted, not duplicated."""
    first = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    second = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})

    with patch(
        "custom_components.sber_mqtt_bridge.config_flow._validate_sber_connection",
        return_value="cannot_connect",
    ):
        # The first dialog claims the login and stays open with an error.
        result = await hass.config_entries.flow.async_configure(first["flow_id"], MOCK_USER_INPUT)
        assert result["errors"] == {"base": "cannot_connect"}

        result = await hass.config_entries.flow.async_configure(second["flow_id"], MOCK_USER_INPUT)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_in_progress"
    assert hass.config_entries.async_entries(DOMAIN) == []
