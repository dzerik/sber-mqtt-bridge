"""Tests for WindowBlindEntity -- Sber window_blind device mapping with tilt support."""

import unittest

from custom_components.sber_mqtt_bridge.devices.window_blind import WindowBlindEntity


ENTITY_DATA = {"entity_id": "cover.blind", "name": "Living Room Blind"}


def _make_ha_state(state="open", current_position=None, current_tilt_position=None, **extra_attrs):
    """Build a minimal HA state dict for cover.blind.

    Args:
        state: HA cover state (open, closed, opening, closing, unavailable).
        current_position: Cover position 0-100, or None to omit.
        current_tilt_position: Tilt position 0-100, or None to omit.
        **extra_attrs: Additional attributes to include.

    Returns:
        HA state dict suitable for fill_by_ha_state.
    """
    attrs = {}
    if current_position is not None:
        attrs["current_position"] = current_position
    if current_tilt_position is not None:
        attrs["current_tilt_position"] = current_tilt_position
    attrs.update(extra_attrs)
    return {
        "entity_id": "cover.blind",
        "state": state,
        "attributes": attrs,
    }


class TestWindowBlindInit(unittest.TestCase):
    """Test WindowBlindEntity initialization and category assignment."""

    def test_category_is_window_blind(self):
        """WindowBlindEntity must use Sber 'window_blind' category."""
        entity = WindowBlindEntity(ENTITY_DATA)
        self.assertEqual(entity.category, "window_blind")

    def test_entity_id(self):
        """entity_id must match the provided entity data."""
        entity = WindowBlindEntity(ENTITY_DATA)
        self.assertEqual(entity.entity_id, "cover.blind")

    def test_default_position_is_zero(self):
        """Initial position must be 0 before any state fill."""
        entity = WindowBlindEntity(ENTITY_DATA)
        self.assertEqual(entity.current_position, 0)

    def test_inherits_curtain(self):
        """WindowBlindEntity must be a subclass of CurtainEntity."""
        from custom_components.sber_mqtt_bridge.devices.curtain import CurtainEntity

        entity = WindowBlindEntity(ENTITY_DATA)
        self.assertIsInstance(entity, CurtainEntity)


class TestWindowBlindFillByHaState(unittest.TestCase):
    """Test fill_by_ha_state parses blind cover attributes including tilt."""

    def test_fill_position_and_tilt(self):
        """Both position and tilt must be stored."""
        entity = WindowBlindEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(
            state="open", current_position=60, current_tilt_position=80,
        ))
        self.assertEqual(entity.current_position, 60)
        self.assertEqual(entity.state, "open")

    def test_fill_position_without_tilt(self):
        """Position without tilt must work; tilt remains None."""
        entity = WindowBlindEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(state="open", current_position=40))
        self.assertEqual(entity.current_position, 40)

    def test_fill_no_position_open_defaults_100(self):
        """No position attribute + HA state 'open' must default to 100."""
        entity = WindowBlindEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(state="open"))
        self.assertEqual(entity.current_position, 100)

    def test_fill_no_position_closed_defaults_0(self):
        """No position attribute + state 'closed' defaults to 0."""
        entity = WindowBlindEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(state="closed"))
        self.assertEqual(entity.current_position, 0)

    def test_fill_tilt_zero(self):
        """Tilt=0 must be stored (not treated as falsy)."""
        entity = WindowBlindEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(
            state="open", current_position=50, current_tilt_position=0,
        ))
        # Verify tilt is stored by checking features list
        features = entity.create_features_list()
        self.assertIn("light_transmission_percentage", features)

    def test_fill_opening_state(self):
        """Transitional 'opening' state is preserved."""
        entity = WindowBlindEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(state="opening", current_position=30))
        self.assertEqual(entity.state, "opening")

    def test_fill_closing_state(self):
        """Transitional 'closing' state is preserved."""
        entity = WindowBlindEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(state="closing", current_position=70))
        self.assertEqual(entity.state, "closing")


class TestWindowBlindCreateFeaturesList(unittest.TestCase):
    """Test create_features_list returns correct Sber features."""

    def test_features_without_tilt(self):
        """Blind without tilt must have core features only."""
        entity = WindowBlindEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(state="open", current_position=50))
        features = entity.create_features_list()
        self.assertIn("online", features)
        self.assertIn("open_set", features)
        self.assertIn("open_state", features)
        self.assertIn("open_percentage", features)
        self.assertNotIn("light_transmission_percentage", features)

    def test_features_with_tilt(self):
        """Blind with tilt must include light_transmission_percentage."""
        entity = WindowBlindEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(
            state="open", current_position=50, current_tilt_position=45,
        ))
        features = entity.create_features_list()
        self.assertIn("light_transmission_percentage", features)

    def test_signal_strength_feature_when_rssi_present(self):
        """signal_strength feature appears when rssi attribute is set."""
        entity = WindowBlindEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(
            state="open", current_position=50, signal_strength=-55,
        ))
        features = entity.create_features_list()
        self.assertIn("signal_strength", features)


class TestWindowBlindToSberState(unittest.TestCase):
    """Test to_sber_state produces correct Sber config JSON."""

    def test_config_category_is_window_blind(self):
        """Sber config must report model.category='window_blind'."""
        entity = WindowBlindEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(state="open", current_position=50))
        result = entity.to_sber_state()
        self.assertEqual(result["model"]["category"], "window_blind")

    def test_config_has_allowed_values(self):
        """Sber config must include allowed_values for open_set and open_percentage."""
        entity = WindowBlindEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(state="open", current_position=50))
        result = entity.to_sber_state()
        allowed = result["model"]["allowed_values"]
        self.assertIn("open_set", allowed)
        self.assertIn("open_percentage", allowed)

    def test_config_features_include_tilt_when_present(self):
        """Features in config must include light_transmission_percentage if tilt is set."""
        entity = WindowBlindEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(
            state="open", current_position=50, current_tilt_position=60,
        ))
        result = entity.to_sber_state()
        features = result["model"]["features"]
        self.assertIn("light_transmission_percentage", features)


class TestWindowBlindToSberCurrentState(unittest.TestCase):
    """Test to_sber_current_state produces correct Sber state payload."""

    def test_open_state_with_position(self):
        """Open blind must report open_state=open and position as string."""
        entity = WindowBlindEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(state="open", current_position=75))
        result = entity.to_sber_current_state()
        self.assertIn("cover.blind", result)
        states = result["cover.blind"]["states"]

        online = next(s for s in states if s["key"] == "online")
        self.assertTrue(online["value"]["bool_value"])

        pos = next(s for s in states if s["key"] == "open_percentage")
        self.assertEqual(pos["value"]["integer_value"], "75")

        open_state = next(s for s in states if s["key"] == "open_state")
        self.assertEqual(open_state["value"]["enum_value"], "open")

    def test_closed_state(self):
        """Closed blind must report open_state=close."""
        entity = WindowBlindEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(state="closed", current_position=0))
        result = entity.to_sber_current_state()
        states = result["cover.blind"]["states"]
        open_state = next(s for s in states if s["key"] == "open_state")
        self.assertEqual(open_state["value"]["enum_value"], "close")

    def test_tilt_value_in_state(self):
        """Tilt=80 must produce light_transmission_percentage=80 as string."""
        entity = WindowBlindEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(
            state="open", current_position=50, current_tilt_position=80,
        ))
        result = entity.to_sber_current_state()
        states = result["cover.blind"]["states"]
        ltp = next(s for s in states if s["key"] == "light_transmission_percentage")
        self.assertEqual(ltp["value"]["integer_value"], "80")

    def test_tilt_zero_in_state(self):
        """Tilt=0 must still be reported (not treated as falsy)."""
        entity = WindowBlindEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(
            state="open", current_position=50, current_tilt_position=0,
        ))
        result = entity.to_sber_current_state()
        states = result["cover.blind"]["states"]
        ltp = next(s for s in states if s["key"] == "light_transmission_percentage")
        self.assertEqual(ltp["value"]["integer_value"], "0")

    def test_no_tilt_in_state_when_absent(self):
        """Without tilt, light_transmission_percentage must not appear in state."""
        entity = WindowBlindEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(state="open", current_position=50))
        result = entity.to_sber_current_state()
        states = result["cover.blind"]["states"]
        keys = [s["key"] for s in states]
        self.assertNotIn("light_transmission_percentage", keys)

    def test_unavailable_returns_offline(self):
        """Unavailable blind must report online=False only."""
        entity = WindowBlindEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(state="unavailable"))
        result = entity.to_sber_current_state()
        states = result["cover.blind"]["states"]
        online = next(s for s in states if s["key"] == "online")
        self.assertFalse(online["value"]["bool_value"])

    def test_position_as_integer_string(self):
        """open_percentage integer_value must be a string per Sber C2C spec."""
        entity = WindowBlindEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(state="open", current_position=33))
        result = entity.to_sber_current_state()
        states = result["cover.blind"]["states"]
        pos = next(s for s in states if s["key"] == "open_percentage")
        self.assertEqual(pos["value"]["integer_value"], "33")


class TestWindowBlindProcessCmd(unittest.TestCase):
    """Test process_cmd dispatches correct HA cover service calls."""

    def _make_entity(self, state="open", position=50, tilt=None):
        entity = WindowBlindEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(
            state=state, current_position=position, current_tilt_position=tilt,
        ))
        return entity

    def test_cmd_open(self):
        """open_set=open must produce cover.open_cover."""
        entity = self._make_entity()
        result = entity.process_cmd({
            "states": [{"key": "open_set", "value": {"type": "ENUM", "enum_value": "open"}}]
        })
        self.assertEqual(len(result), 1)
        url = result[0]["url"]
        self.assertEqual(url["domain"], "cover")
        self.assertEqual(url["service"], "open_cover")
        self.assertEqual(url["target"]["entity_id"], "cover.blind")

    def test_cmd_close(self):
        """open_set=close must produce cover.close_cover."""
        entity = self._make_entity()
        result = entity.process_cmd({
            "states": [{"key": "open_set", "value": {"type": "ENUM", "enum_value": "close"}}]
        })
        url = result[0]["url"]
        self.assertEqual(url["service"], "close_cover")

    def test_cmd_stop(self):
        """open_set=stop must produce cover.stop_cover."""
        entity = self._make_entity()
        result = entity.process_cmd({
            "states": [{"key": "open_set", "value": {"type": "ENUM", "enum_value": "stop"}}]
        })
        url = result[0]["url"]
        self.assertEqual(url["service"], "stop_cover")

    def test_cmd_open_percentage(self):
        """open_percentage INTEGER must produce cover.set_cover_position."""
        entity = self._make_entity()
        result = entity.process_cmd({
            "states": [{"key": "open_percentage", "value": {"type": "INTEGER", "integer_value": 65}}]
        })
        self.assertEqual(len(result), 1)
        url = result[0]["url"]
        self.assertEqual(url["service"], "set_cover_position")
        self.assertEqual(url["service_data"]["position"], 65)

    def test_cmd_open_percentage_clamped_high(self):
        """Position > 100 must be clamped to 100."""
        entity = self._make_entity()
        result = entity.process_cmd({
            "states": [{"key": "open_percentage", "value": {"integer_value": 150}}]
        })
        self.assertEqual(result[0]["url"]["service_data"]["position"], 100)

    def test_cmd_open_percentage_clamped_low(self):
        """Position < 0 must be clamped to 0."""
        entity = self._make_entity()
        result = entity.process_cmd({
            "states": [{"key": "open_percentage", "value": {"integer_value": -10}}]
        })
        self.assertEqual(result[0]["url"]["service_data"]["position"], 0)


class TestWindowBlindNegative(unittest.TestCase):
    """Test edge cases and error handling for WindowBlindEntity."""

    def _make_entity(self, state="open", position=50):
        entity = WindowBlindEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(state=state, current_position=position))
        return entity

    def test_unknown_enum_value_ignored(self):
        """Unknown open_set enum value must produce no service calls."""
        entity = self._make_entity()
        result = entity.process_cmd({
            "states": [{"key": "open_set", "value": {"type": "ENUM", "enum_value": "tilt_up"}}]
        })
        self.assertEqual(len(result), 0)

    def test_empty_states_list(self):
        """Empty states list must produce no service calls."""
        entity = self._make_entity()
        result = entity.process_cmd({"states": []})
        self.assertEqual(result, [])

    def test_missing_key_in_state_item(self):
        """State item without 'key' must be skipped."""
        entity = self._make_entity()
        result = entity.process_cmd({
            "states": [{"value": {"integer_value": 50}}]
        })
        self.assertEqual(len(result), 0)

    def test_open_set_with_no_enum_value(self):
        """open_set with empty value dict must be skipped."""
        entity = self._make_entity()
        result = entity.process_cmd({
            "states": [{"key": "open_set", "value": {}}]
        })
        self.assertEqual(len(result), 0)

    def test_fill_position_none_defaults_by_state(self):
        """Position=None must use state-based default."""
        entity = WindowBlindEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(state="closed"))
        self.assertEqual(entity.current_position, 0)

    def test_fill_empty_attributes(self):
        """Empty attributes dict must not raise errors."""
        entity = WindowBlindEntity(ENTITY_DATA)
        entity.fill_by_ha_state({
            "entity_id": "cover.blind",
            "state": "open",
            "attributes": {},
        })
        # No position attr + HA state 'open' → defaults to 100 (fully open)
        self.assertEqual(entity.current_position, 100)

    def test_fill_invalid_position_string(self):
        """Non-numeric position must fall back to state-based default."""
        entity = WindowBlindEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(state="closed", current_position="bad"))
        self.assertEqual(entity.current_position, 0)


class TestWindowBlindProcessStateChange(unittest.TestCase):
    """Test process_state_change updates entity state."""

    def test_state_change_closed_to_open(self):
        """State change must update position and state."""
        entity = WindowBlindEntity(ENTITY_DATA)
        old = _make_ha_state(state="closed", current_position=0)
        new = _make_ha_state(state="open", current_position=100)
        entity.fill_by_ha_state(old)
        self.assertEqual(entity.current_position, 0)
        entity.process_state_change(old, new)
        self.assertEqual(entity.current_position, 100)
        self.assertEqual(entity.state, "open")

    def test_state_change_updates_tilt(self):
        """State change with tilt must update tilt value."""
        entity = WindowBlindEntity(ENTITY_DATA)
        old = _make_ha_state(state="open", current_position=50, current_tilt_position=0)
        new = _make_ha_state(state="open", current_position=50, current_tilt_position=90)
        entity.fill_by_ha_state(old)
        entity.process_state_change(old, new)
        result = entity.to_sber_current_state()
        states = result["cover.blind"]["states"]
        ltp = next(s for s in states if s["key"] == "light_transmission_percentage")
        self.assertEqual(ltp["value"]["integer_value"], "90")
