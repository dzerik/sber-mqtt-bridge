"""Sber MQTT command dispatcher.

Handles commands, status/config requests, errors, change_group and
rename_device messages from the Sber cloud.  Extracted from
:class:`SberBridge` to isolate Sber-protocol command interpretation
from transport and HA state forwarding (SRP).

The dispatcher owns no reference to :class:`SberBridge`.  Everything it
may touch arrives through :class:`DispatcherDeps`: the collaborators it
drives (publisher, redefinitions store, DevTools hub, ack audit) plus
callables for the few bridge-owned operations it triggers.  Narrowing
this bundle is what keeps the bridge free to reshape its internals.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

import voluptuous as vol
from homeassistant.core import Context
from homeassistant.exceptions import (
    HomeAssistantError,
    ServiceNotFound,
    ServiceValidationError,
    Unauthorized,
)

from .sber_protocol import parse_sber_command, parse_sber_status_request

if TYPE_CHECKING:
    from collections.abc import Callable

    from homeassistant.core import HomeAssistant

    from .ack_audit import AckAudit
    from .bridge_ports import StatsPort
    from .devices.base_entity import BaseEntity
    from .devtools_hub import DevToolsHub
    from .redefinitions_store import RedefinitionsStore
    from .sber_publisher import SberPublisher


@dataclass(frozen=True, slots=True)
class DispatcherDeps:
    """Everything :class:`SberCommandDispatcher` is allowed to reach."""

    hass: HomeAssistant
    """HA core — used only to invoke services for Sber commands."""

    stats: StatsPort
    """Counter bag bumped per inbound message kind."""

    ack_audit: AckAudit
    """Reconnect guard consulted before executing a command."""

    publisher: SberPublisher
    """Publish coordinator used for state / config / echo responses."""

    redefinitions: RedefinitionsStore
    """Store fed by ``change_group`` / ``rename_device`` payloads."""

    devtools: DevToolsHub
    """Collector aggregate that records the command correlation trace."""

    get_entities: Callable[[], dict[str, BaseEntity]]
    """Returns the live ``entity_id → BaseEntity`` map."""

    get_enabled_entity_ids: Callable[[], list[str]]
    """Returns the ordered list of exposed entity IDs."""

    schedule_confirm: Callable[[str], None]
    """Asks the bridge to (re)arm the delayed state confirm for one entity."""

    refresh_repair_issues: Callable[[], None]
    """Asks the bridge to recompute its HA repair-issue set."""


_LOGGER = logging.getLogger(__name__)

_MAX_REDEF_VALUE_LEN = 128
"""Maximum accepted length for cloud-supplied redefinition values
(device name / home / room). Longer values are rejected to keep
persistent ConfigEntry options bounded."""

_MAX_ENTITY_ID_LEN = 255
"""Maximum accepted length for a cloud-supplied device_id key."""


def _parse_json_dict(payload: bytes | str, kind: str) -> dict | None:
    """Parse a JSON payload and require a dict at the top level.

    Args:
        payload: Raw MQTT payload.
        kind: Short label for log messages (e.g. ``change_group``).

    Returns:
        The parsed dict, or ``None`` if the payload is malformed JSON
        or its top-level value is not an object.
    """
    try:
        data = json.loads(payload)
    except (json.JSONDecodeError, TypeError, UnicodeDecodeError) as exc:
        _LOGGER.debug(
            "Malformed %s payload (json): %r — %s",
            kind,
            payload[:200] if isinstance(payload, (bytes, str)) else payload,
            exc,
        )
        return None
    if not isinstance(data, dict):
        _LOGGER.debug("Malformed %s payload: expected object, got %s", kind, type(data).__name__)
        return None
    return data


def _sanitize_redef_value(value: object) -> str | None:
    """Validate one cloud-supplied redefinition value.

    Args:
        value: Raw value from the Sber payload (any JSON type).

    Returns:
        The stripped string if it is a non-empty ``str`` within
        :data:`_MAX_REDEF_VALUE_LEN`, otherwise ``None``.
    """
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or len(value) > _MAX_REDEF_VALUE_LEN:
        return None
    return value


def _state_keys(cmd_data: object) -> str:
    """Return a comma-joined summary of state keys for logging.

    Tolerates arbitrary malformed input: non-dict ``cmd_data``,
    non-list ``states`` and non-dict state items are skipped.
    """
    if not isinstance(cmd_data, dict):
        return "?"
    states = cmd_data.get("states")
    if not isinstance(states, list):
        return "?"
    return ", ".join(str(s.get("key", "?")) for s in states if isinstance(s, dict))


class SberCommandDispatcher:
    """Interprets incoming Sber MQTT payloads and dispatches side effects.

    Each ``handle_*`` method corresponds to one topic suffix in the Sber
    down/* namespace.  The bridge's ``_mqtt_dispatch`` table routes
    incoming messages to the matching handler.
    """

    def __init__(self, deps: DispatcherDeps) -> None:
        """Initialize the dispatcher bound to its dependency bundle.

        Args:
            deps: Narrow dependency bundle assembled by the bridge.
        """
        self._deps = deps

    async def handle_command(self, payload: bytes, context: Context | None = None) -> None:
        """Handle a command from Sber cloud → execute HA service.

        During the reconnect grace period, commands are rejected and
        current HA states are re-published so that Sber cloud accepts
        HA as the authoritative source of truth.

        Args:
            payload: Raw MQTT payload from ``down/commands``.
            context: Optional HA context to attribute the resulting
                service calls to (e.g. a user-scoped context for
                WS-initiated replays). A fresh anonymous ``Context``
                is created when omitted.
        """
        deps = self._deps
        data = parse_sber_command(payload)
        deps.stats.commands_received += 1
        devices = data.get("devices", {})

        if await self._handle_reconnect_grace(devices):
            return

        _LOGGER.debug("Sber command for %d device(s): %s", len(devices), list(devices.keys()))

        if context is None:
            context = Context()
        self._open_command_trace(devices, context)

        update_state_ids: list[str] = []
        for entity_id, cmd_data in devices.items():
            if await self._process_one_entity(entity_id, cmd_data, context):
                update_state_ids.append(entity_id)

        # Only well-formed (dict) command payloads participate in the echo
        # ack — a single type-confused entry must not break the ack for the
        # rest of the batch.
        valid_devices = {eid: cmd for eid, cmd in devices.items() if isinstance(cmd, dict)}
        entities = deps.get_entities()
        commanded_ids = [eid for eid in valid_devices if eid in entities]

        if update_state_ids:
            await deps.publisher.publish_states(update_state_ids, force=True)

        # Immediate echo ack: publish the received command states back to
        # Sber within milliseconds so its ack timer does not expire before
        # HA propagates the real state change.  Required for integrations
        # that delay/omit ``state_changed`` events on no-op commands (e.g.
        # HA WLED integration with WLED 16.0.0 — see GitHub issue #35 and
        # HA core issue #170435).
        if commanded_ids:
            await deps.publisher.publish_command_echo(valid_devices)

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
        deps = self._deps
        if not deps.ack_audit.is_awaiting:
            return False
        if deps.ack_audit.timeout_check():
            return False  # Guard cleared by timeout
        entities = deps.get_entities()
        entity_ids = [eid for eid in devices if eid in entities]
        _LOGGER.warning(
            "Ignoring Sber command (awaiting Sber ack after reconnect, "
            "HA state is authoritative): %s [%s] — re-publishing states",
            entity_ids,
            "; ".join(_state_keys(cmd) for cmd in devices.values()),
        )
        if entity_ids:
            await deps.publisher.publish_states(entity_ids, force=True)
        return True

    def _open_command_trace(self, devices: dict, context: Context) -> None:
        """Open a DevTools correlation trace for an inbound Sber command."""
        deps = self._deps
        entities = deps.get_entities()
        known_ids = [eid for eid in devices if eid in entities]
        deps.devtools.trace_collector.begin(
            trace_id=context.id,
            trigger="sber_command",
            entity_ids=known_ids,
            topic="down/commands",
            payload=devices,
        )
        deps.devtools.sweep_traces()

    async def _process_one_entity(self, entity_id: str, cmd_data: object, context: Context) -> bool:
        """Run process_cmd for one entity and dispatch the resulting service calls.

        A failure while processing one entity (malformed ``cmd_data``,
        a bug in a device class, an unexpected service-call error) is
        logged and contained here so that the remaining entities of a
        multi-device command batch, the echo ack and the delayed
        confirms are still processed.  ``cmd_data`` is deliberately
        typed ``object``: the runtime guard below narrows it to
        ``dict`` before it reaches any device class.

        Returns:
            True if at least one result requested a state update (no ``url``,
            ``update_state=True``). The caller adds the entity_id to a
            post-loop force-publish list.
        """
        deps = self._deps
        deps.stats.acknowledged_entities.add(entity_id)
        entity = deps.get_entities().get(entity_id)
        if entity is None:
            _LOGGER.warning("Sber command for unknown entity: %s", entity_id)
            return False
        if not isinstance(cmd_data, dict):
            _LOGGER.warning(
                "Sber command for %s has invalid payload type %s — skipping",
                entity_id,
                type(cmd_data).__name__,
            )
            return False

        _LOGGER.info("Sber → HA command: %s [%s]", entity_id, _state_keys(cmd_data))

        needs_state_update = False
        try:
            for result in entity.process_cmd(cmd_data):
                cmd = result.get("url")
                if cmd is None:
                    if result.get("update_state"):
                        needs_state_update = True
                    continue
                await self._call_ha_service(entity_id, cmd, context)
                deps.devtools.trace_collector.record(
                    context.id,
                    type_="ha_service_call",
                    entity_id=entity_id,
                    payload={
                        "domain": cmd.get("domain"),
                        "service": cmd.get("service"),
                        "service_data": cmd.get("service_data"),
                    },
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOGGER.exception(
                "Failed to process Sber command for %s — continuing with the rest of the batch",
                entity_id,
            )
        return needs_state_update

    def _schedule_confirms(self, commanded_ids: list[str]) -> None:
        """Ask the bridge for a delayed state confirm per commanded entity.

        Sber expects a state confirmation after every command; the timer
        delivers it independently of HA's state_changed propagation, which
        can be delayed or missing for no-op commands (issue #35).  Task
        ownership (dedup, cancellation, teardown) stays with the bridge.
        """
        for eid in commanded_ids:
            self._deps.schedule_confirm(eid)

    def _refresh_repair_issues(self) -> None:
        """Ask the bridge to recompute its HA repair-issue set.

        Triggered after acknowledgments arrive from Sber so a stale
        silent-rejection tile clears in real time instead of waiting for
        the next entity reload or audit timer.  Bridge owns the actual
        :func:`check_and_create_issues` call to keep the dispatcher free
        of bridge-specific imports.
        """
        self._deps.refresh_repair_issues()

    async def _call_ha_service(self, entity_id: str, cmd: dict, context: Context) -> None:
        """Invoke ``hass.services.async_call`` for a single Sber → HA call."""
        try:
            await self._deps.hass.services.async_call(
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
        deps = self._deps
        requested_ids = parse_sber_status_request(payload)
        deps.stats.status_requests += 1

        deps.ack_audit.acknowledge()

        if requested_ids:
            entities = deps.get_entities()
            unknown = [eid for eid in requested_ids if eid not in entities and eid != "root"]
            if unknown:
                _LOGGER.info(
                    "Sber asked about unknown entities, re-publishing config: %s",
                    unknown,
                )
                await deps.publisher.publish_config()

        if requested_ids:
            for eid in requested_ids:
                deps.stats.acknowledged_entities.add(eid)
            _LOGGER.info(
                "Sber status request for %d specific entities: %s",
                len(requested_ids),
                requested_ids,
            )
        else:
            enabled_ids = deps.get_enabled_entity_ids()
            deps.stats.acknowledged_entities.update(enabled_ids)
            _LOGGER.info(
                "Sber status request for ALL entities (%d)",
                len(enabled_ids),
            )

        await deps.publisher.publish_states(requested_ids if requested_ids else None, force=True)

        # status_request is the strongest single ack signal we get from
        # Sber (it explicitly enumerates accepted entities or asks for
        # the whole set).  Refresh the repair issues so the silent-
        # rejection tile clears in real time, not only on next reload.
        self._refresh_repair_issues()

    async def handle_config_request(self) -> None:
        """Handle config request from Sber cloud — send device list."""
        deps = self._deps
        deps.stats.config_requests += 1
        deps.ack_audit.acknowledge()
        _LOGGER.info(
            "Sber config request received (will publish %d entities)",
            len(deps.get_enabled_entity_ids()),
        )
        await deps.publisher.publish_config()

    def handle_error(self, payload: bytes) -> None:
        """Handle error message from Sber cloud.

        Parses the error payload, stores the detail in stats for repair
        issue creation, and logs the error.
        """
        stats = self._deps.stats
        stats.errors_from_sber += 1
        try:
            error_data = json.loads(payload)
            detail = json.dumps(error_data, ensure_ascii=False)
            stats.last_error_detail = detail[:500]
            _LOGGER.warning(
                "Sber error (#%d): %s",
                stats.errors_from_sber,
                detail,
            )
        except (json.JSONDecodeError, TypeError):
            raw = payload.decode(errors="replace")[:500]
            stats.last_error_detail = raw
            _LOGGER.warning(
                "Sber error (#%d, raw): %s",
                stats.errors_from_sber,
                raw,
            )

    @staticmethod
    def _extract_redef_target(data: dict, kind: str) -> str | None:
        """Validate and return the ``device_id`` of a redefinition payload.

        Args:
            data: Parsed payload dict.
            kind: Short label for log messages.

        Returns:
            The stripped entity_id string, or ``None`` if it is missing,
            not a string, empty, or unreasonably long.
        """
        raw_id = data.get("device_id")
        entity_id = raw_id.strip() if isinstance(raw_id, str) else None
        if not entity_id or len(entity_id) > _MAX_ENTITY_ID_LEN:
            _LOGGER.warning("Ignoring Sber %s with invalid device_id: %r", kind, raw_id)
            return None
        return entity_id

    async def handle_change_group(self, payload: bytes) -> None:
        """Handle device group/room change from Sber.

        Values are validated (string type, length limit) and stored
        through :meth:`RedefinitionsStore.async_update` so cloud input
        goes through the same normalization as the WS API — invalid or
        missing values clear the corresponding key instead of persisting
        arbitrary payloads.

        Only stores the redefinition locally. Does NOT re-publish config
        to avoid an infinite loop: Sber sends change_group → we publish
        config → Sber sends change_group again → loop forever.
        """
        store = self._deps.redefinitions
        data = _parse_json_dict(payload, "change_group_device_request")
        if data is None:
            return
        entity_id = self._extract_redef_target(data, "change_group")
        if entity_id is None:
            return
        fields: dict[str, str | None] = {
            "home": _sanitize_redef_value(data.get("home")),
            "room": _sanitize_redef_value(data.get("room")),
        }
        if all(value is None for value in fields.values()) and not store.has(entity_id):
            # Nothing usable to store and no existing record to clear —
            # avoid creating empty {} entries (and persist churn) for
            # arbitrary cloud-supplied ids.
            _LOGGER.debug("Sber change_group for %s carries no usable values — ignored", entity_id)
            return
        await store.async_update(entity_id, fields)
        _LOGGER.info("Sber group change stored: %s → room=%s", entity_id, fields["room"])

    async def handle_rename_device(self, payload: bytes) -> None:
        """Handle device rename from Sber.

        The new name is validated (string type, length limit) and stored
        through :meth:`RedefinitionsStore.async_update`; payloads with a
        non-string or oversized name are rejected without touching the
        persistent store.

        Only stores the redefinition locally. Does NOT re-publish config
        to avoid potential loops.
        """
        store = self._deps.redefinitions
        data = _parse_json_dict(payload, "rename_device_request")
        if data is None:
            return
        entity_id = self._extract_redef_target(data, "rename_device")
        if entity_id is None:
            return
        new_name = _sanitize_redef_value(data.get("new_name"))
        if new_name is None:
            if data.get("new_name") is not None:
                _LOGGER.warning(
                    "Ignoring Sber rename for %s with invalid new_name: %.60r",
                    entity_id,
                    data.get("new_name"),
                )
            return
        await store.async_update(entity_id, {"name": new_name})
        _LOGGER.info("Sber rename stored: %s → %s", entity_id, new_name)

    def handle_global_config(self, payload: bytes) -> None:
        """Handle global config from Sber (http_api_endpoint)."""
        data = _parse_json_dict(payload, "global_config")
        if data is None:
            return
        endpoint = data.get("http_api_endpoint", "")
        if endpoint:
            _LOGGER.info("Sber HTTP API endpoint: %s", endpoint)
