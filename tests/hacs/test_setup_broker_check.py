"""The broker is checked during config entry setup (HA rule ``test-before-setup``).

``async_setup_entry`` makes one bounded connection attempt before the
bridge loads anything:

- a refused login or password fails the setup with ``ConfigEntryAuthFailed``
  (HA opens the reauth flow);
- an unreachable or silent broker fails it with ``ConfigEntryNotReady``
  (HA retries with backoff — also when HA starts without network);
- a successful attempt is not thrown away: the bridge runs on that session.

A failed setup must leave nothing running: no bridge tasks, no HA
listeners, no open MQTT session, no single-entry claim.

Only ``aiomqtt.Client`` is faked; HA's config entry machinery, the bridge
and the transport run for real.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from typing import Any

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState, HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry
from test_bridge_lifecycle import FakeMqttClient, _bad_credentials, _make_entry, _reauth_flows, _wait_until

from custom_components.sber_mqtt_bridge import ACTIVE_ENTRY_KEY
from custom_components.sber_mqtt_bridge import sber_bridge as sber_bridge_module
from custom_components.sber_mqtt_bridge.const import DOMAIN
from custom_components.sber_mqtt_bridge.sber_bridge import SberBridge


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: Any) -> None:
    """Let HA load ``custom_components/sber_mqtt_bridge`` in every test."""
    return


@pytest.fixture
async def ha(hass: HomeAssistant) -> AsyncGenerator[HomeAssistant]:
    """HA with the frontend (the panel needs it); loaded entries are unloaded afterwards."""
    assert await async_setup_component(hass, "frontend", {})
    yield hass
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is ConfigEntryState.LOADED:
            await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


def _exposing_entry(hass: HomeAssistant) -> MockConfigEntry:
    """Entry exposing one switch, so a started bridge would track its state."""
    er.async_get(hass).async_get_or_create("switch", "test", "lamp-uid", suggested_object_id="lamp")
    hass.states.async_set("switch.lamp", "on")
    return _make_entry(hass, options={"exposed_entities": ["switch.lamp"]})


class _ClientFactory:
    """Stands in for ``aiomqtt.Client``: one shared fake, constructions counted."""

    def __init__(self, fake: FakeMqttClient) -> None:
        self.fake = fake
        self.constructed = 0

    def __call__(self, *args: Any, **kwargs: Any) -> FakeMqttClient:
        self.constructed += 1
        return self.fake


def _install(monkeypatch: pytest.MonkeyPatch, fake: FakeMqttClient) -> _ClientFactory:
    factory = _ClientFactory(fake)
    monkeypatch.setattr("custom_components.sber_mqtt_bridge.mqtt_client_service.aiomqtt.Client", factory)
    return factory


def _bridge_tasks() -> list[asyncio.Task]:
    """Live tasks run by the bridge or its transport."""
    return [
        task
        for task in asyncio.all_tasks()
        if not task.done()
        and (
            task.get_name().startswith(("sber", "mqtt"))
            or getattr(task.get_coro(), "__qualname__", "").startswith(("SberBridge", "MqttClientService"))
        )
    ]


def _listener_counts(hass: HomeAssistant) -> dict[str, int]:
    """HA bus listeners by event type.

    ``homeassistant_final_write`` is left out: HA's own registries (config
    entries, issues) register one per delayed save when the setup outcome
    is recorded, which says nothing about the bridge.
    """
    counts = dict(hass.bus.async_listeners())
    counts.pop("homeassistant_final_write", None)
    return counts


def _assert_nothing_left(hass: HomeAssistant, listeners_before: dict[str, int], fake: FakeMqttClient) -> None:
    """No bridge task, no new HA listener, no open session, no single-entry claim."""
    assert _bridge_tasks() == []
    assert _listener_counts(hass) == listeners_before
    assert fake.exit_count == max(fake.connect_count - fake.fail_connects, 0), "every opened session is closed"
    assert ACTIVE_ENTRY_KEY not in hass.data.get(DOMAIN, {})


async def test_refused_credentials_fail_setup_with_auth_failed(
    ha: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A negative CONNACK for the password: reauth, no retry, nothing left behind."""
    entry = _exposing_entry(ha)
    fake = FakeMqttClient(fail_connects=10**9, connect_error=_bad_credentials())
    _install(monkeypatch, fake)
    listeners_before = _listener_counts(ha)

    assert not await ha.config_entries.async_setup(entry.entry_id)
    await ha.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert entry.error_reason_translation_key == "invalid_auth"
    assert len(_reauth_flows(ha, entry)) == 1
    assert fake.connect_count == 1
    _assert_nothing_left(ha, listeners_before, fake)


@pytest.mark.parametrize(
    "error",
    [
        pytest.param("[Errno 111] Connection refused", id="refused"),
        pytest.param("[Errno -3] Temporary failure in name resolution", id="dns"),
    ],
)
async def test_unreachable_broker_fails_setup_with_not_ready(
    ha: HomeAssistant, monkeypatch: pytest.MonkeyPatch, error: str
) -> None:
    """Broker or network down: HA retries the setup, no reauth, nothing left behind."""
    import aiomqtt

    entry = _exposing_entry(ha)
    fake = FakeMqttClient(fail_connects=10**9, connect_error=aiomqtt.MqttError(error))
    _install(monkeypatch, fake)
    listeners_before = _listener_counts(ha)

    assert not await ha.config_entries.async_setup(entry.entry_id)
    await ha.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert entry.error_reason_translation_key == "cannot_connect"
    assert _reauth_flows(ha, entry) == []
    assert fake.connect_count == 1
    _assert_nothing_left(ha, listeners_before, fake)


async def test_silent_broker_fails_setup_with_not_ready_after_timeout(
    ha: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No handshake in time: setup gives up quickly and the late session is closed."""
    monkeypatch.setattr(sber_bridge_module, "SETUP_CONNECT_TIMEOUT", 0.05)
    entry = _exposing_entry(ha)
    fake = FakeMqttClient()
    fake.connect_gate = asyncio.Event()
    _install(monkeypatch, fake)
    listeners_before = _listener_counts(ha)

    async with asyncio.timeout(2):
        assert not await ha.config_entries.async_setup(entry.entry_id)

    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert entry.error_reason_translation_key == "connect_timeout"

    # The broker answers after setup gave up: that session must not stay open.
    fake.connect_gate.set()
    await _wait_until(lambda: fake.exit_count == 1)
    await ha.async_block_till_done()
    _assert_nothing_left(ha, listeners_before, fake)
    assert fake.published == [], "an abandoned session must never publish"


async def test_successful_check_is_the_bridge_session(ha: HomeAssistant, monkeypatch: pytest.MonkeyPatch) -> None:
    """One connection for setup and runtime: the bridge handshakes on the checked session."""
    entry = _exposing_entry(ha)
    fake = FakeMqttClient()
    factory = _install(monkeypatch, fake)

    assert await ha.config_entries.async_setup(entry.entry_id)
    bridge: SberBridge = entry.runtime_data.bridge
    await _wait_until(lambda: bridge.is_connected and any(t.endswith("up/config") for t, _ in fake.published))

    assert entry.state is ConfigEntryState.LOADED
    assert factory.constructed == 1
    assert fake.connect_count == 1
    assert fake.exit_count == 0

    assert await ha.config_entries.async_unload(entry.entry_id)
    assert fake.exit_count == 1


async def test_start_failure_after_check_closes_the_session(ha: HomeAssistant, monkeypatch: pytest.MonkeyPatch) -> None:
    """A setup that fails after connecting does not leave the session open."""
    entry = _exposing_entry(ha)
    fake = FakeMqttClient()
    _install(monkeypatch, fake)

    async def _broken_start(self: SberBridge) -> None:
        raise RuntimeError("storage unavailable")

    monkeypatch.setattr(SberBridge, "async_start", _broken_start)

    assert not await ha.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert fake.connect_count == 1
    assert fake.exit_count == 1
    assert ACTIVE_ENTRY_KEY not in ha.data[DOMAIN]


async def test_ha_starting_without_network_retries_once_started(
    ha: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """HA booting offline: setup does not hang, and the entry loads once the broker is back."""
    import aiomqtt

    ha.set_state(CoreState.starting)
    entry: MockConfigEntry = _exposing_entry(ha)
    fake = FakeMqttClient(fail_connects=1, connect_error=aiomqtt.MqttError("[Errno 101] Network is unreachable"))
    _install(monkeypatch, fake)

    async with asyncio.timeout(2):
        assert not await ha.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY

    # HA retries a not-ready entry once startup completes.
    ha.set_state(CoreState.running)
    ha.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await _wait_until(lambda: entry.state is ConfigEntryState.LOADED)
    bridge: SberBridge = entry.runtime_data.bridge
    await _wait_until(lambda: bridge.is_connected)
    assert fake.connect_count == 2


async def test_tls_setup_error_fails_setup_with_not_ready(ha: HomeAssistant, monkeypatch: pytest.MonkeyPatch) -> None:
    """A TLS context that cannot be built (e.g. unreadable CA bundle) is retried, not fatal."""
    entry = _exposing_entry(ha)
    fake = FakeMqttClient()
    _install(monkeypatch, fake)

    def _broken_ssl(verify: bool = True) -> None:
        raise OSError("[Errno 2] No such file or directory: 'cacert.pem'")

    monkeypatch.setattr("custom_components.sber_mqtt_bridge.mqtt_client_service.create_ssl_context", _broken_ssl)

    assert not await ha.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert entry.error_reason_translation_key == "cannot_connect"
    assert fake.connect_count == 0
