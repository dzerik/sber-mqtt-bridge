"""Sber MQTT command dispatcher.

Handles commands, status/config requests, errors, change_group and
rename_device messages from the Sber cloud.  Extracted from
:class:`SberBridge` to isolate Sber-protocol command interpretation
from transport and HA state forwarding (SRP).

The dispatcher holds a reference to its parent :class:`SberBridge`
because several command handlers need to mutate bridge state
(entities, redefinitions, acknowledgements) and invoke publish
operations.  The coupling is explicit and one-way.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Protocol, runtime_checkable

import voluptuous as vol
from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import (
    HomeAssistantError,
    ServiceNotFound,
    ServiceValidationError,
    Unauthorized,
)

from .sber_protocol import parse_sber_command, parse_sber_status_request

if TYPE_CHECKING:
    from .ack_audit import AckAudit
    from .devices.base_entity import BaseEntity
    from .devtools_hub import DevToolsHub
    from .redefinitions_store import RedefinitionsStore
    from .sber_publisher import SberPublisher


class _BridgeStats(Protocol):
    """Minimal stats interface used by the dispatcher."""

    commands_received: int
    status_requests: int
    config_requests: int
    errors_from_sber: int
    acknowledged_entities: set[str]


@runtime_checkable
class BridgeCommandContext(Protocol):
    """Narrow interface for SberCommandDispatcher's bridge dependency.

    Exposes the concrete collaborators owned by SberBridge — the
    dispatcher reaches publish, redefinitions, and DevTools flows
    through them, not through bridge-proxied wrapper methods.
    """

    _hass: HomeAssistant
    _stats: _BridgeStats
    _ack_audit: AckAudit
    _entities: dict[str, BaseEntity]
    _enabled_entity_ids: list[str]
    _confirm_tasks: dict[str, asyncio.Task]
    # Concrete collaborators (exposed in Rounds 2-3b).
    _publisher: SberPublisher
    _redef_store: RedefinitionsStore
    _devtools: DevToolsHub

    def _create_safe_task(self, coro: object, *, name: str | None = None) -> asyncio.Task: ...
    async def _delayed_confirm(self, entity_id: str) -> None: ...
    def refresh_repair_issues(self) -> None: ...


_LOGGER = logging.getLogger(__name__)


class SberCommandDispatcher:
    """Interprets incoming Sber MQTT payloads and dispatches side effects.

    Each ``handle_*`` method corresponds to one topic suffix in the Sber
    down/* namespace.  The bridge's ``_mqtt_dispatch`` table routes
    incoming messages to the matching handler.
    """

    def __init__(self, bridge: BridgeCommandContext) -> None:
        """Initialize the dispatcher bound to a bridge context."""
        self._bridge = bridge

    async def handle_command(self, payload: bytes) -> None:
        """Handle a command from Sber cloud → execute HA service.

        During the reconnect grace period, commands are rejected and
        current HA states are re-published so that Sber cloud accepts
        HA as the authoritative source of truth.
        """
        bridge = self._bridge
        data = parse_sber_command(payload)
        bridge._stats.commands_received += 1
        devices = data.get("devices", {})

        if await self._handle_reconnect_grace(devices):
            return

        _LOGGER.debug("Sber command for %d device(s): %s", len(devices), list(devices.keys()))

        context = Context()
        self._open_command_trace(devices, context)

        update_state_ids: list[str] = []
        for entity_id, cmd_data in devices.items():
            if await self._process_one_entity(entity_id, cmd_data, context):
                update_state_ids.append(entity_id)

        commanded_ids = [eid for eid in devices if eid in bridge._entities]

        if update_state_ids:
            await bridge._publisher.publish_states(update_state_ids, force=True)

        # Immediate echo ack: publish the received command states back to
        # Sber within milliseconds so its ack timer does not expire before
        # HA propagates the real state change.  Required for integrations
        # that delay/omit ``state_changed`` events on no-op commands (e.g.
        # HA WLED integration with WLED 16.0.0 — see GitHub issue #35 and
        # HA core issue #170435).
        if commanded_ids:
            await bridge._publisher.publish_command_echo(devices)

        self._schedule_confirms(commanded_ids)

        # Receiving any command is positive evidence that Sber accepted at
        # least one entity — re-evaluate the silent-rejection issue so a
        # stale repair tile clears as soon as the user activates the device.
        self._refresh_repair_issues()

    async def _handle_reconnect_grace(self, devices: dict) -> bool:
        """Reject the command and re-publish states if Sber ack-audit is awaiting.

        Returns:
            True if the caller should return (command was rejected),
            False to continue processing.
        """
        bridge = self._bridge
        if not bridge._ack_audit.is_awaiting:
            return False
        if bridge._ack_audit.timeout_check():
            return False  # Guard cleared by timeout
        entity_ids = [eid for eid in devices if eid in bridge._entities]
        _LOGGER.warning(
            "Ignoring Sber command (awaiting Sber ack after reconnect, "
            "HA state is authoritative): %s [%s] — re-publishing states",
            entity_ids,
            ", ".join(s.get("key", "?") for cmd in devices.values() for s in cmd.get("states", [])),
        )
        if entity_ids:
            await bridge._publisher.publish_states(entity_ids, force=True)
        return True

    def _open_command_trace(self, devices: dict, context: Context) -> None:
        """Open a DevTools correlation trace for an inbound Sber command."""
        bridge = self._bridge
        known_ids = [eid for eid in devices if eid in bridge._entities]
        bridge._devtools.trace_collector.begin(
            trace_id=context.id,
            trigger="sber_command",
            entity_ids=known_ids,
            topic="down/commands",
            payload=devices,
        )
        bridge._devtools.sweep_traces()

    async def _process_one_entity(self, entity_id: str, cmd_data: dict, context: Context) -> bool:
        """Run process_cmd for one entity and dispatch the resulting service calls.

        Returns:
            True if at least one result requested a state update (no ``url``,
            ``update_state=True``). The caller adds the entity_id to a
            post-loop force-publish list.
        """
        bridge = self._bridge
        bridge._stats.acknowledged_entities.add(entity_id)
        entity = bridge._entities.get(entity_id)
        if entity is None:
            _LOGGER.warning("Sber command for unknown entity: %s", entity_id)
            return False

        _LOGGER.info(
            "Sber → HA command: %s [%s]",
            entity_id,
            ", ".join(s.get("key", "?") for s in cmd_data.get("states", [])),
        )

        needs_state_update = False
        for result in entity.process_cmd(cmd_data):
            cmd = result.get("url")
            if cmd is None:
                if result.get("update_state"):
                    needs_state_update = True
                continue
            await self._call_ha_service(entity_id, cmd, context)
            bridge._devtools.trace_collector.record(
                context.id,
                type_="ha_service_call",
                entity_id=entity_id,
                payload={
                    "domain": cmd.get("domain"),
                    "service": cmd.get("service"),
                    "service_data": cmd.get("service_data"),
                },
            )
        return needs_state_update

    def _schedule_confirms(self, commanded_ids: list[str]) -> None:
        """Cancel any prior delayed-confirm task and schedule a fresh one per entity.

        Sber expects a state confirmation after every command; the timer
        delivers it independently of HA's state_changed propagation, which
        can be delayed or missing for no-op commands (issue #35).
        """
        bridge = self._bridge
        for eid in commanded_ids:
            old_task = bridge._confirm_tasks.pop(eid, None)
            if old_task and not old_task.done():
                old_task.cancel()
            bridge._confirm_tasks[eid] = bridge._create_safe_task(
                bridge._delayed_confirm(eid), name=f"delayed_confirm_{eid}"
            )

    def _refresh_repair_issues(self) -> None:
        """Ask the bridge to recompute its HA repair-issue set.

        Triggered after acknowledgments arrive from Sber so a stale
        silent-rejection tile clears in real time instead of waiting for
        the next entity reload or audit timer.  Bridge owns the actual
        :func:`check_and_create_issues` call to keep the dispatcher free
        of bridge-specific imports.
        """
        self._bridge.refresh_repair_issues()

    async def _call_ha_service(self, entity_id: str, cmd: dict, context: Context) -> None:
        """Invoke ``hass.services.async_call`` for a single Sber → HA call."""
        bridge = self._bridge
        try:
            await bridge._hass.services.async_call(
                domain=cmd["domain"],
                service=cmd["service"],
                service_data=cmd.get("service_data", {}),
                target=cmd.get("target", {}),
                blocking=False,
                context=context,
            )
            _LOGGER.debug(
                "HA service called: %s.%s → %s",
                cmd["domain"],
                cmd["service"],
                cmd.get("target", {}).get("entity_id", "?"),
            )
        except (
            vol.Invalid,
            ServiceNotFound,
            ServiceValidationError,
            Unauthorized,
            HomeAssistantError,
            TimeoutError,
        ) as err:
            _LOGGER.warning("HA service call failed for %s: %s", entity_id, err)

    async def handle_status_request(self, payload: bytes) -> None:
        """Handle a status request from Sber cloud.

        If Sber asks about entities not in our current set, automatically
        re-publishes the device config so Sber is aware of the correct list.
        A status_request also counts as Sber acknowledgment.
        """
        bridge = self._bridge
        requested_ids = parse_sber_status_request(payload)
        bridge._stats.status_requests += 1

        bridge._ack_audit.acknowledge()

        if requested_ids:
            unknown = [eid for eid in requested_ids if eid not in bridge._entities and eid != "root"]
            if unknown:
                _LOGGER.info(
                    "Sber asked about unknown entities, re-publishing config: %s",
                    unknown,
                )
                await bridge._publisher.publish_config()

        if requested_ids:
            for eid in requested_ids:
                bridge._stats.acknowledged_entities.add(eid)
            _LOGGER.info(
                "Sber status request for %d specific entities: %s",
                len(requested_ids),
                requested_ids,
            )
        else:
            bridge._stats.acknowledged_entities.update(bridge._enabled_entity_ids)
            _LOGGER.info(
                "Sber status request for ALL entities (%d)",
                len(bridge._enabled_entity_ids),
            )

        await bridge._publisher.publish_states(requested_ids if requested_ids else None, force=True)

        # status_request is the strongest single ack signal we get from
        # Sber (it explicitly enumerates accepted entities or asks for
        # the whole set).  Refresh the repair issues so the silent-
        # rejection tile clears in real time, not only on next reload.
        self._refresh_repair_issues()

    async def handle_config_request(self) -> None:
        """Handle config request from Sber cloud — send device list."""
        bridge = self._bridge
        bridge._stats.config_requests += 1
        bridge._ack_audit.acknowledge()
        _LOGGER.info(
            "Sber config request received (will publish %d entities)",
            len(bridge._enabled_entity_ids),
        )
        await bridge._publisher.publish_config()

    def handle_error(self, payload: bytes) -> None:
        """Handle error message from Sber cloud.

        Parses the error payload, stores the detail in stats for repair
        issue creation, and logs the error.
        """
        bridge = self._bridge
        bridge._stats.errors_from_sber += 1
        try:
            error_data = json.loads(payload)
            detail = json.dumps(error_data, ensure_ascii=False)
            bridge._stats.last_error_detail = detail[:500]
            _LOGGER.warning(
                "Sber error (#%d): %s",
                bridge._stats.errors_from_sber,
                detail,
            )
        except (json.JSONDecodeError, TypeError):
            raw = payload.decode(errors="replace")[:500]
            bridge._stats.last_error_detail = raw
            _LOGGER.warning(
                "Sber error (#%d, raw): %s",
                bridge._stats.errors_from_sber,
                raw,
            )

    async def handle_change_group(self, payload: bytes) -> None:
        """Handle device group/room change from Sber.

        Only stores the redefinition locally. Does NOT re-publish config
        to avoid an infinite loop: Sber sends change_group → we publish
        config → Sber sends change_group again → loop forever.
        """
        bridge = self._bridge
        try:
            data = json.loads(payload)
        except json.JSONDecodeError as exc:
            _LOGGER.debug(
                "Malformed change_group_device_request payload (json): %r — %s",
                payload[:200] if isinstance(payload, (bytes, str)) else payload,
                exc,
            )
            return
        entity_id = data.get("device_id")
        if not entity_id:
            return
        existing = dict(bridge._redef_store.raw.get(entity_id, {}))
        existing["home"] = data.get("home")
        existing["room"] = data.get("room")
        bridge._redef_store.raw[entity_id] = existing
        bridge._redef_store.schedule_persist()
        _LOGGER.info("Sber group change stored: %s → room=%s", entity_id, data.get("room"))

    async def handle_rename_device(self, payload: bytes) -> None:
        """Handle device rename from Sber.

        Only stores the redefinition locally. Does NOT re-publish config
        to avoid potential loops.
        """
        bridge = self._bridge
        try:
            data = json.loads(payload)
        except json.JSONDecodeError as exc:
            _LOGGER.debug(
                "Malformed rename_device_request payload (json): %r — %s",
                payload[:200] if isinstance(payload, (bytes, str)) else payload,
                exc,
            )
            return
        entity_id = data.get("device_id")
        new_name = data.get("new_name")
        if entity_id and new_name:
            redef = bridge._redef_store.raw.setdefault(entity_id, {})
            redef["name"] = new_name
            bridge._redef_store.schedule_persist()
            _LOGGER.info("Sber rename stored: %s → %s", entity_id, new_name)

    def handle_global_config(self, payload: bytes) -> None:
        """Handle global config from Sber (http_api_endpoint)."""
        try:
            data = json.loads(payload)
            endpoint = data.get("http_api_endpoint", "")
            if endpoint:
                _LOGGER.info("Sber HTTP API endpoint: %s", endpoint)
        except json.JSONDecodeError as exc:
            _LOGGER.debug(
                "Malformed global_config payload (json): %r — %s",
                payload[:200] if isinstance(payload, (bytes, str)) else payload,
                exc,
            )
