"""Tests for VacuumCleanerEntity -- Sber vacuum cleaner device mapping."""

import unittest

from custom_components.sber_mqtt_bridge.devices.vacuum_cleaner import VacuumCleanerEntity


ENTITY_DATA = {"entity_id": "vacuum.roborock", "name": "Roborock S7"}


def _make_ha_state(state="docked", **attrs):
    return {
        "entity_id": "vacuum.roborock",
        "state": state,
        "attributes": attrs,
    }


class TestVacuumCreate(unittest.TestCase):
    """Test VacuumCleanerEntity initialization."""

    def test_category(self):
        entity = VacuumCleanerEntity(ENTITY_DATA)
        self.assertEqual(entity.category, "vacuum_cleaner")

    def test_initial_state(self):
        entity = VacuumCleanerEntity(ENTITY_DATA)
        self.assertEqual(entity._status, "docked")

    def test_features_list_basic(self):
        entity = VacuumCleanerEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state())
        features = entity.create_features_list()
        self.assertIn("online", features)
        self.assertIn("vacuum_cleaner_command", features)
        self.assertIn("vacuum_cleaner_status", features)

    def test_features_list_with_fan_speed(self):
        entity = VacuumCleanerEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(fan_speed="standard", fan_speed_list=["quiet", "standard", "turbo"]))
        features = entity.create_features_list()
        self.assertIn("vacuum_cleaner_program", features)

    def test_features_list_with_battery(self):
        entity = VacuumCleanerEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(battery_level=80))
        features = entity.create_features_list()
        self.assertIn("battery_percentage", features)


class TestVacuumFillState(unittest.TestCase):
    """Test fill_by_ha_state."""

    def test_cleaning_status(self):
        entity = VacuumCleanerEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("cleaning"))
        self.assertEqual(entity._status, "cleaning")

    def test_returning_status(self):
        entity = VacuumCleanerEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("returning"))
        self.assertEqual(entity._status, "go_home")

    def test_unknown_state_defaults_standby(self):
        entity = VacuumCleanerEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("some_unknown"))
        self.assertEqual(entity._status, "standby")

    def test_battery_level(self):
        entity = VacuumCleanerEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(battery_level=65))
        self.assertEqual(entity._battery_level, 65)


class TestVacuumToSberCurrentState(unittest.TestCase):
    """Test to_sber_current_state."""

    def test_cleaning_with_battery(self):
        entity = VacuumCleanerEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("cleaning", battery_level=70, fan_speed="turbo"))
        result = entity.to_sber_current_state()
        states = result["vacuum.roborock"]["states"]
        status = next(s for s in states if s["key"] == "vacuum_cleaner_status")
        self.assertEqual(status["value"]["enum_value"], "cleaning")
        battery = next(s for s in states if s["key"] == "battery_percentage")
        self.assertEqual(battery["value"]["integer_value"], "70")
        program = next(s for s in states if s["key"] == "vacuum_cleaner_program")
        self.assertEqual(program["value"]["enum_value"], "turbo")

    def test_no_on_off_in_state(self):
        entity = VacuumCleanerEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state())
        result = entity.to_sber_current_state()
        states = result["vacuum.roborock"]["states"]
        keys = [s["key"] for s in states]
        self.assertNotIn("on_off", keys)

    def test_unavailable_offline(self):
        entity = VacuumCleanerEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("unavailable"))
        result = entity.to_sber_current_state()
        states = result["vacuum.roborock"]["states"]
        online = next(s for s in states if s["key"] == "online")
        self.assertFalse(online["value"]["bool_value"])


class TestVacuumProcessCmd(unittest.TestCase):
    """Test process_cmd."""

    def _make_entity(self, state="docked", **attrs):
        entity = VacuumCleanerEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(state, **attrs))
        return entity

    def test_cmd_start(self):
        entity = self._make_entity()
        result = entity.process_cmd(
            {"states": [{"key": "vacuum_cleaner_command", "value": {"type": "ENUM", "enum_value": "start"}}]}
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["url"]["service"], "start")
        self.assertEqual(result[0]["url"]["domain"], "vacuum")

    def test_cmd_stop(self):
        entity = self._make_entity("cleaning")
        result = entity.process_cmd(
            {"states": [{"key": "vacuum_cleaner_command", "value": {"type": "ENUM", "enum_value": "stop"}}]}
        )
        self.assertEqual(result[0]["url"]["service"], "stop")

    def test_cmd_pause(self):
        entity = self._make_entity("cleaning")
        result = entity.process_cmd(
            {"states": [{"key": "vacuum_cleaner_command", "value": {"type": "ENUM", "enum_value": "pause"}}]}
        )
        self.assertEqual(result[0]["url"]["service"], "pause")

    def test_cmd_return_to_dock(self):
        entity = self._make_entity("cleaning")
        result = entity.process_cmd(
            {"states": [{"key": "vacuum_cleaner_command", "value": {"type": "ENUM", "enum_value": "return_to_dock"}}]}
        )
        self.assertEqual(result[0]["url"]["service"], "return_to_base")

    def test_cmd_set_fan_speed(self):
        entity = self._make_entity("cleaning")
        result = entity.process_cmd(
            {"states": [{"key": "vacuum_cleaner_program", "value": {"type": "ENUM", "enum_value": "turbo"}}]}
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["url"]["service"], "set_fan_speed")
        self.assertEqual(result[0]["url"]["service_data"]["fan_speed"], "turbo")

    def test_cmd_unknown_command_ignored(self):
        entity = self._make_entity()
        result = entity.process_cmd(
            {"states": [{"key": "vacuum_cleaner_command", "value": {"type": "ENUM", "enum_value": "unknown"}}]}
        )
        self.assertEqual(len(result), 0)

    def test_cmd_empty_states(self):
        entity = self._make_entity()
        result = entity.process_cmd({"states": []})
        self.assertEqual(result, [])


class TestVacuumAllowedValues(unittest.TestCase):
    """Test allowed values in to_sber_state."""

    def test_allowed_values_commands(self):
        entity = VacuumCleanerEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(fan_speed_list=["quiet", "standard", "turbo"]))
        result = entity.to_sber_state()
        allowed = result["model"]["allowed_values"]
        self.assertIn("vacuum_cleaner_command", allowed)
        self.assertNotIn("vacuum_cleaner_status", allowed)  # read-only, not in allowed_values
        self.assertIn("vacuum_cleaner_program", allowed)
        self.assertEqual(allowed["vacuum_cleaner_program"]["enum_values"]["values"], ["quiet", "standard", "turbo"])
