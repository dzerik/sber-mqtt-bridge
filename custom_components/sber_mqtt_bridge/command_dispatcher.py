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

import json
import logging
import time
from typing import TYPE_CHECKING

from homeassistant.core import Context
from homeassistant.exceptions import (
    HomeAssistantError,
    ServiceNotFound,
    ServiceValidationError,
    Unauthorized,
)

from .sber_protocol import parse_sber_command, parse_sber_status_request

if TYPE_CHECKING:
    from .sber_bridge import SberBridge

_LOGGER = logging.getLogger(__name__)


class SberCommandDispatcher:
    """Interprets incoming Sber MQTT payloads and dispatches side effects.

    Each ``handle_*`` method corresponds to one topic suffix in the Sber
    down/* namespace.  The bridge's ``_mqtt_dispatch`` table routes
    incoming messages to the matching handler.
    """

    def __init__(self, bridge: SberBridge) -> None:
        """Initialize the dispatcher bound to a bridge instance."""
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

        if bridge._awaiting_sber_ack:
            if time.monotonic() >= bridge._awaiting_sber_ack_deadline:
                _LOGGER.info("Sber ack timeout reached — accepting commands")
                bridge._awaiting_sber_ack = False
            else:
                entity_ids = [eid for eid in devices if eid in bridge._entities]
                _LOGGER.warning(
                    "Ignoring Sber command (awaiting Sber ack after reconnect, "
                    "HA state is authoritative): %s [%s] — re-publishing states",
                    entity_ids,
                    ", ".join(
                        s.get("key", "?")
                        for cmd in devices.values()
                        for s in cmd.get("states", [])
                    ),
                )
                if entity_ids:
                    await bridge._publish_states(entity_ids, force=True)
                return

        _LOGGER.debug(
            "Sber command for %d device(s): %s", len(devices), list(devices.keys()),
        )

        update_state_ids: list[str] = []
        context = Context()

        for entity_id, cmd_data in devices.items():
            bridge._stats.acknowledged_entities.add(entity_id)
            entity = bridge._entities.get(entity_id)
            if entity is None:
                _LOGGER.warning("Sber command for unknown entity: %s", entity_id)
                continue

            _LOGGER.info(
                "Sber → HA command: %s [%s]",
                entity_id,
                ", ".join(s.get("key", "?") for s in cmd_data.get("states", [])),
            )

            results = entity.process_cmd(cmd_data)
            for result in results:
                cmd = result.get("url")
                if cmd is None:
                    if result.get("update_state"):
                        update_state_ids.append(entity_id)
                    continue
                await self._call_ha_service(entity_id, cmd, context)

        commanded_ids = [eid for eid in devices if eid in bridge._entities]

        if update_state_ids:
            await bridge._publish_states(update_state_ids, force=True)

        # Schedule a delayed force-publish for all commanded entities.
        # Sber expects state confirmation after every command.
        for eid in commanded_ids:
            old_task = bridge._confirm_tasks.pop(eid, None)
            if old_task and not old_task.done():
                old_task.cancel()
            bridge._confirm_tasks[eid] = bridge._create_safe_task(
                bridge._delayed_confirm(eid), name=f"delayed_confirm_{eid}"
            )

    async def _call_ha_service(
        self, entity_id: str, cmd: dict, context: Context
    ) -> None:
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

        if bridge._awaiting_sber_ack:
            bridge._awaiting_sber_ack = False
            _LOGGER.info("Sber ack received (status_request) — now accepting commands")

        if requested_ids:
            unknown = [
                eid for eid in requested_ids
                if eid not in bridge._entities and eid != "root"
            ]
            if unknown:
                _LOGGER.info(
                    "Sber asked about unknown entities, re-publishing config: %s",
                    unknown,
                )
                await bridge._publish_config()

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

        await bridge._publish_states(
            requested_ids if requested_ids else None, force=True
        )

    async def handle_config_request(self) -> None:
        """Handle config request from Sber cloud — send device list."""
        bridge = self._bridge
        bridge._stats.config_requests += 1
        if bridge._awaiting_sber_ack:
            bridge._awaiting_sber_ack = False
            _LOGGER.info("Sber ack received (config_request) — now accepting commands")
        _LOGGER.info(
            "Sber config request received (will publish %d entities)",
            len(bridge._enabled_entity_ids),
        )
        await bridge._publish_config()

    def handle_error(self, payload: bytes) -> None:
        """Handle error message from Sber cloud."""
        bridge = self._bridge
        bridge._stats.errors_from_sber += 1
        try:
            error_data = json.loads(payload)
            _LOGGER.warning(
                "Sber error (#%d): %s",
                bridge._stats.errors_from_sber,
                json.dumps(error_data, ensure_ascii=False, indent=2),
            )
        except (json.JSONDecodeError, TypeError):
            _LOGGER.warning(
                "Sber error (#%d, raw): %s",
                bridge._stats.errors_from_sber,
                payload,
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
        except json.JSONDecodeError:
            return
        entity_id = data.get("device_id")
        if not entity_id:
            return
        existing = bridge._redefinitions.get(entity_id, {})
        existing["home"] = data.get("home")
        existing["room"] = data.get("room")
        bridge._redefinitions[entity_id] = existing
        bridge._persist_redefinitions()
        _LOGGER.info(
            "Sber group change stored: %s → room=%s", entity_id, data.get("room")
        )

    async def handle_rename_device(self, payload: bytes) -> None:
        """Handle device rename from Sber.

        Only stores the redefinition locally. Does NOT re-publish config
        to avoid potential loops.
        """
        bridge = self._bridge
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return
        entity_id = data.get("device_id")
        new_name = data.get("new_name")
        if entity_id and new_name:
            redef = bridge._redefinitions.setdefault(entity_id, {})
            redef["name"] = new_name
            bridge._persist_redefinitions()
            _LOGGER.info("Sber rename stored: %s → %s", entity_id, new_name)

    def handle_global_config(self, payload: bytes) -> None:
        """Handle global config from Sber (http_api_endpoint)."""
        try:
            data = json.loads(payload)
            endpoint = data.get("http_api_endpoint", "")
            if endpoint:
                _LOGGER.info("Sber HTTP API endpoint: %s", endpoint)
        except json.JSONDecodeError:
            pass
