"""Tests for IntercomEntity -- Sber intercom device mapping."""

import unittest

from custom_components.sber_mqtt_bridge.devices.intercom import IntercomEntity
from custom_components.sber_mqtt_bridge.devices.on_off_entity import OnOffEntity


ENTITY_DATA = {"entity_id": "switch.intercom", "name": "Front Door Intercom"}


def _make_ha_state(state="on", **attrs):
    return {
        "entity_id": "switch.intercom",
        "state": state,
        "attributes": attrs,
    }


class TestIntercomCreate(unittest.TestCase):
    """Test IntercomEntity initialization."""

    def test_category(self):
        entity = IntercomEntity(ENTITY_DATA)
        self.assertEqual(entity.category, "intercom")

    def test_inherits_on_off_entity(self):
        entity = IntercomEntity(ENTITY_DATA)
        self.assertIsInstance(entity, OnOffEntity)

    def test_initial_state(self):
        entity = IntercomEntity(ENTITY_DATA)
        self.assertFalse(entity.current_state)

    def test_features_list(self):
        entity = IntercomEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state())
        features = entity.get_final_features_list()
        self.assertIn("online", features)
        self.assertIn("on_off", features)
        self.assertIn("incoming_call", features)
        self.assertIn("reject_call", features)
        self.assertIn("unlock", features)


class TestIntercomFillState(unittest.TestCase):
    """Test fill_by_ha_state."""

    def test_on_state(self):
        entity = IntercomEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("on"))
        self.assertTrue(entity.current_state)

    def test_off_state(self):
        entity = IntercomEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("off"))
        self.assertFalse(entity.current_state)

    def test_reads_call_attrs(self):
        entity = IntercomEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("on", incoming_call=True, unlock=True))
        self.assertTrue(entity._incoming_call)
        self.assertTrue(entity._unlock)
        self.assertFalse(entity._reject_call)


class TestIntercomToSberCurrentState(unittest.TestCase):
    """Test to_sber_current_state."""

    def test_state_includes_call_features(self):
        entity = IntercomEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("on", incoming_call=True))
        result = entity.to_sber_current_state()
        states = result["switch.intercom"]["states"]
        on_off = next(s for s in states if s["key"] == "on_off")
        self.assertTrue(on_off["value"]["bool_value"])
        call = next(s for s in states if s["key"] == "incoming_call")
        self.assertTrue(call["value"]["bool_value"])
        unlock = next(s for s in states if s["key"] == "unlock")
        self.assertFalse(unlock["value"]["bool_value"])

    def test_unavailable_offline(self):
        entity = IntercomEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("unavailable"))
        result = entity.to_sber_current_state()
        states = result["switch.intercom"]["states"]
        online = next(s for s in states if s["key"] == "online")
        self.assertFalse(online["value"]["bool_value"])


class TestIntercomProcessCmd(unittest.TestCase):
    """Test process_cmd."""

    def _make_entity(self, state="on", **attrs):
        entity = IntercomEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(state, **attrs))
        return entity

    def test_cmd_turn_on(self):
        entity = self._make_entity("off")
        result = entity.process_cmd({"states": [{"key": "on_off", "value": {"type": "BOOL", "bool_value": True}}]})
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["url"]["service"], "turn_on")
        self.assertEqual(result[0]["url"]["domain"], "switch")

    def test_cmd_turn_off(self):
        entity = self._make_entity("on")
        result = entity.process_cmd({"states": [{"key": "on_off", "value": {"type": "BOOL", "bool_value": False}}]})
        self.assertEqual(result[0]["url"]["service"], "turn_off")

    def test_cmd_read_only_keys_ignored(self):
        entity = self._make_entity()
        result = entity.process_cmd(
            {"states": [{"key": "incoming_call", "value": {"type": "BOOL", "bool_value": True}}]}
        )
        self.assertEqual(len(result), 0)

    def test_cmd_empty_states(self):
        entity = self._make_entity()
        result = entity.process_cmd({"states": []})
        self.assertEqual(result, [])
