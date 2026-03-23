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
import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import aiomqtt
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_state_change_event

from .config_flow import create_ssl_context
from .const import (
    CONF_EXPOSED_ENTITIES,
    CONF_SBER_BROKER,
    CONF_SBER_LOGIN,
    CONF_SBER_PASSWORD,
    CONF_SBER_PORT,
    CONF_SBER_VERIFY_SSL,
    SBER_GLOBAL_CONFIG_TOPIC,
    SBER_TOPIC_PREFIX,
)
from .devices.base_entity import BaseEntity
from .sber_entity_map import create_sber_entity
from .sber_protocol import (
    build_devices_list_json,
    build_states_list_json,
    parse_sber_command,
    parse_sber_status_request,
)

_LOGGER = logging.getLogger(__name__)

RECONNECT_INTERVAL_MIN = 5
"""Minimum seconds to wait before reconnecting after an MQTT connection loss."""

RECONNECT_INTERVAL_MAX = 300
"""Maximum seconds to wait (5 minutes) with exponential backoff."""

MAX_MQTT_PAYLOAD_SIZE = 1_000_000
"""Maximum MQTT payload size in bytes (1 MB) to prevent DoS from oversized messages."""


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
            "connection_uptime_seconds": (
                round(now - self.connected_since, 1) if self.connected_since else None
            ),
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
        self._verify_ssl: bool = entry.data.get(CONF_SBER_VERIFY_SSL, True)

        self._root_topic = f"{SBER_TOPIC_PREFIX}/{self._login}"
        self._down_topic = f"{self._root_topic}/down"

        self._entities: dict[str, BaseEntity] = {}
        self._enabled_entity_ids: list[str] = []
        self._redefinitions: dict[str, dict] = {}

        self._mqtt_client: aiomqtt.Client | None = None
        self._connection_task: asyncio.Task | None = None
        self._running = False
        self._connected = False
        self._reconnect_interval = RECONNECT_INTERVAL_MIN

        self._unsub_state_listeners: list[Callable] = []
        self._unsub_lifecycle_listeners: list[Callable] = []

        self._stats = BridgeStats()
        self._last_config_publish_time: float | None = None

        # Debounce: coalesce rapid state changes into a single publish
        self._pending_publish_ids: set[str] = set()
        self._publish_timer: asyncio.TimerHandle | None = None

    @property
    def is_connected(self) -> bool:
        """Return True if connected to Sber MQTT."""
        return self._connected

    @property
    def entities_count(self) -> int:
        """Return the number of loaded Sber entities."""
        return len(self._entities)

    @property
    def enabled_entity_ids(self) -> list[str]:
        """Return a copy of the enabled entity ID list."""
        return list(self._enabled_entity_ids)

    @property
    def redefinitions(self) -> dict[str, str]:
        """Return a copy of the entity redefinitions mapping."""
        return dict(self._redefinitions)

    @property
    def stats(self) -> dict:
        """Return bridge statistics as a serializable dict."""
        return self._stats.as_dict()

    @property
    def unacknowledged_entities(self) -> list[str]:
        """Return entity IDs that were published but not yet acknowledged by Sber."""
        return [
            eid for eid in self._enabled_entity_ids
            if eid not in self._stats.acknowledged_entities
        ]

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

        # Re-load entities after HA is fully started to pick up any entities
        # that were not yet registered during early async_setup_entry.
        self._unsub_lifecycle_listeners.append(
            self._hass.bus.async_listen_once(
                EVENT_HOMEASSISTANT_STARTED, self._on_homeassistant_started
            )
        )

    async def async_stop(self) -> None:
        """Stop the bridge: disconnect MQTT, unsubscribe from HA events."""
        self._running = False

        # Cancel pending debounced publish
        if self._publish_timer is not None:
            self._publish_timer.cancel()
            self._publish_timer = None
        self._pending_publish_ids.clear()

        for unsub in self._unsub_state_listeners:
            unsub()
        self._unsub_state_listeners.clear()

        for unsub in self._unsub_lifecycle_listeners:
            unsub()
        self._unsub_lifecycle_listeners.clear()

        if self._connection_task:
            self._connection_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._connection_task
            self._connection_task = None

        self._connected = False

    def _load_exposed_entities(self) -> None:
        """Load exposed entity list from options and create Sber entity objects.

        Uses swap-on-replace pattern: builds a new dict, then atomically
        replaces the reference to avoid race conditions with concurrent readers.
        """
        new_enabled = list(self._entry.options.get(CONF_EXPOSED_ENTITIES, []))
        new_entities: dict[str, BaseEntity] = {}

        entity_reg = er.async_get(self._hass)
        device_reg = dr.async_get(self._hass)

        for entity_id in new_enabled:
            entry = entity_reg.async_get(entity_id)
            if entry is None:
                _LOGGER.warning("Entity %s not found in registry", entity_id)
                continue

            entity_data = {
                "entity_id": entry.entity_id,
                "area_id": entry.area_id or "",
                "device_id": entry.device_id,
                "name": entry.name or entry.original_name or entry.entity_id,
                "original_name": entry.original_name,
                "platform": entry.platform,
                "unique_id": entry.unique_id,
                "original_device_class": entry.original_device_class or "",
                "entity_category": entry.entity_category,
                "icon": entry.icon,
                "disabled_by": entry.disabled_by,
                "hidden_by": entry.hidden_by,
            }

            sber_entity = create_sber_entity(entity_id, entity_data)
            if sber_entity is not None:
                new_entities[entity_id] = sber_entity

                # Link device registry data for entities that belong to a device
                if entry.device_id is not None:
                    device = device_reg.async_get(entry.device_id)
                    if device is not None:
                        device_data = {
                            "id": device.id,
                            "name": device.name_by_user or device.name,
                            "area_id": device.area_id or "",
                            "manufacturer": device.manufacturer or "Unknown",
                            "model": device.model or "Unknown",
                            "model_id": device.model_id or "",
                            "hw_version": device.hw_version or "Unknown",
                            "sw_version": device.sw_version or "Unknown",
                        }
                        try:
                            sber_entity.link_device(device_data)
                        except ValueError:
                            _LOGGER.warning(
                                "Device ID mismatch for %s", entity_id
                            )

                state = self._hass.states.get(entity_id)
                if state is not None:
                    ha_state_dict = {
                        "entity_id": state.entity_id,
                        "state": state.state,
                        "attributes": dict(state.attributes),
                    }
                    sber_entity.fill_by_ha_state(ha_state_dict)

        # Atomic swap — readers see either old or new, never partial state
        self._entities = new_entities
        self._enabled_entity_ids = new_enabled

        _LOGGER.info(
            "Loaded %d Sber entities from %d exposed: %s",
            len(self._entities),
            len(self._enabled_entity_ids),
            ", ".join(self._enabled_entity_ids) if self._enabled_entity_ids else "(none)",
        )

    def _subscribe_ha_events(self) -> None:
        """Subscribe to HA state changes for exposed entities.

        Only manages state-change listeners (not lifecycle listeners like
        EVENT_HOMEASSISTANT_STARTED, which are tracked separately).
        """
        for unsub in self._unsub_state_listeners:
            unsub()
        self._unsub_state_listeners.clear()

        if self._enabled_entity_ids:
            unsub = async_track_state_change_event(
                self._hass,
                self._enabled_entity_ids,
                self._on_ha_state_changed,
            )
            self._unsub_state_listeners.append(unsub)

    @callback
    def _on_homeassistant_started(self, _event: Event) -> None:
        """Reload exposed entities after HA is fully started."""
        _LOGGER.debug("HA started — reloading exposed entities")
        self._load_exposed_entities()
        self._subscribe_ha_events()

    async def _mqtt_connection_loop(self) -> None:
        """Maintain persistent MQTT connection with exponential backoff reconnect."""
        ssl_context = await self._hass.async_add_executor_job(
            create_ssl_context, self._verify_ssl
        )

        while self._running:
            try:
                async with aiomqtt.Client(
                    hostname=self._broker,
                    port=self._port,
                    username=self._login,
                    password=self._password,
                    tls_context=ssl_context,
                ) as client:
                    self._mqtt_client = client
                    self._connected = True
                    self._reconnect_interval = RECONNECT_INTERVAL_MIN
                    self._stats.connected_since = time.monotonic()
                    _LOGGER.info(
                        "Connected to Sber MQTT broker %s:%d (entities: %d)",
                        self._broker, self._port, len(self._entities),
                    )

                    await client.subscribe(f"{self._down_topic}/#")
                    await client.subscribe(SBER_GLOBAL_CONFIG_TOPIC)

                    async for message in client.messages:
                        if not self._running:
                            break
                        self._stats.messages_received += 1
                        self._stats.last_message_time = time.monotonic()
                        await self._handle_mqtt_message(str(message.topic), message.payload)

            except aiomqtt.MqttError as err:
                self._connected = False
                self._mqtt_client = None
                self._stats.connected_since = None
                self._stats.reconnect_count += 1
                if not self._running:
                    break
                _LOGGER.warning(
                    "Sber MQTT connection lost: %s. Reconnecting in %ds... (attempt #%d)",
                    err, self._reconnect_interval, self._stats.reconnect_count,
                )
                await asyncio.sleep(self._reconnect_interval)
                self._reconnect_interval = min(self._reconnect_interval * 2, RECONNECT_INTERVAL_MAX)
            except asyncio.CancelledError:
                break
            except Exception:
                self._connected = False
                self._mqtt_client = None
                self._stats.connected_since = None
                self._stats.reconnect_count += 1
                if not self._running:
                    break
                _LOGGER.exception(
                    "Unexpected MQTT error. Reconnecting in %ds...",
                    self._reconnect_interval,
                )
                await asyncio.sleep(self._reconnect_interval)
                self._reconnect_interval = min(self._reconnect_interval * 2, RECONNECT_INTERVAL_MAX)

        self._mqtt_client = None
        self._connected = False
        self._stats.connected_since = None

    async def _handle_mqtt_message(self, topic: str, payload: bytes) -> None:
        """Route incoming MQTT messages to handlers."""
        suffix = topic.rsplit("/", 1)[-1] if "/" in topic else topic
        _LOGGER.debug("MQTT ← %s (%d bytes)", topic, len(payload) if payload else 0)

        # Payload size guard (M2)
        if payload and len(payload) > MAX_MQTT_PAYLOAD_SIZE:
            _LOGGER.warning(
                "MQTT payload too large (%d bytes, max %d), dropping: %s",
                len(payload), MAX_MQTT_PAYLOAD_SIZE, topic,
            )
            return

        if topic.endswith("/down/commands"):
            await self._handle_sber_command(payload)
        elif topic.endswith("/down/status_request"):
            await self._handle_sber_status_request(payload)
        elif topic.endswith("/down/config_request"):
            await self._handle_sber_config_request()
        elif topic.endswith("/down/errors"):
            self._handle_sber_error(payload)
        elif topic.endswith("/down/change_group_device_request"):
            await self._handle_change_group(payload)
        elif topic.endswith("/down/rename_device_request"):
            await self._handle_rename_device(payload)
        elif topic == SBER_GLOBAL_CONFIG_TOPIC:
            self._handle_global_config(payload)
        else:
            _LOGGER.debug("Unhandled MQTT topic suffix: %s", suffix)

    async def _handle_sber_command(self, payload: bytes) -> None:
        """Handle command from Sber cloud → execute HA service."""
        data = parse_sber_command(payload)
        self._stats.commands_received += 1

        devices = data.get("devices", {})
        _LOGGER.debug(
            "Sber command for %d device(s): %s",
            len(devices), list(devices.keys()),
        )

        for entity_id, cmd_data in devices.items():
            # Track Sber acknowledgment
            self._stats.acknowledged_entities.add(entity_id)

            entity = self._entities.get(entity_id)
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
                        await self._publish_states([entity_id])
                    continue

                try:
                    await self._hass.services.async_call(
                        domain=cmd["domain"],
                        service=cmd["service"],
                        service_data=cmd.get("service_data", {}),
                        target=cmd.get("target", {}),
                        blocking=False,
                    )
                    _LOGGER.debug(
                        "HA service called: %s.%s → %s",
                        cmd["domain"], cmd["service"],
                        cmd.get("target", {}).get("entity_id", "?"),
                    )
                except Exception:
                    _LOGGER.exception("Error calling HA service for %s", entity_id)

    async def _handle_sber_status_request(self, payload: bytes) -> None:
        """Handle status request from Sber cloud."""
        requested_ids = parse_sber_status_request(payload)
        self._stats.status_requests += 1

        # Track Sber acknowledgment for requested entities
        if requested_ids:
            for eid in requested_ids:
                self._stats.acknowledged_entities.add(eid)
            _LOGGER.info(
                "Sber status request for %d specific entities: %s",
                len(requested_ids), requested_ids,
            )
        else:
            # All entities requested — mark all as acknowledged
            self._stats.acknowledged_entities.update(self._enabled_entity_ids)
            _LOGGER.info(
                "Sber status request for ALL entities (%d)",
                len(self._enabled_entity_ids),
            )

        await self._publish_states(requested_ids if requested_ids else None)

    async def _handle_sber_config_request(self) -> None:
        """Handle config request from Sber cloud — send device list."""
        self._stats.config_requests += 1
        _LOGGER.info(
            "Sber config request received (will publish %d entities)",
            len(self._enabled_entity_ids),
        )
        await self._publish_config()

    def _handle_sber_error(self, payload: bytes) -> None:
        """Handle error message from Sber cloud."""
        self._stats.errors_from_sber += 1
        try:
            error_data = json.loads(payload)
            _LOGGER.warning(
                "Sber error (#%d): %s",
                self._stats.errors_from_sber,
                json.dumps(error_data, ensure_ascii=False, indent=2),
            )
        except (json.JSONDecodeError, TypeError):
            _LOGGER.warning(
                "Sber error (#%d, raw): %s",
                self._stats.errors_from_sber,
                payload[:500] if isinstance(payload, (str, bytes)) else payload,
            )

    async def _handle_change_group(self, payload: bytes) -> None:
        """Handle device group/room change from Sber."""
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return

        # NOTE: Sber's "device_id" is the value we published as "id" in to_sber_state,
        # which is entity_id (e.g. "light.living_room"). The variable name is misleading
        # but matches the Sber protocol field name.
        entity_id = data.get("device_id")
        if entity_id:
            self._redefinitions[entity_id] = {
                "home": data.get("home"),
                "room": data.get("room"),
            }
            _LOGGER.info("Sber group change: %s → room=%s", entity_id, data.get("room"))
            await self._publish_config(entity_ids=[entity_id])

    async def _handle_rename_device(self, payload: bytes) -> None:
        """Handle device rename from Sber."""
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return

        # See _handle_change_group for device_id vs entity_id note.
        entity_id = data.get("device_id")
        new_name = data.get("new_name")
        if entity_id and new_name:
            redef = self._redefinitions.setdefault(entity_id, {})
            redef["name"] = new_name
            _LOGGER.info("Sber rename: %s → %s", entity_id, new_name)
            await self._publish_config(entity_ids=[entity_id])

    def _handle_global_config(self, payload: bytes) -> None:
        """Handle global config from Sber (http_api_endpoint)."""
        try:
            data = json.loads(payload)
            endpoint = data.get("http_api_endpoint", "")
            if endpoint:
                _LOGGER.info("Sber HTTP API endpoint: %s", endpoint)
        except json.JSONDecodeError:
            pass

    @callback
    def _on_ha_state_changed(self, event: Event) -> None:
        """Handle HA state change → publish to Sber."""
        entity_id = event.data["entity_id"]
        new_state = event.data.get("new_state")
        if new_state is None:
            return

        entity = self._entities.get(entity_id)
        if entity is None:
            return

        ha_state_dict = {
            "entity_id": new_state.entity_id,
            "state": new_state.state,
            "attributes": dict(new_state.attributes),
        }

        try:
            entity.process_state_change(event.data.get("old_state"), ha_state_dict)
        except Exception:
            _LOGGER.exception("Error processing state change for %s", entity_id)
            return

        _LOGGER.debug("HA → Sber state: %s = %s", entity_id, new_state.state)
        self._schedule_debounced_publish(entity_id)

    @callback
    def _schedule_debounced_publish(self, entity_id: str) -> None:
        """Schedule a debounced state publish, coalescing rapid changes.

        Multiple state changes within 100ms are batched into a single
        MQTT publish to avoid flooding the broker during sensor bursts.
        """
        self._pending_publish_ids.add(entity_id)
        if self._publish_timer is not None:
            self._publish_timer.cancel()
        loop = self._hass.loop
        self._publish_timer = loop.call_later(0.1, self._fire_debounced_publish)

    @callback
    def _fire_debounced_publish(self) -> None:
        """Fire the debounced publish task with accumulated entity IDs."""
        self._publish_timer = None
        ids = list(self._pending_publish_ids)
        self._pending_publish_ids.clear()
        if ids:
            self._hass.async_create_task(self._publish_states(ids))

    async def _publish_states(self, entity_ids: list[str] | None = None) -> None:
        """Publish entity states to Sber MQTT."""
        if not self._connected or self._mqtt_client is None:
            return

        payload = build_states_list_json(self._entities, entity_ids, self._enabled_entity_ids)
        try:
            await self._mqtt_client.publish(f"{self._root_topic}/up/status", payload)
            self._stats.messages_sent += 1
        except aiomqtt.MqttError:
            self._stats.publish_errors += 1
            _LOGGER.exception("Error publishing states to Sber")

    async def _publish_config(self, entity_ids: list[str] | None = None) -> None:
        """Publish device config to Sber MQTT."""
        if not self._connected or self._mqtt_client is None:
            return

        ids_to_publish = entity_ids or self._enabled_entity_ids
        payload = build_devices_list_json(self._entities, ids_to_publish, self._redefinitions)
        try:
            await self._mqtt_client.publish(f"{self._root_topic}/up/config", payload)
            self._stats.messages_sent += 1
            self._last_config_publish_time = time.monotonic()
            _LOGGER.info(
                "Published device config to Sber (%d entities): %s",
                len(ids_to_publish),
                ", ".join(ids_to_publish),
            )

            # Log unacknowledged entities for debugging
            unack = self.unacknowledged_entities
            if unack:
                _LOGGER.debug(
                    "Entities not yet acknowledged by Sber (%d): %s",
                    len(unack), ", ".join(unack),
                )
        except aiomqtt.MqttError:
            self._stats.publish_errors += 1
            _LOGGER.exception("Error publishing config to Sber")
