"""Async MQTT transport layer for the Sber Smart Home bridge.

Owns the persistent connection to the Sber MQTT broker, the reconnect
loop with exponential backoff, the topic subscriptions and the raw
publish operations.  Extracted from :class:`SberBridge` to isolate
transport concerns from bridge orchestration (SRP).

The service is driven by a ``SberMqttCredentials`` value object and a
``MqttServiceHooks`` struct of callbacks, so it does NOT know about
entities, commands or HA state.  All higher-level logic (initial
publish, ack-guard, message routing) is injected via hooks.
"""

from __future__ import annotations

import asyncio
import logging
import ssl
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

import aiomqtt

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SberMqttCredentials:
    """Connection credentials for the Sber MQTT broker."""

    login: str
    password: str
    broker: str
    port: int
    verify_ssl: bool


@dataclass(slots=True)
class MqttServiceHooks:
    """Callbacks invoked by :class:`MqttClientService`.

    Attributes:
        on_message: Invoked for every incoming MQTT message (topic, payload).
        on_connected: Invoked once per successful handshake; used by the
            bridge to perform initial publish + subscription setup.
        on_disconnected: Invoked after an MQTT / network error; returns
            ``True`` to continue reconnect loop, ``False`` to stop.
        get_connected_since: Stats hook — called when the connection is
            established so callers can tag the timestamp.
    """

    on_message: Callable[[str, bytes], Awaitable[None]]
    on_connected: Callable[[aiomqtt.Client], Awaitable[None]]
    on_disconnected: Callable[[Exception, bool], Awaitable[bool]]


class MqttClientService:
    """Async MQTT transport with exponential backoff reconnect.

    Typical usage (inside ``SberBridge.async_start``)::

        self._mqtt = MqttClientService(
            hass=hass,
            credentials=SberMqttCredentials(...),
            hooks=MqttServiceHooks(
                on_message=self._handle_mqtt_message,
                on_connected=self._handle_connected,
                on_disconnected=self._handle_disconnect,
            ),
            reconnect_min=reconnect_min,
            reconnect_max=reconnect_max,
        )
        self._connection_task = hass.async_create_task(
            self._mqtt.run(), eager_start=True,
        )
    """

    def __init__(
        self,
        *,
        hass: HomeAssistant,
        credentials: SberMqttCredentials,
        hooks: MqttServiceHooks,
        reconnect_min: int,
        reconnect_max: int,
    ) -> None:
        """Initialize the service.

        Args:
            hass: Home Assistant core instance (used for executor offload).
            credentials: Broker connection credentials.
            hooks: Higher-level callbacks injected by the bridge.
            reconnect_min: Initial reconnect backoff in seconds.
            reconnect_max: Upper bound for exponential backoff in seconds.
        """
        self._hass = hass
        self._credentials = credentials
        self._hooks = hooks
        self._reconnect_min = reconnect_min
        self._reconnect_max = reconnect_max
        self._reconnect_interval = reconnect_min

        self._client: aiomqtt.Client | None = None
        self._connected = False
        self._running = False

    @property
    def client(self) -> aiomqtt.Client | None:
        """Return the current ``aiomqtt.Client`` or ``None`` when disconnected."""
        return self._client

    @property
    def is_connected(self) -> bool:
        """Return True while a live session is active."""
        return self._connected

    @property
    def reconnect_interval(self) -> int:
        """Return the current exponential-backoff delay (read-only)."""
        return self._reconnect_interval

    def update_backoff_limits(self, reconnect_min: int, reconnect_max: int) -> None:
        """Update exponential-backoff bounds at runtime.

        The new minimum takes effect on the next connect; the new
        maximum clamps subsequent backoff steps immediately.
        """
        self._reconnect_min = reconnect_min
        self._reconnect_max = reconnect_max

    def update_verify_ssl(self, verify_ssl: bool) -> None:
        """Update the ``verify_ssl`` flag for the next reconnect."""
        self._credentials = SberMqttCredentials(
            login=self._credentials.login,
            password=self._credentials.password,
            broker=self._credentials.broker,
            port=self._credentials.port,
            verify_ssl=verify_ssl,
        )

    async def run(self) -> None:
        """Maintain a persistent MQTT connection until ``stop()`` is called.

        On successful handshake, invokes ``hooks.on_connected(client)`` and
        then blocks on the inbound message stream, delegating each message
        to ``hooks.on_message``.  On error, invokes ``hooks.on_disconnected``
        and applies exponential backoff before retrying.
        """
        from .config_flow import create_ssl_context

        self._running = True
        ssl_context = await self._hass.async_add_executor_job(create_ssl_context, self._credentials.verify_ssl)
        while self._running:
            try:
                async with self._build_client(ssl_context) as client:
                    self._client = client
                    self._connected = True
                    self._reconnect_interval = self._reconnect_min
                    await self._hooks.on_connected(client)
                    await self._consume_messages(client)
            except aiomqtt.MqttError as err:
                if not await self._after_error(err, unexpected=False):
                    break
            except asyncio.CancelledError:
                break
            except (OSError, ValueError, RuntimeError) as err:
                if not await self._after_error(err, unexpected=True):
                    break

        self._client = None
        self._connected = False

    async def stop(self) -> None:
        """Request the reconnect loop to exit at the next opportunity."""
        self._running = False

    def _build_client(self, ssl_context: ssl.SSLContext) -> aiomqtt.Client:
        """Construct a fresh ``aiomqtt.Client`` configured for Sber broker."""
        return aiomqtt.Client(
            hostname=self._credentials.broker,
            port=self._credentials.port,
            username=self._credentials.login,
            password=self._credentials.password,
            tls_context=ssl_context,
        )

    async def _consume_messages(self, client: aiomqtt.Client) -> None:
        """Forward every received message to ``hooks.on_message``."""
        async for message in client.messages:
            if not self._running:
                break
            await self._hooks.on_message(str(message.topic), message.payload)

    async def _after_error(self, err: Exception, *, unexpected: bool) -> bool:
        """Handle a transport error and compute the next reconnect delay.

        Invokes the bridge hook for stats / repairs, then sleeps for
        ``reconnect_interval`` and doubles it up to ``reconnect_max``.

        Returns:
            ``True`` when the loop should keep running, ``False`` to stop.
        """
        self._client = None
        self._connected = False
        keep_running = await self._hooks.on_disconnected(err, unexpected)
        if not keep_running or not self._running:
            return False
        await asyncio.sleep(self._reconnect_interval)
        self._reconnect_interval = min(self._reconnect_interval * 2, self._reconnect_max)
        return True

    async def publish(self, topic: str, payload: str | bytes) -> None:
        """Publish a raw payload to the given topic.

        Raises:
            RuntimeError: If called while disconnected.
            aiomqtt.MqttError: Propagated on transport errors.
        """
        client = self._client
        if not self._connected or client is None:
            raise RuntimeError("Not connected to MQTT")
        await client.publish(topic, payload)

    async def subscribe(self, topic_pattern: str) -> None:
        """Subscribe to a topic / topic pattern on the active session."""
        client = self._client
        if not self._connected or client is None:
            raise RuntimeError("Not connected to MQTT")
        await client.subscribe(topic_pattern)
