"""Tests for the narrow collaborator ports introduced by the W5A refactor.

``SberPublisher``, ``SberCommandDispatcher`` and ``RedefinitionsStore`` no
longer receive the whole :class:`SberBridge`; they get explicit dependency
bundles (``PublisherDeps`` / ``DispatcherDeps``) or plain HA objects.

Every test here fails if one of the migrated wires is cut:

* dispatcher loses the entity registry, the publisher, the ack audit,
  the redefinitions store, the confirm scheduler or the repairs hook;
* the store stops seeing the entry / loop it was built with;
* :meth:`BaseEntity.mark_state_published` stops honouring the explicit
  snapshot (the lost-update guard).
"""

from __future__ import annotations

import ast
import asyncio
import json
import pathlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.sber_mqtt_bridge import sber_bridge as sber_bridge_module
from custom_components.sber_mqtt_bridge.bridge_ports import StatsPort
from custom_components.sber_mqtt_bridge.command_dispatcher import (
    DispatcherDeps,
    SberCommandDispatcher,
)
from custom_components.sber_mqtt_bridge.const import (
    CONF_SBER_BROKER,
    CONF_SBER_LOGIN,
    CONF_SBER_PASSWORD,
    CONF_SBER_PORT,
)
from custom_components.sber_mqtt_bridge.devices.relay import RelayEntity
from custom_components.sber_mqtt_bridge.redefinitions_store import RedefinitionsStore
from custom_components.sber_mqtt_bridge.sber_bridge import BridgeStats, SberBridge


def _make_entry() -> MagicMock:
    entry = MagicMock()
    entry.data = {
        CONF_SBER_LOGIN: "test",
        CONF_SBER_PASSWORD: "pass",
        CONF_SBER_BROKER: "broker.test",
        CONF_SBER_PORT: 8883,
    }
    entry.options = {}
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
    entity = RelayEntity({"entity_id": entity_id, "name": entity_id})
    entity.fill_by_ha_state({"entity_id": entity_id, "state": state, "attributes": {}})
    bridge._entities[entity_id] = entity
    bridge._enabled_entity_ids.append(entity_id)
    return entity


def _on_off_cmd(*entity_ids: str) -> bytes:
    return json.dumps(
        {
            "devices": {
                eid: {"states": [{"key": "on_off", "value": {"type": "BOOL", "bool_value": True}}]}
                for eid in entity_ids
            }
        }
    ).encode()


def _status_payloads(bridge: SberBridge) -> list[dict]:
    return [
        json.loads(call.args[1])
        for call in bridge._mqtt_service.publish.await_args_list
        if call.args[0].endswith("/up/status")
    ]


# ---------------------------------------------------------------------------
# Architectural boundary
# ---------------------------------------------------------------------------

COLLABORATOR_MODULES = (
    "sber_publisher",
    "command_dispatcher",
    "redefinitions_store",
    "entity_registry",
    "devtools_hub",
    "ack_audit",
    "ha_state_forwarder",
)


class TestCollaboratorsDoNotDependOnTheBridge:
    """The bridge→collaborator edge must stay one-way, imports included."""

    def test_no_collaborator_module_imports_sber_bridge(self) -> None:
        """A re-introduced ``from .sber_bridge import ...`` restores the cycle.

        Even a ``TYPE_CHECKING``-only import means the collaborator is once
        again typed against bridge internals; the whole point of the ports
        is that these modules are usable (and testable) without a bridge.
        """
        pkg = pathlib.Path(sber_bridge_module.__file__).parent
        offenders: list[str] = []
        for name in COLLABORATOR_MODULES:
            tree = ast.parse((pkg / f"{name}.py").read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module and "sber_bridge" in node.module:
                    offenders.append(f"{name} → from {node.module}")
                elif isinstance(node, ast.Import):
                    offenders += [f"{name} → import {a.name}" for a in node.names if "sber_bridge" in a.name]
        assert offenders == [], f"collaborators depend on the bridge again: {offenders}"


# ---------------------------------------------------------------------------
# StatsPort structural contract
# ---------------------------------------------------------------------------


def _stats_attributes_used_in(path: pathlib.Path) -> set[str]:
    """Return every ``stats`` member a module reads or writes.

    Recognises both access shapes used by the collaborators:
    ``<anything>.stats.<member>`` (e.g. ``deps.stats.messages_sent``) and
    a local alias bound to it (``stats = self._deps.stats`` followed by
    ``stats.errors_from_sber``).

    Args:
        path: Source file of the collaborator module to scan.

    Returns:
        Set of member names touched on the stats object.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))

    aliases: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Attribute):
            continue
        if node.value.attr != "stats":
            continue
        aliases |= {t.id for t in node.targets if isinstance(t, ast.Name)}

    used: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        owner = node.value
        direct = isinstance(owner, ast.Attribute) and owner.attr == "stats"
        aliased = isinstance(owner, ast.Name) and owner.id in aliases
        if direct or aliased:
            used.add(node.attr)
    return used


class TestStatsPortContract:
    """Collaborators are typed against ``StatsPort``, not ``BridgeStats``."""

    def test_bridge_stats_still_satisfies_the_port(self) -> None:
        """Dropping a counter from BridgeStats silently breaks the typed port."""
        stats = BridgeStats()
        missing = [name for name in StatsPort.__annotations__ if not hasattr(stats, name)]
        assert missing == [], f"BridgeStats no longer provides: {missing}"

    def test_port_covers_every_counter_the_collaborators_bump(self) -> None:
        """Guard against the port drifting narrower than real usage.

        The required set is *derived from the source* of the two
        collaborators rather than restated by hand, so the drift this
        guards against — a collaborator starting to touch a counter that
        the port does not declare — actually fails the test.
        """
        pkg = pathlib.Path(sber_bridge_module.__file__).parent
        used: set[str] = set()
        for name in ("sber_publisher", "command_dispatcher"):
            used |= _stats_attributes_used_in(pkg / f"{name}.py")

        # Sanity: the extractor must actually see something, otherwise the
        # subset assertion below would pass vacuously forever.
        assert len(used) >= 5, f"stats-usage extractor found almost nothing: {used}"

        undeclared = used - set(StatsPort.__annotations__)
        assert undeclared == set(), f"collaborators touch counters missing from StatsPort: {sorted(undeclared)}"


# ---------------------------------------------------------------------------
# Dispatcher deps
# ---------------------------------------------------------------------------


class TestDispatcherHasNoBridgeReference:
    """The friend-class coupling is gone at the object level."""

    def test_dispatcher_stores_only_a_deps_bundle(self) -> None:
        bridge = _make_bridge()
        dispatcher = bridge._command_dispatcher
        assert isinstance(dispatcher._deps, DispatcherDeps)
        assert not hasattr(dispatcher, "_bridge")
        assert bridge not in vars(dispatcher).values()

    def test_deps_bundle_is_immutable(self) -> None:
        """A frozen bundle keeps the wiring auditable at one place."""
        bridge = _make_bridge()
        with pytest.raises((AttributeError, TypeError)):
            bridge._command_dispatcher._deps.publisher = None


class TestDispatcherEntityRegistryWire:
    """``get_entities`` / ``get_enabled_entity_ids`` must be late-bound."""

    async def test_entity_added_after_construction_is_commandable(self) -> None:
        bridge = _make_bridge()
        _add_relay(bridge, "switch.lamp", "off")

        await bridge._handle_sber_command(_on_off_cmd("switch.lamp"))

        assert bridge._hass.services.async_call.await_count == 1
        kwargs = bridge._hass.services.async_call.await_args.kwargs
        assert kwargs["target"]["entity_id"] == "switch.lamp"

    async def test_status_request_for_all_acks_current_enabled_set(self) -> None:
        """An empty status_request must ack the *current* enabled list."""
        bridge = _make_bridge()
        _add_relay(bridge, "switch.lamp")
        _add_relay(bridge, "switch.fan")

        await bridge._handle_sber_status_request(b"{}")

        assert bridge._stats.acknowledged_entities == {"switch.lamp", "switch.fan"}


class TestDispatcherStatsWire:
    """Counters bumped through ``deps.stats`` reach the bridge's own bag."""

    async def test_incoming_command_acks_its_entity(self) -> None:
        """A command is proof Sber knows the entity — it stops being unacked."""
        bridge = _make_bridge()
        _add_relay(bridge, "switch.lamp", "off")
        assert bridge.unacknowledged_entities == ["switch.lamp"]

        await bridge._handle_sber_command(_on_off_cmd("switch.lamp"))

        assert "switch.lamp" in bridge._stats.acknowledged_entities
        assert bridge.unacknowledged_entities == []

    async def test_command_for_an_unknown_entity_still_counts_as_an_ack(self) -> None:
        """Sber addressing a stale ID proves the config reached it."""
        bridge = _make_bridge()
        _add_relay(bridge, "switch.lamp", "off")

        await bridge._handle_sber_command(_on_off_cmd("switch.ghost"))

        assert "switch.ghost" in bridge._stats.acknowledged_entities
        bridge._hass.services.async_call.assert_not_awaited()


class TestDispatcherDevToolsWire:
    """The dispatcher drives DevTools housekeeping through the shared hub."""

    async def test_command_sweeps_stale_traces(self) -> None:
        """Trace housekeeping rides the command path — without it traces leak."""
        bridge = _make_bridge()
        _add_relay(bridge, "switch.lamp", "off")
        traces = bridge._devtools.trace_collector
        traces.set_trace_timeout(0.0)
        traces.begin(
            trace_id="stale-trace",
            trigger="sber_command",
            entity_ids=["switch.lamp"],
            topic="down/commands",
            payload={},
        )
        assert "stale-trace" in traces._active

        await bridge._handle_sber_command(_on_off_cmd("switch.lamp"))

        assert "stale-trace" not in traces._active, "stale trace was never swept"


class TestDispatcherPublisherWire:
    """The dispatcher reaches Sber only through the injected publisher."""

    async def test_status_request_publishes_states(self) -> None:
        bridge = _make_bridge()
        _add_relay(bridge, "switch.lamp", "on")

        await bridge._handle_sber_status_request(json.dumps({"devices": ["switch.lamp"]}).encode())

        payloads = _status_payloads(bridge)
        assert payloads, "status_request must reach the publisher"
        assert "switch.lamp" in payloads[0]["devices"]

    async def test_config_request_publishes_config(self) -> None:
        bridge = _make_bridge()
        _add_relay(bridge, "switch.lamp")

        await bridge._handle_sber_config_request()

        topics = [call.args[0] for call in bridge._mqtt_service.publish.await_args_list]
        assert any(t.endswith("/up/config") for t in topics)


class TestDispatcherAckAuditWire:
    """The ack audit is consulted through the deps bundle, not the bridge."""

    async def test_command_is_rejected_while_the_guard_is_armed(self) -> None:
        bridge = _make_bridge()
        _add_relay(bridge, "switch.lamp", "on")
        bridge._ack_audit.activate_post_connect()

        await bridge._handle_sber_command(_on_off_cmd("switch.lamp"))

        bridge._hass.services.async_call.assert_not_awaited()
        assert _status_payloads(bridge), "grace path must still re-publish authoritative state"

    async def test_status_request_clears_the_guard(self) -> None:
        bridge = _make_bridge()
        _add_relay(bridge, "switch.lamp", "on")
        bridge._ack_audit.activate_post_connect()

        await bridge._handle_sber_status_request(b"{}")

        assert bridge._ack_audit.is_awaiting is False


class TestDispatcherConfirmSchedulerWire:
    """Delayed-confirm task ownership moved to the bridge."""

    async def test_command_schedules_a_confirm_task_owned_by_the_bridge(self) -> None:
        bridge = _make_bridge()
        bridge._hass.async_create_task = lambda coro, **_kw: asyncio.get_event_loop().create_task(coro)
        bridge._confirm_delay = 10.0
        _add_relay(bridge, "switch.lamp")

        await bridge._handle_sber_command(_on_off_cmd("switch.lamp"))

        task = bridge._confirm_tasks.get("switch.lamp")
        assert task is not None, "dispatcher lost its confirm scheduler"
        assert not task.done()
        task.cancel()
        await asyncio.sleep(0)

    async def test_second_command_replaces_and_cancels_the_first_confirm(self) -> None:
        """Dedup lives on the bridge now — a rapid re-command must not double-fire."""
        bridge = _make_bridge()
        bridge._hass.async_create_task = lambda coro, **_kw: asyncio.get_event_loop().create_task(coro)
        bridge._confirm_delay = 10.0
        _add_relay(bridge, "switch.lamp")

        await bridge._handle_sber_command(_on_off_cmd("switch.lamp"))
        first = bridge._confirm_tasks["switch.lamp"]
        await bridge._handle_sber_command(_on_off_cmd("switch.lamp"))
        second = bridge._confirm_tasks["switch.lamp"]

        assert second is not first
        await asyncio.sleep(0)
        assert first.cancelled(), "previous confirm task was left running"
        second.cancel()
        await asyncio.sleep(0)


class TestDispatcherRedefinitionsWire:
    """change_group / rename_device write through the injected store."""

    async def test_rename_reaches_the_store(self) -> None:
        bridge = _make_bridge()
        _add_relay(bridge, "switch.lamp")

        await bridge._handle_rename_device(json.dumps({"device_id": "switch.lamp", "new_name": "Ночник"}).encode())

        assert bridge._redef_store.raw["switch.lamp"]["name"] == "Ночник"

    async def test_valueless_change_group_uses_store_membership_probe(self) -> None:
        """``store.has()`` decides whether an empty payload may clear a record."""
        bridge = _make_bridge()
        _add_relay(bridge, "switch.lamp")
        bridge._redef_store.replace({"switch.lamp": {"room": "Old"}})

        await bridge._handle_change_group(json.dumps({"device_id": "switch.lamp", "room": 42}).encode())

        # Known entity → invalid value clears the stale key instead of keeping it.
        assert "room" not in bridge._redef_store.raw["switch.lamp"]

    async def test_valueless_change_group_for_unknown_id_creates_nothing(self) -> None:
        bridge = _make_bridge()

        await bridge._handle_change_group(json.dumps({"device_id": "switch.ghost", "room": None}).encode())

        assert bridge._redef_store.raw == {}


class TestDispatcherIsIndependentlyConstructible:
    """The whole point of the bundle: no bridge needed to build a dispatcher."""

    def _deps(self, bridge: SberBridge, **overrides: object) -> DispatcherDeps:
        base = {
            "hass": bridge._hass,
            "stats": bridge._stats,
            "ack_audit": bridge._ack_audit,
            "publisher": bridge._publisher,
            "redefinitions": bridge._redef_store,
            "devtools": bridge._devtools,
            "get_entities": lambda: bridge._entities,
            "get_enabled_entity_ids": lambda: bridge._enabled_entity_ids,
            "schedule_confirm": lambda _eid: None,
            "refresh_repair_issues": lambda: None,
        }
        return DispatcherDeps(**{**base, **overrides})

    async def test_status_request_calls_the_injected_repairs_hook(self) -> None:
        bridge = _make_bridge()
        _add_relay(bridge, "switch.lamp")
        calls: list[int] = []
        dispatcher = SberCommandDispatcher(self._deps(bridge, refresh_repair_issues=lambda: calls.append(1)))

        await dispatcher.handle_status_request(b"{}")

        assert calls == [1], "repairs hook was not invoked through the deps bundle"

    async def test_command_calls_the_injected_confirm_scheduler(self) -> None:
        bridge = _make_bridge()
        _add_relay(bridge, "switch.lamp")
        scheduled: list[str] = []
        dispatcher = SberCommandDispatcher(self._deps(bridge, schedule_confirm=scheduled.append))

        await dispatcher.handle_command(_on_off_cmd("switch.lamp"))

        assert scheduled == ["switch.lamp"]

    async def test_error_payload_lands_in_the_injected_stats(self) -> None:
        bridge = _make_bridge()
        stats = SimpleNamespace(errors_from_sber=0, last_error_detail="")
        dispatcher = SberCommandDispatcher(self._deps(bridge, stats=stats))

        dispatcher.handle_error(b'{"code": 7}')

        assert stats.errors_from_sber == 1
        assert "7" in stats.last_error_detail
        assert bridge._stats.errors_from_sber == 0, "dispatcher wrote to the wrong stats object"


# ---------------------------------------------------------------------------
# RedefinitionsStore without a bridge
# ---------------------------------------------------------------------------


class TestRedefinitionsStoreStandsAlone:
    """The store is constructible from HA objects only."""

    def test_constructor_takes_hass_and_entry(self) -> None:
        hass = MagicMock()
        entry = MagicMock()
        entry.options = {}
        store = RedefinitionsStore(hass, entry)
        assert not hasattr(store, "_bridge")

    def test_has_reports_membership(self) -> None:
        hass = MagicMock()
        entry = MagicMock()
        entry.options = {}
        store = RedefinitionsStore(hass, entry)
        assert store.has("light.a") is False
        store.replace({"light.a": {"name": "A"}})
        assert store.has("light.a") is True
        assert store.has("light.b") is False

    def test_replace_does_not_mark_the_store_dirty(self) -> None:
        """A reload swap comes *from* options — re-persisting it is churn."""
        hass = MagicMock()
        entry = MagicMock()
        entry.options = {}
        store = RedefinitionsStore(hass, entry)

        store.replace({"light.a": {"name": "A"}})
        store.flush_now()

        hass.config_entries.async_update_entry.assert_not_called()

    async def test_update_persists_through_the_injected_entry(self) -> None:
        hass = MagicMock()
        entry = MagicMock()
        entry.options = {"exposed_entities": ["light.a"]}
        store = RedefinitionsStore(hass, entry)

        await store.async_update("light.a", {"name": "A"})
        store.flush_now()

        hass.config_entries.async_update_entry.assert_called_once()
        _args, kwargs = hass.config_entries.async_update_entry.call_args
        assert kwargs["options"]["redefinitions"] == {"light.a": {"name": "A"}}
        assert kwargs["options"]["exposed_entities"] == ["light.a"], "existing options were dropped"


class TestBridgeReloadUsesTheStore:
    """The bridge no longer owns a redefinitions dict of its own."""

    def test_reload_swap_goes_through_the_store(self) -> None:
        bridge = _make_bridge()
        bridge._redef_store.replace({"light.a": {"name": "A"}})
        assert bridge.redefinitions == {"light.a": {"name": "A"}}
        assert bridge._redefinitions is bridge._redef_store.raw

    async def test_stop_shuts_the_store_down_for_good(self) -> None:
        """After async_stop no new debounce timer may be armed."""
        loop_calls: list[tuple] = []
        bridge = _make_bridge()
        bridge._hass.loop.call_later = lambda *a, **kw: loop_calls.append(a) or MagicMock()

        await bridge.async_stop()
        bridge._redef_store.schedule_persist()

        assert loop_calls == [], "a post-shutdown persist re-armed the debounce timer"


# ---------------------------------------------------------------------------
# BaseEntity.mark_state_published — public snapshot API
# ---------------------------------------------------------------------------


class TestMarkStatePublished:
    """The publish path must be able to hand in a pre-await snapshot."""

    def test_explicit_snapshot_is_stored_verbatim(self) -> None:
        entity = RelayEntity({"entity_id": "switch.lamp", "name": "lamp"})
        entity.fill_by_ha_state({"entity_id": "switch.lamp", "state": "off", "attributes": {}})
        wire = entity.to_sber_current_state()

        # Entity changes *after* the snapshot was taken (the publish race).
        entity.fill_by_ha_state({"entity_id": "switch.lamp", "state": "on", "attributes": {}})
        entity.mark_state_published(snapshot=wire)

        assert entity.has_significant_change() is True, "racing update was swallowed (lost update)"

    def test_omitted_snapshot_serializes_the_current_state(self) -> None:
        entity = RelayEntity({"entity_id": "switch.lamp", "name": "lamp"})
        entity.fill_by_ha_state({"entity_id": "switch.lamp", "state": "on", "attributes": {}})

        entity.mark_state_published()

        assert entity.has_significant_change() is False

    def test_none_snapshot_means_treat_as_changed(self) -> None:
        """``None`` is a real value (snapshot failed), not "argument omitted"."""
        entity = RelayEntity({"entity_id": "switch.lamp", "name": "lamp"})
        entity.fill_by_ha_state({"entity_id": "switch.lamp", "state": "on", "attributes": {}})
        entity.mark_state_published()
        assert entity.has_significant_change() is False

        entity.mark_state_published(snapshot=None)

        assert entity.has_significant_change() is True

    async def test_publisher_marks_with_the_pre_await_snapshot(self) -> None:
        """End-to-end: a change racing the publish await is not marked done."""
        bridge = _make_bridge()
        entity = _add_relay(bridge, "switch.lamp", "off")

        async def _racing_publish(_topic: str, _payload: str) -> None:
            # Simulates HA updating the entity while the publish is in flight.
            entity.fill_by_ha_state({"entity_id": "switch.lamp", "state": "on", "attributes": {}})

        bridge._mqtt_service.publish = AsyncMock(side_effect=_racing_publish)

        await bridge._publish_states(["switch.lamp"], force=True)

        assert entity.has_significant_change() is True, (
            "the in-flight state change was marked as published — lost update"
        )
