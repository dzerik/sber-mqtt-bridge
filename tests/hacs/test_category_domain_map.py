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
