"""WebSocket API package for Sber MQTT Bridge panel.

Provides real-time device and connection data to the frontend SPA panel
via Home Assistant native WebSocket commands.  Split across domain
modules to keep per-file size and concerns focused:

- ``_common``         — shared ``get_bridge`` / ``get_config_entry`` helpers
- ``status``          — connection status, devices listing, device detail,
                        publish-one-status, related sensors, republish
- ``entities``        — add / remove / clear / override
- ``links``           — set_entity_links / auto_link_all
- ``devices_grouped`` — device-centric wizard: list_categories /
                        list_devices_for_category / add_ha_device
- ``raw``             — raw config / state inspection + direct MQTT send
- ``io_export``       — export / import / update_redefinitions
- ``settings``        — get_settings / update_settings
- ``log``             — message_log / clear_message_log / subscribe_messages
- ``traces``          — correlation-timeline traces (DevTools #1)
- ``diffs``           — state-payload diffs (DevTools #2)

All public ``ws_*`` command functions are re-exported at package level
for test introspection.
"""

from __future__ import annotations

import logging

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from ..const import DOMAIN
from .devices_grouped import (
    ws_add_ha_device,
    ws_list_categories,
    ws_list_devices_for_category,
    ws_suggest_links,
)
from .diffs import ws_clear_state_diffs, ws_list_state_diffs, ws_subscribe_state_diffs
from .entities import (
    ws_add_entities,
    ws_clear_all,
    ws_remove_entities,
    ws_set_type_override,
)
from .io_export import ws_export, ws_import, ws_update_redefinitions
from .links import ws_auto_link_all, ws_set_entity_links
from .log import ws_clear_message_log, ws_message_log, ws_subscribe_messages
from .raw import ws_raw_config, ws_raw_states, ws_send_raw_config, ws_send_raw_state
from .settings import ws_get_settings, ws_update_settings
from .status import (
    ws_device_detail,
    ws_get_devices,
    ws_get_status,
    ws_publish_one_status,
    ws_related_sensors,
    ws_republish,
)
from .traces import ws_clear_traces, ws_get_trace, ws_list_traces, ws_subscribe_traces

_LOGGER = logging.getLogger(__name__)

__all__ = [
    "async_setup_websocket_api",
    # Re-exports for tests / external use
    "ws_add_entities",
    "ws_add_ha_device",
    "ws_auto_link_all",
    "ws_clear_all",
    "ws_clear_message_log",
    "ws_clear_state_diffs",
    "ws_clear_traces",
    "ws_device_detail",
    "ws_export",
    "ws_get_devices",
    "ws_get_settings",
    "ws_get_status",
    "ws_get_trace",
    "ws_import",
    "ws_list_categories",
    "ws_list_devices_for_category",
    "ws_list_state_diffs",
    "ws_list_traces",
    "ws_message_log",
    "ws_publish_one_status",
    "ws_raw_config",
    "ws_raw_states",
    "ws_related_sensors",
    "ws_remove_entities",
    "ws_republish",
    "ws_send_raw_config",
    "ws_send_raw_state",
    "ws_set_entity_links",
    "ws_set_type_override",
    "ws_subscribe_messages",
    "ws_subscribe_state_diffs",
    "ws_subscribe_traces",
    "ws_suggest_links",
    "ws_update_redefinitions",
    "ws_update_settings",
]


_COMMANDS = (
    # Status / device listing
    ws_get_devices,
    ws_get_status,
    ws_republish,
    ws_related_sensors,
    ws_publish_one_status,
    ws_device_detail,
    # Device-centric wizard (v1.26.0)
    ws_list_categories,
    ws_list_devices_for_category,
    ws_add_ha_device,
    # Entity management (raw / fallback)
    ws_add_entities,
    ws_remove_entities,
    ws_set_type_override,
    ws_clear_all,
    # Linking
    ws_set_entity_links,
    ws_auto_link_all,
    ws_suggest_links,
    # Import / export / redefinitions
    ws_export,
    ws_import,
    ws_update_redefinitions,
    # DevTools raw + message log
    ws_raw_config,
    ws_raw_states,
    ws_send_raw_config,
    ws_send_raw_state,
    ws_message_log,
    ws_clear_message_log,
    ws_subscribe_messages,
    # DevTools correlation timeline (v1.32.0)
    ws_list_traces,
    ws_get_trace,
    ws_clear_traces,
    ws_subscribe_traces,
    # DevTools state diffs (v1.33.0)
    ws_list_state_diffs,
    ws_clear_state_diffs,
    ws_subscribe_state_diffs,
    # Settings
    ws_get_settings,
    ws_update_settings,
)
"""All command handlers, in registration order."""


@callback
def async_setup_websocket_api(hass: HomeAssistant) -> None:
    """Register WebSocket API commands for the Sber MQTT Bridge panel.

    Idempotent — skips registration if already done for this HA instance.

    Args:
        hass: Home Assistant core instance.
    """
    marker = f"{DOMAIN}_ws_registered"
    if hass.data.get(marker):
        return
    hass.data[marker] = True
    for command in _COMMANDS:
        websocket_api.async_register_command(hass, command)
    _LOGGER.debug("Sber MQTT Bridge WebSocket API registered")
