"""Tests for GateEntity -- Sber gate device mapping (inherits CurtainEntity)."""

import unittest

from custom_components.sber_mqtt_bridge.devices.gate import GateEntity


ENTITY_DATA = {"entity_id": "cover.gate", "name": "Garage Gate"}


def _make_ha_state(state="open", current_position=None, **extra_attrs):
    """Build a minimal HA state dict for cover.gate.

    Args:
        state: HA cover state (open, closed, opening, closing, unavailable).
        current_position: Cover position 0-100, or None to omit.
        **extra_attrs: Additional attributes to include.

    Returns:
        HA state dict suitable for fill_by_ha_state.
    """
    attrs = {}
    if current_position is not None:
        attrs["current_position"] = current_position
    attrs.update(extra_attrs)
    return {
        "entity_id": "cover.gate",
        "state": state,
        "attributes": attrs,
    }


class TestGateInit(unittest.TestCase):
    """Test GateEntity initialization and category assignment."""

    def test_category_is_gate(self):
        """GateEntity must use Sber 'gate' category."""
        entity = GateEntity(ENTITY_DATA)
        self.assertEqual(entity.category, "gate")

    def test_entity_id(self):
        """entity_id must match the provided entity data."""
        entity = GateEntity(ENTITY_DATA)
        self.assertEqual(entity.entity_id, "cover.gate")

    def test_default_position_is_zero(self):
        """Initial position must be 0 before any state fill."""
        entity = GateEntity(ENTITY_DATA)
        self.assertEqual(entity.current_position, 0)

    def test_inherits_curtain(self):
        """GateEntity must be a subclass of CurtainEntity."""
        from custom_components.sber_mqtt_bridge.devices.curtain import CurtainEntity

        entity = GateEntity(ENTITY_DATA)
        self.assertIsInstance(entity, CurtainEntity)


class TestGateFillByHaState(unittest.TestCase):
    """Test fill_by_ha_state parses gate cover attributes."""

    def test_fill_state_open_with_position(self):
        """State 'open' with position=80 must set both fields."""
        entity = GateEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(state="open", current_position=80))
        self.assertEqual(entity.state, "open")
        self.assertEqual(entity.current_position, 80)

    def test_fill_state_closed_with_position_zero(self):
        """State 'closed' with position=0."""
        entity = GateEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(state="closed", current_position=0))
        self.assertEqual(entity.state, "closed")
        self.assertEqual(entity.current_position, 0)

    def test_fill_no_position_open_defaults_100(self):
        """No position attribute + HA state 'open' must default to 100.

        HA cover uses 'open' (not 'opened') as the state value.
        """
        entity = GateEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(state="open"))
        self.assertEqual(entity.current_position, 100)

    def test_fill_no_position_closed_defaults_0(self):
        """No position attribute + state 'closed' defaults to 0."""
        entity = GateEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(state="closed"))
        self.assertEqual(entity.current_position, 0)

    def test_fill_opening_state(self):
        """Transitional 'opening' state is preserved."""
        entity = GateEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(state="opening", current_position=50))
        self.assertEqual(entity.state, "opening")
        self.assertEqual(entity.current_position, 50)

    def test_fill_closing_state(self):
        """Transitional 'closing' state is preserved."""
        entity = GateEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(state="closing", current_position=30))
        self.assertEqual(entity.state, "closing")


class TestGateCreateFeaturesList(unittest.TestCase):
    """Test create_features_list returns correct Sber features."""

    def test_minimal_features(self):
        """Gate must have core cover features: online, open_set, open_state, open_percentage.

        Although the Sber gate example model omits open_percentage, it is a valid
        optional feature that can be added to any cover category. Since HA cover
        entities report current_position, we include it so Sber can send
        percentage-based commands.
        """
        entity = GateEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(state="open", current_position=50))
        features = entity.get_final_features_list()
        self.assertIn("online", features)
        self.assertIn("open_set", features)
        self.assertIn("open_state", features)
        self.assertIn("open_percentage", features)

    def test_signal_strength_feature_when_rssi_present(self):
        """signal_strength feature appears when rssi attribute is set."""
        entity = GateEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(
            state="open", current_position=50, signal_strength=-60,
        ))
        features = entity.get_final_features_list()
        self.assertIn("signal_strength", features)

    def test_no_signal_strength_without_rssi(self):
        """signal_strength feature must not appear without rssi data."""
        entity = GateEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(state="open", current_position=50))
        features = entity.get_final_features_list()
        self.assertNotIn("signal_strength", features)


class TestGateToSberState(unittest.TestCase):
    """Test to_sber_state produces correct Sber config JSON."""

    def test_config_category_is_gate(self):
        """Sber config must report model.category='gate'."""
        entity = GateEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(state="open", current_position=50))
        result = entity.to_sber_state()
        self.assertEqual(result["model"]["category"], "gate")

    def test_config_has_allowed_values(self):
        """Sber config must include allowed_values for open_set."""
        entity = GateEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(state="open", current_position=50))
        result = entity.to_sber_state()
        allowed = result["model"]["allowed_values"]
        self.assertIn("open_set", allowed)
        enum_vals = allowed["open_set"]["enum_values"]["values"]
        self.assertIn("open", enum_vals)
        self.assertIn("close", enum_vals)
        self.assertIn("stop", enum_vals)


class TestGateToSberCurrentState(unittest.TestCase):
    """Test to_sber_current_state produces correct Sber state payload."""

    def test_open_state_online(self):
        """Open gate must report online=True, open_state=open."""
        entity = GateEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(state="open", current_position=100))
        result = entity.to_sber_current_state()
        self.assertIn("cover.gate", result)
        states = result["cover.gate"]["states"]

        online = next(s for s in states if s["key"] == "online")
        self.assertTrue(online["value"]["bool_value"])

        open_state = next(s for s in states if s["key"] == "open_state")
        self.assertEqual(open_state["value"]["enum_value"], "open")

    def test_closed_state(self):
        """Closed gate must report open_state=close."""
        entity = GateEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(state="closed", current_position=0))
        result = entity.to_sber_current_state()
        states = result["cover.gate"]["states"]
        open_state = next(s for s in states if s["key"] == "open_state")
        self.assertEqual(open_state["value"]["enum_value"], "close")

    def test_position_as_integer_string(self):
        """open_percentage integer_value must be a string per Sber C2C spec."""
        entity = GateEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(state="open", current_position=50))
        result = entity.to_sber_current_state()
        states = result["cover.gate"]["states"]
        pos = next(s for s in states if s["key"] == "open_percentage")
        self.assertEqual(pos["value"]["integer_value"], "50")

    def test_opening_transitional_state(self):
        """Transitional 'opening' must produce open_state=opening."""
        entity = GateEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(state="opening", current_position=40))
        result = entity.to_sber_current_state()
        states = result["cover.gate"]["states"]
        open_state = next(s for s in states if s["key"] == "open_state")
        self.assertEqual(open_state["value"]["enum_value"], "opening")

    def test_closing_transitional_state(self):
        """Transitional 'closing' must produce open_state=closing."""
        entity = GateEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(state="closing", current_position=60))
        result = entity.to_sber_current_state()
        states = result["cover.gate"]["states"]
        open_state = next(s for s in states if s["key"] == "open_state")
        self.assertEqual(open_state["value"]["enum_value"], "closing")

    def test_unavailable_returns_offline(self):
        """Unavailable gate must report online=False only."""
        entity = GateEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(state="unavailable"))
        result = entity.to_sber_current_state()
        states = result["cover.gate"]["states"]
        online = next(s for s in states if s["key"] == "online")
        self.assertFalse(online["value"]["bool_value"])


class TestGateProcessCmd(unittest.TestCase):
    """Test process_cmd dispatches correct HA cover service calls."""

    def _make_entity(self, state="open", position=50):
        entity = GateEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(state=state, current_position=position))
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
        self.assertEqual(url["target"]["entity_id"], "cover.gate")

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
            "states": [{"key": "open_percentage", "value": {"type": "INTEGER", "integer_value": 75}}]
        })
        self.assertEqual(len(result), 1)
        url = result[0]["url"]
        self.assertEqual(url["service"], "set_cover_position")
        self.assertEqual(url["service_data"]["position"], 75)

    def test_cmd_open_percentage_clamped_high(self):
        """Position > 100 must be clamped to 100."""
        entity = self._make_entity()
        result = entity.process_cmd({
            "states": [{"key": "open_percentage", "value": {"integer_value": 200}}]
        })
        self.assertEqual(result[0]["url"]["service_data"]["position"], 100)

    def test_cmd_open_percentage_clamped_low(self):
        """Position < 0 must be clamped to 0."""
        entity = self._make_entity()
        result = entity.process_cmd({
            "states": [{"key": "open_percentage", "value": {"integer_value": -5}}]
        })
        self.assertEqual(result[0]["url"]["service_data"]["position"], 0)


class TestGateNegative(unittest.TestCase):
    """Test edge cases and error handling for GateEntity."""

    def _make_entity(self, state="open", position=50):
        entity = GateEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(state=state, current_position=position))
        return entity

    def test_unknown_enum_value_ignored(self):
        """Unknown open_set enum value must produce no service calls."""
        entity = self._make_entity()
        result = entity.process_cmd({
            "states": [{"key": "open_set", "value": {"type": "ENUM", "enum_value": "unknown"}}]
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

    def test_fill_with_invalid_position_string(self):
        """Non-numeric position must fall back to state-based default.

        HA state 'open' → position defaults to 100 (fully open).
        """
        entity = GateEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(state="open", current_position="abc"))
        self.assertEqual(entity.current_position, 100)

    def test_fill_empty_attributes(self):
        """Empty attributes dict must not raise errors."""
        entity = GateEntity(ENTITY_DATA)
        entity.fill_by_ha_state({
            "entity_id": "cover.gate",
            "state": "closed",
            "attributes": {},
        })
        self.assertEqual(entity.current_position, 0)
        self.assertEqual(entity.state, "closed")


class TestGateProcessStateChange(unittest.TestCase):
    """Test process_state_change updates entity state."""

    def test_state_change_closed_to_open(self):
        """State change must update position and state."""
        entity = GateEntity(ENTITY_DATA)
        old = _make_ha_state(state="closed", current_position=0)
        new = _make_ha_state(state="open", current_position=100)
        entity.fill_by_ha_state(old)
        self.assertEqual(entity.current_position, 0)
        entity.process_state_change(old, new)
        self.assertEqual(entity.current_position, 100)
        self.assertEqual(entity.state, "open")
