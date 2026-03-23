"""Config flow for Sber Smart Home MQTT Bridge.

Provides UI-based configuration for Sber MQTT credentials
and entity selection via Options Flow.
"""

from __future__ import annotations

import logging
import ssl
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    EntityFilterSelectorConfig,
    EntitySelector,
    EntitySelectorConfig,
)

from .const import (
    CONF_EXPOSED_ENTITIES,
    CONF_SBER_BROKER,
    CONF_SBER_LOGIN,
    CONF_SBER_PASSWORD,
    CONF_SBER_PORT,
    CONF_SBER_VERIFY_SSL,
    DOMAIN,
    SBER_BROKER_DEFAULT,
    SBER_PORT_DEFAULT,
    SUPPORTED_DOMAINS,
)

_LOGGER = logging.getLogger(__name__)

USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_SBER_LOGIN): str,
        vol.Required(CONF_SBER_PASSWORD): str,
        vol.Optional(CONF_SBER_BROKER, default=SBER_BROKER_DEFAULT): str,
        vol.Optional(CONF_SBER_PORT, default=SBER_PORT_DEFAULT): int,
        vol.Optional(CONF_SBER_VERIFY_SSL, default=True): bool,
    }
)


def create_ssl_context(*, verify: bool = True) -> ssl.SSLContext:
    """Create an SSL context for Sber MQTT broker connection.

    Args:
        verify: If True, verify server certificate (recommended).
                If False, skip verification (for brokers with custom/self-signed CA).

    Returns:
        Configured SSL context.
    """
    ssl_context = ssl.create_default_context()
    if not verify:
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
    return ssl_context


async def _validate_sber_connection(
    login: str, password: str, broker: str, port: int, *, verify_ssl: bool = True
) -> str | None:
    """Validate Sber MQTT credentials by attempting a connection.

    Args:
        login: Sber MQTT login.
        password: Sber MQTT password.
        broker: MQTT broker hostname.
        port: MQTT broker port.
        verify_ssl: Whether to verify the broker's SSL certificate.

    Returns:
        Error key string, or None if connection successful.
    """
    try:
        import aiomqtt

        ssl_context = create_ssl_context(verify=verify_ssl)

        async with aiomqtt.Client(
            hostname=broker,
            port=port,
            username=login,
            password=password,
            tls_context=ssl_context,
        ):
            pass
    except aiomqtt.MqttCodeError as err:
        _LOGGER.error("Sber MQTT auth failed: %s", err)
        return "invalid_auth"
    except Exception:  # noqa: BLE001
        _LOGGER.exception("Cannot connect to Sber MQTT broker")
        return "cannot_connect"
    else:
        return None


class SberMqttBridgeConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Sber MQTT Bridge.

    Provides the initial setup step for entering Sber MQTT credentials
    and an options flow for selecting which HA entities to expose.
    """

    VERSION = 1
    MINOR_VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial user configuration step.

        Validates MQTT connection before creating the config entry.
        """
        errors: dict[str, str] = {}

        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_SBER_LOGIN])
            self._abort_if_unique_id_configured()

            error = await _validate_sber_connection(
                user_input[CONF_SBER_LOGIN],
                user_input[CONF_SBER_PASSWORD],
                user_input[CONF_SBER_BROKER],
                user_input[CONF_SBER_PORT],
                verify_ssl=user_input.get(CONF_SBER_VERIFY_SSL, True),
            )
            if error:
                errors["base"] = error
            else:
                return self.async_create_entry(
                    title=f"Sber ({user_input[CONF_SBER_LOGIN]})",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                USER_DATA_SCHEMA, user_input
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry,
    ) -> SberMqttBridgeOptionsFlow:
        """Get the options flow handler."""
        return SberMqttBridgeOptionsFlow()


class SberMqttBridgeOptionsFlow(OptionsFlowWithReload):
    """Handle options flow for Sber MQTT Bridge.

    Allows selecting which HA entities to expose to Sber Smart Home.
    Uses OptionsFlowWithReload for automatic integration reload on change.
    """

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage entity selection options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Optional(CONF_EXPOSED_ENTITIES): EntitySelector(
                            EntitySelectorConfig(
                                multiple=True,
                                filter=EntityFilterSelectorConfig(
                                    domain=SUPPORTED_DOMAINS,
                                ),
                            )
                        ),
                    }
                ),
                self.config_entry.options,
            ),
        )
