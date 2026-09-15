"""Classification of Sber MQTT broker connection failures.

One question matters for every failed connection attempt: will retrying
with the same credentials ever help?  A broker that refused the login or
password answers the same way on every retry, so the only way out is new
credentials from the user (the reauth flow).  Everything else — broker
unavailable, network down, TLS handshake cut, timeout — is transient and
is handled by the normal reconnect backoff.

The answer is given in exactly one place, :func:`is_auth_failure`, which
both the config flow (``invalid_auth`` vs ``cannot_connect``) and the
bridge runtime (start reauth vs keep reconnecting) use.

Only a negative CONNACK counts as an authentication failure.  aiomqtt
raises it as :class:`aiomqtt.exceptions.MqttConnectError`; with paho-mqtt 2
the refusal code arrives as a ``ReasonCode`` in the MQTT 5 numbering even
for an MQTT 3.1.1 session (3.1.1 return code 4 becomes reason code 0x86),
but a plain integer return code is accepted too.  Other ``MqttCodeError``
instances carry paho *client* error numbers (``MQTT_ERR_NO_CONN`` = 4,
``MQTT_ERR_CONN_REFUSED`` = 5, …) that collide with the 3.1.1 return codes
and must never be read as a refused login.
"""

from __future__ import annotations

import logging

from aiomqtt.exceptions import MqttConnectError
from paho.mqtt.reasoncodes import ReasonCode

_LOGGER = logging.getLogger(__name__)

AUTH_FAILURE_RETURN_CODES: frozenset[int] = frozenset({4, 5})
"""MQTT 3.1.1 CONNACK return codes: 4 bad user name or password, 5 not authorized."""

AUTH_FAILURE_REASON_CODES: frozenset[int] = frozenset({0x86, 0x87, 0x8C})
"""MQTT 5 CONNACK reason codes: bad user name or password, not authorized, bad authentication method."""

ERROR_INVALID_AUTH = "invalid_auth"
"""Config-flow error key for credentials the broker refused."""

ERROR_CANNOT_CONNECT = "cannot_connect"
"""Config-flow error key for every transient / connection failure."""


def is_auth_failure(err: BaseException) -> bool:
    """Return whether a connection error means the broker refused the credentials.

    Args:
        err: Exception raised while connecting to (or talking to) the broker.

    Returns:
        ``True`` only for a negative CONNACK whose code is an authentication
        refusal (see :data:`AUTH_FAILURE_RETURN_CODES` and
        :data:`AUTH_FAILURE_REASON_CODES`); ``False`` for everything else,
        which callers must treat as transient.
    """
    if not isinstance(err, MqttConnectError):
        return False
    rc = err.rc
    if isinstance(rc, ReasonCode):
        return rc.value in AUTH_FAILURE_REASON_CODES
    if isinstance(rc, int) and not isinstance(rc, bool):
        return rc in AUTH_FAILURE_RETURN_CODES or rc in AUTH_FAILURE_REASON_CODES
    return False


def connection_error_key(err: BaseException) -> str:
    """Map a failed connection attempt to a config-flow error key.

    Args:
        err: Exception raised by the connection attempt.

    Returns:
        :data:`ERROR_INVALID_AUTH` for an authentication refusal,
        :data:`ERROR_CANNOT_CONNECT` for anything else.
    """
    return ERROR_INVALID_AUTH if is_auth_failure(err) else ERROR_CANNOT_CONNECT
