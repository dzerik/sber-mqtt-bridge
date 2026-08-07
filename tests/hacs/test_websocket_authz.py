"""Authorization + input-validation tests for the WebSocket API.

Three defence layers are guarded here:

1. **Admin gate** — every command registered by
   :func:`async_setup_websocket_api` must reject non-admin users with
   HA ``Unauthorized`` (→ ``unauthorized`` WS error) *before* the
   handler body runs, and must let admins through.  The sweep
   enumerates the *actually registered* handlers, so any new command
   that slips past the ``require_admin`` choke point fails the test.
2. **update_settings** — values are type/range-validated atomically;
   an invalid value must not touch ``entry.options`` (a poisoned
   option like ``debounce_delay="abc"`` would crash every subsequent
   ``async_setup_entry``).
3. **import** — a structurally invalid config payload must neither be
   written to ``entry.options`` nor trigger a reload (a broken import
   would otherwise brick the integration beyond UI repair).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import aiomqtt
import pytest
import voluptuous as vol
from homeassistant.exceptions import Unauthorized

import custom_components.sber_mqtt_bridge.websocket_api as ws_pkg
from custom_components.sber_mqtt_bridge.const import (
    CONF_ENTITY_LINKS,
    CONF_ENTITY_TYPE_OVERRIDES,
    CONF_EXPOSED_ENTITIES,
)
from custom_components.sber_mqtt_bridge.websocket_api import async_setup_websocket_api
from custom_components.sber_mqtt_bridge.websocket_api.io_export import ws_import
from custom_components.sber_mqtt_bridge.websocket_api.links import ws_set_entity_links
from custom_components.sber_mqtt_bridge.websocket_api.raw import ws_send_raw_config
from custom_components.sber_mqtt_bridge.websocket_api.settings import ws_update_settings

WS_REGISTRY_KEY = "websocket_api"
"""``hass.data`` key under which HA stores registered WS handlers."""

SBER_PREFIX = "sber_mqtt_bridge/"


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


def _make_hass() -> tuple[MagicMock, list[str]]:
    """Build a hass stub good enough for command registration + dispatch.

    Returns:
        ``(hass, scheduled_tasks)`` — the list collects names of
        background tasks created by ``async_response`` handlers (the
        coroutine itself is closed, we only care that the admin gate
        let execution proceed to scheduling).
    """
    hass = MagicMock()
    hass.data = {}
    # No loaded entries → requires_bridge/requires_entry send an error
    # instead of touching msg fields (deterministic sweep behaviour).
    hass.config_entries.async_loaded_entries = MagicMock(return_value=[])
    scheduled: list[str] = []

    def _schedule(coro: Any, name: str | None = None, **_kwargs: Any) -> None:
        scheduled.append(name or "task")
        coro.close()

    hass.async_create_background_task = _schedule
    hass.async_create_task = _schedule
    return hass, scheduled


def _make_connection(*, is_admin: bool) -> MagicMock:
    conn = MagicMock()
    conn.user = MagicMock()
    conn.user.is_admin = is_admin
    conn.send_result = MagicMock()
    conn.send_error = MagicMock()
    conn.send_message = MagicMock()
    conn.subscriptions = {}
    return conn


def _registered_sber_handlers(hass: MagicMock) -> dict[str, Any]:
    """Register the WS API on ``hass`` and return sber command handlers."""
    async_setup_websocket_api(hass)
    handlers = hass.data[WS_REGISTRY_KEY]
    return {cmd: handler for cmd, (handler, _schema) in handlers.items() if cmd.startswith(SBER_PREFIX)}


# ---------------------------------------------------------------------------
# 1. Admin gate
# ---------------------------------------------------------------------------


class TestAdminGate:
    """Every registered command must be admin-only."""

    def test_registered_set_matches_commands_tuple(self) -> None:
        """Anti-regress: registration covers exactly ``_COMMANDS`` (40+)."""
        hass, _ = _make_hass()
        registered = set(_registered_sber_handlers(hass))
        expected = {command._ws_command for command in ws_pkg._COMMANDS}
        assert registered == expected
        assert len(registered) >= 40

    def test_every_command_rejects_non_admin(self) -> None:
        """A non-admin caller gets Unauthorized and the handler body never runs.

        Iterates the real post-registration handlers, so removing the
        ``require_admin`` wrap (or registering an unprotected command by
        any other path) fails this test.
        """
        hass, scheduled = _make_hass()
        handlers = _registered_sber_handlers(hass)
        assert handlers, "no sber commands registered"

        unprotected: list[str] = []
        for cmd, handler in handlers.items():
            conn = _make_connection(is_admin=False)
            try:
                handler(hass, conn, {"id": 1, "type": cmd})
            except Unauthorized:
                pass
            else:
                unprotected.append(cmd)
                continue
            # The handler body must not have produced any output either.
            assert not conn.send_result.called, f"{cmd}: handler ran for non-admin"
            assert not conn.send_error.called, f"{cmd}: handler ran for non-admin"
            assert not conn.send_message.called, f"{cmd}: handler ran for non-admin"

        assert not unprotected, f"commands callable by non-admin users: {unprotected}"
        assert not scheduled, f"non-admin call scheduled handler tasks: {scheduled}"

    def test_every_command_rejects_missing_user(self) -> None:
        """``connection.user is None`` is treated as unauthorized too."""
        hass, _ = _make_hass()
        handlers = _registered_sber_handlers(hass)
        for cmd, handler in handlers.items():
            conn = _make_connection(is_admin=True)
            conn.user = None
            with pytest.raises(Unauthorized):
                handler(hass, conn, {"id": 1, "type": cmd})

    def test_every_command_admits_admin(self) -> None:
        """An admin passes the gate: handler body runs (or gets scheduled).

        Kills the "reject everyone" mutation (inverted condition) and
        the "swallow the call" mutation (wrapper that never invokes the
        inner handler): each command must either respond synchronously
        or schedule its async body.
        """
        hass, scheduled = _make_hass()
        handlers = _registered_sber_handlers(hass)

        broken: list[str] = []
        for cmd, handler in handlers.items():
            conn = _make_connection(is_admin=True)
            before = len(scheduled)
            try:
                handler(hass, conn, {"id": 1, "type": cmd})
            except Unauthorized:
                broken.append(f"{cmd}: admin rejected")
                continue
            body_ran = conn.send_result.called or conn.send_error.called or len(scheduled) > before
            if not body_ran:
                broken.append(f"{cmd}: handler body never ran for admin")

        assert not broken, broken


# ---------------------------------------------------------------------------
# 2. update_settings validation
# ---------------------------------------------------------------------------


@pytest.fixture
def connection() -> MagicMock:
    return _make_connection(is_admin=True)


@pytest.fixture
def hass() -> MagicMock:
    hass_ = MagicMock()
    hass_.config_entries.async_update_entry = MagicMock()
    hass_.config_entries.async_reload = AsyncMock()
    return hass_


def _make_entry(options: dict | None = None) -> MagicMock:
    entry = MagicMock()
    entry.entry_id = "test_entry"
    entry.options = options if options is not None else {"exposed_entities": ["light.a"]}
    entry.data = {}
    return entry


_SETTINGS_MODULE = "custom_components.sber_mqtt_bridge.websocket_api.settings"


class TestUpdateSettingsValidation:
    """Invalid settings must be rejected atomically, before persisting."""

    async def _call(self, hass: MagicMock, connection: MagicMock, settings: dict) -> MagicMock:
        entry = _make_entry()
        bridge = MagicMock()
        with (
            patch(f"{_SETTINGS_MODULE}.get_config_entry", return_value=entry),
            patch(f"{_SETTINGS_MODULE}.get_bridge", return_value=bridge),
        ):
            await ws_update_settings.__wrapped__(hass, connection, {"id": 1, "settings": settings})
        return bridge

    @pytest.mark.parametrize(
        "settings",
        [
            {"debounce_delay": "abc"},  # string → every later setup_entry would crash on float()
            {"debounce_delay": "0.5"},  # numeric string: strict number must NOT coerce it
            {"confirm_delay": True},  # bool is not a number (bool is an int subclass!)
            {"ack_audit_delay": "10"},  # int-string for a float key must not coerce either
            {"max_mqtt_payload_size": "1000"},  # numeric string is still a wrong type
            {"max_mqtt_payload_size": 0},  # would silently drop every inbound message
            {"message_log_size": -1},  # deque(maxlen=-1) → ValueError at apply time
            {"message_log_size": True},  # bool is not an int
            {"reconnect_interval_min": 0},  # tight reconnect loop against Sber broker
            {"sber_verify_ssl": "yes"},  # string is not a bool
            {"confirm_delay": -5},  # below range
            {"reconnect_interval_max": 10**9},  # above range
        ],
    )
    async def test_invalid_value_rejected_and_not_persisted(
        self, hass: MagicMock, connection: MagicMock, settings: dict
    ) -> None:
        bridge = await self._call(hass, connection, settings)

        assert connection.send_error.called
        assert connection.send_error.call_args[0][1] == "invalid_settings"
        hass.config_entries.async_update_entry.assert_not_called()
        bridge.apply_settings.assert_not_called()
        connection.send_result.assert_not_called()

    async def test_one_bad_key_rejects_whole_request(self, hass: MagicMock, connection: MagicMock) -> None:
        """Atomicity: a valid key mixed with a bad one writes nothing."""
        await self._call(hass, connection, {"debounce_delay": 0.2, "message_log_size": -5})

        hass.config_entries.async_update_entry.assert_not_called()
        assert connection.send_error.call_args[0][1] == "invalid_settings"

    async def test_valid_settings_persisted_and_applied(self, hass: MagicMock, connection: MagicMock) -> None:
        bridge = await self._call(
            hass,
            connection,
            {"debounce_delay": 0.2, "sber_verify_ssl": False, "message_log_size": 100},
        )

        assert hass.config_entries.async_update_entry.called
        saved = hass.config_entries.async_update_entry.call_args[1]["options"]
        assert saved["debounce_delay"] == 0.2
        assert saved["sber_verify_ssl"] is False
        assert saved["message_log_size"] == 100
        # Pre-existing options survive the merge.
        assert saved["exposed_entities"] == ["light.a"]
        bridge.apply_settings.assert_called_once_with(saved)
        connection.send_result.assert_called_once_with(1, {"success": True})

    async def test_unknown_keys_are_dropped(self, hass: MagicMock, connection: MagicMock) -> None:
        await self._call(hass, connection, {"bogus_key": 123, "debounce_delay": 0.3})

        saved = hass.config_entries.async_update_entry.call_args[1]["options"]
        assert "bogus_key" not in saved
        assert saved["debounce_delay"] == 0.3


# ---------------------------------------------------------------------------
# 3. import validation
# ---------------------------------------------------------------------------


_IO_MODULE = "custom_components.sber_mqtt_bridge.websocket_api.io_export"


class TestImportValidation:
    """A structurally broken import must not touch options or reload."""

    async def _call(self, hass: MagicMock, connection: MagicMock, config: dict) -> MagicMock:
        entry = _make_entry()
        with patch(f"{_IO_MODULE}.get_config_entry", return_value=entry):
            await ws_import.__wrapped__(hass, connection, {"id": 1, "config": config})
        return entry

    @pytest.mark.parametrize(
        "config",
        [
            {"entity_links": ["light.a"]},  # list → AttributeError in _apply_entity_links on reload
            {"entity_links": {"light.a": "sensor.t"}},  # value must be role→entity_id dict
            {"redefinitions": {"light.a": "kitchen"}},  # str → .get() crash in sber_protocol
            {"redefinitions": {"light.a": {"name": 42}}},  # non-string field value
            {"redefinitions": {"light.a": {"evil": "x"}}},  # unknown redefinition field
            {"exposed_entities": "light.a"},  # scalar instead of list
            {"exposed_entities": ["not an entity id"]},
            {"type_overrides": {"light.a": "no_such_category"}},
            {"type_overrides": {"light.a": {"nested": "dict"}}},
        ],
    )
    async def test_invalid_config_rejected_without_side_effects(
        self, hass: MagicMock, connection: MagicMock, config: dict
    ) -> None:
        await self._call(hass, connection, config)

        assert connection.send_error.called
        assert connection.send_error.call_args[0][1] == "invalid_config"
        hass.config_entries.async_update_entry.assert_not_called()
        hass.config_entries.async_reload.assert_not_called()
        connection.send_result.assert_not_called()

    async def test_valid_config_written_and_reloaded(self, hass: MagicMock, connection: MagicMock) -> None:
        config = {
            "version": 2,
            "exposed_entities": ["light.a", "switch.b"],
            "type_overrides": {"light.a": "light"},
            "redefinitions": {"light.a": {"name": "Лампа", "room": "Кухня"}},
            "entity_links": {"light.a": {"temperature": "sensor.t"}},
        }
        entry = await self._call(hass, connection, config)

        saved = hass.config_entries.async_update_entry.call_args[1]["options"]
        assert saved[CONF_EXPOSED_ENTITIES] == ["light.a", "switch.b"]
        assert saved[CONF_ENTITY_TYPE_OVERRIDES] == {"light.a": "light"}
        assert saved["redefinitions"] == {"light.a": {"name": "Лампа", "room": "Кухня"}}
        assert saved[CONF_ENTITY_LINKS] == {"light.a": {"temperature": "sensor.t"}}
        hass.config_entries.async_reload.assert_awaited_once_with(entry.entry_id)
        connection.send_result.assert_called_once_with(1, {"success": True})


# ---------------------------------------------------------------------------
# 4. set_entity_links schema
# ---------------------------------------------------------------------------


class TestSetEntityLinksSchema:
    """``links`` values must be entity ids — the schema HA actually applies."""

    def _msg(self, links: Any) -> dict:
        return {
            "id": 1,
            "type": "sber_mqtt_bridge/set_entity_links",
            "entity_id": "light.a",
            "links": links,
        }

    @pytest.mark.parametrize(
        "links",
        [
            {"temperature": "not an entity id"},
            {"temperature": {"nested": "dict"}},
            {"temperature": ["sensor.t"]},
            "sensor.t",
        ],
    )
    def test_malformed_links_rejected_by_schema(self, links: Any) -> None:
        with pytest.raises(vol.Invalid):
            ws_set_entity_links._ws_schema(self._msg(links))

    def test_valid_links_pass_schema(self) -> None:
        validated = ws_set_entity_links._ws_schema(self._msg({"temperature": "sensor.t"}))
        assert validated["links"] == {"temperature": "sensor.t"}


# ---------------------------------------------------------------------------
# 5. raw publish error mapping
# ---------------------------------------------------------------------------


_RAW_MODULE = "custom_components.sber_mqtt_bridge.websocket_api.raw"


class TestSendRawErrors:
    """MQTT failures surface as specific WS errors, not unknown_error."""

    def _bridge(self, exc: Exception | None = None) -> MagicMock:
        bridge = MagicMock()
        bridge._stats = SimpleNamespace(publish_errors=0)
        bridge.async_publish_raw = AsyncMock(side_effect=exc)
        return bridge

    async def _call(self, hass: MagicMock, connection: MagicMock, bridge: MagicMock, payload: str = "{}") -> None:
        with patch(f"{_RAW_MODULE}.get_bridge", return_value=bridge):
            await ws_send_raw_config.__wrapped__(hass, connection, {"id": 1, "payload": payload})

    async def test_mqtt_error_maps_to_publish_failed(self, hass: MagicMock, connection: MagicMock) -> None:
        bridge = self._bridge(aiomqtt.MqttError("broken pipe"))

        await self._call(hass, connection, bridge)

        assert connection.send_error.call_args[0][1] == "publish_failed"
        assert bridge._stats.publish_errors == 1
        connection.send_result.assert_not_called()

    async def test_runtime_error_maps_to_not_connected(self, hass: MagicMock, connection: MagicMock) -> None:
        bridge = self._bridge(RuntimeError("Not connected to MQTT"))

        await self._call(hass, connection, bridge)

        assert connection.send_error.call_args[0][1] == "not_connected"
        assert bridge._stats.publish_errors == 0

    async def test_invalid_json_rejected_before_publish(self, hass: MagicMock, connection: MagicMock) -> None:
        bridge = self._bridge()

        await self._call(hass, connection, bridge, payload="not json")

        assert connection.send_error.call_args[0][1] == "invalid_json"
        bridge.async_publish_raw.assert_not_called()

    async def test_success_path(self, hass: MagicMock, connection: MagicMock) -> None:
        bridge = self._bridge()

        await self._call(hass, connection, bridge)

        connection.send_result.assert_called_once_with(1, {"success": True})
        assert bridge._stats.publish_errors == 0
