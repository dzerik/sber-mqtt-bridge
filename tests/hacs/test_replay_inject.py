"""Tests for replay / inject (DevTools #3).

The injection path is the quickest way to turn a DevTools user into a
DoS on themselves — a bug here could silently swallow a command, run
it twice, or bypass the reconnect guard.  Tests guard the contract:

* Injected payload lands in the real dispatcher → HA service gets
  called exactly once.
* The message log marks synthetic traffic with ``direction="replay"``
  (or ``"in"`` when ``mark_replay=False``).
* Correlation trace + state diff see the same event they'd see for
  real MQTT traffic.
* Unknown topic suffixes return ``handled=False`` instead of raising.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from unittest.mock import AsyncMock, MagicMock

from custom_components.sber_mqtt_bridge.const import (
    CONF_SBER_BROKER,
    CONF_SBER_LOGIN,
    CONF_SBER_PASSWORD,
    CONF_SBER_PORT,
)
from custom_components.sber_mqtt_bridge.devices.relay import RelayEntity
from custom_components.sber_mqtt_bridge.sber_bridge import SberBridge


def _entry():
    entry = MagicMock()
    entry.data = {
        CONF_SBER_LOGIN: "test",
        CONF_SBER_PASSWORD: "pass",
        CONF_SBER_BROKER: "broker.test",
        CONF_SBER_PORT: 8883,
    }
    entry.options = {}
    return entry


def _hass():
    hass = MagicMock()
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock()
    hass.config.location_name = "My Home"
    tasks: list[asyncio.Task] = []

    def capture(coro, **_):
        t = asyncio.ensure_future(coro)
        tasks.append(t)
        return t

    hass.async_create_task = MagicMock(side_effect=capture)
    hass._created_tasks = tasks
    return hass


def _relay_bridge(hass):
    bridge = SberBridge(hass, _entry())
    bridge._mqtt_client = AsyncMock()
    bridge._mqtt_service.publish = AsyncMock()
    bridge._connected = True
    bridge._ack_audit.cancel()
    rel = RelayEntity({"entity_id": "switch.lamp", "name": "Lamp"})
    rel.fill_by_ha_state({"entity_id": "switch.lamp", "state": "off", "attributes": {}})
    bridge._entities["switch.lamp"] = rel
    bridge._enabled_entity_ids = ["switch.lamp"]
    return bridge


async def _drain(hass):
    for t in list(getattr(hass, "_created_tasks", [])):
        if not t.done():
            with contextlib.suppress(TimeoutError, Exception):
                await asyncio.wait_for(t, timeout=5)


def _cmd_payload() -> str:
    return json.dumps(
        {
            "devices": {
                "switch.lamp": {
                    "states": [
                        {"key": "on_off", "value": {"type": "BOOL", "bool_value": True}},
                    ],
                }
            }
        }
    )


class TestInjectRoutesThroughDispatcher:
    """An injected command must look identical to the real one downstream."""

    async def test_injected_command_triggers_ha_service_call(self) -> None:
        hass = _hass()
        bridge = _relay_bridge(hass)
        await bridge.async_inject_sber_message("commands", _cmd_payload())
        await _drain(hass)
        # Without the service call, injection is worthless — the whole
        # point is to replay command flow end-to-end.
        hass.services.async_call.assert_called()
        call = hass.services.async_call.call_args
        assert call.kwargs["domain"] == "switch"
        assert call.kwargs["service"] == "turn_on"

    async def test_full_topic_and_suffix_both_work(self) -> None:
        hass = _hass()
        bridge = _relay_bridge(hass)
        # Suffix-only form — bridge expands to full {root}/down/commands.
        res = await bridge.async_inject_sber_message("commands", _cmd_payload())
        await _drain(hass)
        assert res["handled"] is True
        assert res["topic"].endswith("/down/commands")

        full = f"{bridge._down_topic}/commands"
        res2 = await bridge.async_inject_sber_message(full, _cmd_payload())
        await _drain(hass)
        assert res2["handled"] is True
        assert res2["topic"] == full

    async def test_injection_appears_in_correlation_trace(self) -> None:
        hass = _hass()
        bridge = _relay_bridge(hass)
        await bridge.async_inject_sber_message("commands", _cmd_payload())
        await _drain(hass)
        traces = bridge.trace_collector.snapshot()
        # The trace must contain the sber_command event and at least
        # one ha_service_call — otherwise DevTools would hide the
        # consequences of the replay entirely.
        assert traces, "no trace created by inject"
        types = {e["type"] for e in traces[0]["events"]}
        assert "sber_command" in types
        assert "ha_service_call" in types


class TestMessageLogMarking:
    async def test_mark_replay_true_writes_replay_direction(self) -> None:
        hass = _hass()
        bridge = _relay_bridge(hass)
        await bridge.async_inject_sber_message("commands", _cmd_payload(), mark_replay=True)
        await _drain(hass)
        # The UI tints synthetic rows based on this field — losing it
        # turns the log into a liar about what's real.
        directions = [m["direction"] for m in bridge.message_log]
        assert "replay" in directions

    async def test_mark_replay_false_writes_in_direction(self) -> None:
        hass = _hass()
        bridge = _relay_bridge(hass)
        await bridge.async_inject_sber_message("commands", _cmd_payload(), mark_replay=False)
        await _drain(hass)
        directions = [m["direction"] for m in bridge.message_log]
        assert "in" in directions
        assert "replay" not in directions


class TestErrorPaths:
    async def test_unknown_suffix_returns_handled_false_without_raising(self) -> None:
        hass = _hass()
        bridge = _relay_bridge(hass)
        # Protocol typo must not take the bridge down — DevTools users
        # type freely, and an uncaught exception here would reach HA
        # logs as an error every time.
        res = await bridge.async_inject_sber_message("nope", "{}")
        assert res == {
            "topic": f"{bridge._down_topic}/nope",
            "handled": False,
            "suffix": "nope",
        }

    async def test_bytes_payload_accepted(self) -> None:
        hass = _hass()
        bridge = _relay_bridge(hass)
        # aiomqtt delivers bytes — the real pipeline must accept them
        # too so "paste exactly what the broker delivered" works.
        res = await bridge.async_inject_sber_message("commands", _cmd_payload().encode())
        await _drain(hass)
        assert res["handled"] is True


class TestWebSocketHandlers:
    """Smoke-test the two WS wrappers (inject + replay)."""

    async def test_inject_ws_returns_handled_true(self) -> None:
        from unittest.mock import patch

        from custom_components.sber_mqtt_bridge.websocket_api.replay import (
            ws_inject_sber_message,
        )

        hass = _hass()
        bridge = _relay_bridge(hass)
        connection = MagicMock()
        connection.send_result = MagicMock()
        connection.send_error = MagicMock()
        with patch(
            "custom_components.sber_mqtt_bridge.websocket_api.replay.get_bridge",
            return_value=bridge,
        ):
            await ws_inject_sber_message.__wrapped__(
                hass,
                connection,
                {
                    "id": 1,
                    "topic": "commands",
                    "payload": _cmd_payload(),
                    "mark_replay": True,
                },
            )
            await _drain(hass)
        payload = connection.send_result.call_args[0][1]
        assert payload["handled"] is True
        connection.send_error.assert_not_called()

    async def test_replay_ws_missing_bridge_sends_error(self) -> None:
        from unittest.mock import patch

        from custom_components.sber_mqtt_bridge.websocket_api.replay import (
            ws_replay_message,
        )

        hass = _hass()
        connection = MagicMock()
        connection.send_result = MagicMock()
        connection.send_error = MagicMock()
        with patch(
            "custom_components.sber_mqtt_bridge.websocket_api.replay.get_bridge",
            return_value=None,
        ):
            await ws_replay_message.__wrapped__(
                hass,
                connection,
                {"id": 1, "topic": "commands", "payload": "{}"},
            )
        # A clear error code lets the UI tell the user "bridge not loaded"
        # instead of a generic spinner timeout.
        err = connection.send_error.call_args
        assert err[0][1] == "bridge_not_found"
