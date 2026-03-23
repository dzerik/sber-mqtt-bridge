"""Config flow for Sber Smart Home MQTT Bridge.

Provides UI-based configuration for Sber MQTT credentials
and entity selection via Options Flow with bulk-add support.
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
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.selector import (
    EntityFilterSelectorConfig,
    EntitySelector,
    EntitySelectorConfig,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
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

# Human-readable domain labels for the domain selector
DOMAIN_LABELS: dict[str, str] = {
    "light": "Lights",
    "switch": "Switches",
    "cover": "Covers (curtains, blinds)",
    "climate": "Climate (HVAC, radiators)",
    "sensor": "Sensors (temperature, humidity)",
    "binary_sensor": "Binary sensors (motion, door, leak)",
    "humidifier": "Humidifiers",
    "valve": "Valves",
    "input_boolean": "Input booleans (scenario buttons)",
    "script": "Scripts",
    "button": "Buttons",
}


def create_ssl_context(verify: bool = True) -> ssl.SSLContext:
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
    hass: HomeAssistant, login: str, password: str, broker: str, port: int, *, verify_ssl: bool = True
) -> str | None:
    """Validate Sber MQTT credentials by attempting a connection.

    Args:
        hass: Home Assistant instance (used for executor offloading).
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

        ssl_context = await hass.async_add_executor_job(create_ssl_context, verify_ssl)

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
    except Exception:
        _LOGGER.exception("Cannot connect to Sber MQTT broker")
        return "cannot_connect"
    else:
        return None


# Domain priority for deduplication: when multiple entities share one device_id,
# keep the one with the richest Sber mapping (light > switch, cover > switch, etc.)
DOMAIN_PRIORITY: dict[str, int] = {
    "light": 10,
    "cover": 9,
    "climate": 8,
    "humidifier": 7,
    "valve": 6,
    "switch": 3,
    "script": 2,
    "button": 1,
    "input_boolean": 1,
    "sensor": 5,
    "binary_sensor": 5,
}


def _get_entities_by_domains(hass: HomeAssistant, domains: list[str]) -> list[str]:
    """Return entity IDs matching the given domains, deduplicated by device.

    When multiple entities share the same ``device_id`` (e.g. a Zigbee device
    that exposes both ``light.kitchen`` and ``switch.kitchen``), only the
    entity with the richest Sber mapping is kept (light > switch).
    Entities without a ``device_id`` are always included.

    Args:
        hass: Home Assistant instance.
        domains: List of HA domains to filter.

    Returns:
        Sorted list of deduplicated entity IDs.
    """
    entity_reg = er.async_get(hass)

    # Collect candidates grouped by device_id
    # device_id -> (priority, entity_id)
    device_best: dict[str, tuple[int, str]] = {}
    no_device: list[str] = []

    for entry in entity_reg.entities.values():
        if entry.disabled_by is not None:
            continue
        domain = entry.entity_id.split(".", 1)[0]
        if domain not in domains:
            continue

        if entry.device_id is None:
            no_device.append(entry.entity_id)
            continue

        priority = DOMAIN_PRIORITY.get(domain, 0)
        existing = device_best.get(entry.device_id)
        if existing is None or priority > existing[0]:
            if existing is not None:
                _LOGGER.debug(
                    "Device %s: %s (priority %d) replaces %s (priority %d)",
                    entry.device_id, entry.entity_id, priority,
                    existing[1], existing[0],
                )
            device_best[entry.device_id] = (priority, entry.entity_id)

    result = no_device + [eid for _, eid in device_best.values()]
    return sorted(result)


class SberMqttBridgeConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Sber MQTT Bridge."""

    VERSION = 1
    MINOR_VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle the initial user configuration step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_SBER_LOGIN])
            self._abort_if_unique_id_configured()

            error = await _validate_sber_connection(
                self.hass,
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
            data_schema=self.add_suggested_values_to_schema(USER_DATA_SCHEMA, user_input),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        """Handle re-authentication when credentials become invalid."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show re-authentication form and validate new credentials."""
        errors: dict[str, str] = {}

        if user_input is not None:
            reauth_entry = self._get_reauth_entry()
            error = await _validate_sber_connection(
                self.hass,
                reauth_entry.data[CONF_SBER_LOGIN],
                user_input[CONF_SBER_PASSWORD],
                reauth_entry.data[CONF_SBER_BROKER],
                reauth_entry.data[CONF_SBER_PORT],
                verify_ssl=reauth_entry.data.get(CONF_SBER_VERIFY_SSL, True),
            )
            if error:
                errors["base"] = error
            else:
                return self.async_update_reload_and_abort(
                    reauth_entry,
                    data={**reauth_entry.data, CONF_SBER_PASSWORD: user_input[CONF_SBER_PASSWORD]},
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_SBER_PASSWORD): str}),
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

    Provides three modes for entity selection:
    - Manual: pick individual entities from a selector
    - Add all: add all supported entities at once
    - By domain: select domains and add all entities from those domains
    """

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Choose entity selection mode."""
        if user_input is not None:
            mode = user_input.get("selection_mode", "manual")
            if mode == "add_all":
                all_ids = _get_entities_by_domains(self.hass, SUPPORTED_DOMAINS)
                _LOGGER.info("Adding all %d supported entities", len(all_ids))
                return self.async_create_entry(data={CONF_EXPOSED_ENTITIES: all_ids})
            if mode == "by_domain":
                return await self.async_step_select_domains()
            return await self.async_step_select_entities()

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required("selection_mode", default="manual"): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                SelectOptionDict(value="manual", label="Select entities manually"),
                                SelectOptionDict(value="by_domain", label="Add all entities by domain"),
                                SelectOptionDict(value="add_all", label="Add ALL supported entities"),
                            ],
                            mode=SelectSelectorMode.LIST,
                        )
                    ),
                }
            ),
        )

    async def async_step_select_entities(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Manual entity selection step."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        return self.async_show_form(
            step_id="select_entities",
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

    async def async_step_select_domains(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Domain-based entity selection step."""
        if user_input is not None:
            selected_domains = user_input.get("domains", [])
            if selected_domains:
                domain_ids = _get_entities_by_domains(self.hass, selected_domains)
                # Merge with existing entities (keep manual selections)
                existing = list(self.config_entry.options.get(CONF_EXPOSED_ENTITIES, []))
                merged = sorted(set(existing) | set(domain_ids))
                _LOGGER.info(
                    "Adding %d entities from domains %s (total: %d)",
                    len(domain_ids), selected_domains, len(merged),
                )
                return self.async_create_entry(data={CONF_EXPOSED_ENTITIES: merged})
            return self.async_create_entry(data=self.config_entry.options)

        # Build domain options with entity counts
        domain_options = []
        entity_reg = er.async_get(self.hass)
        domain_counts: dict[str, int] = {}
        for entry in entity_reg.entities.values():
            if entry.disabled_by is not None:
                continue
            d = entry.entity_id.split(".", 1)[0]
            if d in SUPPORTED_DOMAINS:
                domain_counts[d] = domain_counts.get(d, 0) + 1

        for domain in SUPPORTED_DOMAINS:
            count = domain_counts.get(domain, 0)
            if count > 0:
                label = DOMAIN_LABELS.get(domain, domain)
                domain_options.append(
                    SelectOptionDict(value=domain, label=f"{label} ({count})")
                )

        return self.async_show_form(
            step_id="select_domains",
            data_schema=vol.Schema(
                {
                    vol.Required("domains"): SelectSelector(
                        SelectSelectorConfig(
                            options=domain_options,
                            multiple=True,
                            mode=SelectSelectorMode.LIST,
                        )
                    ),
                }
            ),
        )
