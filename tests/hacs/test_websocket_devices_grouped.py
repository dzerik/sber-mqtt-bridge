"""Unit tests for the device-centric wizard WebSocket commands.

Mocks the HA connection / config_entry / registries to isolate the
business logic of ``ws_list_categories`` / ``ws_list_devices_for_category``
/ ``ws_add_ha_device``.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.sber_mqtt_bridge.websocket_api.devices_grouped import (
    ws_add_ha_device,
    ws_list_categories,
    ws_list_devices_for_category,
)

# ---------------------------------------------------------------------------
# Test fixtures — minimal HA + connection stubs
# ---------------------------------------------------------------------------


@pytest.fixture
def connection():
    conn = MagicMock()
    conn.send_result = MagicMock()
    conn.send_error = MagicMock()
    return conn


@pytest.fixture
def hass():
    hass_ = MagicMock()
    hass_.config_entries.async_update_entry = MagicMock()
    hass_.config_entries.async_reload = AsyncMock()
    return hass_


def _make_entry(options: dict | None = None):
    entry = MagicMock()
    entry.entry_id = "test_entry"
    entry.options = options or {}
    return entry


def _make_entity(
    entity_id: str,
    *,
    device_id: str | None = None,
    domain: str | None = None,
    original_device_class: str | None = None,
    name: str | None = None,
    original_name: str | None = None,
    platform: str = "test",
    unique_id: str | None = None,
    disabled_by: str | None = None,
) -> MagicMock:
    entry = MagicMock()
    entry.entity_id = entity_id
    entry.domain = domain or entity_id.split(".")[0]
    entry.device_id = device_id
    entry.original_device_class = original_device_class
    entry.name = name
    entry.original_name = original_name
    entry.platform = platform
    entry.unique_id = unique_id or entity_id
    entry.disabled_by = disabled_by
    entry.area_id = None
    entry.hidden_by = None
    entry.entity_category = None
    return entry


def _make_device(device_id: str, **kwargs):
    device = MagicMock()
    device.id = device_id
    device.name = kwargs.get("name", device_id)
    device.name_by_user = kwargs.get("name_by_user")
    device.manufacturer = kwargs.get("manufacturer", "")
    device.model = kwargs.get("model", "")
    device.area_id = kwargs.get("area_id")
    device.disabled_by = kwargs.get("disabled_by")
    device.identifiers = kwargs.get("identifiers", set())
    return device


@pytest.fixture
def mock_get_config_entry(hass):
    entry = _make_entry()
    with patch("custom_components.sber_mqtt_bridge.websocket_api.devices_grouped.get_config_entry") as mock:
        mock.return_value = entry
        yield mock, entry


@pytest.fixture
def mock_registries():
    """Patch HA registries used by device_grouper."""
    with (
        patch("custom_components.sber_mqtt_bridge.device_grouper.er") as mock_er,
        patch("custom_components.sber_mqtt_bridge.device_grouper.dr") as mock_dr,
        patch("custom_components.sber_mqtt_bridge.device_grouper.ar") as mock_ar,
    ):
        entity_reg = MagicMock()
        entity_reg.entities = {}
        mock_er.async_get.return_value = entity_reg
        device_reg = MagicMock()
        device_reg.devices = {}
        device_reg.async_get.side_effect = lambda did: device_reg.devices.get(did)
        mock_dr.async_get.return_value = device_reg
        area_reg = MagicMock()
        area_reg._areas = {}
        area_reg.async_get_area.side_effect = lambda aid: area_reg._areas.get(aid)
        mock_ar.async_get.return_value = area_reg
        yield entity_reg, device_reg, area_reg


# ---------------------------------------------------------------------------
# ws_list_categories
# ---------------------------------------------------------------------------


class TestListCategories:
    def test_returns_categories_and_groups(self, hass, connection):
        msg = {"id": 1, "type": "sber_mqtt_bridge/list_categories"}
        ws_list_categories(hass, connection, msg)
        connection.send_result.assert_called_once()
        args = connection.send_result.call_args
        assert args[0][0] == 1
        payload = args[0][1]
        assert "categories" in payload
        assert "groups" in payload
        assert isinstance(payload["categories"], list)
        assert isinstance(payload["groups"], list)

    def test_category_shape(self, hass, connection):
        msg = {"id": 2}
        ws_list_categories(hass, connection, msg)
        payload = connection.send_result.call_args[0][1]
        first = payload["categories"][0]
        assert set(first.keys()) == {
            "id",
            "group",
            "icon",
            "label",
            "domains",
            "device_classes",
            "preferred_rank",
        }

    def test_light_is_present_and_selectable(self, hass, connection):
        msg = {"id": 3}
        ws_list_categories(hass, connection, msg)
        payload = connection.send_result.call_args[0][1]
        ids = {c["id"] for c in payload["categories"]}
        assert "light" in ids
        assert "relay" in ids
        assert "sensor_temp" in ids
        assert "sensor_pir" in ids

    def test_sensor_humidity_is_excluded(self, hass, connection):
        """Non-user-selectable subcategories should not appear in Step 1 grid."""
        msg = {"id": 4}
        ws_list_categories(hass, connection, msg)
        payload = connection.send_result.call_args[0][1]
        ids = {c["id"] for c in payload["categories"]}
        assert "sensor_humidity" not in ids

    def test_groups_have_id_and_label(self, hass, connection):
        msg = {"id": 5}
        ws_list_categories(hass, connection, msg)
        payload = connection.send_result.call_args[0][1]
        assert all(set(g.keys()) == {"id", "label"} for g in payload["groups"])

    def test_categories_sorted_stable(self, hass, connection):
        msg = {"id": 6}
        ws_list_categories(hass, connection, msg)
        payload = connection.send_result.call_args[0][1]
        # Sorted primarily by group
        groups_in_order = [c["group"] for c in payload["categories"]]
        # Check monotonic transitions (no ABAB zig-zag)
        seen = set()
        current = None
        for g in groups_in_order:
            if g != current:
                assert g not in seen, f"Group {g} appeared after others"
                seen.add(g)
                current = g


# ---------------------------------------------------------------------------
# ws_list_devices_for_category
# ---------------------------------------------------------------------------


class TestListDevicesForCategory:
    @pytest.mark.asyncio
    async def test_unknown_category_returns_error(self, hass, connection, mock_get_config_entry, mock_registries):
        msg = {"id": 10, "category": "nonexistent_xyz"}
        await ws_list_devices_for_category.__wrapped__(hass, connection, msg)
        connection.send_error.assert_called_once()
        assert connection.send_error.call_args[0][1] == "unknown_category"

    @pytest.mark.asyncio
    async def test_empty_registry_returns_empty_list(self, hass, connection, mock_get_config_entry, mock_registries):
        msg = {"id": 11, "category": "light"}
        await ws_list_devices_for_category.__wrapped__(hass, connection, msg)
        connection.send_result.assert_called_once()
        payload = connection.send_result.call_args[0][1]
        assert payload["category"] == "light"
        assert payload["devices"] == []
        assert payload["summary"]["total"] == 0
        assert payload["summary"]["already_exposed"] == 0
        assert payload["summary"]["unexposed"] == 0

    @pytest.mark.asyncio
    async def test_returns_grouped_device_structure(self, hass, connection, mock_get_config_entry, mock_registries):
        entity_reg, device_reg, _ = mock_registries
        device_reg.devices = {"dev1": _make_device("dev1", name="Lamp")}
        entity_reg.entities = {
            "light.lamp": _make_entity("light.lamp", device_id="dev1"),
        }
        msg = {"id": 12, "category": "light"}
        await ws_list_devices_for_category.__wrapped__(hass, connection, msg)
        payload = connection.send_result.call_args[0][1]
        assert payload["summary"]["total"] == 1
        assert len(payload["devices"]) == 1
        device = payload["devices"][0]
        assert device["device_id"] == "dev1"
        assert device["primary"]["entity_id"] == "light.lamp"

    @pytest.mark.asyncio
    async def test_already_exposed_counted_in_summary(self, hass, connection, mock_registries):
        entity_reg, device_reg, _ = mock_registries
        device_reg.devices = {"dev1": _make_device("dev1")}
        entity_reg.entities = {
            "light.exposed": _make_entity("light.exposed", device_id="dev1"),
        }
        entry = _make_entry(options={"exposed_entities": ["light.exposed"]})
        with patch(
            "custom_components.sber_mqtt_bridge.websocket_api.devices_grouped.get_config_entry",
            return_value=entry,
        ):
            msg = {"id": 13, "category": "light"}
            await ws_list_devices_for_category.__wrapped__(hass, connection, msg)
        payload = connection.send_result.call_args[0][1]
        assert payload["summary"]["total"] == 1
        assert payload["summary"]["already_exposed"] == 1
        assert payload["devices"][0]["already_exposed"] is True


# ---------------------------------------------------------------------------
# ws_add_ha_device
# ---------------------------------------------------------------------------


class TestAddHaDevice:
    @pytest.mark.asyncio
    async def test_entry_not_found(self, hass, connection):
        with patch(
            "custom_components.sber_mqtt_bridge.websocket_api.devices_grouped.get_config_entry",
            return_value=None,
        ):
            msg = {
                "id": 20,
                "device_id": "dev1",
                "primary_entity_id": "light.lamp",
                "category": "light",
            }
            await ws_add_ha_device.__wrapped__(hass, connection, msg)
        connection.send_error.assert_called_once()
        assert connection.send_error.call_args[0][1] == "entry_not_found"

    @pytest.mark.asyncio
    async def test_unknown_category(self, hass, connection):
        entry = _make_entry()
        with patch(
            "custom_components.sber_mqtt_bridge.websocket_api.devices_grouped.get_config_entry",
            return_value=entry,
        ):
            msg = {
                "id": 21,
                "device_id": "dev1",
                "primary_entity_id": "light.lamp",
                "category": "bogus_category",
            }
            await ws_add_ha_device.__wrapped__(hass, connection, msg)
        connection.send_error.assert_called_once()
        assert connection.send_error.call_args[0][1] == "unknown_category"

    @pytest.mark.asyncio
    async def test_primary_not_found(self, hass, connection):
        entry = _make_entry()
        entity_reg = MagicMock()
        entity_reg.async_get.return_value = None
        with (
            patch(
                "custom_components.sber_mqtt_bridge.websocket_api.devices_grouped.get_config_entry",
                return_value=entry,
            ),
            patch("homeassistant.helpers.entity_registry.async_get", return_value=entity_reg),
        ):
            msg = {
                "id": 22,
                "device_id": "dev1",
                "primary_entity_id": "light.missing",
                "category": "light",
            }
            await ws_add_ha_device.__wrapped__(hass, connection, msg)
        connection.send_error.assert_called_once()
        assert connection.send_error.call_args[0][1] == "primary_not_found"

    @pytest.mark.asyncio
    async def test_primary_device_mismatch(self, hass, connection):
        entry = _make_entry()
        primary = _make_entity("light.lamp", device_id="other_dev")
        entity_reg = MagicMock()
        entity_reg.async_get.return_value = primary
        with (
            patch(
                "custom_components.sber_mqtt_bridge.websocket_api.devices_grouped.get_config_entry",
                return_value=entry,
            ),
            patch("homeassistant.helpers.entity_registry.async_get", return_value=entity_reg),
        ):
            msg = {
                "id": 23,
                "device_id": "dev1",
                "primary_entity_id": "light.lamp",
                "category": "light",
            }
            await ws_add_ha_device.__wrapped__(hass, connection, msg)
        connection.send_error.assert_called_once()
        assert connection.send_error.call_args[0][1] == "primary_device_mismatch"

    @pytest.mark.asyncio
    async def test_primary_category_mismatch(self, hass, connection):
        """light.lamp can't be added as curtain — rejected."""
        entry = _make_entry()
        primary = _make_entity("light.lamp", device_id="dev1")
        entity_reg = MagicMock()
        entity_reg.async_get.return_value = primary
        with (
            patch(
                "custom_components.sber_mqtt_bridge.websocket_api.devices_grouped.get_config_entry",
                return_value=entry,
            ),
            patch("homeassistant.helpers.entity_registry.async_get", return_value=entity_reg),
        ):
            msg = {
                "id": 24,
                "device_id": "dev1",
                "primary_entity_id": "light.lamp",
                "category": "curtain",
            }
            await ws_add_ha_device.__wrapped__(hass, connection, msg)
        connection.send_error.assert_called_once()
        assert connection.send_error.call_args[0][1] == "primary_category_mismatch"

    @pytest.mark.asyncio
    async def test_happy_path_atomic_update(self, hass, connection):
        """Successful add must patch options in one atomic update_entry + reload."""
        entry = _make_entry()
        primary = _make_entity("light.lamp", device_id="dev1", original_name="Lamp")
        entity_reg = MagicMock()
        entity_reg.async_get.side_effect = lambda eid: primary if eid == "light.lamp" else None
        with (
            patch(
                "custom_components.sber_mqtt_bridge.websocket_api.devices_grouped.get_config_entry",
                return_value=entry,
            ),
            patch("homeassistant.helpers.entity_registry.async_get", return_value=entity_reg),
        ):
            msg = {
                "id": 25,
                "device_id": "dev1",
                "primary_entity_id": "light.lamp",
                "category": "light",
                "name": "Living Room Light",
                "room": "Living Room",
            }
            await ws_add_ha_device.__wrapped__(hass, connection, msg)

        connection.send_result.assert_called_once()
        payload = connection.send_result.call_args[0][1]
        assert payload["success"] is True
        assert payload["primary_entity_id"] == "light.lamp"
        assert payload["category"] == "light"
        assert payload["linked_count"] == 0

        # One atomic update_entry call...
        hass.config_entries.async_update_entry.assert_called_once()
        options = hass.config_entries.async_update_entry.call_args[1]["options"]
        assert "light.lamp" in options["exposed_entities"]
        assert options["entity_type_overrides"]["light.lamp"] == "light"
        assert options["redefinitions"]["light.lamp"]["name"] == "Living Room Light"
        assert options["redefinitions"]["light.lamp"]["room"] == "Living Room"

        # ... followed by one reload
        hass.config_entries.async_reload.assert_awaited_once_with("test_entry")

    @pytest.mark.asyncio
    async def test_linked_sensors_stored_by_role(self, hass, connection):
        """Linked entities must be stored as {role: entity_id} mapping."""
        entry = _make_entry()
        primary = _make_entity("cover.curtain", device_id="dev1")
        battery = _make_entity(
            "sensor.curtain_battery",
            device_id="dev1",
            original_device_class="battery",
        )
        entity_reg = MagicMock()
        entity_reg.async_get.side_effect = lambda eid: {
            "cover.curtain": primary,
            "sensor.curtain_battery": battery,
        }.get(eid)
        with (
            patch(
                "custom_components.sber_mqtt_bridge.websocket_api.devices_grouped.get_config_entry",
                return_value=entry,
            ),
            patch("homeassistant.helpers.entity_registry.async_get", return_value=entity_reg),
        ):
            msg = {
                "id": 26,
                "device_id": "dev1",
                "primary_entity_id": "cover.curtain",
                "category": "curtain",
                "linked_entity_ids": ["sensor.curtain_battery"],
            }
            await ws_add_ha_device.__wrapped__(hass, connection, msg)

        connection.send_result.assert_called_once()
        payload = connection.send_result.call_args[0][1]
        assert payload["linked_count"] == 1

        options = hass.config_entries.async_update_entry.call_args[1]["options"]
        assert options["entity_links"]["cover.curtain"] == {"battery": "sensor.curtain_battery"}

    @pytest.mark.asyncio
    async def test_role_conflict_rejected(self, hass, connection):
        """Two linked entities with the same role → error."""
        entry = _make_entry()
        primary = _make_entity("cover.curtain", device_id="dev1")
        battery1 = _make_entity(
            "sensor.battery1",
            device_id="dev1",
            original_device_class="battery",
        )
        battery2 = _make_entity(
            "sensor.battery2",
            device_id="dev1",
            original_device_class="battery",
        )
        entity_reg = MagicMock()
        entity_reg.async_get.side_effect = lambda eid: {
            "cover.curtain": primary,
            "sensor.battery1": battery1,
            "sensor.battery2": battery2,
        }.get(eid)
        with (
            patch(
                "custom_components.sber_mqtt_bridge.websocket_api.devices_grouped.get_config_entry",
                return_value=entry,
            ),
            patch("homeassistant.helpers.entity_registry.async_get", return_value=entity_reg),
        ):
            msg = {
                "id": 27,
                "device_id": "dev1",
                "primary_entity_id": "cover.curtain",
                "category": "curtain",
                "linked_entity_ids": ["sensor.battery1", "sensor.battery2"],
            }
            await ws_add_ha_device.__wrapped__(hass, connection, msg)

        connection.send_error.assert_called_once()
        assert connection.send_error.call_args[0][1] == "role_conflict"

    @pytest.mark.asyncio
    async def test_linked_role_not_accepted(self, hass, connection):
        """A linked entity whose role isn't in LINKABLE_ROLES → error."""
        entry = _make_entry()
        # RelayEntity.LINKABLE_ROLES is empty, so linking battery to a
        # relay should fail.
        primary = _make_entity("switch.relay", device_id="dev1")
        battery = _make_entity(
            "sensor.battery",
            device_id="dev1",
            original_device_class="battery",
        )
        entity_reg = MagicMock()
        entity_reg.async_get.side_effect = lambda eid: {
            "switch.relay": primary,
            "sensor.battery": battery,
        }.get(eid)
        with (
            patch(
                "custom_components.sber_mqtt_bridge.websocket_api.devices_grouped.get_config_entry",
                return_value=entry,
            ),
            patch("homeassistant.helpers.entity_registry.async_get", return_value=entity_reg),
        ):
            msg = {
                "id": 28,
                "device_id": "dev1",
                "primary_entity_id": "switch.relay",
                "category": "relay",
                "linked_entity_ids": ["sensor.battery"],
            }
            await ws_add_ha_device.__wrapped__(hass, connection, msg)
        connection.send_error.assert_called_once()
        assert connection.send_error.call_args[0][1] == "linked_role_not_accepted"

    @pytest.mark.asyncio
    async def test_category_always_stored_in_overrides(self, hass, connection):
        """Even when chosen category equals auto-detect, write it to overrides.

        Makes behaviour deterministic if HA domains change later.
        """
        entry = _make_entry()
        primary = _make_entity("light.lamp", device_id="dev1")
        entity_reg = MagicMock()
        entity_reg.async_get.return_value = primary
        with (
            patch(
                "custom_components.sber_mqtt_bridge.websocket_api.devices_grouped.get_config_entry",
                return_value=entry,
            ),
            patch("homeassistant.helpers.entity_registry.async_get", return_value=entity_reg),
        ):
            msg = {
                "id": 29,
                "device_id": "dev1",
                "primary_entity_id": "light.lamp",
                "category": "light",
            }
            await ws_add_ha_device.__wrapped__(hass, connection, msg)

        options = hass.config_entries.async_update_entry.call_args[1]["options"]
        assert options["entity_type_overrides"]["light.lamp"] == "light"
