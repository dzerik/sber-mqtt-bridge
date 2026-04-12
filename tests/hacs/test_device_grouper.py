"""Unit tests for HaDeviceGrouper — the device-centric wizard classifier.

Tests use MagicMock'ed HA registries (device_registry / entity_registry /
area_registry) to isolate classification logic from the full HA runtime.
The mock pattern matches the one used in ``test_p4_tasks.py`` — patches
target the ``entity_registry`` module where the grouper lives.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from custom_components.sber_mqtt_bridge.device_grouper import (
    DeviceGroup,
    EntityRole,
    HaDeviceGrouper,
)

# ---------------------------------------------------------------------------
# Test fixtures — minimal HA registry stubs
# ---------------------------------------------------------------------------


def _make_device(
    device_id: str,
    *,
    name: str = "",
    name_by_user: str | None = None,
    manufacturer: str = "",
    model: str = "",
    area_id: str | None = None,
    disabled_by: str | None = None,
    identifiers: set | None = None,
) -> MagicMock:
    device = MagicMock()
    device.id = device_id
    device.name = name or device_id
    device.name_by_user = name_by_user
    device.manufacturer = manufacturer
    device.model = model
    device.area_id = area_id
    device.disabled_by = disabled_by
    device.identifiers = identifiers or set()
    return device


def _make_entity(
    entity_id: str,
    *,
    device_id: str | None = None,
    domain: str | None = None,
    original_device_class: str | None = None,
    name: str | None = None,
    original_name: str | None = None,
    area_id: str | None = None,
    disabled_by: str | None = None,
    hidden_by: str | None = None,
    entity_category: str | None = None,
    platform: str = "test",
    unique_id: str | None = None,
) -> MagicMock:
    entry = MagicMock()
    entry.entity_id = entity_id
    entry.domain = domain or entity_id.split(".")[0]
    entry.device_id = device_id
    entry.original_device_class = original_device_class
    entry.name = name
    entry.original_name = original_name
    entry.area_id = area_id
    entry.disabled_by = disabled_by
    entry.hidden_by = hidden_by
    entry.entity_category = entity_category
    entry.platform = platform
    entry.unique_id = unique_id or entity_id
    return entry


def _make_area(area_id: str, name: str) -> MagicMock:
    area = MagicMock()
    area.id = area_id
    area.name = name
    return area


@pytest.fixture
def hass():
    return MagicMock()


@pytest.fixture
def mock_registries():
    """Patch the three HA registries at the device_grouper module level."""
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
        mock_dr.async_get.return_value = device_reg
        # async_get on device_reg returns from the devices dict
        device_reg.async_get.side_effect = lambda did: device_reg.devices.get(did)
        area_reg = MagicMock()
        area_reg._areas = {}
        area_reg.async_get_area.side_effect = lambda aid: area_reg._areas.get(aid)
        mock_ar.async_get.return_value = area_reg
        yield entity_reg, device_reg, area_reg


def _set_entities(entity_reg, entries):
    entity_reg.entities = {e.entity_id: e for e in entries}


def _set_devices(device_reg, devices):
    device_reg.devices = {d.id: d for d in devices}
    device_reg.async_get.side_effect = lambda did: device_reg.devices.get(did)


def _set_areas(area_reg, areas):
    area_reg._areas = {a.id: a for a in areas}
    area_reg.async_get_area.side_effect = lambda aid: area_reg._areas.get(aid)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestEmptyRegistry:
    def test_empty_returns_empty_list(self, hass, mock_registries):
        grouper = HaDeviceGrouper(hass)
        assert grouper.list_for_category("light") == []

    def test_unknown_category_returns_empty(self, hass, mock_registries):
        grouper = HaDeviceGrouper(hass)
        assert grouper.list_for_category("nonexistent_xyz") == []


class TestLightDevices:
    def test_single_light_device_with_battery_signal(self, hass, mock_registries):
        entity_reg, device_reg, area_reg = mock_registries
        device = _make_device(
            "dev_lamp",
            name="Living Room Lamp",
            manufacturer="IKEA",
            model="TRADFRI bulb E27",
            area_id="living_room",
        )
        _set_devices(device_reg, [device])
        _set_areas(area_reg, [_make_area("living_room", "Living Room")])
        _set_entities(
            entity_reg,
            [
                _make_entity(
                    "light.living_room_lamp",
                    device_id="dev_lamp",
                    original_name="Lamp",
                ),
                _make_entity(
                    "sensor.living_room_lamp_battery",
                    device_id="dev_lamp",
                    original_device_class="battery",
                    original_name="Battery",
                ),
                _make_entity(
                    "sensor.living_room_lamp_signal",
                    device_id="dev_lamp",
                    original_device_class="signal_strength",
                    original_name="Signal",
                ),
            ],
        )

        grouper = HaDeviceGrouper(hass)
        result = grouper.list_for_category("light")
        assert len(result) == 1
        group = result[0]
        assert isinstance(group, DeviceGroup)
        assert group.device_id == "dev_lamp"
        assert group.name == "Living Room Lamp"
        assert group.manufacturer == "IKEA"
        assert group.model == "TRADFRI bulb E27"
        assert group.area == "Living Room"
        assert group.primary.entity_id == "light.living_room_lamp"
        assert group.primary.role == EntityRole.PRIMARY
        # NOTE: LightEntity.LINKABLE_ROLES = () in current code, so these will
        # actually end up in unsupported rather than linked_native.  Test
        # asserts the current (documented in ARCHITECTURE_RESEARCH §1.3) state.
        assert len(group.linked_native) == 0
        assert len(group.unsupported) == 2

    def test_no_light_devices_returns_empty(self, hass, mock_registries):
        entity_reg, device_reg, _ = mock_registries
        device = _make_device("dev_switch")
        _set_devices(device_reg, [device])
        _set_entities(
            entity_reg,
            [_make_entity("switch.something", device_id="dev_switch")],
        )
        grouper = HaDeviceGrouper(hass)
        assert grouper.list_for_category("light") == []

    def test_device_without_any_entity_excluded(self, hass, mock_registries):
        _, device_reg, _ = mock_registries
        _set_devices(device_reg, [_make_device("empty_dev")])
        grouper = HaDeviceGrouper(hass)
        assert grouper.list_for_category("light") == []


class TestCurtainDevices:
    """CurtainEntity.LINKABLE_ROLES = SENSOR_LINK_ROLES — proper linking works."""

    def test_curtain_with_native_battery_signal(self, hass, mock_registries):
        entity_reg, device_reg, _area_reg = mock_registries
        _set_devices(device_reg, [_make_device("curt_dev", name="Curtain")])
        _set_entities(
            entity_reg,
            [
                _make_entity("cover.curtain", device_id="curt_dev"),
                _make_entity(
                    "sensor.curtain_battery",
                    device_id="curt_dev",
                    original_device_class="battery",
                ),
                _make_entity(
                    "sensor.curtain_signal",
                    device_id="curt_dev",
                    original_device_class="signal_strength",
                ),
                _make_entity(
                    "update.curtain_firmware",
                    device_id="curt_dev",
                ),
            ],
        )
        grouper = HaDeviceGrouper(hass)
        result = grouper.list_for_category("curtain")
        assert len(result) == 1
        group = result[0]
        assert group.primary.entity_id == "cover.curtain"
        native_ids = {e.entity_id for e in group.linked_native}
        assert native_ids == {
            "sensor.curtain_battery",
            "sensor.curtain_signal",
        }
        for linked in group.linked_native:
            assert linked.preselected is True
            assert linked.role == EntityRole.LINKED_NATIVE
        assert len(group.unsupported) == 1
        assert group.unsupported[0].entity_id == "update.curtain_firmware"


class TestPrimaryAlternatives:
    def test_two_switches_on_one_device(self, hass, mock_registries):
        """Xiaomi-style device with two switches: one primary + one alternative."""
        entity_reg, device_reg, _ = mock_registries
        _set_devices(device_reg, [_make_device("gw_dev", name="Gateway")])
        _set_entities(
            entity_reg,
            [
                _make_entity("switch.gw_relay1", device_id="gw_dev"),
                _make_entity("switch.gw_relay2", device_id="gw_dev"),
            ],
        )
        grouper = HaDeviceGrouper(hass)
        result = grouper.list_for_category("relay")
        assert len(result) == 1
        group = result[0]
        assert group.primary.entity_id == "switch.gw_relay1"
        assert len(group.primary_alternatives) == 1
        assert group.primary_alternatives[0].entity_id == "switch.gw_relay2"


class TestDisabledHiddenEntities:
    def test_disabled_entity_skipped_entirely(self, hass, mock_registries):
        entity_reg, device_reg, _ = mock_registries
        _set_devices(device_reg, [_make_device("dev1")])
        _set_entities(
            entity_reg,
            [
                _make_entity("light.good", device_id="dev1"),
                _make_entity(
                    "sensor.disabled_battery",
                    device_id="dev1",
                    original_device_class="battery",
                    disabled_by="user",
                ),
            ],
        )
        grouper = HaDeviceGrouper(hass)
        result = grouper.list_for_category("light")
        assert len(result) == 1
        # Disabled battery entity must not appear anywhere
        all_entity_ids = {result[0].primary.entity_id}
        all_entity_ids.update(e.entity_id for e in result[0].linked_native)
        all_entity_ids.update(e.entity_id for e in result[0].linked_compatible)
        all_entity_ids.update(e.entity_id for e in result[0].unsupported)
        assert "sensor.disabled_battery" not in all_entity_ids

    def test_disabled_device_skipped(self, hass, mock_registries):
        entity_reg, device_reg, _ = mock_registries
        _set_devices(
            device_reg,
            [_make_device("dev1", disabled_by="user")],
        )
        _set_entities(
            entity_reg,
            [_make_entity("light.bulb", device_id="dev1")],
        )
        grouper = HaDeviceGrouper(hass)
        assert grouper.list_for_category("light") == []


class TestCrossDeviceLinks:
    def test_cross_device_battery_added_to_linked_compatible(self, hass, mock_registries):
        entity_reg, device_reg, _ = mock_registries
        _set_devices(
            device_reg,
            [
                _make_device("curt_dev", name="Curtain"),
                _make_device("orphan_dev", name="Orphan Battery"),
            ],
        )
        _set_entities(
            entity_reg,
            [
                _make_entity("cover.curtain", device_id="curt_dev"),
                _make_entity(
                    "sensor.orphan_battery",
                    device_id="orphan_dev",
                    original_device_class="battery",
                ),
            ],
        )
        grouper = HaDeviceGrouper(hass)
        result = grouper.list_for_category("curtain")
        assert len(result) == 1
        group = result[0]
        assert len(group.linked_compatible) == 1
        comp = group.linked_compatible[0]
        assert comp.entity_id == "sensor.orphan_battery"
        assert comp.is_cross_device is True
        assert comp.origin_device_id == "orphan_dev"
        assert comp.origin_device_name == "Orphan Battery"
        assert comp.preselected is False

    def test_cross_device_skipped_when_native_fills_role(self, hass, mock_registries):
        entity_reg, device_reg, _ = mock_registries
        _set_devices(
            device_reg,
            [
                _make_device("curt_dev"),
                _make_device("orphan_dev"),
            ],
        )
        _set_entities(
            entity_reg,
            [
                _make_entity("cover.curtain", device_id="curt_dev"),
                _make_entity(
                    "sensor.curtain_battery",
                    device_id="curt_dev",
                    original_device_class="battery",
                ),
                _make_entity(
                    "sensor.orphan_battery",
                    device_id="orphan_dev",
                    original_device_class="battery",
                ),
            ],
        )
        grouper = HaDeviceGrouper(hass)
        result = grouper.list_for_category("curtain")
        group = result[0]
        assert len(group.linked_native) == 1
        assert group.linked_native[0].entity_id == "sensor.curtain_battery"
        assert len(group.linked_compatible) == 0


class TestAlreadyExposed:
    def test_primary_already_exposed_sets_flag(self, hass, mock_registries):
        entity_reg, device_reg, _ = mock_registries
        _set_devices(device_reg, [_make_device("dev1")])
        _set_entities(
            entity_reg,
            [_make_entity("light.bulb", device_id="dev1")],
        )
        grouper = HaDeviceGrouper(hass, exposed_ids={"light.bulb"})
        result = grouper.list_for_category("light")
        assert result[0].already_exposed is True
        assert result[0].primary.already_exposed is True


class TestAreaResolution:
    def test_entity_area_beats_device_area(self, hass, mock_registries):
        entity_reg, device_reg, area_reg = mock_registries
        _set_devices(
            device_reg,
            [_make_device("dev1", area_id="kitchen")],
        )
        _set_areas(
            area_reg,
            [
                _make_area("kitchen", "Kitchen"),
                _make_area("bedroom", "Bedroom"),
            ],
        )
        _set_entities(
            entity_reg,
            [
                _make_entity(
                    "light.bulb",
                    device_id="dev1",
                    area_id="bedroom",
                )
            ],
        )
        grouper = HaDeviceGrouper(hass)
        result = grouper.list_for_category("light")
        assert result[0].area == "Kitchen"  # group-level uses device.area_id
        # Primary's own area resolves via entity area_id first
        assert result[0].primary.area == "Bedroom"

    def test_no_area_returns_empty_string(self, hass, mock_registries):
        entity_reg, device_reg, _ = mock_registries
        _set_devices(device_reg, [_make_device("dev1")])
        _set_entities(
            entity_reg,
            [_make_entity("light.bulb", device_id="dev1")],
        )
        grouper = HaDeviceGrouper(hass)
        result = grouper.list_for_category("light")
        assert result[0].area == ""


class TestFriendlyNameFallback:
    def test_friendly_name_fallback_chain(self, hass, mock_registries):
        entity_reg, device_reg, _ = mock_registries
        _set_devices(device_reg, [_make_device("dev1")])
        _set_entities(
            entity_reg,
            [
                _make_entity(
                    "light.bulb",
                    device_id="dev1",
                    name=None,
                    original_name="Original Name",
                ),
            ],
        )
        grouper = HaDeviceGrouper(hass)
        result = grouper.list_for_category("light")
        assert result[0].primary.friendly_name == "Original Name"

    def test_name_overrides_original_name(self, hass, mock_registries):
        entity_reg, device_reg, _ = mock_registries
        _set_devices(device_reg, [_make_device("dev1")])
        _set_entities(
            entity_reg,
            [
                _make_entity(
                    "light.bulb",
                    device_id="dev1",
                    name="Custom Name",
                    original_name="Original Name",
                ),
            ],
        )
        grouper = HaDeviceGrouper(hass)
        result = grouper.list_for_category("light")
        assert result[0].primary.friendly_name == "Custom Name"

    def test_entity_id_fallback_when_names_missing(self, hass, mock_registries):
        entity_reg, device_reg, _ = mock_registries
        _set_devices(device_reg, [_make_device("dev1")])
        _set_entities(
            entity_reg,
            [_make_entity("light.bulb", device_id="dev1")],
        )
        grouper = HaDeviceGrouper(hass)
        result = grouper.list_for_category("light")
        assert result[0].primary.friendly_name == "light.bulb"


class TestDeviceNamePriority:
    def test_name_by_user_wins_over_name(self, hass, mock_registries):
        entity_reg, device_reg, _ = mock_registries
        _set_devices(
            device_reg,
            [_make_device("dev1", name="Auto Name", name_by_user="User Name")],
        )
        _set_entities(
            entity_reg,
            [_make_entity("light.bulb", device_id="dev1")],
        )
        grouper = HaDeviceGrouper(hass)
        result = grouper.list_for_category("light")
        assert result[0].name == "User Name"


class TestMultipleNativeSameRole:
    def test_two_native_temperature_sensors(self, hass, mock_registries):
        """Both temperature sensors should appear in linked_native."""
        entity_reg, device_reg, _ = mock_registries
        _set_devices(device_reg, [_make_device("temp_dev")])
        # sensor_temp primary won't accept temperature role (it IS the temp),
        # so use climate as primary to test multiple temperatures as links
        _set_entities(
            entity_reg,
            [
                _make_entity("climate.thermostat", device_id="temp_dev"),
                _make_entity(
                    "sensor.temp_indoor",
                    device_id="temp_dev",
                    original_device_class="temperature",
                ),
                _make_entity(
                    "sensor.temp_outdoor",
                    device_id="temp_dev",
                    original_device_class="temperature",
                ),
            ],
        )
        grouper = HaDeviceGrouper(hass)
        result = grouper.list_for_category("hvac_ac")
        assert len(result) == 1
        group = result[0]
        assert group.primary.entity_id == "climate.thermostat"
        # ClimateEntity.LINKABLE_ROLES = (ROLE_TEMPERATURE,), so both temps
        # should land in linked_native.
        temp_ids = {e.entity_id for e in group.linked_native if e.link_role == "temperature"}
        assert temp_ids == {"sensor.temp_indoor", "sensor.temp_outdoor"}


class TestPreviewForCategory:
    def test_preview_known_device(self, hass, mock_registries):
        entity_reg, device_reg, _ = mock_registries
        _set_devices(device_reg, [_make_device("dev1", name="Lamp")])
        _set_entities(
            entity_reg,
            [_make_entity("light.lamp", device_id="dev1")],
        )
        grouper = HaDeviceGrouper(hass)
        preview = grouper.preview_for_category("dev1", "light")
        assert preview is not None
        assert preview.primary.entity_id == "light.lamp"

    def test_preview_unknown_device_returns_none(self, hass, mock_registries):
        _, device_reg, _ = mock_registries
        _set_devices(device_reg, [])
        grouper = HaDeviceGrouper(hass)
        assert grouper.preview_for_category("missing_id", "light") is None

    def test_preview_wrong_category_returns_none(self, hass, mock_registries):
        entity_reg, device_reg, _ = mock_registries
        _set_devices(device_reg, [_make_device("dev1")])
        _set_entities(
            entity_reg,
            [_make_entity("light.lamp", device_id="dev1")],
        )
        grouper = HaDeviceGrouper(hass)
        # Looking for a climate device when only a light exists
        assert grouper.preview_for_category("dev1", "hvac_ac") is None


class TestSerialization:
    def test_device_group_to_dict_shape(self, hass, mock_registries):
        entity_reg, device_reg, _ = mock_registries
        _set_devices(device_reg, [_make_device("dev1", name="Lamp")])
        _set_entities(
            entity_reg,
            [_make_entity("light.lamp", device_id="dev1")],
        )
        grouper = HaDeviceGrouper(hass)
        result = grouper.list_for_category("light")
        payload = result[0].to_dict()
        assert set(payload.keys()) == {
            "device_id",
            "name",
            "manufacturer",
            "model",
            "area",
            "identifiers",
            "already_exposed",
            "primary",
            "primary_alternatives",
            "linked_native",
            "linked_compatible",
            "unsupported",
        }
        assert isinstance(payload["primary"], dict)
        assert payload["primary"]["role"] == "primary"
        assert payload["primary"]["entity_id"] == "light.lamp"

    def test_grouped_entity_to_dict_shape(self, hass, mock_registries):
        entity_reg, device_reg, _ = mock_registries
        _set_devices(device_reg, [_make_device("dev1")])
        _set_entities(
            entity_reg,
            [_make_entity("light.lamp", device_id="dev1")],
        )
        grouper = HaDeviceGrouper(hass)
        result = grouper.list_for_category("light")
        primary_dict = result[0].primary.to_dict()
        assert set(primary_dict.keys()) == {
            "entity_id",
            "domain",
            "device_class",
            "friendly_name",
            "area",
            "role",
            "sber_category",
            "link_role",
            "is_cross_device",
            "origin_device_id",
            "origin_device_name",
            "already_exposed",
            "preselected",
        }


class TestSorting:
    def test_sorted_by_exposed_then_area_then_name(self, hass, mock_registries):
        entity_reg, device_reg, area_reg = mock_registries
        _set_devices(
            device_reg,
            [
                _make_device("dev_a", name="Alpha", area_id="liv"),
                _make_device("dev_b", name="Bravo", area_id="bed"),
                _make_device("dev_c", name="Charlie", area_id="liv"),
            ],
        )
        _set_areas(
            area_reg,
            [_make_area("liv", "Living Room"), _make_area("bed", "Bedroom")],
        )
        _set_entities(
            entity_reg,
            [
                _make_entity("light.a", device_id="dev_a"),
                _make_entity("light.b", device_id="dev_b"),
                _make_entity("light.c", device_id="dev_c"),
            ],
        )
        # Expose Alpha — should drop to bottom
        grouper = HaDeviceGrouper(hass, exposed_ids={"light.a"})
        result = grouper.list_for_category("light")
        names = [g.name for g in result]
        # Bedroom (Bravo), Living Room (Charlie), then exposed Alpha last
        assert names == ["Bravo", "Charlie", "Alpha"]
