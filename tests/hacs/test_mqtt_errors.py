"""Classification of Sber broker connection failures (auth vs transient).

The table is the contract shared by the config flow (``invalid_auth`` vs
``cannot_connect``) and the running bridge (start reauth vs keep
reconnecting): a false "auth failure" stops the bridge until the user acts,
a missed one hammers the broker with a rejected password forever.
"""

from __future__ import annotations

import ssl

import aiomqtt
import paho.mqtt.client as paho
import pytest
from aiomqtt.exceptions import MqttConnectError
from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.reasoncodes import ReasonCode

from custom_components.sber_mqtt_bridge.mqtt_errors import (
    ERROR_CANNOT_CONNECT,
    ERROR_INVALID_AUTH,
    connection_error_key,
    is_auth_failure,
)


def _connack(name: str) -> ReasonCode:
    """Build a CONNACK reason code by its MQTT 5 name."""
    return ReasonCode(PacketTypes.CONNACK, name)


AUTH_FAILURES = [
    # paho-mqtt 2 converts MQTT 3.1.1 return codes to MQTT 5 reason codes —
    # this is what aiomqtt actually raises against the Sber broker.
    pytest.param(MqttConnectError(paho.convert_connack_rc_to_reason_code(4)), id="v311-rc4-as-reasoncode"),
    pytest.param(MqttConnectError(paho.convert_connack_rc_to_reason_code(5)), id="v311-rc5-as-reasoncode"),
    pytest.param(MqttConnectError(_connack("Bad user name or password")), id="v5-0x86"),
    pytest.param(MqttConnectError(_connack("Not authorized")), id="v5-0x87"),
    pytest.param(MqttConnectError(_connack("Bad authentication method")), id="v5-0x8C"),
    # Raw integer return codes (older callback API) are accepted too.
    pytest.param(MqttConnectError(4), id="v311-int-4"),
    pytest.param(MqttConnectError(5), id="v311-int-5"),
    pytest.param(MqttConnectError(0x86), id="v5-int-0x86"),
]

TRANSIENT_FAILURES = [
    pytest.param(MqttConnectError(paho.convert_connack_rc_to_reason_code(3)), id="v311-server-unavailable"),
    pytest.param(MqttConnectError(3), id="v311-int-3-server-unavailable"),
    pytest.param(MqttConnectError(1), id="v311-int-1-protocol"),
    pytest.param(MqttConnectError(2), id="v311-int-2-client-id"),
    pytest.param(MqttConnectError(_connack("Server unavailable")), id="v5-0x88"),
    pytest.param(MqttConnectError(_connack("Server busy")), id="v5-0x89"),
    pytest.param(MqttConnectError(_connack("Banned")), id="v5-0x8A"),
    pytest.param(MqttConnectError(_connack("Unspecified error")), id="v5-0x80"),
    # paho client error numbers collide with 3.1.1 return codes (4 = NO_CONN,
    # 5 = CONN_REFUSED) but are not CONNACK answers.
    pytest.param(aiomqtt.MqttCodeError(paho.MQTT_ERR_NO_CONN, "Could not publish message"), id="publish-err-no-conn"),
    pytest.param(aiomqtt.MqttCodeError(paho.MQTT_ERR_CONN_REFUSED, "Could not subscribe"), id="subscribe-err-5"),
    pytest.param(aiomqtt.MqttCodeError(_connack("Not authorized"), "Unexpected disconnection"), id="disconnect-0x87"),
    pytest.param(aiomqtt.MqttError("Operation timed out"), id="timeout"),
    pytest.param(OSError("Network is unreachable"), id="oserror"),
    pytest.param(ssl.SSLError("handshake failed"), id="ssl"),
    pytest.param(RuntimeError("boom"), id="unexpected"),
]


@pytest.mark.parametrize("err", AUTH_FAILURES)
def test_auth_failures_are_classified_as_auth(err: BaseException) -> None:
    """A refused login/password is an auth failure and maps to ``invalid_auth``."""
    assert is_auth_failure(err) is True
    assert connection_error_key(err) == ERROR_INVALID_AUTH


@pytest.mark.parametrize("err", TRANSIENT_FAILURES)
def test_other_failures_are_transient(err: BaseException) -> None:
    """Everything else is transient and maps to ``cannot_connect``."""
    assert is_auth_failure(err) is False
    assert connection_error_key(err) == ERROR_CANNOT_CONNECT


def test_connect_error_without_code_is_transient() -> None:
    """A ``MqttConnectError`` whose code is not a number is not an auth failure."""
    err = MqttConnectError(4)
    err.rc = None
    assert is_auth_failure(err) is False
    err.rc = True  # bool is an int subclass, but never a return code
    assert is_auth_failure(err) is False
