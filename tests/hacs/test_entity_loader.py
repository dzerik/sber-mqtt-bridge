"""Behavioral tests for ``SberEntityLoader`` (entity_registry.py).

Covers the loader paths flagged by review W2C:

- Per-entity isolation: a broken ``fill_by_ha_state`` (real degenerate CCT
  range on a light) must not abort loading of the other entities.
- Restoration of entity links from config-entry options, including links
  pointing at missing primaries, missing linked states, and the
  linked-is-also-primary guard.
- Device registry linking (MAC extraction, hw/sw fallbacks, area names,
  device-id mismatch resilience).
- YAML overrides (name / nicknames / features / sber_type) and their
  priority against options-level type overrides.
- Room overrides merged into redefinitions with correct priority.
- Idempotent repeat loads without duplication.

Only true external boundaries are mocked (HA registries + ``hass.states``);
Sber device classes are real so the assertions verify observable entity
behavior, not mock call signatures.
"""

from __future__ import annotations

import asyncio
import json
import logging
from unittest.mock import MagicMock, patch

import pytest

import custom_components.sber_mqtt_bridge.entity_registry as entity_registry_module
from custom_components.sber_mqtt_bridge.const import (
    CONF_ENTITY_LINKS,
    CONF_ENTITY_TYPE_OVERRIDES,
    CONF_EXPOSED_ENTITIES,
    DOMAIN,
)
from custom_components.sber_mqtt_bridge.custom_capabilities import (
    CustomConfig,
    EntityCustomConfig,
)
from custom_components.sber_mqtt_bridge.devices.light import LightEntity
from custom_components.sber_mqtt_bridge.devices.sensor_temp import SensorTempEntity
from custom_components.sber_mqtt_bridge.entity_registry import SberEntityLoader
from custom_components.sber_mqtt_bridge.sber_protocol import build_devices_list_json

# ---------------------------------------------------------------------------
# Minimal HA stubs (external boundary only)
# ---------------------------------------------------------------------------


class _FakeState:
    """Stand-in for ``homeassistant.core.State`` with the fields the loader reads."""

    def __init__(self, entity_id: str, state: str, attributes: dict | None = None) -> None:
        self.entity_id = entity_id
        self.state = state
        self.attributes = attributes or {}


def _make_reg_entry(
    entity_id: str,
    *,
    device_id: str | None = None,
    original_device_class: str | None = None,
    name: str | None = None,
    original_name: str | None = None,
    area_id: str | None = None,
    platform: str = "test",
) -> MagicMock:
    entry = MagicMock()
    entry.entity_id = entity_id
    entry.device_id = device_id
    entry.original_device_class = original_device_class
    entry.name = name
    entry.original_name = original_name
    entry.area_id = area_id
    entry.platform = platform
    entry.unique_id = entity_id
    entry.entity_category = None
    entry.icon = None
    entry.disabled_by = None
    entry.hidden_by = None
    return entry


def _make_device(
    device_id: str,
    *,
    name: str = "Device",
    name_by_user: str | None = None,
    area_id: str | None = None,
    manufacturer: str | None = None,
    model: str | None = None,
    model_id: str | None = None,
    hw_version: str | None = None,
    sw_version: str | None = None,
    serial_number: str | None = None,
    connections: set[tuple[str, str]] | None = None,
) -> MagicMock:
    device = MagicMock()
    device.id = device_id
    device.name = name
    device.name_by_user = name_by_user
    device.area_id = area_id
    device.manufacturer = manufacturer
    device.model = model
    device.model_id = model_id
    device.hw_version = hw_version
    device.sw_version = sw_version
    device.serial_number = serial_number
    device.connections = connections or set()
    return device


def _make_area(area_id: str, name: str) -> MagicMock:
    area = MagicMock()
    area.id = area_id
    area.name = name
    return area


class _Env:
    """Bundle of hass + registry mocks with mutable backing dicts."""

    def __init__(self) -> None:
        self.entries: dict[str, MagicMock] = {}
        self.devices: dict[str, MagicMock] = {}
        self.areas: dict[str, MagicMock] = {}
        self.states: dict[str, _FakeState] = {}

        self.hass = MagicMock()
        self.hass.data = {}
        self.hass.is_running = True
        self.hass.states.get.side_effect = lambda eid: self.states.get(eid)

        self.entity_reg = MagicMock()
        self.entity_reg.async_get.side_effect = lambda eid: self.entries.get(eid)
        self.device_reg = MagicMock()
        self.device_reg.async_get.side_effect = lambda did: self.devices.get(did)
        self.area_reg = MagicMock()
        self.area_reg.async_get_area.side_effect = lambda aid: self.areas.get(aid)

    def set_yaml(self, entity_configs: dict[str, EntityCustomConfig]) -> None:
        self.hass.data[DOMAIN] = {"yaml_config": CustomConfig(entity_configs=entity_configs)}

    def make_entry(self, options: dict) -> MagicMock:
        entry = MagicMock()
        entry.options = options
        return entry


@pytest.fixture
def env():
    """Yield an ``_Env`` with HA registry lookups patched at the loader module."""
    environment = _Env()
    with (
        patch(
            "custom_components.sber_mqtt_bridge.entity_registry.er.async_get",
            return_value=environment.entity_reg,
        ),
        patch(
            "custom_components.sber_mqtt_bridge.entity_registry.dr.async_get",
            return_value=environment.device_reg,
        ),
        patch(
            "custom_components.sber_mqtt_bridge.entity_registry.ar.async_get",
            return_value=environment.area_reg,
        ),
    ):
        yield environment


def _add_light(env: _Env, entity_id: str, *, state: str = "on", attrs: dict | None = None) -> None:
    env.entries[entity_id] = _make_reg_entry(entity_id)
    env.states[entity_id] = _FakeState(entity_id, state, attrs or {"brightness": 128})


#: Real-world poison: kelvin range so narrow both bounds round to 154 mireds,
#: which makes LinearConverter.set_ha_limits raise ValueError inside
#: LightEntity.fill_by_ha_state (the exact failure from the review finding).
_DEGENERATE_CCT_ATTRS = {"min_color_temp_kelvin": 6493, "max_color_temp_kelvin": 6500}


# ---------------------------------------------------------------------------
# Per-entity isolation in _create_entities
# ---------------------------------------------------------------------------


def test_broken_entity_does_not_abort_other_entities(env, caplog) -> None:
    """One light with a degenerate CCT range must not break the whole load."""
    _add_light(env, "light.ok1", state="on")
    _add_light(env, "light.broken", attrs=_DEGENERATE_CCT_ATTRS)
    _add_light(env, "light.ok2", state="off")
    entry = env.make_entry({CONF_EXPOSED_ENTITIES: ["light.ok1", "light.broken", "light.ok2"]})

    with caplog.at_level(logging.WARNING, logger=entity_registry_module.__name__):
        result = SberEntityLoader(env.hass, entry).load()

    assert set(result.entities) == {"light.ok1", "light.ok2"}
    assert result.enabled_entity_ids == ["light.ok1", "light.ok2"]
    # Survivors got their state actually applied, not just instantiated.
    assert result.entities["light.ok1"].current_state is True
    assert result.entities["light.ok1"].is_filled_by_state is True
    assert result.entities["light.ok2"].current_state is False
    # The dropped entity MUST be traceable: this log line is the only signal
    # a user gets that a device silently vanished from the Sber payload.
    dropped_records = [
        rec
        for rec in caplog.records
        if rec.name == entity_registry_module.__name__ and "light.broken" in rec.getMessage()
    ]
    assert len(dropped_records) == 1, "no diagnostic log naming the dropped entity"
    assert dropped_records[0].exc_info is not None, "log must carry the traceback"
    assert "light.ok1" not in dropped_records[0].getMessage()


def test_broken_entity_order_does_not_matter(env) -> None:
    """A poisoned entity first in the list must not shadow later ones."""
    _add_light(env, "light.broken", attrs=_DEGENERATE_CCT_ATTRS)
    _add_light(env, "light.ok", state="on")
    entry = env.make_entry({CONF_EXPOSED_ENTITIES: ["light.broken", "light.ok"]})

    result = SberEntityLoader(env.hass, entry).load()

    assert set(result.entities) == {"light.ok"}


def test_all_entities_broken_yields_empty_result_without_raising(env) -> None:
    _add_light(env, "light.b1", attrs=_DEGENERATE_CCT_ATTRS)
    _add_light(env, "light.b2", attrs=_DEGENERATE_CCT_ATTRS)
    entry = env.make_entry({CONF_EXPOSED_ENTITIES: ["light.b1", "light.b2"]})

    result = SberEntityLoader(env.hass, entry).load()

    assert result.entities == {}
    assert result.enabled_entity_ids == []


def test_cancellation_during_fill_is_not_swallowed(env) -> None:
    """The isolation ``except`` must stay narrow: cancellation propagates.

    ``asyncio.CancelledError`` is a ``BaseException`` — widening the tuple
    to ``Exception``/``BaseException`` would turn a HA shutdown into a
    silently half-loaded registry.
    """
    _add_light(env, "light.a")
    _add_light(env, "light.b")
    entry = env.make_entry({CONF_EXPOSED_ENTITIES: ["light.a", "light.b"]})

    with (
        patch.object(LightEntity, "fill_by_ha_state", side_effect=asyncio.CancelledError),
        pytest.raises(asyncio.CancelledError),
    ):
        SberEntityLoader(env.hass, entry).load()


def test_cancellation_during_linked_update_is_not_swallowed(env) -> None:
    """Same narrowness contract for the linked-state ``except``."""
    _add_temp_sensor(env, "sensor.temp")
    env.states["sensor.hum"] = _FakeState("sensor.hum", "55")
    entry = env.make_entry(
        {
            CONF_EXPOSED_ENTITIES: ["sensor.temp"],
            CONF_ENTITY_LINKS: {"sensor.temp": {"humidity": "sensor.hum"}},
        }
    )

    with (
        patch.object(SensorTempEntity, "update_linked_data", side_effect=asyncio.CancelledError),
        pytest.raises(asyncio.CancelledError),
    ):
        SberEntityLoader(env.hass, entry).load()


def test_unsupported_domain_entity_is_skipped(env) -> None:
    """A domain with no Sber category yields no entity instead of crashing."""
    env.entries["camera.doorbell"] = _make_reg_entry("camera.doorbell")
    env.states["camera.doorbell"] = _FakeState("camera.doorbell", "idle")
    _add_light(env, "light.ok")
    env.set_yaml({"camera.doorbell": EntityCustomConfig(sber_name="Камера")})
    entry = env.make_entry({CONF_EXPOSED_ENTITIES: ["camera.doorbell", "light.ok"]})

    result = SberEntityLoader(env.hass, entry).load()

    assert set(result.entities) == {"light.ok"}
    assert result.enabled_entity_ids == ["light.ok"]


def test_entity_missing_from_registry_is_skipped(env) -> None:
    """Exposed IDs no longer present in the entity registry are dropped."""
    _add_light(env, "light.ok")
    entry = env.make_entry({CONF_EXPOSED_ENTITIES: ["light.gone", "light.ok"]})

    result = SberEntityLoader(env.hass, entry).load()

    assert set(result.entities) == {"light.ok"}


def test_entity_without_state_is_created_unfilled(env) -> None:
    """No HA state yet (startup order) → entity exists but is not state-filled."""
    env.entries["light.late"] = _make_reg_entry("light.late")
    entry = env.make_entry({CONF_EXPOSED_ENTITIES: ["light.late"]})

    result = SberEntityLoader(env.hass, entry).load()

    assert "light.late" in result.entities
    assert result.entities["light.late"].is_filled_by_state is False


# ---------------------------------------------------------------------------
# Entity links restoration (_apply_entity_links)
# ---------------------------------------------------------------------------


def _add_temp_sensor(env: _Env, entity_id: str, *, state: str = "22.5") -> None:
    env.entries[entity_id] = _make_reg_entry(entity_id, original_device_class="temperature")
    env.states[entity_id] = _FakeState(entity_id, state)


def test_links_restored_from_options_with_initial_data(env) -> None:
    """Links from options are rebuilt and the linked state is applied."""
    _add_temp_sensor(env, "sensor.temp", state="22.5")
    env.states["sensor.hum"] = _FakeState("sensor.hum", "55")
    env.states["sensor.batt"] = _FakeState("sensor.batt", "87")
    entry = env.make_entry(
        {
            CONF_EXPOSED_ENTITIES: ["sensor.temp"],
            CONF_ENTITY_LINKS: {"sensor.temp": {"humidity": "sensor.hum", "battery": "sensor.batt"}},
        }
    )

    result = SberEntityLoader(env.hass, entry).load()

    assert result.entity_links == {"sensor.temp": {"humidity": "sensor.hum", "battery": "sensor.batt"}}
    assert result.linked_reverse == {
        "sensor.hum": ("sensor.temp", "humidity"),
        "sensor.batt": ("sensor.temp", "battery"),
    }
    primary = result.entities["sensor.temp"]
    # Behavioral: linked data landed in the entity and changes its features.
    assert primary._linked_humidity == 55
    assert primary._battery_level == 87
    assert "humidity" in primary._create_features_list()


def test_link_for_missing_primary_is_dropped(env) -> None:
    """Stale link whose primary is no longer exposed disappears from both maps."""
    _add_temp_sensor(env, "sensor.temp")
    env.states["sensor.hum"] = _FakeState("sensor.hum", "50")
    entry = env.make_entry(
        {
            CONF_EXPOSED_ENTITIES: ["sensor.temp"],
            CONF_ENTITY_LINKS: {"sensor.gone": {"humidity": "sensor.hum"}},
        }
    )

    result = SberEntityLoader(env.hass, entry).load()

    assert result.entity_links == {}
    assert result.linked_reverse == {}
    assert result.entities["sensor.temp"]._linked_humidity is None


def test_linked_entity_that_is_also_primary_is_rejected(env) -> None:
    """Guard: linking an exposed primary would double-publish it to Sber."""
    _add_temp_sensor(env, "sensor.t1")
    env.entries["sensor.h1"] = _make_reg_entry("sensor.h1", original_device_class="humidity")
    env.states["sensor.h1"] = _FakeState("sensor.h1", "60")
    env.states["sensor.batt"] = _FakeState("sensor.batt", "42")
    entry = env.make_entry(
        {
            CONF_EXPOSED_ENTITIES: ["sensor.t1", "sensor.h1"],
            CONF_ENTITY_LINKS: {"sensor.t1": {"humidity": "sensor.h1", "battery": "sensor.batt"}},
        }
    )

    result = SberEntityLoader(env.hass, entry).load()

    # The conflicting humidity link is dropped, the innocent battery link stays.
    assert result.entity_links == {"sensor.t1": {"battery": "sensor.batt"}}
    assert result.linked_reverse == {"sensor.batt": ("sensor.t1", "battery")}
    assert result.entities["sensor.t1"]._linked_humidity is None
    # Both primaries are still exposed as standalone devices.
    assert set(result.entities) == {"sensor.t1", "sensor.h1"}


def test_link_with_only_conflicting_role_yields_no_links_entry(env) -> None:
    _add_temp_sensor(env, "sensor.t1")
    env.entries["sensor.h1"] = _make_reg_entry("sensor.h1", original_device_class="humidity")
    env.states["sensor.h1"] = _FakeState("sensor.h1", "60")
    entry = env.make_entry(
        {
            CONF_EXPOSED_ENTITIES: ["sensor.t1", "sensor.h1"],
            CONF_ENTITY_LINKS: {"sensor.t1": {"humidity": "sensor.h1"}},
        }
    )

    result = SberEntityLoader(env.hass, entry).load()

    assert result.entity_links == {}
    assert result.linked_reverse == {}


def test_link_with_unavailable_state_is_kept_in_maps(env) -> None:
    """Linked entity without a state yet keeps the link for later updates."""
    _add_temp_sensor(env, "sensor.temp")
    # sensor.hum has NO state in hass.
    entry = env.make_entry(
        {
            CONF_EXPOSED_ENTITIES: ["sensor.temp"],
            CONF_ENTITY_LINKS: {"sensor.temp": {"humidity": "sensor.hum"}},
        }
    )

    result = SberEntityLoader(env.hass, entry).load()

    assert result.entity_links == {"sensor.temp": {"humidity": "sensor.hum"}}
    assert result.linked_reverse == {"sensor.hum": ("sensor.temp", "humidity")}
    assert result.entities["sensor.temp"]._linked_humidity is None


def test_update_linked_data_error_keeps_link_and_load(env) -> None:
    """A crash while applying the initial linked state must not drop the link."""
    _add_temp_sensor(env, "sensor.temp")
    env.states["sensor.hum"] = _FakeState("sensor.hum", "55")
    entry = env.make_entry(
        {
            CONF_EXPOSED_ENTITIES: ["sensor.temp"],
            CONF_ENTITY_LINKS: {"sensor.temp": {"humidity": "sensor.hum"}},
        }
    )

    with patch.object(SensorTempEntity, "update_linked_data", side_effect=ValueError("boom")):
        result = SberEntityLoader(env.hass, entry).load()

    assert result.entity_links == {"sensor.temp": {"humidity": "sensor.hum"}}
    assert result.linked_reverse == {"sensor.hum": ("sensor.temp", "humidity")}
    # register_link still ran: the entity knows its companion for future updates.
    assert result.entities["sensor.temp"]._linked_entities == {"humidity": "sensor.hum"}


# ---------------------------------------------------------------------------
# Device registry linking (_link_device_registry)
# ---------------------------------------------------------------------------


def test_device_registry_data_linked_with_mac_and_fallbacks(env) -> None:
    env.entries["light.ok"] = _make_reg_entry("light.ok", device_id="dev1")
    env.states["light.ok"] = _FakeState("light.ok", "on")
    env.areas["area1"] = _make_area("area1", "Кухня")
    env.devices["dev1"] = _make_device(
        "dev1",
        name="Lamp",
        name_by_user="My Lamp",
        area_id="area1",
        manufacturer="Acme",
        model=None,
        hw_version=None,
        sw_version="2.1",
        connections={("bluetooth", "11:22"), ("mac", "aa:bb:cc:dd:ee:ff")},
    )
    entry = env.make_entry({CONF_EXPOSED_ENTITIES: ["light.ok"]})

    result = SberEntityLoader(env.hass, entry).load()

    linked = result.entities["light.ok"].linked_device
    assert linked is not None
    assert linked["id"] == "dev1"
    assert linked["name"] == "My Lamp"  # name_by_user wins
    assert linked["area_id"] == "Кухня"  # area resolved to human name
    assert linked["manufacturer"] == "Acme"
    assert linked["model"] == "Unknown"  # None → fallback
    assert linked["hw_version"] == "1"  # None → fallback
    assert linked["sw_version"] == "2.1"
    assert linked["mac"] == "aa:bb:cc:dd:ee:ff"  # bluetooth connection ignored


def test_device_registry_without_mac_yields_empty_mac(env) -> None:
    """Non-MAC connections (and none at all) must not leak into ``mac``."""
    env.entries["light.ok"] = _make_reg_entry("light.ok", device_id="dev1")
    env.states["light.ok"] = _FakeState("light.ok", "on")
    env.devices["dev1"] = _make_device("dev1", connections={("zigbee", "0x00124b00")})
    entry = env.make_entry({CONF_EXPOSED_ENTITIES: ["light.ok"]})

    result = SberEntityLoader(env.hass, entry).load()

    assert result.entities["light.ok"].linked_device["mac"] == ""


def _sber_device_ids(result) -> list[str]:
    """Serialize a load result the way the publisher does and list device ids.

    Uses the real ``build_devices_list_json`` so a half-initialised entity
    (``device_id`` set + ``linked_device`` None) surfaces exactly as it
    would in production: ``BaseEntity.to_sber_state`` raises ``RuntimeError``,
    which the protocol layer does *not* catch, aborting the whole publish.
    """
    payload, _valid, _invalid = build_devices_list_json(
        result.entities,
        result.enabled_entity_ids,
        result.redefinitions,
        default_home="Дом",
        default_room="Дом",
    )
    return [device["id"] for device in json.loads(payload)["devices"]]


def test_device_id_mismatch_demotes_entity_to_standalone(env) -> None:
    """A foreign device from the registry must not leave a half-linked entity.

    ``device_id`` set without ``linked_device`` makes ``to_sber_state``
    raise ``RuntimeError`` and kills the publication of the *entire*
    device list, so the loader clears ``device_id`` instead.
    """
    env.entries["light.ok"] = _make_reg_entry("light.ok", device_id="dev1")
    env.states["light.ok"] = _FakeState("light.ok", "on")
    env.devices["dev1"] = _make_device("other-id")
    _add_light(env, "light.healthy")
    entry = env.make_entry({CONF_EXPOSED_ENTITIES: ["light.ok", "light.healthy"]})

    result = SberEntityLoader(env.hass, entry).load()

    assert "light.ok" in result.entities
    assert result.entities["light.ok"].linked_device is None
    assert result.entities["light.ok"].device_id is None
    # Publication of the whole list still works and keeps both devices.
    assert _sber_device_ids(result) == ["root", "light.ok", "light.healthy"]


def test_device_absent_from_registry_demotes_entity_to_standalone(env) -> None:
    """Device deleted between registry reads → entity published standalone."""
    env.entries["light.ok"] = _make_reg_entry("light.ok", device_id="dev-missing")
    env.states["light.ok"] = _FakeState("light.ok", "on")
    _add_light(env, "light.healthy")
    entry = env.make_entry({CONF_EXPOSED_ENTITIES: ["light.ok", "light.healthy"]})

    result = SberEntityLoader(env.hass, entry).load()

    assert "light.ok" in result.entities
    assert result.entities["light.ok"].linked_device is None
    assert result.entities["light.ok"].device_id is None
    # Without the demotion this call raises RuntimeError and NOTHING is
    # published — not even the healthy light.
    assert _sber_device_ids(result) == ["root", "light.ok", "light.healthy"]


def test_multiple_entities_of_one_device_are_reported(env, caplog) -> None:
    """Duplicate-risk warning fires only for real (non-linked) duplicates."""
    for eid in ("light.a", "light.b"):
        env.entries[eid] = _make_reg_entry(eid, device_id="dev1")
        env.states[eid] = _FakeState(eid, "on")
    env.devices["dev1"] = _make_device("dev1", name="Multi")
    entry = env.make_entry({CONF_EXPOSED_ENTITIES: ["light.a", "light.b"]})

    with caplog.at_level(logging.WARNING, logger=entity_registry_module.__name__):
        result = SberEntityLoader(env.hass, entry).load()

    assert set(result.entities) == {"light.a", "light.b"}
    conflict = [rec.getMessage() for rec in caplog.records if "may cause duplicates" in rec.getMessage()]
    assert len(conflict) == 1
    assert "light.a" in conflict[0]
    assert "light.b" in conflict[0]


def test_single_entity_per_device_reports_no_conflict(env, caplog) -> None:
    """Control case: one entity per device must stay silent."""
    env.entries["light.a"] = _make_reg_entry("light.a", device_id="dev1")
    env.states["light.a"] = _FakeState("light.a", "on")
    env.devices["dev1"] = _make_device("dev1")
    entry = env.make_entry({CONF_EXPOSED_ENTITIES: ["light.a"]})

    with caplog.at_level(logging.WARNING, logger=entity_registry_module.__name__):
        SberEntityLoader(env.hass, entry).load()

    assert not [rec for rec in caplog.records if "may cause duplicates" in rec.getMessage()]


# ---------------------------------------------------------------------------
# YAML overrides (_apply_yaml_overrides + sber_type routing)
# ---------------------------------------------------------------------------


def test_yaml_overrides_applied_to_entity(env) -> None:
    env.entries["switch.plug"] = _make_reg_entry("switch.plug")
    env.states["switch.plug"] = _FakeState("switch.plug", "on")
    env.set_yaml(
        {
            "switch.plug": EntityCustomConfig(
                sber_type="socket",
                sber_name="Розетка",
                sber_nicknames=["Розетка кухня"],
                sber_groups=["Кухня"],
                sber_features_add=["extra_feature"],
                sber_features_remove=["on_off"],
            )
        }
    )
    entry = env.make_entry({CONF_EXPOSED_ENTITIES: ["switch.plug"]})

    result = SberEntityLoader(env.hass, entry).load()

    ent = result.entities["switch.plug"]
    assert ent.category == "socket"  # yaml sber_type routed the class choice
    assert ent.name == "Розетка"
    assert ent.nicknames == ["Розетка кухня"]
    assert ent.groups == ["Кухня"]
    assert ent.extra_features == ["extra_feature"]
    assert ent.removed_features == ["on_off"]


def test_yaml_parent_and_partner_meta_reach_sber_payload(env) -> None:
    """``sber_parent_id`` / ``sber_partner_meta`` end up in the Sber descriptor."""
    _add_light(env, "light.child")
    env.set_yaml(
        {
            "light.child": EntityCustomConfig(
                sber_parent_id="light.parent",
                sber_partner_meta={"vendor": "acme"},
            )
        }
    )
    entry = env.make_entry({CONF_EXPOSED_ENTITIES: ["light.child"]})

    result = SberEntityLoader(env.hass, entry).load()

    ent = result.entities["light.child"]
    assert ent.parent_entity_id == "light.parent"
    assert ent.partner_meta == {"vendor": "acme"}
    descriptor = ent.to_sber_state()
    assert descriptor["parent_id"] == "light.parent"
    assert descriptor["partner_meta"] == {"vendor": "acme"}


def test_options_type_override_beats_yaml_sber_type(env) -> None:
    env.entries["switch.plug"] = _make_reg_entry("switch.plug")
    env.states["switch.plug"] = _FakeState("switch.plug", "on")
    env.set_yaml({"switch.plug": EntityCustomConfig(sber_type="socket")})
    entry = env.make_entry(
        {
            CONF_EXPOSED_ENTITIES: ["switch.plug"],
            CONF_ENTITY_TYPE_OVERRIDES: {"switch.plug": "relay"},
        }
    )

    result = SberEntityLoader(env.hass, entry).load()

    assert result.entities["switch.plug"].category == "relay"


# ---------------------------------------------------------------------------
# Room overrides + redefinitions merge / prune
# ---------------------------------------------------------------------------


def test_room_override_priority_and_prune(env) -> None:
    for eid in ("light.a", "light.b", "light.c"):
        _add_light(env, eid)
    env.set_yaml(
        {
            "light.a": EntityCustomConfig(sber_room="Кухня"),
            "light.b": EntityCustomConfig(sber_room="Кухня"),
            "light.c": EntityCustomConfig(sber_room="Кухня"),
        }
    )
    entry = env.make_entry({CONF_EXPOSED_ENTITIES: ["light.a", "light.b", "light.c"]})
    existing = {
        "light.b": {"room": "Гостиная"},  # explicit user room must win over YAML
        "light.c": {"name": "Лампа"},  # partial redef gets YAML room merged in
        "light.gone": {"room": "Чулан"},  # not exposed → pruned
    }

    result = SberEntityLoader(env.hass, entry).load(existing_redefinitions=existing)

    assert result.redefinitions["light.a"] == {"room": "Кухня"}
    assert result.redefinitions["light.b"] == {"room": "Гостиная"}
    assert result.redefinitions["light.c"] == {"name": "Лампа", "room": "Кухня"}
    assert "light.gone" not in result.redefinitions


def test_persisted_redefinitions_win_over_in_memory(env) -> None:
    _add_light(env, "light.a")
    entry = env.make_entry(
        {
            CONF_EXPOSED_ENTITIES: ["light.a"],
            "redefinitions": {"light.a": {"name": "saved"}},
        }
    )

    result = SberEntityLoader(env.hass, entry).load(existing_redefinitions={"light.a": {"name": "memory"}})

    assert result.redefinitions["light.a"] == {"name": "saved"}


# ---------------------------------------------------------------------------
# Repeat load / duplication
# ---------------------------------------------------------------------------


def test_duplicate_exposed_ids_built_once(env) -> None:
    """A duplicated exposed id must not build the entity twice.

    Asserting only on ``result.entities`` would be a tautology (a dict
    dedupes keys by itself), so this counts the actual construction work —
    the real cost the ``dict.fromkeys`` pass exists to avoid.  The factory
    is wrapped, not stubbed: real Sber entities are still produced.
    """
    _add_light(env, "light.a")
    entry = env.make_entry({CONF_EXPOSED_ENTITIES: ["light.a", "light.a", "light.a"]})

    with patch(
        "custom_components.sber_mqtt_bridge.entity_registry.create_sber_entity",
        wraps=entity_registry_module.create_sber_entity,
    ) as factory:
        result = SberEntityLoader(env.hass, entry).load()

    assert factory.call_count == 1
    assert result.enabled_entity_ids == ["light.a"]
    assert result.entities["light.a"].is_filled_by_state is True


def test_redefinitions_of_a_broken_entity_survive_the_load(env) -> None:
    """Deliberate policy: a failed load must NOT erase user redefinitions.

    Pruning against successfully loaded entities would destroy the user's
    room/name assignment the first time a lamp reports a degenerate CCT
    range — the prune therefore runs against the *exposed* option list.
    """
    _add_light(env, "light.broken", attrs=_DEGENERATE_CCT_ATTRS)
    _add_light(env, "light.ok")
    entry = env.make_entry({CONF_EXPOSED_ENTITIES: ["light.broken", "light.ok"]})
    existing = {
        "light.broken": {"room": "Спальня", "name": "Ночник"},
        "light.removed": {"room": "Чулан"},
    }

    result = SberEntityLoader(env.hass, entry).load(existing_redefinitions=existing)

    assert "light.broken" not in result.entities
    assert result.redefinitions["light.broken"] == {"room": "Спальня", "name": "Ночник"}
    # Entities dropped from the exposed list are still pruned.
    assert "light.removed" not in result.redefinitions


def test_repeat_load_returns_fresh_equivalent_result(env) -> None:
    """Second load() produces the same set without accumulating state."""
    _add_temp_sensor(env, "sensor.temp")
    env.states["sensor.hum"] = _FakeState("sensor.hum", "55")
    entry = env.make_entry(
        {
            CONF_EXPOSED_ENTITIES: ["sensor.temp"],
            CONF_ENTITY_LINKS: {"sensor.temp": {"humidity": "sensor.hum"}},
        }
    )
    loader = SberEntityLoader(env.hass, entry)

    first = loader.load()
    second = loader.load(existing_redefinitions=first.redefinitions)

    assert list(second.entities) == ["sensor.temp"]
    assert second.enabled_entity_ids == ["sensor.temp"]
    assert second.entity_links == first.entity_links
    assert second.linked_reverse == first.linked_reverse
    # Fresh objects each pass (swap-on-replace contract), fully re-filled.
    assert second.entities["sensor.temp"] is not first.entities["sensor.temp"]
    assert second.entities["sensor.temp"]._linked_humidity == 55
