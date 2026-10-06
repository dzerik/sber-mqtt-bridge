"""The broker is checked before setup, but local management can start offline.

``async_setup_entry`` makes one bounded connection attempt before the
bridge loads anything:

- a refused login or password fails the setup with ``ConfigEntryAuthFailed``
  (HA opens the reauth flow);
- an unreachable or silent broker leaves a loaded, disconnected bridge
  with its recovery panel and background reconnect loop;
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
        pytest.param("[SSL: CERTIFICATE_VERIFY_FAILED] unable to get local issuer certificate", id="tls"),
    ],
)
async def test_unreachable_broker_keeps_local_panel_available(
    ha: HomeAssistant, monkeypatch: pytest.MonkeyPatch, error: str
) -> None:
    """A connection failure leaves recovery controls and saved devices available."""
    import aiomqtt

    entry = _exposing_entry(ha)
    fake = FakeMqttClient(fail_connects=10**9, connect_error=aiomqtt.MqttError(error))
    _install(monkeypatch, fake)
    assert await ha.config_entries.async_setup(entry.entry_id)
    await ha.async_block_till_done()

    from homeassistant.components.frontend import DATA_PANELS

    from custom_components.sber_mqtt_bridge.websocket_api._common import get_config_entry

    assert entry.state is ConfigEntryState.LOADED
    assert "sber-mqtt-bridge" in ha.data[DATA_PANELS]
    assert get_config_entry(ha) is entry
    assert entry.runtime_data.bridge.entities_count == 1
    assert not entry.runtime_data.bridge.is_connected
    expected_kind = "certificate" if "CERTIFICATE" in error else "network"
    assert entry.runtime_data.bridge.connection_error["kind"] == expected_kind
    assert fake.published == []
    assert _reauth_flows(ha, entry) == []
    assert fake.connect_count >= 1
    assert await ha.config_entries.async_unload(entry.entry_id)
    assert _bridge_tasks() == []
    assert ACTIVE_ENTRY_KEY not in ha.data[DOMAIN]


async def test_silent_broker_keeps_panel_after_timeout(ha: HomeAssistant, monkeypatch: pytest.MonkeyPatch) -> None:
    """No handshake in time: setup gives up quickly and the late session is closed."""
    monkeypatch.setattr(sber_bridge_module, "SETUP_CONNECT_TIMEOUT", 0.05)
    entry = _exposing_entry(ha)
    fake = FakeMqttClient()
    fake.connect_gate = asyncio.Event()
    _install(monkeypatch, fake)
    async with asyncio.timeout(2):
        assert await ha.config_entries.async_setup(entry.entry_id)

    from homeassistant.components.frontend import DATA_PANELS

    assert entry.state is ConfigEntryState.LOADED
    assert "sber-mqtt-bridge" in ha.data[DATA_PANELS]
    assert await ha.config_entries.async_unload(entry.entry_id)

    # The broker answers after setup gave up: that session must not stay open.
    fake.connect_gate.set()
    await _wait_until(lambda: fake.exit_count == 1)
    await ha.async_block_till_done()
    assert _bridge_tasks() == []
    assert ACTIVE_ENTRY_KEY not in ha.data[DOMAIN]
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
        assert await ha.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.LOADED

    # Local setup is already loaded; the bridge's own loop reconnects.
    ha.set_state(CoreState.running)
    ha.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await _wait_until(lambda: entry.state is ConfigEntryState.LOADED)
    bridge: SberBridge = entry.runtime_data.bridge
    await _wait_until(lambda: bridge.is_connected)
    assert fake.connect_count == 2
    assert bridge.connection_error is None


@pytest.mark.parametrize("surface", ["panel", "options"])
async def test_trusting_certificate_recovers_same_entry_from_offline_panel(ha, monkeypatch, surface) -> None:
    """Exercise setup → certificate review → trust → reconnect without deleting the entry."""
    from unittest.mock import MagicMock

    import aiomqtt
    from _ws_dispatch import dispatch

    from custom_components.sber_mqtt_bridge.ssl_utils import ServerCertificate
    from custom_components.sber_mqtt_bridge.websocket_api.settings import ws_inspect_certificate, ws_trust_certificate
    from custom_components.sber_mqtt_bridge.websocket_api.status import ws_get_status

    entry = _exposing_entry(ha)
    ha.config_entries.async_update_entry(entry, options={**entry.options, "reconnect_min": 300, "reconnect_max": 300})
    original_options = dict(entry.options)
    fake = FakeMqttClient(fail_connects=10**9, connect_error=aiomqtt.MqttError("CERTIFICATE_VERIFY_FAILED"))
    _install(monkeypatch, fake)
    contexts = []
    monkeypatch.setattr(
        "custom_components.sber_mqtt_bridge.mqtt_client_service.create_ssl_context",
        lambda *args: contexts.append(args) or object(),
    )
    certificate = ServerCertificate("PEM", "AA:BB", "subject", "issuer", "2026", "2028", False, True, True)
    monkeypatch.setattr(
        "custom_components.sber_mqtt_bridge.websocket_api.settings.inspect_server_certificate",
        lambda *args: certificate,
    )
    assert await ha.config_entries.async_setup(entry.entry_id)
    bridge = entry.runtime_data.bridge
    await _wait_until(lambda: fake.connect_count >= 2)
    connection = MagicMock()
    await dispatch(ws_get_status, ha, connection, {"id": 1})
    status = connection.send_result.call_args.args[1]
    assert status["connection_error"]["kind"] == "certificate"
    assert "test_pass" not in str(status["connection_error"])
    await dispatch(ws_inspect_certificate, ha, connection, {"id": 2})
    assert connection.send_result.call_args.args[1]["certificate"]["fingerprint"] == "AA:BB"
    fake.fail_connects = 0
    if surface == "panel":
        await dispatch(ws_trust_certificate, ha, connection, {"id": 3, "fingerprint": "AA:BB"})
    else:
        from test_config_flow_options import _open_advanced_step

        monkeypatch.setattr(
            "custom_components.sber_mqtt_bridge.config_flow.inspect_server_certificate", lambda *args: certificate
        )
        result = await _open_advanced_step(ha, entry, "broker_certificate")
        await ha.config_entries.options.async_configure(result["flow_id"], {"action": "trust", "confirm": True})
    await _wait_until(lambda: bridge.is_connected and bridge.connection_error is None)
    assert entry.runtime_data.bridge is bridge
    assert entry.options["sber_trusted_certificate"] == "PEM"
    assert entry.options["sber_verify_ssl"] is True
    assert all(entry.options[key] == value for key, value in original_options.items())
    assert contexts[-1] == (True, "PEM")
    assert bridge.entities_count == 1
    connects_before = fake.connect_count
    bridge.apply_settings({**entry.options, "debounce_delay": 0.5})
    await ha.async_block_till_done()
    assert fake.connect_count == connects_before, "unrelated settings must keep the session"
    await dispatch(ws_get_status, ha, connection, {"id": 4})
    assert connection.send_result.call_args.args[1]["connection_error"] is None


async def test_tls_setup_error_keeps_local_panel(ha: HomeAssistant, monkeypatch: pytest.MonkeyPatch) -> None:
    """A TLS context that cannot be built (e.g. unreadable CA bundle) is retried, not fatal."""
    entry = _exposing_entry(ha)
    fake = FakeMqttClient()
    _install(monkeypatch, fake)

    def _broken_ssl(verify: bool = True) -> None:
        raise OSError("[Errno 2] No such file or directory: 'cacert.pem'")

    monkeypatch.setattr("custom_components.sber_mqtt_bridge.mqtt_client_service.create_ssl_context", _broken_ssl)

    assert await ha.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.LOADED
    assert fake.connect_count == 0
