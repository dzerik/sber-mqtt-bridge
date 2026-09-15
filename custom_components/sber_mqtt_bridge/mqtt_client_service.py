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
import contextlib
import logging
import random
import ssl
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

import aiomqtt

from .ssl_utils import create_ssl_context

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

STABLE_SESSION_SECONDS = 60.0
"""Seconds a session must stay connected before the reconnect backoff resets.

A CONNACK alone does not prove the link is healthy: a session takeover by
another client with the same login, an ACL rejection or a broker-side kick
all accept the connection and drop it moments later.  Resetting the backoff
on CONNACK turned each of those into a reconnect every ``reconnect_min``
seconds forever; only a session that survives this long counts as recovery.
"""


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
        on_disconnected: Invoked after an MQTT / network error with the error
            and whether it was unexpected (not an ``aiomqtt.MqttError``);
            returns ``True`` to continue reconnect loop, ``False`` to stop.
            The service does not log these errors itself: the hook owns the
            logging, so each failure (and each traceback) is reported once.
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
        self._pending_session: tuple[contextlib.AsyncExitStack, aiomqtt.Client] | None = None
        """Session opened by :meth:`async_connect` that :meth:`run` has not taken over yet."""
        self._running = False
        self._stable_handle: asyncio.TimerHandle | None = None
        """Pending "session is stable" timer that resets the backoff; ``None`` when disarmed."""

    @property
    def client(self) -> aiomqtt.Client | None:
        """Return the current ``aiomqtt.Client`` or ``None`` when disconnected."""
        return self._client

    @property
    def queued_inbound_count(self) -> int:
        """Return how many received messages wait in the client's queue, not yet consumed.

        ``0`` without a live client.  The queue is FIFO and consumed only
        after ``hooks.on_connected`` returns, so the count taken during that
        hook names the oldest messages of the session.
        """
        client = self._client
        return len(client.messages) if client is not None else 0

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

        The new minimum takes effect on the next backoff reset (a session
        that stayed up for :data:`STABLE_SESSION_SECONDS`); the new maximum
        clamps subsequent backoff steps immediately.
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

    async def async_connect(self, connect_timeout: float) -> None:
        """Open the first session up front and keep it for :meth:`run`.

        Used by the integration setup to find out whether the broker can be
        reached with the configured credentials before the entry is
        considered loaded.  The connected client is not thrown away: the
        next :meth:`run` continues with it instead of connecting again, so a
        successful check costs exactly one connection.

        The attempt is bounded by ``connect_timeout``.  A connection that is still
        being established when the time is up (or when the caller is
        cancelled) is not interrupted — cancelling ``aiomqtt`` in the middle
        of its executor-side socket connect can leave a socket open behind
        it — but abandoned: it finishes on its own and, if it succeeds, is
        closed straight away.

        Args:
            connect_timeout: Seconds the whole attempt (SSL context included) may take.

        Raises:
            aiomqtt.MqttError: The broker refused the connection or could not
                be reached (use :func:`.mqtt_errors.is_auth_failure` to tell a
                refused login from a transient failure).
            TimeoutError: The broker did not complete the handshake in time.
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + connect_timeout
        async with asyncio.timeout_at(deadline):
            ssl_context = await self._hass.async_add_executor_job(create_ssl_context, self._credentials.verify_ssl)
        stack = contextlib.AsyncExitStack()
        attempt = self._hass.async_create_background_task(
            self._enter_session(stack, self._build_client(ssl_context)),
            "sber_mqtt_first_connect",
            eager_start=True,
        )
        try:
            done, _ = await asyncio.wait((attempt,), timeout=max(deadline - loop.time(), 0.0))
        except asyncio.CancelledError:
            self._abandon_attempt(attempt, stack)
            raise
        if not done:
            self._abandon_attempt(attempt, stack)
            raise TimeoutError(
                f"Sber MQTT broker {self._credentials.broker}:{self._credentials.port} "
                f"did not answer within {connect_timeout:g}s"
            )
        self._pending_session = (stack, attempt.result())

    @staticmethod
    async def _enter_session(stack: contextlib.AsyncExitStack, client: aiomqtt.Client) -> aiomqtt.Client:
        """Connect ``client`` under ``stack``, which then owns the disconnect."""
        await stack.enter_async_context(client)
        return client

    def _abandon_attempt(self, attempt: asyncio.Task[aiomqtt.Client], stack: contextlib.AsyncExitStack) -> None:
        """Let a connection attempt nobody waits for finish, then close what it opened."""

        def _on_done(task: asyncio.Task[aiomqtt.Client]) -> None:
            if task.cancelled() or task.exception() is not None:
                return
            self._hass.async_create_background_task(
                self._close_session(stack), "sber_mqtt_abandoned_connect_close", eager_start=True
            )

        attempt.add_done_callback(_on_done)

    @staticmethod
    async def _close_session(stack: contextlib.AsyncExitStack) -> None:
        """Disconnect a session no loop runs on; a failing disconnect is not an error."""
        try:
            await stack.aclose()
        except aiomqtt.MqttError:  # the session is being discarded either way
            _LOGGER.debug("Closing an unused Sber MQTT session failed", exc_info=True)

    @contextlib.asynccontextmanager
    async def _session(self) -> AsyncIterator[aiomqtt.Client]:
        """Yield a connected client: the session from :meth:`async_connect` or a new one.

        The SSL context of a new session is rebuilt on every attempt so a
        runtime ``verify_ssl`` change (:meth:`update_verify_ssl`) takes
        effect on the next reconnect.
        """
        pending, self._pending_session = self._pending_session, None
        if pending is not None:
            stack, client = pending
            async with stack:
                yield client
            return
        ssl_context = await self._hass.async_add_executor_job(create_ssl_context, self._credentials.verify_ssl)
        async with self._build_client(ssl_context) as client:
            yield client

    async def run(self) -> None:
        """Maintain a persistent MQTT connection until ``stop()`` is called.

        On successful handshake, invokes ``hooks.on_connected(client)`` and
        then blocks on the inbound message stream, delegating each message
        to ``hooks.on_message``.  On error, invokes ``hooks.on_disconnected``
        and applies exponential backoff before retrying.

        The backoff is reset only once a session has stayed connected for
        :data:`STABLE_SESSION_SECONDS` (see :meth:`_arm_stable_timer`), not on
        CONNACK: a broker that accepts the connection and drops it straight
        away must see the delay grow to ``reconnect_max`` like any other
        failure.

        The first iteration continues the session opened by
        :meth:`async_connect`, if any (see :meth:`_session`).  Any
        non-cancellation exception is treated as a recoverable connection
        failure: the loop never dies silently.  Errors are reported through
        ``hooks.on_disconnected`` only, which logs them.
        """
        self._running = True
        try:
            while self._running:
                try:
                    async with self._session() as client:
                        self._client = client
                        self._connected = True
                        self._arm_stable_timer()
                        try:
                            await self._hooks.on_connected(client)
                            await self._consume_messages(client)
                        finally:
                            # Disarm before ``__aexit__`` awaits the socket
                            # teardown: a session that has already ended must
                            # not be credited as stable.
                            self._cancel_stable_timer()
                except aiomqtt.MqttError as err:
                    if not await self._after_error(err, unexpected=False):
                        break
                except asyncio.CancelledError:
                    break
                except Exception as err:  # noqa: BLE001 — last-resort barrier, logged by the hook
                    # Not logged here: the on_disconnected hook reports it
                    # (with its traceback) — logging in both places printed
                    # every unexpected error twice.
                    if not await self._after_error(err, unexpected=True):
                        break
        finally:
            self._cancel_stable_timer()
            self._client = None
            self._connected = False

    def _arm_stable_timer(self) -> None:
        """Schedule the backoff reset for when the new session proves stable.

        Two ways to decide that a reconnect "worked" were considered: a
        fixed connected period and the first successful round-trip with the
        cloud.  The period is used because the transport can judge it on its
        own and it always resolves: a round-trip needs protocol knowledge
        this layer deliberately lacks, and whether the cloud answers at all
        depends on what the bridge exposes — a healthy link that draws no
        reply would keep the backoff at its maximum.  Takeover, ACL
        rejection and broker kicks all end a session within seconds, far
        below the threshold.

        Every path that ends the session (``_after_error``, leaving the
        ``async with`` block, the loop's ``finally``) disarms the timer, so
        it can only fire while the session it was armed for is still live.
        """
        self._cancel_stable_timer()
        self._stable_handle = asyncio.get_running_loop().call_later(STABLE_SESSION_SECONDS, self._on_session_stable)

    def _cancel_stable_timer(self) -> None:
        """Disarm the pending backoff reset (disconnect, stop or cancellation)."""
        if self._stable_handle is not None:
            self._stable_handle.cancel()
            self._stable_handle = None

    def _on_session_stable(self) -> None:
        """Reset the backoff: the session outlived :data:`STABLE_SESSION_SECONDS`."""
        self._stable_handle = None
        if self._reconnect_interval != self._reconnect_min:
            _LOGGER.debug(
                "Sber MQTT session stable for %.0fs — reconnect backoff reset to %ds",
                STABLE_SESSION_SECONDS,
                self._reconnect_min,
            )
        self._reconnect_interval = self._reconnect_min

    async def stop(self) -> None:
        """Request the reconnect loop to exit at the next opportunity.

        Also closes the session opened by :meth:`async_connect` when
        :meth:`run` never took it over (setup failed after connecting).
        """
        self._running = False
        pending, self._pending_session = self._pending_session, None
        if pending is not None:
            await self._close_session(pending[0])

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
        """Forward every received message to ``hooks.on_message``.

        A failure while handling ONE message (malformed payload, a bug in
        a device handler, ...) must never kill the transport: the error is
        logged and the stream continues.  Cancellation always propagates.
        """
        async for message in client.messages:
            if not self._running:
                break
            topic = str(message.topic)
            try:
                await self._hooks.on_message(topic, message.payload)
            except asyncio.CancelledError:
                raise
            except Exception:  # one bad message must not kill the transport
                _LOGGER.exception(
                    "Error handling MQTT message on topic %s — message skipped, transport continues",
                    topic,
                )

    async def _after_error(self, err: Exception, *, unexpected: bool) -> bool:
        """Handle a transport error and compute the next reconnect delay.

        Invokes the bridge hook for stats / repairs, then sleeps for
        ``reconnect_interval`` (with a random ±50% jitter to avoid
        synchronized reconnect storms across installations) and doubles
        the base interval up to ``reconnect_max``.

        A failure inside the ``on_disconnected`` hook itself is contained:
        it is logged and treated as "keep reconnecting", because this method
        runs inside ``run()``'s ``except`` handlers where a raised exception
        would otherwise terminate the whole reconnect loop.  Cancellation
        always propagates.

        Returns:
            ``True`` when the loop should keep running, ``False`` to stop.
        """
        self._cancel_stable_timer()
        self._client = None
        self._connected = False
        try:
            keep_running = await self._hooks.on_disconnected(err, unexpected)
        except asyncio.CancelledError:
            raise
        except Exception:  # hook bug must not kill the reconnect loop
            _LOGGER.exception("Error in on_disconnected hook — continuing reconnect loop")
            keep_running = True
        if not keep_running or not self._running:
            return False
        jitter = random.uniform(0.5, 1.5)  # noqa: S311 — not crypto, backoff desync only
        await asyncio.sleep(self._reconnect_interval * jitter)
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
