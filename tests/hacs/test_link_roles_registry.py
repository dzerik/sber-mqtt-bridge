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
* MINOR — the ``on_off`` / ``hvac_air_flow_power`` command handlers
  duplicated between ``HvacFanEntity`` and ``HvacAirPurifierEntity``
  moved into ``FanSpeedMixin``.
"""

from __future__ import annotations

import ast
import logging
import pathlib
import sys
import types
from unittest.mock import MagicMock, patch

import pytest

from custom_components.sber_mqtt_bridge._generated.category_features import (
    CATEGORY_REFERENCE_FEATURES,
)
from custom_components.sber_mqtt_bridge.device_grouper import EntityRole, HaDeviceGrouper
from custom_components.sber_mqtt_bridge.devices import base_entity as base_entity_mod
from custom_components.sber_mqtt_bridge.devices.base_entity import (
    ALL_LINKABLE_ROLES,
    ROLE_BATTERY,
    ROLE_BATTERY_LOW,
    SENSOR_LINK_ROLES,
    LinkableRole,
    resolve_link_role,
    resolve_link_role_for,
)
from custom_components.sber_mqtt_bridge.devices.fan_speed_mixin import FanSpeedMixin
from custom_components.sber_mqtt_bridge.devices.hvac_air_purifier import HvacAirPurifierEntity
from custom_components.sber_mqtt_bridge.devices.hvac_fan import HvacFanEntity
from custom_components.sber_mqtt_bridge.devices.intercom import IntercomEntity
from custom_components.sber_mqtt_bridge.devices.on_off_entity import OnOffEntity
from custom_components.sber_mqtt_bridge.devices.relay import RelayEntity
from custom_components.sber_mqtt_bridge.devices.sensor_air import SensorAirEntity
from custom_components.sber_mqtt_bridge.devices.sensor_temp import SensorTempEntity
from custom_components.sber_mqtt_bridge.devices.socket_entity import SocketEntity
from custom_components.sber_mqtt_bridge.sber_entity_map import (
    CATEGORY_DOMAIN_MAP,
    create_sber_entity,
)
from custom_components.sber_mqtt_bridge.websocket_api.devices_grouped import ws_add_ha_device

# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------

_ALL_DEVICE_CLASSES = sorted(
    {spec.cls for spec in CATEGORY_DOMAIN_MAP.values()},
    key=lambda cls: cls.__name__,
)
"""Every concrete device class reachable through the wizard."""

_ON_OFF_CATEGORIES = sorted(cat for cat, spec in CATEGORY_DOMAIN_MAP.items() if issubclass(spec.cls, OnOffEntity))
"""Every Sber category served by an :class:`OnOffEntity` subclass."""

_SENSOR_AIR_LOGGER = "custom_components.sber_mqtt_bridge.devices.sensor_air"


def _states_of(entity) -> dict[str, dict]:
    """Return {feature_key: value_dict} from to_sber_current_state."""
    payload = entity.to_sber_current_state()[entity.entity_id]["states"]
    return {s["key"]: s["value"] for s in payload}


def _reg_entry(entity_id: str, *, device_id: str | None = None, device_class: str | None = None) -> MagicMock:
    """Build a minimal HA entity-registry entry stub."""
    entry = MagicMock()
    entry.entity_id = entity_id
    entry.domain = entity_id.split(".")[0]
    entry.device_id = device_id
    entry.original_device_class = device_class
    entry.name = None
    entry.original_name = entity_id
    entry.area_id = None
    entry.disabled_by = None
    entry.hidden_by = None
    entry.entity_category = None
    entry.platform = "test"
    entry.unique_id = entity_id
    return entry


def _reg_device(device_id: str) -> MagicMock:
    """Build a minimal HA device-registry entry stub."""
    device = MagicMock()
    device.id = device_id
    device.name = device_id
    device.name_by_user = None
    device.manufacturer = ""
    device.model = ""
    device.area_id = None
    device.disabled_by = None
    device.identifiers = set()
    return device


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
        # Exact wizard-path condition (devices_grouped._resolve_role_mapping).
        assert role
        assert role in accepted

        entity.update_linked_data(role, {"state": "812", "attributes": {"device_class": "carbon_dioxide"}})

        assert "co2" in entity.get_final_features_list()
        states = _states_of(entity)
        assert states["co2"] == {"type": "INTEGER", "integer_value": "812"}

    def test_battery_link_role_objects_are_shared_instances(self):
        """SENSOR_LINK_ROLES reuses the module-level ROLE_* constants.

        Identity, not equality: ``LinkableRole`` is a frozen dataclass
        with a generated ``__eq__``, so ``in`` would also accept a
        separately-constructed copy — and a copy is exactly the drift
        this suite exists to prevent (a copy declared inside another
        module would never reach ``ALL_LINKABLE_ROLES``).
        """
        assert any(r is ROLE_BATTERY for r in SENSOR_LINK_ROLES)
        assert any(r is ROLE_BATTERY_LOW for r in SENSOR_LINK_ROLES)
        assert all(any(r is g for g in ALL_LINKABLE_ROLES) for r in SENSOR_LINK_ROLES)

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

    def test_registry_equals_module_level_declarations_in_source_order(self):
        """Every ``LinkableRole`` declared in base_entity.py is registered, in order.

        ``_collect_declared_roles`` scans ``globals()`` *at import time*,
        so it only sees constants bound ABOVE the ``ALL_LINKABLE_ROLES``
        assignment.  A role declared below it would silently vanish from
        the registry — and would only be noticed if some device class
        happened to use it.  This test reads the declaration order
        straight out of the source AST, so both a forgotten registration
        and a reordering of the registry fail loudly.
        """
        source = pathlib.Path(base_entity_mod.__file__).read_text(encoding="utf-8")
        module = ast.parse(source)
        declared: list[str] = []
        for node in module.body:
            if not isinstance(node, ast.Assign) or len(node.targets) != 1:
                continue
            target = node.targets[0]
            value = node.value
            if (
                isinstance(target, ast.Name)
                and isinstance(value, ast.Call)
                and isinstance(value.func, ast.Name)
                and value.func.id == "LinkableRole"
            ):
                declared.append(target.id)

        assert declared, "no module-level LinkableRole declarations found — test is looking at the wrong file"
        expected = tuple(getattr(base_entity_mod, name) for name in declared)
        assert all(isinstance(role, LinkableRole) for role in expected)
        assert expected == ALL_LINKABLE_ROLES, (
            "ALL_LINKABLE_ROLES must equal the module-level LinkableRole "
            f"declarations in source order.\ndeclared: {declared}\n"
            f"registry: {[r.role for r in ALL_LINKABLE_ROLES]}"
        )
        # Identity, not just dataclass equality: the registry must hold the
        # very objects the device classes import.
        for name, role in zip(declared, ALL_LINKABLE_ROLES, strict=True):
            assert getattr(base_entity_mod, name) is role

    def test_aliased_constant_does_not_duplicate_a_role(self):
        """A second module-level name bound to the same role collapses.

        Exercises the de-duplication branch documented on
        ``_collect_declared_roles`` (unreachable with the current module
        contents, so it is injected here rather than left untested).
        """
        base_entity_mod.ROLE_BATTERY_ALIAS = base_entity_mod.ROLE_BATTERY
        try:
            recollected = base_entity_mod._collect_declared_roles()
        finally:
            del base_entity_mod.ROLE_BATTERY_ALIAS
        assert recollected == ALL_LINKABLE_ROLES

    def test_newly_declared_role_is_picked_up(self):
        """``_collect_declared_roles`` really scans — a new constant joins it.

        Guards the collector itself; the module-wide wiring is covered by
        :meth:`test_registry_is_derived_not_hand_written`.
        """
        extra = LinkableRole("moisture_probe", frozenset({"sensor"}), frozenset({"moisture"}))
        base_entity_mod.ROLE_MOISTURE_PROBE = extra
        try:
            recollected = base_entity_mod._collect_declared_roles()
        finally:
            del base_entity_mod.ROLE_MOISTURE_PROBE
        assert recollected[-1] is extra
        assert recollected[: len(ALL_LINKABLE_ROLES)] == ALL_LINKABLE_ROLES

    def test_registry_is_derived_not_hand_written(self):
        """A role declared in the module lands in ``ALL_LINKABLE_ROLES`` itself.

        ``ALL_LINKABLE_ROLES`` is built once at import time, so injecting
        a constant into the already-imported module proves nothing about
        the binding.  Instead the module source is re-executed in a fresh
        namespace with one extra role declared just above the registry
        assignment: with the derived form the role shows up, with a
        hand-maintained tuple (the shape that produced the original
        drift, six air roles silently missing) it does not.
        """
        source = pathlib.Path(base_entity_mod.__file__).read_text(encoding="utf-8")
        anchor = "ALL_LINKABLE_ROLES: tuple[LinkableRole, ...] ="
        assert source.count(anchor) == 1, "registry assignment moved — update this test"
        probe = (
            'ROLE_DERIVATION_PROBE = LinkableRole("derivation_probe", frozenset({"sensor"}), frozenset({"probe"}))\n'
        )
        patched = source.replace(anchor, probe + anchor, 1)

        probe_name = f"{base_entity_mod.__name__}_derivation_probe"
        probe_module = types.ModuleType(probe_name)
        probe_module.__file__ = base_entity_mod.__file__
        probe_module.__package__ = base_entity_mod.__package__
        # ``@dataclass(slots=True)`` resolves its own module via sys.modules.
        sys.modules[probe_name] = probe_module
        try:
            exec(compile(patched, base_entity_mod.__file__, "exec"), probe_module.__dict__)  # noqa: S102
            roles = [r.role for r in probe_module.ALL_LINKABLE_ROLES]
        finally:
            del sys.modules[probe_name]

        assert "derivation_probe" in roles, (
            "ALL_LINKABLE_ROLES ignored a role declared above it — the registry "
            f"is no longer derived from the module contents. Got: {roles}"
        )
        # ...and it did not lose anything on the way.
        assert set(roles) == {r.role for r in ALL_LINKABLE_ROLES} | {"derivation_probe"}


# ---------------------------------------------------------------------------
#  MINOR: the _supports_* escape hatch must stay inside the Sber spec
# ---------------------------------------------------------------------------


class TestOnOffFlagsMatchSberSpec:
    """``_supports_energy`` / ``_supports_child_lock`` are spec-derived, not free.

    The old frozenset gates were a hard boundary derived from the Sber
    functions catalog (issue #44: ``relay`` has no ``child_lock``,
    ``intercom`` has no power/voltage/current).  Replacing them with
    overridable flags removed that boundary from the code, so it is
    re-established here against the generated spec table — a subclass
    that opts into a feature its category does not declare now fails.
    """

    @staticmethod
    def _entity(category: str):
        entity = create_sber_entity(
            "switch.spec_probe",
            {"entity_id": "switch.spec_probe", "name": "Probe"},
            sber_category=category,
        )
        assert entity is not None, f"CATEGORY_DOMAIN_MAP[{category!r}] did not produce an entity"
        assert entity.category == category
        return entity

    def test_discovery_found_the_known_on_off_categories(self):
        """Sanity: the parametrization is not silently empty."""
        assert set(_ON_OFF_CATEGORIES) >= {"relay", "socket", "intercom"}

    @pytest.mark.parametrize("category", _ON_OFF_CATEGORIES)
    def test_energy_flag_matches_reference_features(self, category):
        entity = self._entity(category)
        reference = CATEGORY_REFERENCE_FEATURES[category]
        expected = {"power", "voltage", "current"} <= reference
        assert entity._supports_energy is expected, (
            f"{type(entity).__name__} (_supports_energy={entity._supports_energy}) disagrees with the Sber "
            f"spec for {category!r}: {sorted(reference)}"
        )

    @pytest.mark.parametrize("category", _ON_OFF_CATEGORIES)
    def test_child_lock_flag_matches_reference_features(self, category):
        entity = self._entity(category)
        reference = CATEGORY_REFERENCE_FEATURES[category]
        expected = "child_lock" in reference
        assert entity._supports_child_lock is expected, (
            f"{type(entity).__name__} (_supports_child_lock={entity._supports_child_lock}) disagrees with the "
            f"Sber spec for {category!r}: {sorted(reference)}"
        )

    @pytest.mark.parametrize("category", _ON_OFF_CATEGORIES)
    def test_emitted_energy_and_lock_features_are_in_the_spec(self, category):
        """Behavioral counterpart: what reaches the wire stays inside the spec.

        Feeds every gated HA attribute at once and checks the published
        feature list AND state payload — catches a flag override as well
        as a gate bypassed inside ``_create_features_list``.
        """
        gated = {"power", "voltage", "current", "child_lock"}
        entity = self._entity(category)
        entity.fill_by_ha_state(
            {"state": "on", "attributes": {"power": 100, "voltage": 230, "current": 1, "child_lock": True}}
        )
        reference = CATEGORY_REFERENCE_FEATURES[category]

        emitted_features = gated & set(entity.get_final_features_list())
        emitted_states = gated & set(_states_of(entity))
        assert emitted_features <= reference, (
            f"{category}: features outside spec: {sorted(emitted_features - reference)}"
        )
        assert emitted_states <= reference, f"{category}: states outside spec: {sorted(emitted_states - reference)}"
        # And the spec-allowed ones are actually emitted, so the assertion
        # above cannot pass by emitting nothing at all.
        assert emitted_features == gated & reference


# ---------------------------------------------------------------------------
#  SensorAir: diagnostics for an unroutable primary device_class
# ---------------------------------------------------------------------------


class TestSensorAirPrimaryDiagnostics:
    """``_store_measurement``'s return value drives the debug log."""

    def test_unknown_primary_device_class_is_logged(self, caplog):
        entity = SensorAirEntity({"entity_id": "sensor.weird", "name": "Weird"})
        with caplog.at_level(logging.DEBUG, logger=_SENSOR_AIR_LOGGER):
            entity.fill_by_ha_state({"state": "5", "attributes": {"device_class": "illuminance"}})
        messages = [r.getMessage() for r in caplog.records if r.name == _SENSOR_AIR_LOGGER]
        assert any("no measurement mapping" in m and "sensor.weird" in m and "illuminance" in m for m in messages), (
            f"expected a diagnostic for the unroutable device_class, got: {messages}"
        )

    @pytest.mark.parametrize("device_class", ["carbon_dioxide", "pm25", "volatile_organic_compounds"])
    def test_routable_primary_device_class_is_not_logged(self, caplog, device_class):
        """A successfully routed primary must stay quiet (no log spam per state change)."""
        entity = SensorAirEntity({"entity_id": "sensor.air", "name": "Air"})
        with caplog.at_level(logging.DEBUG, logger=_SENSOR_AIR_LOGGER):
            entity.fill_by_ha_state({"state": "500", "attributes": {"device_class": device_class}})
        messages = [r.getMessage() for r in caplog.records if r.name == _SENSOR_AIR_LOGGER]
        assert not [m for m in messages if "no measurement mapping" in m], messages


# ---------------------------------------------------------------------------
#  Wizard-level: the air roles must survive the real HaDeviceGrouper /
#  ws_add_ha_device call sites, not just resolve_link_role in isolation.
# ---------------------------------------------------------------------------


@pytest.fixture
def grouper_registries():
    """Patch the three HA registries used by :class:`HaDeviceGrouper`."""
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
        area_reg.async_get_area.side_effect = lambda aid: None
        mock_ar.async_get.return_value = area_reg
        yield entity_reg, device_reg


class TestSensorAirWizardClassification:
    """``HaDeviceGrouper`` must offer air siblings as links, not as junk."""

    def test_same_device_air_siblings_are_linked_or_alternative_never_unsupported(self, grouper_registries):
        """HCHO/temperature/humidity siblings become links with the right roles.

        Before the registry fix ``resolve_link_role`` did not know the
        air roles, so ``sensor.hcho`` landed in ``unsupported`` and the
        user could not attach it at all.  ``pm25``/``tvoc`` are valid
        ``sensor_air`` primaries themselves, so by design they surface as
        primary alternatives instead of links.
        """
        entity_reg, device_reg = grouper_registries
        device_reg.devices = {"dev_air": _reg_device("dev_air")}
        entries = [
            _reg_entry("sensor.co2", device_id="dev_air", device_class="carbon_dioxide"),
            _reg_entry("sensor.pm25", device_id="dev_air", device_class="pm25"),
            _reg_entry("sensor.hcho", device_id="dev_air", device_class="volatile_organic_compounds_parts"),
            _reg_entry("sensor.temp", device_id="dev_air", device_class="temperature"),
            _reg_entry("sensor.hum", device_id="dev_air", device_class="humidity"),
            _reg_entry("sensor.bat", device_id="dev_air", device_class="battery"),
        ]
        entity_reg.entities = {e.entity_id: e for e in entries}

        groups = HaDeviceGrouper(MagicMock()).list_for_category("sensor_air")

        assert len(groups) == 1
        group = groups[0]
        assert group.primary.entity_id == "sensor.co2"
        assert group.primary.role == EntityRole.PRIMARY
        assert {e.entity_id: e.link_role for e in group.linked_native} == {
            "sensor.hcho": "hcho",
            "sensor.temp": "temperature",
            "sensor.hum": "humidity",
            "sensor.bat": "battery",
        }
        assert [e.entity_id for e in group.primary_alternatives] == ["sensor.pm25"]
        assert group.unsupported == []

    def test_cross_device_co2_is_offered_as_a_compatible_link(self, grouper_registries):
        """The cross-device index is a second, independent resolve_link_role caller.

        ``_build_role_index`` resolves EVERY entity in the registry, so a
        CO2/PM sensor living on another HA device is only offered when
        the global registry knows the air roles.
        """
        entity_reg, device_reg = grouper_registries
        device_reg.devices = {"dev_primary": _reg_device("dev_primary"), "dev_other": _reg_device("dev_other")}
        entries = [
            _reg_entry("sensor.tvoc", device_id="dev_primary", device_class="volatile_organic_compounds"),
            _reg_entry("sensor.remote_co2", device_id="dev_other", device_class="carbon_dioxide"),
            _reg_entry("sensor.remote_pm10", device_id="dev_other", device_class="pm10"),
        ]
        entity_reg.entities = {e.entity_id: e for e in entries}

        groups = {g.primary.entity_id: g for g in HaDeviceGrouper(MagicMock()).list_for_category("sensor_air")}

        group = groups["sensor.tvoc"]
        assert {e.entity_id: e.link_role for e in group.linked_compatible} == {
            "sensor.remote_co2": "co2",
            "sensor.remote_pm10": "pm10",
        }
        # Cross-device suggestions are opt-in, unlike same-device siblings.
        assert all(e.preselected is False for e in group.linked_compatible)


class TestAddHaDeviceAcceptsAirLinks:
    """``ws_add_ha_device`` must persist an air link, not reject it."""

    @staticmethod
    def _ws_context(entries):
        entry = MagicMock()
        entry.entry_id = "test_entry"
        entry.options = {}
        entity_reg = MagicMock()
        by_id = {e.entity_id: e for e in entries}
        entity_reg.async_get.side_effect = by_id.get
        return entry, entity_reg

    @pytest.mark.asyncio
    async def test_co2_and_pm_links_are_stored_by_role(self):
        primary = _reg_entry("sensor.tvoc", device_id="dev1", device_class="volatile_organic_compounds")
        co2 = _reg_entry("sensor.co2", device_id="dev1", device_class="carbon_dioxide")
        pm10 = _reg_entry("sensor.pm10", device_id="dev1", device_class="pm10")
        entry, entity_reg = self._ws_context([primary, co2, pm10])
        hass = MagicMock()
        hass.config_entries.async_update_entry = MagicMock()
        connection = MagicMock()

        with (
            patch(
                "custom_components.sber_mqtt_bridge.websocket_api.devices_grouped.get_config_entry",
                return_value=entry,
            ),
            patch("homeassistant.helpers.entity_registry.async_get", return_value=entity_reg),
        ):
            await ws_add_ha_device.__wrapped__(
                hass,
                connection,
                {
                    "id": 1,
                    "device_id": "dev1",
                    "primary_entity_id": "sensor.tvoc",
                    "category": "sensor_air",
                    "linked_entity_ids": ["sensor.co2", "sensor.pm10"],
                },
            )

        assert connection.send_error.call_args_list == []
        payload = connection.send_result.call_args[0][1]
        assert payload["linked_count"] == 2
        options = hass.config_entries.async_update_entry.call_args[1]["options"]
        assert options["entity_links"]["sensor.tvoc"] == {
            "co2": "sensor.co2",
            "pm10": "sensor.pm10",
        }
        assert "sensor.tvoc" in options["exposed_entities"]

    @pytest.mark.asyncio
    async def test_link_rejected_when_primary_does_not_accept_the_role(self):
        """A CO2 sensor linked to a light is still refused (roles are per class)."""
        primary = _reg_entry("light.lamp", device_id="dev1")
        co2 = _reg_entry("sensor.co2", device_id="dev1", device_class="carbon_dioxide")
        entry, entity_reg = self._ws_context([primary, co2])
        hass = MagicMock()
        connection = MagicMock()

        with (
            patch(
                "custom_components.sber_mqtt_bridge.websocket_api.devices_grouped.get_config_entry",
                return_value=entry,
            ),
            patch("homeassistant.helpers.entity_registry.async_get", return_value=entity_reg),
        ):
            await ws_add_ha_device.__wrapped__(
                hass,
                connection,
                {
                    "id": 2,
                    "device_id": "dev1",
                    "primary_entity_id": "light.lamp",
                    "category": "light",
                    "linked_entity_ids": ["sensor.co2"],
                },
            )

        connection.send_error.assert_called_once()
        assert connection.send_error.call_args[0][1] == "linked_role_not_accepted"


# ---------------------------------------------------------------------------
#  MINOR: fan command handlers live in FanSpeedMixin, not copy-pasted
# ---------------------------------------------------------------------------


_FAN_ENTITY_CLASSES = [HvacFanEntity, HvacAirPurifierEntity]


class TestFanCommandHandlersAreShared:
    """``hvac_fan`` and ``hvac_air_purifier`` share one implementation."""

    @pytest.mark.parametrize("cls", _FAN_ENTITY_CLASSES, ids=lambda c: c.__name__)
    def test_handlers_are_the_mixin_functions(self, cls):
        """Re-introducing a per-class copy fails here."""
        assert cls._cmd_on_off is FanSpeedMixin._cmd_on_off
        assert cls._cmd_air_flow_power is FanSpeedMixin._cmd_air_flow_power

    @pytest.mark.parametrize("cls", _FAN_ENTITY_CLASSES, ids=lambda c: c.__name__)
    def test_on_off_command_calls_fan_domain(self, cls):
        entity = cls({"entity_id": "fan.f", "name": "F"})
        entity.fill_by_ha_state({"state": "off", "attributes": {}})
        calls = entity.process_cmd({"states": [{"key": "on_off", "value": {"type": "BOOL", "bool_value": True}}]})
        assert [(c["url"]["domain"], c["url"]["service"], c["url"]["target"]) for c in calls] == [
            ("fan", "turn_on", {"entity_id": "fan.f"})
        ]

    @pytest.mark.parametrize("cls", _FAN_ENTITY_CLASSES, ids=lambda c: c.__name__)
    def test_speed_command_uses_preset_mode_when_available(self, cls):
        entity = cls({"entity_id": "fan.f", "name": "F"})
        entity.fill_by_ha_state({"state": "on", "attributes": {"preset_modes": ["low", "turbo"], "percentage": 50}})
        calls = entity.process_cmd(
            {"states": [{"key": "hvac_air_flow_power", "value": {"type": "ENUM", "enum_value": "turbo"}}]}
        )
        assert [(c["url"]["service"], c["url"].get("service_data")) for c in calls] == [
            ("set_preset_mode", {"preset_mode": "turbo"})
        ]

    @pytest.mark.parametrize("cls", _FAN_ENTITY_CLASSES, ids=lambda c: c.__name__)
    def test_speed_command_falls_back_to_percentage(self, cls):
        entity = cls({"entity_id": "fan.f", "name": "F"})
        entity.fill_by_ha_state({"state": "on", "attributes": {"percentage": 50}})
        calls = entity.process_cmd(
            {"states": [{"key": "hvac_air_flow_power", "value": {"type": "ENUM", "enum_value": "low"}}]}
        )
        assert [(c["url"]["service"], c["url"].get("service_data")) for c in calls] == [
            ("set_percentage", {"percentage": 25})
        ]

    @pytest.mark.parametrize("cls", _FAN_ENTITY_CLASSES, ids=lambda c: c.__name__)
    @pytest.mark.parametrize(
        ("key", "value"),
        [
            ("on_off", {"type": "ENUM", "enum_value": "on"}),
            ("hvac_air_flow_power", {"type": "BOOL", "bool_value": True}),
        ],
    )
    def test_wrong_value_type_is_ignored(self, cls, key, value):
        """Type guards survived the move into the mixin."""
        entity = cls({"entity_id": "fan.f", "name": "F"})
        entity.fill_by_ha_state({"state": "on", "attributes": {"percentage": 50}})
        assert entity.process_cmd({"states": [{"key": key, "value": value}]}) == []


# ---------------------------------------------------------------------------
#  MINOR: one °F rule for every class that emits `temperature`
# ---------------------------------------------------------------------------


class TestTemperatureUnitRuleIsShared:
    """SensorTemp and SensorAir must agree on unit detection AND conversion.

    Both categories publish ``temperature`` (``°C × 10``) plus
    ``temp_unit_view``.  They used to carry two independent copies of
    the ``"°F"`` check and of the ``(t - 32) * 5 / 9`` formula, so a
    change to one shipped a silent ~50°C discrepancy on the other.
    """

    @staticmethod
    def _air_wire(state: str, unit: str | None) -> tuple[int, str]:
        entity = SensorAirEntity({"entity_id": "sensor.air", "name": "Air"})
        attributes: dict = {"device_class": "temperature"}
        if unit is not None:
            attributes["unit_of_measurement"] = unit
        entity.fill_by_ha_state({"state": state, "attributes": attributes})
        states = _states_of(entity)
        return int(states["temperature"]["integer_value"]), states["temp_unit_view"]["enum_value"]

    @staticmethod
    def _temp_wire(state: str, unit: str | None) -> tuple[int, str]:
        entity = SensorTempEntity({"entity_id": "sensor.t", "name": "T"})
        attributes: dict = {}
        if unit is not None:
            attributes["unit_of_measurement"] = unit
        entity.fill_by_ha_state({"state": state, "attributes": attributes})
        states = _states_of(entity)
        return int(states["temperature"]["integer_value"]), states["temp_unit_view"]["enum_value"]

    @pytest.mark.parametrize(
        ("state", "unit", "expected"),
        [
            ("72", "°F", (222, "f")),
            ("-40", "°F", (-400, "f")),
            ("22.5", "°C", (225, "c")),
            ("22.5", None, (225, "c")),
            # Not the exact HA unit string → no conversion (documented rule).
            ("72", "F", (720, "c")),
        ],
    )
    def test_both_categories_produce_the_same_wire_values(self, state, unit, expected):
        air = self._air_wire(state, unit)
        temp = self._temp_wire(state, unit)
        assert air == expected
        assert temp == expected

    def test_linked_air_temperature_uses_the_same_rule(self):
        """The third ingestion path (linked companion) must not drift either."""
        entity = SensorAirEntity({"entity_id": "sensor.air", "name": "Air"})
        entity.update_linked_data(
            "temperature",
            {"state": "72", "attributes": {"unit_of_measurement": "°F"}},
        )
        states = _states_of(entity)
        assert int(states["temperature"]["integer_value"]) == 222
        assert states["temp_unit_view"]["enum_value"] == "f"

    @pytest.mark.parametrize("cls", _FAN_ENTITY_CLASSES, ids=lambda c: c.__name__)
    @pytest.mark.parametrize("enum_value", ["", "hurricane", None])
    def test_unknown_or_empty_speed_produces_no_service_call(self, cls, enum_value):
        """An unmapped Sber speed must be dropped, not guessed at."""
        entity = cls({"entity_id": "fan.f", "name": "F"})
        entity.fill_by_ha_state({"state": "on", "attributes": {"percentage": 50}})
        value: dict = {"type": "ENUM"}
        if enum_value is not None:
            value["enum_value"] = enum_value
        assert entity.process_cmd({"states": [{"key": "hvac_air_flow_power", "value": value}]}) == []

    @pytest.mark.parametrize("cls", _FAN_ENTITY_CLASSES, ids=lambda c: c.__name__)
    def test_auto_speed_turns_on_without_a_percentage(self, cls):
        """'auto' maps to plain fan.turn_on (percentage 0 would mean 'off')."""
        entity = cls({"entity_id": "fan.f", "name": "F"})
        entity.fill_by_ha_state({"state": "on", "attributes": {"percentage": 50}})
        calls = entity.process_cmd(
            {"states": [{"key": "hvac_air_flow_power", "value": {"type": "ENUM", "enum_value": "auto"}}]}
        )
        assert len(calls) == 1
        url = calls[0]["url"]
        assert (url["domain"], url["service"], url["target"]) == ("fan", "turn_on", {"entity_id": "fan.f"})
        assert "service_data" not in url
