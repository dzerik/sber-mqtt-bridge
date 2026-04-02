"""Sber C2C protocol compliance tests for relay, valve, and miscellaneous devices.

Validates that JSON output from device classes conforms to the Sber C2C
specification:
- ``to_sber_state()`` returns correct structure with required keys
- ``to_sber_current_state()`` returns correct value types (BOOL, ENUM, INTEGER)
- All ``integer_value`` fields are strings (Sber spec requirement)
- ``online`` BOOL is always present in current state
- ``hw_version`` / ``sw_version`` present in device descriptor
- Allowed values match Sber-documented ENUM/INTEGER specs
- Commands map to correct HA service calls

Devices covered:
- RelayEntity (relay)
- SocketEntity (socket)
- ValveEntity (valve)
- VacuumCleanerEntity (vacuum_cleaner)
- KettleEntity (kettle)
- IntercomEntity (intercom)
- ScenarioButtonEntity (scenario_button)
- HvacRadiatorEntity (hvac_radiator)
- HvacHeaterEntity (hvac_heater)
- HvacBoilerEntity (hvac_boiler)
- HvacUnderfloorEntity (hvac_underfloor_heating)
"""

from __future__ import annotations

import pytest

from custom_components.sber_mqtt_bridge.devices.relay import RelayEntity
from custom_components.sber_mqtt_bridge.devices.socket_entity import SocketEntity
from custom_components.sber_mqtt_bridge.devices.valve import ValveEntity
from custom_components.sber_mqtt_bridge.devices.vacuum_cleaner import VacuumCleanerEntity
from custom_components.sber_mqtt_bridge.devices.kettle import KettleEntity
from custom_components.sber_mqtt_bridge.devices.intercom import IntercomEntity
from custom_components.sber_mqtt_bridge.devices.scenario_button import ScenarioButtonEntity
from custom_components.sber_mqtt_bridge.devices.hvac_radiator import HvacRadiatorEntity
from custom_components.sber_mqtt_bridge.devices.hvac_heater import HvacHeaterEntity
from custom_components.sber_mqtt_bridge.devices.hvac_boiler import HvacBoilerEntity
from custom_components.sber_mqtt_bridge.devices.hvac_underfloor_heating import HvacUnderfloorEntity


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------


def _find_state(states: list[dict], key: str) -> dict | None:
    """Find a state entry by key in the states list."""
    for s in states:
        if s["key"] == key:
            return s
    return None


def _assert_sber_state_structure(result: dict) -> None:
    """Assert that to_sber_state() output has all required top-level keys.

    Per Sber C2C spec, device descriptor must have:
    id, name, room, model (with id, manufacturer, model, description, category, features),
    hw_version, sw_version.
    """
    assert "id" in result, "Missing 'id' in to_sber_state"
    assert "name" in result, "Missing 'name' in to_sber_state"
    assert "room" in result, "Missing 'room' in to_sber_state"
    assert "hw_version" in result, "Missing 'hw_version' in to_sber_state"
    assert "sw_version" in result, "Missing 'sw_version' in to_sber_state"

    model = result.get("model")
    assert model is not None, "Missing 'model' in to_sber_state"
    for key in ("id", "manufacturer", "model", "description", "category", "features"):
        assert key in model, f"Missing 'model.{key}' in to_sber_state"
    assert isinstance(model["features"], list), "model.features must be a list"


def _assert_online_bool_present(states: list[dict]) -> None:
    """Assert that 'online' BOOL state is always present."""
    online = _find_state(states, "online")
    assert online is not None, "Missing 'online' key in current state"
    assert online["value"]["type"] == "BOOL", "online must be BOOL type"
    assert isinstance(online["value"]["bool_value"], bool), "online.bool_value must be bool"


def _assert_all_integer_values_are_strings(states: list[dict]) -> None:
    """Assert that all INTEGER type values have string integer_value (Sber spec)."""
    for s in states:
        if s["value"].get("type") == "INTEGER":
            val = s["value"]["integer_value"]
            assert isinstance(val, str), (
                f"integer_value for '{s['key']}' must be a string, got {type(val).__name__}: {val!r}"
            )


def _assert_bool_value_is_bool(states: list[dict], key: str) -> None:
    """Assert that a BOOL state has Python bool value."""
    entry = _find_state(states, key)
    if entry is not None:
        assert entry["value"]["type"] == "BOOL"
        assert isinstance(entry["value"]["bool_value"], bool)


def _assert_enum_value_is_string(states: list[dict], key: str) -> None:
    """Assert that an ENUM state has a string enum_value."""
    entry = _find_state(states, key)
    if entry is not None:
        assert entry["value"]["type"] == "ENUM"
        assert isinstance(entry["value"]["enum_value"], str)


# ---------------------------------------------------------------------------
#  RelayEntity compliance tests
# ---------------------------------------------------------------------------


class TestRelayCompliance:
    """Sber C2C compliance tests for RelayEntity (category: relay)."""

    ENTITY_DATA = {"entity_id": "switch.relay1", "name": "Relay"}

    def _make_ha_state(self, state: str = "on", **attrs) -> dict:
        return {"entity_id": "switch.relay1", "state": state, "attributes": attrs}

    def test_category_is_relay(self):
        """RelayEntity must report category='relay'."""
        entity = RelayEntity(self.ENTITY_DATA)
        assert entity.category == "relay"

    def test_to_sber_state_structure(self):
        """to_sber_state() must contain all required Sber C2C keys."""
        entity = RelayEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state())
        result = entity.to_sber_state()
        _assert_sber_state_structure(result)
        assert result["model"]["category"] == "relay"

    def test_hw_sw_version_present(self):
        """hw_version and sw_version must be present in device descriptor."""
        entity = RelayEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state())
        result = entity.to_sber_state()
        assert result["hw_version"] is not None
        assert result["sw_version"] is not None

    def test_features_include_online_on_off(self):
        """Relay must expose online and on_off features."""
        entity = RelayEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state())
        features = entity.create_features_list()
        assert "online" in features
        assert "on_off" in features

    def test_features_include_energy_when_available(self):
        """Relay must expose power/voltage/current when HA provides them."""
        entity = RelayEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state(power=150, voltage=220, current=1))
        features = entity.create_features_list()
        assert "power" in features
        assert "voltage" in features
        assert "current" in features

    def test_features_include_child_lock_when_available(self):
        """Relay must expose child_lock when HA provides it."""
        entity = RelayEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state(child_lock=True))
        features = entity.create_features_list()
        assert "child_lock" in features

    def test_features_exclude_energy_when_not_available(self):
        """Relay must NOT expose power/voltage/current when HA has no attributes."""
        entity = RelayEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state())
        features = entity.create_features_list()
        assert "power" not in features
        assert "voltage" not in features
        assert "current" not in features

    def test_current_state_online_bool_present(self):
        """online BOOL must always be in current state."""
        entity = RelayEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state())
        result = entity.to_sber_current_state()
        states = result["switch.relay1"]["states"]
        _assert_online_bool_present(states)

    def test_current_state_on_off_bool(self):
        """on_off must be BOOL type in current state."""
        entity = RelayEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state("on"))
        states = entity.to_sber_current_state()["switch.relay1"]["states"]
        _assert_bool_value_is_bool(states, "on_off")
        on_off = _find_state(states, "on_off")
        assert on_off["value"]["bool_value"] is True

    def test_current_state_off(self):
        """on_off must be False when HA state is 'off'."""
        entity = RelayEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state("off"))
        states = entity.to_sber_current_state()["switch.relay1"]["states"]
        on_off = _find_state(states, "on_off")
        assert on_off["value"]["bool_value"] is False

    def test_current_state_energy_integer_as_string(self):
        """power/voltage/current INTEGER values must be strings per Sber spec."""
        entity = RelayEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state(power=150, voltage=220, current=1))
        states = entity.to_sber_current_state()["switch.relay1"]["states"]
        _assert_all_integer_values_are_strings(states)
        power = _find_state(states, "power")
        assert power["value"]["integer_value"] == "150"
        voltage = _find_state(states, "voltage")
        assert voltage["value"]["integer_value"] == "220"
        current = _find_state(states, "current")
        assert current["value"]["integer_value"] == "1"

    def test_current_state_child_lock_bool(self):
        """child_lock must be BOOL type when present."""
        entity = RelayEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state(child_lock=True))
        states = entity.to_sber_current_state()["switch.relay1"]["states"]
        _assert_bool_value_is_bool(states, "child_lock")
        child_lock = _find_state(states, "child_lock")
        assert child_lock["value"]["bool_value"] is True

    def test_unavailable_sets_offline(self):
        """HA 'unavailable' state must set online=False."""
        entity = RelayEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state("unavailable"))
        states = entity.to_sber_current_state()["switch.relay1"]["states"]
        online = _find_state(states, "online")
        assert online["value"]["bool_value"] is False

    def test_cmd_on_off_true_maps_to_turn_on(self):
        """on_off BOOL=True command must produce switch.turn_on."""
        entity = RelayEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state("off"))
        result = entity.process_cmd(
            {"states": [{"key": "on_off", "value": {"type": "BOOL", "bool_value": True}}]}
        )
        assert len(result) == 1
        assert result[0]["url"]["domain"] == "switch"
        assert result[0]["url"]["service"] == "turn_on"

    def test_cmd_on_off_false_maps_to_turn_off(self):
        """on_off BOOL=False command must produce switch.turn_off."""
        entity = RelayEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state("on"))
        result = entity.process_cmd(
            {"states": [{"key": "on_off", "value": {"type": "BOOL", "bool_value": False}}]}
        )
        assert len(result) == 1
        assert result[0]["url"]["service"] == "turn_off"

    def test_cmd_button_domain_maps_to_press(self):
        """Relay with button entity_id must produce button.press service."""
        entity = RelayEntity({"entity_id": "button.test", "name": "Button"})
        entity.fill_by_ha_state(
            {"entity_id": "button.test", "state": "unknown", "attributes": {}}
        )
        result = entity.process_cmd(
            {"states": [{"key": "on_off", "value": {"type": "BOOL", "bool_value": True}}]}
        )
        assert len(result) == 1
        assert result[0]["url"]["domain"] == "button"
        assert result[0]["url"]["service"] == "press"

    def test_cmd_script_domain_maps_to_turn_on(self):
        """Relay with script entity_id must produce script.turn_on service."""
        entity = RelayEntity({"entity_id": "script.my_script", "name": "Script"})
        entity.fill_by_ha_state(
            {"entity_id": "script.my_script", "state": "off", "attributes": {}}
        )
        result = entity.process_cmd(
            {"states": [{"key": "on_off", "value": {"type": "BOOL", "bool_value": True}}]}
        )
        assert result[0]["url"]["domain"] == "script"
        assert result[0]["url"]["service"] == "turn_on"


# ---------------------------------------------------------------------------
#  SocketEntity compliance tests
# ---------------------------------------------------------------------------


class TestSocketCompliance:
    """Sber C2C compliance tests for SocketEntity (category: socket)."""

    ENTITY_DATA = {"entity_id": "switch.outlet", "name": "Smart Socket"}

    def _make_ha_state(self, state: str = "on", **attrs) -> dict:
        return {"entity_id": "switch.outlet", "state": state, "attributes": attrs}

    def test_category_is_socket(self):
        """SocketEntity must report category='socket'."""
        entity = SocketEntity(self.ENTITY_DATA)
        assert entity.category == "socket"

    def test_inherits_relay(self):
        """SocketEntity must inherit from RelayEntity."""
        entity = SocketEntity(self.ENTITY_DATA)
        assert isinstance(entity, RelayEntity)

    def test_to_sber_state_structure(self):
        """to_sber_state() must contain all required Sber C2C keys."""
        entity = SocketEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state())
        result = entity.to_sber_state()
        _assert_sber_state_structure(result)
        assert result["model"]["category"] == "socket"

    def test_features_same_as_relay(self):
        """Socket features must include online and on_off (same as relay)."""
        entity = SocketEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state())
        features = entity.create_features_list()
        assert "online" in features
        assert "on_off" in features

    def test_socket_energy_features(self):
        """Socket must expose energy features when HA provides them."""
        entity = SocketEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state(power=100, voltage=230, current=2))
        features = entity.create_features_list()
        assert "power" in features
        assert "voltage" in features
        assert "current" in features

    def test_current_state_online_bool(self):
        """online BOOL must be present in socket current state."""
        entity = SocketEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state())
        states = entity.to_sber_current_state()["switch.outlet"]["states"]
        _assert_online_bool_present(states)

    def test_current_state_integer_values_are_strings(self):
        """All INTEGER values in socket state must be strings."""
        entity = SocketEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state(power=50, voltage=225, current=3))
        states = entity.to_sber_current_state()["switch.outlet"]["states"]
        _assert_all_integer_values_are_strings(states)

    def test_cmd_maps_to_switch_domain(self):
        """Socket on_off command must target switch domain."""
        entity = SocketEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state("off"))
        result = entity.process_cmd(
            {"states": [{"key": "on_off", "value": {"type": "BOOL", "bool_value": True}}]}
        )
        assert result[0]["url"]["domain"] == "switch"
        assert result[0]["url"]["service"] == "turn_on"


# ---------------------------------------------------------------------------
#  ValveEntity compliance tests
# ---------------------------------------------------------------------------


class TestValveCompliance:
    """Sber C2C compliance tests for ValveEntity (category: valve)."""

    ENTITY_DATA = {"entity_id": "valve.main", "name": "Main Valve"}

    def _make_ha_state(self, state: str = "open", **attrs) -> dict:
        return {"entity_id": "valve.main", "state": state, "attributes": attrs}

    def test_category_is_valve(self):
        """ValveEntity must report category='valve'."""
        entity = ValveEntity(self.ENTITY_DATA)
        assert entity.category == "valve"

    def test_to_sber_state_structure(self):
        """to_sber_state() must contain all required Sber C2C keys."""
        entity = ValveEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state())
        result = entity.to_sber_state()
        _assert_sber_state_structure(result)
        assert result["model"]["category"] == "valve"

    def test_features_include_open_set_open_state(self):
        """Valve must expose online, open_set, open_state features."""
        entity = ValveEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state())
        features = entity.create_features_list()
        assert "online" in features
        assert "open_set" in features
        assert "open_state" in features

    def test_features_do_not_include_on_off(self):
        """Valve must NOT expose on_off feature (uses open_set instead)."""
        entity = ValveEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state())
        features = entity.create_features_list()
        assert "on_off" not in features

    def test_features_include_battery_when_available(self):
        """Valve must expose battery_percentage when HA provides battery attr."""
        entity = ValveEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state(battery=85))
        features = entity.create_features_list()
        assert "battery_percentage" in features
        assert "battery_low_power" in features

    def test_features_include_signal_strength_when_available(self):
        """Valve must expose signal_strength when HA provides rssi attr."""
        entity = ValveEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state(rssi=-60))
        features = entity.create_features_list()
        assert "signal_strength" in features

    def test_current_state_online_bool_present(self):
        """online BOOL must be present in valve current state."""
        entity = ValveEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state())
        states = entity.to_sber_current_state()["valve.main"]["states"]
        _assert_online_bool_present(states)

    def test_current_state_open_state_enum(self):
        """open_state must be ENUM with 'open' when valve is open."""
        entity = ValveEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state("open"))
        states = entity.to_sber_current_state()["valve.main"]["states"]
        _assert_enum_value_is_string(states, "open_state")
        open_state = _find_state(states, "open_state")
        assert open_state["value"]["enum_value"] == "open"

    def test_current_state_close_state_enum(self):
        """open_state must be ENUM with 'close' when valve is closed."""
        entity = ValveEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state("closed"))
        states = entity.to_sber_current_state()["valve.main"]["states"]
        open_state = _find_state(states, "open_state")
        assert open_state["value"]["enum_value"] == "close"

    def test_current_state_no_on_off(self):
        """on_off must NOT be present in valve current state."""
        entity = ValveEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state())
        states = entity.to_sber_current_state()["valve.main"]["states"]
        keys = [s["key"] for s in states]
        assert "on_off" not in keys

    def test_current_state_battery_integer_as_string(self):
        """battery_percentage INTEGER must be a string per Sber spec."""
        entity = ValveEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state(battery=85))
        states = entity.to_sber_current_state()["valve.main"]["states"]
        _assert_all_integer_values_are_strings(states)
        batt = _find_state(states, "battery_percentage")
        assert batt["value"]["integer_value"] == "85"

    def test_allowed_values_open_set_enum(self):
        """Allowed values for open_set must be ENUM with open/close/stop."""
        entity = ValveEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state())
        result = entity.to_sber_state()
        allowed = result["model"]["allowed_values"]
        assert "open_set" in allowed
        vals = allowed["open_set"]["enum_values"]["values"]
        assert set(vals) == {"open", "close", "stop"}

    @pytest.mark.parametrize(
        "cmd_value,expected_service",
        [
            ("open", "open_valve"),
            ("close", "close_valve"),
            ("stop", "stop_valve"),
        ],
    )
    def test_cmd_open_set_maps_to_valve_service(self, cmd_value, expected_service):
        """open_set ENUM commands must map to correct valve services."""
        entity = ValveEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state("closed"))
        result = entity.process_cmd(
            {"states": [{"key": "open_set", "value": {"type": "ENUM", "enum_value": cmd_value}}]}
        )
        assert len(result) == 1
        assert result[0]["url"]["domain"] == "valve"
        assert result[0]["url"]["service"] == expected_service

    def test_cmd_unknown_open_set_value_ignored(self):
        """Unknown open_set enum value must be ignored."""
        entity = ValveEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state())
        result = entity.process_cmd(
            {"states": [{"key": "open_set", "value": {"type": "ENUM", "enum_value": "half_open"}}]}
        )
        assert len(result) == 0


# ---------------------------------------------------------------------------
#  VacuumCleanerEntity compliance tests
# ---------------------------------------------------------------------------


class TestVacuumCleanerCompliance:
    """Sber C2C compliance tests for VacuumCleanerEntity (category: vacuum_cleaner)."""

    ENTITY_DATA = {"entity_id": "vacuum.robo", "name": "Robot Vacuum"}

    def _make_ha_state(self, state: str = "docked", **attrs) -> dict:
        return {"entity_id": "vacuum.robo", "state": state, "attributes": attrs}

    def test_category_is_vacuum_cleaner(self):
        """VacuumCleanerEntity must report category='vacuum_cleaner'."""
        entity = VacuumCleanerEntity(self.ENTITY_DATA)
        assert entity.category == "vacuum_cleaner"

    def test_to_sber_state_structure(self):
        """to_sber_state() must contain all required Sber C2C keys."""
        entity = VacuumCleanerEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state())
        result = entity.to_sber_state()
        _assert_sber_state_structure(result)
        assert result["model"]["category"] == "vacuum_cleaner"

    def test_features_include_command_and_status(self):
        """Vacuum must expose vacuum_cleaner_command and vacuum_cleaner_status."""
        entity = VacuumCleanerEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state())
        features = entity.create_features_list()
        assert "online" in features
        assert "vacuum_cleaner_command" in features
        assert "vacuum_cleaner_status" in features

    def test_features_include_program_when_fan_speed_list(self):
        """Vacuum must expose vacuum_cleaner_program when fan_speed_list is available."""
        entity = VacuumCleanerEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(
            self._make_ha_state(fan_speed_list=["low", "medium", "high"], fan_speed="low")
        )
        features = entity.create_features_list()
        assert "vacuum_cleaner_program" in features

    def test_features_exclude_program_when_no_fan_speed(self):
        """Vacuum must NOT expose vacuum_cleaner_program when fan_speed_list is empty."""
        entity = VacuumCleanerEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state())
        features = entity.create_features_list()
        assert "vacuum_cleaner_program" not in features

    def test_features_include_cleaning_type_when_available(self):
        """Vacuum must expose vacuum_cleaner_cleaning_type when cleaning_type attr present."""
        entity = VacuumCleanerEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state(cleaning_type="dry"))
        features = entity.create_features_list()
        assert "vacuum_cleaner_cleaning_type" in features

    def test_features_include_battery_when_available(self):
        """Vacuum must expose battery_percentage when battery_level is available."""
        entity = VacuumCleanerEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state(battery_level=75))
        features = entity.create_features_list()
        assert "battery_percentage" in features

    def test_current_state_online_bool_present(self):
        """online BOOL must be present in vacuum current state."""
        entity = VacuumCleanerEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state())
        states = entity.to_sber_current_state()["vacuum.robo"]["states"]
        _assert_online_bool_present(states)

    def test_current_state_status_enum(self):
        """vacuum_cleaner_status must be ENUM in current state."""
        entity = VacuumCleanerEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state("cleaning"))
        states = entity.to_sber_current_state()["vacuum.robo"]["states"]
        _assert_enum_value_is_string(states, "vacuum_cleaner_status")
        status = _find_state(states, "vacuum_cleaner_status")
        assert status["value"]["enum_value"] == "cleaning"

    @pytest.mark.parametrize(
        "ha_state,expected_sber_status",
        [
            ("cleaning", "cleaning"),
            ("returning", "go_home"),
            ("docked", "standby"),
            ("paused", "standby"),
            ("idle", "standby"),
            ("error", "error"),
        ],
    )
    def test_ha_state_to_sber_status_mapping(self, ha_state, expected_sber_status):
        """HA vacuum states must map to correct Sber status values."""
        entity = VacuumCleanerEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state(ha_state))
        states = entity.to_sber_current_state()["vacuum.robo"]["states"]
        status = _find_state(states, "vacuum_cleaner_status")
        assert status["value"]["enum_value"] == expected_sber_status

    def test_current_state_battery_integer_as_string(self):
        """battery_percentage INTEGER must be a string per Sber spec."""
        entity = VacuumCleanerEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state(battery_level=42))
        states = entity.to_sber_current_state()["vacuum.robo"]["states"]
        _assert_all_integer_values_are_strings(states)
        batt = _find_state(states, "battery_percentage")
        assert batt["value"]["integer_value"] == "42"

    def test_current_state_fan_speed_enum(self):
        """vacuum_cleaner_program must be ENUM when fan_speed is set."""
        entity = VacuumCleanerEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(
            self._make_ha_state(fan_speed="medium", fan_speed_list=["low", "medium", "high"])
        )
        states = entity.to_sber_current_state()["vacuum.robo"]["states"]
        _assert_enum_value_is_string(states, "vacuum_cleaner_program")
        prog = _find_state(states, "vacuum_cleaner_program")
        assert prog["value"]["enum_value"] == "medium"

    def test_current_state_cleaning_type_enum(self):
        """vacuum_cleaner_cleaning_type must be ENUM when cleaning_type is set."""
        entity = VacuumCleanerEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state(cleaning_type="wet"))
        states = entity.to_sber_current_state()["vacuum.robo"]["states"]
        _assert_enum_value_is_string(states, "vacuum_cleaner_cleaning_type")
        ct = _find_state(states, "vacuum_cleaner_cleaning_type")
        assert ct["value"]["enum_value"] == "wet"

    def test_allowed_values_command_enum(self):
        """Allowed values for vacuum_cleaner_command must include start/stop/pause/return_to_dock."""
        entity = VacuumCleanerEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state())
        result = entity.to_sber_state()
        allowed = result["model"]["allowed_values"]
        assert "vacuum_cleaner_command" in allowed
        vals = allowed["vacuum_cleaner_command"]["enum_values"]["values"]
        assert set(vals) == {"start", "stop", "pause", "return_to_dock"}

    def test_allowed_values_status_enum(self):
        """Allowed values for vacuum_cleaner_status must include all valid states."""
        entity = VacuumCleanerEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state())
        result = entity.to_sber_state()
        allowed = result["model"]["allowed_values"]
        assert "vacuum_cleaner_status" in allowed
        vals = set(allowed["vacuum_cleaner_status"]["enum_values"]["values"])
        assert {"cleaning", "charging", "standby", "go_home", "error"} <= vals

    def test_allowed_values_program_when_fan_speeds(self):
        """Allowed values for vacuum_cleaner_program must list fan speeds."""
        entity = VacuumCleanerEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(
            self._make_ha_state(fan_speed_list=["silent", "standard", "turbo"])
        )
        result = entity.to_sber_state()
        allowed = result["model"]["allowed_values"]
        assert "vacuum_cleaner_program" in allowed
        vals = allowed["vacuum_cleaner_program"]["enum_values"]["values"]
        assert vals == ["silent", "standard", "turbo"]

    def test_allowed_values_cleaning_type_when_available(self):
        """Allowed values for vacuum_cleaner_cleaning_type must include dry/wet/dry_and_wet."""
        entity = VacuumCleanerEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state(cleaning_type="dry"))
        result = entity.to_sber_state()
        allowed = result["model"]["allowed_values"]
        assert "vacuum_cleaner_cleaning_type" in allowed
        vals = set(allowed["vacuum_cleaner_cleaning_type"]["enum_values"]["values"])
        assert vals == {"dry", "wet", "dry_and_wet"}

    @pytest.mark.parametrize(
        "cmd_value,expected_service",
        [
            ("start", "start"),
            ("stop", "stop"),
            ("pause", "pause"),
            ("return_to_dock", "return_to_base"),
        ],
    )
    def test_cmd_vacuum_command_maps_to_service(self, cmd_value, expected_service):
        """vacuum_cleaner_command ENUM must map to correct HA vacuum services."""
        entity = VacuumCleanerEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state())
        result = entity.process_cmd(
            {"states": [{"key": "vacuum_cleaner_command", "value": {"type": "ENUM", "enum_value": cmd_value}}]}
        )
        assert len(result) == 1
        assert result[0]["url"]["domain"] == "vacuum"
        assert result[0]["url"]["service"] == expected_service

    def test_cmd_vacuum_program_maps_to_set_fan_speed(self):
        """vacuum_cleaner_program ENUM must map to vacuum.set_fan_speed."""
        entity = VacuumCleanerEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state())
        result = entity.process_cmd(
            {"states": [{"key": "vacuum_cleaner_program", "value": {"type": "ENUM", "enum_value": "turbo"}}]}
        )
        assert len(result) == 1
        assert result[0]["url"]["service"] == "set_fan_speed"
        assert result[0]["url"]["service_data"]["fan_speed"] == "turbo"

    def test_cmd_unknown_command_ignored(self):
        """Unknown vacuum_cleaner_command value must be ignored."""
        entity = VacuumCleanerEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state())
        result = entity.process_cmd(
            {"states": [{"key": "vacuum_cleaner_command", "value": {"type": "ENUM", "enum_value": "self_destruct"}}]}
        )
        assert len(result) == 0

    def test_unavailable_sets_offline(self):
        """HA 'unavailable' state must set online=False."""
        entity = VacuumCleanerEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state("unavailable"))
        states = entity.to_sber_current_state()["vacuum.robo"]["states"]
        online = _find_state(states, "online")
        assert online["value"]["bool_value"] is False


# ---------------------------------------------------------------------------
#  KettleEntity compliance tests
# ---------------------------------------------------------------------------


class TestKettleCompliance:
    """Sber C2C compliance tests for KettleEntity (category: kettle)."""

    ENTITY_DATA = {"entity_id": "water_heater.kettle", "name": "Kitchen Kettle"}

    def _make_ha_state(self, state: str = "idle", **attrs) -> dict:
        return {"entity_id": "water_heater.kettle", "state": state, "attributes": attrs}

    def test_category_is_kettle(self):
        """KettleEntity must report category='kettle'."""
        entity = KettleEntity(self.ENTITY_DATA)
        assert entity.category == "kettle"

    def test_to_sber_state_structure(self):
        """to_sber_state() must contain all required Sber C2C keys."""
        entity = KettleEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state())
        result = entity.to_sber_state()
        _assert_sber_state_structure(result)
        assert result["model"]["category"] == "kettle"

    def test_features_list(self):
        """Kettle must expose all required Sber features."""
        entity = KettleEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state())
        features = entity.create_features_list()
        for feat in ("online", "on_off", "kitchen_water_temperature",
                     "kitchen_water_temperature_set", "kitchen_water_low_level", "child_lock"):
            assert feat in features, f"Missing feature: {feat}"

    def test_current_state_online_bool_present(self):
        """online BOOL must be present in kettle current state."""
        entity = KettleEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state())
        states = entity.to_sber_current_state()["water_heater.kettle"]["states"]
        _assert_online_bool_present(states)

    def test_current_state_on_off_bool(self):
        """on_off must be BOOL in current state."""
        entity = KettleEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state("heating"))
        states = entity.to_sber_current_state()["water_heater.kettle"]["states"]
        _assert_bool_value_is_bool(states, "on_off")
        on_off = _find_state(states, "on_off")
        assert on_off["value"]["bool_value"] is True

    def test_current_state_temperature_integer_as_string(self):
        """Temperature INTEGER values must be strings per Sber spec."""
        entity = KettleEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state("heating", current_temperature=85, temperature=100))
        states = entity.to_sber_current_state()["water_heater.kettle"]["states"]
        _assert_all_integer_values_are_strings(states)
        temp = _find_state(states, "kitchen_water_temperature")
        assert temp["value"]["integer_value"] == "85"
        target = _find_state(states, "kitchen_water_temperature_set")
        assert target["value"]["integer_value"] == "100"

    def test_current_state_child_lock_bool(self):
        """child_lock must be BOOL in current state."""
        entity = KettleEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state("idle"))
        states = entity.to_sber_current_state()["water_heater.kettle"]["states"]
        _assert_bool_value_is_bool(states, "child_lock")

    def test_current_state_low_level_bool(self):
        """kitchen_water_low_level must be BOOL in current state."""
        entity = KettleEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state("idle", current_temperature=25))
        states = entity.to_sber_current_state()["water_heater.kettle"]["states"]
        _assert_bool_value_is_bool(states, "kitchen_water_low_level")
        low = _find_state(states, "kitchen_water_low_level")
        assert low["value"]["bool_value"] is True  # temp < 30 => low water

    def test_allowed_values_temperature_set(self):
        """Allowed values for kitchen_water_temperature_set must have INTEGER range."""
        entity = KettleEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state())
        result = entity.to_sber_state()
        allowed = result["model"]["allowed_values"]
        assert "kitchen_water_temperature_set" in allowed
        vals = allowed["kitchen_water_temperature_set"]["integer_values"]
        assert vals["min"] == "60"
        assert vals["max"] == "100"
        assert vals["step"] == "10"
        # min/max/step must be strings per Sber spec
        assert isinstance(vals["min"], str)
        assert isinstance(vals["max"], str)
        assert isinstance(vals["step"], str)

    def test_cmd_on_off_maps_to_water_heater(self):
        """on_off command must target water_heater domain."""
        entity = KettleEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state("off"))
        result = entity.process_cmd(
            {"states": [{"key": "on_off", "value": {"type": "BOOL", "bool_value": True}}]}
        )
        assert len(result) == 1
        assert result[0]["url"]["domain"] == "water_heater"
        assert result[0]["url"]["service"] == "turn_on"

    def test_cmd_set_temperature(self):
        """kitchen_water_temperature_set must map to set_temperature service."""
        entity = KettleEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state("heating"))
        result = entity.process_cmd(
            {"states": [{"key": "kitchen_water_temperature_set", "value": {"type": "INTEGER", "integer_value": "80"}}]}
        )
        assert len(result) == 1
        assert result[0]["url"]["service"] == "set_temperature"
        assert result[0]["url"]["service_data"]["temperature"] == 80

    def test_unavailable_sets_offline(self):
        """HA 'unavailable' state must set online=False."""
        entity = KettleEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state("unavailable"))
        states = entity.to_sber_current_state()["water_heater.kettle"]["states"]
        online = _find_state(states, "online")
        assert online["value"]["bool_value"] is False


# ---------------------------------------------------------------------------
#  IntercomEntity compliance tests
# ---------------------------------------------------------------------------


class TestIntercomCompliance:
    """Sber C2C compliance tests for IntercomEntity (category: intercom)."""

    ENTITY_DATA = {"entity_id": "switch.intercom", "name": "Front Door Intercom"}

    def _make_ha_state(self, state: str = "on", **attrs) -> dict:
        return {"entity_id": "switch.intercom", "state": state, "attributes": attrs}

    def test_category_is_intercom(self):
        """IntercomEntity must report category='intercom'."""
        entity = IntercomEntity(self.ENTITY_DATA)
        assert entity.category == "intercom"

    def test_to_sber_state_structure(self):
        """to_sber_state() must contain all required Sber C2C keys."""
        entity = IntercomEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state())
        result = entity.to_sber_state()
        _assert_sber_state_structure(result)
        assert result["model"]["category"] == "intercom"

    def test_features_list(self):
        """Intercom must expose all required Sber features."""
        entity = IntercomEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state())
        features = entity.create_features_list()
        for feat in ("online", "on_off", "incoming_call", "reject_call", "unlock"):
            assert feat in features, f"Missing feature: {feat}"

    def test_current_state_online_bool_present(self):
        """online BOOL must be present in intercom current state."""
        entity = IntercomEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state())
        states = entity.to_sber_current_state()["switch.intercom"]["states"]
        _assert_online_bool_present(states)

    def test_current_state_all_bools(self):
        """All intercom state keys must be BOOL type."""
        entity = IntercomEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state("on", incoming_call=True, unlock=True))
        states = entity.to_sber_current_state()["switch.intercom"]["states"]
        for key in ("on_off", "incoming_call", "reject_call", "unlock"):
            _assert_bool_value_is_bool(states, key)

    def test_current_state_on_off_true(self):
        """on_off must be True when HA state is 'on'."""
        entity = IntercomEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state("on"))
        states = entity.to_sber_current_state()["switch.intercom"]["states"]
        on_off = _find_state(states, "on_off")
        assert on_off["value"]["bool_value"] is True

    def test_current_state_on_off_false(self):
        """on_off must be False when HA state is 'off'."""
        entity = IntercomEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state("off"))
        states = entity.to_sber_current_state()["switch.intercom"]["states"]
        on_off = _find_state(states, "on_off")
        assert on_off["value"]["bool_value"] is False

    def test_cmd_on_off_maps_to_switch(self):
        """on_off command must target switch domain."""
        entity = IntercomEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state("off"))
        result = entity.process_cmd(
            {"states": [{"key": "on_off", "value": {"type": "BOOL", "bool_value": True}}]}
        )
        assert len(result) == 1
        assert result[0]["url"]["domain"] == "switch"
        assert result[0]["url"]["service"] == "turn_on"

    def test_cmd_read_only_keys_ignored(self):
        """Read-only features (incoming_call, reject_call, unlock) must be ignored in commands."""
        entity = IntercomEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state())
        for key in ("incoming_call", "reject_call", "unlock"):
            result = entity.process_cmd(
                {"states": [{"key": key, "value": {"type": "BOOL", "bool_value": True}}]}
            )
            assert len(result) == 0, f"Command for read-only key '{key}' should be ignored"

    def test_unavailable_sets_offline(self):
        """HA 'unavailable' state must set online=False."""
        entity = IntercomEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state("unavailable"))
        states = entity.to_sber_current_state()["switch.intercom"]["states"]
        online = _find_state(states, "online")
        assert online["value"]["bool_value"] is False


# ---------------------------------------------------------------------------
#  ScenarioButtonEntity compliance tests
# ---------------------------------------------------------------------------


class TestScenarioButtonCompliance:
    """Sber C2C compliance tests for ScenarioButtonEntity (category: scenario_button)."""

    ENTITY_DATA = {"entity_id": "input_boolean.scene", "name": "Scene Button"}

    def _make_ha_state(self, state: str = "on") -> dict:
        return {"entity_id": "input_boolean.scene", "state": state, "attributes": {}}

    def test_category_is_scenario_button(self):
        """ScenarioButtonEntity must report category='scenario_button'."""
        entity = ScenarioButtonEntity(self.ENTITY_DATA)
        assert entity.category == "scenario_button"

    def test_to_sber_state_structure(self):
        """to_sber_state() must contain all required Sber C2C keys."""
        entity = ScenarioButtonEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state())
        result = entity.to_sber_state()
        _assert_sber_state_structure(result)
        assert result["model"]["category"] == "scenario_button"

    def test_features_include_button_event(self):
        """ScenarioButton must expose online and button_event features."""
        entity = ScenarioButtonEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state())
        features = entity.create_features_list()
        assert "online" in features
        assert "button_event" in features

    def test_current_state_online_bool_present(self):
        """online BOOL must be present in scenario_button current state."""
        entity = ScenarioButtonEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state())
        states = entity.to_sber_current_state()["input_boolean.scene"]["states"]
        _assert_online_bool_present(states)

    def test_current_state_button_event_enum(self):
        """button_event must be ENUM in current state."""
        entity = ScenarioButtonEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state("on"))
        states = entity.to_sber_current_state()["input_boolean.scene"]["states"]
        _assert_enum_value_is_string(states, "button_event")
        event = _find_state(states, "button_event")
        assert event["value"]["enum_value"] == "click"

    def test_on_state_maps_to_click(self):
        """HA 'on' state must map to button_event='click'."""
        entity = ScenarioButtonEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state("on"))
        states = entity.to_sber_current_state()["input_boolean.scene"]["states"]
        event = _find_state(states, "button_event")
        assert event["value"]["enum_value"] == "click"

    def test_off_state_maps_to_double_click(self):
        """HA 'off' state must map to button_event='double_click'."""
        entity = ScenarioButtonEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state("off"))
        states = entity.to_sber_current_state()["input_boolean.scene"]["states"]
        event = _find_state(states, "button_event")
        assert event["value"]["enum_value"] == "double_click"

    def test_allowed_values_button_event_enum(self):
        """Allowed values for button_event must include click/double_click/long_press."""
        entity = ScenarioButtonEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state())
        result = entity.to_sber_state()
        allowed = result["model"]["allowed_values"]
        assert "button_event" in allowed
        vals = set(allowed["button_event"]["enum_values"]["values"])
        assert vals == {"click", "double_click", "long_press"}

    def test_process_cmd_is_noop(self):
        """ScenarioButton must return empty list for any command (read-only)."""
        entity = ScenarioButtonEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state())
        result = entity.process_cmd(
            {"states": [{"key": "button_event", "value": {"type": "ENUM", "enum_value": "click"}}]}
        )
        assert result == []

    def test_unavailable_state_preserves_event(self):
        """HA 'unavailable' must not change button_event value."""
        entity = ScenarioButtonEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state("on"))
        assert entity.button_event == "click"
        entity.fill_by_ha_state(self._make_ha_state("unavailable"))
        # button_event should remain unchanged for unavailable/unknown
        assert entity.button_event == "click"


# ---------------------------------------------------------------------------
#  HVAC variant compliance tests
# ---------------------------------------------------------------------------


class TestHvacRadiatorCompliance:
    """Sber C2C compliance tests for HvacRadiatorEntity (category: hvac_radiator)."""

    ENTITY_DATA = {"entity_id": "climate.radiator", "name": "Radiator"}

    def _make_ha_state(self, state: str = "heat", **attrs) -> dict:
        base_attrs = {"current_temperature": 22, "temperature": 30}
        base_attrs.update(attrs)
        return {"entity_id": "climate.radiator", "state": state, "attributes": base_attrs}

    def test_category_is_hvac_radiator(self):
        """HvacRadiatorEntity must report category='hvac_radiator'."""
        entity = HvacRadiatorEntity(self.ENTITY_DATA)
        assert entity.category == "hvac_radiator"

    def test_to_sber_state_structure(self):
        """to_sber_state() must contain all required Sber C2C keys."""
        entity = HvacRadiatorEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state())
        result = entity.to_sber_state()
        _assert_sber_state_structure(result)
        assert result["model"]["category"] == "hvac_radiator"

    def test_features_no_fan_swing_work_mode(self):
        """Radiator must NOT support fan, swing, or work_mode features."""
        entity = HvacRadiatorEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state(
            fan_modes=["low", "high"],
            swing_modes=["off", "vertical"],
            hvac_modes=["off", "heat"],
        ))
        features = entity.create_features_list()
        assert "hvac_air_flow_power" not in features
        assert "hvac_air_flow_direction" not in features
        assert "hvac_work_mode" not in features
        assert "hvac_thermostat_mode" not in features

    def test_features_include_temperature(self):
        """Radiator must include on_off, temperature, hvac_temp_set."""
        entity = HvacRadiatorEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state())
        features = entity.create_features_list()
        assert "online" in features
        assert "on_off" in features
        assert "temperature" in features
        assert "hvac_temp_set" in features

    def test_current_state_online_bool_present(self):
        """online BOOL must be present."""
        entity = HvacRadiatorEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state())
        states = entity.to_sber_current_state()["climate.radiator"]["states"]
        _assert_online_bool_present(states)

    def test_current_state_integer_values_are_strings(self):
        """All INTEGER values in radiator state must be strings."""
        entity = HvacRadiatorEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state())
        states = entity.to_sber_current_state()["climate.radiator"]["states"]
        _assert_all_integer_values_are_strings(states)


class TestHvacHeaterCompliance:
    """Sber C2C compliance tests for HvacHeaterEntity (category: hvac_heater)."""

    ENTITY_DATA = {"entity_id": "climate.heater", "name": "Space Heater"}

    def _make_ha_state(self, state: str = "heat", **attrs) -> dict:
        base_attrs = {"current_temperature": 20, "temperature": 25}
        base_attrs.update(attrs)
        return {"entity_id": "climate.heater", "state": state, "attributes": base_attrs}

    def test_category_is_hvac_heater(self):
        """HvacHeaterEntity must report category='hvac_heater'."""
        entity = HvacHeaterEntity(self.ENTITY_DATA)
        assert entity.category == "hvac_heater"

    def test_to_sber_state_structure(self):
        """to_sber_state() must contain all required Sber C2C keys."""
        entity = HvacHeaterEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state())
        result = entity.to_sber_state()
        _assert_sber_state_structure(result)
        assert result["model"]["category"] == "hvac_heater"

    def test_supports_fan_and_thermostat_mode(self):
        """Heater must support hvac_air_flow_power and hvac_thermostat_mode."""
        entity = HvacHeaterEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state(
            fan_modes=["low", "high"],
            hvac_modes=["off", "heat"],
        ))
        features = entity.create_features_list()
        assert "hvac_air_flow_power" in features
        assert "hvac_thermostat_mode" in features

    def test_no_swing_no_work_mode(self):
        """Heater must NOT support swing or work_mode features."""
        entity = HvacHeaterEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state(
            swing_modes=["off", "vertical"],
            hvac_modes=["off", "heat"],
        ))
        features = entity.create_features_list()
        assert "hvac_air_flow_direction" not in features
        assert "hvac_work_mode" not in features

    def test_current_state_online_bool_present(self):
        """online BOOL must be present."""
        entity = HvacHeaterEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state())
        states = entity.to_sber_current_state()["climate.heater"]["states"]
        _assert_online_bool_present(states)

    def test_current_state_integer_values_are_strings(self):
        """All INTEGER values in heater state must be strings."""
        entity = HvacHeaterEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state())
        states = entity.to_sber_current_state()["climate.heater"]["states"]
        _assert_all_integer_values_are_strings(states)


class TestHvacBoilerCompliance:
    """Sber C2C compliance tests for HvacBoilerEntity (category: hvac_boiler)."""

    ENTITY_DATA = {"entity_id": "climate.boiler", "name": "Water Boiler"}

    def _make_ha_state(self, state: str = "heat", **attrs) -> dict:
        base_attrs = {"current_temperature": 55, "temperature": 65}
        base_attrs.update(attrs)
        return {"entity_id": "climate.boiler", "state": state, "attributes": base_attrs}

    def test_category_is_hvac_boiler(self):
        """HvacBoilerEntity must report category='hvac_boiler'."""
        entity = HvacBoilerEntity(self.ENTITY_DATA)
        assert entity.category == "hvac_boiler"

    def test_to_sber_state_structure(self):
        """to_sber_state() must contain all required Sber C2C keys."""
        entity = HvacBoilerEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state())
        result = entity.to_sber_state()
        _assert_sber_state_structure(result)
        assert result["model"]["category"] == "hvac_boiler"

    def test_supports_thermostat_mode(self):
        """Boiler must support hvac_thermostat_mode (NOT hvac_work_mode)."""
        entity = HvacBoilerEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state(hvac_modes=["off", "heat"]))
        features = entity.create_features_list()
        assert "hvac_thermostat_mode" in features
        assert "hvac_work_mode" not in features

    def test_no_fan_no_swing(self):
        """Boiler must NOT support fan or swing features."""
        entity = HvacBoilerEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state(
            fan_modes=["low", "high"],
            swing_modes=["off", "vertical"],
        ))
        features = entity.create_features_list()
        assert "hvac_air_flow_power" not in features
        assert "hvac_air_flow_direction" not in features

    def test_current_state_online_bool_present(self):
        """online BOOL must be present."""
        entity = HvacBoilerEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state())
        states = entity.to_sber_current_state()["climate.boiler"]["states"]
        _assert_online_bool_present(states)

    def test_current_state_integer_values_are_strings(self):
        """All INTEGER values in boiler state must be strings."""
        entity = HvacBoilerEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state())
        states = entity.to_sber_current_state()["climate.boiler"]["states"]
        _assert_all_integer_values_are_strings(states)


class TestHvacUnderfloorCompliance:
    """Sber C2C compliance tests for HvacUnderfloorEntity (category: hvac_underfloor_heating)."""

    ENTITY_DATA = {"entity_id": "climate.floor", "name": "Underfloor Heating"}

    def _make_ha_state(self, state: str = "heat", **attrs) -> dict:
        base_attrs = {"current_temperature": 28, "temperature": 35}
        base_attrs.update(attrs)
        return {"entity_id": "climate.floor", "state": state, "attributes": base_attrs}

    def test_category_is_hvac_underfloor_heating(self):
        """HvacUnderfloorEntity must report category='hvac_underfloor_heating'."""
        entity = HvacUnderfloorEntity(self.ENTITY_DATA)
        assert entity.category == "hvac_underfloor_heating"

    def test_to_sber_state_structure(self):
        """to_sber_state() must contain all required Sber C2C keys."""
        entity = HvacUnderfloorEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state())
        result = entity.to_sber_state()
        _assert_sber_state_structure(result)
        assert result["model"]["category"] == "hvac_underfloor_heating"

    def test_supports_thermostat_mode(self):
        """Underfloor must support hvac_thermostat_mode (NOT hvac_work_mode)."""
        entity = HvacUnderfloorEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state(hvac_modes=["off", "heat"]))
        features = entity.create_features_list()
        assert "hvac_thermostat_mode" in features
        assert "hvac_work_mode" not in features

    def test_no_fan_no_swing(self):
        """Underfloor must NOT support fan or swing features."""
        entity = HvacUnderfloorEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state(
            fan_modes=["low", "high"],
            swing_modes=["off", "vertical"],
        ))
        features = entity.create_features_list()
        assert "hvac_air_flow_power" not in features
        assert "hvac_air_flow_direction" not in features

    def test_current_state_online_bool_present(self):
        """online BOOL must be present."""
        entity = HvacUnderfloorEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state())
        states = entity.to_sber_current_state()["climate.floor"]["states"]
        _assert_online_bool_present(states)

    def test_current_state_integer_values_are_strings(self):
        """All INTEGER values in underfloor state must be strings."""
        entity = HvacUnderfloorEntity(self.ENTITY_DATA)
        entity.fill_by_ha_state(self._make_ha_state())
        states = entity.to_sber_current_state()["climate.floor"]["states"]
        _assert_all_integer_values_are_strings(states)


# ---------------------------------------------------------------------------
#  Cross-device compliance: to_sber_state structure validation
# ---------------------------------------------------------------------------


class TestCrossDeviceSberStateStructure:
    """Verify to_sber_state() structure across all device classes."""

    @pytest.mark.parametrize(
        "entity_cls,entity_data,ha_state",
        [
            (RelayEntity, {"entity_id": "switch.r", "name": "R"}, {"entity_id": "switch.r", "state": "on", "attributes": {}}),
            (SocketEntity, {"entity_id": "switch.s", "name": "S"}, {"entity_id": "switch.s", "state": "on", "attributes": {}}),
            (ValveEntity, {"entity_id": "valve.v", "name": "V"}, {"entity_id": "valve.v", "state": "open", "attributes": {}}),
            (VacuumCleanerEntity, {"entity_id": "vacuum.vc", "name": "VC"}, {"entity_id": "vacuum.vc", "state": "docked", "attributes": {}}),
            (KettleEntity, {"entity_id": "water_heater.k", "name": "K"}, {"entity_id": "water_heater.k", "state": "idle", "attributes": {}}),
            (IntercomEntity, {"entity_id": "switch.i", "name": "I"}, {"entity_id": "switch.i", "state": "on", "attributes": {}}),
            (ScenarioButtonEntity, {"entity_id": "input_boolean.sb", "name": "SB"}, {"entity_id": "input_boolean.sb", "state": "on", "attributes": {}}),
            (HvacRadiatorEntity, {"entity_id": "climate.rad", "name": "Rad"}, {"entity_id": "climate.rad", "state": "heat", "attributes": {"current_temperature": 22, "temperature": 30}}),
            (HvacHeaterEntity, {"entity_id": "climate.ht", "name": "Ht"}, {"entity_id": "climate.ht", "state": "heat", "attributes": {"current_temperature": 20, "temperature": 25}}),
            (HvacBoilerEntity, {"entity_id": "climate.bl", "name": "Bl"}, {"entity_id": "climate.bl", "state": "heat", "attributes": {"current_temperature": 55, "temperature": 65}}),
            (HvacUnderfloorEntity, {"entity_id": "climate.uf", "name": "UF"}, {"entity_id": "climate.uf", "state": "heat", "attributes": {"current_temperature": 28, "temperature": 35}}),
        ],
        ids=[
            "relay", "socket", "valve", "vacuum", "kettle",
            "intercom", "scenario_button", "hvac_radiator",
            "hvac_heater", "hvac_boiler", "hvac_underfloor",
        ],
    )
    def test_sber_state_has_required_keys(self, entity_cls, entity_data, ha_state):
        """Every device class must produce valid to_sber_state() with required keys."""
        entity = entity_cls(entity_data)
        entity.fill_by_ha_state(ha_state)
        result = entity.to_sber_state()
        _assert_sber_state_structure(result)

    @pytest.mark.parametrize(
        "entity_cls,entity_data,ha_state",
        [
            (RelayEntity, {"entity_id": "switch.r", "name": "R"}, {"entity_id": "switch.r", "state": "on", "attributes": {}}),
            (SocketEntity, {"entity_id": "switch.s", "name": "S"}, {"entity_id": "switch.s", "state": "on", "attributes": {}}),
            (ValveEntity, {"entity_id": "valve.v", "name": "V"}, {"entity_id": "valve.v", "state": "open", "attributes": {}}),
            (VacuumCleanerEntity, {"entity_id": "vacuum.vc", "name": "VC"}, {"entity_id": "vacuum.vc", "state": "docked", "attributes": {}}),
            (KettleEntity, {"entity_id": "water_heater.k", "name": "K"}, {"entity_id": "water_heater.k", "state": "idle", "attributes": {}}),
            (IntercomEntity, {"entity_id": "switch.i", "name": "I"}, {"entity_id": "switch.i", "state": "on", "attributes": {}}),
            (ScenarioButtonEntity, {"entity_id": "input_boolean.sb", "name": "SB"}, {"entity_id": "input_boolean.sb", "state": "on", "attributes": {}}),
            (HvacRadiatorEntity, {"entity_id": "climate.rad", "name": "Rad"}, {"entity_id": "climate.rad", "state": "heat", "attributes": {"current_temperature": 22, "temperature": 30}}),
            (HvacHeaterEntity, {"entity_id": "climate.ht", "name": "Ht"}, {"entity_id": "climate.ht", "state": "heat", "attributes": {"current_temperature": 20, "temperature": 25}}),
            (HvacBoilerEntity, {"entity_id": "climate.bl", "name": "Bl"}, {"entity_id": "climate.bl", "state": "heat", "attributes": {"current_temperature": 55, "temperature": 65}}),
            (HvacUnderfloorEntity, {"entity_id": "climate.uf", "name": "UF"}, {"entity_id": "climate.uf", "state": "heat", "attributes": {"current_temperature": 28, "temperature": 35}}),
        ],
        ids=[
            "relay", "socket", "valve", "vacuum", "kettle",
            "intercom", "scenario_button", "hvac_radiator",
            "hvac_heater", "hvac_boiler", "hvac_underfloor",
        ],
    )
    def test_current_state_online_bool_present(self, entity_cls, entity_data, ha_state):
        """Every device class must include online BOOL in current state."""
        entity = entity_cls(entity_data)
        entity.fill_by_ha_state(ha_state)
        result = entity.to_sber_current_state()
        entity_id = entity_data["entity_id"]
        states = result[entity_id]["states"]
        _assert_online_bool_present(states)

    @pytest.mark.parametrize(
        "entity_cls,entity_data,ha_state",
        [
            (RelayEntity, {"entity_id": "switch.r", "name": "R"}, {"entity_id": "switch.r", "state": "on", "attributes": {"power": 100, "voltage": 220, "current": 1}}),
            (SocketEntity, {"entity_id": "switch.s", "name": "S"}, {"entity_id": "switch.s", "state": "on", "attributes": {"power": 50}}),
            (ValveEntity, {"entity_id": "valve.v", "name": "V"}, {"entity_id": "valve.v", "state": "open", "attributes": {"battery": 90}}),
            (VacuumCleanerEntity, {"entity_id": "vacuum.vc", "name": "VC"}, {"entity_id": "vacuum.vc", "state": "docked", "attributes": {"battery_level": 80}}),
            (KettleEntity, {"entity_id": "water_heater.k", "name": "K"}, {"entity_id": "water_heater.k", "state": "heating", "attributes": {"current_temperature": 75, "temperature": 100}}),
            (HvacRadiatorEntity, {"entity_id": "climate.rad", "name": "Rad"}, {"entity_id": "climate.rad", "state": "heat", "attributes": {"current_temperature": 22, "temperature": 30}}),
        ],
        ids=["relay", "socket", "valve", "vacuum", "kettle", "hvac_radiator"],
    )
    def test_all_integer_values_are_strings(self, entity_cls, entity_data, ha_state):
        """All INTEGER values in any device current state must be strings."""
        entity = entity_cls(entity_data)
        entity.fill_by_ha_state(ha_state)
        result = entity.to_sber_current_state()
        entity_id = entity_data["entity_id"]
        states = result[entity_id]["states"]
        _assert_all_integer_values_are_strings(states)

    @pytest.mark.parametrize(
        "entity_cls,entity_data,ha_state",
        [
            (RelayEntity, {"entity_id": "switch.r", "name": "R"}, {"entity_id": "switch.r", "state": "unavailable", "attributes": {}}),
            (SocketEntity, {"entity_id": "switch.s", "name": "S"}, {"entity_id": "switch.s", "state": "unavailable", "attributes": {}}),
            (ValveEntity, {"entity_id": "valve.v", "name": "V"}, {"entity_id": "valve.v", "state": "unavailable", "attributes": {}}),
            (VacuumCleanerEntity, {"entity_id": "vacuum.vc", "name": "VC"}, {"entity_id": "vacuum.vc", "state": "unavailable", "attributes": {}}),
            (KettleEntity, {"entity_id": "water_heater.k", "name": "K"}, {"entity_id": "water_heater.k", "state": "unavailable", "attributes": {}}),
            (IntercomEntity, {"entity_id": "switch.i", "name": "I"}, {"entity_id": "switch.i", "state": "unavailable", "attributes": {}}),
            (ScenarioButtonEntity, {"entity_id": "input_boolean.sb", "name": "SB"}, {"entity_id": "input_boolean.sb", "state": "unavailable", "attributes": {}}),
        ],
        ids=["relay", "socket", "valve", "vacuum", "kettle", "intercom", "scenario_button"],
    )
    def test_unavailable_sets_online_false(self, entity_cls, entity_data, ha_state):
        """HA 'unavailable' must set online=False for every device class."""
        entity = entity_cls(entity_data)
        entity.fill_by_ha_state(ha_state)
        result = entity.to_sber_current_state()
        entity_id = entity_data["entity_id"]
        states = result[entity_id]["states"]
        online = _find_state(states, "online")
        assert online["value"]["bool_value"] is False
