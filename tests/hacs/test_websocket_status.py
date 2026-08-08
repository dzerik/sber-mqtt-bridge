"""Tests for the status WebSocket command — hub info consistency.

Guards against defaults drifting between the publisher (what the bridge
actually does) and the panel (what the user is shown) — issue #44 showed
``hub_auto_parent_id`` reported as ``True`` while the publisher default
is ``False``.

Commands are invoked through :func:`_ws_dispatch.dispatch`, which
replays HA's own ``ActiveConnection.async_handle`` pipeline (schema →
``require_admin`` → handler).  Calling
``ws_get_status.__wrapped__.__wrapped__`` would skip the schema
entirely, so a command that lost it would still look healthy here.
End-to-end coverage over a real socket — including the *registered*
admin guard, which ``dispatch`` only simulates — lives in
``test_websocket_full_stack.py``.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import voluptuous as vol
from _ws_dispatch import dispatch
from homeassistant.exceptions import Unauthorized

from custom_components.sber_mqtt_bridge.const import CONF_HUB_AUTO_PARENT, SETTINGS_DEFAULTS
from custom_components.sber_mqtt_bridge.websocket_api.status import ws_get_status

_STATUS_MODULE = "custom_components.sber_mqtt_bridge.websocket_api.status"


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


async def _call_status(options: dict) -> MagicMock:
    """Run ``ws_get_status`` with ``entry.options`` and return the connection."""
    hass = MagicMock()
    hass.config.location_name = "Home"
    connection = MagicMock()
    entry = MagicMock()
    entry.options = options

    with (
        patch(f"{_STATUS_MODULE}.get_config_entry", return_value=entry),
        patch(f"{_STATUS_MODULE}.get_bridge", return_value=_make_bridge()),
    ):
        await dispatch(ws_get_status, hass, connection, {"id": 1})
    return connection


@pytest.mark.asyncio
async def test_status_auto_parent_default_matches_publisher() -> None:
    """Without the option set, the panel must report the publisher's default.

    ``SETTINGS_DEFAULTS[CONF_HUB_AUTO_PARENT]`` is the single source of
    truth used by sber_publisher — status must not invent its own default.
    """
    connection = await _call_status({})

    assert _sent_hub(connection)["auto_parent_id"] is SETTINGS_DEFAULTS[CONF_HUB_AUTO_PARENT]


@pytest.mark.asyncio
async def test_status_auto_parent_reflects_option() -> None:
    """An explicitly set option is reported as-is."""
    connection = await _call_status({CONF_HUB_AUTO_PARENT: True})

    assert _sent_hub(connection)["auto_parent_id"] is True


@pytest.mark.asyncio
async def test_status_rejects_extra_keys() -> None:
    """The schema declares no fields besides ``type`` — nothing else passes."""
    hass = MagicMock()
    connection = MagicMock()

    with pytest.raises(vol.Invalid):
        await dispatch(ws_get_status, hass, connection, {"id": 1, "hub_id": "root"})

    connection.send_result.assert_not_called()


@pytest.mark.asyncio
async def test_status_is_admin_only() -> None:
    """A non-admin never reaches the handler body.

    Scope: this pins the *handler side* of the contract — the body must
    not run once ``require_admin`` raises, and nothing is sent back.
    The guard here is installed by :func:`_ws_dispatch.dispatch`, not
    observed from the registration, so it cannot detect
    ``async_setup_websocket_api`` dropping ``require_admin``; that is
    covered by ``test_websocket_authz.py::TestAdminGate`` and
    ``test_websocket_full_stack.py``'s sweep over the registered table.
    """
    hass = MagicMock()
    connection = MagicMock()

    with (
        patch(f"{_STATUS_MODULE}.get_bridge", return_value=_make_bridge()),
        pytest.raises(Unauthorized),
    ):
        await dispatch(ws_get_status, hass, connection, {"id": 1}, is_admin=False)

    connection.send_result.assert_not_called()
