"""Tests for LightEntity — Sber light device mapping."""

import unittest

from custom_components.sber_mqtt_bridge.devices.light import LightEntity


def _make_ha_state(
    state="on",
    brightness=200,
    color_temp=300,
    min_mireds=153,
    max_mireds=500,
    supported_color_modes=None,
    color_mode="color_temp",
    hs_color=None,
    rgb_color=None,
    xy_color=None,
    supported_features=0,
):
    """Build a mock HA state dict for light.room."""
    if supported_color_modes is None:
        supported_color_modes = ["color_temp", "xy"]
    return {
        "entity_id": "light.room",
        "state": state,
        "attributes": {
            "brightness": brightness,
            "color_temp": color_temp,
            "min_mireds": min_mireds,
            "max_mireds": max_mireds,
            "supported_color_modes": supported_color_modes,
            "color_mode": color_mode,
            "supported_features": supported_features,
            "hs_color": hs_color if hs_color is not None else [30, 80],
            "rgb_color": rgb_color if rgb_color is not None else [255, 200, 50],
            "xy_color": xy_color if xy_color is not None else [0.5, 0.3],
        },
    }


ENTITY_DATA = {"entity_id": "light.room", "name": "Room Light"}


class TestLightEntityInit(unittest.TestCase):
    """Test LightEntity initialization."""

    def test_init_defaults(self):
        """Entity initializes with correct category and defaults."""
        entity = LightEntity(ENTITY_DATA)
        self.assertEqual(entity.category, "light")
        self.assertEqual(entity.entity_id, "light.room")
        self.assertEqual(entity.name, "Room Light")
        self.assertFalse(entity.current_state)
        self.assertEqual(entity.current_sber_brightness, 0)
        self.assertEqual(entity.supported_color_modes, [])


class TestLightFillByHaState(unittest.TestCase):
    """Test fill_by_ha_state parses HA attributes correctly."""

    def test_fill_basic_attributes(self):
        """Brightness, color temp, mireds, and color mode are parsed."""
        entity = LightEntity(ENTITY_DATA)
        ha_state = _make_ha_state()
        entity.fill_by_ha_state(ha_state)

        self.assertTrue(entity.current_state)
        self.assertEqual(entity.min_mireds, 153)
        self.assertEqual(entity.max_mireds, 500)
        self.assertEqual(entity.current_color_mode, "color_temp")
        self.assertEqual(entity.supported_color_modes, ["color_temp", "xy"])
        self.assertIsNotNone(entity.current_sber_brightness)
        self.assertIsNotNone(entity.current_sber_color_temp)

    def test_fill_off_state(self):
        """State 'off' sets current_state to False."""
        entity = LightEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(state="off"))
        self.assertFalse(entity.current_state)

    def test_fill_none_brightness(self):
        """None brightness is treated as 0."""
        entity = LightEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(brightness=None))
        # brightness=0 => sber_brightness should be min (100)
        self.assertEqual(entity.current_sber_brightness, 100)

    def test_fill_none_color_temp(self):
        """None color_temp sets sber_color_temp to None."""
        entity = LightEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(color_temp=None))
        self.assertIsNone(entity.current_sber_color_temp)

    def test_fill_xy_color(self):
        """xy_color attribute is stored."""
        entity = LightEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(xy_color=[0.4, 0.5]))
        self.assertEqual(entity.xy_color, [0.4, 0.5])

    def test_fill_updates_mireds_limits(self):
        """color_temp_converter limits are updated from mireds."""
        entity = LightEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(min_mireds=100, max_mireds=400))
        self.assertEqual(entity.color_temp_converter.ha_side_min, 100)
        self.assertEqual(entity.color_temp_converter.ha_side_max, 400)


class TestLightCreateFeaturesList(unittest.TestCase):
    """Test create_features_list returns correct features based on color modes."""

    def test_features_xy_and_color_temp(self):
        """Both xy and color_temp modes produce full feature list."""
        entity = LightEntity(ENTITY_DATA)
        entity.fill_by_ha_state(
            _make_ha_state(supported_color_modes=["color_temp", "xy"])
        )
        features = entity.create_features_list()
        self.assertIn("on_off", features)
        self.assertIn("light_colour", features)
        self.assertIn("light_mode", features)
        self.assertIn("light_brightness", features)
        self.assertIn("light_colour_temp", features)
        self.assertIn("online", features)

    def test_features_only_color_temp(self):
        """Only color_temp mode omits xy-related features."""
        entity = LightEntity(ENTITY_DATA)
        entity.fill_by_ha_state(
            _make_ha_state(supported_color_modes=["color_temp"])
        )
        features = entity.create_features_list()
        self.assertIn("on_off", features)
        self.assertIn("light_colour_temp", features)
        self.assertNotIn("light_colour", features)
        self.assertNotIn("light_mode", features)

    def test_features_only_xy(self):
        """Only xy mode omits color_temp feature."""
        entity = LightEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(supported_color_modes=["xy"]))
        features = entity.create_features_list()
        self.assertIn("light_colour", features)
        self.assertNotIn("light_colour_temp", features)

    def test_features_no_modes(self):
        """No color modes means only on_off and online."""
        entity = LightEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(supported_color_modes=[]))
        features = entity.create_features_list()
        self.assertIn("on_off", features)
        self.assertNotIn("light_colour", features)
        self.assertNotIn("light_colour_temp", features)


class TestLightToSberCurrentState(unittest.TestCase):
    """Test to_sber_current_state builds correct Sber state payload."""

    def test_on_state_color_temp_mode(self):
        """On state in color_temp mode includes on_off, brightness, light_colour_temp, light_mode=white."""
        entity = LightEntity(ENTITY_DATA)
        entity.fill_by_ha_state(
            _make_ha_state(state="on", color_mode="color_temp", brightness=200, color_temp=300)
        )
        result = entity.to_sber_current_state()
        self.assertIn("light.room", result)
        states = result["light.room"]["states"]
        keys = [s["key"] for s in states]

        self.assertIn("on_off", keys)
        on_off = next(s for s in states if s["key"] == "on_off")
        self.assertTrue(on_off["value"]["bool_value"])

        self.assertIn("light_brightness", keys)
        self.assertIn("light_colour_temp", keys)
        self.assertIn("light_mode", keys)
        mode = next(s for s in states if s["key"] == "light_mode")
        self.assertEqual(mode["value"]["enum_value"], "white")

    def test_on_state_xy_mode(self):
        """On state in xy mode includes light_colour and light_mode=colour."""
        entity = LightEntity(ENTITY_DATA)
        entity.fill_by_ha_state(
            _make_ha_state(state="on", color_mode="xy", hs_color=[30, 80], brightness=200)
        )
        result = entity.to_sber_current_state()
        states = result["light.room"]["states"]
        keys = [s["key"] for s in states]

        self.assertIn("light_colour", keys)
        colour = next(s for s in states if s["key"] == "light_colour")
        self.assertIn("h", colour["value"]["colour_value"])
        self.assertIn("s", colour["value"]["colour_value"])
        self.assertIn("v", colour["value"]["colour_value"])

        mode = next(s for s in states if s["key"] == "light_mode")
        self.assertEqual(mode["value"]["enum_value"], "colour")

    def test_off_state(self):
        """Off state only includes on_off=false and brightness (no color/mode states)."""
        entity = LightEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(state="off", brightness=100))
        result = entity.to_sber_current_state()
        states = result["light.room"]["states"]
        keys = [s["key"] for s in states]

        on_off = next(s for s in states if s["key"] == "on_off")
        self.assertFalse(on_off["value"]["bool_value"])
        # Off state should not include light_mode or light_colour
        self.assertNotIn("light_mode", keys)
        self.assertNotIn("light_colour", keys)

    def test_zero_sber_brightness_excluded(self):
        """Zero sber brightness is excluded from states (requires converter output=0)."""
        entity = LightEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(state="off", brightness=0))
        # brightness=0 maps to sber 50 via converter (min), so it IS included.
        # Force sber brightness to 0 to test the exclusion branch.
        entity.current_sber_brightness = 0
        result = entity.to_sber_current_state()
        states = result["light.room"]["states"]
        keys = [s["key"] for s in states]
        self.assertNotIn("light_brightness", keys)

    def test_min_brightness_included(self):
        """HA brightness=0 maps to sber min (50), which is included."""
        entity = LightEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(state="off", brightness=0))
        result = entity.to_sber_current_state()
        states = result["light.room"]["states"]
        keys = [s["key"] for s in states]
        self.assertIn("light_brightness", keys)


class TestLightProcessCmd(unittest.TestCase):
    """Test process_cmd dispatches HA service calls correctly."""

    def _make_entity(self, state="on", brightness=200):
        entity = LightEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(state=state, brightness=brightness))
        return entity

    def test_cmd_on_off_turn_on(self):
        """on_off=True generates light.turn_on service call."""
        entity = self._make_entity(state="off")
        result = entity.process_cmd({
            "states": [{"key": "on_off", "value": {"type": "BOOL", "bool_value": True}}]
        })
        self.assertEqual(len(result), 1)
        url = result[0]["url"]
        self.assertEqual(url["domain"], "light")
        self.assertEqual(url["service"], "turn_on")
        self.assertEqual(url["target"]["entity_id"], "light.room")

    def test_cmd_on_off_turn_off(self):
        """on_off=False generates light.turn_off service call."""
        entity = self._make_entity()
        result = entity.process_cmd({
            "states": [{"key": "on_off", "value": {"type": "BOOL", "bool_value": False}}]
        })
        url = result[0]["url"]
        self.assertEqual(url["service"], "turn_off")

    def test_cmd_brightness_when_on(self):
        """light_brightness while on generates turn_on with brightness."""
        entity = self._make_entity(state="on")
        result = entity.process_cmd({
            "states": [{"key": "light_brightness", "value": {"type": "INTEGER", "integer_value": 500}}]
        })
        self.assertEqual(len(result), 1)
        url = result[0]["url"]
        self.assertEqual(url["service"], "turn_on")
        self.assertIn("brightness", url["service_data"])
        br = url["service_data"]["brightness"]
        self.assertGreaterEqual(br, 50)
        self.assertLessEqual(br, 255)

    def test_cmd_brightness_when_off_still_sends(self):
        """light_brightness while off still generates service call (state not gated)."""
        entity = self._make_entity(state="off")
        result = entity.process_cmd({
            "states": [{"key": "light_brightness", "value": {"type": "INTEGER", "integer_value": 500}}]
        })
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["url"]["service"], "turn_on")

    def test_cmd_light_colour_when_on(self):
        """light_colour with HSV generates turn_on with hs_color."""
        entity = self._make_entity(state="on")
        result = entity.process_cmd({
            "states": [{
                "key": "light_colour",
                "value": {
                    "type": "COLOUR",
                    "colour_value": {"h": 120, "s": 500, "v": 500}
                }
            }]
        })
        self.assertEqual(len(result), 1)
        url = result[0]["url"]
        self.assertEqual(url["service"], "turn_on")
        self.assertIn("hs_color", url["service_data"])
        self.assertIn("brightness", url["service_data"])

    def test_cmd_light_colour_when_off_still_sends(self):
        """light_colour while off still generates service call (state not gated)."""
        entity = self._make_entity(state="off")
        result = entity.process_cmd({
            "states": [{
                "key": "light_colour",
                "value": {"type": "COLOUR", "colour_value": {"h": 120, "s": 500, "v": 500}}
            }]
        })
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["url"]["service"], "turn_on")

    def test_cmd_light_colour_none_value(self):
        """light_colour with no colour_value uses default."""
        entity = self._make_entity(state="on")
        result = entity.process_cmd({
            "states": [{"key": "light_colour", "value": {"type": "COLOUR"}}]
        })
        self.assertEqual(len(result), 1)

    def test_cmd_light_mode_colour_no_hs(self):
        """light_mode=colour without hs_color returns update_state fallback."""
        entity = self._make_entity()
        entity.hs_color = None  # Clear hs_color to test fallback
        result = entity.process_cmd({
            "states": [{"key": "light_mode", "value": {"type": "ENUM", "enum_value": "colour"}}]
        })
        self.assertEqual(len(result), 1)
        self.assertIn("update_state", result[0])
        self.assertEqual(entity.current_color_mode, "hs")

    def test_cmd_light_mode_colour_with_hs(self):
        """light_mode=colour with hs_color sends turn_on with hs_color."""
        entity = self._make_entity()
        entity.hs_color = [120.0, 80.0]
        result = entity.process_cmd({
            "states": [{"key": "light_mode", "value": {"type": "ENUM", "enum_value": "colour"}}]
        })
        self.assertEqual(len(result), 1)
        url = result[0]["url"]
        self.assertEqual(url["service"], "turn_on")
        self.assertEqual(url["service_data"]["hs_color"], [120.0, 80.0])
        self.assertEqual(entity.current_color_mode, "hs")

    def test_cmd_light_mode_white(self):
        """light_mode=white sends turn_on with color_temp to switch HA mode."""
        entity = self._make_entity()
        result = entity.process_cmd({
            "states": [{"key": "light_mode", "value": {"type": "ENUM", "enum_value": "white"}}]
        })
        self.assertEqual(entity.current_color_mode, "color_temp")
        url = result[0]["url"]
        self.assertEqual(url["service"], "turn_on")
        self.assertIn("color_temp", url["service_data"])

    def test_cmd_light_colour_temp_when_on(self):
        """light_colour_temp generates turn_on with color_temp."""
        entity = self._make_entity(state="on")
        result = entity.process_cmd({
            "states": [{"key": "light_colour_temp", "value": {"type": "INTEGER", "integer_value": 500}}]
        })
        self.assertEqual(len(result), 1)
        url = result[0]["url"]
        self.assertEqual(url["service"], "turn_on")
        self.assertIn("color_temp", url["service_data"])

    def test_cmd_light_colour_temp_when_off_still_sends(self):
        """light_colour_temp while off still generates service call (state not gated)."""
        entity = self._make_entity(state="off")
        result = entity.process_cmd({
            "states": [{"key": "light_colour_temp", "value": {"type": "INTEGER", "integer_value": 500}}]
        })
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["url"]["service"], "turn_on")

    def test_cmd_none_data(self):
        """None cmd_data returns empty list."""
        entity = self._make_entity()
        result = entity.process_cmd(None)
        self.assertEqual(result, [])

    def test_cmd_empty_states(self):
        """Empty states list returns empty result."""
        entity = self._make_entity()
        result = entity.process_cmd({"states": []})
        self.assertEqual(result, [])

    def test_cmd_multiple_commands(self):
        """Multiple commands in one payload are all processed."""
        entity = self._make_entity(state="on")
        result = entity.process_cmd({
            "states": [
                {"key": "on_off", "value": {"type": "BOOL", "bool_value": True}},
                {"key": "light_brightness", "value": {"type": "INTEGER", "integer_value": 700}},
            ]
        })
        self.assertEqual(len(result), 2)


class TestLightProcessStateChange(unittest.TestCase):
    """Test process_state_change updates internal state."""

    def test_state_change_updates(self):
        """process_state_change calls fill_by_ha_state with new state."""
        entity = LightEntity(ENTITY_DATA)
        old = _make_ha_state(state="off")
        new = _make_ha_state(state="on", brightness=255)
        entity.fill_by_ha_state(old)
        self.assertFalse(entity.current_state)
        entity.process_state_change(old, new)
        self.assertTrue(entity.current_state)


class TestLightAllowedValues(unittest.TestCase):
    """Test create_allowed_values_list."""

    def test_allowed_values_xy_and_color_temp(self):
        """Both modes produce brightness, colour, mode, and colour_temp."""
        entity = LightEntity(ENTITY_DATA)
        entity.fill_by_ha_state(
            _make_ha_state(supported_color_modes=["color_temp", "xy"])
        )
        av = entity.create_allowed_values_list()
        self.assertIn("light_brightness", av)
        self.assertIn("light_colour", av)
        self.assertIn("light_mode", av)
        self.assertIn("light_colour_temp", av)
        self.assertEqual(av["light_brightness"]["type"], "INTEGER")
        self.assertEqual(av["light_colour"]["type"], "COLOUR")
        self.assertEqual(av["light_mode"]["type"], "ENUM")

    def test_allowed_values_empty_modes(self):
        """No color modes produce empty allowed values."""
        entity = LightEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(supported_color_modes=[]))
        av = entity.create_allowed_values_list()
        self.assertEqual(av, {})
