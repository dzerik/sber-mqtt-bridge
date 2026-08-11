"""End-to-end WebSocket API tests that run through the *whole* HA stack.

Every other WS test in this suite calls handlers directly (often via
``handler.__wrapped__``), which silently strips two production layers:

* the voluptuous schema attached by
  ``@websocket_api.websocket_command`` — HA validates the message
  *before* the handler ever sees it, so a broken or missing schema is
  invisible to a direct call;
* the ``require_admin`` wrapper applied at the single registration
  choke point in :func:`async_setup_websocket_api`.

Here nothing is stripped: a real ``hass`` runs a real
``websocket_api`` component, the integration is set up through
``hass.config_entries.async_setup`` (real ``SberBridge``, real entity
loading, real ``runtime_data``), and messages travel over a real
WebSocket connection created by ``hass_ws_client``.  Only the outermost
boundary — the aiomqtt reconnect loop — is neutralised, and the
transport is swapped for an in-memory recorder when a test needs to
observe publishes.

Three properties are asserted for the key command of every WS module
(``status``, ``devices_grouped``, ``entities``, ``links``, ``settings``,
``io_export``, ``raw``, ``log``, ``replay``, ``traces``, ``diffs``,
``validation``, ``diagnose`` — i.e. all of them):

a. a valid payload produces a successful result of the expected shape;
b. an invalid payload is rejected with ``invalid_format`` **and leaves
   no trace** — no option writes, no MQTT publishes, no HA service
   calls, no message-log entries;
c. a non-admin user gets ``unauthorized`` with the same absence of
   side effects.

Commands that mutate the config entry are additionally checked *past*
the answer frame: the entry must still be ``LOADED`` and the freshly
built bridge must actually reflect the change, so dropping the
``async_reload`` (options written, running bridge stale) fails here.

Plus two anti-regress sweeps over the *registered* command table, so a
newly added command that forgets its schema or its admin guard fails
the suite instead of shipping.
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator, Callable
from typing import Any

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_mock_service

import custom_components.sber_mqtt_bridge.websocket_api as ws_pkg
from custom_components.sber_mqtt_bridge.const import (
    CONF_ENTITY_LINKS,
    CONF_ENTITY_TYPE_OVERRIDES,
    CONF_EXPOSED_ENTITIES,
    CONF_HUB_AUTO_PARENT,
    CONF_SBER_BROKER,
    CONF_SBER_LOGIN,
    CONF_SBER_PASSWORD,
    CONF_SBER_PORT,
    CONF_SBER_VERIFY_SSL,
    DOMAIN,
    SBER_TOPIC_PREFIX,
    SETTINGS_DEFAULTS,
)
from custom_components.sber_mqtt_bridge.sber_bridge import SberBridge

WS_REGISTRY_KEY = "websocket_api"
"""``hass.data`` key under which HA stores ``{command: (handler, schema)}``."""

SBER_PREFIX = "sber_mqtt_bridge/"
"""Namespace prefix of every command owned by this integration."""

LAMP = "light.lamp"
LAMP_TEMP = "sensor.lamp_temp"
PUMP = "switch.pump"
LAMP_DEVICE_NAME = "Lamp device"
PUMP_DEVICE_NAME = "Pump device"


# ---------------------------------------------------------------------------
# Fakes / fixtures
# ---------------------------------------------------------------------------


class RecordingTransport:
    """In-memory stand-in for a connected ``aiomqtt.Client``.

    Only ``publish`` is exercised: the reconnect loop is disabled, so the
    bridge never subscribes or consumes through this object.
    """

    def __init__(self) -> None:
        """Start with an empty publish journal."""
        self.published: list[tuple[str, str | bytes]] = []

    async def publish(self, topic: str, payload: str | bytes) -> None:
        """Record an outbound publish instead of hitting the network."""
        self.published.append((topic, payload))


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: Any) -> None:
    """Let HA load ``custom_components/sber_mqtt_bridge`` in every test."""
    return


@pytest.fixture(autouse=True)
def _no_mqtt_reconnect_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    """Neutralise the endless MQTT reconnect task.

    Everything above the transport (entity loading, WS registration,
    option writes, dispatcher) still runs for real; only the network
    boundary is removed so ``async_block_till_done`` terminates.
    """

    async def _noop(self: SberBridge) -> None:
        return

    monkeypatch.setattr(SberBridge, "_mqtt_connection_loop", _noop)


def _register_devices(hass: HomeAssistant) -> None:
    """Create two HA devices with the entities the wizard tests need."""
    owner = MockConfigEntry(domain="test_devices")
    owner.add_to_hass(hass)
    device_reg = dr.async_get(hass)
    entity_reg = er.async_get(hass)

    lamp_device = device_reg.async_get_or_create(
        config_entry_id=owner.entry_id,
        identifiers={("test_devices", "lamp")},
        name=LAMP_DEVICE_NAME,
    )
    pump_device = device_reg.async_get_or_create(
        config_entry_id=owner.entry_id,
        identifiers={("test_devices", "pump")},
        name=PUMP_DEVICE_NAME,
    )

    entity_reg.async_get_or_create(
        "light",
        "test_devices",
        "lamp-uid",
        suggested_object_id="lamp",
        config_entry=owner,
        device_id=lamp_device.id,
    )
    entity_reg.async_get_or_create(
        "sensor",
        "test_devices",
        "lamp-temp-uid",
        suggested_object_id="lamp_temp",
        config_entry=owner,
        device_id=lamp_device.id,
        original_device_class="temperature",
    )
    entity_reg.async_get_or_create(
        "switch",
        "test_devices",
        "pump-uid",
        suggested_object_id="pump",
        config_entry=owner,
        device_id=pump_device.id,
    )

    hass.states.async_set(LAMP, "on", {"friendly_name": "Lamp", "supported_color_modes": ["brightness"]})
    hass.states.async_set(LAMP_TEMP, "21.5", {"device_class": "temperature", "unit_of_measurement": "°C"})
    hass.states.async_set(PUMP, "off", {"friendly_name": "Pump"})


@pytest.fixture
async def entry(hass: HomeAssistant) -> AsyncGenerator[MockConfigEntry]:
    """Set up the integration for real and yield its config entry."""
    assert await async_setup_component(hass, "frontend", {})
    _register_devices(hass)

    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_SBER_LOGIN: "test",
            CONF_SBER_PASSWORD: "pass",
            CONF_SBER_BROKER: "broker.test",
            CONF_SBER_PORT: 8883,
            CONF_SBER_VERIFY_SSL: False,
        },
        options={CONF_EXPOSED_ENTITIES: [LAMP]},
        version=3,
    )
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    yield config_entry

    if config_entry.state is ConfigEntryState.LOADED:
        await hass.config_entries.async_unload(config_entry.entry_id)
        await hass.async_block_till_done()


@pytest.fixture
def transport(entry: MockConfigEntry) -> RecordingTransport:
    """Attach a recording transport and mark the bridge as connected."""
    recorder = RecordingTransport()
    service = entry.runtime_data.bridge._mqtt_service
    service._client = recorder
    service._connected = True
    return recorder


@pytest.fixture
async def admin(hass: HomeAssistant, hass_ws_client: Any, entry: MockConfigEntry) -> Any:
    """WebSocket client authenticated as an admin user."""
    return await hass_ws_client(hass)


@pytest.fixture
async def guest(
    hass: HomeAssistant,
    hass_ws_client: Any,
    hass_read_only_access_token: str,
    entry: MockConfigEntry,
) -> Any:
    """WebSocket client authenticated as a *non-admin* user."""
    return await hass_ws_client(hass, hass_read_only_access_token)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def call(client: Any, command: str, **payload: Any) -> dict[str, Any]:
    """Send one command over the socket and return its ``result`` frame.

    Subscription commands keep pushing ``event`` frames onto the same
    socket; those are skipped so a sweep over every command stays in
    sync with the responses it is reading.
    """
    await client.send_json_auto_id({"type": f"{SBER_PREFIX}{command}", **payload})
    while True:
        message = await client.receive_json()
        if message["type"] == "result":
            return message


async def ok(client: Any, command: str, **payload: Any) -> Any:
    """Send a command and assert it succeeded; return ``result``."""
    response = await call(client, command, **payload)
    assert response["success"], f"{command} failed: {response.get('error')}"
    return response["result"]


def registered_commands(hass: HomeAssistant) -> dict[str, tuple[Any, Any]]:
    """Return ``{command: (handler, schema)}`` for this integration only."""
    handlers = hass.data[WS_REGISTRY_KEY]
    return {cmd: pair for cmd, pair in handlers.items() if cmd.startswith(SBER_PREFIX)}


class SideEffects:
    """Snapshot of everything a WS command is able to mutate.

    Comparing two snapshots is how "the handler never ran" is proven:
    option writes, MQTT publishes, DevTools log entries and HA service
    calls are the complete set of observable effects of these commands.
    """

    def __init__(
        self,
        config_entry: MockConfigEntry,
        recorder: RecordingTransport,
        service_calls: list[ServiceCall],
    ) -> None:
        """Capture the current state of all four effect channels."""
        bridge = config_entry.runtime_data.bridge
        self.options = json.dumps(dict(config_entry.options), sort_keys=True, default=str)
        self.published = list(recorder.published)
        self.log_size = len(bridge.message_log)
        self.service_calls = len(service_calls)
        self.entity_ids = list(bridge.enabled_entity_ids)

    def assert_same_as(self, other: SideEffects, context: str) -> None:
        """Fail with a precise message if any effect channel differs."""
        assert self.options == other.options, f"{context}: entry.options mutated"
        assert self.published == other.published, f"{context}: MQTT publish happened"
        assert self.log_size == other.log_size, f"{context}: message log grew"
        assert self.service_calls == other.service_calls, f"{context}: HA service was called"
        assert self.entity_ids == other.entity_ids, f"{context}: exposed entity set changed"


@pytest.fixture
def snapshot(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    transport: RecordingTransport,
) -> Callable[[], SideEffects]:
    """Return a callable producing a fresh :class:`SideEffects` snapshot."""
    light_calls = async_mock_service(hass, "light", "turn_on")
    switch_calls = async_mock_service(hass, "switch", "turn_on")

    def _take() -> SideEffects:
        return SideEffects(entry, transport, [*light_calls, *switch_calls])

    return _take


def _command_payload() -> str:
    """Return a Sber ``commands`` payload that switches the lamp on."""
    return json.dumps(
        {
            "devices": {
                LAMP: {
                    "states": [
                        {"key": "on_off", "value": {"type": "BOOL", "bool_value": True}},
                    ],
                }
            }
        }
    )


# ---------------------------------------------------------------------------
# Reload safety — the defect this used to pin is now fixed in production
# ---------------------------------------------------------------------------


async def test_reload_triggering_command_keeps_entry_loaded(
    hass: HomeAssistant,
    admin: Any,
    entry: MockConfigEntry,
) -> None:
    """A panel action that reloads the entry must not brick the integration.

    Runs *without* the de-duplicating static-path patch, i.e. against
    production ``async_setup_entry`` exactly as a user's HA runs it.
    Every mutating panel command (``add_entities``, ``remove_entities``,
    ``set_override``, ``clear_all``, ``set_entity_links``, ``import``)
    goes through ``hass.config_entries.async_reload``, so if the reload
    cannot succeed the panel dies after the first click.
    """
    await ok(admin, "set_override", entity_id=LAMP, category="led_strip")
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED, (
        f"entry left in {entry.state} after a reload-triggering command: {entry.reason}"
    )
    assert (await ok(admin, "status"))["entities_count"] == 1


# ---------------------------------------------------------------------------
# (a) Valid calls — one per WS module, real schema + real admin gate
# ---------------------------------------------------------------------------


class TestStatusModule:
    """``status.py`` — status / devices / device_detail."""

    async def test_status_reports_the_full_contract(self, admin: Any, entry: MockConfigEntry) -> None:
        """Every field the panel renders is pinned to the known fixture state.

        The bridge here is *not* connected (no ``transport`` fixture) and
        the single exposed entity was never acknowledged, so all values
        are exactly determined — no ``in {...}`` escape hatches.
        """
        from custom_components.sber_mqtt_bridge.sber_protocol import VERSION

        result = await ok(admin, "status")

        assert result["connected"] is False
        assert result["phase"] == "connecting"
        assert result["version"] == VERSION
        assert result["entities_count"] == 1
        assert result["unacknowledged"] == [LAMP]
        assert result["stats"]["acknowledged_entities"] == []
        assert result["hub"] == {
            "id": "root",
            "name": "Home Assistant Bridge",
            "home": "test home",
            "room": "test home",
            "version": VERSION,
            "is_online": False,
            "children_count": 1,
            "auto_parent_id": SETTINGS_DEFAULTS[CONF_HUB_AUTO_PARENT],
        }

    async def test_status_health_is_unhealthy_while_disconnected(self, admin: Any) -> None:
        """No MQTT link ⇒ ``unhealthy``, whatever else is going on."""
        health = (await ok(admin, "status"))["health"]

        assert health["score"] == "unhealthy"
        assert "disconnected" in health["issues"]
        assert "1 entities unacknowledged" in health["issues"]

    async def test_status_health_is_degraded_when_connected_but_unacknowledged(
        self, admin: Any, transport: RecordingTransport
    ) -> None:
        """Connected with a device Sber never acked ⇒ ``degraded``."""
        health = (await ok(admin, "status"))["health"]

        assert health["score"] == "degraded"
        assert health["issues"] == ["1 entities unacknowledged"]

    async def test_status_health_is_healthy_when_connected_and_acknowledged(
        self, admin: Any, entry: MockConfigEntry, transport: RecordingTransport
    ) -> None:
        """Connected, everything acked, no errors ⇒ ``healthy`` with no issues."""
        entry.runtime_data.bridge._stats.acknowledged_entities.add(LAMP)

        health = (await ok(admin, "status"))["health"]

        assert health["score"] == "healthy"
        assert health["issues"] == []

    async def test_status_health_degrades_on_sber_errors(
        self, admin: Any, entry: MockConfigEntry, transport: RecordingTransport
    ) -> None:
        """A connected, fully acked bridge still degrades on Sber errors."""
        bridge = entry.runtime_data.bridge
        bridge._stats.acknowledged_entities.add(LAMP)
        bridge._stats.errors_from_sber = 2
        bridge._stats.publish_errors = 3

        health = (await ok(admin, "status"))["health"]

        assert health["score"] == "degraded"
        assert health["issues"] == ["2 Sber error(s)", "3 publish error(s)"]

    async def test_devices_lists_the_exposed_entity(self, admin: Any) -> None:
        result = await ok(admin, "devices")
        assert [device["entity_id"] for device in result["devices"]] == [LAMP]
        assert result["total"] == 1

    async def test_device_detail_returns_sber_model(self, admin: Any) -> None:
        result = await ok(admin, "device_detail", entity_id=LAMP)
        assert result["entity_id"] == LAMP
        assert result["sber_category"] == "light"
        assert result["ha_state"] == "on"
        assert result["device_info"]["name"] == LAMP_DEVICE_NAME

    async def test_device_detail_unknown_entity_is_not_found(self, admin: Any) -> None:
        """Handler-level error (not schema): well-formed but unknown entity."""
        response = await call(admin, "device_detail", entity_id="light.ghost")
        assert response["success"] is False
        assert response["error"]["code"] == "not_found"


class TestDevicesGroupedModule:
    """``devices_grouped.py`` — the add-device wizard."""

    async def test_list_categories_contains_light(self, admin: Any) -> None:
        result = await ok(admin, "list_categories")
        assert "light" in {category["id"] for category in result["categories"]}

    async def test_list_devices_for_category(self, admin: Any) -> None:
        result = await ok(admin, "list_devices_for_category", category="light")
        assert result["category"] == "light"
        assert result["summary"]["total"] == 1
        device = result["devices"][0]
        assert device["primary"]["entity_id"] == LAMP
        assert device["already_exposed"] is True

    async def test_add_ha_device_persists_options(
        self, hass: HomeAssistant, admin: Any, entry: MockConfigEntry
    ) -> None:
        """Options are written *and* hot-applied to the running bridge.

        ``ws_add_ha_device`` deliberately avoids a full entry reload (it
        would tear the sidebar panel down mid-wizard) and calls
        ``_hot_reload`` instead — so the same "did it actually take
        effect?" question applies, just against the same bridge object.
        """
        bridge_before = entry.runtime_data.bridge

        result = await ok(
            admin,
            "add_ha_device",
            device_id=next(
                device.id for device in dr.async_get(hass).devices.values() if device.name == PUMP_DEVICE_NAME
            ),
            primary_entity_id=PUMP,
            category="relay",
            name="Насос",
        )
        await hass.async_block_till_done()

        assert result["success"] is True
        assert PUMP in entry.options[CONF_EXPOSED_ENTITIES]
        assert entry.options[CONF_ENTITY_TYPE_OVERRIDES][PUMP] == "relay"
        assert entry.options["redefinitions"][PUMP]["name"] == "Насос"

        assert entry.state is ConfigEntryState.LOADED
        bridge = entry.runtime_data.bridge
        assert bridge is bridge_before, "wizard must hot-reload, not tear the entry down"
        assert bridge.enabled_entity_ids == [LAMP, PUMP], "hot reload skipped — bridge unaware of the new device"
        assert bridge.entities[PUMP].category == "relay"
        # The redefined display name is kept in the bridge's redefinition
        # store (the publisher applies it when serialising for Sber), so
        # this is where a lost hot-reload of redefinitions shows up.
        assert bridge.redefinitions[PUMP]["name"] == "Насос"

    async def test_suggest_links_offers_the_same_device_sibling(self, hass: HomeAssistant, admin: Any) -> None:
        """The lamp's sibling sensor is offered with its resolved role.

        The sibling is a *battery* sensor because that is a role
        ``light`` actually accepts (``SENSOR_LINK_ROLES``), so both the
        candidate list and ``allowed_roles`` are fully determined.
        """
        entity_reg = er.async_get(hass)
        battery = entity_reg.async_get_or_create(
            "sensor",
            "test_devices",
            "lamp-battery-uid",
            suggested_object_id="lamp_battery",
            device_id=entity_reg.async_get(LAMP).device_id,
            original_device_class="battery",
        ).entity_id

        result = await ok(admin, "suggest_links", entity_id=LAMP)

        assert result["category"] == "light"
        assert "battery" in result["allowed_roles"]
        offered = {c["entity_id"]: c for c in result["candidates"]}
        assert battery in offered, result["candidates"]
        assert offered[battery]["suggested_role"] == "battery"
        assert offered[battery]["same_device"] is True
        assert offered[battery]["currently_linked"] is False

    async def test_suggest_links_for_a_device_less_entity_is_empty(self, hass: HomeAssistant, admin: Any) -> None:
        """An entity with no HA device has nothing to suggest — and no crash."""
        hass.states.async_set("light.orphan", "on")

        result = await ok(admin, "suggest_links", entity_id="light.orphan")

        assert result == {"candidates": [], "allowed_roles": [], "category": ""}


class TestEntitiesModule:
    """``entities.py`` — add / remove / override / clear.

    Each test asserts the *running* bridge as well as ``entry.options``:
    the options are written before ``async_reload``, so a handler that
    persisted the change but skipped the reload would answer
    ``success`` while the bridge kept publishing the old device set.
    """

    async def test_add_entities_extends_exposed_list(
        self, hass: HomeAssistant, admin: Any, entry: MockConfigEntry
    ) -> None:
        result = await ok(admin, "add_entities", entity_ids=[PUMP])
        await hass.async_block_till_done()

        assert result == {"added": [PUMP], "total": 2}
        assert entry.options[CONF_EXPOSED_ENTITIES] == [LAMP, PUMP]
        assert entry.state is ConfigEntryState.LOADED
        bridge = entry.runtime_data.bridge
        assert bridge.enabled_entity_ids == [LAMP, PUMP], "reload skipped — bridge still exposes the old set"
        assert set(bridge.entities) == {LAMP, PUMP}

    async def test_remove_entities_shrinks_exposed_list(
        self, hass: HomeAssistant, admin: Any, entry: MockConfigEntry
    ) -> None:
        result = await ok(admin, "remove_entities", entity_ids=[LAMP])
        await hass.async_block_till_done()

        assert result == {"removed": 1, "total": 0}
        assert entry.options[CONF_EXPOSED_ENTITIES] == []
        assert entry.state is ConfigEntryState.LOADED
        assert entry.runtime_data.bridge.enabled_entity_ids == []
        assert entry.runtime_data.bridge.entities == {}

    async def test_set_override_writes_and_auto_clears(
        self, hass: HomeAssistant, admin: Any, entry: MockConfigEntry
    ) -> None:
        await ok(admin, "set_override", entity_id=LAMP, category="led_strip")
        await hass.async_block_till_done()
        assert entry.options[CONF_ENTITY_TYPE_OVERRIDES][LAMP] == "led_strip"
        assert entry.state is ConfigEntryState.LOADED
        assert entry.runtime_data.bridge.entities[LAMP].category == "led_strip"

        await ok(admin, "set_override", entity_id=LAMP, category="auto")
        await hass.async_block_till_done()
        assert LAMP not in entry.options[CONF_ENTITY_TYPE_OVERRIDES]
        assert entry.state is ConfigEntryState.LOADED
        assert entry.runtime_data.bridge.entities[LAMP].category == "light"

    async def test_clear_all_empties_everything(self, hass: HomeAssistant, admin: Any, entry: MockConfigEntry) -> None:
        result = await ok(admin, "clear_all")
        await hass.async_block_till_done()

        assert result == {"removed": 1}
        assert entry.options[CONF_EXPOSED_ENTITIES] == []
        assert entry.state is ConfigEntryState.LOADED
        assert entry.runtime_data.bridge.enabled_entity_ids == []


class TestLinksModule:
    """``links.py`` — manual and automatic sensor linking."""

    async def test_set_entity_links_persists_role_mapping(
        self, hass: HomeAssistant, admin: Any, entry: MockConfigEntry
    ) -> None:
        result = await ok(admin, "set_entity_links", entity_id=LAMP, links={"temperature": LAMP_TEMP})
        await hass.async_block_till_done()

        assert result["success"] is True
        assert entry.options[CONF_ENTITY_LINKS][LAMP] == {"temperature": LAMP_TEMP}
        assert entry.state is ConfigEntryState.LOADED
        bridge = entry.runtime_data.bridge
        assert bridge.entity_links[LAMP] == {"temperature": LAMP_TEMP}, "reload skipped — bridge has no link"
        assert LAMP_TEMP in bridge.linked_entity_ids

    async def test_set_entity_links_rejects_unexposed_primary(self, admin: Any) -> None:
        response = await call(admin, "set_entity_links", entity_id=PUMP, links={"temperature": LAMP_TEMP})
        assert response["error"]["code"] == "not_exposed"

    async def test_auto_link_all_ignores_roles_the_category_does_not_accept(
        self, hass: HomeAssistant, admin: Any, entry: MockConfigEntry
    ) -> None:
        """``sensor.lamp_temp`` shares the device but ``light`` has no temp role.

        ``LightEntity.LINKABLE_ROLES`` is ``SENSOR_LINK_ROLES`` (battery /
        battery_low / signal), so a same-device temperature sensor must
        *not* be linked.  Exact numbers, not ``isinstance(int)``: a
        matcher regression that links "any sibling sensor" fails here.
        """
        result = await ok(admin, "auto_link_all")
        await hass.async_block_till_done()

        assert result == {"linked_count": 0, "devices_affected": 0}
        assert entry.options.get(CONF_ENTITY_LINKS, {}) == {}

    async def test_auto_link_all_links_an_accepted_role_and_is_idempotent(
        self, hass: HomeAssistant, admin: Any, entry: MockConfigEntry
    ) -> None:
        """A battery sibling *is* an accepted role — linked once, then never again."""
        entity_reg = er.async_get(hass)
        lamp_entry = entity_reg.async_get(LAMP)
        battery = entity_reg.async_get_or_create(
            "sensor",
            "test_devices",
            "lamp-battery-uid",
            suggested_object_id="lamp_battery",
            device_id=lamp_entry.device_id,
            original_device_class="battery",
        ).entity_id

        result = await ok(admin, "auto_link_all")
        await hass.async_block_till_done()

        assert result == {"linked_count": 1, "devices_affected": 1}
        assert entry.options[CONF_ENTITY_LINKS] == {LAMP: {"battery": battery}}
        assert entry.state is ConfigEntryState.LOADED
        assert entry.runtime_data.bridge.entity_links == {LAMP: {"battery": battery}}

        assert await ok(admin, "auto_link_all") == {"linked_count": 0, "devices_affected": 1}


class TestSettingsModule:
    """``settings.py`` — get / update."""

    async def test_get_settings_exposes_defaults(self, admin: Any) -> None:
        result = await ok(admin, "get_settings")
        assert "debounce_delay" in result["settings"]
        assert result["defaults"]["debounce_delay"] == pytest.approx(result["settings"]["debounce_delay"])

    async def test_update_settings_persists_valid_values(self, admin: Any, entry: MockConfigEntry) -> None:
        result = await ok(admin, "update_settings", settings={"debounce_delay": 0.75})
        assert result == {"success": True}
        assert entry.options["debounce_delay"] == pytest.approx(0.75)

    async def test_update_settings_rejects_poisoned_value(self, admin: Any, entry: MockConfigEntry) -> None:
        """Type-valid ``dict`` passes the WS schema; the value schema stops it."""
        response = await call(admin, "update_settings", settings={"debounce_delay": "abc"})
        assert response["error"]["code"] == "invalid_settings"
        assert "debounce_delay" not in entry.options


class TestIoExportModule:
    """``io_export.py`` — export / import."""

    async def test_export_round_trips_through_import(
        self, hass: HomeAssistant, admin: Any, entry: MockConfigEntry
    ) -> None:
        exported = await ok(admin, "export")
        assert exported["exposed_entities"] == [LAMP]

        exported["exposed_entities"] = [LAMP, PUMP]
        result = await ok(admin, "import", config=exported)
        await hass.async_block_till_done()

        assert result == {"success": True}
        assert entry.options[CONF_EXPOSED_ENTITIES] == [LAMP, PUMP]
        assert entry.state is ConfigEntryState.LOADED
        assert entry.runtime_data.bridge.enabled_entity_ids == [LAMP, PUMP], "reload skipped — import not applied"

    async def test_import_rejects_structurally_broken_config(self, admin: Any, entry: MockConfigEntry) -> None:
        response = await call(admin, "import", config={"entity_links": [LAMP]})
        assert response["error"]["code"] == "invalid_config"
        assert entry.options[CONF_EXPOSED_ENTITIES] == [LAMP]


class TestRawModule:
    """``raw.py`` — payload inspection + direct publish."""

    async def test_raw_config_returns_parsable_sber_payload(self, admin: Any) -> None:
        result = await ok(admin, "raw_config")
        payload = json.loads(result["payload"])
        assert any(device["id"] == LAMP for device in payload["devices"])

    @pytest.mark.parametrize("auto_parent", [True, False])
    async def test_raw_config_preview_matches_what_is_published(
        self,
        hass: HomeAssistant,
        admin: Any,
        entry: MockConfigEntry,
        transport: RecordingTransport,
        auto_parent: bool,
    ) -> None:
        """The DevTools preview must be byte-identical to the published config.

        Regression guard for issue #44: ``ws_raw_config`` called the payload
        builder without ``auto_parent_id`` / ``default_home`` / ``default_room``
        and silently inherited the builder's defaults, so the preview always
        showed ``parent_id: "root"`` however the user set the toggle.  The
        reporter concluded the setting "is not applied to the config" — the
        publish was in fact correct, only the preview lied.

        Parametrised over both toggle states so a preview that hardcodes
        either answer fails.
        """
        hass.config_entries.async_update_entry(entry, options={**entry.options, CONF_HUB_AUTO_PARENT: auto_parent})
        await hass.async_block_till_done()

        preview = json.loads((await ok(admin, "raw_config"))["payload"])

        transport.published.clear()
        await ok(admin, "republish")
        await hass.async_block_till_done()
        config_topic = f"{SBER_TOPIC_PREFIX}/test/up/config"
        sent = [json.loads(body) for topic, body in transport.published if topic == config_topic]
        assert sent, "republish did not publish a config payload"

        assert preview == sent[-1], "DevTools preview diverged from the published config"

        lamp = next(d for d in preview["devices"] if d["id"] == LAMP)
        assert ("parent_id" in lamp) is auto_parent, (
            f"parent_id must follow hub_auto_parent_id={auto_parent}, got {lamp.get('parent_id', 'absent')!r}"
        )

    async def test_raw_states_returns_parsable_payload(self, admin: Any) -> None:
        result = await ok(admin, "raw_states")
        assert LAMP in json.loads(result["payload"])["devices"]

    async def test_send_raw_config_publishes_to_the_broker(self, admin: Any, transport: RecordingTransport) -> None:
        result = await ok(admin, "send_raw_config", payload='{"devices": []}')
        assert result == {"success": True}
        assert [topic for topic, _ in transport.published] == [f"{SBER_TOPIC_PREFIX}/test/up/config"]

    async def test_send_raw_state_rejects_non_json_before_publishing(
        self, admin: Any, transport: RecordingTransport
    ) -> None:
        response = await call(admin, "send_raw_state", payload="definitely not json")
        assert response["error"]["code"] == "invalid_json"
        assert transport.published == []


class TestLogModule:
    """``log.py`` — message log + live subscription."""

    async def test_message_log_and_clear(self, admin: Any, transport: RecordingTransport) -> None:
        await ok(admin, "send_raw_config", payload='{"devices": []}')
        messages = (await ok(admin, "message_log"))["messages"]
        assert [message["direction"] for message in messages] == ["out"]

        assert await ok(admin, "clear_message_log") == {"success": True}
        assert (await ok(admin, "message_log"))["messages"] == []

    async def test_subscribe_messages_streams_new_traffic(self, admin: Any, transport: RecordingTransport) -> None:
        """The subscription pushes a snapshot first, then live traffic."""
        await admin.send_json_auto_id({"type": f"{SBER_PREFIX}subscribe_messages"})
        subscribed = await admin.receive_json()
        assert subscribed["type"] == "result"
        assert subscribed["success"] is True

        snapshot_event = await admin.receive_json()
        assert snapshot_event["type"] == "event"
        assert snapshot_event["event"]["snapshot"] == []

        await admin.send_json_auto_id({"type": f"{SBER_PREFIX}send_raw_config", "payload": '{"devices": []}'})
        frames = [await admin.receive_json() for _ in range(2)]
        streamed = [frame for frame in frames if frame["type"] == "event"]
        assert [frame["event"]["message"]["direction"] for frame in streamed] == ["out"]


class TestReplayModule:
    """``replay.py`` — inject a Sber command as if the broker sent it."""

    async def test_inject_dispatches_a_real_ha_service_call(self, hass: HomeAssistant, admin: Any) -> None:
        calls = async_mock_service(hass, "light", "turn_on")
        result = await ok(admin, "inject_sber_message", topic="commands", payload=_command_payload())
        await hass.async_block_till_done()

        assert result["handled"] is True
        assert result["topic"].endswith("/down/commands")
        assert [c.data["entity_id"] for c in calls] == [LAMP]

    async def test_inject_unknown_topic_is_reported_unhandled(self, hass: HomeAssistant, admin: Any) -> None:
        calls = async_mock_service(hass, "light", "turn_on")
        result = await ok(admin, "inject_sber_message", topic="typo", payload="{}")
        await hass.async_block_till_done()

        assert result["handled"] is False
        assert calls == []


class TestTracesModule:
    """``traces.py`` — the correlation timeline behind the DevTools tab."""

    async def test_traces_capture_an_injected_command(self, hass: HomeAssistant, admin: Any) -> None:
        """A real command produces a trace that ``traces`` / ``trace`` return."""
        async_mock_service(hass, "light", "turn_on")
        assert await ok(admin, "traces") == {"traces": []}

        await ok(admin, "inject_sber_message", topic="commands", payload=_command_payload())
        await hass.async_block_till_done()

        traces = (await ok(admin, "traces"))["traces"]
        assert len(traces) == 1, traces
        assert LAMP in traces[0]["entity_ids"]

        single = await ok(admin, "trace", trace_id=traces[0]["trace_id"])
        assert single["trace"]["trace_id"] == traces[0]["trace_id"]

        assert await ok(admin, "clear_traces") == {"success": True}
        assert await ok(admin, "traces") == {"traces": []}

    async def test_traces_honour_include_active_false(self, admin: Any, entry: MockConfigEntry) -> None:
        """``include_active=False`` is forwarded to the collector, not ignored.

        One still-open trace and one closed trace exist, so the flag
        changes the answer: hard-coding either value fails.
        """
        collector = entry.runtime_data.bridge.trace_collector
        collector.begin(trace_id="closed-one", trigger="sber_command", entity_ids=[LAMP])
        collector.close("closed-one")
        collector.begin(trace_id="open-one", trigger="sber_command", entity_ids=[LAMP])

        with_active = {t["trace_id"] for t in (await ok(admin, "traces", include_active=True))["traces"]}
        without_active = {t["trace_id"] for t in (await ok(admin, "traces", include_active=False))["traces"]}

        assert with_active == {"closed-one", "open-one"}
        assert without_active == {"closed-one"}
        # The default must keep active traces (the panel relies on it).
        assert {t["trace_id"] for t in (await ok(admin, "traces"))["traces"]} == with_active

    async def test_trace_unknown_id_is_reported(self, admin: Any) -> None:
        response = await call(admin, "trace", trace_id="does-not-exist")
        assert response["error"]["code"] == "trace_not_found"


class TestDiffsModule:
    """``diffs.py`` — the state-payload diff ring buffer."""

    async def test_state_diffs_list_and_clear(self, hass: HomeAssistant, admin: Any) -> None:
        assert await ok(admin, "state_diffs") == {"diffs": []}

        bridge = hass.config_entries.async_entries(DOMAIN)[0].runtime_data.bridge
        bridge.diff_collector.update(LAMP, [{"key": "on_off", "value": {"bool_value": False}}])
        bridge.diff_collector.update(LAMP, [{"key": "on_off", "value": {"bool_value": True}}])

        diffs = (await ok(admin, "state_diffs"))["diffs"]
        assert [d["entity_id"] for d in diffs] == [LAMP]

        assert await ok(admin, "clear_state_diffs") == {"success": True}
        assert await ok(admin, "state_diffs") == {"diffs": []}


class TestValidationModule:
    """``validation.py`` — Sber schema-validation issues."""

    async def test_validation_issues_snapshot_and_clear(self, hass: HomeAssistant, admin: Any) -> None:
        result = await ok(admin, "validation_issues")
        assert result == {"recent": [], "by_entity": {}}

        bridge = hass.config_entries.async_entries(DOMAIN)[0].runtime_data.bridge
        from custom_components.sber_mqtt_bridge.schema_validator import validate_publish

        issues = validate_publish(entity_id=LAMP, category="light", states=[], declared_features=["on_off"])
        assert issues, "fixture precondition: a light publishing no states must be invalid"
        bridge.validation_collector.record(LAMP, issues)

        snapshot = await ok(admin, "validation_issues")
        assert [i["entity_id"] for i in snapshot["recent"]] == [LAMP] * len(issues)
        assert LAMP in snapshot["by_entity"]

        assert await ok(admin, "clear_validation_issues") == {"success": True}
        assert await ok(admin, "validation_issues") == {"recent": [], "by_entity": {}}


class TestDiagnoseModule:
    """``diagnose.py`` — the per-entity "why isn't it working?" advisor."""

    async def test_diagnose_reports_an_exposed_entity(self, admin: Any) -> None:
        report = (await ok(admin, "diagnose_entity", entity_id=LAMP))["report"]

        assert report["entity_id"] == LAMP
        assert report["summary"]["known_to_bridge"] is True
        assert report["summary"]["enabled"] is True
        assert report["summary"]["category"] == "light"
        assert report["summary"]["acknowledged_by_sber"] is False
        assert "never_acknowledged" in {finding["code"] for finding in report["findings"]}

    async def test_diagnose_flags_an_entity_the_bridge_never_loaded(self, admin: Any) -> None:
        report = (await ok(admin, "diagnose_entity", entity_id=PUMP))["report"]

        assert report["verdict"] == "broken"
        assert report["summary"]["known_to_bridge"] is False
        assert "not_known_to_bridge" in {finding["code"] for finding in report["findings"]}


# ---------------------------------------------------------------------------
# (b) Invalid payloads — rejected by the schema, no side effects
# ---------------------------------------------------------------------------


INVALID_PAYLOADS: list[tuple[str, dict[str, Any], str]] = [
    ("status", {"unexpected": 1}, "extra key on a schema-less command"),
    ("devices", {"limit": 5}, "extra key"),
    ("device_detail", {}, "missing required entity_id"),
    ("device_detail", {"entity_id": "not an entity id"}, "malformed entity_id"),
    ("list_categories", {"group": "lighting"}, "extra key"),
    ("list_devices_for_category", {}, "missing required category"),
    ("list_devices_for_category", {"category": "no_such_category"}, "category outside vol.In"),
    ("add_ha_device", {"device_id": "dev", "primary_entity_id": PUMP}, "missing required category"),
    (
        "add_ha_device",
        {"device_id": "dev", "primary_entity_id": "pump", "category": "relay"},
        "primary_entity_id is not domain.object_id",
    ),
    (
        "add_ha_device",
        {"device_id": "dev", "primary_entity_id": PUMP, "category": "not_a_category"},
        "category outside vol.In",
    ),
    ("suggest_links", {}, "missing required entity_id"),
    ("add_entities", {}, "missing required entity_ids"),
    ("add_entities", {"entity_ids": []}, "empty list violates Length(min=1)"),
    ("add_entities", {"entity_ids": ["not an entity id"]}, "malformed entity_id in list"),
    ("remove_entities", {"entity_ids": []}, "empty list violates Length(min=1)"),
    ("set_override", {"entity_id": LAMP}, "missing required category"),
    ("set_override", {"entity_id": LAMP, "category": "no_such_category"}, "category outside vol.In"),
    ("clear_all", {"confirm": True}, "extra key"),
    ("set_entity_links", {"entity_id": LAMP}, "missing required links"),
    ("set_entity_links", {"entity_id": LAMP, "links": {"temperature": "bad id"}}, "link value not an entity_id"),
    ("set_entity_links", {"entity_id": LAMP, "links": LAMP_TEMP}, "links is not a mapping"),
    ("auto_link_all", {"dry_run": True}, "extra key"),
    ("export", {"format": "json"}, "extra key"),
    ("import", {}, "missing required config"),
    ("import", {"config": "not a dict"}, "config is not a mapping"),
    ("update_redefinitions", {}, "missing required entity_id"),
    ("update_redefinitions", {"entity_id": LAMP, "name": 42}, "name is not a string"),
    ("raw_config", {"pretty": True}, "extra key"),
    ("send_raw_config", {}, "missing required payload"),
    ("send_raw_config", {"payload": {"devices": []}}, "payload is a dict, not a string"),
    ("send_raw_state", {"payload": ["a"]}, "payload is a list, not a string"),
    ("message_log", {"limit": 10}, "extra key"),
    ("clear_message_log", {"older_than": 1}, "extra key"),
    ("subscribe_messages", {"filter": "out"}, "extra key"),
    ("inject_sber_message", {"topic": "commands"}, "missing required payload"),
    (
        "inject_sber_message",
        {"topic": "commands", "payload": _command_payload(), "mark_replay": "yes"},
        "mark_replay is not a bool",
    ),
    ("replay_message", {"payload": "{}"}, "missing required topic"),
    ("get_settings", {"section": "mqtt"}, "extra key"),
    ("update_settings", {}, "missing required settings"),
    ("update_settings", {"settings": 5}, "settings is not a mapping"),
    ("publish_one_status", {}, "missing required entity_id"),
    ("related_sensors", {"entity_id": "lamp"}, "malformed entity_id"),
    ("traces", {"include_active": "yes"}, "include_active is not a bool"),
    ("trace", {}, "missing required trace_id"),
    ("trace", {"trace_id": 7}, "trace_id is not a string"),
    ("state_diffs", {"entity_id": LAMP}, "extra key"),
    ("validation_issues", {"severity": "error"}, "extra key"),
    ("diagnose_entity", {}, "missing required entity_id"),
    ("diagnose_entity", {"entity_id": "lamp"}, "malformed entity_id"),
]
"""``(command, payload, why-it-must-fail)`` triples for schema rejection.

Every entry is a payload the *handler* would happily act on (or crash
on) if the schema were removed or loosened — which is exactly the
regression this table exists to catch."""


@pytest.mark.parametrize(("command", "payload", "reason"), INVALID_PAYLOADS, ids=lambda value: str(value)[:40])
async def test_invalid_payload_is_rejected_without_side_effects(
    hass: HomeAssistant,
    admin: Any,
    snapshot: Callable[[], SideEffects],
    command: str,
    payload: dict[str, Any],
    reason: str,
) -> None:
    """Schema violations never reach the handler.

    ``invalid_format`` is asserted specifically: if the schema were
    dropped, the handler would run and answer either with a success, a
    domain-specific error code, or ``unknown_error`` from a ``KeyError``
    — all three fail here.
    """
    before = snapshot()

    response = await call(admin, command, **payload)
    await hass.async_block_till_done()

    assert response["success"] is False, f"{command} accepted invalid payload ({reason})"
    assert response["error"]["code"] == "invalid_format", f"{command}: {reason} — not a schema rejection"
    snapshot().assert_same_as(before, f"{command} ({reason})")


# ---------------------------------------------------------------------------
# (c) Non-admin access — rejected for every registered command
# ---------------------------------------------------------------------------


VALID_PAYLOADS: dict[str, dict[str, Any]] = {
    "device_detail": {"entity_id": LAMP},
    "publish_one_status": {"entity_id": LAMP},
    "related_sensors": {"entity_id": LAMP},
    "list_devices_for_category": {"category": "light"},
    "add_ha_device": {"device_id": "dev", "primary_entity_id": PUMP, "category": "relay"},
    "suggest_links": {"entity_id": LAMP},
    "add_entities": {"entity_ids": [PUMP]},
    "remove_entities": {"entity_ids": [LAMP]},
    "set_override": {"entity_id": LAMP, "category": "led_strip"},
    "set_entity_links": {"entity_id": LAMP, "links": {"temperature": LAMP_TEMP}},
    "import": {"config": {"exposed_entities": [PUMP]}},
    "update_redefinitions": {"entity_id": LAMP, "name": "Кухня"},
    "send_raw_config": {"payload": "{}"},
    "send_raw_state": {"payload": "{}"},
    "inject_sber_message": {"topic": "commands", "payload": _command_payload()},
    "replay_message": {"topic": "commands", "payload": _command_payload()},
    "update_settings": {"settings": {"debounce_delay": 0.9}},
    "trace": {"trace_id": "nope"},
    "diagnose_entity": {"entity_id": LAMP},
}
"""Schema-valid extra fields per command (commands not listed take none).

Deliberately *effective* payloads: the non-admin sweep must prove the
guard fires before a request that would otherwise mutate state."""


async def test_non_admin_is_rejected_for_every_registered_command(
    hass: HomeAssistant,
    guest: Any,
    snapshot: Callable[[], SideEffects],
) -> None:
    """A read-only user cannot reach a single command of this integration.

    The sweep enumerates the *registered* table rather than a hand-kept
    list, so a command added without going through the ``require_admin``
    choke point fails here.  Payloads are schema-valid and mutating on
    purpose: the snapshot comparison proves the guard runs *before* the
    handler, not after it.
    """
    commands = registered_commands(hass)
    assert len(commands) >= 40, "WS command table looks empty — fixture wiring broken"

    before = snapshot()
    unprotected: list[str] = []

    for command in commands:
        short = command.removeprefix(SBER_PREFIX)
        response = await call(guest, short, **VALID_PAYLOADS.get(short, {}))
        if response["success"] or response["error"]["code"] != "unauthorized":
            unprotected.append(f"{short} -> {response.get('error', response)}")

    await hass.async_block_till_done()
    assert not unprotected, f"commands reachable by a non-admin user: {unprotected}"
    snapshot().assert_same_as(before, "non-admin sweep")


async def test_admin_reaches_the_same_commands(hass: HomeAssistant, admin: Any) -> None:
    """Counter-test: the guard must not reject *everyone*.

    Without this, a mutation that raises ``Unauthorized`` unconditionally
    would keep the sweep above green.
    """
    responses = {
        command.removeprefix(SBER_PREFIX): await call(
            admin,
            command.removeprefix(SBER_PREFIX),
            **VALID_PAYLOADS.get(command.removeprefix(SBER_PREFIX), {}),
        )
        for command in registered_commands(hass)
    }
    await hass.async_block_till_done()

    denied = [
        name
        for name, response in responses.items()
        if not response["success"] and response["error"]["code"] == "unauthorized"
    ]
    assert not denied, f"admin was denied: {denied}"


# ---------------------------------------------------------------------------
# Anti-regress: every registered command is schema-guarded and admin-only
# ---------------------------------------------------------------------------


class TestCommandTableInvariants:
    """Structural + behavioural invariants of the registered table."""

    def test_registration_covers_exactly_the_commands_tuple(self, hass: HomeAssistant, entry: Any) -> None:
        """Nothing is registered outside :data:`ws_pkg._COMMANDS`."""
        assert set(registered_commands(hass)) == {command._ws_command for command in ws_pkg._COMMANDS}

    def test_every_command_declares_a_type_bearing_schema(self, hass: HomeAssistant, entry: Any) -> None:
        """Each handler carries a ``type``-anchored voluptuous schema.

        HA stores ``False`` for the degenerate "only ``type``" schema and
        then enforces "no extra keys" itself, so both shapes are legal —
        but a handler registered without going through
        ``@websocket_api.websocket_command`` (no ``_ws_schema`` at all)
        would accept arbitrary payloads and is rejected here.
        """
        offenders: list[str] = []
        for command, (handler, schema) in registered_commands(hass).items():
            if not hasattr(handler, "_ws_schema"):
                offenders.append(f"{command}: no _ws_schema (missing @websocket_command)")
                continue
            if getattr(handler, "_ws_command", None) != command:
                offenders.append(f"{command}: _ws_command mismatch ({handler._ws_command!r})")
            if schema is False:
                continue
            required = {str(key) for key in schema.schema if key.schema == "type"}
            if not required:
                offenders.append(f"{command}: schema has no 'type' key")
            elif schema.schema.get("type") != command:
                offenders.append(f"{command}: schema type pins {schema.schema.get('type')!r}")
        assert not offenders, offenders

    async def test_every_command_rejects_an_unexpected_key(
        self,
        hass: HomeAssistant,
        admin: Any,
        snapshot: Callable[[], SideEffects],
    ) -> None:
        """Behavioural proof that the schema is applied, command by command.

        A command whose schema is missing, or relaxed to
        ``extra=vol.ALLOW_EXTRA``, would silently accept the junk key and
        execute — caught both by the error-code assertion and by the
        side-effect snapshot.
        """
        before = snapshot()
        leaky: list[str] = []

        for command in registered_commands(hass):
            short = command.removeprefix(SBER_PREFIX)
            payload = {**VALID_PAYLOADS.get(short, {}), "__unexpected__": "x"}
            response = await call(admin, short, **payload)
            if response["success"] or response["error"]["code"] != "invalid_format":
                leaky.append(f"{short} -> {response.get('error', response)}")

        await hass.async_block_till_done()
        assert not leaky, f"commands accepting undeclared keys: {leaky}"
        snapshot().assert_same_as(before, "unexpected-key sweep")
