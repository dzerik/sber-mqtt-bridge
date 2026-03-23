"""Sber Smart Home MQTT Bridge integration for Home Assistant."""

from __future__ import annotations

import logging
import pathlib
from dataclasses import dataclass
from typing import Any

from homeassistant.components.frontend import async_register_built_in_panel, async_remove_panel
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN as DOMAIN
from .custom_capabilities import parse_yaml_config
from .sber_bridge import SberBridge
from .websocket_api import async_setup_websocket_api

_LOGGER = logging.getLogger(__name__)


@dataclass
class SberBridgeData:
    """Runtime data for the Sber MQTT Bridge integration.

    Attributes:
        bridge: The active SberBridge instance managing MQTT communication.
    """

    bridge: SberBridge


type SberBridgeConfigEntry = ConfigEntry[SberBridgeData]
"""Type alias for a ConfigEntry carrying SberBridgeData as runtime_data."""


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Set up the Sber MQTT Bridge component from configuration.yaml.

    Parses the optional ``sber_mqtt_bridge:`` YAML section and stores
    the custom entity configuration in ``hass.data[DOMAIN]``.

    Args:
        hass: Home Assistant core instance.
        config: Full HA configuration dict.

    Returns:
        True always (YAML config is optional).
    """
    hass.data.setdefault(DOMAIN, {})

    if DOMAIN in config:
        yaml_config = parse_yaml_config(config[DOMAIN])
        hass.data[DOMAIN]["yaml_config"] = yaml_config
        _LOGGER.info(
            "Loaded YAML config with %d entity overrides",
            len(yaml_config.entity_configs),
        )

    return True


async def async_setup_entry(hass: HomeAssistant, entry: SberBridgeConfigEntry) -> bool:
    """Set up Sber MQTT Bridge from a config entry.

    The bridge starts in background-reconnect mode: entity loading and HA event
    subscription happen immediately, while the MQTT connection is established
    asynchronously. Connection failures are logged and retried with backoff.

    Args:
        hass: Home Assistant core instance.
        entry: Config entry with Sber broker credentials and options.

    Returns:
        True if setup succeeded.
    """
    bridge = SberBridge(hass, entry)
    await bridge.async_start()

    entry.runtime_data = SberBridgeData(bridge=bridge)

    # Register WebSocket API (idempotent — skips if already registered)
    async_setup_websocket_api(hass)

    # Register frontend panel (static path + sidebar entry)
    panel_dir = str(pathlib.Path(__file__).parent / "www")
    await hass.http.async_register_static_paths(
        [StaticPathConfig("/sber_mqtt_bridge/panel", panel_dir, cache_headers=False)]
    )

    async_register_built_in_panel(
        hass,
        component_name="custom",
        sidebar_title="Sber Bridge",
        sidebar_icon="mdi:home-assistant",
        frontend_url_path="sber-mqtt-bridge",
        config={
            "_panel_custom": {
                "name": "sber-mqtt-panel",
                "module_url": "/sber_mqtt_bridge/panel/sber-panel.js",
            }
        },
        require_admin=False,
    )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: SberBridgeConfigEntry) -> bool:
    """Unload a config entry and stop the Sber bridge.

    Args:
        hass: Home Assistant core instance.
        entry: Config entry being unloaded.

    Returns:
        True if unload succeeded.
    """
    await entry.runtime_data.bridge.async_stop()

    # Remove panel from sidebar
    try:
        async_remove_panel(hass, "sber-mqtt-bridge")
    except KeyError:
        _LOGGER.debug("Panel 'sber-mqtt-bridge' already removed")

    return True


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate config entry to a newer version.

    Version 1 → 2: ensure ``entity_type_overrides`` key exists in options.

    Args:
        hass: Home Assistant core instance.
        entry: Config entry being migrated.

    Returns:
        True if migration succeeded.
    """
    if entry.version == 1:
        _LOGGER.info(
            "Migrating config entry %s from version %s to 2",
            entry.entry_id,
            entry.version,
        )
        new_options = dict(entry.options)
        if "entity_type_overrides" not in new_options:
            new_options["entity_type_overrides"] = {}
        hass.config_entries.async_update_entry(entry, options=new_options, version=2)
        _LOGGER.info("Migration of config entry %s to version 2 complete", entry.entry_id)

    return True
