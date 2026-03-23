"""Config flow for Sber Smart Home MQTT Bridge.

Provides UI-based configuration for Sber MQTT credentials
and entity selection via Options Flow with menu-based navigation,
entity type overrides, and label-based filtering.
"""

from __future__ import annotations

import logging
import ssl
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
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
    CONF_ENTITY_TYPE_OVERRIDES,
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
from .sber_entity_map import OVERRIDABLE_CATEGORIES, create_sber_entity

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
    "cover": "Covers (curtains, blinds, gates)",
    "climate": "Climate (HVAC, radiators)",
    "sensor": "Sensors (temperature, humidity)",
    "binary_sensor": "Binary sensors (motion, door, leak)",
    "humidifier": "Humidifiers",
    "valve": "Valves",
    "input_boolean": "Input booleans (scenario buttons)",
    "script": "Scripts",
    "button": "Buttons",
    "media_player": "Media players (TV)",
    "vacuum": "Vacuums",
}

# Human-readable labels for Sber categories (used in type override selector)
CATEGORY_LABELS: dict[str, str] = {
    "light": "Light",
    "relay": "Relay (switch)",
    "socket": "Socket (outlet)",
    "curtain": "Curtain",
    "window_blind": "Window blind",
    "gate": "Gate / Garage door",
    "hvac_ac": "Air conditioner (HVAC)",
    "hvac_radiator": "Radiator",
    "valve": "Valve",
    "hvac_humidifier": "Humidifier",
    "scenario_button": "Scenario button",
    "hvac_air_purifier": "Air purifier",
    "kettle": "Kettle",
    "tv": "TV / Media player",
    "vacuum_cleaner": "Vacuum cleaner",
    "intercom": "Intercom",
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
                    entry.device_id,
                    entry.entity_id,
                    priority,
                    existing[1],
                    existing[0],
                )
            device_best[entry.device_id] = (priority, entry.entity_id)

    result = no_device + [eid for _, eid in device_best.values()]
    return sorted(result)


def _get_entities_by_labels(hass: HomeAssistant, labels: list[str]) -> list[str]:
    """Return entity IDs that have any of the specified labels.

    Args:
        hass: Home Assistant instance.
        labels: List of label IDs to match.

    Returns:
        Sorted list of matching entity IDs.
    """
    entity_reg = er.async_get(hass)
    label_set = set(labels)
    result: list[str] = []

    for entry in entity_reg.entities.values():
        if entry.disabled_by is not None:
            continue
        domain = entry.entity_id.split(".", 1)[0]
        if domain not in SUPPORTED_DOMAINS:
            continue
        if label_set & set(entry.labels):
            result.append(entry.entity_id)

    return sorted(result)


class SberMqttBridgeConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Sber MQTT Bridge."""

    VERSION = 2
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
        config_entry: ConfigEntry,
    ) -> SberMqttBridgeOptionsFlow:
        """Get the options flow handler."""
        return SberMqttBridgeOptionsFlow()


class SberMqttBridgeOptionsFlow(OptionsFlowWithReload):
    """Handle options flow for Sber MQTT Bridge.

    Primary device management is done through the sidebar panel.
    Options Flow is kept as a fallback with a link to the panel
    and advanced entity selection for users who prefer it.
    """

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show panel link with fallback to advanced options."""
        if user_input is not None:
            mode = user_input.get("action", "panel")
            if mode == "advanced":
                return self.async_show_menu(
                    step_id="advanced_menu",
                    menu_options=[
                        "select_entities_menu",
                        "type_overrides",
                    ],
                )
            # Default: just close (user goes to panel)
            return self.async_create_entry(data=self.config_entry.options)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required("action", default="panel"): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                SelectOptionDict(
                                    value="panel",
                                    label="Open Sber Bridge panel (recommended)",
                                ),
                                SelectOptionDict(
                                    value="advanced",
                                    label="Advanced entity management (fallback)",
                                ),
                            ],
                            mode=SelectSelectorMode.LIST,
                        )
                    ),
                }
            ),
        )

    # ── Entity Selection Menu ──

    async def async_step_select_entities_menu(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Choose entity selection mode."""
        if user_input is not None:
            mode = user_input.get("selection_mode", "manual")
            if mode == "clear_all":
                _LOGGER.info("Clearing all exposed entities")
                return self.async_create_entry(
                    data={
                        CONF_EXPOSED_ENTITIES: [],
                        CONF_ENTITY_TYPE_OVERRIDES: self.config_entry.options.get(CONF_ENTITY_TYPE_OVERRIDES, {}),
                    },
                )
            if mode == "add_all":
                all_ids = _get_entities_by_domains(self.hass, SUPPORTED_DOMAINS)
                _LOGGER.info("Adding all %d supported entities", len(all_ids))
                return self.async_create_entry(
                    data={
                        CONF_EXPOSED_ENTITIES: all_ids,
                        CONF_ENTITY_TYPE_OVERRIDES: self.config_entry.options.get(CONF_ENTITY_TYPE_OVERRIDES, {}),
                    },
                )
            if mode == "by_domain":
                return await self.async_step_select_domains()
            if mode == "by_label":
                return await self.async_step_select_labels()
            return await self.async_step_select_entities()

        return self.async_show_form(
            step_id="select_entities_menu",
            data_schema=vol.Schema(
                {
                    vol.Required("selection_mode", default="manual"): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                SelectOptionDict(value="manual", label="Select entities manually"),
                                SelectOptionDict(value="by_domain", label="Add all entities by domain"),
                                SelectOptionDict(value="by_label", label="Add entities by label"),
                                SelectOptionDict(value="add_all", label="Add ALL supported entities"),
                                SelectOptionDict(value="clear_all", label="Remove ALL entities"),
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
            return self.async_create_entry(
                data={
                    **user_input,
                    CONF_ENTITY_TYPE_OVERRIDES: self.config_entry.options.get(CONF_ENTITY_TYPE_OVERRIDES, {}),
                },
            )

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
                    len(domain_ids),
                    selected_domains,
                    len(merged),
                )
                return self.async_create_entry(
                    data={
                        CONF_EXPOSED_ENTITIES: merged,
                        CONF_ENTITY_TYPE_OVERRIDES: self.config_entry.options.get(CONF_ENTITY_TYPE_OVERRIDES, {}),
                    },
                )
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
                domain_options.append(SelectOptionDict(value=domain, label=f"{label} ({count})"))

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

    # ── Label-based Filtering ──

    async def async_step_select_labels(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Label-based entity selection step."""
        if user_input is not None:
            selected_labels = user_input.get("labels", [])
            if selected_labels:
                label_ids = _get_entities_by_labels(self.hass, selected_labels)
                existing = list(self.config_entry.options.get(CONF_EXPOSED_ENTITIES, []))
                merged = sorted(set(existing) | set(label_ids))
                _LOGGER.info(
                    "Adding %d entities with labels %s (total: %d)",
                    len(label_ids),
                    selected_labels,
                    len(merged),
                )
                return self.async_create_entry(
                    data={
                        CONF_EXPOSED_ENTITIES: merged,
                        CONF_ENTITY_TYPE_OVERRIDES: self.config_entry.options.get(CONF_ENTITY_TYPE_OVERRIDES, {}),
                    },
                )
            return self.async_create_entry(data=self.config_entry.options)

        # Collect all labels from supported entities
        entity_reg = er.async_get(self.hass)
        all_labels: set[str] = set()
        for entry in entity_reg.entities.values():
            if entry.disabled_by is not None:
                continue
            domain = entry.entity_id.split(".", 1)[0]
            if domain in SUPPORTED_DOMAINS and hasattr(entry, "labels"):
                all_labels.update(entry.labels)

        if not all_labels:
            # No labels found — go back with a message
            return self.async_show_form(
                step_id="select_labels",
                data_schema=vol.Schema(
                    {
                        vol.Optional("labels"): SelectSelector(
                            SelectSelectorConfig(
                                options=[],
                                multiple=True,
                                mode=SelectSelectorMode.LIST,
                            )
                        ),
                    }
                ),
            )

        label_options = [SelectOptionDict(value=label, label=label) for label in sorted(all_labels)]

        return self.async_show_form(
            step_id="select_labels",
            data_schema=vol.Schema(
                {
                    vol.Required("labels"): SelectSelector(
                        SelectSelectorConfig(
                            options=label_options,
                            multiple=True,
                            mode=SelectSelectorMode.LIST,
                        )
                    ),
                }
            ),
        )

    # ── Entity Type Overrides ──

    async def async_step_type_overrides(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Entity type override selection step.

        Shows exposed entities and allows overriding their Sber category.
        """
        exposed = list(self.config_entry.options.get(CONF_EXPOSED_ENTITIES, []))
        current_overrides: dict[str, str] = dict(self.config_entry.options.get(CONF_ENTITY_TYPE_OVERRIDES, {}))

        if user_input is not None:
            # Parse overrides from user input
            new_overrides: dict[str, str] = {}
            for entity_id in exposed:
                key = f"override_{entity_id}"
                selected = user_input.get(key, "auto")
                if selected != "auto":
                    new_overrides[entity_id] = selected

            _LOGGER.info("Entity type overrides updated: %s", new_overrides)
            return self.async_create_entry(
                data={
                    CONF_EXPOSED_ENTITIES: exposed,
                    CONF_ENTITY_TYPE_OVERRIDES: new_overrides,
                },
            )

        if not exposed:
            # No entities exposed — show empty form
            return self.async_show_form(
                step_id="type_overrides",
                data_schema=vol.Schema({}),
                description_placeholders={"entities_info": "No entities are exposed yet."},
            )

        # Build form with one selector per exposed entity
        entity_reg = er.async_get(self.hass)
        schema_dict: dict = {}

        # Build category options
        category_options = [SelectOptionDict(value="auto", label="Auto (detect from domain)")]
        for cat in OVERRIDABLE_CATEGORIES:
            cat_label = CATEGORY_LABELS.get(cat, cat)
            category_options.append(SelectOptionDict(value=cat, label=cat_label))

        for entity_id in exposed:
            entry = entity_reg.async_get(entity_id)
            if entry is None:
                continue

            # Determine current auto-detected category and features
            entity_data = {
                "entity_id": entry.entity_id,
                "original_device_class": entry.original_device_class or "",
            }
            auto_entity = create_sber_entity(entity_id, entity_data)
            auto_cat = auto_entity.category if auto_entity else "unknown"
            features_str = ""
            if auto_entity is not None:
                features = auto_entity.create_features_list()
                features_str = f" features: {', '.join(features)}"

            # Current override value
            current = current_overrides.get(entity_id, "auto")

            display_name = entry.name or entry.original_name or entity_id
            key = f"override_{entity_id}"

            schema_dict[vol.Optional(key, default=current, description={"suffix": f" [{auto_cat}] {display_name}{features_str}"})] = (
                SelectSelector(
                    SelectSelectorConfig(
                        options=category_options,
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                )
            )

        return self.async_show_form(
            step_id="type_overrides",
            data_schema=vol.Schema(schema_dict),
        )
