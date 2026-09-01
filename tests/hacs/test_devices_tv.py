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
        features = entity.get_final_features_list()
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
        features = entity.get_final_features_list()
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
        entity.fill_by_ha_state(
            _make_ha_state(
                "playing",
                volume_level=0.3,
                is_volume_muted=False,
                source="HDMI 1",
                source_list=["HDMI 1", "TV"],
            )
        )
        result = entity.to_sber_current_state()
        states = result["media_player.tv"]["states"]
        on_off = next(s for s in states if s["key"] == "on_off")
        self.assertTrue(on_off["value"]["bool_value"])
        vol = next(s for s in states if s["key"] == "volume_int")
        self.assertEqual(vol["value"]["integer_value"], "30")
        mute = next(s for s in states if s["key"] == "mute")
        self.assertFalse(mute["value"]["bool_value"])
        source = next(s for s in states if s["key"] == "source")
        # Sber knows hdmi1/hdmi2/hdmi3/tv/av/content/screencast — never the
        # HA input label, so "HDMI 1" is published as "hdmi1".
        self.assertEqual(source["value"]["enum_value"], "hdmi1")

    def test_source_not_published_without_source_list(self):
        """Without ``source_list`` the ``source`` feature is not declared.

        Publishing it anyway produced a ``not_declared`` finding and an
        ENUM value outside any declared ``allowed_values`` (issue #44
        follow-up); the base-class filter now drops it.
        """
        entity = TvEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("playing", source="HDMI 1"))
        self.assertNotIn("source", entity.get_final_features_list())
        states = entity.to_sber_current_state()["media_player.tv"]["states"]
        self.assertNotIn("source", [s["key"] for s in states])

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
        """A documented Sber input is translated back to the HA label.

        The command used to be asserted with ``"HDMI 2"`` — a value Sber
        cannot send: its ``source`` vocabulary is ``hdmi1, hdmi2, hdmi3,
        tv, av, content, screencast, +, -``.  What it does send is
        ``hdmi2``, and ``media_player.select_source`` only accepts a name
        from ``source_list``.
        """
        entity = self._make_entity("playing", source_list=["HDMI 1", "HDMI 2"])
        result = entity.process_cmd({"states": [{"key": "source", "value": {"type": "ENUM", "enum_value": "hdmi2"}}]})
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

    def test_cmd_channel_int_omitted_value_is_zero(self):
        """channel_int without integer_value means channel 0 (proto3 omission).

        Sber drops proto3-default fields, so ``{"type": "INTEGER"}`` is a
        legitimate command carrying 0 — it must not be skipped (issue #44).
        """
        entity = self._make_entity("playing")
        result = entity.process_cmd({"states": [{"key": "channel_int", "value": {"type": "INTEGER"}}]})
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["url"]["service"], "play_media")

    def test_cmd_channel_int_valueless_payload_skipped(self):
        """channel_int without even a type must be skipped (malformed)."""
        entity = self._make_entity("playing")
        result = entity.process_cmd({"states": [{"key": "channel_int", "value": {}}]})
        self.assertEqual(len(result), 0)

    def test_cmd_direction_up(self):
        """direction=up must produce media_player.volume_up service call."""
        entity = self._make_entity("playing")
        result = entity.process_cmd({"states": [{"key": "direction", "value": {"type": "ENUM", "enum_value": "up"}}]})
        self.assertEqual(len(result), 1)
        url = result[0]["url"]
        self.assertEqual(url["domain"], "media_player")
        self.assertEqual(url["service"], "volume_up")

    def test_cmd_direction_down(self):
        """direction=down must produce media_player.volume_down service call."""
        entity = self._make_entity("playing")
        result = entity.process_cmd({"states": [{"key": "direction", "value": {"type": "ENUM", "enum_value": "down"}}]})
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
        result = entity.process_cmd({"states": [{"key": "direction", "value": {"type": "ENUM", "enum_value": ""}}]})
        self.assertEqual(len(result), 0)

    def test_cmd_channel_plus(self):
        """channel=+ must produce media_next_track service call."""
        entity = self._make_entity("playing")
        result = entity.process_cmd({"states": [{"key": "channel", "value": {"type": "ENUM", "enum_value": "+"}}]})
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["url"]["service"], "media_next_track")

    def test_cmd_channel_minus(self):
        """channel=- must produce media_previous_track service call."""
        entity = self._make_entity("playing")
        result = entity.process_cmd({"states": [{"key": "channel", "value": {"type": "ENUM", "enum_value": "-"}}]})
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
        features = entity.get_final_features_list()
        self.assertIn("channel_int", features)

    def test_direction_in_features(self):
        """direction must always be in features list."""
        entity = TvEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("on", volume_level=0.5))
        features = entity.get_final_features_list()
        self.assertIn("direction", features)

    def test_channel_in_features(self):
        """channel must always be in features list."""
        entity = TvEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("on", volume_level=0.5))
        features = entity.get_final_features_list()
        self.assertIn("channel", features)


class TestTvAllowedValues(unittest.TestCase):
    """Test allowed values in to_sber_state."""

    def test_no_allowed_values_without_source_list(self):
        """TV without source_list must have empty allowed_values (Sber uses defaults)."""
        entity = TvEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("on", volume_level=0.5))
        result = entity.to_sber_state()
        # No allowed_values key when source_list is empty
        self.assertNotIn("allowed_values", result["model"])

    def test_source_allowed_values_with_list(self):
        """TV with source_list declares the Sber values, not the HA labels.

        The app renders exactly what is declared and echoes it back as a
        command, so ``"HDMI 1"`` (outside Sber's ``source`` vocabulary)
        would be a control that cannot work.
        """
        entity = TvEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("on", volume_level=0.5, source_list=["HDMI 1", "TV"]))
        result = entity.to_sber_state()
        allowed = result["model"]["allowed_values"]
        self.assertEqual(list(allowed.keys()), ["source"])
        self.assertEqual(allowed["source"]["enum_values"]["values"], ["hdmi1", "tv"])


class TestTvNewFeatures(unittest.TestCase):
    """Test new TV features: custom_key, volume, number."""

    def test_custom_key_in_features(self):
        """custom_key must be in features list."""
        entity = TvEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("on", volume_level=0.5))
        self.assertIn("custom_key", entity.get_final_features_list())

    def test_volume_in_features(self):
        """volume (relative) must be in features list."""
        entity = TvEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("on", volume_level=0.5))
        self.assertIn("volume", entity.get_final_features_list())

    def test_number_in_features(self):
        """number must be in features list."""
        entity = TvEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("on", volume_level=0.5))
        self.assertIn("number", entity.get_final_features_list())


class TestTvProcessCmdNewKeys(unittest.TestCase):
    """Test process_cmd for custom_key, volume, number."""

    def _make_entity(self, state="playing", **attrs):
        entity = TvEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(state, **attrs))
        return entity

    def test_volume_plus(self):
        """volume=+ must produce media_player.volume_up."""
        entity = self._make_entity()
        result = entity.process_cmd({"states": [{"key": "volume", "value": {"type": "ENUM", "enum_value": "+"}}]})
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["url"]["service"], "volume_up")
        self.assertEqual(result[0]["url"]["domain"], "media_player")

    def test_volume_minus(self):
        """volume=- must produce media_player.volume_down."""
        entity = self._make_entity()
        result = entity.process_cmd({"states": [{"key": "volume", "value": {"type": "ENUM", "enum_value": "-"}}]})
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["url"]["service"], "volume_down")

    def test_number_digit(self):
        """number=5 must produce play_media with channel content type."""
        entity = self._make_entity()
        result = entity.process_cmd({"states": [{"key": "number", "value": {"type": "INTEGER", "integer_value": "5"}}]})
        self.assertEqual(len(result), 1)
        url = result[0]["url"]
        self.assertEqual(url["service"], "play_media")
        self.assertEqual(url["service_data"]["media_content_type"], "channel")
        self.assertEqual(url["service_data"]["media_content_id"], "5")

    def test_number_zero(self):
        """number=0 must produce play_media with channel '0'."""
        entity = self._make_entity()
        result = entity.process_cmd({"states": [{"key": "number", "value": {"type": "INTEGER", "integer_value": "0"}}]})
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["url"]["service_data"]["media_content_id"], "0")

    def test_number_omitted_value_is_zero(self):
        """number without integer_value means digit 0 (proto3 omission)."""
        entity = self._make_entity()
        result = entity.process_cmd({"states": [{"key": "number", "value": {"type": "INTEGER"}}]})
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["url"]["service"], "play_media")

    def test_number_valueless_payload_skipped(self):
        """number without even a type must be skipped (malformed)."""
        entity = self._make_entity()
        result = entity.process_cmd({"states": [{"key": "number", "value": {}}]})
        self.assertEqual(len(result), 0)

    def test_custom_key_play(self):
        """custom_key=play must produce media_player.media_play."""
        entity = self._make_entity()
        result = entity.process_cmd(
            {"states": [{"key": "custom_key", "value": {"type": "ENUM", "enum_value": "play"}}]}
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["url"]["service"], "media_play")
        self.assertEqual(result[0]["url"]["domain"], "media_player")

    def test_custom_key_pause(self):
        """custom_key=pause must produce media_player.media_pause."""
        entity = self._make_entity()
        result = entity.process_cmd(
            {"states": [{"key": "custom_key", "value": {"type": "ENUM", "enum_value": "pause"}}]}
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["url"]["service"], "media_pause")

    def test_custom_key_stop(self):
        """custom_key=stop must produce media_player.media_stop."""
        entity = self._make_entity()
        result = entity.process_cmd(
            {"states": [{"key": "custom_key", "value": {"type": "ENUM", "enum_value": "stop"}}]}
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["url"]["service"], "media_stop")

    def test_custom_key_rewind(self):
        """custom_key=rewind must produce media_player.media_previous_track."""
        entity = self._make_entity()
        result = entity.process_cmd(
            {"states": [{"key": "custom_key", "value": {"type": "ENUM", "enum_value": "rewind"}}]}
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["url"]["service"], "media_previous_track")

    def test_custom_key_fast_forward(self):
        """custom_key=fast_forward must produce media_player.media_next_track."""
        entity = self._make_entity()
        result = entity.process_cmd(
            {"states": [{"key": "custom_key", "value": {"type": "ENUM", "enum_value": "fast_forward"}}]}
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["url"]["service"], "media_next_track")

    def test_custom_key_unsupported_logged(self):
        """custom_key=back (unsupported) must not produce service call."""
        entity = self._make_entity()
        result = entity.process_cmd(
            {"states": [{"key": "custom_key", "value": {"type": "ENUM", "enum_value": "back"}}]}
        )
        self.assertEqual(len(result), 0)

    def test_custom_key_empty_skipped(self):
        """custom_key with empty enum_value must be skipped."""
        entity = self._make_entity()
        result = entity.process_cmd({"states": [{"key": "custom_key", "value": {"type": "ENUM", "enum_value": ""}}]})
        self.assertEqual(len(result), 0)


class TestSourceListSurvivesAnEmptyRefresh(unittest.TestCase):
    """A momentarily blank ``source_list`` must not disarm the TV.

    ``MediaPlayerEntity.capability_attributes`` adds ``source_list`` only
    ``if (source_list := self.source_list)``, so an empty list removes the
    attribute outright.  Core integrations produce exactly that
    transiently: ``braviatv`` clears the list at the top of every update
    and returns early while the TV is off, and ``apple_tv`` fills it only
    after a fetch that can fail.

    Rebuilding the translation table from such a blank used to erase it,
    after which every ``source`` command the cloud sent was dropped — the
    Sber app kept rendering the HDMI button and it silently stopped doing
    anything.  No republish repairs that, so the list is kept instead.
    """

    HDMI1_CMD = {"states": [{"key": "source", "value": {"type": "ENUM", "enum_value": "hdmi1"}}]}

    def _tv_that_lost_its_list(self, second_state):
        """Fill a TV with two inputs, then re-fill it with ``second_state``."""
        entity = TvEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("playing", source="HDMI 1", source_list=["HDMI 1", "TV"]))
        entity.fill_by_ha_state(second_state)
        return entity

    def test_command_survives_an_empty_source_list(self):
        """An empty list is a gap in the data, not a TV that lost its inputs."""
        entity = self._tv_that_lost_its_list(_make_ha_state("playing", source_list=[]))
        result = entity.process_cmd(self.HDMI1_CMD)
        self.assertEqual(len(result), 1, "the source command was silently dropped")
        self.assertEqual(result[0]["url"]["service_data"]["source"], "HDMI 1")

    def test_command_survives_a_missing_source_list(self):
        """The attribute vanishing entirely is the same gap."""
        entity = self._tv_that_lost_its_list(_make_ha_state("playing"))
        result = entity.process_cmd(self.HDMI1_CMD)
        self.assertEqual(len(result), 1, "the source command was silently dropped")
        self.assertEqual(result[0]["url"]["service_data"]["source"], "HDMI 1")

    def test_allowed_values_do_not_churn(self):
        """``allowed_values`` drives ``model.id`` — it must not flap.

        A narrower republish makes Sber re-register the device, which
        costs the user the room they assigned it (issue #44).
        """
        entity = self._tv_that_lost_its_list(_make_ha_state("playing"))
        allowed = entity.create_allowed_values_list()
        self.assertEqual(allowed["source"]["enum_values"]["values"], ["hdmi1", "tv"])

    def test_a_real_new_list_still_replaces_the_old_one(self):
        """Preservation must not freeze the mapping: a real list wins."""
        entity = self._tv_that_lost_its_list(_make_ha_state("playing", source_list=["AV"]))
        allowed = entity.create_allowed_values_list()
        self.assertEqual(allowed["source"]["enum_values"]["values"], ["av"])
        self.assertEqual(entity.process_cmd(self.HDMI1_CMD), [], "a dropped input must stop resolving")
