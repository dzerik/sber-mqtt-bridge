"""Tests for ValveEntity — Sber valve device mapping."""

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
        self.assertFalse(entity.current_state)


class TestValveFillByHaState(unittest.TestCase):
    """Test fill_by_ha_state."""

    def test_fill_open(self):
        entity = ValveEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("open"))
        self.assertTrue(entity.current_state)

    def test_fill_closed(self):
        entity = ValveEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("closed"))
        self.assertFalse(entity.current_state)

    def test_fill_other_state(self):
        entity = ValveEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("unknown"))
        self.assertFalse(entity.current_state)


class TestValveCreateFeaturesList(unittest.TestCase):
    """Test create_features_list."""

    def test_features(self):
        entity = ValveEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state())
        features = entity.create_features_list()
        self.assertIn("on_off", features)
        self.assertIn("online", features)


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

        on_off = next(s for s in states if s["key"] == "on_off")
        self.assertTrue(on_off["value"]["bool_value"])

    def test_closed(self):
        entity = ValveEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("closed"))
        result = entity.to_sber_current_state()
        states = result["valve.main"]["states"]
        on_off = next(s for s in states if s["key"] == "on_off")
        self.assertFalse(on_off["value"]["bool_value"])

    def test_unavailable_offline(self):
        entity = ValveEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("unavailable"))
        result = entity.to_sber_current_state()
        states = result["valve.main"]["states"]
        online = next(s for s in states if s["key"] == "online")
        self.assertFalse(online["value"]["bool_value"])


class TestValveProcessCmd(unittest.TestCase):
    """Test process_cmd."""

    def _make_entity(self, state="closed"):
        entity = ValveEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(state))
        return entity

    def test_cmd_open(self):
        entity = self._make_entity("closed")
        result = entity.process_cmd({
            "states": [{"key": "on_off", "value": {"type": "BOOL", "bool_value": True}}]
        })
        self.assertEqual(len(result), 1)
        url = result[0]["url"]
        self.assertEqual(url["domain"], "valve")
        self.assertEqual(url["service"], "open_valve")
        self.assertTrue(entity.current_state)

    def test_cmd_close(self):
        entity = self._make_entity("open")
        result = entity.process_cmd({
            "states": [{"key": "on_off", "value": {"type": "BOOL", "bool_value": False}}]
        })
        url = result[0]["url"]
        self.assertEqual(url["service"], "close_valve")
        self.assertFalse(entity.current_state)

    def test_cmd_wrong_type_ignored(self):
        """Non-BOOL type for on_off is ignored."""
        entity = self._make_entity()
        result = entity.process_cmd({
            "states": [{"key": "on_off", "value": {"type": "INTEGER", "bool_value": True}}]
        })
        self.assertEqual(len(result), 0)

    def test_cmd_empty_states(self):
        entity = self._make_entity()
        result = entity.process_cmd({"states": []})
        self.assertEqual(result, [])

    def test_cmd_unknown_key_ignored(self):
        entity = self._make_entity()
        result = entity.process_cmd({
            "states": [{"key": "unknown", "value": {"type": "BOOL", "bool_value": True}}]
        })
        self.assertEqual(len(result), 0)


class TestValveProcessStateChange(unittest.TestCase):
    """Test process_state_change."""

    def test_state_change(self):
        entity = ValveEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("closed"))
        self.assertFalse(entity.current_state)
        entity.process_state_change(
            _make_ha_state("closed"),
            _make_ha_state("open"),
        )
        self.assertTrue(entity.current_state)
