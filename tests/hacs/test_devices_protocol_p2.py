"""Tests for P2 tasks: dependencies, allowed_values, nicknames, groups, parent_id."""

import unittest

from custom_components.sber_mqtt_bridge.devices.light import LightEntity
from custom_components.sber_mqtt_bridge.devices.valve import ValveEntity
from custom_components.sber_mqtt_bridge.devices.curtain import CurtainEntity
from custom_components.sber_mqtt_bridge.devices.climate import ClimateEntity
from custom_components.sber_mqtt_bridge.devices.humidifier import HumidifierEntity
from custom_components.sber_mqtt_bridge.devices.scenario_button import ScenarioButtonEntity
from custom_components.sber_mqtt_bridge.devices.base_entity import BaseEntity
from custom_components.sber_mqtt_bridge.devices.relay import RelayEntity
from custom_components.sber_mqtt_bridge.custom_capabilities import (
    EntityCustomConfig,
    parse_yaml_config,
)


LIGHT_DATA = {"entity_id": "light.room", "name": "Room Light"}
VALVE_DATA = {"entity_id": "valve.main", "name": "Main Valve"}
CURTAIN_DATA = {"entity_id": "cover.curtain", "name": "Curtain"}
CLIMATE_DATA = {"entity_id": "climate.ac", "name": "AC"}
HUMIDIFIER_DATA = {"entity_id": "humidifier.hum", "name": "Humidifier"}
BUTTON_DATA = {"entity_id": "input_boolean.scene", "name": "Scene Button"}
RELAY_DATA = {"entity_id": "switch.relay", "name": "Relay"}


def _light_state(
    state="on",
    brightness=200,
    color_temp=300,
    min_mireds=153,
    max_mireds=500,
    supported_color_modes=None,
    color_mode="color_temp",
    hs_color=None,
    rgb_color=None,
    xy_color=None,
):
    if supported_color_modes is None:
        supported_color_modes = ["color_temp", "xy"]
    return {
        "entity_id": "light.room",
        "state": state,
        "attributes": {
            "brightness": brightness,
            "color_temp": color_temp,
            "min_mireds": min_mireds,
            "max_mireds": max_mireds,
            "supported_color_modes": supported_color_modes,
            "color_mode": color_mode,
            "supported_features": 0,
            "hs_color": hs_color if hs_color is not None else [30, 80],
            "rgb_color": rgb_color if rgb_color is not None else [255, 200, 50],
            "xy_color": xy_color if xy_color is not None else [0.5, 0.3],
        },
    }


def _valve_state(state="open"):
    return {"entity_id": "valve.main", "state": state, "attributes": {}}


def _cover_state(state="open", **attrs):
    return {"entity_id": "cover.curtain", "state": state, "attributes": attrs}


def _climate_state(state="cool", **extra_attrs):
    attrs = {
        "current_temperature": 24.5,
        "temperature": 22.0,
        "fan_modes": ["auto", "low", "high"],
        "swing_modes": ["off", "vertical"],
        "hvac_modes": ["off", "cool", "heat"],
        "fan_mode": "auto",
        "swing_mode": "off",
        "min_temp": 16.0,
        "max_temp": 32.0,
    }
    attrs.update(extra_attrs)
    return {"entity_id": "climate.ac", "state": state, "attributes": attrs}


def _humidifier_state(state="on", **extra_attrs):
    attrs = {
        "humidity": 50,
        "current_humidity": 40,
        "available_modes": ["normal", "sleep", "turbo"],
        "mode": "normal",
    }
    attrs.update(extra_attrs)
    return {"entity_id": "humidifier.hum", "state": state, "attributes": attrs}


def _button_state(state="off"):
    return {"entity_id": "input_boolean.scene", "state": state, "attributes": {}}


def _switch_state(entity_id="switch.relay", state="on"):
    return {"entity_id": entity_id, "state": state, "attributes": {}}


# === Task 11: dependencies (light_colour depends on light_mode) ===


class TestLightDependencies(unittest.TestCase):
    """Test dependencies in LightEntity.to_sber_state()."""

    def test_dependencies_present_when_color_supported(self):
        """Dependencies should be set when light supports xy color mode."""
        entity = LightEntity(LIGHT_DATA)
        entity.fill_by_ha_state(_light_state(supported_color_modes=["color_temp", "xy"]))
        result = entity.to_sber_state()
        deps = result["model"]["dependencies"]
        self.assertIn("light_colour", deps)
        self.assertEqual(deps["light_colour"]["key"], "light_mode")
        self.assertEqual(
            deps["light_colour"]["value"],
            [{"type": "ENUM", "enum_value": "colour"}],
        )

    def test_dependencies_absent_when_no_color(self):
        """Dependencies should not be set when light has no color support."""
        entity = LightEntity(LIGHT_DATA)
        entity.fill_by_ha_state(_light_state(supported_color_modes=["color_temp"]))
        result = entity.to_sber_state()
        self.assertNotIn("dependencies", result["model"])

    def test_dependencies_absent_brightness_only(self):
        """Dependencies absent for brightness-only lights."""
        entity = LightEntity(LIGHT_DATA)
        entity.fill_by_ha_state(_light_state(supported_color_modes=["brightness"]))
        result = entity.to_sber_state()
        self.assertNotIn("dependencies", result["model"])


# === Task 12: allowed_values expansion ===


class TestValveAllowedValues(unittest.TestCase):
    """Test allowed_values in ValveEntity.to_sber_state()."""

    def test_open_set_allowed_values(self):
        entity = ValveEntity(VALVE_DATA)
        entity.fill_by_ha_state(_valve_state())
        result = entity.to_sber_state()
        av = result["model"]["allowed_values"]
        self.assertIn("open_set", av)
        self.assertEqual(av["open_set"]["type"], "ENUM")
        self.assertEqual(
            av["open_set"]["enum_values"]["values"], ["open", "close", "stop"]
        )

    def test_allowed_values_structure(self):
        entity = ValveEntity(VALVE_DATA)
        entity.fill_by_ha_state(_valve_state())
        result = entity.to_sber_state()
        self.assertIn("allowed_values", result["model"])


class TestCurtainAllowedValues(unittest.TestCase):
    """Test allowed_values in CurtainEntity.to_sber_state()."""

    def test_open_set_and_percentage(self):
        entity = CurtainEntity(CURTAIN_DATA)
        entity.fill_by_ha_state(_cover_state(current_position=50))
        result = entity.to_sber_state()
        av = result["model"]["allowed_values"]
        self.assertIn("open_set", av)
        self.assertIn("open_percentage", av)
        self.assertEqual(
            av["open_set"]["enum_values"]["values"], ["open", "close", "stop"]
        )
        self.assertEqual(av["open_percentage"]["type"], "INTEGER")
        self.assertEqual(av["open_percentage"]["integer_values"]["min"], "0")
        self.assertEqual(av["open_percentage"]["integer_values"]["max"], "100")

    def test_open_percentage_step(self):
        entity = CurtainEntity(CURTAIN_DATA)
        entity.fill_by_ha_state(_cover_state(current_position=50))
        result = entity.to_sber_state()
        av = result["model"]["allowed_values"]
        self.assertEqual(av["open_percentage"]["integer_values"]["step"], "1")


class TestClimateAllowedValues(unittest.TestCase):
    """Test hvac_temp_set in ClimateEntity allowed_values."""

    def test_hvac_temp_set_present(self):
        entity = ClimateEntity(CLIMATE_DATA)
        entity.fill_by_ha_state(_climate_state())
        result = entity.to_sber_state()
        av = result["model"]["allowed_values"]
        self.assertIn("hvac_temp_set", av)
        self.assertEqual(av["hvac_temp_set"]["type"], "INTEGER")
        self.assertEqual(av["hvac_temp_set"]["integer_values"]["min"], "16")
        self.assertEqual(av["hvac_temp_set"]["integer_values"]["max"], "32")
        self.assertEqual(av["hvac_temp_set"]["integer_values"]["step"], "1")

    def test_hvac_temp_set_custom_range(self):
        entity = ClimateEntity(CLIMATE_DATA, min_temp=10.0, max_temp=40.0)
        entity.fill_by_ha_state(_climate_state(min_temp=10.0, max_temp=40.0))
        result = entity.to_sber_state()
        av = result["model"]["allowed_values"]
        self.assertEqual(av["hvac_temp_set"]["integer_values"]["min"], "10")
        self.assertEqual(av["hvac_temp_set"]["integer_values"]["max"], "40")


class TestHumidifierAllowedValues(unittest.TestCase):
    """Test hvac_humidity_set in HumidifierEntity allowed_values."""

    def test_hvac_humidity_set_present(self):
        entity = HumidifierEntity(HUMIDIFIER_DATA)
        entity.fill_by_ha_state(_humidifier_state())
        result = entity.to_sber_state()
        av = result["model"]["allowed_values"]
        self.assertIn("hvac_humidity_set", av)
        self.assertEqual(av["hvac_humidity_set"]["type"], "INTEGER")
        self.assertEqual(av["hvac_humidity_set"]["integer_values"]["min"], "0")
        self.assertEqual(av["hvac_humidity_set"]["integer_values"]["max"], "100")

    def test_hvac_air_flow_power_and_humidity_both_present(self):
        entity = HumidifierEntity(HUMIDIFIER_DATA)
        entity.fill_by_ha_state(_humidifier_state())
        result = entity.to_sber_state()
        av = result["model"]["allowed_values"]
        self.assertIn("hvac_air_flow_power", av)
        self.assertIn("hvac_humidity_set", av)


class TestScenarioButtonAllowedValues(unittest.TestCase):
    """Test allowed_values in ScenarioButtonEntity.to_sber_state()."""

    def test_button_event_allowed_values(self):
        entity = ScenarioButtonEntity(BUTTON_DATA)
        entity.fill_by_ha_state(_button_state())
        result = entity.to_sber_state()
        av = result["model"]["allowed_values"]
        self.assertIn("button_event", av)
        self.assertEqual(av["button_event"]["type"], "ENUM")
        self.assertIn("click", av["button_event"]["enum_values"]["values"])
        self.assertIn("double_click", av["button_event"]["enum_values"]["values"])
        self.assertIn("long_press", av["button_event"]["enum_values"]["values"])

    def test_button_event_three_values(self):
        entity = ScenarioButtonEntity(BUTTON_DATA)
        entity.fill_by_ha_state(_button_state())
        result = entity.to_sber_state()
        av = result["model"]["allowed_values"]
        self.assertEqual(len(av["button_event"]["enum_values"]["values"]), 3)


# === Task 13: nicknames ===


class TestNicknames(unittest.TestCase):
    """Test nicknames support in BaseEntity."""

    def test_nicknames_default_empty(self):
        entity = RelayEntity(RELAY_DATA)
        self.assertEqual(entity.nicknames, [])

    def test_nicknames_in_to_sber_state(self):
        entity = RelayEntity(RELAY_DATA)
        entity.fill_by_ha_state(_switch_state())
        entity.nicknames = ["Свет кухня", "Кухонная лампа"]
        result = entity.to_sber_state()
        self.assertEqual(result["nicknames"], ["Свет кухня", "Кухонная лампа"])

    def test_nicknames_absent_when_empty(self):
        entity = RelayEntity(RELAY_DATA)
        entity.fill_by_ha_state(_switch_state())
        result = entity.to_sber_state()
        self.assertNotIn("nicknames", result)

    def test_nicknames_custom_config_dataclass(self):
        cfg = EntityCustomConfig(sber_nicknames=["Alias1", "Alias2"])
        self.assertEqual(cfg.sber_nicknames, ["Alias1", "Alias2"])


class TestNicknamesYamlParsing(unittest.TestCase):
    """Test nicknames YAML parsing."""

    def test_parse_nicknames_from_yaml(self):
        yaml_data = {
            "entity_config": {
                "light.kitchen": {
                    "sber_nicknames": ["Свет кухня", "Кухонная лампа"],
                }
            }
        }
        config = parse_yaml_config(yaml_data)
        cfg = config.get("light.kitchen")
        self.assertIsNotNone(cfg)
        self.assertEqual(cfg.sber_nicknames, ["Свет кухня", "Кухонная лампа"])


# === Task 14: groups ===


class TestGroups(unittest.TestCase):
    """Test groups support in BaseEntity."""

    def test_groups_default_empty(self):
        entity = RelayEntity(RELAY_DATA)
        self.assertEqual(entity.groups, [])

    def test_groups_in_to_sber_state(self):
        entity = RelayEntity(RELAY_DATA)
        entity.fill_by_ha_state(_switch_state())
        entity.groups = ["Свет", "Кухня"]
        result = entity.to_sber_state()
        self.assertEqual(result["groups"], ["Свет", "Кухня"])

    def test_groups_absent_when_empty(self):
        entity = RelayEntity(RELAY_DATA)
        entity.fill_by_ha_state(_switch_state())
        result = entity.to_sber_state()
        self.assertNotIn("groups", result)

    def test_groups_custom_config_dataclass(self):
        cfg = EntityCustomConfig(sber_groups=["Свет", "Кухня"])
        self.assertEqual(cfg.sber_groups, ["Свет", "Кухня"])


class TestGroupsYamlParsing(unittest.TestCase):
    """Test groups YAML parsing."""

    def test_parse_groups_from_yaml(self):
        yaml_data = {
            "entity_config": {
                "light.kitchen": {
                    "sber_groups": ["Свет", "Кухня"],
                }
            }
        }
        config = parse_yaml_config(yaml_data)
        cfg = config.get("light.kitchen")
        self.assertIsNotNone(cfg)
        self.assertEqual(cfg.sber_groups, ["Свет", "Кухня"])


# === Task 15: parent_id ===


class TestParentId(unittest.TestCase):
    """Test parent_id support in BaseEntity."""

    def test_parent_entity_id_default_none(self):
        entity = RelayEntity(RELAY_DATA)
        self.assertIsNone(entity.parent_entity_id)

    def test_parent_id_in_to_sber_state(self):
        entity = RelayEntity(RELAY_DATA)
        entity.fill_by_ha_state(_switch_state())
        entity.parent_entity_id = "sensor.hub_123"
        result = entity.to_sber_state()
        self.assertEqual(result["parent_id"], "sensor.hub_123")

    def test_parent_id_absent_when_none(self):
        entity = RelayEntity(RELAY_DATA)
        entity.fill_by_ha_state(_switch_state())
        result = entity.to_sber_state()
        self.assertNotIn("parent_id", result)

    def test_parent_id_custom_config_dataclass(self):
        cfg = EntityCustomConfig(sber_parent_id="sensor.hub_123")
        self.assertEqual(cfg.sber_parent_id, "sensor.hub_123")


class TestParentIdYamlParsing(unittest.TestCase):
    """Test parent_id YAML parsing."""

    def test_parse_parent_id_from_yaml(self):
        yaml_data = {
            "entity_config": {
                "light.kitchen": {
                    "sber_parent_id": "sensor.hub_123",
                }
            }
        }
        config = parse_yaml_config(yaml_data)
        cfg = config.get("light.kitchen")
        self.assertIsNotNone(cfg)
        self.assertEqual(cfg.sber_parent_id, "sensor.hub_123")


# === Combined test: all three in one entity ===


class TestCombinedMetadata(unittest.TestCase):
    """Test nicknames, groups, and parent_id together."""

    def test_all_metadata_present(self):
        entity = RelayEntity(RELAY_DATA)
        entity.fill_by_ha_state(_switch_state())
        entity.nicknames = ["Alias"]
        entity.groups = ["Group1"]
        entity.parent_entity_id = "hub.main"
        result = entity.to_sber_state()
        self.assertEqual(result["nicknames"], ["Alias"])
        self.assertEqual(result["groups"], ["Group1"])
        self.assertEqual(result["parent_id"], "hub.main")

    def test_full_yaml_config(self):
        yaml_data = {
            "entity_config": {
                "light.kitchen": {
                    "sber_type": "light",
                    "sber_name": "Кухня",
                    "sber_room": "Кухня",
                    "sber_nicknames": ["Свет"],
                    "sber_groups": ["Освещение"],
                    "sber_parent_id": "sensor.hub",
                }
            }
        }
        config = parse_yaml_config(yaml_data)
        cfg = config.get("light.kitchen")
        self.assertEqual(cfg.sber_type, "light")
        self.assertEqual(cfg.sber_name, "Кухня")
        self.assertEqual(cfg.sber_room, "Кухня")
        self.assertEqual(cfg.sber_nicknames, ["Свет"])
        self.assertEqual(cfg.sber_groups, ["Освещение"])
        self.assertEqual(cfg.sber_parent_id, "sensor.hub")
