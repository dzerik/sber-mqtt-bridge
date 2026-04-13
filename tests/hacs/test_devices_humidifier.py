"""Tests for HumidifierEntity — Sber humidifier device mapping."""

import unittest

from custom_components.sber_mqtt_bridge.devices.humidifier import HumidifierEntity


ENTITY_DATA = {"entity_id": "humidifier.room", "name": "Humidifier"}


def _make_ha_state(
    state="on",
    humidity=50,
    current_humidity=45,
    available_modes=None,
    mode="normal",
):
    if available_modes is None:
        available_modes = ["normal", "eco", "boost"]
    return {
        "entity_id": "humidifier.room",
        "state": state,
        "attributes": {
            "humidity": humidity,
            "current_humidity": current_humidity,
            "available_modes": available_modes,
            "mode": mode,
        },
    }


class TestHumidifierInit(unittest.TestCase):
    """Test HumidifierEntity initialization."""

    def test_init_defaults(self):
        entity = HumidifierEntity(ENTITY_DATA)
        self.assertEqual(entity.category, "hvac_humidifier")
        self.assertEqual(entity.entity_id, "humidifier.room")
        self.assertFalse(entity.current_state)
        self.assertIsNone(entity.target_humidity)
        self.assertIsNone(entity.current_humidity)
        self.assertEqual(entity.available_modes, [])
        self.assertIsNone(entity.mode)


class TestHumidifierFillByHaState(unittest.TestCase):
    """Test fill_by_ha_state parses humidifier attributes."""

    def test_fill_on(self):
        entity = HumidifierEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state())
        self.assertTrue(entity.current_state)
        self.assertEqual(entity.target_humidity, 50)
        self.assertEqual(entity.current_humidity, 45)
        self.assertEqual(entity.available_modes, ["normal", "eco", "boost"])
        self.assertEqual(entity.mode, "normal")

    def test_fill_off(self):
        entity = HumidifierEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(state="off"))
        self.assertFalse(entity.current_state)

    def test_fill_no_modes(self):
        entity = HumidifierEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(available_modes=[]))
        self.assertEqual(entity.available_modes, [])


class TestHumidifierCreateFeaturesList(unittest.TestCase):
    """Test create_features_list."""

    def test_with_modes(self):
        entity = HumidifierEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state())
        features = entity.get_final_features_list()
        self.assertIn("on_off", features)
        self.assertIn("humidity", features)
        self.assertIn("hvac_humidity_set", features)
        self.assertIn("hvac_air_flow_power", features)
        self.assertIn("online", features)

    def test_without_modes(self):
        entity = HumidifierEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(available_modes=[]))
        features = entity.get_final_features_list()
        self.assertIn("on_off", features)
        self.assertIn("humidity", features)
        self.assertIn("hvac_humidity_set", features)
        self.assertNotIn("hvac_air_flow_power", features)


class TestHumidifierCreateAllowedValues(unittest.TestCase):
    """Test create_allowed_values_list."""

    def test_with_modes(self):
        entity = HumidifierEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state())
        av = entity.create_allowed_values_list()
        self.assertIn("hvac_air_flow_power", av)
        self.assertEqual(av["hvac_air_flow_power"]["type"], "ENUM")
        self.assertEqual(
            av["hvac_air_flow_power"]["enum_values"]["values"],
            ["normal", "eco", "turbo"],
        )

    def test_without_modes(self):
        entity = HumidifierEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(available_modes=[]))
        av = entity.create_allowed_values_list()
        # Only hvac_humidity_set remains when no enum modes
        self.assertNotIn("hvac_air_flow_power", av)
        self.assertIn("hvac_humidity_set", av)


class TestHumidifierToSberCurrentState(unittest.TestCase):
    """Test to_sber_current_state."""

    def test_full_state(self):
        entity = HumidifierEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state())
        result = entity.to_sber_current_state()
        self.assertIn("humidifier.room", result)
        states = result["humidifier.room"]["states"]
        keys = [s["key"] for s in states]

        self.assertIn("online", keys)
        self.assertIn("on_off", keys)
        self.assertIn("humidity", keys)
        self.assertIn("hvac_air_flow_power", keys)

        online = next(s for s in states if s["key"] == "online")
        self.assertTrue(online["value"]["bool_value"])

        on_off = next(s for s in states if s["key"] == "on_off")
        self.assertTrue(on_off["value"]["bool_value"])

        hum = next(s for s in states if s["key"] == "humidity")
        self.assertEqual(hum["value"]["integer_value"], "45")  # current_humidity, not target

        hum_set = next(s for s in states if s["key"] == "hvac_humidity_set")
        self.assertEqual(hum_set["value"]["integer_value"], "50")  # target humidity

        mode = next(s for s in states if s["key"] == "hvac_air_flow_power")
        self.assertEqual(mode["value"]["enum_value"], "normal")

    def test_off_state(self):
        entity = HumidifierEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(state="off"))
        result = entity.to_sber_current_state()
        states = result["humidifier.room"]["states"]
        on_off = next(s for s in states if s["key"] == "on_off")
        self.assertFalse(on_off["value"]["bool_value"])

    def test_unavailable_offline(self):
        entity = HumidifierEntity(ENTITY_DATA)
        entity.fill_by_ha_state({
            "entity_id": "humidifier.room",
            "state": "unavailable",
            "attributes": {},
        })
        result = entity.to_sber_current_state()
        states = result["humidifier.room"]["states"]
        online = next(s for s in states if s["key"] == "online")
        self.assertFalse(online["value"]["bool_value"])

    def test_no_humidity(self):
        entity = HumidifierEntity(ENTITY_DATA)
        entity.fill_by_ha_state({
            "entity_id": "humidifier.room",
            "state": "on",
            "attributes": {},
        })
        result = entity.to_sber_current_state()
        states = result["humidifier.room"]["states"]
        keys = [s["key"] for s in states]
        self.assertNotIn("humidity", keys)

    def test_no_mode(self):
        entity = HumidifierEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(mode=None))
        result = entity.to_sber_current_state()
        states = result["humidifier.room"]["states"]
        keys = [s["key"] for s in states]
        self.assertNotIn("hvac_air_flow_power", keys)


class TestHumidifierProcessCmd(unittest.TestCase):
    """Test process_cmd dispatches HA service calls."""

    def _make_entity(self):
        entity = HumidifierEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state())
        return entity

    def test_cmd_on_off_turn_on(self):
        entity = self._make_entity()
        result = entity.process_cmd({
            "states": [{"key": "on_off", "value": {"bool_value": True}}]
        })
        url = result[0]["url"]
        self.assertEqual(url["domain"], "humidifier")
        self.assertEqual(url["service"], "turn_on")

    def test_cmd_on_off_turn_off(self):
        entity = self._make_entity()
        result = entity.process_cmd({
            "states": [{"key": "on_off", "value": {"bool_value": False}}]
        })
        url = result[0]["url"]
        self.assertEqual(url["service"], "turn_off")

    def test_cmd_humidity(self):
        entity = self._make_entity()
        result = entity.process_cmd({
            "states": [{"key": "humidity", "value": {"integer_value": 60}}]
        })
        url = result[0]["url"]
        self.assertEqual(url["service"], "set_humidity")
        self.assertEqual(url["service_data"]["humidity"], 60)  # plain percentage

    def test_cmd_mode(self):
        entity = self._make_entity()
        result = entity.process_cmd({
            "states": [{"key": "hvac_air_flow_power", "value": {"enum_value": "eco"}}]
        })
        url = result[0]["url"]
        self.assertEqual(url["service"], "set_mode")
        self.assertEqual(url["service_data"]["mode"], "eco")

    def test_cmd_empty_states(self):
        entity = self._make_entity()
        result = entity.process_cmd({"states": []})
        self.assertEqual(result, [])

    def test_cmd_multiple(self):
        entity = self._make_entity()
        result = entity.process_cmd({
            "states": [
                {"key": "on_off", "value": {"bool_value": True}},
                {"key": "humidity", "value": {"integer_value": 700}},
                {"key": "hvac_air_flow_power", "value": {"enum_value": "boost"}},
            ]
        })
        self.assertEqual(len(result), 3)


class TestHumidifierUpdateLinkedData(unittest.TestCase):
    """Test update_linked_data for linked humidity sensor."""

    def test_humidity_role_updates_current_humidity(self):
        """Linked humidity sensor should update current_humidity."""
        entity = HumidifierEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(current_humidity=None))
        self.assertIsNone(entity.current_humidity)
        entity.update_linked_data("humidity", {"state": "55.3"})
        self.assertAlmostEqual(entity.current_humidity, 55.3)

    def test_humidity_role_overrides_native(self):
        """Linked sensor value should override native current_humidity."""
        entity = HumidifierEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(current_humidity=40))
        self.assertEqual(entity.current_humidity, 40)
        entity.update_linked_data("humidity", {"state": "62"})
        self.assertAlmostEqual(entity.current_humidity, 62.0)

    def test_humidity_role_ignores_unavailable(self):
        """Unavailable/unknown states should not change current_humidity."""
        entity = HumidifierEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(current_humidity=40))
        for bad_state in ("unknown", "unavailable", None):
            entity.update_linked_data("humidity", {"state": bad_state})
            self.assertEqual(entity.current_humidity, 40)

    def test_humidity_role_ignores_invalid(self):
        """Non-numeric state should not change current_humidity."""
        entity = HumidifierEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(current_humidity=40))
        entity.update_linked_data("humidity", {"state": "not_a_number"})
        self.assertEqual(entity.current_humidity, 40)

    def test_unrelated_role_ignored(self):
        """Roles other than 'humidity' should be silently ignored."""
        entity = HumidifierEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(current_humidity=40))
        entity.update_linked_data("temperature", {"state": "25"})
        self.assertEqual(entity.current_humidity, 40)


class TestHumidifierChildLock(unittest.TestCase):
    """Test child_lock feature in HumidifierEntity."""

    def test_child_lock_feature_present(self):
        """Humidifier with child_lock=True must include child_lock in features."""
        entity = HumidifierEntity(ENTITY_DATA)
        ha = _make_ha_state()
        ha["attributes"]["child_lock"] = True
        entity.fill_by_ha_state(ha)
        features = entity.get_final_features_list()
        self.assertIn("child_lock", features)

    def test_child_lock_feature_present_when_false(self):
        """Humidifier with child_lock=False must still include child_lock in features."""
        entity = HumidifierEntity(ENTITY_DATA)
        ha = _make_ha_state()
        ha["attributes"]["child_lock"] = False
        entity.fill_by_ha_state(ha)
        features = entity.get_final_features_list()
        self.assertIn("child_lock", features)

    def test_child_lock_feature_absent(self):
        """Humidifier without child_lock attribute must not include it."""
        entity = HumidifierEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state())
        features = entity.get_final_features_list()
        self.assertNotIn("child_lock", features)

    def test_child_lock_true_in_state(self):
        """child_lock=True must produce child_lock=True in Sber state."""
        entity = HumidifierEntity(ENTITY_DATA)
        ha = _make_ha_state()
        ha["attributes"]["child_lock"] = True
        entity.fill_by_ha_state(ha)
        result = entity.to_sber_current_state()
        states = result["humidifier.room"]["states"]
        cl = next(s for s in states if s["key"] == "child_lock")
        self.assertTrue(cl["value"]["bool_value"])

    def test_child_lock_false_in_state(self):
        """child_lock=False must produce child_lock=False in Sber state."""
        entity = HumidifierEntity(ENTITY_DATA)
        ha = _make_ha_state()
        ha["attributes"]["child_lock"] = False
        entity.fill_by_ha_state(ha)
        result = entity.to_sber_current_state()
        states = result["humidifier.room"]["states"]
        cl = next(s for s in states if s["key"] == "child_lock")
        self.assertFalse(cl["value"]["bool_value"])

    def test_child_lock_not_in_state_when_absent(self):
        """Without child_lock attribute, it must not appear in Sber state."""
        entity = HumidifierEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state())
        result = entity.to_sber_current_state()
        states = result["humidifier.room"]["states"]
        keys = [s["key"] for s in states]
        self.assertNotIn("child_lock", keys)


class TestHumidifierProcessStateChange(unittest.TestCase):
    """Test process_state_change."""

    def test_state_change(self):
        entity = HumidifierEntity(ENTITY_DATA)
        old = _make_ha_state(state="off")
        new = _make_ha_state(state="on", humidity=60)
        entity.fill_by_ha_state(old)
        self.assertFalse(entity.current_state)
        entity.process_state_change(old, new)
        self.assertTrue(entity.current_state)
        self.assertEqual(entity.target_humidity, 60)
