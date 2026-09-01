"""Sber Smart Home MQTT Bridge - core bridge logic.

Manages:
- Async MQTT connection to Sber cloud broker (aiomqtt)
- HA state change listening and publishing to Sber
- Sber command reception and forwarding to HA services
- Connection health monitoring and device acknowledgment tracking
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from functools import cached_property
from typing import Any

import aiomqtt
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import Event, HomeAssistant, callback

from .cloud_device_registry import OPTIONS_KEY as CLOUD_KNOWN_OPTIONS_KEY
from .cloud_device_registry import CloudDeviceRegistry
from .command_dispatcher import DispatcherDeps, SberCommandDispatcher
from .config_publish_gate import ConfigPublishGate
from .const import (
    CONF_ACK_AUDIT_DELAY,
    CONF_CONFIG_MAX_WAIT,
    CONF_CONFIG_SETTLE_DELAY,
    CONF_CONFIRM_DELAY,
    CONF_DEBOUNCE_DELAY,
    CONF_ENTITY_OPTIONS,
    CONF_HA_SERIAL_NUMBER,
    CONF_HUB_AUTO_PARENT,
    CONF_MAX_MQTT_PAYLOAD,
    CONF_MESSAGE_LOG_SIZE,
    CONF_RECONNECT_MAX,
    CONF_RECONNECT_MIN,
    CONF_SBER_BROKER,
    CONF_SBER_LOGIN,
    CONF_SBER_PASSWORD,
    CONF_SBER_PORT,
    CONF_SBER_VERIFY_SSL,
    SBER_GLOBAL_CONFIG_TOPIC,
    SBER_TOPIC_PREFIX,
    SETTINGS_DEFAULTS,
)
from .devices.base_entity import BaseEntity
from .devtools_hub import DevToolsHub
from .entity_registry import SberEntityLoader
from .ha_state_forwarder import HaStateForwarder
from .mqtt_client_service import (
    MqttClientService,
    MqttServiceHooks,
    SberMqttCredentials,
)
from .redefinitions_store import RedefinitionsStore
from .repairs import check_and_create_issues
from .sber_constants import MqttTopicSuffix
from .sber_publisher import ConfigPublishContext, PublisherDeps, SberPublisher
from .schema_validator import ValidationCollector
from .state_diff import DiffCollector
from .trace_collector import TraceCollector

_LOGGER = logging.getLogger(__name__)

RECONNECT_GRACE_TIMEOUT = 30.0
"""Maximum seconds to wait for Sber acknowledgment after (re)connect.

After a reconnect, the bridge publishes HA states and waits for Sber to
acknowledge them (via status_request or config_request) before accepting
commands.  This timeout is a fallback in case Sber never sends a request."""

DEFERRED_CONFIRM_SLOT_SUFFIX = "#deferred"
"""Suffix of the ``_confirm_tasks`` slot holding an entity-requested republish.

The default confirm is keyed by the bare entity id (unchanged), so an
entity that asks for a *second*, later publish through
``pending_confirm_delay`` gets its own slot instead of cancelling the
short one.  ``#`` cannot occur in an HA entity id, so the two namespaces
can never collide."""

LOG_PAYLOAD_MAX_CHARS = 8192
"""Maximum characters of a payload stored in the DevTools message log.

Payloads may legally be up to ``max_payload_size`` (1 MB by default), but
the DevTools ring buffer keeps ``message_log_size`` entries and pushes
each one synchronously to every WebSocket subscriber.  Storing full
payloads would bound memory at ``maxlen * max_payload_size`` (~50 MB with
defaults); truncating each stored copy to this limit bounds it at a few
hundred KB.  Only the DevTools copy is truncated — real MQTT traffic and
command handling always see the full payload."""


@dataclass
class BridgeStats:
    """Connection statistics and health metrics for the Sber MQTT bridge."""

    connected_since: float | None = None
    """Timestamp when the current connection was established."""

    messages_received: int = 0
    """Total MQTT messages received from Sber."""

    messages_sent: int = 0
    """Total MQTT messages published to Sber."""

    commands_received: int = 0
    """Total Sber commands processed."""

    config_requests: int = 0
    """Total config requests received from Sber."""

    status_requests: int = 0
    """Total status requests received from Sber."""

    errors_from_sber: int = 0
    """Total error messages received from Sber."""

    publish_errors: int = 0
    """Total failed publish attempts."""

    reconnect_count: int = 0
    """Total number of reconnections since startup."""

    acknowledged_entities: set[str] = field(default_factory=set)
    """Entity IDs that Sber has acknowledged (via status_request or command)."""

    collectively_acked_entities: set[str] = field(default_factory=set)
    """Subset of :attr:`acknowledged_entities` marked *without* being named.

    A ``status_request`` carrying no device list means "send me the state
    of everything you have".  It is a real acknowledgement — the cloud is
    talking to this hub — but it is a **collective** one: it names nobody,
    so it cannot vouch for any individual device.

    Keeping the two strengths apart is what lets the same signal answer two
    different questions honestly.  "Confirmed this session" (the panel
    counter) legitimately counts a collective ack, while the
    silent-rejection alarm
    (:attr:`~SberBridge.never_confirmed_entities`) must not: a device Sber
    silently rejected is still covered by "state of everything", so folding
    the two together made the alarm unable to fire at all — the user saw
    "confirmed: 36 / never confirmed: 0" on a bridge whose registry knew
    nothing (issue #57).

    An id leaves this set as soon as the cloud names it individually (a
    command, or a ``status_request`` listing it): the weak mark is then
    superseded by real per-device evidence.
    """

    last_error_detail: str = ""
    """Human-readable detail of the last error message from Sber cloud."""

    validation_failures: list[str] = field(default_factory=list)
    """Entity IDs that failed pydantic validation and were excluded from last config."""

    def as_dict(self) -> dict:
        """Return stats as a serializable dict."""
        now = time.monotonic()
        return {
            "connected_since": self.connected_since,
            "connection_uptime_seconds": (round(now - self.connected_since, 1) if self.connected_since else None),
            "messages_received": self.messages_received,
            "messages_sent": self.messages_sent,
            "commands_received": self.commands_received,
            "config_requests": self.config_requests,
            "status_requests": self.status_requests,
            "errors_from_sber": self.errors_from_sber,
            "publish_errors": self.publish_errors,
            "reconnect_count": self.reconnect_count,
            "acknowledged_entities": sorted(self.acknowledged_entities),
            "last_error_detail": self.last_error_detail,
            "validation_failures": list(self.validation_failures),
        }


class SberBridge:
    """Bridge between Home Assistant and Sber Smart Home MQTT cloud."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the bridge."""
        self._hass = hass
        self._entry = entry

        self._login: str = entry.data[CONF_SBER_LOGIN]
        self._password: str = entry.data[CONF_SBER_PASSWORD]
        self._broker: str = entry.data[CONF_SBER_BROKER]
        self._port: int = entry.data[CONF_SBER_PORT]
        self._verify_ssl: bool = entry.options.get(CONF_SBER_VERIFY_SSL, entry.data.get(CONF_SBER_VERIFY_SSL, True))

        self._root_topic = f"{SBER_TOPIC_PREFIX}/{self._login}"
        self._down_topic = f"{self._root_topic}/down"

        self._ha_instance_id_prefix: str = ""
        """Cached 8-char prefix of HA instance UUID; populated in ``async_start``."""
        self._entities: dict[str, BaseEntity] = {}
        self._enabled_entity_ids: list[str] = []
        # Persisted redefinitions delegated to RedefinitionsStore (v1.38.4).
        self._redef_store = RedefinitionsStore(hass, entry)
        self._entity_links: dict[str, dict[str, str]] = {}
        """Primary entity → {role: linked_entity_id}."""
        self._linked_reverse: dict[str, tuple[str, str]] = {}
        """Linked entity_id → (primary_entity_id, role)."""
        self._entity_loader = SberEntityLoader(hass, entry)

        # NOTE: connection state (_connected / _mqtt_client) is NOT stored
        # here — MqttClientService is the single owner; the bridge exposes
        # read/write forwarding properties below for compatibility.
        self._connection_task: asyncio.Task | None = None
        self._running = False

        # Configurable operational settings loaded from ``config_entry.options``.
        # All defaults live in ``SETTINGS_DEFAULTS`` (const.py) — this avoids
        # scattered ``opts.get(key, hardcoded_default)`` calls and keeps the
        # canonical values in exactly one place (DRY).
        self._load_settings_from_options(entry.options)

        self._unsub_lifecycle_listeners: list[Callable] = []

        self._stats = BridgeStats()

        # DevTools collector aggregate (message log, traces, diff, validation).
        # Built early: both the publisher and the dispatcher receive it as an
        # explicit dependency rather than reaching back through the bridge.
        self._devtools = DevToolsHub(message_log_size=self._message_log_size)

        # Delayed confirm tasks per entity (dedup: cancel previous on new command)
        self._confirm_tasks: dict[str, asyncio.Task] = {}

        # MQTT transport service: owns reconnect loop + publish + subscribe
        self._mqtt_service = MqttClientService(
            hass=hass,
            credentials=SberMqttCredentials(
                login=self._login,
                password=self._password,
                broker=self._broker,
                port=self._port,
                verify_ssl=self._verify_ssl,
            ),
            hooks=MqttServiceHooks(
                on_message=self._handle_mqtt_message,
                on_connected=self._handle_mqtt_connected,
                on_disconnected=self._handle_mqtt_disconnected,
            ),
            reconnect_min=self._reconnect_min,
            reconnect_max=self._reconnect_max,
        )

        # Ack audit owns the reconnect guard AND the silent-rejection
        # scheduler in one place — see ``ack_audit.py`` for the rationale.
        from .ack_audit import AckAudit

        self._ack_audit = AckAudit(
            hass,
            grace_timeout=RECONNECT_GRACE_TIMEOUT,
            audit_delay=self._ack_audit_delay,
            on_audit=self._run_ack_audit,
        )

        # Publish coordinator owns the three Sber publish flows and the
        # last-config timestamp; bridge keeps thin delegators below.
        self._publisher = SberPublisher(
            PublisherDeps(
                root_topic=self._root_topic,
                stats=self._stats,
                devtools=self._devtools,
                is_connected=self._is_transport_ready,
                publish=self._publish_via_transport,
                log_message=self._log_message,
                get_entities=lambda: self._entities,
                get_enabled_entity_ids=lambda: self._enabled_entity_ids,
                get_redefinitions=lambda: self._redef_store.raw,
                get_config_context=self._build_config_publish_context,
                on_config_published=self._on_config_published,
            )
        )

        # Gate: delay initial MQTT publish until HA is fully started so that
        # entity states (and therefore Sber features) are fully populated.
        self._ha_ready = asyncio.Event()

        # What the Sber cloud currently holds — the floor a publish must not
        # go below.  Fed by our own publishes and by the device list Sber
        # names in every status_request (issue #44).
        self._cloud_devices = CloudDeviceRegistry(hass, entry)

        # Coalescing gate in front of up/config: Sber treats every config
        # payload as the complete device list, so a partial one (entities
        # still loading) makes it drop and later re-create devices, losing
        # their room.  See ConfigPublishGate (issue #44).
        self._config_gate = ConfigPublishGate(
            loop=hass.loop,
            settle_delay=self._config_settle_delay,
            max_wait=self._config_max_wait,
            get_enabled_entity_ids=self._config_relevant_entity_ids,
            get_ready_entity_ids=self._ready_entity_ids,
            get_cloud_known_ids=lambda: self._cloud_devices.known,
            publish=self._publish_config,
            create_task=self._create_safe_task,
        )

        # HA → Sber event forwarder: owns state-change subscription + debouncing
        self._state_forwarder = HaStateForwarder(
            hass=hass,
            debounce_delay=self._debounce_delay,
            get_entities=lambda: self._entities,
            get_linked_reverse=lambda: self._linked_reverse,
            on_publish_states=self._publish_states,
            on_republish_config=self._request_config_publish,
            create_safe_task=self._create_safe_task,
            on_trace_state_change=self._trace_on_state_change,
            on_state_settled=self._sync_deferred_confirm,
        )

        # Sber protocol command dispatcher (commands, status/config request, etc.)
        self._command_dispatcher = SberCommandDispatcher(
            DispatcherDeps(
                hass=hass,
                stats=self._stats,
                ack_audit=self._ack_audit,
                publisher=self._publisher,
                redefinitions=self._redef_store,
                devtools=self._devtools,
                get_entities=lambda: self._entities,
                get_enabled_entity_ids=lambda: self._enabled_entity_ids,
                schedule_confirm=self.schedule_confirm,
                note_cloud_reported=self._cloud_devices.note_cloud_reported,
                refresh_repair_issues=self.refresh_repair_issues,
            )
        )

    # ------------------------------------------------------------------
    # Collaborator-facing hooks (the callables handed out in __init__)
    # ------------------------------------------------------------------

    def _is_transport_ready(self) -> bool:
        """Return True when a live MQTT session can accept a publish.

        Tolerates a torn-down service (``None``) so publish callers get a
        clean "skip" instead of an ``AttributeError``.
        """
        service = self._mqtt_service
        return service is not None and service.is_connected

    async def _publish_via_transport(self, topic: str, payload: str) -> None:
        """Publish through the MQTT service, or fail loudly if it is gone.

        Args:
            topic: Full MQTT topic.
            payload: Serialized payload.

        Raises:
            RuntimeError: When the transport service has been torn down
                or is not connected.
            aiomqtt.MqttError: Propagated from the transport.
        """
        service = self._mqtt_service
        if service is None:
            raise RuntimeError("MQTT service is not initialized")
        await service.publish(topic, payload)

    @property
    def config_publish_context(self) -> ConfigPublishContext:
        """Return the descriptor context the next config publish will use.

        Public so the DevTools "Raw config" preview can render exactly what
        would go on the wire.  Previously the preview called the payload
        builder without these arguments and silently got the builder's own
        defaults, so it always showed ``parent_id: "root"`` no matter how
        ``hub_auto_parent_id`` was set — reported as "the setting is not
        applied to the config" (issue #44).
        """
        return self._build_config_publish_context()

    def _build_config_publish_context(self) -> ConfigPublishContext:
        """Resolve the descriptor context for the next config publish."""
        ha_location = self._hass.config.location_name
        location = ha_location if ha_location and ha_location != "Home Assistant" else "Мой дом"
        return ConfigPublishContext(
            default_home=location,
            default_room=location,
            auto_parent_id=self._entry.options.get(CONF_HUB_AUTO_PARENT, False),
            ha_serial_prefix=self.ha_serial_prefix,
        )

    def _on_config_published(self, published_ids: list[str]) -> None:
        """React to a successful config publish.

        Records what the cloud now holds (so a later publish cannot drop one
        of those devices) and arms the silent-rejection audit.

        Args:
            published_ids: Entity ids that went out in the payload.
        """
        self._cloud_devices.note_published(published_ids)
        self._ack_audit.schedule_audit()
        unack = self.unacknowledged_entities
        if unack:
            _LOGGER.info(
                "Waiting for Sber ack on %d entities (audit in %ds): %s",
                len(unack),
                int(self._ack_audit_delay),
                ", ".join(unack),
            )

    @callback
    def schedule_confirm(self, entity_id: str) -> None:
        """(Re)arm the delayed state confirm(s) for one commanded entity.

        Always arms the short confirm that lets HA settle its async
        attribute updates (:attr:`_confirm_delay`).  An entity may ask for
        a *second*, later republish through a ``pending_confirm_delay``
        attribute — the impulse gate uses it to replace its emulated
        ``opening`` / ``closing`` value once the leaf's travel time is
        over (see :class:`~devices.gate.ImpulseGateEntity`).  Both go
        through the very same :meth:`_delayed_confirm` machinery, just in
        different slots, so there is exactly one timer mechanism to reason
        about (and to cancel on :meth:`async_stop`).

        Cancels a still-pending confirm in the same slot first, so a rapid
        command sequence produces exactly one confirmation per slot.  An
        entity that no longer asks for a deferred republish gets its slot
        *cleared* by :meth:`_sync_deferred_confirm`: a timer armed for a
        movement that has since been cancelled (counter-command, contact
        arrival, option switched off) would otherwise survive for the
        whole travel time and fire a redundant forced publish long after
        the fact.

        Args:
            entity_id: HA entity identifier that was just commanded.
        """
        self._arm_confirm(entity_id, entity_id, self._confirm_delay)
        self._sync_deferred_confirm(entity_id, floor=self._confirm_delay)

    @callback
    def _sync_deferred_confirm(self, entity_id: str, *, floor: float = 0.0, adopt_slot: bool = False) -> None:
        """Align the deferred republish slot with what the entity asks for.

        The entity names the next moment it wants to be published again
        through ``pending_confirm_delay`` (see
        :class:`~devices.gate.ImpulseGateEntity`: the end of an emulated
        travel, or the moment its board starts closing the gate on its
        own).  Timers belong to the bridge, so this is where that wish
        becomes a task.

        Called after a Sber command *and* after every HA state change of
        the entity or of one of its linked companions — an auto-close
        countdown is armed by a contact sensor, not by a command, and
        would otherwise never be scheduled.

        Args:
            entity_id: HA entity identifier to (re)schedule.
            floor: Delays at or below this are not worth their own slot
                because the plain confirm already covers them.
            adopt_slot: Set when the currently running task *is* the one
                registered in the slot (the deferred confirm re-arming
                itself for the next phase).  The registration is dropped
                first so :meth:`_arm_confirm` does not cancel the caller.
        """
        slot = f"{entity_id}{DEFERRED_CONFIRM_SLOT_SUFFIX}"
        if adopt_slot:
            self._confirm_tasks.pop(slot, None)
        entity = self._entities.get(entity_id)
        deferred = getattr(entity, "pending_confirm_delay", None)
        if isinstance(deferred, int | float) and not isinstance(deferred, bool) and deferred > floor:
            self._arm_confirm(slot, entity_id, float(deferred), background=True)
        else:
            self._cancel_confirm(slot)

    @callback
    def _cancel_confirm(self, slot: str) -> None:
        """Cancel and forget the confirm task registered under ``slot``.

        Args:
            slot: Key in :attr:`_confirm_tasks`; unknown slots are a no-op.
        """
        task = self._confirm_tasks.pop(slot, None)
        if task and not task.done():
            task.cancel()

    @callback
    def _arm_confirm(self, slot: str, entity_id: str, delay: float, *, background: bool = False) -> None:
        """Replace the confirm task registered under ``slot``.

        Args:
            slot: Key in :attr:`_confirm_tasks`.  The plain entity id is
                the default confirm; suffixed slots carry entity-requested
                deferred republishes.
            entity_id: HA entity identifier to re-publish.
            delay: Seconds to wait before publishing.
            background: Schedule as an *untracked* background task.
                Required for entity-requested delays: they are measured in
                whole leaf travel times (up to
                ``MAX_TRAVEL_TIME_SECONDS`` + margin = 600.5 s), and a
                tracked task sleeping that long violates the SHORT-LIVED
                contract of :meth:`_create_safe_task` — it would hold up
                every ``async_block_till_done`` (i.e. every test touching
                a moving gate) and still be running at HA's final
                shutdown stage.  Both kinds stay in :attr:`_confirm_tasks`
                and are cancelled by :meth:`async_stop` all the same.
        """
        self._cancel_confirm(slot)
        coro = self._delayed_confirm(entity_id, delay=delay, slot=slot)
        name = f"delayed_confirm_{slot}"
        self._confirm_tasks[slot] = (
            self._create_daemon_task(coro, name=name) if background else self._create_safe_task(coro, name=name)
        )

    @property
    def _redefinitions(self) -> dict[str, dict]:
        """Backward-compat proxy — actual storage lives on RedefinitionsStore."""
        return self._redef_store.raw

    # --- DevTools collector aliases ---------------------------------
    # The real owners live on ``self._devtools`` and are reachable via the
    # public ``trace_collector`` / ``diff_collector`` / ``validation_collector``
    # properties below.  These private aliases are kept only because test
    # modules outside this refactor's perimeter still use them.

    @property
    def _trace_collector(self) -> TraceCollector:
        """Deprecated alias for :attr:`trace_collector`."""
        return self._devtools.trace_collector

    @property
    def _diff_collector(self) -> DiffCollector:
        """Deprecated alias for :attr:`diff_collector`."""
        return self._devtools.diff_collector

    @property
    def _validation_collector(self) -> ValidationCollector:
        """Deprecated alias for :attr:`validation_collector`."""
        return self._devtools.validation_collector

    @property
    def is_connected(self) -> bool:
        """Return True if connected to Sber MQTT (owned by MqttClientService)."""
        return self._is_transport_ready()

    # --- Connection-state forwarding ---------------------------------
    # :class:`MqttClientService` is the single owner of ``_connected`` /
    # ``_client``; the bridge stores neither, so there is no duplicated
    # state — only forwarding.
    #
    # Reads: production code goes through :meth:`_is_transport_ready`
    # (via the public :attr:`is_connected`); the ``_connected`` getter is
    # kept only because tests and the setters below share the name.
    #
    # Writes: still production paths — :meth:`async_stop`,
    # :meth:`_mark_connected` and :meth:`_handle_disconnect` drive the
    # connect/disconnect/teardown transitions through these setters, and
    # tests reuse them to force a state without a live broker.
    #
    # Removing the setters therefore needs a public state-transition API
    # on :class:`MqttClientService` first (it currently exposes no way to
    # flip ``_connected`` / ``_client`` from outside), not just test edits.

    @property
    def _connected(self) -> bool:
        """Connection flag — single source of truth is :class:`MqttClientService`."""
        return self._is_transport_ready()

    @_connected.setter
    def _connected(self, value: bool) -> None:
        """Forward a forced connection state to the owning service."""
        self._mqtt_service._connected = value

    @property
    def _mqtt_client(self) -> aiomqtt.Client | None:
        """Live MQTT client — single source of truth is :class:`MqttClientService`."""
        return self._mqtt_service.client

    @_mqtt_client.setter
    def _mqtt_client(self, value: aiomqtt.Client | None) -> None:
        """Forward a forced client object to the owning service."""
        self._mqtt_service._client = value

    @property
    def config_entry(self) -> ConfigEntry:
        """Return the bridge's owning HA config entry (read-only access)."""
        return self._entry

    @property
    def connection_phase(self) -> str:
        """Return the current connection lifecycle phase.

        Phases:
            ``starting`` — HA not fully loaded, waiting for integrations.
            ``connecting`` — MQTT connection in progress.
            ``awaiting_ack`` — connected, published config, waiting for Sber to acknowledge.
            ``ready`` — fully operational, accepting commands.
            ``disconnected`` — not connected to MQTT broker.
        """
        if not self._running:
            return "disconnected"
        if not self._ha_ready.is_set():
            return "starting"
        if not self.is_connected:
            return "connecting"
        if self._ack_audit.is_awaiting:
            return "awaiting_ack"
        return "ready"

    @property
    def entities_count(self) -> int:
        """Return the number of loaded Sber entities."""
        return len(self._entities)

    @property
    def entities(self) -> dict[str, BaseEntity]:
        """Return the dict of loaded Sber entities (read-only view)."""
        return self._entities

    @property
    def enabled_entity_ids(self) -> list[str]:
        """Return a copy of the enabled entity ID list."""
        return list(self._enabled_entity_ids)

    @property
    def redefinitions(self) -> dict[str, dict]:
        """Return a copy of the entity redefinitions mapping.

        Values are per-entity dicts with optional ``name`` / ``room`` /
        ``home`` keys (see :class:`RedefinitionsStore`).
        """
        return dict(self._redefinitions)

    @property
    def entity_links(self) -> dict[str, dict[str, str]]:
        """Return the current entity link map."""
        return dict(self._entity_links)

    @property
    def linked_entity_ids(self) -> set[str]:
        """Return set of all linked entity IDs (not primary)."""
        return set(self._linked_reverse.keys())

    @property
    def stats(self) -> dict:
        """Return bridge statistics as a serializable dict."""
        return self._stats.as_dict()

    @property
    def ha_serial_prefix(self) -> str | None:
        """Return active per-HA serial prefix, or ``None`` when feature is off."""
        return self._ha_instance_id_prefix if self._ha_serial_enabled else None

    @property
    def unacknowledged_entities(self) -> list[str]:
        """Return entity IDs Sber has not spoken about **in this session**.

        Note what this is *not*: evidence that the cloud rejected the
        device.  The acknowledgement mark is set when Sber sends a command
        or a ``status_request`` for the entity, and it lives in memory, so
        every restart empties it.  The cloud has no idea we restarted and
        no reason to speak up immediately — it will ask for state when the
        user opens the Salute app, issues a voice command, or its own poll
        comes round.  Right after a restart this list therefore contains
        *everything*, which says nothing about registration (issue #57).

        Use :attr:`never_confirmed_entities` for "something is actually
        wrong"; this property answers the narrower question of what has
        been confirmed since the bridge came up.
        """
        return [eid for eid in self._enabled_entity_ids if eid not in self._stats.acknowledged_entities]

    @property
    def cloud_known_entities(self) -> list[str]:
        """Return exposed entity IDs the cloud is believed to hold.

        Backed by :class:`~cloud_device_registry.CloudDeviceRegistry`,
        which persists into ``ConfigEntry.options`` and therefore survives
        a restart.  This is the closest thing to "the cloud accepted it"
        that the protocol allows: there is no way to *ask* Sber what it
        holds — we only publish on ``up/config`` / ``up/status`` and learn
        from the ids it names in ``down/status_request``.
        """
        known = self._cloud_devices.known
        return [eid for eid in self._enabled_entity_ids if eid in known]

    @callback
    def forget_cloud_devices(self, entity_ids: Iterable[str]) -> None:
        """Drop entity ids from the persisted "cloud holds it" registry.

        Called when the user un-exposes entities.  Normally the next config
        publish mirrors the shorter list on its own, but it cannot when the
        shorter list is *empty*: a publish carrying no device is refused as
        evidence (see
        :meth:`~cloud_device_registry.CloudDeviceRegistry.note_published`),
        so "remove everything" would otherwise leave the registry claiming
        devices nobody exposes any more.

        Args:
            entity_ids: Entity ids the user removed from the bridge.
        """
        self._cloud_devices.forget(entity_ids)

    @property
    def cloud_device_registry_state(self) -> dict[str, Any]:
        """Return the raw cloud-device registry state, for diagnostics.

        Deliberately unfiltered and paired with what is on disk: when the
        panel reports "known to Sber: 0" the question is *which* of the two
        is empty — the live set, the persisted key, or neither (in which
        case the panel is at fault).  Answering that from a diagnostics
        download is the whole point; issue #57 was diagnosed by guesswork
        because none of this was in the dump.

        Returns:
            Mapping with the in-memory set (``known``), the value persisted
            in ``ConfigEntry.options`` (``persisted``), the exposed subset
            the panel shows (``known_exposed``), and whether a config
            publish has succeeded since this bridge came up.
        """
        persisted = self._entry.options.get(CLOUD_KNOWN_OPTIONS_KEY) or []
        return {
            "known": sorted(self._cloud_devices.known),
            "persisted": sorted(str(eid) for eid in persisted),
            "known_exposed": self.cloud_known_entities,
            "never_confirmed": self.never_confirmed_entities,
            "config_published_this_session": self._publisher.last_config_publish_time is not None,
        }

    @property
    def never_confirmed_entities(self) -> list[str]:
        """Return exposed entities the cloud has never been seen to know.

        Neither confirmed in this session nor remembered from an earlier
        one.  Unlike :attr:`unacknowledged_entities` this does not light up
        after every restart, so it is the list worth alerting on: a device
        published repeatedly that the cloud never once asks about is the
        signature of a silent rejection.

        Only **named** evidence counts here.  A bare ``status_request``
        acknowledges every exposed entity collectively (see
        :attr:`SberStats.collectively_acked_entities`), and counting that
        as per-device confirmation disarmed the alarm permanently: a
        silently rejected device is still covered by "send me the state of
        everything", so it looked confirmed forever (issue #57).
        """
        known = self._cloud_devices.known
        named = self._stats.acknowledged_entities - self._stats.collectively_acked_entities
        return [eid for eid in self._enabled_entity_ids if eid not in known and eid not in named]

    @property
    def entities_missing_required_links(self) -> dict[str, list[str]]:
        """Return loaded composite entities whose required links are unmapped.

        A class with a non-empty
        :attr:`~devices.base_entity.BaseEntity.REQUIRED_LINK_ROLES` cannot
        publish a truthful state without its companion — an impulse gate
        without a reed contact reports ``close`` forever.  The wizard
        refuses to create such a device, but "add the entity, then set the
        category by hand" bypasses that check, so the half-configured
        device has to stay *visible* instead of silent: this property
        feeds the HA repair issue, diagnostics and the panel's device
        dialog.

        Returns:
            ``entity_id → unmapped role names`` (declaration order), empty
            when every composite device is fully linked.
        """
        missing: dict[str, list[str]] = {}
        for entity_id, entity in self._entities.items():
            required = getattr(entity, "REQUIRED_LINK_ROLES", ())
            if not required:
                continue
            linked = self._entity_links.get(entity_id, {})
            absent = [role for role in required if role not in linked]
            if absent:
                missing[entity_id] = absent
        return missing

    async def async_update_redefinition(self, entity_id: str, fields: dict[str, str | None]) -> dict[str, str]:
        """Merge redefinition fields for an entity and trigger config republish.

        Public API for frontend / WebSocket handlers to update a device's
        Sber-side name / room / home without reaching into private state.
        Delegates data mutation and debounced persistence to
        :meth:`RedefinitionsStore.async_update`.

        Args:
            entity_id: Target Sber entity identifier (must exist in the bridge).
            fields: Partial mapping with any of ``name`` / ``room`` / ``home``.
                An empty string or ``None`` for a key removes that field.

        Returns:
            Resulting redefinitions dict for the entity after merge.

        Raises:
            KeyError: If ``entity_id`` is not loaded in the bridge.
            HomeAssistantError: If the follow-up config publish fails.
        """
        if entity_id not in self._entities:
            raise KeyError(entity_id)
        existing = await self._redef_store.async_update(entity_id, fields)
        await self._publish_config()
        return existing

    async def async_update_entity_options(self, entity_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        """Merge per-entity device options for one entity and apply them live.

        Persists into ``entry.options[CONF_ENTITY_OPTIONS]`` and then
        pushes the merged values straight into the loaded entity instead
        of reloading the config entry: a reload tears the MQTT session
        down and back up, and dropping the bridge for a couple of seconds
        because someone flipped a checkbox is not a trade the user agreed
        to.  Same approach as :meth:`async_update_redefinition`.

        The entity is re-seeded from HA afterwards because some options
        change how *existing* readings are interpreted (a gate's
        ``invert_contact`` flips the meaning of the contact's last value),
        and both the config and this entity's state are republished
        because the model descriptor may change too (``travel_time`` /
        ``auto_close_time`` add ``allowed_values.open_state``).  The
        config publish covers *every* device on purpose: Sber reads each
        config payload as the complete device list, so a one-device
        payload would make the cloud drop and re-create everything else
        (issue #44).  Only the state publish is narrowed to the edited
        entity.

        Category-agnostic: which keys an entity accepts, what they mean
        and whether a value is usable is decided by the device class
        (``BaseEntity.ENTITY_OPTION_KEYS`` /
        ``validate_entity_options`` / ``apply_entity_options``).

        Args:
            entity_id: HA entity identifier.
            fields: Partial option mapping; only the keys present are
                changed.

        Returns:
            The merged option dict stored for this entity.

        Raises:
            KeyError: If ``entity_id`` is not loaded in the bridge.
            TypeError: If the entity's class accepts no options.
            ValueError: If the entity rejects one of the submitted values.
            HomeAssistantError: If the follow-up publish fails.
        """
        entity = self._entities.get(entity_id)
        if entity is None:
            raise KeyError(entity_id)
        if not entity.supports_entity_options:
            raise TypeError(f"{entity_id} ({entity.category}) has no configurable options")
        entity.validate_entity_options(fields)

        all_options: dict[str, dict] = dict(self._entry.options.get(CONF_ENTITY_OPTIONS, {}))
        merged: dict[str, Any] = {**all_options.get(entity_id, {}), **fields}
        all_options[entity_id] = merged
        new_options = dict(self._entry.options)
        new_options[CONF_ENTITY_OPTIONS] = all_options
        self._hass.config_entries.async_update_entry(self._entry, options=new_options)

        entity.apply_entity_options(merged)
        self._refresh_entity_from_ha(entity_id)
        # An option change both *destroys* and *creates* deadlines the
        # entity wants to be republished at: a gate drops a running
        # auto-close countdown whenever the delay changes (it was armed
        # against the old value), and re-seeding from HA above can arm a
        # fresh one.  Without this resync the slot armed for the previous
        # value survives — up to ``MAX_AUTO_CLOSE_TIME_SECONDS``, an hour
        # — and fires a redundant forced publish for a movement that was
        # cancelled long before.
        self._sync_deferred_confirm(entity_id)
        await self._publish_config()
        await self._publish_states([entity_id], force=True)
        return merged

    async def async_update_gate_options(self, entity_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        """Deprecated alias of :meth:`async_update_entity_options`.

        Kept because the per-entity option store shipped for impulse gates
        first (v1.42) and this name is part of that public surface.

        Args:
            entity_id: HA entity identifier of the gate relay.
            fields: Partial gate-option mapping.

        Returns:
            The merged option dict stored for this entity.
        """
        return await self.async_update_entity_options(entity_id, fields)

    @callback
    def _refresh_entity_from_ha(self, entity_id: str) -> None:
        """Re-apply the current HA states of an entity and its linked companions.

        Mirrors what :class:`SberEntityLoader` does at load time, without
        rebuilding the entity: used after a settings change that alters how
        the already-received readings must be interpreted.  Failures are
        contained per entity (same narrow tuple as the loader) — a broken
        refresh must not take down the caller's WebSocket command.

        Args:
            entity_id: HA entity identifier of the primary entity.
        """
        entity = self._entities.get(entity_id)
        if entity is None:
            return

        def _apply(source_id: str, role: str | None) -> None:
            """Feed one HA state back into the entity, isolating failures."""
            state = self._hass.states.get(source_id)
            if state is None:
                return
            ha_state = {
                "entity_id": source_id,
                "state": state.state,
                "attributes": dict(state.attributes),
            }
            try:
                if role is None:
                    entity.fill_by_ha_state(ha_state)
                else:
                    entity.update_linked_data(role, ha_state)
            except (TypeError, ValueError, KeyError, AttributeError):
                _LOGGER.warning(
                    "Failed to refresh %s from %s (role=%s)",
                    entity_id,
                    source_id,
                    role,
                    exc_info=True,
                )

        _apply(entity_id, None)
        for role, linked_id in self._entity_links.get(entity_id, {}).items():
            _apply(linked_id, role)

    def _config_relevant_entity_ids(self) -> list[str]:
        """Entities whose readiness affects the published config.

        Includes linked companions: a temperature sensor's ``humidity``
        feature comes from its linked sibling, so publishing before that
        sibling reports yields a *narrower* feature set — and, since the
        model id is a digest of the capabilities, a different model id for
        the very same physical device on every restart (issue #44).
        """
        return [*self._enabled_entity_ids, *self._linked_reverse]

    def _ready_entity_ids(self) -> set[str]:
        """Entities that already have state (primaries and linked alike)."""
        ready = {eid for eid, ent in self._entities.items() if ent.is_filled_by_state}
        ready |= {eid for eid in self._linked_reverse if self._hass.states.get(eid) is not None}
        return ready

    async def _request_config_publish(self) -> None:
        """Ask the gate for a config publish instead of firing one now.

        Called when an entity becomes available or its feature set changes.
        During startup these fire once per entity, and each individual
        publish would be an incomplete device list — which Sber treats as
        "the rest were removed" (issue #44).  The gate coalesces the burst
        into a single complete payload.
        """
        self._config_gate.request("entity availability change")

    async def async_republish_config(self) -> None:
        """Public wrapper for forcing a device config republish to Sber.

        Explicit user action — bypasses the coalescing gate so the panel's
        "Re-publish" button is immediate.
        """
        await self._config_gate.flush_now()

    def _attach_error_logger(self, task: asyncio.Task, name: str | None) -> asyncio.Task:
        """Log any unhandled exception of ``task`` instead of losing it.

        Without this, a failing fire-and-forget task surfaces only as
        asyncio's ``Task exception was never retrieved`` at GC time.

        Args:
            task: Task to observe.
            name: Human-readable name used in the log message.

        Returns:
            The same task, for call chaining.
        """

        def _done_cb(t: asyncio.Task) -> None:
            if t.cancelled():
                return
            exc = t.exception()
            if exc is not None:
                _LOGGER.warning(
                    "Background task %s failed: %s",
                    name or t.get_name(),
                    exc,
                    exc_info=exc,
                )

        task.add_done_callback(_done_cb)
        return task

    def _create_safe_task(self, coro: Any, *, name: str | None = None) -> asyncio.Task:
        """Create a SHORT-LIVED tracked task with error logging.

        Use for work that finishes on its own (debounced publish, delayed
        confirm).  These are tracked by Home Assistant, so
        ``async_block_till_done`` — and therefore tests and shutdown —
        wait for them, which is what we want for short work.

        Do NOT use for loops that run for the lifetime of the entry: a
        tracked never-ending task blocks HA bootstrap until it times out.
        Use :meth:`_create_daemon_task` instead.

        Args:
            coro: Coroutine to schedule.
            name: Optional task name for log messages.

        Returns:
            The created asyncio task; callers may store it for cancellation.
        """
        return self._attach_error_logger(self._hass.async_create_task(coro, eager_start=True), name)

    def _create_daemon_task(self, coro: Any, *, name: str) -> asyncio.Task:
        """Create a LONG-RUNNING background task with error logging.

        ``hass.async_create_background_task`` is explicitly excluded from
        ``async_block_till_done`` and is cancelled on HA shutdown, so a
        never-ending loop scheduled this way does not hold up startup.

        This matters: the MQTT connection loop runs forever by design, and
        scheduling it as a tracked task made HA's bootstrap wait on it until
        the setup timeout fired ("Setup timed out for bootstrap waiting on
        ... _mqtt_connection_loop - moving forward"), delaying every start.

        Args:
            coro: Coroutine to schedule.
            name: Task name (required — it shows up in HA diagnostics).

        Returns:
            The created asyncio task; callers may store it for cancellation.
        """
        return self._attach_error_logger(self._hass.async_create_background_task(coro, name, eager_start=True), name)

    @property
    def message_log(self) -> list[dict[str, Any]]:
        """Return the DevTools outbound-message ring buffer (delegates to hub)."""
        return self._devtools.message_log

    def clear_message_log(self) -> None:
        """Clear the DevTools message log (delegates to hub)."""
        self._devtools.clear_message_log()

    def _load_settings_from_options(self, options: dict) -> None:
        """Load operational settings from ``config_entry.options`` dict.

        Drives attribute assignment from ``SETTINGS_DEFAULTS`` so that every
        default lives in exactly one place.  Called both from ``__init__``
        and from ``apply_settings`` (runtime update).

        Args:
            options: Config entry options dict.
        """
        self._reconnect_min: int = int(options.get(CONF_RECONNECT_MIN, SETTINGS_DEFAULTS[CONF_RECONNECT_MIN]))
        self._reconnect_max: int = int(options.get(CONF_RECONNECT_MAX, SETTINGS_DEFAULTS[CONF_RECONNECT_MAX]))
        self._debounce_delay: float = float(options.get(CONF_DEBOUNCE_DELAY, SETTINGS_DEFAULTS[CONF_DEBOUNCE_DELAY]))
        self._max_payload_size: int = int(options.get(CONF_MAX_MQTT_PAYLOAD, SETTINGS_DEFAULTS[CONF_MAX_MQTT_PAYLOAD]))
        self._message_log_size: int = int(options.get(CONF_MESSAGE_LOG_SIZE, SETTINGS_DEFAULTS[CONF_MESSAGE_LOG_SIZE]))
        self._confirm_delay: float = float(options.get(CONF_CONFIRM_DELAY, SETTINGS_DEFAULTS[CONF_CONFIRM_DELAY]))
        self._ack_audit_delay: float = float(options.get(CONF_ACK_AUDIT_DELAY, SETTINGS_DEFAULTS[CONF_ACK_AUDIT_DELAY]))
        self._config_settle_delay: float = float(
            options.get(CONF_CONFIG_SETTLE_DELAY, SETTINGS_DEFAULTS[CONF_CONFIG_SETTLE_DELAY])
        )
        self._config_max_wait: float = float(options.get(CONF_CONFIG_MAX_WAIT, SETTINGS_DEFAULTS[CONF_CONFIG_MAX_WAIT]))
        self._ha_serial_enabled: bool = bool(
            options.get(CONF_HA_SERIAL_NUMBER, SETTINGS_DEFAULTS[CONF_HA_SERIAL_NUMBER])
        )
        # verify_ssl has a special path: config_entry.data fallback for migrated entries
        self._verify_ssl: bool = bool(
            options.get(
                CONF_SBER_VERIFY_SSL,
                self._entry.data.get(CONF_SBER_VERIFY_SSL, SETTINGS_DEFAULTS[CONF_SBER_VERIFY_SSL]),
            )
        )

    def apply_settings(self, options: dict) -> None:
        """Apply changed operational settings without full bridge restart.

        Settings that take effect immediately: debounce_delay, max_mqtt_payload_size,
        message_log_size.
        Settings that take effect on next reconnect: reconnect_min, reconnect_max, verify_ssl.

        Args:
            options: Config entry options dict.
        """
        self._load_settings_from_options(options)
        self._state_forwarder.set_debounce_delay(self._debounce_delay)
        self._config_gate.update_delays(settle_delay=self._config_settle_delay, max_wait=self._config_max_wait)
        self._mqtt_service.update_backoff_limits(self._reconnect_min, self._reconnect_max)
        self._mqtt_service.update_verify_ssl(self._verify_ssl)
        self._devtools.resize(self._message_log_size)

        _LOGGER.info(
            "Bridge settings applied (debounce=%.2fs, log=%d)",
            self._debounce_delay,
            self._message_log_size,
        )

    async def async_publish_raw(self, payload: str, target: str) -> None:
        """Publish arbitrary JSON payload to Sber MQTT for debugging.

        Args:
            payload: Raw JSON string to publish.
            target: Topic suffix — either "config" or "status".

        Raises:
            RuntimeError: If not connected to MQTT broker.
            aiomqtt.MqttError: Propagated on transport errors (counted in
                ``publish_errors``).
        """
        topic = f"{self._root_topic}/up/{target}"
        try:
            await self._mqtt_service.publish(topic, payload)
        except aiomqtt.MqttError:
            self._stats.publish_errors += 1
            raise
        self._stats.messages_sent += 1
        self._log_message("out", topic, payload)

    async def async_inject_sber_message(
        self,
        topic: str,
        payload: str | bytes,
        *,
        mark_replay: bool = True,
    ) -> dict[str, Any]:
        """Feed a synthetic message into the dispatcher as if Sber sent it.

        Used by DevTools Replay / Inject: takes a topic (full
        ``sbdev/.../down/commands`` or a bare suffix like ``commands``)
        and runs it through the normal inbound pipeline —
        :class:`SberCommandDispatcher`, correlation trace, state diff,
        ack audit — without going through the MQTT broker.  No network
        round-trip means an injected command flows even when the bridge
        is offline, which is exactly what users want when debugging.

        Args:
            topic: Either the full MQTT topic as it would arrive from
                Sber cloud, or just the last segment (suffix) which is
                automatically expanded to ``{root}/down/{suffix}``.
            payload: Raw JSON body.  Bytes pass through as-is; strings
                are UTF-8 encoded to match the real on-wire shape.
            mark_replay: When True (default), the DevTools message log
                records the direction as ``"replay"`` instead of
                ``"in"`` so the UI can visually distinguish synthetic
                traffic from real Sber commands.  Set False to make
                the injection indistinguishable from real MQTT input
                (e.g. reproducing a bug for screenshot).

        Returns:
            Dict with ``{"topic": str, "handled": bool, "suffix": str}``.
            ``handled`` is False only when no dispatcher was registered
            for the given suffix (unknown topic).
        """
        full_topic = topic if "/" in topic else f"{self._down_topic}/{topic}"
        body = payload.encode("utf-8") if isinstance(payload, str) else payload

        # Route through the dispatch table used by the real MQTT handler.
        suffix = full_topic.rsplit("/", 1)[-1] if "/" in full_topic else full_topic
        decoded = body.decode("utf-8", errors="replace")
        self._log_message("replay" if mark_replay else "in", full_topic, decoded)

        if full_topic == SBER_GLOBAL_CONFIG_TOPIC:
            self._handle_global_config(body)
            return {"topic": full_topic, "handled": True, "suffix": "(global_config)"}

        handler = self._mqtt_dispatch.get(suffix)
        if handler is None:
            _LOGGER.warning("Inject: unhandled topic suffix %r", suffix)
            return {"topic": full_topic, "handled": False, "suffix": suffix}

        await handler(body)
        return {"topic": full_topic, "handled": True, "suffix": suffix}

    # ---------------------------------------------------------------------------
    # Message log subscriber management (for real-time DevTools push)
    # ---------------------------------------------------------------------------

    def subscribe_messages(self, callback_fn: Callable[[dict], None]) -> Callable[[], None]:
        """Subscribe to new MQTT messages in real time (delegates to hub).

        Args:
            callback_fn: Called with each new message dict.

        Returns:
            Unsubscribe callable.
        """
        return self._devtools.subscribe_messages(callback_fn)

    def _log_message(self, direction: str, topic: str, payload: str) -> None:
        """Log a message into the DevTools ring buffer (delegates to hub).

        The stored copy is truncated to :data:`LOG_PAYLOAD_MAX_CHARS` so the
        ring buffer and live WebSocket pushes stay memory-bounded regardless
        of ``max_payload_size``.  A truncation marker with the original
        length is appended so DevTools users can tell the copy is partial.

        Args:
            direction: ``"in"``, ``"out"`` or ``"replay"``.
            topic: Full MQTT topic.
            payload: Decoded payload text (truncated here if oversized).
        """
        if len(payload) > LOG_PAYLOAD_MAX_CHARS:
            payload = (
                payload[:LOG_PAYLOAD_MAX_CHARS]
                + f"<truncated: showing {LOG_PAYLOAD_MAX_CHARS} of {len(payload)} chars>"
            )
        self._devtools.log_message(direction, topic, payload)

    # ---------------------------------------------------------------------------
    # Correlation-timeline traces (DevTools #1)
    # ---------------------------------------------------------------------------

    @property
    def trace_collector(self) -> TraceCollector:
        """Return the correlation-trace collector (delegates to hub)."""
        return self._devtools.trace_collector

    @property
    def diff_collector(self) -> DiffCollector:
        """Return the state-diff collector (delegates to hub)."""
        return self._devtools.diff_collector

    @property
    def validation_collector(self) -> ValidationCollector:
        """Return the schema-validation collector (delegates to hub)."""
        return self._devtools.validation_collector

    def _trace_on_state_change(self, context_id: str | None, entity_id: str, state: dict) -> None:
        """Forwarder hook → append ``ha_state_changed`` to the correlation trace.

        When ``context_id`` is already known (because a Sber command opened
        the trace moments ago), the event joins that trace. Otherwise a new
        trace is opened with ``trigger="ha_state_change"`` so DevTools also
        surfaces user-initiated changes in the HA UI.
        """
        if not context_id:
            return
        self.trace_collector.record(
            context_id,
            type_="ha_state_changed",
            entity_id=entity_id,
            payload={"state": state.get("state"), "attributes": state.get("attributes")},
            trigger_if_new="ha_state_change",
        )

    async def async_start(self) -> None:
        """Start the bridge: load entities, subscribe to HA events, connect MQTT.

        HA state events are subscribed immediately (independent of MQTT connectivity)
        so that no state changes are lost while waiting for the first connection.
        MQTT connection is established in a background task with exponential backoff.
        """
        self._running = True
        # Cache the HA instance UUID prefix so the publish hot-path stays sync.
        # Used for the per-HA ``ha_serial_number`` loop-detection marker.
        from homeassistant.helpers import instance_id

        full_uuid = await instance_id.async_get(self._hass)
        self._ha_instance_id_prefix: str = full_uuid[:8]
        self._load_exposed_entities()
        self._subscribe_ha_events()
        # Daemon, not a tracked task: this loop never returns, so tracking it
        # would make HA bootstrap wait on it until the setup timeout.
        self._connection_task = self._create_daemon_task(
            self._mqtt_connection_loop(),
            name="mqtt_connection_loop",
        )

        # If HA is already running (e.g. integration reload), entities are
        # fully available — mark ready immediately.  Otherwise, wait for
        # EVENT_HOMEASSISTANT_STARTED to reload entities with real states.
        if self._hass.is_running:
            _LOGGER.debug("HA already running — entities loaded, marking ready")
            self._ha_ready.set()
        else:
            self._unsub_lifecycle_listeners.append(
                self._hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, self._on_homeassistant_started)
            )

    async def async_stop(self) -> None:
        """Stop the bridge: disconnect MQTT, unsubscribe from HA events.

        Idempotent — safe to call multiple times.  Cancels every timer and
        background task the bridge owns (state forwarder debounce, lifecycle
        listeners, ack-audit timer, delayed-confirm tasks, redefinitions
        debounce timer, MQTT connection loop) so nothing outlives the entry
        unload.  A pending redefinitions snapshot is flushed synchronously
        before shutdown so user edits are not lost on reload.
        """
        self._running = False

        # HA state-change listeners + debounced publish live in the forwarder
        self._state_forwarder.unsubscribe_all()

        for unsub in self._unsub_lifecycle_listeners:
            unsub()
        self._unsub_lifecycle_listeners.clear()

        # Cancel any pending ack-audit timer so it can't fire after shutdown
        self._ack_audit.cancel()

        # Cancel delayed-confirm tasks so they don't touch hass after unload
        for task in self._confirm_tasks.values():
            task.cancel()
        self._confirm_tasks.clear()

        # Cancel the redefinitions debounce timer and flush a pending
        # snapshot synchronously so a reload within the debounce window
        # cannot lose (or later overwrite) user edits.
        self._redef_store.shutdown()

        # Stop the MQTT service reconnect loop
        await self._mqtt_service.stop()

        if self._connection_task:
            self._connection_task.cancel()
            try:
                await self._connection_task
            except asyncio.CancelledError:
                pass
            except Exception:  # shutdown must not fail entry unload
                _LOGGER.exception("MQTT connection task raised during shutdown")
            self._connection_task = None

        self._config_gate.cancel()
        self._cloud_devices.shutdown()
        self._connected = False

    @callback
    def _reload_entities_and_resubscribe(self) -> None:
        """Atomic reload: rebuild entities and re-subscribe HA events.

        Must always be called together to keep subscriptions in sync with
        the entity set. Prevents stale subscriptions after entity list changes.
        """
        self._load_exposed_entities()
        self._subscribe_ha_events()

    def _load_exposed_entities(self) -> None:
        """Reload exposed entities via :class:`SberEntityLoader`.

        Uses swap-on-replace: delegates all registry lookup / YAML parsing
        / link resolution to the loader, then atomically copies the result
        into ``self._entities``, ``self._enabled_entity_ids``,
        ``self._entity_links``, ``self._linked_reverse`` and
        ``self._redefinitions``.  Prunes stale ack tracking and kicks off
        the post-load repairs check.
        """
        result = self._entity_loader.load(existing_redefinitions=self._redefinitions)

        # Atomic swap — readers see either old or new, never partial state
        self._entities = result.entities
        self._enabled_entity_ids = result.enabled_entity_ids
        self._entity_links = result.entity_links
        self._linked_reverse = result.linked_reverse
        self._redef_store.replace(result.redefinitions)

        # Prune stale ack tracking
        valid_ids = set(self._enabled_entity_ids)
        self._stats.acknowledged_entities &= valid_ids

        self._sync_deferred_confirms_after_load(valid_ids)

        # Only run repair checks after HA is fully started — during early
        # async_setup_entry many entities are still loading and linked
        # entity states are not yet available, causing false-positive
        # "broken link" warnings.
        if self._hass.is_running:
            self._create_safe_task(
                check_and_create_issues(self._hass, self),
                name="check_and_create_issues",
            )

    @callback
    def _sync_deferred_confirms_after_load(self, valid_ids: set[str]) -> None:
        """Register the deadlines entities arrived from the loader with.

        Loading is the third way a deferred republish can come into
        existence, next to a Sber command and an HA state change — and
        the only one with no event behind it.  A gate whose contact
        already reads "open" when the entry is set up arms its auto-close
        countdown inside the loader's initial ``update_linked_data``, i.e.
        before anything is listening.  Nothing would then turn that
        countdown into a published ``closing``: the fabricated phase
        would first surface on whatever unrelated publish comes next (a
        Sber ``status_request``, a config republish, an ack-audit forced
        publish) with no follow-up scheduled to take it back down, so the
        Sber app would show the gate as "closing" — control button
        blocked — until some unrelated state change happens to move it.
        That is exactly the "HA restarted while the gate stood open" case
        :data:`~devices.gate.GATE_OPTION_AUTO_CLOSE_TIME` exists for.

        Slots belonging to entities that did not survive the reload are
        dropped in the same pass: their timers would force a publish for
        an entity the bridge no longer knows.

        Args:
            valid_ids: Entity ids present after the atomic swap.
        """
        for slot in list(self._confirm_tasks):
            entity_id = slot.removesuffix(DEFERRED_CONFIRM_SLOT_SUFFIX)
            if slot != entity_id and entity_id not in valid_ids:
                self._cancel_confirm(slot)
        for entity_id in valid_ids:
            self._sync_deferred_confirm(entity_id)

    def _subscribe_ha_events(self) -> None:
        """Subscribe the :class:`HaStateForwarder` to the current entity set.

        Only manages state-change listeners (not lifecycle listeners like
        EVENT_HOMEASSISTANT_STARTED, which are tracked separately).
        """
        all_tracked = list(self._enabled_entity_ids)
        for linked_id in self._linked_reverse:
            if linked_id not in all_tracked:
                all_tracked.append(linked_id)
        self._state_forwarder.subscribe(all_tracked)

    @callback
    def _on_homeassistant_started(self, _event: Event) -> None:
        """Reload exposed entities after HA is fully started and republish.

        At async_setup_entry time, many entities are still unavailable/unknown.
        Once HA is fully started, all integrations have loaded their entities
        with real states — reload and republish so Sber gets correct data.
        """
        _LOGGER.debug("HA started — reloading exposed entities and republishing")
        self._reload_entities_and_resubscribe()
        # Signal that HA is ready.  If MQTT is already connected and waiting
        # in _mqtt_connection_loop, this will unblock the initial publish there.
        # If MQTT connected *after* HA started, _ha_ready is already set and
        # the loop publishes immediately — no duplicate publish needed here.
        if not self._ha_ready.is_set():
            self._ha_ready.set()
        else:
            # HA was already marked ready (shouldn't happen, but be safe) —
            # force republish since entities were just reloaded.
            if self.is_connected:
                self._config_gate.request("entities reloaded after HA start")
                self._create_safe_task(self._publish_states(force=True), name="republish_states")

    async def _mqtt_connection_loop(self) -> None:
        """Delegate the reconnect loop to :class:`MqttClientService`.

        All transport logic (including connection-state ownership) lives
        in :mod:`.mqtt_client_service`; the bridge only resets its own
        stats when the loop exits.
        """
        try:
            await self._mqtt_service.run()
        finally:
            self._stats.connected_since = None

    async def _handle_mqtt_connected(self, client: aiomqtt.Client) -> None:
        """MqttClientService hook: runs after each successful handshake.

        The service already owns the connection state (``client`` /
        ``connected`` flags); this hook only executes the Sber-specific
        handshake dance (initial publish, subscribe, ack-guard).

        Args:
            client: Live ``aiomqtt.Client`` from the service.
        """
        self._mark_connected()
        await self._wait_for_ha_ready()
        await self._perform_initial_publish()
        await self._subscribe_down_topics(client)
        self._ack_audit.activate_post_connect()
        _LOGGER.info(
            "Connected & published states → subscribed to commands (awaiting Sber ack, timeout %.0fs)",
            RECONNECT_GRACE_TIMEOUT,
        )
        # Message consumption is handled by MqttClientService itself —
        # it will call ``_handle_mqtt_message`` for each incoming message.

    async def _handle_mqtt_disconnected(self, err: Exception, unexpected: bool) -> bool:
        """MqttClientService hook: runs after a transport error.

        Defers to the ``_handle_disconnect`` helper for state reset,
        logging and repair triggering.
        """
        return await self._handle_disconnect(err, unexpected=unexpected)

    def _mark_connected(self) -> None:
        """Flip connection-related state flags after a successful MQTT handshake."""
        self._connected = True
        self._stats.connected_since = time.monotonic()
        _LOGGER.info(
            "Connected to Sber MQTT broker %s:%d (entities: %d)",
            self._broker,
            self._port,
            len(self._entities),
        )

    async def _wait_for_ha_ready(self) -> None:
        """Block until HA is fully started.

        Without this gate, lights can be published with an empty feature
        set (only ``on_off``) and Sber cloud may misclassify them
        (e.g. display a lamp as a fan).
        """
        if self._ha_ready.is_set():
            return
        _LOGGER.debug("MQTT connected, waiting for HA startup before publishing config")
        await self._ha_ready.wait()

    async def _perform_initial_publish(self) -> None:
        """Publish authoritative config + states BEFORE subscribing.

        HA state is authoritative.  We publish config + states FIRST so
        that Sber cloud knows the real device state BEFORE it can send
        any commands.  MQTT broker delivers messages on down/# only after
        SUBSCRIBE, so the message buffer is guaranteed to be empty of
        stale "corrective" commands when we start listening.
        """
        # Wait for the entity set to finish loading before the very first
        # publish: Sber reads every config payload as the complete device
        # list, so shipping one while a Zigbee coordinator is still bringing
        # devices up makes the cloud drop and later re-create them, losing
        # their room (issue #44).  Bounded by the gate's hard cap.
        await self._config_gate.wait_until_ready()
        if not await self._config_gate.flush_now():
            # The handshake used to continue in silence here: it subscribed,
            # served commands and looked healthy while Sber had never
            # received the device list — and the registry, fed only by a
            # *successful* publish, stayed empty for the whole session.  The
            # user saw nothing but "known to Sber: 0" (issue #57).  Say so,
            # and ask the gate for another attempt: a single dropped packet
            # must not cost the session its configuration.
            _LOGGER.error(
                "Initial device config did NOT reach Sber — the cloud has not received the device list. "
                "Retrying; check the errors above for the transport failure."
            )
            self._config_gate.request("initial config publish failed")
        await self._publish_states(force=True)

    async def _subscribe_down_topics(self, client: aiomqtt.Client) -> None:
        """Subscribe to Sber ``down/#`` and the global config topic."""
        await client.subscribe(f"{self._down_topic}/#")
        await client.subscribe(SBER_GLOBAL_CONFIG_TOPIC)

    @callback
    def refresh_repair_issues(self) -> None:
        """Recompute HA repair issues without awaiting.

        Wraps :func:`check_and_create_issues` in a safe background task so
        callers (notably the command dispatcher) can fire-and-forget after
        an ack arrives.  No-op when HA is not yet running so we don't fight
        the early-startup grace window in :meth:`_load_exposed_entities`.
        """
        if not self._hass.is_running:
            return
        self._create_safe_task(
            check_and_create_issues(self._hass, self),
            name="refresh_repair_issues",
        )

    def _run_ack_audit(self) -> None:
        """Bridge-side audit callback invoked by :class:`AckAudit` on timer.

        Detects silently rejected entities (accepted in the config
        handshake but never queried via ``status_request``) and
        triggers HA repair issue creation.  Kept on the bridge because
        it reads bridge state (``unacknowledged_entities``) and uses
        ``check_and_create_issues`` which needs the full bridge context.

        No-op while disconnected: without a live link Sber physically
        cannot acknowledge anything, so an audit would only produce
        false positives.
        """
        if not self.is_connected:
            return
        unack = self.unacknowledged_entities
        if unack:
            _LOGGER.warning(
                "Sber silent rejection detected: %d entities unacknowledged after %ds: %s",
                len(unack),
                int(self._ack_audit_delay),
                ", ".join(unack),
            )
            # Mark any active correlation traces for these entities as failed
            # so DevTools surfaces "Sber never acknowledged" cleanly.
            self.trace_collector.record_silent_rejection(unack)
        self._create_safe_task(
            check_and_create_issues(self._hass, self),
            name="ack_audit_issues",
        )

    async def _handle_disconnect(self, err: Exception, *, unexpected: bool = False) -> bool:
        """Handle MQTT disconnection: reset state, log, backoff, check repairs.

        Args:
            err: The exception that caused disconnection.
            unexpected: True for non-MqttError exceptions (logged at exception level).

        Returns:
            True if the loop should continue reconnecting, False if it should stop.
        """
        self._connected = False
        self._mqtt_client = None
        # Cancel the pending silent-rejection audit: with the link down no
        # ack can physically arrive, so letting the timer fire would create
        # false "silent rejection" warnings / repair issues that mask the
        # real (network) problem.  Reconnect re-arms it via publish_config.
        self._ack_audit.cancel()
        self._stats.connected_since = None
        self._stats.reconnect_count += 1
        if not self._running:
            return False
        interval = self._mqtt_service.reconnect_interval
        if unexpected:
            _LOGGER.error(
                "Unexpected MQTT error. Reconnecting in %ds...",
                interval,
                exc_info=err,
            )
        else:
            _LOGGER.warning(
                "Sber MQTT connection lost: %s. Reconnecting in %ds... (attempt #%d)",
                err,
                interval,
                self._stats.reconnect_count,
            )
        await check_and_create_issues(self._hass, self)
        return True

    async def _handle_mqtt_message(self, topic: str, payload: bytes) -> None:
        """Route incoming MQTT messages to registered handlers.

        Uses a dispatch table (``_mqtt_dispatch``) keyed by topic suffix
        instead of an ``if/elif`` chain for extensibility (OCP).

        The payload-size guard runs FIRST — before any decoding or DevTools
        buffering — so an oversized remote payload is never decoded or held
        in the ring buffers (memory-DoS protection).  A failure inside one
        topic handler is isolated here and never propagates to the transport.
        """
        self._stats.messages_received += 1
        _LOGGER.debug("MQTT <- %s (%d bytes)", topic, len(payload) if payload else 0)

        # Payload size guard (M2) — MUST run before decode / DevTools logging
        # so a hostile 256 MB MQTT message costs no memory beyond the socket.
        if payload and len(payload) > self._max_payload_size:
            _LOGGER.warning(
                "MQTT payload too large (%d bytes, max %d), dropping: %s",
                len(payload),
                self._max_payload_size,
                topic,
            )
            self._log_message(
                "in",
                topic,
                f"<dropped: payload of {len(payload)} bytes exceeds max_payload_size={self._max_payload_size}>",
            )
            return

        # DevTools: log incoming message
        decoded = payload.decode("utf-8", errors="replace") if isinstance(payload, bytes) else str(payload)[:500]
        self._log_message("in", topic, decoded)

        if topic == SBER_GLOBAL_CONFIG_TOPIC:
            self._handle_global_config(payload)
            return

        suffix = topic.rsplit("/", 1)[-1] if "/" in topic else topic
        handler = self._mqtt_dispatch.get(suffix)
        if handler is None:
            _LOGGER.debug("Unhandled MQTT topic suffix: %s", suffix)
            return
        try:
            await handler(payload)
        except asyncio.CancelledError:
            raise
        except Exception:  # per-handler isolation: one bad message must not break routing
            _LOGGER.exception("Error handling MQTT message on topic %s", topic)

    @cached_property
    def _mqtt_dispatch(self) -> dict[str, Callable[[bytes], Any]]:
        """Dispatch table from ``down/*`` topic suffix to async handler (cached)."""
        return {
            MqttTopicSuffix.COMMANDS: self._handle_sber_command,
            MqttTopicSuffix.STATUS_REQUEST: self._handle_sber_status_request,
            MqttTopicSuffix.CONFIG_REQUEST: self._handle_sber_config_request_async,
            MqttTopicSuffix.ERRORS: self._handle_sber_error_async,
            MqttTopicSuffix.CHANGE_GROUP: self._handle_change_group,
            MqttTopicSuffix.RENAME_DEVICE: self._handle_rename_device,
        }

    async def _handle_sber_config_request_async(self, _payload: bytes) -> None:
        """Async wrapper for :meth:`_handle_sber_config_request` (ignores payload)."""
        await self._handle_sber_config_request()

    async def _handle_sber_error_async(self, payload: bytes) -> None:
        """Async wrapper for :meth:`_handle_sber_error` (sync body)."""
        self._handle_sber_error(payload)

    async def _handle_sber_command(self, payload: bytes) -> None:
        """Delegate Sber command handling to :class:`SberCommandDispatcher`."""
        await self._command_dispatcher.handle_command(payload)

    async def _delayed_confirm(
        self,
        entity_id: str,
        delay: float | None = None,
        slot: str | None = None,
    ) -> None:
        """Delayed state confirmation for a commanded entity.

        Waits ``delay`` seconds (letting HA settle async attribute
        updates, or letting a gate leaf finish its travel) and then
        re-publishes the entity's current state to Sber.  Cleans up the
        ``_confirm_tasks`` entry on completion.

        Args:
            entity_id: HA entity identifier to confirm.
            delay: Seconds to wait; defaults to :attr:`_confirm_delay`.
            slot: Key this task is registered under in
                :attr:`_confirm_tasks`; defaults to ``entity_id``.
        """
        slot = slot if slot is not None else entity_id
        deferred_slot = slot.endswith(DEFERRED_CONFIRM_SLOT_SUFFIX)
        wait = self._confirm_delay if delay is None else delay
        due = self._hass.loop.time() + wait
        try:
            await asyncio.sleep(wait)
            entity = self._entities.get(entity_id)
            if entity is not None:
                ha_state = self._hass.states.get(entity_id)
                if ha_state is not None:
                    entity.fill_by_ha_state(
                        {
                            "entity_id": entity_id,
                            "state": ha_state.state,
                            "attributes": dict(ha_state.attributes),
                        }
                    )
            _LOGGER.debug("Delayed state confirm for %s", entity_id)
            await self._publish_states([entity_id], force=True)
            if deferred_slot and self._running and self._hass.loop.time() >= due:
                # One deferred publish can uncover the next one: a gate
                # whose auto-close countdown just elapsed publishes
                # ``closing`` here and now needs a second republish when
                # that phase times out.  Re-asking the entity keeps a
                # single timer mechanism instead of growing a second one.
                #
                # Only once the deadline this task was armed for has
                # really arrived, though: a confirm that woke up early
                # would re-arm the very same deadline it has not reached
                # yet, publish again, and spin.  And never after
                # :meth:`async_stop` has emptied ``_confirm_tasks`` — a
                # task registered then would outlive the entry.
                self._sync_deferred_confirm(entity_id, adopt_slot=True)
        finally:
            # Only pop if THIS task still owns the slot. A faster follow-up
            # command may have already replaced us; we must not delete the
            # successor's handle.
            if self._confirm_tasks.get(slot) is asyncio.current_task():
                self._confirm_tasks.pop(slot, None)

    async def _handle_sber_status_request(self, payload: bytes) -> None:
        """Delegate Sber status request to :class:`SberCommandDispatcher`.

        The request names the devices the cloud holds — direct evidence,
        recorded before dispatching so a restart cannot publish a list that
        drops one of them (issue #44).

        A request that names *nobody* ("state of every device") is weaker
        evidence, but it used to be thrown away entirely — the session
        marked all exposed entities acknowledged while the persistent
        registry learned nothing, so a bridge whose config publish had
        failed reported "known to Sber: 0" for its whole life (issue #57).
        It is handed to
        :meth:`~cloud_device_registry.CloudDeviceRegistry.note_cloud_active`,
        which uses it only to seed an empty registry.  The candidates are
        the exposed entities that have state: an entity without state was
        never serialized into a config payload, so the cloud cannot be
        holding it.
        """
        from .sber_protocol import parse_sber_status_request

        requested = parse_sber_status_request(payload)
        if requested:
            self._cloud_devices.note_cloud_reported(requested)
        else:
            ready = self._ready_entity_ids()
            self._cloud_devices.note_cloud_active([eid for eid in self._enabled_entity_ids if eid in ready])
        await self._command_dispatcher.handle_status_request(payload)

    async def _handle_sber_config_request(self) -> None:
        """Delegate Sber config request to :class:`SberCommandDispatcher`."""
        await self._command_dispatcher.handle_config_request()

    def _handle_sber_error(self, payload: bytes) -> None:
        """Delegate Sber error handling to :class:`SberCommandDispatcher`."""
        self._command_dispatcher.handle_error(payload)

    async def _handle_change_group(self, payload: bytes) -> None:
        """Delegate change_group handling to :class:`SberCommandDispatcher`."""
        await self._command_dispatcher.handle_change_group(payload)

    async def _handle_rename_device(self, payload: bytes) -> None:
        """Delegate rename_device handling to :class:`SberCommandDispatcher`."""
        await self._command_dispatcher.handle_rename_device(payload)

    @callback
    def _persist_redefinitions(self) -> None:
        """Delegate to :meth:`RedefinitionsStore.schedule_persist`."""
        self._redef_store.schedule_persist()

    @callback
    def _flush_redefinitions(self) -> None:
        """Delegate to :meth:`RedefinitionsStore._flush`."""
        self._redef_store._flush()

    def _handle_global_config(self, payload: bytes) -> None:
        """Delegate global config handling to :class:`SberCommandDispatcher`."""
        self._command_dispatcher.handle_global_config(payload)

    async def async_publish_entity_status(self, entity_id: str) -> None:
        """Publish the current state of a single entity to Sber cloud.

        Args:
            entity_id: HA entity identifier.
        """
        await self._publish_states([entity_id])

    async def _publish_states(
        self,
        entity_ids: list[str] | None = None,
        *,
        force: bool = False,
    ) -> None:
        """Delegate to :meth:`SberPublisher.publish_states`."""
        await self._publisher.publish_states(entity_ids, force=force)

    async def _publish_config(self, entity_ids: list[str] | None = None, *, force: bool = False) -> bool:
        """Delegate to :meth:`SberPublisher.publish_config`.

        Returns:
            True when Sber has the current descriptor, False when the
            publish did not reach the broker.
        """
        return await self._publisher.publish_config(entity_ids, force=force)
