"""Sber Smart Home MQTT Bridge - core bridge logic.

Manages:
- Async MQTT connection to Sber cloud broker (aiomqtt)
- HA state change listening and publishing to Sber
- Sber command reception and forwarding to HA services
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import Callable

import aiomqtt
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
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

        self._unsub_listeners: list[Callable] = []

    @property
    def is_connected(self) -> bool:
        """Return True if connected to Sber MQTT."""
        return self._connected

    async def async_start(self) -> None:
        """Start the bridge: load entities, connect MQTT, subscribe to HA events."""
        self._running = True
        self._load_exposed_entities()
        self._connection_task = asyncio.create_task(self._mqtt_connection_loop())

    async def async_stop(self) -> None:
        """Stop the bridge: disconnect MQTT, unsubscribe from HA events."""
        self._running = False

        for unsub in self._unsub_listeners:
            unsub()
        self._unsub_listeners.clear()

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
        new_enabled = list(
            self._entry.options.get(CONF_EXPOSED_ENTITIES, [])
        )
        new_entities: dict[str, BaseEntity] = {}

        entity_reg = er.async_get(self._hass)

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
            "Loaded %d Sber entities from %d exposed",
            len(self._entities),
            len(self._enabled_entity_ids),
        )

    def _subscribe_ha_events(self) -> None:
        """Subscribe to HA state changes for exposed entities."""
        for unsub in self._unsub_listeners:
            unsub()
        self._unsub_listeners.clear()

        if self._enabled_entity_ids:
            unsub = async_track_state_change_event(
                self._hass,
                self._enabled_entity_ids,
                self._on_ha_state_changed,
            )
            self._unsub_listeners.append(unsub)

    async def _mqtt_connection_loop(self) -> None:
        """Maintain persistent MQTT connection with exponential backoff reconnect."""
        ssl_context = create_ssl_context(verify=self._verify_ssl)

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
                    _LOGGER.info("Connected to Sber MQTT broker %s", self._broker)

                    await client.subscribe(f"{self._down_topic}/#")
                    await client.subscribe(SBER_GLOBAL_CONFIG_TOPIC)

                    self._subscribe_ha_events()

                    async for message in client.messages:
                        if not self._running:
                            break
                        await self._handle_mqtt_message(
                            str(message.topic), message.payload
                        )

            except aiomqtt.MqttError as err:
                self._connected = False
                if not self._running:
                    break
                _LOGGER.warning(
                    "Sber MQTT connection lost: %s. Reconnecting in %ds...",
                    err,
                    self._reconnect_interval,
                )
                await asyncio.sleep(self._reconnect_interval)
                self._reconnect_interval = min(
                    self._reconnect_interval * 2, RECONNECT_INTERVAL_MAX
                )
            except asyncio.CancelledError:
                break
            except Exception:
                self._connected = False
                if not self._running:
                    break
                _LOGGER.exception(
                    "Unexpected MQTT error. Reconnecting in %ds...",
                    self._reconnect_interval,
                )
                await asyncio.sleep(self._reconnect_interval)
                self._reconnect_interval = min(
                    self._reconnect_interval * 2, RECONNECT_INTERVAL_MAX
                )

        self._mqtt_client = None
        self._connected = False

    async def _handle_mqtt_message(self, topic: str, payload: bytes) -> None:
        """Route incoming MQTT messages to handlers."""
        _LOGGER.debug("MQTT message: %s", topic)

        if topic.endswith("/down/commands"):
            await self._handle_sber_command(payload)
        elif topic.endswith("/down/status_request"):
            await self._handle_sber_status_request(payload)
        elif topic.endswith("/down/config_request"):
            await self._handle_sber_config_request()
        elif topic.endswith("/down/errors"):
            _LOGGER.warning("Sber MQTT error: %s", payload)
        elif topic.endswith("/down/change_group_device_request"):
            await self._handle_change_group(payload)
        elif topic.endswith("/down/rename_device_request"):
            await self._handle_rename_device(payload)
        elif topic == SBER_GLOBAL_CONFIG_TOPIC:
            self._handle_global_config(payload)

    async def _handle_sber_command(self, payload: bytes) -> None:
        """Handle command from Sber cloud → execute HA service."""
        data = parse_sber_command(payload)
        _LOGGER.debug("Sber command payload: %s", data)

        for entity_id, cmd_data in data.get("devices", {}).items():
            entity = self._entities.get(entity_id)
            if entity is None:
                _LOGGER.warning("Unknown entity in Sber command: %s", entity_id)
                continue

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
                except Exception:
                    _LOGGER.exception(
                        "Error calling HA service for %s", entity_id
                    )

    async def _handle_sber_status_request(self, payload: bytes) -> None:
        """Handle status request from Sber cloud."""
        requested_ids = parse_sber_status_request(payload)
        await self._publish_states(requested_ids if requested_ids else None)

    async def _handle_sber_config_request(self) -> None:
        """Handle config request from Sber cloud — send device list."""
        await self._publish_config()

    async def _handle_change_group(self, payload: bytes) -> None:
        """Handle device group/room change from Sber."""
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return

        device_id = data.get("device_id")
        if device_id:
            self._redefinitions[device_id] = {
                "home": data.get("home"),
                "room": data.get("room"),
            }
            await self._publish_config(entity_ids=[device_id])

    async def _handle_rename_device(self, payload: bytes) -> None:
        """Handle device rename from Sber."""
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return

        device_id = data.get("device_id")
        new_name = data.get("new_name")
        if device_id and new_name:
            redef = self._redefinitions.setdefault(device_id, {})
            redef["name"] = new_name
            await self._publish_config(entity_ids=[device_id])

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
            entity.process_state_change(
                event.data.get("old_state"), ha_state_dict
            )
        except Exception:
            _LOGGER.exception("Error processing state change for %s", entity_id)
            return

        self._hass.async_create_task(self._publish_states([entity_id]))

    async def _publish_states(self, entity_ids: list[str] | None = None) -> None:
        """Publish entity states to Sber MQTT."""
        if not self._connected or self._mqtt_client is None:
            return

        payload = build_states_list_json(
            self._entities, entity_ids, self._enabled_entity_ids
        )
        try:
            await self._mqtt_client.publish(
                f"{self._root_topic}/up/status", payload
            )
        except aiomqtt.MqttError:
            _LOGGER.exception("Error publishing states to Sber")

    async def _publish_config(
        self, entity_ids: list[str] | None = None
    ) -> None:
        """Publish device config to Sber MQTT."""
        if not self._connected or self._mqtt_client is None:
            return

        ids_to_publish = entity_ids or self._enabled_entity_ids
        payload = build_devices_list_json(
            self._entities, ids_to_publish, self._redefinitions
        )
        try:
            await self._mqtt_client.publish(
                f"{self._root_topic}/up/config", payload
            )
            _LOGGER.info("Published device config to Sber (%d entities)", len(ids_to_publish))
        except aiomqtt.MqttError:
            _LOGGER.exception("Error publishing config to Sber")
