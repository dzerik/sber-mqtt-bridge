"""Tests for VacuumCleanerEntity -- Sber vacuum cleaner device mapping."""

import unittest

from custom_components.sber_mqtt_bridge.devices.base_entity import ROLE_BATTERY
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
        features = entity.get_final_features_list()
        self.assertIn("online", features)
        self.assertIn("vacuum_cleaner_command", features)
        self.assertIn("vacuum_cleaner_status", features)

    def test_features_list_with_mappable_modes(self):
        """``vacuum_cleaner_program`` appears only for modes Sber documents.

        Sber's vocabulary is ``perimeter, spot, smart, random_route``;
        HA suction names ("quiet"/"turbo") denote none of them, so the
        list here is one the cloud can actually route.
        """
        entity = VacuumCleanerEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(fan_speed="Spot", fan_speed_list=["Spot", "Smart"]))
        features = entity.get_final_features_list()
        self.assertIn("vacuum_cleaner_program", features)

    def test_features_list_with_battery(self):
        entity = VacuumCleanerEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(battery_level=80))
        features = entity.get_final_features_list()
        self.assertIn("battery_percentage", features)


class TestVacuumFillState(unittest.TestCase):
    """Test fill_by_ha_state."""

    def test_cleaning_status(self):
        entity = VacuumCleanerEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("cleaning"))
        self.assertEqual(entity._status, "cleaning")

    def test_returning_status(self):
        """HA ``returning`` is Sber ``returning_to_dock``.

        ``go_home`` was asserted here before and is not a value the
        ``vacuum_cleaner_status`` page documents at all.
        """
        entity = VacuumCleanerEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("returning"))
        self.assertEqual(entity._status, "returning_to_dock")

    def test_unknown_state_defaults_docked(self):
        """An uninterpretable HA state degrades to the resting value."""
        entity = VacuumCleanerEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("some_unknown"))
        self.assertEqual(entity._status, "docked")

    def test_battery_level(self):
        entity = VacuumCleanerEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(battery_level=65))
        self.assertEqual(entity._battery_level, 65)


class TestVacuumToSberCurrentState(unittest.TestCase):
    """Test to_sber_current_state."""

    def test_cleaning_with_battery(self):
        entity = VacuumCleanerEntity(ENTITY_DATA)
        entity.fill_by_ha_state(
            _make_ha_state(
                "cleaning",
                battery_level=70,
                fan_speed="Spot",
                fan_speed_list=["Spot", "Smart"],
            )
        )
        result = entity.to_sber_current_state()
        states = result["vacuum.roborock"]["states"]
        status = next(s for s in states if s["key"] == "vacuum_cleaner_status")
        self.assertEqual(status["value"]["enum_value"], "cleaning")
        battery = next(s for s in states if s["key"] == "battery_percentage")
        self.assertEqual(battery["value"]["integer_value"], "70")
        program = next(s for s in states if s["key"] == "vacuum_cleaner_program")
        self.assertEqual(program["value"]["enum_value"], "spot")

    def test_program_not_published_without_fan_speed_list(self):
        """Without ``fan_speed_list`` the ``vacuum_cleaner_program`` feature is undeclared.

        Publishing the current fan speed anyway sent an ENUM value with
        no declared ``allowed_values`` (issue #44 follow-up).
        """
        entity = VacuumCleanerEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("cleaning", fan_speed="turbo"))
        self.assertNotIn("vacuum_cleaner_program", entity.get_final_features_list())
        states = entity.to_sber_current_state()["vacuum.roborock"]["states"]
        self.assertNotIn("vacuum_cleaner_program", [s["key"] for s in states])

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

    def test_cmd_resume(self):
        """``resume`` continues a paused job through ``vacuum.start``.

        It replaces the old ``stop`` case: ``stop`` is not one of the
        four values (``start, resume, pause, return_to_dock``) the
        ``vacuum_cleaner_command`` page documents, so the cloud never
        sends it, while ``resume`` used to be silently dropped.
        """
        entity = self._make_entity("paused")
        result = entity.process_cmd(
            {"states": [{"key": "vacuum_cleaner_command", "value": {"type": "ENUM", "enum_value": "resume"}}]}
        )
        self.assertEqual(result[0]["url"]["service"], "start")

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
        """A Sber route name is translated back to the HA mode label."""
        entity = self._make_entity("cleaning", fan_speed_list=["Spot", "Smart"])
        result = entity.process_cmd(
            {"states": [{"key": "vacuum_cleaner_program", "value": {"type": "ENUM", "enum_value": "spot"}}]}
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["url"]["service"], "set_fan_speed")
        self.assertEqual(result[0]["url"]["service_data"]["fan_speed"], "Spot")

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
        """Only documented values are declared, in Sber's own spelling.

        ``vacuum_cleaner_command`` no longer offers ``stop`` (absent from
        the documented ``start, resume, pause, return_to_dock``), and the
        program list carries the Sber routes rather than the HA labels
        they were derived from.
        """
        entity = VacuumCleanerEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(fan_speed_list=["Spot", "Smart"]))
        result = entity.to_sber_state()
        allowed = result["model"]["allowed_values"]
        self.assertIn("vacuum_cleaner_command", allowed)
        self.assertNotIn("vacuum_cleaner_status", allowed)  # read-only, not in allowed_values
        self.assertEqual(
            sorted(allowed["vacuum_cleaner_command"]["enum_values"]["values"]),
            ["pause", "resume", "return_to_dock", "start"],
        )
        self.assertIn("vacuum_cleaner_program", allowed)
        self.assertEqual(allowed["vacuum_cleaner_program"]["enum_values"]["values"], ["spot", "smart"])


class TestVacuumBatteryLink(unittest.TestCase):
    """Test battery via linked sensor entity (HA vacuum battery_level is deprecated)."""

    def test_linkable_roles_include_battery(self):
        self.assertIn(ROLE_BATTERY, VacuumCleanerEntity.LINKABLE_ROLES)

    def test_legacy_battery_attr_still_works(self):
        entity = VacuumCleanerEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(battery_level=42))
        self.assertEqual(entity._battery_level, 42)
        self.assertIn("battery_percentage", entity.get_final_features_list())

    def test_linked_battery_sensor_sets_level(self):
        entity = VacuumCleanerEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("cleaning"))
        entity.update_linked_data("battery", {"state": "77"})
        self.assertEqual(entity._battery_level, 77)

    def test_linked_battery_gives_feature(self):
        entity = VacuumCleanerEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("cleaning"))
        entity.update_linked_data("battery", {"state": "55"})
        features = entity.get_final_features_list()
        self.assertIn("battery_percentage", features)

    def test_linked_battery_in_sber_state(self):
        entity = VacuumCleanerEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("cleaning"))
        entity.update_linked_data("battery", {"state": "88.0"})
        states = entity.to_sber_current_state()["vacuum.roborock"]["states"]
        battery = next(s for s in states if s["key"] == "battery_percentage")
        self.assertEqual(battery["value"]["integer_value"], "88")

    def test_linked_battery_survives_primary_refresh(self):
        entity = VacuumCleanerEntity(ENTITY_DATA)
        entity.update_linked_data("battery", {"state": "60"})
        entity.fill_by_ha_state(_make_ha_state("cleaning"))
        self.assertEqual(entity._battery_level, 60)
        self.assertIn("battery_percentage", entity.get_final_features_list())

    def test_legacy_attr_overwrites_when_present(self):
        entity = VacuumCleanerEntity(ENTITY_DATA)
        entity.update_linked_data("battery", {"state": "60"})
        entity.fill_by_ha_state(_make_ha_state("cleaning", battery_level=30))
        self.assertEqual(entity._battery_level, 30)

    def test_linked_battery_unavailable_ignored(self):
        entity = VacuumCleanerEntity(ENTITY_DATA)
        entity.update_linked_data("battery", {"state": "50"})
        entity.update_linked_data("battery", {"state": "unavailable"})
        self.assertEqual(entity._battery_level, 50)

    def test_linked_battery_unknown_ignored(self):
        entity = VacuumCleanerEntity(ENTITY_DATA)
        entity.update_linked_data("battery", {"state": "unknown"})
        self.assertIsNone(entity._battery_level)

    def test_linked_battery_invalid_ignored(self):
        entity = VacuumCleanerEntity(ENTITY_DATA)
        entity.update_linked_data("battery", {"state": "not-a-number"})
        self.assertIsNone(entity._battery_level)

    def test_unrelated_role_ignored(self):
        entity = VacuumCleanerEntity(ENTITY_DATA)
        entity.update_linked_data("humidity", {"state": "45"})
        self.assertIsNone(entity._battery_level)

    def test_no_battery_no_feature(self):
        entity = VacuumCleanerEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("cleaning"))
        features = entity.get_final_features_list()
        self.assertNotIn("battery_percentage", features)
        states = entity.to_sber_current_state()["vacuum.roborock"]["states"]
        self.assertNotIn("battery_percentage", [s["key"] for s in states])


class TestFanSpeedListSurvivesAnEmptyRefresh(unittest.TestCase):
    """A momentarily blank ``fan_speed_list`` must not disarm the vacuum.

    Same shape as the TV's ``source_list``: an integration that reports no
    modes for one refresh used to erase the program translation table, so
    every ``vacuum_cleaner_program`` command was silently dropped and the
    published ``allowed_values`` narrowed — churning ``model.id`` and
    costing the user the assigned room (issue #44).
    """

    SPOT_CMD = {"states": [{"key": "vacuum_cleaner_program", "value": {"type": "ENUM", "enum_value": "spot"}}]}

    def _vacuum_that_lost_its_list(self, second_state):
        """Fill a vacuum with two modes, then re-fill it with ``second_state``."""
        entity = VacuumCleanerEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("cleaning", fan_speed="Spot", fan_speed_list=["Spot", "Smart"]))
        entity.fill_by_ha_state(second_state)
        return entity

    def test_command_survives_a_missing_fan_speed_list(self):
        """The attribute vanishing is a gap in the data, not a lost capability."""
        entity = self._vacuum_that_lost_its_list(_make_ha_state("cleaning"))
        result = entity.process_cmd(self.SPOT_CMD)
        self.assertEqual(len(result), 1, "the program command was silently dropped")
        self.assertEqual(result[0]["url"]["service_data"]["fan_speed"], "Spot")

    def test_allowed_values_do_not_churn(self):
        """``allowed_values`` drives ``model.id`` — it must not flap."""
        entity = self._vacuum_that_lost_its_list(_make_ha_state("cleaning", fan_speed_list=[]))
        allowed = entity.to_sber_state()["model"]["allowed_values"]
        self.assertEqual(allowed["vacuum_cleaner_program"]["enum_values"]["values"], ["spot", "smart"])
