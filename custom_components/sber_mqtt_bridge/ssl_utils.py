"""SSL helpers shared by the transport layer and the config flow.

Kept free of Home Assistant / UI imports so that the MQTT transport
(:mod:`mqtt_client_service`) does not depend on the presentation layer
(:mod:`config_flow`).
"""

from __future__ import annotations

import logging
import ssl
from collections.abc import Mapping
from typing import Any

from .const import CONF_SBER_VERIFY_SSL

_LOGGER = logging.getLogger(__name__)


def create_ssl_context(verify: bool = True) -> ssl.SSLContext:
    """Create an SSL context for the Sber MQTT broker connection.

    Note:
        This performs blocking I/O (loads system CA certificates) and must
        be called via ``hass.async_add_executor_job`` from the event loop.

    Args:
        verify: If True, verify server certificate (recommended).
                If False, skip verification (for brokers with custom/self-signed CA).

    Returns:
        Configured SSL context.
    """
    ssl_context = ssl.create_default_context()
    if not verify:
        _LOGGER.warning(
            "SSL verification DISABLED for Sber broker — "
            "connection is vulnerable to MITM attacks. "
            "Only use this with a trusted private / self-signed broker."
        )
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
    return ssl_context


def entry_verify_ssl(data: Mapping[str, Any], options: Mapping[str, Any]) -> bool:
    """Return the effective "Verify SSL certificate" setting of a config entry.

    The setup form stores the value in the entry data; the panel stores later
    changes in the entry options, which therefore take precedence. Every
    connection to the broker (the running bridge and reauthentication) must
    use this one rule, otherwise a broker with its own certificate accepts
    one connection and rejects the other.

    Args:
        data: The config entry data.
        options: The config entry options.

    Returns:
        True when the broker certificate must be verified.
    """
    return bool(options.get(CONF_SBER_VERIFY_SSL, data.get(CONF_SBER_VERIFY_SSL, True)))
