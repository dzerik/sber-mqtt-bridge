"""Sber Smart Home MQTT publish coordinator.

Owns the three Sber publish flows extracted from :class:`SberBridge`:

* :meth:`publish_states` — outbound state updates on ``up/status``.
* :meth:`publish_config` — outbound device descriptor on ``up/config``.
* :meth:`publish_command_echo` — fast ack echo for incoming Sber commands.

Each method retains the side-effects of its predecessor in
``sber_bridge.SberBridge`` (DevTools instrumentation, ack audit hook,
stats bump, dirty-flag bookkeeping).  The bridge keeps thin delegators
for the two flows its own code and the WS API still call —
``_publish_states`` and ``_publish_config``; the echo has no bridge-side
delegator any more and is invoked on the publisher directly.

The publisher owns no bridge reference: every dependency arrives through
:class:`PublisherDeps` (callables + two collaborator objects), mirroring
the shape :class:`~.ha_state_forwarder.HaStateForwarder` already uses.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

import aiomqtt

from .sber_protocol import (
    build_devices_list_json,
    build_states_list_json,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterable

    from .bridge_ports import StatsPort
    from .devices.base_entity import BaseEntity
    from .devtools_hub import DevToolsHub

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ConfigPublishContext:
    """Descriptor-shaping inputs resolved by the bridge per config publish.

    Grouped into one value object so :class:`PublisherDeps` needs a single
    getter instead of four, and so the publisher never has to know where
    the values come from (HA config, config-entry options, instance UUID).
    """

    default_home: str
    """Home name used when an entity has no redefinition."""

    default_room: str
    """Room name used when an entity has no redefinition."""

    auto_parent_id: bool
    """Whether devices are grouped under an auto-generated hub parent."""

    ha_serial_prefix: str | None
    """Per-HA loop-detection marker, or ``None`` when the feature is off."""


@dataclass(frozen=True, slots=True)
class PublisherDeps:
    """Everything :class:`SberPublisher` is allowed to reach.

    Read-only values are passed directly, mutable/live state through
    callables so a hot reload on the bridge side stays visible without
    re-wiring the publisher.
    """

    root_topic: str
    """MQTT root topic (``sbdev/<login>``); ``up/...`` suffixes appended here."""

    stats: StatsPort
    """Counter bag bumped on every publish attempt."""

    devtools: DevToolsHub
    """Collector aggregate fed after each successful publish."""

    is_connected: Callable[[], bool]
    """Returns True while a usable MQTT transport exists."""

    publish: Callable[[str, str], Awaitable[None]]
    """Raw transport publish; raises ``MqttError``/``RuntimeError`` on failure."""

    log_message: Callable[[str, str, str], None]
    """DevTools ring-buffer sink ``(direction, topic, payload)``."""

    get_entities: Callable[[], dict[str, BaseEntity]]
    """Returns the live ``entity_id → BaseEntity`` map."""

    get_enabled_entity_ids: Callable[[], list[str]]
    """Returns the ordered list of exposed entity IDs."""

    get_redefinitions: Callable[[], dict[str, dict]]
    """Returns the per-entity name/room/home overrides."""

    get_config_context: Callable[[], ConfigPublishContext]
    """Resolves the descriptor context for the next config publish."""

    on_config_published: Callable[[], None]
    """Invoked after a successful config publish (arms the ack audit)."""


class SberPublisher:
    """Publish coordinator for the Sber MQTT bridge.

    Constructed with a :class:`PublisherDeps` bundle — no back-reference
    to :class:`~.sber_bridge.SberBridge` and therefore no access to its
    private attributes.
    """

    def __init__(self, deps: PublisherDeps) -> None:
        """Bind the publisher to its dependency bundle.

        Args:
            deps: Narrow dependency bundle assembled by the bridge.
        """
        self._deps = deps
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
        deps = self._deps
        try:
            # A torn-down transport surfaces as RuntimeError from the
            # injected publish callable: counted as a transport failure
            # instead of a silent no-op, so DevTools stats stay truthful.
            await deps.publish(topic, payload)
        except (aiomqtt.MqttError, RuntimeError):
            deps.stats.publish_errors += 1
            _LOGGER.exception("Error publishing %s to Sber", error_context)
            return False
        deps.stats.messages_sent += 1
        deps.log_message("out", topic, payload)
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
        devtools = self._deps.devtools
        entities = self._deps.get_entities()
        ids = list(entity_ids)
        for eid in ids:
            devtools.trace_collector.record_publish(eid, topic, payload)
        try:
            devtools.diff_collector.record_publish_payload(payload, topic=topic)
        except Exception:  # pragma: no cover — must never break publish
            _LOGGER.exception("DiffCollector.record_publish_payload failed%s", log_suffix)
        try:
            published = {eid: ent for eid in ids if (ent := entities.get(eid)) is not None}
            categories = {eid: ent.category for eid, ent in published.items()}
            declared = {eid: ent.get_final_features_list() for eid, ent in published.items()}
            devtools.validation_collector.record_publish_payload(
                payload,
                categories=categories,
                declared_features=declared,
            )
        except Exception:  # pragma: no cover — must never break publish
            _LOGGER.exception("ValidationCollector.record_publish_payload failed%s", log_suffix)

    @staticmethod
    def _snapshot_wire_state(entity: BaseEntity) -> dict | None:
        """Snapshot the entity state exactly as serialized into the payload.

        Swallows the same exception set as
        :func:`~.sber_protocol.build_states_list_json` (plus ``RuntimeError``,
        as in ``BaseEntity.mark_state_published``).  That is an invariant, not
        defensiveness: the payload builder deliberately drops a broken entity
        and still ships the batch, so re-serializing here must never be able
        to abort a publish that the builder already survived.  A snapshot
        failure yields ``None`` so the next diff treats the entity as changed.

        Args:
            entity: Entity being published.

        Returns:
            The ``to_sber_current_state()`` dict, or ``None`` on failure.
        """
        try:
            return entity.to_sber_current_state()
        except (RuntimeError, TypeError, ValueError, KeyError, AttributeError):
            _LOGGER.debug("Wire-state snapshot failed for %s", entity.entity_id, exc_info=True)
            return None

    @staticmethod
    def _payload_device_ids(payload: str) -> set[str]:
        """Return the device IDs that actually made it into a status payload.

        ``build_states_list_json`` silently drops entities that are not in
        ``enabled_entity_ids`` and entities whose serialization raised, and
        substitutes a synthetic ``root`` device when nothing is left.  Only
        the surviving IDs may be marked as published — marking a dropped
        entity would suppress its first real publish once it is re-enabled.

        Args:
            payload: The serialized status payload.

        Returns:
            Set of entity IDs present in ``devices`` (excluding ``root``).
        """
        try:
            devices = json.loads(payload)["devices"]
        except (ValueError, TypeError, KeyError):  # pragma: no cover — builder always emits valid JSON
            return set()
        if not isinstance(devices, dict):  # pragma: no cover — builder always emits a dict
            return set()
        return {eid for eid in devices if eid != "root"}

    async def publish_command_echo(self, devices: dict[str, dict]) -> None:
        """Publish immediate echo of a received Sber command as fast ack.

        Args:
            devices: ``devices`` dict from the incoming Sber command.

        Side effects (unchanged since this flow lived on the bridge, as
        ``SberBridge._publish_command_echo``, before the extraction):
        bumps ``messages_sent`` on success, logs the outbound message in
        the DevTools ring buffer, and records into the trace / diff /
        validation collectors.
        """
        deps = self._deps
        if not deps.is_connected():
            return

        entities = deps.get_entities()
        echo_devices: dict[str, dict] = {}
        for entity_id, cmd_data in devices.items():
            entity = entities.get(entity_id)
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
        topic = f"{deps.root_topic}/up/status"
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

        Residual (benign) race: with two overlapping ``publish_states``
        calls the older coroutine may overwrite the newer snapshot, which
        can cost one redundant publish of the *current* state — never a
        lost update, and it cannot loop (the redundant publish stores an
        up-to-date snapshot).  Serializing publishes behind a lock is not
        worth the added head-of-line blocking.
        """
        deps = self._deps
        if not deps.is_connected():
            return

        entities = deps.get_entities()
        if not force and entity_ids:
            changed_ids = [
                eid for eid in entity_ids if (e := entities.get(eid)) is not None and e.has_significant_change()
            ]
            if not changed_ids:
                _LOGGER.debug("All %d entities unchanged, skipping publish", len(entity_ids))
                return
            entity_ids = changed_ids

        # Freeze the publish set now: re-reading enabled_entity_ids after the
        # await could mark entities that were never in the payload (hot-reload).
        enabled_ids = deps.get_enabled_entity_ids()
        ids_to_publish = list(entity_ids) if entity_ids else list(enabled_ids)
        payload, payload_valid = build_states_list_json(entities, entity_ids, enabled_ids)
        snapshots: dict[str, dict | None] = {}
        if payload_valid:
            published_ids = self._payload_device_ids(payload)
            for eid in ids_to_publish:
                entity = entities.get(eid)
                if entity is not None and eid in published_ids:
                    snapshots[eid] = self._snapshot_wire_state(entity)
        topic = f"{deps.root_topic}/up/status"
        _LOGGER.debug(
            "Publishing state to %s (%d bytes): %s",
            topic,
            len(payload),
            payload,
        )
        if not await self._publish_logged(topic, payload, "states"):
            return
        for eid, snapshot in snapshots.items():
            entity = entities.get(eid)
            if entity is not None:
                # Hand the pre-await snapshot of what actually went on the
                # wire to the entity: re-serializing *now* (the no-argument
                # form) would re-introduce the lost update described above.
                entity.mark_state_published(snapshot=snapshot)
        self._record_devtools(topic, payload, ids_to_publish)

    async def publish_config(self, entity_ids: list[str] | None = None) -> None:
        """Publish device descriptor on ``up/config``.

        Args:
            entity_ids: Specific entity IDs to publish, or ``None`` for all
                enabled entities.

        Stores ``_last_config_publish_time`` on success, hands control back
        to the bridge via ``on_config_published`` (which arms the ack
        audit), and emits the DevTools log entry.
        """
        deps = self._deps
        if not deps.is_connected():
            return

        ids_to_publish = entity_ids or deps.get_enabled_entity_ids()
        ctx = deps.get_config_context()
        payload, _config_valid, invalid_ids = build_devices_list_json(
            deps.get_entities(),
            ids_to_publish,
            deps.get_redefinitions(),
            default_home=ctx.default_home,
            default_room=ctx.default_room,
            auto_parent_id=ctx.auto_parent_id,
            ha_serial_prefix=ctx.ha_serial_prefix,
        )
        if invalid_ids:
            deps.stats.validation_failures = invalid_ids
            _LOGGER.warning(
                "%d devices excluded from config (validation failed): %s",
                len(invalid_ids),
                ", ".join(invalid_ids),
            )
        topic = f"{deps.root_topic}/up/config"
        _LOGGER.debug(
            "Publishing config to %s (%d bytes): %s",
            topic,
            len(payload),
            payload,
        )
        if not await self._publish_logged(topic, payload, "config"):
            return
        self._last_config_publish_time = time.monotonic()
        _LOGGER.info(
            "Published device config to Sber (%d entities): %s",
            len(ids_to_publish),
            ", ".join(ids_to_publish),
        )

        deps.on_config_published()
