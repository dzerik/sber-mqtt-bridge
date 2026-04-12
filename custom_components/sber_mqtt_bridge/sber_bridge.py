"""Sber Smart Home MQTT Bridge - core bridge logic.

Manages:
- Async MQTT connection to Sber cloud broker (aiomqtt)
- HA state change listening and publishing to Sber
- Sber command reception and forwarding to HA services
- Connection health monitoring and device acknowledgment tracking
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import aiomqtt
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import Event, HomeAssistant, callback

from .command_dispatcher import SberCommandDispatcher
from .const import (
    CONF_DEBOUNCE_DELAY,
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
from .entity_registry import SberEntityLoader
from .ha_state_forwarder import HaStateForwarder
from .message_logger import MessageLogger
from .mqtt_client_service import (
    MqttClientService,
    MqttServiceHooks,
    SberMqttCredentials,
)
from .repairs import check_and_create_issues
from .sber_constants import MqttTopicSuffix
from .sber_protocol import (
    build_devices_list_json,
    build_states_list_json,
)

_LOGGER = logging.getLogger(__name__)

RECONNECT_INTERVAL_MIN = SETTINGS_DEFAULTS[CONF_RECONNECT_MIN]
"""Default minimum seconds to wait before reconnecting after an MQTT connection loss."""

RECONNECT_INTERVAL_MAX = SETTINGS_DEFAULTS[CONF_RECONNECT_MAX]
"""Default maximum seconds to wait (5 minutes) with exponential backoff."""

MAX_MQTT_PAYLOAD_SIZE = SETTINGS_DEFAULTS[CONF_MAX_MQTT_PAYLOAD]
"""Default maximum MQTT payload size in bytes (1 MB) to prevent DoS from oversized messages."""

RECONNECT_GRACE_TIMEOUT = 30.0
"""Maximum seconds to wait for Sber acknowledgment after (re)connect.

After a reconnect, the bridge publishes HA states and waits for Sber to
acknowledge them (via status_request or config_request) before accepting
commands.  This timeout is a fallback in case Sber never sends a request."""


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

    last_message_time: float | None = None
    """Timestamp of the last message received."""

    reconnect_count: int = 0
    """Total number of reconnections since startup."""

    acknowledged_entities: set[str] = field(default_factory=set)
    """Entity IDs that Sber has acknowledged (via status_request or command)."""

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
        self._verify_ssl: bool = entry.options.get(
            CONF_SBER_VERIFY_SSL, entry.data.get(CONF_SBER_VERIFY_SSL, True)
        )

        self._root_topic = f"{SBER_TOPIC_PREFIX}/{self._login}"
        self._down_topic = f"{self._root_topic}/down"

        self._entities: dict[str, BaseEntity] = {}
        self._enabled_entity_ids: list[str] = []
        self._redefinitions: dict[str, dict] = {}
        self._entity_links: dict[str, dict[str, str]] = {}
        """Primary entity → {role: linked_entity_id}."""
        self._linked_reverse: dict[str, tuple[str, str]] = {}
        """Linked entity_id → (primary_entity_id, role)."""
        self._entity_loader = SberEntityLoader(hass, entry)

        self._mqtt_client: aiomqtt.Client | None = None
        self._connection_task: asyncio.Task | None = None
        self._running = False
        self._connected = False

        # Configurable operational settings loaded from ``config_entry.options``.
        # All defaults live in ``SETTINGS_DEFAULTS`` (const.py) — this avoids
        # scattered ``opts.get(key, hardcoded_default)`` calls and keeps the
        # canonical values in exactly one place (DRY).
        self._load_settings_from_options(entry.options)

        self._unsub_lifecycle_listeners: list[Callable] = []

        self._stats = BridgeStats()
        self._last_config_publish_time: float | None = None

        # Gate: delay initial MQTT publish until HA is fully started so that
        # entity states (and therefore Sber features) are fully populated.
        self._ha_ready = asyncio.Event()

        # HA → Sber event forwarder: owns state-change subscription + debouncing
        self._state_forwarder = HaStateForwarder(
            hass=hass,
            debounce_delay=self._debounce_delay,
            get_entities=lambda: self._entities,
            get_linked_reverse=lambda: self._linked_reverse,
            on_publish_states=self._publish_states,
            on_republish_config=self._publish_config,
            create_safe_task=self._create_safe_task,
        )

        # Sber protocol command dispatcher (commands, status/config request, etc.)
        self._command_dispatcher = SberCommandDispatcher(self)

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

        # Reconnect guard: reject Sber commands until Sber acknowledges
        # our published states (via status_request or config_request).
        # This prevents Sber cloud from overriding HA state with stale cache.
        self._awaiting_sber_ack: bool = False
        """True while waiting for Sber to acknowledge our states after (re)connect."""
        self._awaiting_sber_ack_deadline: float = 0.0
        """Fallback deadline: stop waiting even without acknowledgment."""

        # Delayed confirm tasks per entity (dedup: cancel previous on new command)
        self._confirm_tasks: dict[str, asyncio.Task] = {}

        # Debounced redefinitions persistence (avoid reload mid-MQTT-loop)
        self._redef_dirty = False
        self._redef_timer: asyncio.TimerHandle | None = None

        # Ring buffer + subscribers for MQTT message log (DevTools)
        self._msg_logger = MessageLogger(maxlen=self._message_log_size)

    @property
    def is_connected(self) -> bool:
        """Return True if connected to Sber MQTT."""
        return self._connected

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
        if not self._connected:
            return "connecting"
        if self._awaiting_sber_ack:
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
    def redefinitions(self) -> dict[str, str]:
        """Return a copy of the entity redefinitions mapping."""
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
    def unacknowledged_entities(self) -> list[str]:
        """Return entity IDs that were published but not yet acknowledged by Sber."""
        return [eid for eid in self._enabled_entity_ids if eid not in self._stats.acknowledged_entities]

    async def async_update_redefinition(
        self, entity_id: str, fields: dict[str, str | None]
    ) -> dict[str, str]:
        """Merge redefinition fields for an entity and trigger config republish.

        Public API for frontend / WebSocket handlers to update a device's
        Sber-side name / room / home without reaching into private state.

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
        existing = dict(self._redefinitions.get(entity_id, {}))
        for key in ("name", "room", "home"):
            if key not in fields:
                continue
            raw = fields[key]
            value = raw.strip() if isinstance(raw, str) else ""
            if value:
                existing[key] = value
            else:
                existing.pop(key, None)
        self._redefinitions[entity_id] = existing
        self._persist_redefinitions()
        await self._publish_config()
        return existing

    async def async_republish_config(self) -> None:
        """Public wrapper for forcing a device config republish to Sber."""
        await self._publish_config()

    def _create_safe_task(
        self, coro: Any, *, name: str | None = None
    ) -> asyncio.Task:
        """Create an asyncio task with error logging to prevent silent failures.

        Wraps ``hass.async_create_task`` with a done-callback that logs any
        unhandled exception at WARNING level.  This prevents the class of bugs
        where a fire-and-forget publish task silently drops a state update
        (similar to issue #3).

        Args:
            coro: Coroutine to schedule.
            name: Optional task name for log messages.

        Returns:
            The created asyncio task; callers may store it for cancellation.
        """
        task = self._hass.async_create_task(coro, eager_start=True)

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

    @property
    def message_log(self) -> list[dict[str, Any]]:
        """Return a snapshot of the MQTT message log ring buffer."""
        return self._msg_logger.entries

    def clear_message_log(self) -> None:
        """Clear the MQTT message log."""
        self._msg_logger.clear()

    def _load_settings_from_options(self, options: dict) -> None:
        """Load operational settings from ``config_entry.options`` dict.

        Drives attribute assignment from ``SETTINGS_DEFAULTS`` so that every
        default lives in exactly one place.  Called both from ``__init__``
        and from ``apply_settings`` (runtime update).

        Args:
            options: Config entry options dict.
        """
        self._reconnect_min: int = int(
            options.get(CONF_RECONNECT_MIN, SETTINGS_DEFAULTS[CONF_RECONNECT_MIN])
        )
        self._reconnect_max: int = int(
            options.get(CONF_RECONNECT_MAX, SETTINGS_DEFAULTS[CONF_RECONNECT_MAX])
        )
        self._reconnect_interval = self._reconnect_min
        self._debounce_delay: float = float(
            options.get(CONF_DEBOUNCE_DELAY, SETTINGS_DEFAULTS[CONF_DEBOUNCE_DELAY])
        )
        self._max_payload_size: int = int(
            options.get(CONF_MAX_MQTT_PAYLOAD, SETTINGS_DEFAULTS[CONF_MAX_MQTT_PAYLOAD])
        )
        self._message_log_size: int = int(
            options.get(CONF_MESSAGE_LOG_SIZE, SETTINGS_DEFAULTS[CONF_MESSAGE_LOG_SIZE])
        )
        # verify_ssl has a special path: config_entry.data fallback for migrated entries
        self._verify_ssl: bool = bool(
            options.get(
                CONF_SBER_VERIFY_SSL,
                self._entry.data.get(
                    CONF_SBER_VERIFY_SSL, SETTINGS_DEFAULTS[CONF_SBER_VERIFY_SSL]
                ),
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
        self._mqtt_service.update_backoff_limits(
            self._reconnect_min, self._reconnect_max
        )
        self._mqtt_service.update_verify_ssl(self._verify_ssl)
        self._msg_logger.resize(self._message_log_size)

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
        """
        if not self._connected or self._mqtt_client is None:
            msg = "Not connected to MQTT"
            raise RuntimeError(msg)

        topic = f"{self._root_topic}/up/{target}"
        await self._mqtt_client.publish(topic, payload)
        self._stats.messages_sent += 1
        self._log_message("out", topic, payload)

    # ---------------------------------------------------------------------------
    # Message log subscriber management (for real-time DevTools push)
    # ---------------------------------------------------------------------------

    def subscribe_messages(
        self, callback_fn: Callable[[dict], None]
    ) -> Callable[[], None]:
        """Subscribe to new MQTT messages in real time.

        Args:
            callback_fn: Called with each new message dict.

        Returns:
            Unsubscribe callable.
        """
        return self._msg_logger.subscribe(callback_fn)

    def _log_message(self, direction: str, topic: str, payload: str) -> None:
        """Append message to ring buffer and notify subscribers."""
        self._msg_logger.log(direction, topic, payload)

    async def async_start(self) -> None:
        """Start the bridge: load entities, subscribe to HA events, connect MQTT.

        HA state events are subscribed immediately (independent of MQTT connectivity)
        so that no state changes are lost while waiting for the first connection.
        MQTT connection is established in a background task with exponential backoff.
        """
        self._running = True
        self._load_exposed_entities()
        self._subscribe_ha_events()
        self._connection_task = asyncio.create_task(self._mqtt_connection_loop())

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
        """Stop the bridge: disconnect MQTT, unsubscribe from HA events."""
        self._running = False

        # HA state-change listeners + debounced publish live in the forwarder
        self._state_forwarder.unsubscribe_all()

        for unsub in self._unsub_lifecycle_listeners:
            unsub()
        self._unsub_lifecycle_listeners.clear()

        # Stop the MQTT service reconnect loop
        await self._mqtt_service.stop()

        if self._connection_task:
            self._connection_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._connection_task
            self._connection_task = None

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
        self._redefinitions = result.redefinitions

        # Prune stale ack tracking
        valid_ids = set(self._enabled_entity_ids)
        self._stats.acknowledged_entities &= valid_ids

        # Only run repair checks after HA is fully started — during early
        # async_setup_entry many entities are still loading and linked
        # entity states are not yet available, causing false-positive
        # "broken link" warnings.
        if self._hass.is_running:
            self._create_safe_task(
                check_and_create_issues(self._hass, self),
                name="check_and_create_issues",
            )

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
            if self._connected:
                self._create_safe_task(self._publish_config(), name="republish_config")
                self._create_safe_task(self._publish_states(force=True), name="republish_states")

    async def _mqtt_connection_loop(self) -> None:
        """Delegate the reconnect loop to :class:`MqttClientService`.

        Kept as a named method on ``SberBridge`` for test compatibility
        (some tests still reference ``bridge._mqtt_connection_loop``).
        All transport logic lives in :mod:`.mqtt_client_service`.
        """
        try:
            await self._mqtt_service.run()
        finally:
            self._mqtt_client = None
            self._connected = False
            self._stats.connected_since = None

    async def _handle_mqtt_connected(self, client: aiomqtt.Client) -> None:
        """MqttClientService hook: runs after each successful handshake.

        Mirrors ``client`` into ``self._mqtt_client`` / ``self._connected``
        for backwards compatibility with tests and legacy call sites, then
        executes the Sber-specific handshake dance (initial publish,
        subscribe, ack-guard, message consume).

        Args:
            client: Live ``aiomqtt.Client`` from the service.
        """
        self._mqtt_client = client
        self._mark_connected()
        await self._wait_for_ha_ready()
        await self._perform_initial_publish()
        await self._subscribe_down_topics(client)
        self._setup_ack_guard()
        _LOGGER.info(
            "Connected & published states → subscribed to commands "
            "(awaiting Sber ack, timeout %.0fs)",
            RECONNECT_GRACE_TIMEOUT,
        )
        # Message consumption is handled by MqttClientService itself —
        # it will call ``_handle_mqtt_message`` for each incoming message.

    async def _handle_mqtt_disconnected(
        self, err: Exception, unexpected: bool
    ) -> bool:
        """MqttClientService hook: runs after a transport error.

        Clears cached transport state, defers to the existing
        ``_handle_disconnect`` helper for logging / repair triggering.
        """
        self._mqtt_client = None
        return await self._handle_disconnect(err, unexpected=unexpected)

    def _mark_connected(self) -> None:
        """Flip connection-related state flags after a successful MQTT handshake."""
        self._connected = True
        self._reconnect_interval = self._reconnect_min
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
        _LOGGER.debug(
            "MQTT connected, waiting for HA startup before publishing config"
        )
        await self._ha_ready.wait()

    async def _perform_initial_publish(self) -> None:
        """Publish authoritative config + states BEFORE subscribing.

        HA state is authoritative.  We publish config + states FIRST so
        that Sber cloud knows the real device state BEFORE it can send
        any commands.  MQTT broker delivers messages on down/# only after
        SUBSCRIBE, so the message buffer is guaranteed to be empty of
        stale "corrective" commands when we start listening.
        """
        await self._publish_config()
        await self._publish_states(force=True)

    async def _subscribe_down_topics(self, client: aiomqtt.Client) -> None:
        """Subscribe to Sber ``down/#`` and the global config topic."""
        await client.subscribe(f"{self._down_topic}/#")
        await client.subscribe(SBER_GLOBAL_CONFIG_TOPIC)

    def _setup_ack_guard(self) -> None:
        """Activate the reconnect-ack guard with a fallback timeout.

        Rejects Sber commands until Sber acknowledges our published states
        (via status_request / config_request).  Sber cloud may send
        "corrective" commands based on stale cache — accepting them would
        override the real HA device state.  The fallback timer ensures we
        don't block forever even if Sber never sends a message.
        """
        self._awaiting_sber_ack = True
        self._awaiting_sber_ack_deadline = time.monotonic() + RECONNECT_GRACE_TIMEOUT
        self._hass.loop.call_later(RECONNECT_GRACE_TIMEOUT, self._ack_timeout_cb)

    def _ack_timeout_cb(self) -> None:
        """Fallback timer: auto-clear ack flag after grace period."""
        if self._awaiting_sber_ack:
            _LOGGER.info("Sber ack timeout reached (timer) — accepting commands")
            self._awaiting_sber_ack = False

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
        self._stats.connected_since = None
        self._stats.reconnect_count += 1
        if not self._running:
            return False
        interval = self._mqtt_service.reconnect_interval
        if unexpected:
            _LOGGER.exception(
                "Unexpected MQTT error. Reconnecting in %ds...", interval,
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
        """
        self._stats.messages_received += 1
        self._stats.last_message_time = time.monotonic()
        _LOGGER.debug("MQTT <- %s (%d bytes)", topic, len(payload) if payload else 0)

        # DevTools: log incoming message
        decoded = payload.decode("utf-8", errors="replace") if isinstance(payload, bytes) else str(payload)[:500]
        self._log_message("in", topic, decoded)

        # Payload size guard (M2)
        if payload and len(payload) > self._max_payload_size:
            _LOGGER.warning(
                "MQTT payload too large (%d bytes, max %d), dropping: %s",
                len(payload),
                self._max_payload_size,
                topic,
            )
            return

        if topic == SBER_GLOBAL_CONFIG_TOPIC:
            self._handle_global_config(payload)
            return

        suffix = topic.rsplit("/", 1)[-1] if "/" in topic else topic
        handler = self._mqtt_dispatch.get(suffix)
        if handler is None:
            _LOGGER.debug("Unhandled MQTT topic suffix: %s", suffix)
            return
        await handler(payload)

    @property
    def _mqtt_dispatch(self) -> dict[str, Callable[[bytes], Any]]:
        """Return dispatch table from ``down/*`` topic suffix to async handler."""
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

    async def _delayed_confirm(self, entity_id: str) -> None:
        """Delayed state confirmation for a commanded entity.

        Waits 1.5 seconds (letting HA settle async attribute updates) and
        then re-publishes the entity's current state to Sber.  Cleans up
        ``_confirm_tasks`` entry on completion.

        Args:
            entity_id: HA entity identifier to confirm.
        """
        try:
            await asyncio.sleep(1.5)
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
        finally:
            self._confirm_tasks.pop(entity_id, None)

    async def _handle_sber_status_request(self, payload: bytes) -> None:
        """Delegate Sber status request to :class:`SberCommandDispatcher`."""
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
        """Schedule debounced save of redefinitions to config entry options.

        Debounced to 2s to avoid triggering OptionsFlowWithReload mid-MQTT-loop
        when Sber sends rapid group/rename changes (e.g. user moves 10 devices).
        """
        self._redef_dirty = True
        if self._redef_timer is not None:
            self._redef_timer.cancel()
        self._redef_timer = self._hass.loop.call_later(
            2.0, self._flush_redefinitions
        )

    @callback
    def _flush_redefinitions(self) -> None:
        """Actually persist redefinitions to config entry options."""
        self._redef_timer = None
        if not self._redef_dirty:
            return
        self._redef_dirty = False
        new_options = {**self._entry.options, "redefinitions": self._redefinitions}
        self._hass.config_entries.async_update_entry(self._entry, options=new_options)

    def _handle_global_config(self, payload: bytes) -> None:
        """Delegate global config handling to :class:`SberCommandDispatcher`."""
        self._command_dispatcher.handle_global_config(payload)

    @callback
    def _on_ha_state_changed(self, event: Event) -> None:
        """Delegate HA state change to :class:`HaStateForwarder`.

        Kept as a thin proxy on ``SberBridge`` for backwards compatibility
        with tests that call ``bridge._on_ha_state_changed(event)`` directly.
        The real logic lives in :mod:`.ha_state_forwarder`.
        """
        self._state_forwarder._on_ha_state_changed(event)

    @callback
    def _schedule_debounced_publish(self, entity_id: str) -> None:
        """Delegate debounced publish scheduling to :class:`HaStateForwarder`.

        Kept as a thin proxy on ``SberBridge`` for backwards compatibility
        with tests.
        """
        self._state_forwarder._schedule_debounced_publish(entity_id)

    async def async_publish_entity_status(self, entity_id: str) -> None:
        """Publish the current state of a single entity to Sber cloud.

        Args:
            entity_id: HA entity identifier.
        """
        await self._publish_states([entity_id])

    async def async_republish(self) -> None:
        """Force republish full device config to Sber cloud."""
        await self._publish_config()

    async def _publish_states(
        self, entity_ids: list[str] | None = None, *, force: bool = False
    ) -> None:
        """Publish entity states to Sber MQTT.

        Args:
            entity_ids: Specific entity IDs to publish, or None for all enabled.
            force: If True, skip value diffing (used for status_request responses).
        """
        # Snapshot the client locally to avoid TOCTOU race: ``self._mqtt_client``
        # may become None between the connectivity check and the ``publish``
        # call if the transport drops mid-await.  The local reference is
        # stable even if the attribute is cleared concurrently.
        client = self._mqtt_client
        if not self._connected or client is None:
            return

        # Value change diffing: skip entities whose Sber state has not changed
        if not force and entity_ids:
            changed_ids = [
                eid for eid in entity_ids
                if (e := self._entities.get(eid)) is not None and e.has_significant_change()
            ]
            if not changed_ids:
                _LOGGER.debug("All %d entities unchanged, skipping publish", len(entity_ids))
                return
            entity_ids = changed_ids

        payload, payload_valid = build_states_list_json(
            self._entities, entity_ids, self._enabled_entity_ids
        )
        topic = f"{self._root_topic}/up/status"
        try:
            await client.publish(topic, payload)
        except aiomqtt.MqttError:
            self._stats.publish_errors += 1
            _LOGGER.exception("Error publishing states to Sber")
            return
        self._stats.messages_sent += 1
        # Only mark entities as published when the payload passed
        # validation.  If Sber silently rejects an invalid payload,
        # keeping the "dirty" flag ensures we retry on the next cycle.
        if payload_valid:
            for eid in (entity_ids or self._enabled_entity_ids):
                entity = self._entities.get(eid)
                if entity is not None:
                    entity.mark_state_published()
        # DevTools: log outgoing message
        self._log_message("out", topic, payload if isinstance(payload, str) else "")

    async def _publish_config(self, entity_ids: list[str] | None = None) -> None:
        """Publish device config to Sber MQTT."""
        client = self._mqtt_client
        if not self._connected or client is None:
            return

        ids_to_publish = entity_ids or self._enabled_entity_ids
        # Sber expects Russian home/room names. HA default "Home Assistant"
        # doesn't match redefinitions from Sber app (typically "Мой дом").
        ha_location = self._hass.config.location_name
        location = ha_location if ha_location and ha_location != "Home Assistant" else "Мой дом"
        auto_parent = self._entry.options.get(CONF_HUB_AUTO_PARENT, False)
        payload, _config_valid = build_devices_list_json(
            self._entities,
            ids_to_publish,
            self._redefinitions,
            default_home=location,
            default_room=location,
            auto_parent_id=auto_parent,
        )
        topic = f"{self._root_topic}/up/config"
        try:
            await client.publish(topic, payload)
        except aiomqtt.MqttError:
            self._stats.publish_errors += 1
            _LOGGER.exception("Error publishing config to Sber")
            return
        self._stats.messages_sent += 1
        self._last_config_publish_time = time.monotonic()
        _LOGGER.info(
            "Published device config to Sber (%d entities): %s",
            len(ids_to_publish),
            ", ".join(ids_to_publish),
        )
        # DevTools: log outgoing message
        self._log_message("out", topic, payload if isinstance(payload, str) else "")

        # Log unacknowledged entities for debugging
        unack = self.unacknowledged_entities
        if unack:
            _LOGGER.debug(
                "Entities not yet acknowledged by Sber (%d): %s",
                len(unack),
                ", ".join(unack),
            )
