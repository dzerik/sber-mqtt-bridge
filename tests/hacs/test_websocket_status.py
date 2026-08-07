"""Tests for the status WebSocket command — hub info consistency.

Guards against defaults drifting between the publisher (what the bridge
actually does) and the panel (what the user is shown) — issue #44 showed
``hub_auto_parent_id`` reported as ``True`` while the publisher default
is ``False``.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from custom_components.sber_mqtt_bridge.const import CONF_HUB_AUTO_PARENT, SETTINGS_DEFAULTS
from custom_components.sber_mqtt_bridge.websocket_api.status import ws_get_status


def _make_bridge() -> MagicMock:
    bridge = MagicMock()
    bridge.stats = {}
    bridge.unacknowledged_entities = []
    bridge.is_connected = True
    bridge.connection_phase = "connected"
    bridge.entities_count = 0
    bridge.enabled_entity_ids = []
    return bridge


def _sent_hub(connection: MagicMock) -> dict:
    return connection.send_result.call_args[0][1]["hub"]


@pytest.mark.asyncio
async def test_status_auto_parent_default_matches_publisher() -> None:
    """Without the option set, the panel must report the publisher's default.

    ``SETTINGS_DEFAULTS[CONF_HUB_AUTO_PARENT]`` is the single source of
    truth used by sber_publisher — status must not invent its own default.
    """
    hass = MagicMock()
    hass.config.location_name = "Home"
    connection = MagicMock()
    entry = MagicMock()
    entry.options = {}

    with patch(
        "custom_components.sber_mqtt_bridge.websocket_api.status.get_config_entry",
        return_value=entry,
    ):
        await ws_get_status.__wrapped__.__wrapped__(hass, connection, {"id": 1}, _make_bridge())

    assert _sent_hub(connection)["auto_parent_id"] is SETTINGS_DEFAULTS[CONF_HUB_AUTO_PARENT]


@pytest.mark.asyncio
async def test_status_auto_parent_reflects_option() -> None:
    """An explicitly set option is reported as-is."""
    hass = MagicMock()
    hass.config.location_name = "Home"
    connection = MagicMock()
    entry = MagicMock()
    entry.options = {CONF_HUB_AUTO_PARENT: True}

    with patch(
        "custom_components.sber_mqtt_bridge.websocket_api.status.get_config_entry",
        return_value=entry,
    ):
        await ws_get_status.__wrapped__.__wrapped__(hass, connection, {"id": 1}, _make_bridge())

    assert _sent_hub(connection)["auto_parent_id"] is True
