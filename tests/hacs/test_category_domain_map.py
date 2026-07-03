"""Unit tests for CATEGORY_DOMAIN_MAP + CategorySpec + categories_for_domain.

These tests enforce the source-of-truth contract between Sber categories
and HA (domain, device_class) promotion rules for the device-centric
wizard introduced in v1.26.0.
"""

from __future__ import annotations

import pytest

from custom_components.sber_mqtt_bridge.devices.relay import RelayEntity
from custom_components.sber_mqtt_bridge.sber_entity_map import (
    CATEGORY_DOMAIN_MAP,
    CATEGORY_GROUPS,
    CATEGORY_UI_META,
    CategorySpec,
    CategoryUiMeta,
    categories_for_domain,
)

# Placeholder entity class used by tests that only exercise CategorySpec.matches()
# — the ``cls`` field is required on the dataclass but irrelevant to match logic.
_Stub = RelayEntity


class TestCategorySpec:
    """Direct tests for CategorySpec.matches()."""

    def test_domain_only_match_accepts_any_device_class(self):
        spec = CategorySpec(cls=_Stub, domains=("light",), device_classes=None)
        assert spec.matches("light", None)
        assert spec.matches("light", "")
        assert spec.matches("light", "whatever")
        assert not spec.matches("switch", None)

    def test_device_class_restricted_match(self):
        spec = CategorySpec(cls=_Stub, domains=("switch",), device_classes=("outlet",))
        assert spec.matches("switch", "outlet")
        assert not spec.matches("switch", "")
        assert not spec.matches("switch", None)
        assert not spec.matches("switch", "generic")
        assert not spec.matches("light", "outlet")

    def test_fallback_when_no_device_class(self):
        spec = CategorySpec(
            cls=_Stub,
            domains=("switch",),
            device_classes=("outlet",),
            fallback_when_no_device_class=True,
        )
        assert spec.matches("switch", "outlet")
        assert spec.matches("switch", None)
        assert spec.matches("switch", "")
        # Still rejects mismatched non-empty device_class:
        assert not spec.matches("switch", "generic_switch")


class TestCategoryDomainMap:
    """Integration tests for the registry as a whole."""

    def test_light_domain_maps_only_to_light_category_by_rank(self):
        cats = categories_for_domain("light", None)
        assert "light" in cats
        assert cats[0] == "light"  # rank 1 beats led_strip rank 5

    def test_switch_outlet_prefers_socket_over_relay(self):
        cats = categories_for_domain("switch", "outlet")
        assert cats[0] == "socket"
        # Relay also matches because fallback_when_no_device_class=True? no —
        # relay.device_classes is None → matches any device_class.  Both match,
        # socket wins by preferred_rank.
        assert "relay" in cats

    def test_switch_no_device_class_falls_back_to_relay(self):
        cats = categories_for_domain("switch", None)
        # socket requires "outlet" → excluded
        assert "socket" not in cats
        # relay has fallback → included
        assert "relay" in cats
        assert cats[0] == "relay"

    def test_cover_gate_device_class(self):
        cats = categories_for_domain("cover", "gate")
        assert cats[0] == "gate"

    def test_cover_curtain_fallback_when_no_device_class(self):
        cats = categories_for_domain("cover", None)
        assert "curtain" in cats  # fallback_when_no_device_class=True
        assert "gate" not in cats  # strict device_class requirement
        assert "window_blind" not in cats
        assert cats[0] == "curtain"

    def test_cover_blind_device_class_maps_to_window_blind(self):
        cats = categories_for_domain("cover", "blind")
        assert cats[0] == "window_blind"

    def test_cover_shade_maps_to_window_blind(self):
        cats = categories_for_domain("cover", "shade")
        assert cats[0] == "window_blind"

    def test_climate_no_device_class_falls_back_to_hvac_ac(self):
        cats = categories_for_domain("climate", None)
        assert cats[0] == "hvac_ac"

    def test_climate_radiator_wins_by_rank(self):
        cats = categories_for_domain("climate", "radiator")
        assert cats[0] == "hvac_radiator"

    def test_sensor_temperature_device_class_required(self):
        cats = categories_for_domain("sensor", "temperature")
        assert cats == ["sensor_temp"]

    def test_sensor_humidity_device_class_required(self):
        cats = categories_for_domain("sensor", "humidity")
        assert cats == ["sensor_humidity"]

    def test_sensor_no_device_class_matches_nothing(self):
        # No sensor category has fallback_when_no_device_class — this avoids
        # random diagnostic sensors (power, voltage, etc.) showing up in the
        # wizard as "unknown sensor type".
        assert categories_for_domain("sensor", None) == []

    def test_sensor_air_registered_in_category_domain_map(self):
        """sensor_air must be dispatchable from CATEGORY_DOMAIN_MAP.

        Wizard resolves category via matches(); air-quality HA device_classes
        (carbon_dioxide, pm25, pm10, pm1, volatile_organic_compounds) all
        route to sensor_air.
        """
        from custom_components.sber_mqtt_bridge.devices.sensor_air import SensorAirEntity

        spec = CATEGORY_DOMAIN_MAP.get("sensor_air")
        assert spec is not None, "sensor_air category not registered"
        assert spec.cls is SensorAirEntity
        for dc in ("carbon_dioxide", "pm25", "pm10", "pm1", "volatile_organic_compounds"):
            assert spec.matches("sensor", dc), f"sensor_air should match device_class={dc}"
        # Should not steal ownership of pure temperature sensors from sensor_temp:
        assert not spec.matches("sensor", "temperature")

    def test_sensor_air_ranks_above_sensor_temp_for_ambiguous_matches(self):
        """When a device_class shares nothing with sensor_temp, sensor_air
        should be picked without competition. But there's no ambiguity — this
        is just a sanity guard against a future refactor accidentally putting
        temperature into sensor_air's device_classes."""
        assert "temperature" not in CATEGORY_DOMAIN_MAP["sensor_air"].device_classes

    def test_binary_sensor_motion_maps_to_pir(self):
        cats = categories_for_domain("binary_sensor", "motion")
        assert cats == ["sensor_pir"]

    def test_binary_sensor_occupancy_maps_to_pir(self):
        cats = categories_for_domain("binary_sensor", "occupancy")
        assert cats == ["sensor_pir"]

    def test_binary_sensor_door_maps_to_door(self):
        cats = categories_for_domain("binary_sensor", "door")
        assert cats == ["sensor_door"]

    def test_binary_sensor_moisture_maps_to_water_leak(self):
        cats = categories_for_domain("binary_sensor", "moisture")
        assert cats == ["sensor_water_leak"]

    def test_binary_sensor_smoke_maps_to_smoke(self):
        cats = categories_for_domain("binary_sensor", "smoke")
        assert cats == ["sensor_smoke"]

    def test_binary_sensor_gas_maps_to_gas(self):
        cats = categories_for_domain("binary_sensor", "gas")
        assert cats == ["sensor_gas"]

    def test_unknown_domain_returns_empty(self):
        assert categories_for_domain("weather", None) == []
        assert categories_for_domain("automation", None) == []
        assert categories_for_domain("update", "firmware") == []

    def test_kettle_matches_both_switch_and_water_heater(self):
        # Kettle can come from either a water_heater or a plain switch.
        assert "kettle" in categories_for_domain("water_heater", None)
        assert "kettle" in categories_for_domain("switch", None)

    def test_preferred_rank_ordering_is_stable(self):
        cats = categories_for_domain("switch", None)
        # Enumerate ranks to verify monotonic ordering
        ranks = [CATEGORY_DOMAIN_MAP[c].preferred_rank for c in cats]
        assert ranks == sorted(ranks)


class TestSensorAirRoutingDetails:
    """Closes audit Subject 5 — the top-level ``test_sensor_air_registered``
    happy-path test covers 5 device_classes with a loop but doesn't
    lock rank / tie-breaking behaviour, and doesn't guard against the
    scenario where sensor_air would compete with another category.
    """

    @pytest.mark.parametrize("device_class,expected_first", [
        ("carbon_dioxide", "sensor_air"),
        ("pm1", "sensor_air"),
        ("pm25", "sensor_air"),
        ("pm10", "sensor_air"),
        ("volatile_organic_compounds", "sensor_air"),
    ])
    def test_each_air_device_class_routes_to_sensor_air(self, device_class, expected_first):
        """Each of the five HA air-quality device_classes must resolve to
        sensor_air first, not accidentally to sensor_temp / sensor_humidity."""
        cats = categories_for_domain("sensor", device_class)
        assert cats
        assert cats[0] == expected_first, (
            f"sensor+{device_class} routed to {cats[0]!r}, expected {expected_first!r}"
        )

    def test_hcho_ha_device_class_is_not_a_sensor_domain_match(self):
        """``volatile_organic_compounds_parts`` (HCHO) is only routed via
        the *linked-role* path — sensor_air's ``device_classes`` tuple
        does not include it, so it can't be picked in the wizard as
        primary via auto-detection.  Locks this against a future
        "just add all device_classes for symmetry" refactor that would
        surface HCHO-only sensors as sensor_air primaries with no
        actual primary field populated.
        """
        cats = categories_for_domain("sensor", "volatile_organic_compounds_parts")
        assert cats == [], f"unexpected match: {cats}"

    def test_sensor_air_rank_higher_priority_than_generic_default(self):
        """sensor_air preferred_rank must sort ahead of any category
        whose default rank (50) would otherwise beat it."""
        assert CATEGORY_DOMAIN_MAP["sensor_air"].preferred_rank < 50

    def test_sensor_air_does_not_match_binary_sensor_domain(self):
        """Air-quality sensor_air lives in the ``sensor`` domain; a
        ``binary_sensor.carbon_dioxide`` (which exists in HA for
        threshold-crossing binary alerts) must NOT be picked as sensor_air."""
        spec = CATEGORY_DOMAIN_MAP["sensor_air"]
        assert not spec.matches("binary_sensor", "carbon_dioxide")

    def test_sensor_air_does_not_match_switch_domain(self):
        spec = CATEGORY_DOMAIN_MAP["sensor_air"]
        assert not spec.matches("switch", "carbon_dioxide")

    def test_sensor_air_no_fallback_when_device_class_empty(self):
        """Without ``fallback_when_no_device_class``, a plain ``sensor.foo``
        with no device_class must NOT accidentally end up as sensor_air.
        Otherwise every diagnostic power/voltage sensor gets misclassified."""
        spec = CATEGORY_DOMAIN_MAP["sensor_air"]
        assert not spec.matches("sensor", None)
        assert not spec.matches("sensor", "")


class TestCategorySpecFallbackSemantics:
    """The ``fallback_when_no_device_class`` flag has subtle interactions
    with the ``device_classes`` allowlist that are easy to break in
    refactors.  Lock the semantic contract with focused tests.
    """

    def test_fallback_does_not_relax_wrong_device_class(self):
        """Even with ``fallback_when_no_device_class=True``, a mismatched
        non-empty device_class must still be rejected — the fallback
        rule only fires when device_class is missing, not wrong."""
        spec = CategorySpec(
            cls=_Stub,
            domains=("switch",),
            device_classes=("outlet",),
            fallback_when_no_device_class=True,
        )
        assert spec.matches("switch", "outlet")  # allowed
        assert spec.matches("switch", None)       # fallback fires
        assert not spec.matches("switch", "bogus")  # wrong dc still rejected

    def test_fallback_ignored_when_domain_wrong(self):
        """Domain check runs first — a wrong domain is a hard reject,
        the fallback flag never enters the picture."""
        spec = CategorySpec(
            cls=_Stub,
            domains=("switch",),
            device_classes=("outlet",),
            fallback_when_no_device_class=True,
        )
        assert not spec.matches("light", None)

    def test_device_classes_none_ignores_fallback_flag(self):
        """When ``device_classes is None`` (accept any dc in domain),
        the fallback flag is redundant — matches() must not crash
        or behave differently."""
        spec_with_flag = CategorySpec(
            cls=_Stub, domains=("light",),
            device_classes=None,
            fallback_when_no_device_class=True,
        )
        spec_without = CategorySpec(
            cls=_Stub, domains=("light",),
            device_classes=None,
            fallback_when_no_device_class=False,
        )
        for dc in (None, "", "anything", "led"):
            assert spec_with_flag.matches("light", dc) == spec_without.matches("light", dc)


class TestCategorySpecMultiDomainCategories:
    """Categories that live in multiple HA domains (``intercom``, ``kettle``,
    ``relay``) — their routing must respect every domain equally.
    """

    def test_intercom_matches_both_lock_and_switch(self):
        spec = CATEGORY_DOMAIN_MAP["intercom"]
        assert spec.matches("lock", None)
        assert spec.matches("switch", None)
        assert not spec.matches("light", None)

    def test_relay_matches_switch_script_and_button(self):
        spec = CATEGORY_DOMAIN_MAP["relay"]
        assert spec.matches("switch", None)
        assert spec.matches("script", None)
        assert spec.matches("button", None)
        # Cover isn't a relay domain
        assert not spec.matches("cover", None)

    def test_kettle_matches_water_heater_and_switch_with_fallback(self):
        spec = CATEGORY_DOMAIN_MAP["kettle"]
        assert spec.matches("water_heater", None)
        assert spec.matches("switch", None)
        # Fallback fires on empty device_class
        assert spec.matches("switch", "")
        # Wrong domain — even with fallback, no
        assert not spec.matches("humidifier", None)


class TestRegistryConsistency:
    """Cross-check that registries stay in sync with each other."""

    def test_all_mapped_categories_are_constructible(self):
        """Every category in CATEGORY_DOMAIN_MAP must carry a valid entity class.

        The ``cls`` field is the constructor — if it's missing or isn't a
        BaseEntity subclass, auto-detection or user-override will crash at
        runtime when the wizard tries to build the entity.
        """
        from custom_components.sber_mqtt_bridge.devices.base_entity import BaseEntity

        invalid = [
            cat
            for cat, spec in CATEGORY_DOMAIN_MAP.items()
            if not (isinstance(spec.cls, type) and issubclass(spec.cls, BaseEntity))
        ]
        assert not invalid, f"Categories with invalid cls: {invalid}"

    def test_ui_meta_is_subset_of_domain_map(self):
        """Every CATEGORY_UI_META key must exist in CATEGORY_DOMAIN_MAP."""
        orphans = [cat for cat in CATEGORY_UI_META if cat not in CATEGORY_DOMAIN_MAP]
        assert not orphans, f"UI meta without domain map entry: {orphans}"

    def test_domain_map_covers_all_user_selectable(self):
        """Every user_selectable=True category must be in CATEGORY_DOMAIN_MAP."""
        missing = [
            cat for cat, meta in CATEGORY_UI_META.items() if meta.user_selectable and cat not in CATEGORY_DOMAIN_MAP
        ]
        assert not missing, f"User-selectable without domain mapping: {missing}"

    def test_ui_meta_group_values_are_known(self):
        known_groups = {group_id for group_id, _ in CATEGORY_GROUPS}
        bad = [(cat, meta.group) for cat, meta in CATEGORY_UI_META.items() if meta.group not in known_groups]
        assert not bad, f"Unknown UI groups: {bad}"

    def test_every_user_selectable_has_ui_meta(self):
        """Every category that can be shown in the wizard Step 1 grid must have a UI meta entry."""
        # Reverse direction: catch domain_map categories missing UI meta
        missing_meta = [cat for cat in CATEGORY_DOMAIN_MAP if cat not in CATEGORY_UI_META]
        assert not missing_meta, f"Domain-map categories without UI meta: {missing_meta}"


class TestCategoryUiMeta:
    """Direct dataclass tests."""

    def test_default_user_selectable_is_true(self):
        meta = CategoryUiMeta(icon="X", group="control", label_key="X")
        assert meta.user_selectable is True

    def test_user_selectable_can_be_false(self):
        meta = CategoryUiMeta(icon="X", group="control", label_key="X", user_selectable=False)
        assert meta.user_selectable is False

    def test_ui_meta_is_frozen(self):
        meta = CATEGORY_UI_META["light"]
        with pytest.raises(AttributeError):
            meta.icon = "🔦"  # type: ignore[misc]
