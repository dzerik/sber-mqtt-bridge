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
        entity.fill_by_ha_state(_make_ha_state(source_list=["HDMI 1", "TV"]))
        features = entity.create_features_list()
        self.assertIn("online", features)
        self.assertIn("on_off", features)
        self.assertIn("volume_int", features)
        self.assertIn("mute", features)
        self.assertIn("source", features)
        self.assertIn("channel", features)
        self.assertIn("direction", features)

    def test_features_no_source_without_list(self):
        entity = TvEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state())
        features = entity.create_features_list()
        self.assertNotIn("source", features)
        self.assertIn("channel", features)
        self.assertIn("direction", features)


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

    def test_cmd_channel_int(self):
        """channel_int INTEGER command must produce play_media service call."""
        entity = self._make_entity("playing")
        result = entity.process_cmd(
            {"states": [{"key": "channel_int", "value": {"type": "INTEGER", "integer_value": "5"}}]}
        )
        self.assertEqual(len(result), 1)
        url = result[0]["url"]
        self.assertEqual(url["service"], "play_media")
        self.assertEqual(url["domain"], "media_player")
        self.assertEqual(url["service_data"]["media_content_type"], "channel")
        self.assertEqual(url["service_data"]["media_content_id"], "5")

    def test_cmd_channel_int_large_number(self):
        """channel_int with large channel number must work correctly."""
        entity = self._make_entity("playing")
        result = entity.process_cmd(
            {"states": [{"key": "channel_int", "value": {"type": "INTEGER", "integer_value": "999"}}]}
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["url"]["service_data"]["media_content_id"], "999")

    def test_cmd_channel_int_none_skipped(self):
        """channel_int with None integer_value must be skipped."""
        entity = self._make_entity("playing")
        result = entity.process_cmd(
            {"states": [{"key": "channel_int", "value": {"type": "INTEGER"}}]}
        )
        self.assertEqual(len(result), 0)

    def test_cmd_direction_up(self):
        """direction=up must produce media_player.volume_up service call."""
        entity = self._make_entity("playing")
        result = entity.process_cmd(
            {"states": [{"key": "direction", "value": {"type": "ENUM", "enum_value": "up"}}]}
        )
        self.assertEqual(len(result), 1)
        url = result[0]["url"]
        self.assertEqual(url["domain"], "media_player")
        self.assertEqual(url["service"], "volume_up")

    def test_cmd_direction_down(self):
        """direction=down must produce media_player.volume_down service call."""
        entity = self._make_entity("playing")
        result = entity.process_cmd(
            {"states": [{"key": "direction", "value": {"type": "ENUM", "enum_value": "down"}}]}
        )
        self.assertEqual(len(result), 1)
        url = result[0]["url"]
        self.assertEqual(url["service"], "volume_down")

    def test_cmd_direction_left_right_ok_handled(self):
        """direction left/right/ok produce service calls per Sber spec."""
        entity = self._make_entity("playing")
        expected = {"left": "media_previous_track", "right": "media_next_track", "ok": "media_play_pause"}
        for direction, service in expected.items():
            result = entity.process_cmd(
                {"states": [{"key": "direction", "value": {"type": "ENUM", "enum_value": direction}}]}
            )
            self.assertEqual(len(result), 1, f"direction={direction} should produce a service call")
            self.assertEqual(result[0]["url"]["service"], service)

    def test_cmd_direction_empty_skipped(self):
        """direction with empty enum_value must be skipped."""
        entity = self._make_entity("playing")
        result = entity.process_cmd(
            {"states": [{"key": "direction", "value": {"type": "ENUM", "enum_value": ""}}]}
        )
        self.assertEqual(len(result), 0)

    def test_cmd_channel_plus(self):
        """channel=+ must produce media_next_track service call."""
        entity = self._make_entity("playing")
        result = entity.process_cmd(
            {"states": [{"key": "channel", "value": {"type": "ENUM", "enum_value": "+"}}]}
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["url"]["service"], "media_next_track")

    def test_cmd_channel_minus(self):
        """channel=- must produce media_previous_track service call."""
        entity = self._make_entity("playing")
        result = entity.process_cmd(
            {"states": [{"key": "channel", "value": {"type": "ENUM", "enum_value": "-"}}]}
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["url"]["service"], "media_previous_track")

    def test_cmd_empty_states(self):
        entity = self._make_entity()
        result = entity.process_cmd({"states": []})
        self.assertEqual(result, [])


class TestTvFeatures(unittest.TestCase):
    """Test channel_int and direction in features list."""

    def test_channel_int_in_features(self):
        """channel_int must always be in features list."""
        entity = TvEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("on", volume_level=0.5))
        features = entity.create_features_list()
        self.assertIn("channel_int", features)

    def test_direction_in_features(self):
        """direction must always be in features list."""
        entity = TvEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("on", volume_level=0.5))
        features = entity.create_features_list()
        self.assertIn("direction", features)

    def test_channel_in_features(self):
        """channel must always be in features list."""
        entity = TvEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("on", volume_level=0.5))
        features = entity.create_features_list()
        self.assertIn("channel", features)


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

    def test_channel_int_allowed_values(self):
        """channel_int must have INTEGER allowed values with min=1, max=999."""
        entity = TvEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("on", volume_level=0.5))
        result = entity.to_sber_state()
        allowed = result["model"]["allowed_values"]
        self.assertIn("channel_int", allowed)
        self.assertEqual(allowed["channel_int"]["type"], "INTEGER")
        self.assertEqual(allowed["channel_int"]["integer_values"]["min"], "1")
        self.assertEqual(allowed["channel_int"]["integer_values"]["max"], "999")

    def test_direction_allowed_values(self):
        """direction must have ENUM allowed values with up/down/left/right/ok."""
        entity = TvEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("on", volume_level=0.5))
        result = entity.to_sber_state()
        allowed = result["model"]["allowed_values"]
        self.assertIn("direction", allowed)
        self.assertEqual(allowed["direction"]["type"], "ENUM")
        values = allowed["direction"]["enum_values"]["values"]
        self.assertEqual(values, ["up", "down", "left", "right", "ok"])

    def test_channel_allowed_values(self):
        """channel must have ENUM allowed values with +/-."""
        entity = TvEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("on", volume_level=0.5))
        result = entity.to_sber_state()
        allowed = result["model"]["allowed_values"]
        self.assertIn("channel", allowed)
        self.assertEqual(allowed["channel"]["enum_values"]["values"], ["+", "-"])
