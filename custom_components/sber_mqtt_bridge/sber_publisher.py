"""Sber Smart Home MQTT publish coordinator.

Owns the three Sber publish flows extracted from :class:`SberBridge`:

* :meth:`publish_states` — outbound state updates on ``up/status``.
* :meth:`publish_config` — outbound device descriptor on ``up/config``.
* :meth:`publish_command_echo` — fast ack echo for incoming Sber commands.

Each method retains the side-effects of its predecessor in
``sber_bridge.SberBridge`` (DevTools instrumentation, ack audit hook,
stats bump, dirty-flag bookkeeping) — the bridge keeps thin delegators
so existing call sites remain untouched.
"""

from __future__ import annotations

import json
import logging
import time
from typing import TYPE_CHECKING

import aiomqtt

from .const import CONF_HUB_AUTO_PARENT
from .sber_protocol import (
    build_devices_list_json,
    build_states_list_json,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from .devices.base_entity import BaseEntity
    from .sber_bridge import SberBridge

_LOGGER = logging.getLogger(__name__)


class SberPublisher:
    """Publish coordinator for the Sber MQTT bridge.

    Constructed with a reference to its parent :class:`SberBridge`; reads
    shared state directly (entities, settings, MQTT service, collectors).
    The coupling is deliberate and one-way — the bridge does not call
    back into the publisher except via the publish methods themselves.
    """

    def __init__(self, bridge: SberBridge) -> None:
        """Bind the publisher to its parent bridge.

        Args:
            bridge: The bridge instance whose state this publisher
                reads (entities, settings, MQTT service).
        """
        self._bridge = bridge
        self._last_config_publish_time: float | None = None
        """Monotonic timestamp of the most recent successful config publish."""

    @property
    def last_config_publish_time(self) -> float | None:
        """Return the monotonic timestamp of the last successful config publish."""
        return self._last_config_publish_time

    async def _publish_logged(self, topic: str, payload: str, error_context: str) -> bool:
        """Publish a payload and apply the shared stats / message-log tail.

        Args:
            topic: Full MQTT topic to publish to.
            payload: Serialized JSON payload.
            error_context: Human-readable payload kind for the error log
                (``"command echo"`` / ``"states"`` / ``"config"``).

        Returns:
            True when the publish succeeded (``messages_sent`` bumped and
            the outbound message logged), False when it raised
            (``publish_errors`` bumped, exception logged, nothing else done).
        """
        bridge = self._bridge
        mqtt_service = bridge._mqtt_service
        if mqtt_service is None:
            return False
        try:
            await mqtt_service.publish(topic, payload)
        except (aiomqtt.MqttError, RuntimeError):
            bridge._stats.publish_errors += 1
            _LOGGER.exception("Error publishing %s to Sber", error_context)
            return False
        bridge._stats.messages_sent += 1
        bridge._log_message("out", topic, payload)
        return True

    def _record_devtools(self, topic: str, payload: str, entity_ids: Iterable[str], *, log_suffix: str = "") -> None:
        """Feed the trace / diff / validation collectors after a publish.

        Builds the ``categories`` / ``declared_features`` maps only for the
        published ``entity_ids`` — the validation collector only looks up
        devices present in the payload, so rebuilding them for every bridge
        entity on each publish was pure overhead in the hot path.

        Args:
            topic: Topic the payload was published to.
            payload: The exact payload string that went on the wire.
            entity_ids: IDs of the entities included in the payload.
            log_suffix: Suffix appended to collector failure log messages
                (e.g. ``" (echo)"``) to keep historical log text intact.
        """
        bridge = self._bridge
        ids = list(entity_ids)
        for eid in ids:
            bridge._trace_collector.record_publish(eid, topic, payload)
        try:
            bridge._diff_collector.record_publish_payload(payload, topic=topic)
        except Exception:  # pragma: no cover — must never break publish
            _LOGGER.exception("DiffCollector.record_publish_payload failed%s", log_suffix)
        try:
            published = {eid: ent for eid in ids if (ent := bridge._entities.get(eid)) is not None}
            categories = {eid: ent.category for eid, ent in published.items()}
            declared = {eid: ent.get_final_features_list() for eid, ent in published.items()}
            bridge._validation_collector.record_publish_payload(
                payload,
                categories=categories,
                declared_features=declared,
            )
        except Exception:  # pragma: no cover — must never break publish
            _LOGGER.exception("ValidationCollector.record_publish_payload failed%s", log_suffix)

    @staticmethod
    def _snapshot_wire_state(entity: BaseEntity) -> dict | None:
        """Snapshot the entity state exactly as serialized into the payload.

        Mirrors the failure semantics of ``BaseEntity.mark_state_published``:
        a snapshot failure yields ``None`` so the next diff treats the entity
        as changed.

        Args:
            entity: Entity being published.

        Returns:
            The ``to_sber_current_state()`` dict, or ``None`` on failure.
        """
        try:
            return entity.to_sber_current_state()
        except (RuntimeError, TypeError, ValueError):
            return None

    async def publish_command_echo(self, devices: dict[str, dict]) -> None:
        """Publish immediate echo of a received Sber command as fast ack.

        Args:
            devices: ``devices`` dict from the incoming Sber command.

        Side effects mirror the original ``SberBridge._publish_command_echo``:
        bumps ``messages_sent`` on success, logs the outbound message in
        the DevTools ring buffer, and records into the trace / diff /
        validation collectors.
        """
        bridge = self._bridge
        if not bridge._connected or bridge._mqtt_service is None:
            return

        echo_devices: dict[str, dict] = {}
        for entity_id, cmd_data in devices.items():
            entity = bridge._entities.get(entity_id)
            if entity is None:
                continue
            try:
                current = entity.to_sber_current_state().get(entity_id, {"states": []})
            except (TypeError, ValueError, KeyError, AttributeError):
                _LOGGER.exception("Building command-echo baseline failed for %s", entity_id)
                continue
            baseline_states: list[dict] = list(current.get("states", []))
            cmd_states_by_key: dict[str, dict] = {s.get("key"): s for s in cmd_data.get("states", []) if s.get("key")}
            merged: list[dict] = []
            overridden: set[str] = set()
            for state in baseline_states:
                key = state.get("key")
                if key in cmd_states_by_key:
                    merged.append(cmd_states_by_key[key])
                    overridden.add(key)
                else:
                    merged.append(state)
            for key, state in cmd_states_by_key.items():
                if key not in overridden:
                    merged.append(state)
            echo_devices[entity_id] = {"states": merged}

        if not echo_devices:
            return

        payload = json.dumps({"devices": echo_devices})
        topic = f"{bridge._root_topic}/up/status"
        if not await self._publish_logged(topic, payload, "command echo"):
            return
        _LOGGER.debug("Published command echo for %s: %s", list(echo_devices), payload)
        self._record_devtools(topic, payload, echo_devices, log_suffix=" (echo)")

    async def publish_states(
        self,
        entity_ids: list[str] | None = None,
        *,
        force: bool = False,
    ) -> None:
        """Publish entity states on ``up/status``.

        Args:
            entity_ids: Specific entity IDs to publish, or ``None`` for all enabled.
            force: If True, skip the value-change diff (used for status_request
                responses and command echo).

        Mirrors the original ``SberBridge._publish_states``: skips if
        disconnected, applies the change diff unless ``force`` is set,
        marks state as published on success, and feeds the three DevTools
        collectors so the panel stays in sync.

        Lost-update guard: the "last published" snapshot per entity is
        captured synchronously with payload construction — *before* the
        publish ``await`` yields the event loop.  A state change racing in
        during the network round-trip therefore still differs from the
        snapshot and is published by the next debounce flush instead of
        being silently considered already-published.
        """
        bridge = self._bridge
        if not bridge._connected or bridge._mqtt_service is None:
            return

        if not force and entity_ids:
            changed_ids = [
                eid for eid in entity_ids if (e := bridge._entities.get(eid)) is not None and e.has_significant_change()
            ]
            if not changed_ids:
                _LOGGER.debug("All %d entities unchanged, skipping publish", len(entity_ids))
                return
            entity_ids = changed_ids

        # Freeze the publish set now: re-reading _enabled_entity_ids after the
        # await could mark entities that were never in the payload (hot-reload).
        ids_to_publish = list(entity_ids) if entity_ids else list(bridge._enabled_entity_ids)
        payload, payload_valid = build_states_list_json(bridge._entities, entity_ids, bridge._enabled_entity_ids)
        payload_str = payload if isinstance(payload, str) else ""
        snapshots: dict[str, dict | None] = {}
        if payload_valid:
            for eid in ids_to_publish:
                entity = bridge._entities.get(eid)
                if entity is not None:
                    snapshots[eid] = self._snapshot_wire_state(entity)
        topic = f"{bridge._root_topic}/up/status"
        _LOGGER.debug(
            "Publishing state to %s (%d bytes): %s",
            topic,
            len(payload_str),
            payload,
        )
        if not await self._publish_logged(topic, payload_str, "states"):
            return
        if payload_valid:
            for eid, snapshot in snapshots.items():
                entity = bridge._entities.get(eid)
                if entity is not None:
                    # Same effect as BaseEntity.mark_state_published(), but with
                    # the pre-await snapshot of what actually went on the wire.
                    entity._previous_sber_state = snapshot
        self._record_devtools(topic, payload_str, ids_to_publish)

    async def publish_config(self, entity_ids: list[str] | None = None) -> None:
        """Publish device descriptor on ``up/config``.

        Args:
            entity_ids: Specific entity IDs to publish, or ``None`` for all
                enabled entities.

        Stores ``_last_config_publish_time`` on success, refreshes the
        ack-audit schedule, and emits the DevTools log entry. Behaviour
        mirrors the original ``SberBridge._publish_config`` exactly.
        """
        bridge = self._bridge
        if not bridge._connected or bridge._mqtt_service is None:
            return

        ids_to_publish = entity_ids or bridge._enabled_entity_ids
        ha_location = bridge._hass.config.location_name
        location = ha_location if ha_location and ha_location != "Home Assistant" else "Мой дом"
        auto_parent = bridge._entry.options.get(CONF_HUB_AUTO_PARENT, False)
        ha_serial_prefix = bridge._ha_instance_id_prefix if bridge._ha_serial_enabled else None
        payload, _config_valid, invalid_ids = build_devices_list_json(
            bridge._entities,
            ids_to_publish,
            bridge._redefinitions,
            default_home=location,
            default_room=location,
            auto_parent_id=auto_parent,
            ha_serial_prefix=ha_serial_prefix,
        )
        if invalid_ids:
            bridge._stats.validation_failures = invalid_ids
            _LOGGER.warning(
                "%d devices excluded from config (validation failed): %s",
                len(invalid_ids),
                ", ".join(invalid_ids),
            )
        topic = f"{bridge._root_topic}/up/config"
        payload_str = payload if isinstance(payload, str) else ""
        _LOGGER.debug(
            "Publishing config to %s (%d bytes): %s",
            topic,
            len(payload_str),
            payload,
        )
        if not await self._publish_logged(topic, payload_str, "config"):
            return
        self._last_config_publish_time = time.monotonic()
        _LOGGER.info(
            "Published device config to Sber (%d entities): %s",
            len(ids_to_publish),
            ", ".join(ids_to_publish),
        )

        bridge._ack_audit.schedule_audit()

        unack = bridge.unacknowledged_entities
        if unack:
            _LOGGER.info(
                "Waiting for Sber ack on %d entities (audit in %ds): %s",
                len(unack),
                int(bridge._ack_audit_delay),
                ", ".join(unack),
            )
