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
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import aiomqtt
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_state_change_event

from .config_flow import create_ssl_context
from .const import (
    CONF_ENTITY_LINKS,
    CONF_ENTITY_TYPE_OVERRIDES,
    CONF_EXPOSED_ENTITIES,
    CONF_SBER_BROKER,
    CONF_SBER_LOGIN,
    CONF_SBER_PASSWORD,
    CONF_SBER_PORT,
    CONF_SBER_VERIFY_SSL,
    SBER_GLOBAL_CONFIG_TOPIC,
    SBER_TOPIC_PREFIX,
)
from .custom_capabilities import get_custom_config
from .devices.base_entity import BaseEntity
from .repairs import check_and_create_issues
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
        self._verify_ssl: bool = entry.data.get(CONF_SBER_VERIFY_SSL, True)

        self._root_topic = f"{SBER_TOPIC_PREFIX}/{self._login}"
        self._down_topic = f"{self._root_topic}/down"

        self._entities: dict[str, BaseEntity] = {}
        self._enabled_entity_ids: list[str] = []
        self._redefinitions: dict[str, dict] = {}
        self._entity_links: dict[str, dict[str, str]] = {}
        """Primary entity → {role: linked_entity_id}."""
        self._linked_reverse: dict[str, tuple[str, str]] = {}
        """Linked entity_id → (primary_entity_id, role)."""

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

        # Ring buffer for MQTT message log (DevTools)
        self._message_log: deque[dict[str, Any]] = deque(maxlen=50)

    @property
    def is_connected(self) -> bool:
        """Return True if connected to Sber MQTT."""
        return self._connected

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

    @property
    def message_log(self) -> list[dict[str, Any]]:
        """Return a copy of the MQTT message log ring buffer."""
        return list(self._message_log)

    def clear_message_log(self) -> None:
        """Clear the MQTT message log."""
        self._message_log.clear()

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
            self._hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, self._on_homeassistant_started)
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

        Custom YAML config (``sber_type``, ``sber_name``, ``sber_room``) from
        ``configuration.yaml`` is applied after entity creation:
        - ``sber_type`` overrides Sber category (UI override takes precedence).
        - ``sber_name`` overrides entity display name.
        - ``sber_room`` is added to redefinitions.
        """
        # Deduplicate entity IDs while preserving order
        new_enabled = list(dict.fromkeys(self._entry.options.get(CONF_EXPOSED_ENTITIES, [])))
        type_overrides: dict[str, str] = self._entry.options.get(CONF_ENTITY_TYPE_OVERRIDES, {})
        new_entities: dict[str, BaseEntity] = {}

        # Restore persisted redefinitions from entry options
        saved_redefs: dict[str, dict] = self._entry.options.get("redefinitions", {})
        if saved_redefs:
            self._redefinitions.update(saved_redefs)
            _LOGGER.debug("Loaded %d persisted redefinitions from options", len(saved_redefs))

        # Load custom YAML config
        custom_config = get_custom_config(self._hass)

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

            # Determine sber_category: UI override > YAML override > auto-detect
            yaml_cfg = custom_config.get(entity_id)
            sber_category = type_overrides.get(entity_id)
            if sber_category is None and yaml_cfg is not None and yaml_cfg.sber_type is not None:
                sber_category = yaml_cfg.sber_type
                _LOGGER.debug("YAML sber_type override for %s: %s", entity_id, sber_category)

            sber_entity = create_sber_entity(
                entity_id,
                entity_data,
                sber_category=sber_category,
            )
            if sber_entity is not None:
                new_entities[entity_id] = sber_entity

                # Apply YAML name override
                if yaml_cfg is not None and yaml_cfg.sber_name is not None:
                    sber_entity.name = yaml_cfg.sber_name
                    _LOGGER.debug("YAML sber_name override for %s: %s", entity_id, yaml_cfg.sber_name)

                # Apply YAML nicknames, groups, parent_id, partner_meta
                if yaml_cfg is not None:
                    if yaml_cfg.sber_nicknames is not None:
                        sber_entity.nicknames = yaml_cfg.sber_nicknames
                    if yaml_cfg.sber_groups is not None:
                        sber_entity.groups = yaml_cfg.sber_groups
                    if yaml_cfg.sber_parent_id is not None:
                        sber_entity.parent_entity_id = yaml_cfg.sber_parent_id
                    if yaml_cfg.sber_partner_meta is not None:
                        sber_entity.partner_meta = yaml_cfg.sber_partner_meta
                    if yaml_cfg.sber_features_add is not None:
                        sber_entity.extra_features = yaml_cfg.sber_features_add
                        _LOGGER.debug("YAML sber_features_add for %s: %s", entity_id, yaml_cfg.sber_features_add)
                    if yaml_cfg.sber_features_remove is not None:
                        sber_entity.removed_features = yaml_cfg.sber_features_remove
                        _LOGGER.debug("YAML sber_features_remove for %s: %s", entity_id, yaml_cfg.sber_features_remove)

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
                            _LOGGER.warning("Device ID mismatch for %s", entity_id)

                state = self._hass.states.get(entity_id)
                if state is not None:
                    ha_state_dict = {
                        "entity_id": state.entity_id,
                        "state": state.state,
                        "attributes": dict(state.attributes),
                    }
                    sber_entity.fill_by_ha_state(ha_state_dict)

        # Load and apply entity links
        raw_links: dict[str, dict[str, str]] = self._entry.options.get(CONF_ENTITY_LINKS, {})
        new_links: dict[str, dict[str, str]] = {}
        new_reverse: dict[str, tuple[str, str]] = {}
        for primary_id, roles in raw_links.items():
            if primary_id not in new_entities:
                continue
            primary_entity = new_entities[primary_id]
            valid_roles: dict[str, str] = {}
            for role, linked_id in roles.items():
                linked_state = self._hass.states.get(linked_id)
                if linked_state is None:
                    _LOGGER.warning("Linked entity %s (role=%s) for %s not found", linked_id, role, primary_id)
                    continue
                if hasattr(primary_entity, "update_linked_data"):
                    ha_state_dict = {
                        "entity_id": linked_state.entity_id,
                        "state": linked_state.state,
                        "attributes": dict(linked_state.attributes),
                    }
                    primary_entity.update_linked_data(role, ha_state_dict)
                    primary_entity._linked_entities[role] = linked_id
                valid_roles[role] = linked_id
                new_reverse[linked_id] = (primary_id, role)
            if valid_roles:
                new_links[primary_id] = valid_roles
                _LOGGER.info("Entity links for %s: %s", primary_id, valid_roles)

        self._entity_links = new_links
        self._linked_reverse = new_reverse

        # Warn about multiple entities sharing the same physical device (exclude linked)
        linked_ids = set(new_reverse.keys())
        device_entities: dict[str, list[str]] = {}
        for eid, ent in new_entities.items():
            if eid in linked_ids:
                continue
            did = getattr(ent, "device_id", None)
            if did:
                device_entities.setdefault(did, []).append(eid)
        for did, eids in device_entities.items():
            if len(eids) > 1:
                _LOGGER.warning(
                    "Device %s has %d entities in Sber (may cause duplicates): %s",
                    did,
                    len(eids),
                    ", ".join(eids),
                )

        # Atomic swap — readers see either old or new, never partial state
        self._entities = new_entities
        self._enabled_entity_ids = list(new_entities.keys())

        # Apply YAML room overrides to redefinitions
        new_redefinitions: dict[str, dict[str, str]] = {}
        for entity_id in self._enabled_entity_ids:
            yaml_cfg = custom_config.get(entity_id)
            if yaml_cfg is not None and yaml_cfg.sber_room is not None:
                new_redefinitions[entity_id] = {"room": yaml_cfg.sber_room}
                _LOGGER.debug("YAML sber_room override for %s: %s", entity_id, yaml_cfg.sber_room)

        # Merge YAML room overrides into existing redefinitions (runtime overrides take precedence)
        for eid, redef in new_redefinitions.items():
            if eid not in self._redefinitions:
                self._redefinitions[eid] = redef
            else:
                # Only set room from YAML if not already set by Sber cloud
                if "room" not in self._redefinitions[eid]:
                    self._redefinitions[eid]["room"] = redef["room"]

        # Prune stale data from previous entity sets
        valid_ids = set(new_enabled)
        self._stats.acknowledged_entities &= valid_ids
        self._redefinitions = {k: v for k, v in self._redefinitions.items() if k in valid_ids}

        _LOGGER.info(
            "Loaded %d Sber entities from %d exposed: %s",
            len(self._entities),
            len(self._enabled_entity_ids),
            ", ".join(self._enabled_entity_ids) if self._enabled_entity_ids else "(none)",
        )

        # Check for HA repair issues after entity loading
        self._hass.async_create_task(check_and_create_issues(self._hass, self))

    def _subscribe_ha_events(self) -> None:
        """Subscribe to HA state changes for exposed entities.

        Only manages state-change listeners (not lifecycle listeners like
        EVENT_HOMEASSISTANT_STARTED, which are tracked separately).
        """
        for unsub in self._unsub_state_listeners:
            unsub()
        self._unsub_state_listeners.clear()

        # Subscribe to both primary entities and linked entities
        all_tracked = list(self._enabled_entity_ids)
        for linked_id in self._linked_reverse:
            if linked_id not in all_tracked:
                all_tracked.append(linked_id)

        if all_tracked:
            unsub = async_track_state_change_event(
                self._hass,
                all_tracked,
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
        ssl_context = await self._hass.async_add_executor_job(create_ssl_context, self._verify_ssl)

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
                        self._broker,
                        self._port,
                        len(self._entities),
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
                    err,
                    self._reconnect_interval,
                    self._stats.reconnect_count,
                )
                await check_and_create_issues(self._hass, self)
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
        _LOGGER.debug("MQTT <- %s (%d bytes)", topic, len(payload) if payload else 0)

        # DevTools: log incoming message
        self._message_log.append(
            {
                "time": time.time(),
                "direction": "in",
                "topic": topic,
                "payload": payload[:500].decode("utf-8", errors="replace")
                if isinstance(payload, bytes)
                else str(payload)[:500],
            }
        )

        # Payload size guard (M2)
        if payload and len(payload) > MAX_MQTT_PAYLOAD_SIZE:
            _LOGGER.warning(
                "MQTT payload too large (%d bytes, max %d), dropping: %s",
                len(payload),
                MAX_MQTT_PAYLOAD_SIZE,
                topic,
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
            len(devices),
            list(devices.keys()),
        )

        update_state_ids: list[str] = []

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
                        update_state_ids.append(entity_id)
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
                        cmd["domain"],
                        cmd["service"],
                        cmd.get("target", {}).get("entity_id", "?"),
                    )
                except Exception:
                    _LOGGER.exception("Error calling HA service for %s", entity_id)

        # Batch publish state updates (e.g. light_mode) in a single call
        if update_state_ids:
            await self._publish_states(update_state_ids)

    async def _handle_sber_status_request(self, payload: bytes) -> None:
        """Handle status request from Sber cloud.

        If Sber asks about entities not in our current set, automatically
        re-publishes the device config so Sber is aware of the correct list.
        """
        requested_ids = parse_sber_status_request(payload)
        self._stats.status_requests += 1

        # Auto re-publish config if Sber asks about unknown entities
        if requested_ids:
            unknown = [eid for eid in requested_ids if eid not in self._entities and eid != "root"]
            if unknown:
                _LOGGER.info(
                    "Sber asked about unknown entities, re-publishing config: %s",
                    unknown,
                )
                await self._publish_config()

        # Track Sber acknowledgment for requested entities
        if requested_ids:
            for eid in requested_ids:
                self._stats.acknowledged_entities.add(eid)
            _LOGGER.info(
                "Sber status request for %d specific entities: %s",
                len(requested_ids),
                requested_ids,
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
        """Handle device group/room change from Sber.

        Only stores the redefinition locally. Does NOT re-publish config
        to avoid an infinite loop: Sber sends change_group → we publish
        config → Sber sends change_group again → loop forever.
        The updated room/home will be included in the next config_request.
        """
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return

        # NOTE: Sber's "device_id" is the value we published as "id" in to_sber_state,
        # which is entity_id (e.g. "light.living_room").
        entity_id = data.get("device_id")
        if entity_id:
            self._redefinitions[entity_id] = {
                "home": data.get("home"),
                "room": data.get("room"),
            }
            self._persist_redefinitions()
            _LOGGER.info("Sber group change stored: %s → room=%s", entity_id, data.get("room"))

    async def _handle_rename_device(self, payload: bytes) -> None:
        """Handle device rename from Sber.

        Only stores the redefinition locally. Does NOT re-publish config
        to avoid potential loops. The updated name will be included in
        the next config_request from Sber.
        """
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return

        entity_id = data.get("device_id")
        new_name = data.get("new_name")
        if entity_id and new_name:
            redef = self._redefinitions.setdefault(entity_id, {})
            redef["name"] = new_name
            self._persist_redefinitions()
            _LOGGER.info("Sber rename stored: %s → %s", entity_id, new_name)

    @callback
    def _persist_redefinitions(self) -> None:
        """Save redefinitions to config entry options for persistence across restarts."""
        new_options = {**self._entry.options, "redefinitions": self._redefinitions}
        self._hass.config_entries.async_update_entry(self._entry, options=new_options)

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
        """Handle HA state change → publish to Sber.

        Also handles linked entity state changes by forwarding data
        to the primary entity and scheduling publish for the primary.
        """
        entity_id = event.data["entity_id"]
        new_state = event.data.get("new_state")
        if new_state is None:
            return

        ha_state_dict = {
            "entity_id": new_state.entity_id,
            "state": new_state.state,
            "attributes": dict(new_state.attributes),
        }

        # Check if this is a linked entity → forward to primary
        if entity_id in self._linked_reverse:
            primary_id, role = self._linked_reverse[entity_id]
            primary_entity = self._entities.get(primary_id)
            if primary_entity is not None and hasattr(primary_entity, "update_linked_data"):
                features_before = primary_entity.get_final_features_list()
                primary_entity.update_linked_data(role, ha_state_dict)
                features_after = primary_entity.get_final_features_list()
                _LOGGER.debug("Linked %s (%s) → primary %s", entity_id, role, primary_id)
                if features_before != features_after:
                    _LOGGER.info("Features changed for %s after linked update — republishing config", primary_id)
                    self._hass.async_create_task(self._publish_config())
                self._schedule_debounced_publish(primary_id)
            return

        entity = self._entities.get(entity_id)
        if entity is None:
            return

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

    async def async_publish_entity_status(self, entity_id: str) -> None:
        """Publish the current state of a single entity to Sber cloud.

        Args:
            entity_id: HA entity identifier.
        """
        await self._publish_states([entity_id])

    async def async_republish(self) -> None:
        """Force republish full device config to Sber cloud."""
        await self._publish_config()

    async def _publish_states(self, entity_ids: list[str] | None = None) -> None:
        """Publish entity states to Sber MQTT."""
        if not self._connected or self._mqtt_client is None:
            return

        payload = build_states_list_json(self._entities, entity_ids, self._enabled_entity_ids)
        topic = f"{self._root_topic}/up/status"
        try:
            await self._mqtt_client.publish(topic, payload)
            self._stats.messages_sent += 1
            # DevTools: log outgoing message
            self._message_log.append(
                {
                    "time": time.time(),
                    "direction": "out",
                    "topic": topic,
                    "payload": payload[:500] if isinstance(payload, str) else "",
                }
            )
        except aiomqtt.MqttError:
            self._stats.publish_errors += 1
            _LOGGER.exception("Error publishing states to Sber")
        except (AttributeError, TypeError):
            # TOCTOU: _mqtt_client may become None between the check and publish()
            self._stats.publish_errors += 1

    async def _publish_config(self, entity_ids: list[str] | None = None) -> None:
        """Publish device config to Sber MQTT."""
        if not self._connected or self._mqtt_client is None:
            return

        ids_to_publish = entity_ids or self._enabled_entity_ids
        payload = build_devices_list_json(self._entities, ids_to_publish, self._redefinitions)
        topic = f"{self._root_topic}/up/config"
        try:
            await self._mqtt_client.publish(topic, payload)
            self._stats.messages_sent += 1
            self._last_config_publish_time = time.monotonic()
            _LOGGER.info(
                "Published device config to Sber (%d entities): %s",
                len(ids_to_publish),
                ", ".join(ids_to_publish),
            )
            # DevTools: log outgoing message
            self._message_log.append(
                {
                    "time": time.time(),
                    "direction": "out",
                    "topic": topic,
                    "payload": payload[:500] if isinstance(payload, str) else "",
                }
            )

            # Log unacknowledged entities for debugging
            unack = self.unacknowledged_entities
            if unack:
                _LOGGER.debug(
                    "Entities not yet acknowledged by Sber (%d): %s",
                    len(unack),
                    ", ".join(unack),
                )
        except aiomqtt.MqttError:
            self._stats.publish_errors += 1
            _LOGGER.exception("Error publishing config to Sber")
        except (AttributeError, TypeError):
            self._stats.publish_errors += 1
