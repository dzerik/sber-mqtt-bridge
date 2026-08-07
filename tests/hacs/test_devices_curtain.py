"""Tests for CurtainEntity — Sber curtain/cover device mapping."""

import unittest

from custom_components.sber_mqtt_bridge.devices.curtain import CurtainEntity
from custom_components.sber_mqtt_bridge.devices.window_blind import WindowBlindEntity

ENTITY_DATA = {"entity_id": "cover.curtain", "name": "Curtain"}


def _make_ha_state(state="open", current_position=75):
    return {
        "entity_id": "cover.curtain",
        "state": state,
        "attributes": {
            "current_position": current_position,
        },
    }


class TestCurtainInit(unittest.TestCase):
    """Test CurtainEntity initialization."""

    def test_init_defaults(self):
        entity = CurtainEntity(ENTITY_DATA)
        self.assertEqual(entity.category, "curtain")
        self.assertEqual(entity.entity_id, "cover.curtain")
        self.assertEqual(entity.current_position, 0)


class TestCurtainFillByHaState(unittest.TestCase):
    """Test fill_by_ha_state parses cover attributes."""

    def test_fill_with_position(self):
        entity = CurtainEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(state="open", current_position=75))
        self.assertEqual(entity.current_position, 75)
        self.assertEqual(entity.state, "open")

    def test_fill_no_position_open_defaults_100(self):
        """No position attribute + HA state 'open' must default to 100.

        HA cover uses 'open' (not 'opened') as the state value per HA docs.
        """
        entity = CurtainEntity(ENTITY_DATA)
        entity.fill_by_ha_state(
            {
                "entity_id": "cover.curtain",
                "state": "open",
                "attributes": {},
            }
        )
        self.assertEqual(entity.current_position, 100)

    def test_fill_no_position_closed(self):
        """No position attribute + state 'closed' defaults to 0."""
        entity = CurtainEntity(ENTITY_DATA)
        entity.fill_by_ha_state(
            {
                "entity_id": "cover.curtain",
                "state": "closed",
                "attributes": {},
            }
        )
        self.assertEqual(entity.current_position, 0)

    def test_fill_position_zero(self):
        """Position=0 is stored as 0 (not treated as falsy)."""
        entity = CurtainEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(current_position=0))
        self.assertEqual(entity.current_position, 0)


class TestCurtainCreateFeaturesList(unittest.TestCase):
    """Test create_features_list."""

    def test_features(self):
        entity = CurtainEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state())
        features = entity.get_final_features_list()
        self.assertIn("open_percentage", features)
        self.assertIn("open_set", features)
        self.assertIn("open_state", features)
        self.assertIn("online", features)


class TestCurtainToSberCurrentState(unittest.TestCase):
    """Test to_sber_current_state."""

    def test_open_state(self):
        entity = CurtainEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(state="open", current_position=60))
        result = entity.to_sber_current_state()
        self.assertIn("cover.curtain", result)
        states = result["cover.curtain"]["states"]
        keys = [s["key"] for s in states]

        self.assertIn("online", keys)
        online = next(s for s in states if s["key"] == "online")
        self.assertTrue(online["value"]["bool_value"])

        self.assertIn("open_percentage", keys)
        pos = next(s for s in states if s["key"] == "open_percentage")
        self.assertEqual(pos["value"]["integer_value"], "60")

        self.assertIn("open_state", keys)
        state = next(s for s in states if s["key"] == "open_state")
        self.assertEqual(state["value"]["enum_value"], "open")

    def test_closed_state(self):
        entity = CurtainEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(state="closed", current_position=0))
        result = entity.to_sber_current_state()
        states = result["cover.curtain"]["states"]
        state = next(s for s in states if s["key"] == "open_state")
        self.assertEqual(state["value"]["enum_value"], "close")

    def test_unavailable_returns_offline(self):
        entity = CurtainEntity(ENTITY_DATA)
        entity.fill_by_ha_state(
            {
                "entity_id": "cover.curtain",
                "state": "unavailable",
                "attributes": {},
            }
        )
        result = entity.to_sber_current_state()
        self.assertIsNotNone(result)
        states = result["cover.curtain"]["states"]
        online = next(s for s in states if s["key"] == "online")
        self.assertFalse(online["value"]["bool_value"])


class TestCurtainProcessCmd(unittest.TestCase):
    """Test process_cmd dispatches HA service calls."""

    def _make_entity(self, state="open", position=50):
        entity = CurtainEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(state=state, current_position=position))
        return entity

    def test_cmd_open_percentage(self):
        entity = self._make_entity()
        result = entity.process_cmd(
            {"states": [{"key": "open_percentage", "value": {"type": "INTEGER", "integer_value": 80}}]}
        )
        self.assertEqual(len(result), 1)
        url = result[0]["url"]
        self.assertEqual(url["domain"], "cover")
        self.assertEqual(url["service"], "set_cover_position")
        self.assertEqual(url["service_data"]["position"], 80)

    def test_cmd_open_percentage_clamped(self):
        """Position values are clamped to 0-100."""
        entity = self._make_entity()
        result = entity.process_cmd(
            {"states": [{"key": "open_percentage", "value": {"type": "INTEGER", "integer_value": 150}}]}
        )
        url = result[0]["url"]
        self.assertEqual(url["service_data"]["position"], 100)

    def test_cmd_open_percentage_negative_clamped(self):
        entity = self._make_entity()
        result = entity.process_cmd(
            {"states": [{"key": "open_percentage", "value": {"type": "INTEGER", "integer_value": -10}}]}
        )
        url = result[0]["url"]
        self.assertEqual(url["service_data"]["position"], 0)

    def test_cmd_cover_position(self):
        entity = self._make_entity()
        result = entity.process_cmd({"states": [{"key": "cover_position", "value": {"integer_value": 40}}]})
        self.assertEqual(len(result), 1)
        url = result[0]["url"]
        self.assertEqual(url["service"], "set_cover_position")
        self.assertEqual(url["service_data"]["position"], 40)

    def test_cmd_open_set_open(self):
        entity = self._make_entity()
        result = entity.process_cmd({"states": [{"key": "open_set", "value": {"enum_value": "open"}}]})
        url = result[0]["url"]
        self.assertEqual(url["service"], "open_cover")

    def test_cmd_open_set_close(self):
        entity = self._make_entity()
        result = entity.process_cmd({"states": [{"key": "open_set", "value": {"enum_value": "close"}}]})
        url = result[0]["url"]
        self.assertEqual(url["service"], "close_cover")

    def test_cmd_open_set_stop(self):
        entity = self._make_entity()
        result = entity.process_cmd({"states": [{"key": "open_set", "value": {"enum_value": "stop"}}]})
        url = result[0]["url"]
        self.assertEqual(url["service"], "stop_cover")

    def test_cmd_open_set_none_value_skipped(self):
        entity = self._make_entity()
        result = entity.process_cmd({"states": [{"key": "open_set", "value": {}}]})
        self.assertEqual(len(result), 0)

    def test_cmd_no_key_skipped(self):
        entity = self._make_entity()
        result = entity.process_cmd({"states": [{"value": {"integer_value": 50}}]})
        self.assertEqual(len(result), 0)

    def test_cmd_empty_states(self):
        entity = self._make_entity()
        result = entity.process_cmd({"states": []})
        self.assertEqual(result, [])


class TestCurtainLightTransmission(unittest.TestCase):
    """Tilt feature is window_blind-only per the Sber category spec (issue #44 audit)."""

    def _blind(self, tilt):
        entity = WindowBlindEntity(ENTITY_DATA)
        entity.fill_by_ha_state(
            {
                "entity_id": "cover.curtain",
                "state": "open",
                "attributes": {"current_position": 50, "current_tilt_position": tilt},
            }
        )
        return entity

    def test_tilt_feature_present_on_window_blind(self):
        """window_blind with current_tilt_position includes light_transmission_percentage."""
        features = self._blind(80).get_final_features_list()
        self.assertIn("light_transmission_percentage", features)

    def test_tilt_feature_absent_on_curtain_category(self):
        """The curtain category spec has no light_transmission_percentage — tilt is not advertised."""
        entity = CurtainEntity(ENTITY_DATA)
        entity.fill_by_ha_state(
            {
                "entity_id": "cover.curtain",
                "state": "open",
                "attributes": {"current_position": 50, "current_tilt_position": 80},
            }
        )
        self.assertNotIn("light_transmission_percentage", entity.get_final_features_list())
        states = entity.to_sber_current_state()["cover.curtain"]["states"]
        self.assertNotIn("light_transmission_percentage", [s["key"] for s in states])

    def test_tilt_feature_absent(self):
        """window_blind without tilt must not include light_transmission_percentage."""
        entity = WindowBlindEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state())
        features = entity.get_final_features_list()
        self.assertNotIn("light_transmission_percentage", features)

    def test_tilt_value_in_state(self):
        """Tilt value=80 must produce light_transmission_percentage=80 in Sber state."""
        result = self._blind(80).to_sber_current_state()
        states = result["cover.curtain"]["states"]
        ltp = next(s for s in states if s["key"] == "light_transmission_percentage")
        self.assertEqual(ltp["value"]["integer_value"], "80")

    def test_tilt_zero_value(self):
        """Tilt=0 must still be reported (not treated as falsy)."""
        entity = self._blind(0)
        self.assertIn("light_transmission_percentage", entity.get_final_features_list())
        states = entity.to_sber_current_state()["cover.curtain"]["states"]
        ltp = next(s for s in states if s["key"] == "light_transmission_percentage")
        self.assertEqual(ltp["value"]["integer_value"], "0")

    def test_tilt_allowed_values_present(self):
        """Advertised tilt feature carries its integer limits (no dead slider)."""
        allowed = self._blind(80).create_allowed_values_list()
        self.assertIn("light_transmission_percentage", allowed)
        self.assertEqual(allowed["light_transmission_percentage"]["integer_values"]["max"], "100")

    def test_tilt_not_in_state_when_absent(self):
        """Without tilt, light_transmission_percentage must not appear in state."""
        entity = WindowBlindEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state())
        result = entity.to_sber_current_state()
        states = result["cover.curtain"]["states"]
        keys = [s["key"] for s in states]
        self.assertNotIn("light_transmission_percentage", keys)


class TestCurtainOpenRate(unittest.TestCase):
    """Test open_rate feature in CurtainEntity."""

    def test_open_rate_feature_present(self):
        """Cover with speed=low must include open_rate in features."""
        entity = CurtainEntity(ENTITY_DATA)
        entity.fill_by_ha_state(
            {
                "entity_id": "cover.curtain",
                "state": "open",
                "attributes": {"current_position": 50, "speed": "low"},
            }
        )
        features = entity.get_final_features_list()
        self.assertIn("open_rate", features)

    def test_open_rate_feature_absent(self):
        """Cover without speed must not include open_rate."""
        entity = CurtainEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state())
        features = entity.get_final_features_list()
        self.assertNotIn("open_rate", features)

    def test_open_rate_low_in_state(self):
        """speed=low must produce open_rate=low in Sber state."""
        entity = CurtainEntity(ENTITY_DATA)
        entity.fill_by_ha_state(
            {
                "entity_id": "cover.curtain",
                "state": "open",
                "attributes": {"current_position": 50, "speed": "low"},
            }
        )
        result = entity.to_sber_current_state()
        states = result["cover.curtain"]["states"]
        rate = next(s for s in states if s["key"] == "open_rate")
        self.assertEqual(rate["value"]["enum_value"], "low")

    def test_open_rate_high_in_state(self):
        """speed=high must produce open_rate=high in Sber state."""
        entity = CurtainEntity(ENTITY_DATA)
        entity.fill_by_ha_state(
            {
                "entity_id": "cover.curtain",
                "state": "open",
                "attributes": {"current_position": 50, "speed": "high"},
            }
        )
        result = entity.to_sber_current_state()
        states = result["cover.curtain"]["states"]
        rate = next(s for s in states if s["key"] == "open_rate")
        self.assertEqual(rate["value"]["enum_value"], "high")

    def test_open_rate_auto_in_state(self):
        """speed=auto must produce open_rate=auto in Sber state."""
        entity = CurtainEntity(ENTITY_DATA)
        entity.fill_by_ha_state(
            {
                "entity_id": "cover.curtain",
                "state": "open",
                "attributes": {"current_position": 50, "speed": "auto"},
            }
        )
        result = entity.to_sber_current_state()
        states = result["cover.curtain"]["states"]
        rate = next(s for s in states if s["key"] == "open_rate")
        self.assertEqual(rate["value"]["enum_value"], "auto")

    def test_open_rate_invalid_speed_ignored(self):
        """Unrecognized speed value must not produce open_rate."""
        entity = CurtainEntity(ENTITY_DATA)
        entity.fill_by_ha_state(
            {
                "entity_id": "cover.curtain",
                "state": "open",
                "attributes": {"current_position": 50, "speed": "turbo"},
            }
        )
        features = entity.get_final_features_list()
        self.assertNotIn("open_rate", features)

    def test_open_rate_motor_speed_alias(self):
        """motor_speed attribute must also be recognized as open_rate source."""
        entity = CurtainEntity(ENTITY_DATA)
        entity.fill_by_ha_state(
            {
                "entity_id": "cover.curtain",
                "state": "open",
                "attributes": {"current_position": 50, "motor_speed": "high"},
            }
        )
        features = entity.get_final_features_list()
        self.assertIn("open_rate", features)

    def test_open_rate_not_in_state_when_absent(self):
        """Without speed, open_rate must not appear in Sber state."""
        entity = CurtainEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state())
        result = entity.to_sber_current_state()
        states = result["cover.curtain"]["states"]
        keys = [s["key"] for s in states]
        self.assertNotIn("open_rate", keys)

    def test_open_rate_allowed_values_reference(self):
        """open_rate carries the Sber reference enum values (issue #44 audit).

        An ENUM feature without enum_values renders a dead control —
        the curtain reference example declares ["auto", "low", "high"].
        """
        entity = CurtainEntity(ENTITY_DATA)
        entity.fill_by_ha_state(
            {
                "entity_id": "cover.curtain",
                "state": "open",
                "attributes": {"current_position": 50, "speed": "low"},
            }
        )
        result = entity.to_sber_state()
        allowed = result["model"]["allowed_values"]
        self.assertIn("open_rate", allowed)
        self.assertEqual(allowed["open_rate"]["enum_values"]["values"], ["auto", "low", "high"])

    def test_open_rate_no_allowed_values_when_absent(self):
        """open_rate must not appear in allowed values when absent."""
        entity = CurtainEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state())
        result = entity.to_sber_state()
        allowed = result["model"]["allowed_values"]
        self.assertNotIn("open_rate", allowed)


class TestCurtainProcessStateChange(unittest.TestCase):
    """Test process_state_change."""

    def test_state_change(self):
        entity = CurtainEntity(ENTITY_DATA)
        old = _make_ha_state(state="closed", current_position=0)
        new = _make_ha_state(state="open", current_position=100)
        entity.fill_by_ha_state(old)
        self.assertEqual(entity.current_position, 0)
        entity.process_state_change(old, new)
        self.assertEqual(entity.current_position, 100)
