"""Tests for the link-role registry and W3A device-class fixes.

Covers the review findings of wave W3A:

* MAJOR — ``ALL_LINKABLE_ROLES`` drifting out of sync with per-class
  ``LINKABLE_ROLES`` (air-quality roles were missing, so the wizard path
  ``resolve_link_role`` rejected CO2/PM/TVOC/HCHO siblings while
  ``auto_link_all`` accepted them).  The anti-regress tests here walk
  every device class registered in ``CATEGORY_DOMAIN_MAP`` so a NEW
  class with a NEW role that is not in the global registry fails loudly.
* MINOR — ``OnOffEntity`` category-frozenset gates replaced with
  overridable ``_supports_energy`` / ``_supports_child_lock`` flags.
* MINOR — ``SensorAirEntity`` °F detection/conversion deduplicated into
  a single ``_store_measurement`` path shared by primary and linked
  ingestion.
* MINOR — dead ``rgb_color`` / ``xy_color`` parsing removed from
  ``LightEntity`` (covered in ``test_devices_light.py``).
"""

from __future__ import annotations

import pytest

from custom_components.sber_mqtt_bridge.devices.base_entity import (
    ALL_LINKABLE_ROLES,
    ROLE_BATTERY,
    ROLE_BATTERY_LOW,
    SENSOR_LINK_ROLES,
    LinkableRole,
    resolve_link_role,
    resolve_link_role_for,
)
from custom_components.sber_mqtt_bridge.devices.intercom import IntercomEntity
from custom_components.sber_mqtt_bridge.devices.relay import RelayEntity
from custom_components.sber_mqtt_bridge.devices.sensor_air import SensorAirEntity
from custom_components.sber_mqtt_bridge.devices.socket_entity import SocketEntity
from custom_components.sber_mqtt_bridge.sber_entity_map import CATEGORY_DOMAIN_MAP

# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------

_ALL_DEVICE_CLASSES = sorted(
    {spec.cls for spec in CATEGORY_DOMAIN_MAP.values()},
    key=lambda cls: cls.__name__,
)
"""Every concrete device class reachable through the wizard."""


def _states_of(entity) -> dict[str, dict]:
    """Return {feature_key: value_dict} from to_sber_current_state."""
    payload = entity.to_sber_current_state()[entity.entity_id]["states"]
    return {s["key"]: s["value"] for s in payload}


# ---------------------------------------------------------------------------
#  MAJOR: single registry — anti-regress over ALL device classes
# ---------------------------------------------------------------------------


class TestGlobalRegistryCoversEveryDeviceClass:
    """A role declared by ANY device class must be resolvable globally."""

    @pytest.mark.parametrize("cls", _ALL_DEVICE_CLASSES, ids=lambda c: c.__name__)
    def test_every_class_role_is_in_global_registry(self, cls):
        """Each LINKABLE_ROLES entry of each class exists in ALL_LINKABLE_ROLES.

        A new device class introducing a role that is not registered in
        ``base_entity`` breaks the wizard (resolve_link_role returns "")
        — this test makes that a hard failure.
        """
        global_names = {r.role for r in ALL_LINKABLE_ROLES}
        missing = {r.role for r in cls.LINKABLE_ROLES} - global_names
        assert not missing, f"{cls.__name__} declares roles unknown to ALL_LINKABLE_ROLES: {sorted(missing)}"

    @pytest.mark.parametrize("cls", _ALL_DEVICE_CLASSES, ids=lambda c: c.__name__)
    def test_wizard_resolution_agrees_with_class_roles(self, cls):
        """For every (domain, device_class) a class accepts, the wizard path agrees.

        This is the exact invariant ``devices_grouped.add_ha_device`` and
        ``device_grouper`` rely on: ``resolve_link_role(domain, dc)`` must
        return a role name that the primary's ``LINKABLE_ROLES`` accepts.
        Catches both missing registrations AND shadowing (an earlier
        global role hijacking the same (domain, device_class) pair).
        """
        accepted = {r.role for r in cls.LINKABLE_ROLES}
        for role in cls.LINKABLE_ROLES:
            for domain in role.domains:
                for dc in role.device_classes:
                    resolved = resolve_link_role(domain, dc)
                    assert resolved, f"{cls.__name__}: ({domain}, {dc}) resolves to nothing globally"
                    assert resolved in accepted, (
                        f"{cls.__name__}: ({domain}, {dc}) resolves to {resolved!r} "
                        f"which the class does not accept ({sorted(accepted)})"
                    )

    def test_registry_has_no_duplicate_role_names(self):
        """Auto-collected registry must not contain two roles with one name."""
        names = [r.role for r in ALL_LINKABLE_ROLES]
        assert len(names) == len(set(names))

    def test_registry_has_no_ambiguous_matches(self):
        """No (domain, device_class) pair may match two different global roles.

        First-match iteration in ``resolve_link_role_for`` is only safe
        while matches stay unambiguous.
        """
        seen: dict[tuple[str, str], str] = {}
        for role in ALL_LINKABLE_ROLES:
            for domain in role.domains:
                for dc in role.device_classes:
                    prev = seen.setdefault((domain, dc), role.role)
                    assert prev == role.role, f"({domain}, {dc}) matches both {prev!r} and {role.role!r}"


class TestResolveLinkRoleAirRoles:
    """resolve_link_role must know the six air-quality roles (the MAJOR bug)."""

    @pytest.mark.parametrize(
        ("domain", "device_class", "expected"),
        [
            ("sensor", "carbon_dioxide", "co2"),
            ("sensor", "pm1", "pm1"),
            ("sensor", "pm25", "pm25"),
            ("sensor", "pm10", "pm10"),
            ("sensor", "volatile_organic_compounds", "tvoc"),
            ("sensor", "volatile_organic_compounds_parts", "hcho"),
            # Pre-existing roles must keep resolving (incl. domain disambiguation)
            ("sensor", "battery", "battery"),
            ("binary_sensor", "battery", "battery_low"),
            ("sensor", "signal_strength", "signal_strength"),
            ("sensor", "temperature", "temperature"),
            ("sensor", "humidity", "humidity"),
        ],
    )
    def test_resolves(self, domain, device_class, expected):
        assert resolve_link_role(domain, device_class) == expected

    @pytest.mark.parametrize(
        ("domain", "device_class"),
        [
            ("sensor", "nonexistent_class"),
            ("binary_sensor", "carbon_dioxide"),  # wrong domain for co2
            ("", ""),
            ("sensor", ""),
        ],
    )
    def test_no_match_returns_empty(self, domain, device_class):
        assert resolve_link_role(domain, device_class) == ""

    def test_resolve_for_respects_the_accepted_subset(self):
        """resolve_link_role_for must not invent roles outside the given set.

        A light only accepts battery/battery_low/signal — a CO2 sensor
        must NOT resolve against it even though co2 is globally known.
        """
        assert resolve_link_role_for(SENSOR_LINK_ROLES, "sensor", "carbon_dioxide") == ""
        assert resolve_link_role_for(SENSOR_LINK_ROLES, "sensor", "battery") == "battery"
        assert resolve_link_role_for((), "sensor", "battery") == ""

    def test_global_resolver_delegates_to_single_implementation(self):
        """Global and per-set resolution give identical answers on the registry."""
        for role in ALL_LINKABLE_ROLES:
            for domain in role.domains:
                for dc in role.device_classes:
                    assert resolve_link_role(domain, dc) == resolve_link_role_for(ALL_LINKABLE_ROLES, domain, dc)


class TestCo2LinkPassesWizardValidation:
    """End-to-end (minus HA registries): CO2 sensor links into sensor_air."""

    def test_co2_sibling_is_accepted_and_lands_on_the_wire(self):
        """The wizard validation condition passes AND the value reaches Sber payload.

        Mirrors ``devices_grouped._resolve_role_mapping``: role must be
        non-empty and inside the primary's accepted role names.  Then the
        linked update must actually surface in feature list and state.
        """
        entity = SensorAirEntity({"entity_id": "sensor.air_temp", "name": "Air"})
        entity.fill_by_ha_state(
            {"state": "21.5", "attributes": {"device_class": "temperature", "unit_of_measurement": "°C"}}
        )

        role = resolve_link_role("sensor", "carbon_dioxide")
        accepted = {r.role for r in SensorAirEntity.LINKABLE_ROLES}
        assert role and role in accepted  # exact wizard-path condition

        entity.update_linked_data(role, {"state": "812", "attributes": {"device_class": "carbon_dioxide"}})

        assert "co2" in entity.get_final_features_list()
        states = _states_of(entity)
        assert states["co2"] == {"type": "INTEGER", "integer_value": "812"}

    def test_battery_link_role_objects_are_shared_instances(self):
        """SENSOR_LINK_ROLES reuses the module-level ROLE_* constants."""
        assert ROLE_BATTERY in SENSOR_LINK_ROLES
        assert ROLE_BATTERY_LOW in SENSOR_LINK_ROLES

    def test_unknown_role_update_is_ignored_gracefully(self):
        """A bogus role must not crash nor create phantom measurements."""
        entity = SensorAirEntity({"entity_id": "sensor.air", "name": "Air"})
        entity.fill_by_ha_state({"state": "400", "attributes": {"device_class": "carbon_dioxide"}})
        entity.update_linked_data("bogus_role", {"state": "999", "attributes": {}})
        states = _states_of(entity)
        assert states["co2"] == {"type": "INTEGER", "integer_value": "400"}
        assert set(states) == {"online", "co2"}


# ---------------------------------------------------------------------------
#  MINOR: SensorAir — one °F conversion path for primary and linked data
# ---------------------------------------------------------------------------


class TestSensorAirTemperaturePaths:
    """Primary (device_class) and linked (role) ingestion must be identical."""

    @staticmethod
    def _f_state() -> dict:
        return {"state": "72", "attributes": {"device_class": "temperature", "unit_of_measurement": "°F"}}

    def test_fahrenheit_identical_via_primary_and_linked(self):
        primary = SensorAirEntity({"entity_id": "sensor.a", "name": "A"})
        primary.fill_by_ha_state(self._f_state())

        linked = SensorAirEntity({"entity_id": "sensor.b", "name": "B"})
        linked.fill_by_ha_state({"state": "500", "attributes": {"device_class": "carbon_dioxide"}})
        linked.update_linked_data("temperature", self._f_state())

        s_primary = _states_of(primary)
        s_linked = _states_of(linked)
        # 72°F = 22.22°C → wire 222 (°C × 10), NOT 720.
        assert s_primary["temperature"] == {"type": "INTEGER", "integer_value": "222"}
        assert s_linked["temperature"] == s_primary["temperature"]
        assert s_primary["temp_unit_view"]["enum_value"] == "f"
        assert s_linked["temp_unit_view"]["enum_value"] == "f"

    def test_celsius_default_no_conversion(self):
        entity = SensorAirEntity({"entity_id": "sensor.a", "name": "A"})
        entity.update_linked_data("temperature", {"state": "22.5", "attributes": {}})
        states = _states_of(entity)
        assert states["temperature"] == {"type": "INTEGER", "integer_value": "225"}
        assert states["temp_unit_view"]["enum_value"] == "c"

    def test_device_class_alias_routes_to_same_field_as_role(self):
        """'carbon_dioxide' (device_class) and 'co2' (role) share one field."""
        entity = SensorAirEntity({"entity_id": "sensor.a", "name": "A"})
        entity.fill_by_ha_state({"state": "400", "attributes": {"device_class": "carbon_dioxide"}})
        entity.update_linked_data("co2", {"state": "999", "attributes": {}})
        assert _states_of(entity)["co2"] == {"type": "INTEGER", "integer_value": "999"}

    def test_unparseable_linked_state_clears_measurement(self):
        entity = SensorAirEntity({"entity_id": "sensor.a", "name": "A"})
        entity.update_linked_data("co2", {"state": "500", "attributes": {}})
        entity.update_linked_data("co2", {"state": "unavailable", "attributes": {}})
        assert "co2" not in _states_of(entity)

    def test_primary_without_device_class_degrades_gracefully(self):
        entity = SensorAirEntity({"entity_id": "sensor.a", "name": "A"})
        entity.fill_by_ha_state({"state": "42", "attributes": {}})
        assert set(_states_of(entity)) == {"online"}


# ---------------------------------------------------------------------------
#  MINOR: OnOffEntity — overridable capability flags instead of frozensets
# ---------------------------------------------------------------------------


def _on_state(**extra_attrs) -> dict:
    return {"state": "on", "attributes": dict(extra_attrs)}


class TestOnOffCapabilityFlags:
    """Energy / child_lock gating still works and is now overridable."""

    def test_relay_reports_energy_but_not_child_lock(self):
        entity = RelayEntity({"entity_id": "switch.r", "name": "R"})
        entity.fill_by_ha_state(_on_state(power=100, voltage=230, current=1, child_lock=True))
        features = entity.get_final_features_list()
        states = _states_of(entity)
        assert {"power", "voltage", "current"} <= set(features)
        assert "child_lock" not in features
        assert states["power"] == {"type": "INTEGER", "integer_value": "100"}
        assert "child_lock" not in states

    def test_socket_reports_child_lock_and_energy(self):
        entity = SocketEntity({"entity_id": "switch.s", "name": "S"})
        entity.fill_by_ha_state(_on_state(power=50, child_lock=True))
        features = entity.get_final_features_list()
        states = _states_of(entity)
        assert "child_lock" in features
        assert "power" in features
        assert states["child_lock"] == {"type": "BOOL", "bool_value": True}

    def test_intercom_never_reports_energy_or_child_lock(self):
        """Category outside relay/socket must not leak energy states (Sber rejects)."""
        entity = IntercomEntity({"entity_id": "switch.i", "name": "I"})
        entity.fill_by_ha_state(_on_state(power=100, voltage=230, current=1, child_lock=True))
        features = entity.get_final_features_list()
        states = _states_of(entity)
        assert not {"power", "voltage", "current", "child_lock"} & set(features)
        assert not {"power", "voltage", "current", "child_lock"} & set(states)

    def test_subclass_can_opt_out_of_energy(self):
        """The flag is a real extension point: shadowing it changes behavior."""

        class _NoEnergyRelay(RelayEntity):
            _supports_energy = False

        entity = _NoEnergyRelay({"entity_id": "switch.r", "name": "R"})
        entity.fill_by_ha_state(_on_state(power=100))
        assert "power" not in entity.get_final_features_list()
        assert "power" not in _states_of(entity)

    def test_subclass_can_opt_in_child_lock(self):
        """A future kettle-like OnOff subclass enables child_lock without base edits."""

        class _LockableRelay(RelayEntity):
            _supports_child_lock = True

        entity = _LockableRelay({"entity_id": "switch.k", "name": "K"})
        entity.fill_by_ha_state(_on_state(child_lock=False))
        assert "child_lock" in entity.get_final_features_list()
        assert _states_of(entity)["child_lock"] == {"type": "BOOL", "bool_value": False}


# ---------------------------------------------------------------------------
#  Registry construction sanity
# ---------------------------------------------------------------------------


class TestRegistryConstruction:
    """ALL_LINKABLE_ROLES is derived, ordered, and complete."""

    def test_contains_all_eleven_known_roles(self):
        assert {r.role for r in ALL_LINKABLE_ROLES} == {
            "battery",
            "battery_low",
            "signal_strength",
            "temperature",
            "humidity",
            "co2",
            "pm1",
            "pm25",
            "pm10",
            "tvoc",
            "hcho",
        }

    def test_all_entries_are_linkable_roles(self):
        assert all(isinstance(r, LinkableRole) for r in ALL_LINKABLE_ROLES)
