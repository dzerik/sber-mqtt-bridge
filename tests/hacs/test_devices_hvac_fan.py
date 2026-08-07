"""Tests for HvacFanEntity -- Sber fan device mapping."""

import unittest

from custom_components.sber_mqtt_bridge.devices.hvac_fan import HvacFanEntity

ENTITY_DATA = {"entity_id": "fan.living_room", "name": "Living Room Fan"}


def _make_ha_state(state="on", **attrs):
    return {
        "entity_id": "fan.living_room",
        "state": state,
        "attributes": attrs,
    }


class TestHvacFanCreate(unittest.TestCase):
    """Test HvacFanEntity initialization."""

    def test_category(self):
        entity = HvacFanEntity(ENTITY_DATA)
        self.assertEqual(entity.category, "hvac_fan")

    def test_initial_state(self):
        entity = HvacFanEntity(ENTITY_DATA)
        self.assertFalse(entity.current_state)

    def test_features_list_with_speed(self):
        entity = HvacFanEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(percentage=50))
        features = entity.get_final_features_list()
        self.assertIn("online", features)
        self.assertIn("on_off", features)
        self.assertIn("hvac_air_flow_power", features)

    def test_features_list_simple_relay(self):
        entity = HvacFanEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state())
        features = entity.get_final_features_list()
        self.assertIn("online", features)
        self.assertIn("on_off", features)
        self.assertNotIn("hvac_air_flow_power", features)


class TestHvacFanSpeedCapability(unittest.TestCase):
    """Speed capability must be derived from capabilities, not current values.

    Regression tests for the bug where a fan turned off (percentage=None)
    lost the hvac_air_flow_power feature and was republished without it.
    """

    def test_off_fan_with_set_speed_keeps_feature(self):
        """Off fan (percentage=None) with SET_SPEED bit keeps speed feature."""
        entity = HvacFanEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("off", supported_features=1, percentage=None, percentage_step=25))
        features = entity.get_final_features_list()
        self.assertIn("hvac_air_flow_power", features)

    def test_off_fan_with_set_speed_keeps_allowed_values(self):
        """Off fan (percentage=None) with SET_SPEED bit keeps allowed_values."""
        entity = HvacFanEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("off", supported_features=1, percentage=None))
        allowed = entity.create_allowed_values_list()
        self.assertIn("hvac_air_flow_power", allowed)

    def test_supported_features_bitmask_alone_enables_feature(self):
        """SET_SPEED bit is enough even without percentage attribute keys."""
        entity = HvacFanEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("off", supported_features=49))  # SET_SPEED|TURN_OFF|TURN_ON
        self.assertIn("hvac_air_flow_power", entity.get_final_features_list())

    def test_percentage_key_presence_enables_feature(self):
        """Presence of 'percentage' key (even None) marks the fan speed-capable."""
        entity = HvacFanEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("off", percentage=None))
        self.assertIn("hvac_air_flow_power", entity.get_final_features_list())

    def test_no_set_speed_no_feature(self):
        """Fan without SET_SPEED bit and without speed attributes has no speed feature."""
        entity = HvacFanEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("on", supported_features=48))  # TURN_OFF|TURN_ON only
        features = entity.get_final_features_list()
        self.assertNotIn("hvac_air_flow_power", features)
        self.assertNotIn("hvac_air_flow_power", entity.create_allowed_values_list())

    def test_feature_stable_across_off_on_cycle(self):
        """Feature list stays identical when fan goes on -> off -> on."""
        entity = HvacFanEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("on", supported_features=1, percentage=50))
        features_on = entity.get_final_features_list()
        entity.fill_by_ha_state(_make_ha_state("off", supported_features=1, percentage=None))
        features_off = entity.get_final_features_list()
        self.assertEqual(features_on, features_off)
        self.assertIn("hvac_air_flow_power", features_off)

    def test_feature_stable_across_unavailable(self):
        """Capability persists when the fan becomes unavailable (empty attrs)."""
        entity = HvacFanEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("on", supported_features=1, percentage=50))
        entity.fill_by_ha_state(_make_ha_state("unavailable"))
        self.assertIn("hvac_air_flow_power", entity.get_final_features_list())

    def test_off_fan_percentage_none_sends_no_speed_state(self):
        """Speed-capable fan with unknown speed does not report a speed state."""
        entity = HvacFanEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("off", supported_features=1, percentage=None))
        states = entity.to_sber_current_state()["fan.living_room"]["states"]
        self.assertNotIn("hvac_air_flow_power", [s["key"] for s in states])

    def test_on_fan_percentage_still_reports_speed_state(self):
        """Known percentage still produces a speed state as before."""
        entity = HvacFanEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("on", supported_features=1, percentage=50))
        states = entity.to_sber_current_state()["fan.living_room"]["states"]
        speed = next(s for s in states if s["key"] == "hvac_air_flow_power")
        self.assertEqual(speed["value"]["enum_value"], "medium")


class TestHvacFanToSberCurrentState(unittest.TestCase):
    """Test to_sber_current_state."""

    def test_on_with_preset_mode(self):
        entity = HvacFanEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("on", preset_mode="high", preset_modes=["low", "high"]))
        result = entity.to_sber_current_state()
        states = result["fan.living_room"]["states"]
        on_off = next(s for s in states if s["key"] == "on_off")
        self.assertTrue(on_off["value"]["bool_value"])
        speed = next(s for s in states if s["key"] == "hvac_air_flow_power")
        self.assertEqual(speed["value"]["enum_value"], "high")

    def test_off_state(self):
        entity = HvacFanEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("off"))
        result = entity.to_sber_current_state()
        states = result["fan.living_room"]["states"]
        on_off = next(s for s in states if s["key"] == "on_off")
        self.assertFalse(on_off["value"]["bool_value"])

    def test_percentage_to_speed(self):
        entity = HvacFanEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("on", percentage=50))
        result = entity.to_sber_current_state()
        states = result["fan.living_room"]["states"]
        speed = next(s for s in states if s["key"] == "hvac_air_flow_power")
        self.assertEqual(speed["value"]["enum_value"], "medium")

    def test_unavailable_offline(self):
        entity = HvacFanEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("unavailable"))
        result = entity.to_sber_current_state()
        states = result["fan.living_room"]["states"]
        online = next(s for s in states if s["key"] == "online")
        self.assertFalse(online["value"]["bool_value"])


class TestHvacFanProcessCmd(unittest.TestCase):
    """Test process_cmd."""

    def _make_entity(self, state="on", **attrs):
        entity = HvacFanEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(state, **attrs))
        return entity

    def test_cmd_turn_on(self):
        entity = self._make_entity("off")
        result = entity.process_cmd({"states": [{"key": "on_off", "value": {"type": "BOOL", "bool_value": True}}]})
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["url"]["service"], "turn_on")
        self.assertEqual(result[0]["url"]["domain"], "fan")

    def test_cmd_turn_off(self):
        entity = self._make_entity("on")
        result = entity.process_cmd({"states": [{"key": "on_off", "value": {"type": "BOOL", "bool_value": False}}]})
        self.assertEqual(result[0]["url"]["service"], "turn_off")

    def test_cmd_set_preset_mode(self):
        entity = self._make_entity("on", preset_modes=["low", "medium", "high"])
        result = entity.process_cmd(
            {"states": [{"key": "hvac_air_flow_power", "value": {"type": "ENUM", "enum_value": "medium"}}]}
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["url"]["service"], "set_preset_mode")
        self.assertEqual(result[0]["url"]["service_data"]["preset_mode"], "medium")

    def test_cmd_set_percentage_fallback(self):
        entity = self._make_entity("on", preset_modes=[])
        result = entity.process_cmd(
            {"states": [{"key": "hvac_air_flow_power", "value": {"type": "ENUM", "enum_value": "high"}}]}
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["url"]["service"], "set_percentage")
        self.assertEqual(result[0]["url"]["service_data"]["percentage"], 75)

    def test_cmd_auto_turns_on(self):
        entity = self._make_entity("on", preset_modes=[])
        result = entity.process_cmd(
            {"states": [{"key": "hvac_air_flow_power", "value": {"type": "ENUM", "enum_value": "auto"}}]}
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["url"]["service"], "turn_on")

    def test_cmd_empty_states(self):
        entity = self._make_entity()
        result = entity.process_cmd({"states": []})
        self.assertEqual(result, [])


class TestHvacFanAllowedValues(unittest.TestCase):
    """Test to_sber_state allowed values."""

    def test_allowed_values_with_speed(self):
        entity = HvacFanEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("on", percentage=50))
        result = entity.to_sber_state()
        allowed = result["model"]["allowed_values"]
        self.assertIn("hvac_air_flow_power", allowed)
        values = allowed["hvac_air_flow_power"]["enum_values"]["values"]
        self.assertIn("auto", values)
        self.assertIn("high", values)

    def test_allowed_values_simple_relay(self):
        entity = HvacFanEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("on"))
        result = entity.to_sber_state()
        allowed = result["model"].get("allowed_values", {})
        self.assertNotIn("hvac_air_flow_power", allowed)
