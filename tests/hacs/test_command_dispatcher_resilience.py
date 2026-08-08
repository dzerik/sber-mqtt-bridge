"""Resilience tests for SberCommandDispatcher (review wave W1C).

Covers:
    * Per-entity failure isolation in ``handle_command`` — one buggy
      device class or malformed per-device payload must not prevent the
      other devices of a batch from executing, nor kill the echo ack
      and the delayed-confirm scheduling.
    * Type-confusion defense — non-dict ``cmd_data`` values and garbage
      ``states`` shapes must not crash the dispatcher (including the
      reconnect-grace logging path).
    * Cloud-sourced redefinition hygiene — ``change_group`` and
      ``rename_device`` payloads with non-string / oversized / empty
      values must never reach the persistent RedefinitionsStore;
      device_ids are stripped and value-less payloads do not create
      empty store records.
    * Caller-supplied ``Context`` propagation into HA service calls.
    * ``handle_global_config`` resilience against non-object JSON and
      garbage payloads (loop-level path in the bridge has no
      per-handler try/except for this handler).
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.core import Context

from custom_components.sber_mqtt_bridge.const import (
    CONF_SBER_BROKER,
    CONF_SBER_LOGIN,
    CONF_SBER_PASSWORD,
    CONF_SBER_PORT,
)
from custom_components.sber_mqtt_bridge.devices.relay import RelayEntity
from custom_components.sber_mqtt_bridge.sber_bridge import SberBridge


def _make_entry(options: dict | None = None) -> MagicMock:
    entry = MagicMock()
    entry.data = {
        CONF_SBER_LOGIN: "test",
        CONF_SBER_PASSWORD: "pass",
        CONF_SBER_BROKER: "broker.test",
        CONF_SBER_PORT: 8883,
    }
    entry.options = options or {}
    return entry


def _make_bridge() -> SberBridge:
    hass = MagicMock()
    hass.config.location_name = "My Home"
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock()
    bridge = SberBridge(hass, _make_entry())
    bridge._mqtt_client = AsyncMock()
    bridge._mqtt_service.publish = AsyncMock()
    bridge._connected = True
    return bridge


def _add_relay(bridge: SberBridge, entity_id: str, state: str = "off") -> RelayEntity:
    """Register a real RelayEntity filled from a plain HA state."""
    entity = RelayEntity({"entity_id": entity_id, "name": entity_id})
    entity.fill_by_ha_state({"entity_id": entity_id, "state": state, "attributes": {}})
    bridge._entities[entity_id] = entity
    bridge._enabled_entity_ids.append(entity_id)
    return entity


class _BrokenRelay(RelayEntity):
    """Relay whose command processing raises — simulates a device-class bug."""

    def process_cmd(self, cmd_data: dict) -> list:
        """Raise unconditionally to model a buggy device implementation."""
        raise RuntimeError("device class bug")


def _on_off_cmd(*entity_ids: str) -> bytes:
    """Build a Sber on_off=True command payload for the given entities."""
    return json.dumps(
        {
            "devices": {
                eid: {"states": [{"key": "on_off", "value": {"type": "BOOL", "bool_value": True}}]}
                for eid in entity_ids
            }
        }
    ).encode()


def _publishes(bridge: SberBridge, topic_suffix: str) -> list[dict]:
    """Return decoded payloads published to topics ending with ``topic_suffix``."""
    out: list[dict] = []
    for call in bridge._mqtt_service.publish.call_args_list:
        topic = call[0][0]
        if topic.endswith(topic_suffix):
            out.append(json.loads(call[0][1]))
    return out


def _service_targets(bridge: SberBridge) -> list[tuple[str, str, str]]:
    """Return (domain, service, target entity_id) for every HA service call made."""
    out = []
    for call in bridge._hass.services.async_call.call_args_list:
        kw = call.kwargs
        out.append((kw["domain"], kw["service"], kw["target"].get("entity_id")))
    return out


class TestBatchFailureIsolation:
    """One failing device must not break the rest of a multi-device command."""

    @pytest.mark.asyncio
    async def test_middle_entity_exception_does_not_break_batch(self) -> None:
        """switch.b raises inside process_cmd → a and c still executed, echo + confirms sent."""
        bridge = _make_bridge()
        bridge._hass.async_create_task = lambda coro, **_kw: asyncio.get_event_loop().create_task(coro)
        bridge._confirm_delay = 10.0  # keep confirm tasks alive during assertions

        _add_relay(bridge, "switch.a")
        broken = _BrokenRelay({"entity_id": "switch.b", "name": "switch.b"})
        broken.fill_by_ha_state({"entity_id": "switch.b", "state": "off", "attributes": {}})
        bridge._entities["switch.b"] = broken
        bridge._enabled_entity_ids.append("switch.b")
        _add_relay(bridge, "switch.c")

        # dict ordering guarantees a → b → c processing order.
        await bridge._handle_sber_command(_on_off_cmd("switch.a", "switch.b", "switch.c"))

        # The two healthy entities got their real HA service calls.
        assert _service_targets(bridge) == [
            ("switch", "turn_on", "switch.a"),
            ("switch", "turn_on", "switch.c"),
        ]

        # The echo ack still went out and covers the whole batch (the broken
        # entity's state snapshot works — only its command processing is broken).
        published = _publishes(bridge, "up/status")
        assert published, "Echo ack must still be published after a per-entity failure"
        assert {"switch.a", "switch.b", "switch.c"} <= set(published[0]["devices"])

        # Delayed confirms are scheduled for all commanded entities.
        assert set(bridge._confirm_tasks) == {"switch.a", "switch.b", "switch.c"}
        for task in bridge._confirm_tasks.values():
            assert not task.done(), "Confirm task must be alive (10s delay)"

        for task in bridge._confirm_tasks.values():
            task.cancel()
        await asyncio.sleep(0)

    @pytest.mark.asyncio
    async def test_unexpected_service_error_does_not_block_next_entity(self) -> None:
        """A non-HA exception escaping the service call is contained per-entity."""
        bridge = _make_bridge()
        _add_relay(bridge, "switch.a")
        _add_relay(bridge, "switch.b")
        # RuntimeError is NOT in _call_ha_service's caught tuple — it escapes
        # into the per-entity barrier.
        bridge._hass.services.async_call = AsyncMock(side_effect=[RuntimeError("boom"), None])

        await bridge._handle_sber_command(_on_off_cmd("switch.a", "switch.b"))

        # Second entity still got its service call despite the first blowing up.
        assert _service_targets(bridge) == [
            ("switch", "turn_on", "switch.a"),
            ("switch", "turn_on", "switch.b"),
        ]
        assert _publishes(bridge, "up/status"), "Echo ack must survive a service-call crash"


class TestTypeConfusionDefense:
    """Malformed per-device payload shapes must not crash the dispatcher."""

    @pytest.mark.asyncio
    async def test_non_dict_cmd_data_skipped_batch_continues(self) -> None:
        """A string cmd_data for one known entity is skipped; the other executes."""
        bridge = _make_bridge()
        _add_relay(bridge, "switch.a")
        _add_relay(bridge, "switch.b")

        payload = json.dumps(
            {
                "devices": {
                    "switch.a": "garbage-not-a-dict",
                    "switch.b": {"states": [{"key": "on_off", "value": {"type": "BOOL", "bool_value": True}}]},
                }
            }
        ).encode()

        await bridge._handle_sber_command(payload)

        assert _service_targets(bridge) == [("switch", "turn_on", "switch.b")]
        published = _publishes(bridge, "up/status")
        assert published, "Echo ack must still be sent when one entry is type-confused"
        assert "switch.b" in published[0]["devices"]

    @pytest.mark.asyncio
    async def test_garbage_states_shape_does_not_kill_batch(self) -> None:
        """states as a string (iterates into chars) is contained per-entity."""
        bridge = _make_bridge()
        _add_relay(bridge, "switch.a")
        _add_relay(bridge, "switch.b")

        payload = json.dumps(
            {
                "devices": {
                    "switch.a": {"states": "oops"},
                    "switch.b": {"states": [{"key": "on_off", "value": {"type": "BOOL", "bool_value": True}}]},
                }
            }
        ).encode()

        await bridge._handle_sber_command(payload)

        assert _service_targets(bridge) == [("switch", "turn_on", "switch.b")]
        assert _publishes(bridge, "up/status")

    @pytest.mark.asyncio
    async def test_reconnect_grace_survives_non_dict_cmd_data(self) -> None:
        """During ack-grace, a type-confused batch still triggers state re-publish.

        Calls the dispatcher layer directly with an already-parsed devices
        dict: the parser sanitizes non-dict entries upstream, but the
        dispatcher must not rely on that (defense in depth).
        """
        bridge = _make_bridge()
        _add_relay(bridge, "switch.a", state="on")
        # Arm the *real* guard (30s grace) instead of stubbing it out, so
        # the dispatcher is exercised against the production ack semantics.
        bridge._ack_audit.activate_post_connect()
        assert bridge._ack_audit.is_awaiting is True

        devices = {"switch.a": 42, "switch.b": {"states": ["oops", {"key": "on_off"}]}}
        rejected = await bridge._command_dispatcher._handle_reconnect_grace(devices)

        # Command rejected: no HA service call, but the authoritative HA
        # state was re-published so Sber's view converges.
        assert rejected is True
        bridge._hass.services.async_call.assert_not_called()
        published = _publishes(bridge, "up/status")
        assert published, "Grace path must re-publish states even for malformed cmd_data"
        assert "switch.a" in published[0]["devices"]

    @pytest.mark.asyncio
    async def test_process_one_entity_rejects_non_dict_directly(self, caplog: pytest.LogCaptureFixture) -> None:
        """Dispatcher's own guard: non-dict cmd_data for a known entity → no crash, no call.

        The rejection must come from the explicit type guard (clean WARNING),
        not from the crash barrier (stack trace) — device classes are never
        invoked with garbage input.
        """
        import logging as _logging

        bridge = _make_bridge()
        _add_relay(bridge, "switch.a")

        with caplog.at_level(_logging.WARNING, logger="custom_components.sber_mqtt_bridge.command_dispatcher"):
            result = await bridge._command_dispatcher._process_one_entity("switch.a", ["garbage"], Context())

        assert result is False
        bridge._hass.services.async_call.assert_not_called()
        assert "invalid payload type" in caplog.text, "Type guard must reject garbage explicitly"
        assert "Failed to process Sber command" not in caplog.text, (
            "Garbage must be rejected by the guard, not swallowed by the crash barrier"
        )

    @pytest.mark.asyncio
    async def test_handle_command_survives_parser_regression(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """If the parser ever leaks non-dict entries again, the echo ack must survive.

        Simulates an upstream sanitization regression by stubbing
        parse_sber_command to return a type-confused devices dict; the
        dispatcher must still execute the healthy entity and publish the
        echo ack instead of raising.
        """
        bridge = _make_bridge()
        _add_relay(bridge, "switch.a")
        _add_relay(bridge, "switch.b")

        from custom_components.sber_mqtt_bridge import command_dispatcher as cd

        monkeypatch.setattr(
            cd,
            "parse_sber_command",
            lambda payload: {
                "devices": {
                    "switch.a": "garbage-not-a-dict",
                    "switch.b": {"states": [{"key": "on_off", "value": {"type": "BOOL", "bool_value": True}}]},
                }
            },
        )

        await bridge._handle_sber_command(b"{}")

        assert _service_targets(bridge) == [("switch", "turn_on", "switch.b")]
        published = _publishes(bridge, "up/status")
        assert published, "Echo must survive a type-confused devices entry"
        assert "switch.b" in published[0]["devices"]
        assert "switch.a" not in published[0]["devices"]


class TestCallerSuppliedContext:
    """A caller-supplied Context must be attributed to the HA service calls."""

    @pytest.mark.asyncio
    async def test_caller_context_reaches_service_calls(self) -> None:
        """handle_command(payload, context=ctx) → hass.services.async_call gets that exact ctx."""
        bridge = _make_bridge()
        _add_relay(bridge, "switch.a")
        ctx = Context(user_id="abcdef0123456789")

        await bridge._command_dispatcher.handle_command(_on_off_cmd("switch.a"), context=ctx)

        assert _service_targets(bridge) == [("switch", "turn_on", "switch.a")]
        kw = bridge._hass.services.async_call.call_args.kwargs
        assert kw["context"] is ctx, "Caller-supplied context must reach the HA service call"

    @pytest.mark.asyncio
    async def test_omitted_context_creates_fresh_anonymous_one(self) -> None:
        """Without an explicit context a fresh anonymous Context is attached."""
        bridge = _make_bridge()
        _add_relay(bridge, "switch.a")

        await bridge._command_dispatcher.handle_command(_on_off_cmd("switch.a"))

        kw = bridge._hass.services.async_call.call_args.kwargs
        assert isinstance(kw["context"], Context)
        assert kw["context"].user_id is None


class TestGlobalConfigHardening:
    """Malformed global_config payloads must not raise (bridge calls this loop-level)."""

    def test_json_list_payload_does_not_raise(self, caplog: pytest.LogCaptureFixture) -> None:
        """A JSON array at the top level is rejected without an AttributeError."""
        import logging as _logging

        bridge = _make_bridge()
        with caplog.at_level(_logging.INFO):
            bridge._handle_global_config(b"[1, 2, 3]")
        assert "Sber HTTP API endpoint" not in caplog.text

    def test_not_json_payload_does_not_raise(self, caplog: pytest.LogCaptureFixture) -> None:
        """Non-JSON garbage is rejected without a JSONDecodeError escaping."""
        import logging as _logging

        bridge = _make_bridge()
        with caplog.at_level(_logging.INFO):
            bridge._handle_global_config(b"\x00not json at all")
        assert "Sber HTTP API endpoint" not in caplog.text

    def test_valid_endpoint_still_logged(self, caplog: pytest.LogCaptureFixture) -> None:
        """The happy path still surfaces the endpoint (hardening is not over-rejecting).

        Asserts on the log record's argument rather than a substring of the
        formatted text: exact equality is the stronger check (a truncated or
        mangled endpoint would still pass a substring test), and it keeps
        CodeQL from reading the assertion as URL-substring sanitization.
        """
        import logging as _logging

        endpoint = "https://api.sber.test"
        bridge = _make_bridge()
        with caplog.at_level(_logging.INFO):
            bridge._handle_global_config(json.dumps({"http_api_endpoint": endpoint}).encode())

        records = [r for r in caplog.records if r.getMessage().startswith("Sber HTTP API endpoint")]
        assert len(records) == 1, "endpoint must be logged exactly once"
        assert records[0].args == (endpoint,)


class TestChangeGroupValidation:
    """Cloud change_group values must be sanitized before persisting."""

    @pytest.mark.asyncio
    async def test_non_string_values_not_persisted(self) -> None:
        bridge = _make_bridge()
        payload = json.dumps({"device_id": "light.a", "home": 123, "room": {"$": 1}}).encode()
        await bridge._handle_change_group(payload)

        redef = bridge._redefinitions.get("light.a", {})
        assert "home" not in redef
        assert "room" not in redef

    @pytest.mark.asyncio
    async def test_none_values_clear_instead_of_storing_none(self) -> None:
        bridge = _make_bridge()
        bridge._redefinitions["light.a"] = {"room": "Old Room", "name": "Keep"}

        payload = json.dumps({"device_id": "light.a", "home": None, "room": None}).encode()
        await bridge._handle_change_group(payload)

        redef = bridge._redefinitions["light.a"]
        assert None not in redef.values(), "None must never be persisted"
        assert "room" not in redef
        assert redef["name"] == "Keep", "Unrelated keys must survive a group change"

    @pytest.mark.asyncio
    async def test_overlong_string_rejected(self) -> None:
        bridge = _make_bridge()
        payload = json.dumps({"device_id": "light.a", "home": "Home", "room": "x" * 500}).encode()
        await bridge._handle_change_group(payload)

        redef = bridge._redefinitions.get("light.a", {})
        assert "room" not in redef, "500-char room must be rejected"
        assert redef.get("home") == "Home", "Valid sibling value must still be stored"

    @pytest.mark.asyncio
    async def test_valid_values_stripped_and_persist_scheduled(self) -> None:
        bridge = _make_bridge()
        payload = json.dumps({"device_id": "light.a", "home": " My House ", "room": " Bedroom "}).encode()
        await bridge._handle_change_group(payload)

        redef = bridge._redefinitions["light.a"]
        assert redef["home"] == "My House"
        assert redef["room"] == "Bedroom"
        # Debounced persistence to ConfigEntry.options was armed.
        assert bridge._hass.loop.call_later.called

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "payload",
        [
            json.dumps({"device_id": 123, "room": "Bedroom"}).encode(),
            json.dumps({"device_id": "", "room": "Bedroom"}).encode(),
            json.dumps({"device_id": "   ", "room": "Bedroom"}).encode(),
            json.dumps({"device_id": "x" * 600, "room": "Bedroom"}).encode(),
            json.dumps({"room": "Bedroom"}).encode(),
            json.dumps([1, 2, 3]).encode(),
            b"not json at all",
        ],
        ids=["int-id", "empty-id", "blank-id", "overlong-id", "missing-id", "list-payload", "not-json"],
    )
    async def test_invalid_payloads_leave_store_untouched(self, payload: bytes) -> None:
        bridge = _make_bridge()
        await bridge._handle_change_group(payload)
        assert bridge._redefinitions == {}

    @pytest.mark.asyncio
    async def test_device_id_is_stripped_before_storing(self) -> None:
        """A padded ' light.a ' key must be stored under the real entity_id."""
        bridge = _make_bridge()
        payload = json.dumps({"device_id": "  light.a  ", "room": "Bedroom"}).encode()
        await bridge._handle_change_group(payload)

        assert "  light.a  " not in bridge._redefinitions, "Padded key must not leak into the store"
        assert bridge._redefinitions["light.a"]["room"] == "Bedroom"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "payload_fields",
        [
            {"home": None, "room": None},
            {"home": 123, "room": {"$": 1}},
            {},
        ],
        ids=["both-none", "both-invalid", "no-fields"],
    )
    async def test_valueless_payload_does_not_create_empty_record(self, payload_fields: dict) -> None:
        """Valid device_id but no usable values → no {} record, no persist armed."""
        bridge = _make_bridge()
        payload = json.dumps({"device_id": "light.ghost", **payload_fields}).encode()
        await bridge._handle_change_group(payload)

        assert bridge._redefinitions == {}, "Cloud must not create empty records for arbitrary ids"
        assert not bridge._hass.loop.call_later.called, "Persist must not be armed for a no-op"

    @pytest.mark.asyncio
    async def test_valueless_payload_still_clears_existing_record(self) -> None:
        """Clearing semantics survive the empty-record guard when a record exists."""
        bridge = _make_bridge()
        bridge._redefinitions["light.a"] = {"room": "Old Room"}

        payload = json.dumps({"device_id": "light.a", "home": None, "room": None}).encode()
        await bridge._handle_change_group(payload)

        assert "room" not in bridge._redefinitions.get("light.a", {})


class TestRenameDeviceValidation:
    """Cloud rename_device values must be sanitized before persisting."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "new_name",
        [{"$": 1}, ["Night Lamp"], 42, True, "", "   ", "x" * 500],
        ids=["dict", "list", "int", "bool", "empty", "blank", "overlong"],
    )
    async def test_invalid_new_name_not_persisted(self, new_name: object) -> None:
        bridge = _make_bridge()
        payload = json.dumps({"device_id": "switch.lamp", "new_name": new_name}).encode()
        await bridge._handle_rename_device(payload)

        assert "name" not in bridge._redefinitions.get("switch.lamp", {})

    @pytest.mark.asyncio
    async def test_valid_name_stored_stripped(self) -> None:
        bridge = _make_bridge()
        payload = json.dumps({"device_id": "switch.lamp", "new_name": "  Night Lamp  "}).encode()
        await bridge._handle_rename_device(payload)

        assert bridge._redefinitions["switch.lamp"]["name"] == "Night Lamp"
        assert bridge._hass.loop.call_later.called

    @pytest.mark.asyncio
    async def test_invalid_device_id_ignored(self) -> None:
        bridge = _make_bridge()
        payload = json.dumps({"device_id": None, "new_name": "Night Lamp"}).encode()
        await bridge._handle_rename_device(payload)
        assert bridge._redefinitions == {}

    @pytest.mark.asyncio
    async def test_existing_name_survives_invalid_rename(self) -> None:
        """A garbage rename must not clobber a previously stored valid name."""
        bridge = _make_bridge()
        bridge._redefinitions["switch.lamp"] = {"name": "Good Name"}

        payload = json.dumps({"device_id": "switch.lamp", "new_name": {"evil": 1}}).encode()
        await bridge._handle_rename_device(payload)

        assert bridge._redefinitions["switch.lamp"]["name"] == "Good Name"
