"""Sber Smart Home MQTT Bridge integration for Home Assistant."""

from __future__ import annotations

import logging
import pathlib
from dataclasses import dataclass
from typing import Any

import voluptuous as vol
from homeassistant.components.frontend import async_register_built_in_panel, async_remove_panel
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError, ConfigEntryNotReady

from .cloud_device_registry import CloudDeviceRegistry, ModelIdentityMigration
from .conflict import async_track_conflicts
from .const import DOMAIN as DOMAIN
from .custom_capabilities import YAML_CONFIG_KEY, YAML_CONFIG_SCHEMA, parse_yaml_config
from .repairs import async_delete_all_issues
from .sber_bridge import SberBridge
from .sber_protocol import VERSION as INTEGRATION_VERSION
from .websocket_api import async_setup_websocket_api

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = vol.Schema(
    {vol.Optional(DOMAIN): YAML_CONFIG_SCHEMA},
    extra=vol.ALLOW_EXTRA,
)
"""Validates the optional ``sber_mqtt_bridge:`` section of ``configuration.yaml``.

``extra=ALLOW_EXTRA`` at this level is the HA convention: the dict handed
over is the whole configuration, every other integration's section
included.  What the section itself accepts is described by
:data:`~.custom_capabilities.YAML_CONFIG_SCHEMA`."""


@dataclass
class SberBridgeData:
    """Runtime data for the Sber MQTT Bridge integration.

    Attributes:
        bridge: The active SberBridge instance managing MQTT communication.
    """

    bridge: SberBridge


PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR]
"""Platforms carrying the bridge's own diagnostic entities."""

type SberBridgeConfigEntry = ConfigEntry[SberBridgeData]
"""Type alias for a ConfigEntry carrying SberBridgeData as runtime_data."""


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Set up the Sber MQTT Bridge component from configuration.yaml.

    Parses the optional ``sber_mqtt_bridge:`` YAML section (already
    validated by :data:`CONFIG_SCHEMA`) and stores the custom entity
    configuration in ``hass.data[DOMAIN]`` under
    :data:`~.custom_capabilities.YAML_CONFIG_KEY`.  HA runs this once per
    start, so nothing tied to a config entry may drop that key — see
    :func:`async_remove_entry`.

    Args:
        hass: Home Assistant core instance.
        config: Full HA configuration dict.

    Returns:
        True always (YAML config is optional).
    """
    hass.data.setdefault(DOMAIN, {})

    if DOMAIN in config:
        yaml_config = parse_yaml_config(config[DOMAIN])
        hass.data[DOMAIN][YAML_CONFIG_KEY] = yaml_config
        _LOGGER.info(
            "Loaded YAML config with %d entity overrides",
            len(yaml_config.entity_configs),
        )

    return True


def _async_migrate_model_identity(hass: HomeAssistant, entry: SberBridgeConfigEntry) -> None:
    """Warn once when the ``model.id`` formula has moved under an existing entry.

    Run before the bridge starts, so the explanation is in front of the
    user before the first config publish re-registers anything.  A fresh
    installation is stamped silently — see
    :class:`~.cloud_device_registry.ModelIdentityMigration`.

    The registry is built here rather than taken from the bridge because
    the bridge does not exist yet and because all this needs is the set
    the config entry already carries; the instance is read-only for our
    purposes and is dropped as soon as the check is done.

    Args:
        hass: Home Assistant core instance.
        entry: Config entry being set up.
    """
    ModelIdentityMigration(hass, entry, CloudDeviceRegistry(hass, entry)).async_run()


ACTIVE_ENTRY_KEY = "active_entry_id"
"""``hass.data[DOMAIN]`` key naming the one config entry that runs the bridge."""


def _claim_single_entry(hass: HomeAssistant, entry: SberBridgeConfigEntry) -> None:
    """Make ``entry`` the only config entry running the bridge on this HA.

    The integration supports one config entry (``single_config_entry`` in
    the manifest), but HA only stops *new* entries from being created — an
    installation that already has two keeps both, and HA sets them up side
    by side.  A second bridge cannot work: the sidebar panel and every
    WebSocket command are bound to one entry, so the second setup used to
    retry forever and unloading either entry took the panel away from the
    other.  The first entry to set up claims the bridge; any other one fails
    with a permanent, explained setup error instead.

    The claim is taken synchronously, before any ``await``, so two entries
    being set up concurrently at HA start cannot both win.

    Args:
        hass: Home Assistant core instance.
        entry: Config entry being set up.

    Raises:
        ConfigEntryError: Another config entry of this integration already
            runs the bridge.
    """
    domain_data: dict[str, Any] = hass.data.setdefault(DOMAIN, {})
    active_id = domain_data.get(ACTIVE_ENTRY_KEY)
    if active_id is not None and active_id != entry.entry_id:
        active = hass.config_entries.async_get_entry(active_id)
        active_title = active.title if active is not None else active_id
        _LOGGER.error(
            "Config entry '%s' is not started: Sber MQTT Bridge supports a single config entry "
            "and '%s' is already running. Delete the extra entry in Settings → Devices & services",
            entry.title,
            active_title,
        )
        raise ConfigEntryError(
            translation_domain=DOMAIN,
            translation_key="single_entry_only",
            translation_placeholders={"active": active_title},
        )
    domain_data[ACTIVE_ENTRY_KEY] = entry.entry_id


def _release_single_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Drop the claim taken by :func:`_claim_single_entry`, if ``entry`` holds it.

    Args:
        hass: Home Assistant core instance.
        entry: Config entry being unloaded or rolled back.
    """
    domain_data = hass.data.get(DOMAIN)
    if domain_data is not None and domain_data.get(ACTIVE_ENTRY_KEY) == entry.entry_id:
        domain_data.pop(ACTIVE_ENTRY_KEY)


async def async_setup_entry(hass: HomeAssistant, entry: SberBridgeConfigEntry) -> bool:
    """Set up Sber MQTT Bridge from a config entry.

    The bridge starts in background-reconnect mode: entity loading and HA event
    subscription happen immediately, while the MQTT connection is established
    asynchronously. Connection failures are logged and retried with backoff.

    Every step after ``bridge.async_start()`` is rolled back on failure: a
    started bridge holds an MQTT client, background tasks and
    ``state_changed`` subscriptions, so leaving it running for an entry HA
    considers *not loaded* would keep publishing to Sber from a dead entry
    and would leak a second bridge on every setup retry.

    Args:
        hass: Home Assistant core instance.
        entry: Config entry with Sber broker credentials and options.

    Returns:
        True if setup succeeded.

    Raises:
        ConfigEntryError: Another config entry of this integration already
            runs the bridge (see :func:`_claim_single_entry`).
        ConfigEntryNotReady: If frontend/WebSocket registration failed; the
            bridge is stopped first and HA retries the whole setup.
    """
    _claim_single_entry(hass, entry)
    try:
        _async_migrate_model_identity(hass, entry)
        bridge = SberBridge(hass, entry)
        await bridge.async_start()
    except BaseException:
        _release_single_entry(hass, entry)
        raise

    try:
        entry.runtime_data = SberBridgeData(bridge=bridge)

        # Register WebSocket API (idempotent — skips if already registered)
        async_setup_websocket_api(hass)

        # Another HA → Sber bridge next to this one is invisible from the
        # bridge's own traffic; surface it as a Repairs issue (issue #63).
        entry.async_on_unload(async_track_conflicts(hass, entry))

        # The bridge's own diagnostic entities (connection, errors).
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

        # Register frontend panel (static path + sidebar entry).
        #
        # The static path is registered ONCE per HA instance, not per entry
        # setup: aiohttp freezes its router as soon as the HTTP server is
        # running, so a second registration during a reload raises
        # RuntimeError -> ConfigEntryNotReady and the entry never comes back.
        # Every mutating panel command reloads the entry, so without this
        # guard the panel bricked the integration on the first click.
        # Same marker pattern as async_setup_websocket_api.
        static_marker = f"{DOMAIN}_panel_static_registered"
        if not hass.data.get(static_marker):
            panel_dir = str(pathlib.Path(__file__).parent / "www")
            await hass.http.async_register_static_paths(
                [StaticPathConfig("/sber_mqtt_bridge/panel", panel_dir, cache_headers=False)]
            )
            hass.data[static_marker] = True

        async_register_built_in_panel(
            hass,
            component_name="custom",
            sidebar_title="Sber Bridge",
            sidebar_icon="mdi:home-assistant",
            frontend_url_path="sber-mqtt-bridge",
            config={
                "_panel_custom": {
                    "name": "sber-mqtt-panel",
                    "module_url": f"/sber_mqtt_bridge/panel/sber-panel.js?v={INTEGRATION_VERSION}",
                }
            },
            # Every WebSocket command of this integration is admin-only
            # (websocket_api/__init__.py wraps them in require_admin), so a
            # non-admin would see a panel where every action fails.
            require_admin=True,
        )
    except Exception as err:
        _LOGGER.exception("Sber MQTT Bridge setup failed after bridge start, rolling back")
        await bridge.async_stop()
        _release_single_entry(hass, entry)
        raise ConfigEntryNotReady(f"Sber MQTT Bridge frontend registration failed: {err}") from err

    return True


async def async_unload_entry(hass: HomeAssistant, entry: SberBridgeConfigEntry) -> bool:
    """Unload a config entry and stop the Sber bridge.

    Args:
        hass: Home Assistant core instance.
        entry: Config entry being unloaded.

    Returns:
        True if unload succeeded.
    """
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    await entry.runtime_data.bridge.async_stop()
    _release_single_entry(hass, entry)
    if entry.disabled_by is not None:
        # The user disabled the integration: the repair tiles describe a
        # bridge that stays stopped, and nothing would clear them.  A plain
        # unload is a reload (options saved, reauth, "Reload"): deleting
        # would drop the user's "Ignore" choice, because a deleted issue is
        # recreated as new; the restarted bridge re-checks them instead.
        # Removal is handled by :func:`async_remove_entry`.
        async_delete_all_issues(hass)

    # Remove panel from sidebar
    try:
        async_remove_panel(hass, "sber-mqtt-bridge")
    except KeyError:
        _LOGGER.debug("Panel 'sber-mqtt-bridge' already removed")

    return True


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Clean up when a config entry is removed.

    Deletes the repair issues of the integration once no entry is left,
    including those of an entry that was never loaded (its unload did not
    run).  ``hass.data[DOMAIN]`` is deliberately kept: it holds the YAML
    configuration parsed by :func:`async_setup`, which HA does not run again
    until restart, so dropping it made an entry added afterwards ignore the
    YAML overrides.  Only the single-entry claim of the removed entry is
    dropped — normally :func:`async_unload_entry` has released it already,
    but not when that unload failed, and a claim left behind would stop
    the next entry from starting.

    Args:
        hass: Home Assistant core instance.
        entry: Config entry being removed.
    """
    _release_single_entry(hass, entry)
    if not hass.config_entries.async_entries(DOMAIN):
        async_delete_all_issues(hass)


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
        _LOGGER.info("Migrating config entry %s from version 1 to 2", entry.entry_id)
        new_options = dict(entry.options)
        if "entity_type_overrides" not in new_options:
            new_options["entity_type_overrides"] = {}
        hass.config_entries.async_update_entry(entry, options=new_options, version=2)
        _LOGGER.info("Migration to version 2 complete")

    if entry.version == 2:
        _LOGGER.info("Migrating config entry %s from version 2 to 3", entry.entry_id)
        new_options = dict(entry.options)
        if "entity_links" not in new_options:
            new_options["entity_links"] = {}
        hass.config_entries.async_update_entry(entry, options=new_options, version=3)
        _LOGGER.info("Migration to version 3 complete")

    return True
