"""Bridge-level persistence of Sber device redefinitions.

Sber lets the user rename a device or move it to another room from the
Salute app.  Those edits arrive as ``change_group`` / ``rename_device``
messages and must survive an HA restart, i.e. end up in
``ConfigEntry.options["redefinitions"]`` and be restored on load.

The debounce/timer mechanics of :class:`RedefinitionsStore` itself are
covered by ``test_timers_lifecycle.py``; here we pin the bridge wiring
end-to-end.  Moved out of the former ``test_p4_tasks.py`` grab-bag.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from custom_components.sber_mqtt_bridge.const import (
    CONF_EXPOSED_ENTITIES,
    CONF_SBER_BROKER,
    CONF_SBER_LOGIN,
    CONF_SBER_PASSWORD,
    CONF_SBER_PORT,
)
from custom_components.sber_mqtt_bridge.sber_bridge import SberBridge
from custom_components.sber_mqtt_bridge.sber_protocol import build_devices_list_json


def _make_entry(options=None):
    """Create a mock config entry with Sber credentials."""
    entry = MagicMock()
    entry.data = {
        CONF_SBER_LOGIN: "test",
        CONF_SBER_PASSWORD: "pass",
        CONF_SBER_BROKER: "broker.test",
        CONF_SBER_PORT: 8883,
    }
    entry.options = options or {}
    return entry


def _persisted_redefinitions(bridge) -> dict:
    """Return the redefinitions written to ConfigEntry options."""
    update = bridge._hass.config_entries.async_update_entry
    assert update.call_count == 1, f"expected exactly one options write, got {update.call_count}"
    options = update.call_args.kwargs["options"]
    return options["redefinitions"]


@pytest.fixture
def bridge():
    """Bridge with a MagicMock hass (config_entries writes are recorded)."""
    return SberBridge(MagicMock(), _make_entry())


async def test_change_group_persists_room_and_home(bridge):
    payload = json.dumps(
        {
            "device_id": "light.living_room",
            "home": "Home",
            "room": "Living Room",
        }
    ).encode()

    await bridge._handle_change_group(payload)
    bridge._flush_redefinitions()  # debounced — flush manually for test

    assert bridge._redefinitions["light.living_room"]["room"] == "Living Room"
    assert _persisted_redefinitions(bridge) == {"light.living_room": {"home": "Home", "room": "Living Room"}}


async def test_rename_device_persists_new_name(bridge):
    payload = json.dumps(
        {
            "device_id": "light.kitchen",
            "new_name": "Kitchen Light New",
        }
    ).encode()

    await bridge._handle_rename_device(payload)
    bridge._flush_redefinitions()  # debounced — flush manually for test

    assert bridge._redefinitions["light.kitchen"]["name"] == "Kitchen Light New"
    assert _persisted_redefinitions(bridge) == {"light.kitchen": {"name": "Kitchen Light New"}}


async def test_persist_keeps_existing_unrelated_options(bridge):
    bridge._entry.options = {CONF_EXPOSED_ENTITIES: ["light.a"]}
    bridge._redefinitions["light.a"] = {"room": "Room A"}
    bridge._persist_redefinitions()
    bridge._flush_redefinitions()

    written = bridge._hass.config_entries.async_update_entry.call_args.kwargs["options"]
    assert written[CONF_EXPOSED_ENTITIES] == ["light.a"], "unrelated options must not be dropped"
    assert written["redefinitions"] == {"light.a": {"room": "Room A"}}


def test_load_restores_persisted_redefinitions():
    """A saved redefinition is re-applied to the entity on load."""
    hass = MagicMock()
    hass.data = {}
    # Include light.saved in exposed list so it survives pruning
    entry = _make_entry(
        options={
            CONF_EXPOSED_ENTITIES: ["light.saved"],
            "redefinitions": {"light.saved": {"room": "Saved Room"}},
        }
    )
    bridge = SberBridge(hass, entry)

    # Mock registries: entity registry returns a valid entry for light.saved
    mock_reg_entry = MagicMock()
    mock_reg_entry.entity_id = "light.saved"
    mock_reg_entry.area_id = ""
    mock_reg_entry.device_id = None
    mock_reg_entry.name = "Saved"
    mock_reg_entry.original_name = "Saved"
    mock_reg_entry.platform = "test"
    mock_reg_entry.unique_id = "saved_1"
    mock_reg_entry.original_device_class = None
    mock_reg_entry.entity_category = None
    mock_reg_entry.icon = None
    mock_reg_entry.disabled_by = None
    mock_reg_entry.hidden_by = None

    with (
        patch("custom_components.sber_mqtt_bridge.entity_registry.er") as mock_er,
        patch("custom_components.sber_mqtt_bridge.entity_registry.dr"),
        patch("custom_components.sber_mqtt_bridge.entity_registry.ar"),
        patch("custom_components.sber_mqtt_bridge.sber_bridge.check_and_create_issues"),
    ):
        mock_entity_reg = MagicMock()
        mock_entity_reg.async_get.return_value = mock_reg_entry
        mock_er.async_get.return_value = mock_entity_reg

        # Mock states so entity gets filled
        mock_state = MagicMock()
        mock_state.entity_id = "light.saved"
        mock_state.state = "on"
        mock_state.attributes = {}
        hass.states.get.return_value = mock_state

        bridge._load_exposed_entities()

    assert bridge._redefinitions.get("light.saved") == {"room": "Saved Room"}

    # The restored room must reach the Sber config payload, not just the store.
    payload, _valid, _invalid = build_devices_list_json(
        bridge._entities,
        bridge._enabled_entity_ids,
        redefinitions=bridge._redefinitions,
    )
    device = next(d for d in json.loads(payload)["devices"] if d["id"] == "light.saved")
    assert device["room"] == "Saved Room"


def test_load_drops_redefinitions_for_no_longer_exposed_entities():
    """Stale redefinitions must not accumulate in options forever."""
    hass = MagicMock()
    hass.data = {}
    entry = _make_entry(
        options={
            CONF_EXPOSED_ENTITIES: [],
            "redefinitions": {"light.gone": {"room": "Old Room"}},
        }
    )
    bridge = SberBridge(hass, entry)

    with (
        patch("custom_components.sber_mqtt_bridge.entity_registry.er"),
        patch("custom_components.sber_mqtt_bridge.entity_registry.dr"),
        patch("custom_components.sber_mqtt_bridge.entity_registry.ar"),
        patch("custom_components.sber_mqtt_bridge.sber_bridge.check_and_create_issues"),
    ):
        bridge._load_exposed_entities()

    assert "light.gone" not in bridge._redefinitions
