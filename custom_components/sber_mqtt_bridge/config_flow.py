"""Config flow for Sber Smart Home MQTT Bridge."""

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
    EntitySelector,
    EntitySelectorConfig,
    EntityFilterSelectorConfig,
)

from .const import (
    CONF_EXPOSED_ENTITIES,
    CONF_SBER_BROKER,
    CONF_SBER_LOGIN,
    CONF_SBER_PASSWORD,
    CONF_SBER_PORT,
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
    }
)


async def _validate_sber_connection(
    login: str, password: str, broker: str, port: int
) -> str | None:
    """Validate Sber MQTT credentials by attempting a connection.

    Returns error key or None if successful.
    """
    try:
        import aiomqtt

        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

        async with aiomqtt.Client(
            hostname=broker,
            port=port,
            username=login,
            password=password,
            tls_params=aiomqtt.TLSParameters(ssl_context=ssl_context),
        ):
            pass
        return None
    except aiomqtt.MqttCodeError as err:
        _LOGGER.error("Sber MQTT auth failed: %s", err)
        return "invalid_auth"
    except Exception as err:
        _LOGGER.error("Cannot connect to Sber MQTT: %s", err)
        return "cannot_connect"


class SberMqttBridgeConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Sber MQTT Bridge."""

    VERSION = 1
    MINOR_VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_SBER_LOGIN])
            self._abort_if_unique_id_configured()

            error = await _validate_sber_connection(
                user_input[CONF_SBER_LOGIN],
                user_input[CONF_SBER_PASSWORD],
                user_input[CONF_SBER_BROKER],
                user_input[CONF_SBER_PORT],
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
        """Get the options flow."""
        return SberMqttBridgeOptionsFlow()


class SberMqttBridgeOptionsFlow(OptionsFlowWithReload):
    """Handle options flow for Sber MQTT Bridge."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
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
