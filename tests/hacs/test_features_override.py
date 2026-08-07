"""Tests for user feature overrides (``sber_features_add`` / ``_remove``).

Covers :meth:`BaseEntity.get_final_features_list` and the YAML config
parsing that feeds it.  Moved out of the former ``test_p4_tasks.py``
grab-bag.

Ordering is asserted deliberately: ``HaStateForwarder`` compares the
feature *list* before and after a state change and republishes the whole
config when it differs, so an unstable order would cause an endless
republish loop.
"""

from __future__ import annotations

from custom_components.sber_mqtt_bridge.custom_capabilities import (
    EntityCustomConfig,
    parse_yaml_config,
)
from custom_components.sber_mqtt_bridge.devices.base_entity import BaseEntity


class _ConcreteEntity(BaseEntity):
    """Minimal concrete entity: BaseEntity is abstract."""

    def to_sber_current_state(self) -> dict:
        """Return an empty Sber state payload (not exercised here)."""
        return {self.entity_id: {"states": []}}

    def process_cmd(self, cmd_data: dict) -> list[dict]:
        """Ignore commands (not exercised here)."""
        return []


def _make_entity() -> _ConcreteEntity:
    """Create a filled concrete entity whose only base feature is ``online``."""
    entity = _ConcreteEntity("light", {"entity_id": "light.test", "name": "Test"})
    entity.fill_by_ha_state({"state": "on", "attributes": {}})
    return entity


class TestFeaturesOverride:
    """``get_final_features_list`` = base features - removed + added."""

    def test_no_overrides_returns_base_features(self):
        assert _make_entity().get_final_features_list() == ["online"]

    def test_extra_features_are_appended_after_base_features(self):
        entity = _make_entity()
        entity.extra_features = ["light_brightness", "light_colour"]
        assert entity.get_final_features_list() == ["online", "light_brightness", "light_colour"]

    def test_removed_features_are_excluded(self):
        entity = _make_entity()
        entity.removed_features = ["online"]
        assert entity.get_final_features_list() == []

    def test_remove_wins_over_base_and_add_still_applies(self):
        entity = _make_entity()
        entity.extra_features = ["light_brightness"]
        entity.removed_features = ["online"]
        assert entity.get_final_features_list() == ["light_brightness"]

    def test_adding_an_existing_feature_does_not_duplicate_it(self):
        # A duplicate feature makes Sber reject the whole device config.
        entity = _make_entity()
        entity.extra_features = ["online", "light_brightness"]
        result = entity.get_final_features_list()
        assert result == ["online", "light_brightness"]
        assert len(result) == len(set(result))

    def test_result_is_stable_across_calls(self):
        # HaStateForwarder republishes the config whenever this list differs
        # from the previous one — an unstable order would loop forever.
        entity = _make_entity()
        entity.extra_features = ["light_brightness", "light_colour"]
        entity.removed_features = ["light_colour_temp"]
        assert entity.get_final_features_list() == entity.get_final_features_list()

    def test_to_sber_state_uses_final_features(self):
        entity = _make_entity()
        entity.extra_features = ["light_brightness"]
        entity.removed_features = []
        features = entity.to_sber_state()["model"]["features"]
        assert set(features) == {"online", "light_brightness"}

    def test_to_sber_state_drops_removed_features(self):
        entity = _make_entity()
        entity.removed_features = ["online"]
        assert entity.to_sber_state()["model"]["features"] == []


class TestYamlFeaturesConfig:
    """YAML ``entity_config`` → :class:`EntityCustomConfig`."""

    def test_config_object_carries_both_override_lists(self):
        cfg = EntityCustomConfig(
            sber_features_add=["light_brightness"],
            sber_features_remove=["online"],
        )
        assert cfg.sber_features_add == ["light_brightness"]
        assert cfg.sber_features_remove == ["online"]

    def test_parse_yaml_config_reads_features(self):
        config = parse_yaml_config(
            {
                "entity_config": {
                    "light.test": {
                        "sber_features_add": ["light_brightness"],
                        "sber_features_remove": ["online"],
                    }
                }
            }
        )
        cfg = config.get("light.test")
        assert cfg is not None
        assert cfg.sber_features_add == ["light_brightness"]
        assert cfg.sber_features_remove == ["online"]

    def test_parse_yaml_config_leaves_features_unset_when_absent(self):
        config = parse_yaml_config({"entity_config": {"light.test": {"sber_name": "Kitchen"}}})
        cfg = config.get("light.test")
        assert cfg is not None
        assert cfg.sber_features_add is None
        assert cfg.sber_features_remove is None
