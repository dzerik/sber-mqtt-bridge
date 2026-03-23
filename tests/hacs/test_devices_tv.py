"""Tests for TvEntity -- Sber TV device mapping."""

import unittest

from custom_components.sber_mqtt_bridge.devices.tv import TvEntity


ENTITY_DATA = {"entity_id": "media_player.tv", "name": "Living Room TV"}


def _make_ha_state(state="playing", **attrs):
    return {
        "entity_id": "media_player.tv",
        "state": state,
        "attributes": attrs,
    }


class TestTvCreate(unittest.TestCase):
    """Test TvEntity initialization."""

    def test_category(self):
        entity = TvEntity(ENTITY_DATA)
        self.assertEqual(entity.category, "tv")

    def test_initial_state(self):
        entity = TvEntity(ENTITY_DATA)
        self.assertFalse(entity.current_state)

    def test_features_list(self):
        entity = TvEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state())
        features = entity.create_features_list()
        self.assertIn("online", features)
        self.assertIn("on_off", features)
        self.assertIn("volume_int", features)
        self.assertIn("mute", features)
        self.assertIn("source", features)


class TestTvFillState(unittest.TestCase):
    """Test fill_by_ha_state."""

    def test_playing_is_on(self):
        entity = TvEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("playing", volume_level=0.5))
        self.assertTrue(entity.current_state)
        self.assertEqual(entity._volume, 50)

    def test_off_state(self):
        entity = TvEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("off"))
        self.assertFalse(entity.current_state)

    def test_standby_is_off(self):
        entity = TvEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("standby"))
        self.assertFalse(entity.current_state)

    def test_volume_conversion(self):
        entity = TvEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("on", volume_level=0.75))
        self.assertEqual(entity._volume, 75)

    def test_source_list(self):
        entity = TvEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("on", source="HDMI 1", source_list=["HDMI 1", "HDMI 2", "TV"]))
        self.assertEqual(entity._source, "HDMI 1")
        self.assertEqual(entity._source_list, ["HDMI 1", "HDMI 2", "TV"])


class TestTvToSberCurrentState(unittest.TestCase):
    """Test to_sber_current_state."""

    def test_on_with_volume(self):
        entity = TvEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("playing", volume_level=0.3, is_volume_muted=False, source="HDMI 1"))
        result = entity.to_sber_current_state()
        states = result["media_player.tv"]["states"]
        on_off = next(s for s in states if s["key"] == "on_off")
        self.assertTrue(on_off["value"]["bool_value"])
        vol = next(s for s in states if s["key"] == "volume_int")
        self.assertEqual(vol["value"]["integer_value"], "30")
        mute = next(s for s in states if s["key"] == "mute")
        self.assertFalse(mute["value"]["bool_value"])
        source = next(s for s in states if s["key"] == "source")
        self.assertEqual(source["value"]["enum_value"], "HDMI 1")

    def test_off_state(self):
        entity = TvEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("off"))
        result = entity.to_sber_current_state()
        states = result["media_player.tv"]["states"]
        on_off = next(s for s in states if s["key"] == "on_off")
        self.assertFalse(on_off["value"]["bool_value"])

    def test_unavailable_offline(self):
        entity = TvEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("unavailable"))
        result = entity.to_sber_current_state()
        states = result["media_player.tv"]["states"]
        online = next(s for s in states if s["key"] == "online")
        self.assertFalse(online["value"]["bool_value"])

    def test_no_source_if_none(self):
        entity = TvEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("on", volume_level=0.5))
        result = entity.to_sber_current_state()
        states = result["media_player.tv"]["states"]
        keys = [s["key"] for s in states]
        self.assertNotIn("source", keys)


class TestTvProcessCmd(unittest.TestCase):
    """Test process_cmd."""

    def _make_entity(self, state="playing", **attrs):
        entity = TvEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(state, **attrs))
        return entity

    def test_cmd_turn_on(self):
        entity = self._make_entity("off")
        result = entity.process_cmd({"states": [{"key": "on_off", "value": {"type": "BOOL", "bool_value": True}}]})
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["url"]["service"], "turn_on")
        self.assertEqual(result[0]["url"]["domain"], "media_player")

    def test_cmd_turn_off(self):
        entity = self._make_entity("playing")
        result = entity.process_cmd({"states": [{"key": "on_off", "value": {"type": "BOOL", "bool_value": False}}]})
        self.assertEqual(result[0]["url"]["service"], "turn_off")

    def test_cmd_volume_set(self):
        entity = self._make_entity("playing")
        result = entity.process_cmd(
            {"states": [{"key": "volume_int", "value": {"type": "INTEGER", "integer_value": "50"}}]}
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["url"]["service"], "volume_set")
        self.assertAlmostEqual(result[0]["url"]["service_data"]["volume_level"], 0.5)

    def test_cmd_mute(self):
        entity = self._make_entity("playing")
        result = entity.process_cmd({"states": [{"key": "mute", "value": {"type": "BOOL", "bool_value": True}}]})
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["url"]["service"], "volume_mute")
        self.assertTrue(result[0]["url"]["service_data"]["is_volume_muted"])

    def test_cmd_select_source(self):
        entity = self._make_entity("playing")
        result = entity.process_cmd({"states": [{"key": "source", "value": {"type": "ENUM", "enum_value": "HDMI 2"}}]})
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["url"]["service"], "select_source")
        self.assertEqual(result[0]["url"]["service_data"]["source"], "HDMI 2")

    def test_cmd_empty_states(self):
        entity = self._make_entity()
        result = entity.process_cmd({"states": []})
        self.assertEqual(result, [])


class TestTvAllowedValues(unittest.TestCase):
    """Test allowed values in to_sber_state."""

    def test_volume_allowed_values(self):
        entity = TvEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("on", volume_level=0.5))
        result = entity.to_sber_state()
        allowed = result["model"]["allowed_values"]
        self.assertIn("volume_int", allowed)

    def test_source_allowed_values_with_list(self):
        entity = TvEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("on", volume_level=0.5, source_list=["HDMI 1", "TV"]))
        result = entity.to_sber_state()
        allowed = result["model"]["allowed_values"]
        self.assertIn("source", allowed)
        self.assertEqual(allowed["source"]["enum_values"]["values"], ["HDMI 1", "TV"])

    def test_source_allowed_values_without_list(self):
        entity = TvEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("on", volume_level=0.5))
        result = entity.to_sber_state()
        allowed = result["model"]["allowed_values"]
        self.assertNotIn("source", allowed)
