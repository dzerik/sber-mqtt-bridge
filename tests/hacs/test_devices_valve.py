"""Tests for ValveEntity -- Sber valve device mapping with open_set/open_state."""

import unittest

from custom_components.sber_mqtt_bridge.devices.valve import ValveEntity


ENTITY_DATA = {"entity_id": "valve.main", "name": "Main Valve"}


def _make_ha_state(state="open"):
    return {
        "entity_id": "valve.main",
        "state": state,
        "attributes": {},
    }


class TestValveInit(unittest.TestCase):
    """Test ValveEntity initialization."""

    def test_init_defaults(self):
        entity = ValveEntity(ENTITY_DATA)
        self.assertEqual(entity.category, "valve")
        self.assertEqual(entity.entity_id, "valve.main")
        self.assertFalse(entity.is_open)

    def test_not_inherits_on_off_entity(self):
        """ValveEntity should NOT inherit OnOffEntity."""
        from custom_components.sber_mqtt_bridge.devices.on_off_entity import OnOffEntity

        entity = ValveEntity(ENTITY_DATA)
        self.assertNotIsInstance(entity, OnOffEntity)


class TestValveFillByHaState(unittest.TestCase):
    """Test fill_by_ha_state."""

    def test_fill_open(self):
        entity = ValveEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("open"))
        self.assertTrue(entity.is_open)

    def test_fill_closed(self):
        entity = ValveEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("closed"))
        self.assertFalse(entity.is_open)

    def test_fill_other_state(self):
        entity = ValveEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("unknown"))
        self.assertFalse(entity.is_open)


class TestValveCreateFeaturesList(unittest.TestCase):
    """Test create_features_list."""

    def test_features_include_open_set_open_state(self):
        entity = ValveEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state())
        features = entity.get_final_features_list()
        self.assertIn("open_set", features)
        self.assertIn("open_state", features)
        self.assertIn("online", features)

    def test_features_do_not_include_on_off(self):
        entity = ValveEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state())
        features = entity.get_final_features_list()
        self.assertNotIn("on_off", features)


class TestValveToSberCurrentState(unittest.TestCase):
    """Test to_sber_current_state."""

    def test_open(self):
        entity = ValveEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("open"))
        result = entity.to_sber_current_state()
        self.assertIn("valve.main", result)
        states = result["valve.main"]["states"]

        online = next(s for s in states if s["key"] == "online")
        self.assertTrue(online["value"]["bool_value"])

        open_state = next(s for s in states if s["key"] == "open_state")
        self.assertEqual(open_state["value"]["type"], "ENUM")
        self.assertEqual(open_state["value"]["enum_value"], "open")

    def test_closed(self):
        entity = ValveEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("closed"))
        result = entity.to_sber_current_state()
        states = result["valve.main"]["states"]
        open_state = next(s for s in states if s["key"] == "open_state")
        self.assertEqual(open_state["value"]["enum_value"], "close")

    def test_unavailable_offline(self):
        entity = ValveEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("unavailable"))
        result = entity.to_sber_current_state()
        states = result["valve.main"]["states"]
        online = next(s for s in states if s["key"] == "online")
        self.assertFalse(online["value"]["bool_value"])

    def test_no_on_off_in_state(self):
        """Ensure on_off key is NOT present in current state."""
        entity = ValveEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("open"))
        result = entity.to_sber_current_state()
        states = result["valve.main"]["states"]
        keys = [s["key"] for s in states]
        self.assertNotIn("on_off", keys)


class TestValveProcessCmd(unittest.TestCase):
    """Test process_cmd with open_set ENUM commands."""

    def _make_entity(self, state="closed"):
        entity = ValveEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(state))
        return entity

    def test_cmd_open(self):
        entity = self._make_entity("closed")
        result = entity.process_cmd({
            "states": [{"key": "open_set", "value": {"type": "ENUM", "enum_value": "open"}}]
        })
        self.assertEqual(len(result), 1)
        url = result[0]["url"]
        self.assertEqual(url["domain"], "valve")
        self.assertEqual(url["service"], "open_valve")

    def test_cmd_close(self):
        entity = self._make_entity("open")
        result = entity.process_cmd({
            "states": [{"key": "open_set", "value": {"type": "ENUM", "enum_value": "close"}}]
        })
        url = result[0]["url"]
        self.assertEqual(url["service"], "close_valve")

    def test_cmd_stop(self):
        entity = self._make_entity("open")
        result = entity.process_cmd({
            "states": [{"key": "open_set", "value": {"type": "ENUM", "enum_value": "stop"}}]
        })
        url = result[0]["url"]
        self.assertEqual(url["service"], "stop_valve")

    def test_cmd_wrong_type_ignored(self):
        """Non-ENUM type for open_set is ignored."""
        entity = self._make_entity()
        result = entity.process_cmd({
            "states": [{"key": "open_set", "value": {"type": "BOOL", "bool_value": True}}]
        })
        self.assertEqual(len(result), 0)

    def test_cmd_empty_states(self):
        entity = self._make_entity()
        result = entity.process_cmd({"states": []})
        self.assertEqual(result, [])

    def test_cmd_unknown_key_ignored(self):
        entity = self._make_entity()
        result = entity.process_cmd({
            "states": [{"key": "on_off", "value": {"type": "BOOL", "bool_value": True}}]
        })
        self.assertEqual(len(result), 0)

    def test_cmd_unknown_enum_value_ignored(self):
        entity = self._make_entity()
        result = entity.process_cmd({
            "states": [{"key": "open_set", "value": {"type": "ENUM", "enum_value": "unknown"}}]
        })
        self.assertEqual(len(result), 0)


class TestValveProcessStateChange(unittest.TestCase):
    """Test process_state_change."""

    def test_state_change(self):
        entity = ValveEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("closed"))
        self.assertFalse(entity.is_open)
        entity.process_state_change(
            _make_ha_state("closed"),
            _make_ha_state("open"),
        )
        self.assertTrue(entity.is_open)
