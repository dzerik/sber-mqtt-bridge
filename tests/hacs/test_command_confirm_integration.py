"""Command confirmation wired through the real bridge publish path.

Guards the two wiring points that make the tracker meaningful: the
dispatcher records the command *before* anything is published, and only
full state snapshots — never the command echo — can confirm it.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from custom_components.sber_mqtt_bridge.devices.relay import RelayEntity
from tests.hacs.test_traces_integration import _cmd, _drain, _make_bridge_with_relay, _make_hass


async def _command(bridge, hass) -> None:
    with patch("custom_components.sber_mqtt_bridge.sber_bridge.asyncio.sleep", new_callable=AsyncMock):
        await bridge._handle_sber_command(_cmd("switch.lamp"))
        await _drain(hass)


async def test_echo_alone_does_not_confirm() -> None:
    """The echo repeats the command; the relay is still off in HA."""
    hass = _make_hass()
    bridge = _make_bridge_with_relay(hass)

    await _command(bridge, hass)

    [record] = bridge.command_confirm.snapshot()
    assert record["entity_id"] == "switch.lamp"
    assert record["status"] == "pending"
    assert record["keys"][0]["reported"] == {"type": "BOOL", "bool_value": False}


async def test_state_reaching_ha_confirms() -> None:
    hass = _make_hass()
    bridge = _make_bridge_with_relay(hass)
    await _command(bridge, hass)

    entity: RelayEntity = bridge._entities["switch.lamp"]
    entity.fill_by_ha_state({"entity_id": "switch.lamp", "state": "on", "attributes": {}})
    await bridge.async_publish_entity_status("switch.lamp")

    [record] = bridge.command_confirm.snapshot()
    assert record["status"] == "confirmed"
    trace = bridge.trace_collector.snapshot()[0]
    assert record["context_id"] == trace["trace_id"], "confirmation must link to its trace"


async def test_device_that_never_changes_is_not_confirmed() -> None:
    """Issue #63: the service call succeeded, the lamp stayed as it was."""
    hass = _make_hass()
    bridge = _make_bridge_with_relay(hass)
    bridge.command_confirm._timeout = 0
    await _command(bridge, hass)
    await bridge.async_publish_entity_status("switch.lamp")

    bridge._devtools.sweep_traces()

    [record] = bridge.command_confirm.snapshot()
    assert record["status"] == "not_confirmed"


def test_tolerance_follows_the_feature_range() -> None:
    hass = _make_hass()
    bridge = _make_bridge_with_relay(hass)
    assert bridge._confirm_tolerance("switch.lamp", "on_off", "BOOL") == 0
    # Documented brightness range 100–900 through an 8-bit HA scale.
    assert bridge._confirm_tolerance("light.unknown", "light_brightness", "INTEGER") == 3
    assert bridge._confirm_tolerance("light.unknown", "no_such_feature", "INTEGER") == 0
