"""Sber C2C protocol compliance tests for ENUM values produced by device classes.

Validates that ALL enum values produced by our device classes match the
Sber C2C documentation exactly. Each test creates an entity, sets state
to trigger the specific enum, and verifies the output value matches the
documented value set.

Sber documentation reference:
    https://developers.sber.ru/docs/ru/smarthome/c2c/
"""

from __future__ import annotations

import pytest

from custom_components.sber_mqtt_bridge.devices.climate import (
    ClimateEntity,
    HA_TO_SBER_FAN_MODE,
    HA_TO_SBER_SWING,
    HA_TO_SBER_WORK_MODE,
)
from custom_components.sber_mqtt_bridge.devices.curtain import CurtainEntity
from custom_components.sber_mqtt_bridge.devices.light import LightEntity
from custom_components.sber_mqtt_bridge.devices.motion_sensor import MotionSensorEntity
from custom_components.sber_mqtt_bridge.devices.scenario_button import (
    ScenarioButtonEntity,
)
from custom_components.sber_mqtt_bridge.devices.sensor_temp import SensorTempEntity
from custom_components.sber_mqtt_bridge.devices.simple_sensor import (
    SimpleReadOnlySensor,
)
from custom_components.sber_mqtt_bridge.devices.tv import TvEntity
from custom_components.sber_mqtt_bridge.devices.utils.signal import (
    rssi_to_signal_strength,
)
from custom_components.sber_mqtt_bridge.devices.vacuum_cleaner import (
    VacuumCleanerEntity,
    _HA_STATE_TO_SBER_STATUS,
)


# ---------------------------------------------------------------------------
# Documented Sber C2C enum value sets
# ---------------------------------------------------------------------------

SBER_HVAC_AIR_FLOW_DIRECTION = {"auto", "horizontal", "no", "rotation", "swing", "vertical"}
"""Sber docs: hvac_air_flow_direction allowed values."""

SBER_VACUUM_CLEANER_STATUS = {"cleaning", "charging", "standby", "go_home", "error"}
"""Sber docs: vacuum_cleaner_status allowed values."""

SBER_DIRECTION = {"up", "down", "left", "right", "ok"}
"""Sber docs: direction allowed values for TV remote."""

SBER_SIGNAL_STRENGTH = {"low", "medium", "high"}
"""Sber docs: signal_strength allowed values."""

SBER_SENSOR_SENSITIVE = {"auto", "high", "low"}
"""Sber docs: sensor_sensitive allowed values."""

SBER_BUTTON_EVENT = {"click", "double_click", "long_press"}
"""Sber docs: button_event allowed values (HA input_boolean can only produce click/double_click)."""

SBER_TEMP_UNIT_VIEW = {"c", "f"}
"""Sber docs: temp_unit_view allowed values."""

SBER_OPEN_STATE = {"open", "close", "opening", "closing"}
"""Sber docs: open_state allowed values."""

SBER_HVAC_WORK_MODE = {"cooling", "heating", "ventilation", "dehumidification", "auto", "eco", "turbo", "quiet"}
"""Sber docs: hvac_work_mode allowed values."""

SBER_LIGHT_MODE = {"white", "colour"}
"""Sber docs: light_mode allowed values."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entity_data(entity_id: str) -> dict:
    """Build minimal HA entity registry dict for testing."""
    return {
        "entity_id": entity_id,
        "area_id": "living_room",
        "name": "Test Entity",
        "original_name": "Test Entity",
        "device_id": "test_device_001",
        "platform": "test",
    }


def _find_state(states: list[dict], key: str) -> dict | None:
    """Find a state entry by key in the Sber states list."""
    for s in states:
        if s.get("key") == key:
            return s
    return None


def _get_states(entity, entity_id: str) -> list[dict]:
    """Extract states list from to_sber_current_state for the given entity_id."""
    result = entity.to_sber_current_state()
    assert entity_id in result, f"entity_id {entity_id} not in result keys"
    return result[entity_id]["states"]


def _get_enum_value(states: list[dict], key: str) -> str | None:
    """Extract enum_value from a state entry by key."""
    entry = _find_state(states, key)
    if entry is None:
        return None
    value = entry.get("value", {})
    if value.get("type") != "ENUM":
        return None
    return value.get("enum_value")


# ===========================================================================
# 1. hvac_air_flow_direction (climate.py) — HA_TO_SBER_SWING mapping
# ===========================================================================


class TestHvacAirFlowDirection:
    """Verify HA_TO_SBER_SWING maps only to documented Sber direction values."""

    def test_all_mapped_values_are_documented(self):
        """Every value in HA_TO_SBER_SWING must be in Sber documented set."""
        for ha_mode, sber_mode in HA_TO_SBER_SWING.items():
            assert sber_mode in SBER_HVAC_AIR_FLOW_DIRECTION, (
                f"HA swing mode '{ha_mode}' maps to '{sber_mode}' which is NOT "
                f"in Sber docs: {SBER_HVAC_AIR_FLOW_DIRECTION}"
            )

    def test_no_extra_undocumented_values(self):
        """The set of mapped values is a subset of the documented set."""
        produced = set(HA_TO_SBER_SWING.values())
        undocumented = produced - SBER_HVAC_AIR_FLOW_DIRECTION
        assert not undocumented, f"Undocumented hvac_air_flow_direction values: {undocumented}"

    @pytest.mark.parametrize(
        "ha_swing,expected_sber",
        [
            ("off", "no"),
            ("vertical", "vertical"),
            ("horizontal", "horizontal"),
            ("both", "rotation"),
            ("swing", "swing"),
            ("auto", "auto"),
        ],
    )
    def test_swing_mapping_individual_values(self, ha_swing: str, expected_sber: str):
        """Each HA swing mode maps to the correct documented Sber value."""
        assert HA_TO_SBER_SWING[ha_swing] == expected_sber

    def test_entity_produces_documented_swing_in_state(self):
        """ClimateEntity.to_sber_current_state produces documented direction value."""
        entity_id = "climate.test_ac"
        entity = ClimateEntity(_make_entity_data(entity_id))
        entity.fill_by_ha_state(
            {
                "state": "cool",
                "attributes": {
                    "swing_modes": ["off", "vertical", "horizontal", "both"],
                    "swing_mode": "vertical",
                    "fan_modes": ["auto"],
                    "fan_mode": "auto",
                    "hvac_modes": ["cool", "heat", "off"],
                },
            }
        )
        states = _get_states(entity, entity_id)
        direction_val = _get_enum_value(states, "hvac_air_flow_direction")
        assert direction_val is not None, "hvac_air_flow_direction not found in state"
        assert direction_val in SBER_HVAC_AIR_FLOW_DIRECTION, (
            f"Produced '{direction_val}' not in docs: {SBER_HVAC_AIR_FLOW_DIRECTION}"
        )


# ===========================================================================
# 2. vacuum_cleaner_status (vacuum_cleaner.py)
# ===========================================================================


class TestVacuumCleanerStatus:
    """Verify _HA_STATE_TO_SBER_STATUS maps to documented Sber values."""

    def test_all_mapped_values_are_documented(self):
        """Every Sber status value must be in the documented set."""
        non_compliant = {}
        for ha_state, sber_status in _HA_STATE_TO_SBER_STATUS.items():
            if sber_status not in SBER_VACUUM_CLEANER_STATUS:
                non_compliant[ha_state] = sber_status
        assert not non_compliant, (
            f"Non-compliant HA→Sber status mappings: {non_compliant}. Documented values: {SBER_VACUUM_CLEANER_STATUS}"
        )

    def test_cleaning_status_is_documented(self):
        """'cleaning' is a valid Sber vacuum_cleaner_status."""
        assert _HA_STATE_TO_SBER_STATUS["cleaning"] == "cleaning"
        assert "cleaning" in SBER_VACUUM_CLEANER_STATUS

    def test_error_status_is_documented(self):
        """'error' is a valid Sber vacuum_cleaner_status."""
        assert _HA_STATE_TO_SBER_STATUS["error"] == "error"
        assert "error" in SBER_VACUUM_CLEANER_STATUS

    def test_returning_maps_to_go_home(self):
        """HA 'returning' must map to Sber 'go_home'."""
        sber_val = _HA_STATE_TO_SBER_STATUS.get("returning")
        assert sber_val == "go_home"
        assert sber_val in SBER_VACUUM_CLEANER_STATUS

    def test_docked_maps_to_standby(self):
        """HA 'docked' must map to Sber 'standby'."""
        sber_val = _HA_STATE_TO_SBER_STATUS.get("docked")
        assert sber_val == "standby"
        assert sber_val in SBER_VACUUM_CLEANER_STATUS

    def test_entity_produces_status_in_state(self):
        """VacuumCleanerEntity.to_sber_current_state produces a status value."""
        entity_id = "vacuum.robot"
        entity = VacuumCleanerEntity(_make_entity_data(entity_id))
        entity.fill_by_ha_state(
            {
                "state": "cleaning",
                "attributes": {"battery_level": 80},
            }
        )
        states = _get_states(entity, entity_id)
        status = _get_enum_value(states, "vacuum_cleaner_status")
        assert status is not None, "vacuum_cleaner_status not found in state"

    def test_unknown_ha_state_defaults_to_standby(self):
        """Unknown HA state defaults to 'standby' (Sber-documented fallback)."""
        entity_id = "vacuum.robot"
        entity = VacuumCleanerEntity(_make_entity_data(entity_id))
        entity.fill_by_ha_state(
            {
                "state": "totally_unknown_state",
                "attributes": {},
            }
        )
        states = _get_states(entity, entity_id)
        status = _get_enum_value(states, "vacuum_cleaner_status")
        assert status == "standby"


# ===========================================================================
# 3. direction (tv.py) — command processing
# ===========================================================================


class TestTvDirection:
    """Verify TvEntity.process_cmd handles Sber direction commands."""

    @staticmethod
    def _build_direction_cmd(direction: str) -> dict:
        """Build a Sber command with a direction ENUM value."""
        return {
            "states": [
                {
                    "key": "direction",
                    "value": {"type": "ENUM", "enum_value": direction},
                }
            ]
        }

    def test_up_direction_produces_service_call(self):
        """Sber direction='up' produces media_player.volume_up."""
        entity_id = "media_player.tv"
        entity = TvEntity(_make_entity_data(entity_id))
        result = entity.process_cmd(self._build_direction_cmd("up"))
        assert len(result) == 1
        assert result[0]["url"]["service"] == "volume_up"

    def test_down_direction_produces_service_call(self):
        """Sber direction='down' produces media_player.volume_down."""
        entity_id = "media_player.tv"
        entity = TvEntity(_make_entity_data(entity_id))
        result = entity.process_cmd(self._build_direction_cmd("down"))
        assert len(result) == 1
        assert result[0]["url"]["service"] == "volume_down"

    def test_left_direction_not_handled(self):
        """Sber direction='left' is NOT handled -- compliance gap.

        Sber docs include 'left' in direction values, but the current
        implementation only maps 'up' and 'down'. This test documents the gap.
        """
        entity_id = "media_player.tv"
        entity = TvEntity(_make_entity_data(entity_id))
        result = entity.process_cmd(self._build_direction_cmd("left"))
        if not result:
            pytest.skip(
                "COMPLIANCE GAP: direction='left' not handled. Sber docs define it but no HA service mapping exists."
            )

    def test_right_direction_handled(self):
        """Sber direction='right' must produce a service call."""
        entity_id = "media_player.tv"
        entity = TvEntity(_make_entity_data(entity_id))
        result = entity.process_cmd(self._build_direction_cmd("right"))
        assert result, "direction='right' must be handled"

    def test_ok_direction_handled(self):
        """Sber direction='ok' must produce a service call."""
        entity_id = "media_player.tv"
        entity = TvEntity(_make_entity_data(entity_id))
        result = entity.process_cmd(self._build_direction_cmd("ok"))
        assert result, "direction='ok' must be handled"

    def test_all_directions_handled(self):
        """All 5 Sber direction values must be handled."""
        entity_id = "media_player.tv"
        entity = TvEntity(_make_entity_data(entity_id))
        for d in SBER_DIRECTION:
            result = entity.process_cmd(self._build_direction_cmd(d))
            assert result, f"direction='{d}' must be handled"


# ===========================================================================
# 4. signal_strength (utils/signal.py)
# ===========================================================================


class TestSignalStrength:
    """Verify rssi_to_signal_strength produces only documented Sber values."""

    @pytest.mark.parametrize(
        "rssi,expected",
        [
            (-30, "high"),
            (-49, "high"),
            (-50, "medium"),
            (-51, "medium"),
            (-69, "medium"),
            (-70, "low"),
            (-71, "low"),
            (-100, "low"),
        ],
    )
    def test_rssi_mapping(self, rssi: int, expected: str):
        """RSSI value maps to the correct Sber signal_strength."""
        result = rssi_to_signal_strength(rssi)
        assert result == expected

    @pytest.mark.parametrize("rssi", [-120, -100, -70, -69, -50, -49, -30, 0, 10, 100])
    def test_all_outputs_are_documented(self, rssi: int):
        """Every possible output must be in the documented set."""
        result = rssi_to_signal_strength(rssi)
        assert result in SBER_SIGNAL_STRENGTH, f"RSSI={rssi} produced '{result}' not in docs: {SBER_SIGNAL_STRENGTH}"

    def test_boundary_minus_50(self):
        """RSSI=-50 is the boundary between high and medium."""
        assert rssi_to_signal_strength(-50) == "medium"

    def test_boundary_minus_70(self):
        """RSSI=-70 is the boundary between medium and low."""
        assert rssi_to_signal_strength(-70) == "low"

    def test_no_undocumented_values_across_range(self):
        """Sweep RSSI range -120..+20 and verify all outputs are documented."""
        produced = set()
        for rssi in range(-120, 21):
            produced.add(rssi_to_signal_strength(rssi))
        undocumented = produced - SBER_SIGNAL_STRENGTH
        assert not undocumented, f"Undocumented signal_strength values: {undocumented}"


# ===========================================================================
# 5. sensor_sensitive (simple_sensor.py)
# ===========================================================================


class TestSensorSensitive:
    """Verify sensor_sensitive values match Sber docs: auto, high, low."""

    @pytest.mark.parametrize(
        "sensitivity_input,expected_sber",
        [
            ("auto", "auto"),
            ("high", "high"),
            ("low", "low"),
            ("medium", "auto"),
            ("Auto", "auto"),
            ("HIGH", "high"),
            ("Low", "low"),
            ("Medium", "auto"),
        ],
    )
    def test_sensitivity_mapping(self, sensitivity_input: str, expected_sber: str):
        """HA sensitivity attribute maps to the correct Sber sensor_sensitive value."""
        entity_id = "binary_sensor.motion"
        entity = MotionSensorEntity(_make_entity_data(entity_id))
        entity.fill_by_ha_state(
            {
                "state": "off",
                "attributes": {"sensitivity": sensitivity_input},
            }
        )
        states = _get_states(entity, entity_id)
        actual = _get_enum_value(states, "sensor_sensitive")
        assert actual == expected_sber
        assert expected_sber in SBER_SENSOR_SENSITIVE

    @pytest.mark.parametrize("invalid_value", ["very_high", "super_low", "123", "none", ""])
    def test_invalid_sensitivity_not_in_state(self, invalid_value: str):
        """Invalid sensitivity values must not produce sensor_sensitive in state."""
        entity_id = "binary_sensor.motion"
        entity = MotionSensorEntity(_make_entity_data(entity_id))
        entity.fill_by_ha_state(
            {
                "state": "off",
                "attributes": {"sensitivity": invalid_value},
            }
        )
        states = _get_states(entity, entity_id)
        assert _get_enum_value(states, "sensor_sensitive") is None

    def test_no_sensitivity_attribute_not_in_state(self):
        """Missing sensitivity attribute must not produce sensor_sensitive in state."""
        entity_id = "binary_sensor.motion"
        entity = MotionSensorEntity(_make_entity_data(entity_id))
        entity.fill_by_ha_state(
            {
                "state": "off",
                "attributes": {},
            }
        )
        states = _get_states(entity, entity_id)
        assert _get_enum_value(states, "sensor_sensitive") is None

    def test_motion_sensitivity_attribute_also_works(self):
        """The 'motion_sensitivity' HA attribute is also recognized."""
        entity_id = "binary_sensor.motion"
        entity = MotionSensorEntity(_make_entity_data(entity_id))
        entity.fill_by_ha_state(
            {
                "state": "off",
                "attributes": {"motion_sensitivity": "high"},
            }
        )
        states = _get_states(entity, entity_id)
        assert _get_enum_value(states, "sensor_sensitive") == "high"

    def test_all_produced_values_are_documented(self):
        """Sweep known inputs and verify only documented values are produced."""
        entity_id = "binary_sensor.motion"
        produced = set()
        for val in ("auto", "high", "low", "medium", "Auto", "HIGH", "LOW", "Medium"):
            entity = MotionSensorEntity(_make_entity_data(entity_id))
            entity.fill_by_ha_state(
                {
                    "state": "off",
                    "attributes": {"sensitivity": val},
                }
            )
            if entity._sensor_sensitive is not None:
                produced.add(entity._sensor_sensitive)
        undocumented = produced - SBER_SENSOR_SENSITIVE
        assert not undocumented, f"Undocumented sensor_sensitive values: {undocumented}"


# ===========================================================================
# 6. button_event (scenario_button.py)
# ===========================================================================


class TestButtonEvent:
    """Verify button_event values match Sber docs: click, double_click, long_press."""

    def test_on_state_produces_click(self):
        """HA state 'on' maps to button_event='click'."""
        entity_id = "input_boolean.test"
        entity = ScenarioButtonEntity(_make_entity_data(entity_id))
        entity.fill_by_ha_state({"state": "on", "attributes": {}})
        states = _get_states(entity, entity_id)
        event = _get_enum_value(states, "button_event")
        assert event == "click"
        assert event in SBER_BUTTON_EVENT

    def test_off_state_produces_double_click(self):
        """HA state 'off' maps to button_event='double_click'."""
        entity_id = "input_boolean.test"
        entity = ScenarioButtonEntity(_make_entity_data(entity_id))
        entity.fill_by_ha_state({"state": "off", "attributes": {}})
        states = _get_states(entity, entity_id)
        event = _get_enum_value(states, "button_event")
        assert event == "double_click"
        assert event in SBER_BUTTON_EVENT

    def test_allowed_values_list_matches_docs(self):
        """create_allowed_values_list returns exactly the documented button_event set."""
        entity_id = "input_boolean.test"
        entity = ScenarioButtonEntity(_make_entity_data(entity_id))
        allowed = entity.create_allowed_values_list()
        assert "button_event" in allowed
        enum_values = set(allowed["button_event"]["enum_values"]["values"])
        assert enum_values == SBER_BUTTON_EVENT, (
            f"Allowed button_event values {enum_values} != docs {SBER_BUTTON_EVENT}"
        )

    def test_all_produced_values_are_documented(self):
        """Both possible state outputs must be in the documented set."""
        entity_id = "input_boolean.test"
        produced = set()
        for state in ("on", "off"):
            entity = ScenarioButtonEntity(_make_entity_data(entity_id))
            entity.fill_by_ha_state({"state": state, "attributes": {}})
            states = _get_states(entity, entity_id)
            event = _get_enum_value(states, "button_event")
            if event:
                produced.add(event)
        undocumented = produced - SBER_BUTTON_EVENT
        assert not undocumented, f"Undocumented button_event values: {undocumented}"

    def test_long_press_in_allowed_values(self):
        """'long_press' must be in allowed_values for scenario button."""
        entity_id = "input_boolean.test"
        entity = ScenarioButtonEntity(_make_entity_data(entity_id))
        allowed = entity.create_allowed_values_list()
        enum_values = set(allowed["button_event"]["enum_values"]["values"])
        assert "long_press" in enum_values, "long_press should be in allowed_values for scenario button"


# ===========================================================================
# 7. temp_unit_view (sensor_temp.py)
# ===========================================================================


class TestTempUnitView:
    """Verify temp_unit_view values match Sber docs: c, f."""

    def test_celsius_unit(self):
        """HA unit '°C' maps to temp_unit_view='c'."""
        entity_id = "sensor.temperature"
        entity = SensorTempEntity(_make_entity_data(entity_id))
        entity.fill_by_ha_state(
            {
                "state": "22.5",
                "attributes": {"unit_of_measurement": "°C"},
            }
        )
        states = _get_states(entity, entity_id)
        unit = _get_enum_value(states, "temp_unit_view")
        assert unit == "c"
        assert unit in SBER_TEMP_UNIT_VIEW

    def test_fahrenheit_unit(self):
        """HA unit '°F' maps to temp_unit_view='f'."""
        entity_id = "sensor.temperature"
        entity = SensorTempEntity(_make_entity_data(entity_id))
        entity.fill_by_ha_state(
            {
                "state": "72.5",
                "attributes": {"unit_of_measurement": "°F"},
            }
        )
        states = _get_states(entity, entity_id)
        unit = _get_enum_value(states, "temp_unit_view")
        assert unit == "f"
        assert unit in SBER_TEMP_UNIT_VIEW

    def test_no_unit_defaults_to_celsius(self):
        """Missing unit_of_measurement defaults to 'c'."""
        entity_id = "sensor.temperature"
        entity = SensorTempEntity(_make_entity_data(entity_id))
        entity.fill_by_ha_state(
            {
                "state": "22.5",
                "attributes": {},
            }
        )
        states = _get_states(entity, entity_id)
        unit = _get_enum_value(states, "temp_unit_view")
        assert unit == "c"

    @pytest.mark.parametrize(
        "ha_unit,expected",
        [
            ("°C", "c"),
            ("°F", "f"),
            ("", "c"),
            ("K", "c"),
        ],
    )
    def test_all_outputs_are_documented(self, ha_unit: str, expected: str):
        """Every possible output must be in the documented set."""
        entity_id = "sensor.temperature"
        entity = SensorTempEntity(_make_entity_data(entity_id))
        entity.fill_by_ha_state(
            {
                "state": "22.5",
                "attributes": {"unit_of_measurement": ha_unit},
            }
        )
        states = _get_states(entity, entity_id)
        unit = _get_enum_value(states, "temp_unit_view")
        assert unit in SBER_TEMP_UNIT_VIEW, f"HA unit '{ha_unit}' produced '{unit}' not in docs: {SBER_TEMP_UNIT_VIEW}"
        assert unit == expected


# ===========================================================================
# 8. open_state (curtain.py)
# ===========================================================================


class TestOpenState:
    """Verify open_state values match Sber docs: open, close, opening, closing."""

    @pytest.mark.parametrize(
        "ha_state,position,expected_sber",
        [
            ("open", 100, "open"),
            ("closed", 0, "close"),
            ("opening", 50, "opening"),
            ("closing", 50, "closing"),
        ],
    )
    def test_state_mapping(self, ha_state: str, position: int, expected_sber: str):
        """Each HA cover state maps to the correct documented Sber open_state."""
        entity_id = "cover.curtain"
        entity = CurtainEntity(_make_entity_data(entity_id))
        entity.fill_by_ha_state(
            {
                "state": ha_state,
                "attributes": {"current_position": position},
            }
        )
        states = _get_states(entity, entity_id)
        open_state = _get_enum_value(states, "open_state")
        assert open_state == expected_sber
        assert open_state in SBER_OPEN_STATE

    def test_closed_state_maps_to_close_not_closed(self):
        """HA 'closed' must map to Sber 'close', NOT 'closed'."""
        entity_id = "cover.curtain"
        entity = CurtainEntity(_make_entity_data(entity_id))
        entity.fill_by_ha_state(
            {
                "state": "closed",
                "attributes": {"current_position": 0},
            }
        )
        states = _get_states(entity, entity_id)
        open_state = _get_enum_value(states, "open_state")
        assert open_state == "close", f"Expected 'close' for HA 'closed', got '{open_state}'"

    def test_position_zero_forces_close(self):
        """When position is 0 and state is not opening/closing, force 'close'."""
        entity_id = "cover.curtain"
        entity = CurtainEntity(_make_entity_data(entity_id))
        entity.fill_by_ha_state(
            {
                "state": "open",
                "attributes": {"current_position": 0},
            }
        )
        states = _get_states(entity, entity_id)
        open_state = _get_enum_value(states, "open_state")
        assert open_state == "close"

    def test_position_nonzero_forces_open(self):
        """When position > 0 and state is not opening/closing, force 'open'."""
        entity_id = "cover.curtain"
        entity = CurtainEntity(_make_entity_data(entity_id))
        entity.fill_by_ha_state(
            {
                "state": "closed",
                "attributes": {"current_position": 50},
            }
        )
        states = _get_states(entity, entity_id)
        open_state = _get_enum_value(states, "open_state")
        assert open_state == "open"

    def test_no_undocumented_values_produced(self):
        """Sweep all HA cover states and verify only documented values are produced."""
        entity_id = "cover.curtain"
        produced = set()
        test_cases = [
            ("open", 100),
            ("closed", 0),
            ("opening", 50),
            ("closing", 50),
            ("open", 0),
            ("closed", 50),
            ("unknown_state", 50),
        ]
        for ha_state, pos in test_cases:
            entity = CurtainEntity(_make_entity_data(entity_id))
            entity.fill_by_ha_state(
                {
                    "state": ha_state,
                    "attributes": {"current_position": pos},
                }
            )
            states = _get_states(entity, entity_id)
            val = _get_enum_value(states, "open_state")
            if val:
                produced.add(val)
        undocumented = produced - SBER_OPEN_STATE
        assert not undocumented, f"Undocumented open_state values: {undocumented}"


# ===========================================================================
# 9. hvac_work_mode (climate.py)
# ===========================================================================


class TestHvacWorkMode:
    """Verify HA_TO_SBER_WORK_MODE maps only to documented Sber values."""

    def test_all_mapped_values_are_documented(self):
        """Every value in HA_TO_SBER_WORK_MODE must be in Sber documented set."""
        for ha_mode, sber_mode in HA_TO_SBER_WORK_MODE.items():
            assert sber_mode in SBER_HVAC_WORK_MODE, (
                f"HA hvac_mode '{ha_mode}' maps to '{sber_mode}' which is NOT in Sber docs: {SBER_HVAC_WORK_MODE}"
            )

    def test_no_extra_undocumented_values(self):
        """The set of mapped values is a subset of the documented set."""
        produced = set(HA_TO_SBER_WORK_MODE.values())
        undocumented = produced - SBER_HVAC_WORK_MODE
        assert not undocumented, f"Undocumented hvac_work_mode values: {undocumented}"

    @pytest.mark.parametrize(
        "ha_mode,expected_sber",
        [
            ("cool", "cooling"),
            ("heat", "heating"),
            ("dry", "dehumidification"),
            ("fan_only", "ventilation"),
            ("heat_cool", "auto"),
            ("auto", "auto"),
            ("eco", "eco"),
        ],
    )
    def test_work_mode_mapping_individual_values(self, ha_mode: str, expected_sber: str):
        """Each HA HVAC mode maps to the correct documented Sber value."""
        assert HA_TO_SBER_WORK_MODE[ha_mode] == expected_sber

    def test_entity_produces_documented_work_mode_in_state(self):
        """ClimateEntity.to_sber_current_state produces documented work_mode value."""
        entity_id = "climate.test_ac"
        entity = ClimateEntity(_make_entity_data(entity_id))
        entity.fill_by_ha_state(
            {
                "state": "cool",
                "attributes": {
                    "hvac_modes": ["cool", "heat", "dry", "fan_only", "auto", "off"],
                    "fan_modes": ["auto"],
                    "fan_mode": "auto",
                },
            }
        )
        states = _get_states(entity, entity_id)
        work_mode = _get_enum_value(states, "hvac_work_mode")
        assert work_mode is not None, "hvac_work_mode not found in state"
        assert work_mode in SBER_HVAC_WORK_MODE, f"Produced '{work_mode}' not in docs: {SBER_HVAC_WORK_MODE}"

    def test_preset_boost_produces_turbo(self):
        """HA preset_mode='boost' produces hvac_work_mode='turbo'."""
        entity_id = "climate.test_ac"
        entity = ClimateEntity(_make_entity_data(entity_id))
        entity.fill_by_ha_state(
            {
                "state": "cool",
                "attributes": {
                    "hvac_modes": ["cool", "heat", "off"],
                    "preset_mode": "boost",
                    "preset_modes": ["boost", "sleep"],
                },
            }
        )
        states = _get_states(entity, entity_id)
        work_mode = _get_enum_value(states, "hvac_work_mode")
        assert work_mode == "turbo"
        assert work_mode in SBER_HVAC_WORK_MODE

    def test_preset_sleep_produces_quiet(self):
        """HA preset_mode='sleep' produces hvac_work_mode='quiet'."""
        entity_id = "climate.test_ac"
        entity = ClimateEntity(_make_entity_data(entity_id))
        entity.fill_by_ha_state(
            {
                "state": "heat",
                "attributes": {
                    "hvac_modes": ["cool", "heat", "off"],
                    "preset_mode": "sleep",
                    "preset_modes": ["boost", "sleep"],
                },
            }
        )
        states = _get_states(entity, entity_id)
        work_mode = _get_enum_value(states, "hvac_work_mode")
        assert work_mode == "quiet"
        assert work_mode in SBER_HVAC_WORK_MODE

    def test_off_mode_does_not_produce_work_mode(self):
        """HA hvac_mode='off' should NOT produce hvac_work_mode state."""
        entity_id = "climate.test_ac"
        entity = ClimateEntity(_make_entity_data(entity_id))
        entity.fill_by_ha_state(
            {
                "state": "off",
                "attributes": {
                    "hvac_modes": ["cool", "heat", "off"],
                },
            }
        )
        states = _get_states(entity, entity_id)
        work_mode = _get_enum_value(states, "hvac_work_mode")
        assert work_mode is None, f"hvac_work_mode should not be present when off, got '{work_mode}'"


# ===========================================================================
# 10. light_mode (light.py)
# ===========================================================================


class TestLightMode:
    """Verify light_mode values match Sber docs: white, colour."""

    def test_white_mode_when_color_temp(self):
        """Light with color_temp mode produces light_mode='white'."""
        entity_id = "light.test"
        entity = LightEntity(_make_entity_data(entity_id))
        entity.fill_by_ha_state(
            {
                "state": "on",
                "attributes": {
                    "brightness": 200,
                    "color_mode": "color_temp",
                    "color_temp": 300,
                    "supported_color_modes": ["color_temp", "hs"],
                },
            }
        )
        states = _get_states(entity, entity_id)
        mode = _get_enum_value(states, "light_mode")
        assert mode == "white"
        assert mode in SBER_LIGHT_MODE

    def test_colour_mode_when_hs(self):
        """Light with hs color mode produces light_mode='colour'."""
        entity_id = "light.test"
        entity = LightEntity(_make_entity_data(entity_id))
        entity.fill_by_ha_state(
            {
                "state": "on",
                "attributes": {
                    "brightness": 200,
                    "color_mode": "hs",
                    "hs_color": [180.0, 50.0],
                    "supported_color_modes": ["color_temp", "hs"],
                },
            }
        )
        states = _get_states(entity, entity_id)
        mode = _get_enum_value(states, "light_mode")
        assert mode == "colour"
        assert mode in SBER_LIGHT_MODE

    def test_colour_mode_when_rgb(self):
        """Light with rgb color mode produces light_mode='colour'."""
        entity_id = "light.test"
        entity = LightEntity(_make_entity_data(entity_id))
        entity.fill_by_ha_state(
            {
                "state": "on",
                "attributes": {
                    "brightness": 200,
                    "color_mode": "rgb",
                    "hs_color": [120.0, 100.0],
                    "supported_color_modes": ["color_temp", "rgb"],
                },
            }
        )
        states = _get_states(entity, entity_id)
        mode = _get_enum_value(states, "light_mode")
        assert mode == "colour"
        assert mode in SBER_LIGHT_MODE

    def test_colour_mode_when_xy(self):
        """Light with xy color mode produces light_mode='colour'."""
        entity_id = "light.test"
        entity = LightEntity(_make_entity_data(entity_id))
        entity.fill_by_ha_state(
            {
                "state": "on",
                "attributes": {
                    "brightness": 200,
                    "color_mode": "xy",
                    "hs_color": [60.0, 80.0],
                    "supported_color_modes": ["color_temp", "xy"],
                },
            }
        )
        states = _get_states(entity, entity_id)
        mode = _get_enum_value(states, "light_mode")
        assert mode == "colour"
        assert mode in SBER_LIGHT_MODE

    def test_no_light_mode_when_off(self):
        """Light mode is not included when light is off."""
        entity_id = "light.test"
        entity = LightEntity(_make_entity_data(entity_id))
        entity.fill_by_ha_state(
            {
                "state": "off",
                "attributes": {
                    "brightness": 0,
                    "color_mode": "color_temp",
                    "supported_color_modes": ["color_temp", "hs"],
                },
            }
        )
        states = _get_states(entity, entity_id)
        mode = _get_enum_value(states, "light_mode")
        assert mode is None, f"light_mode should not be present when off, got '{mode}'"

    def test_only_documented_values_produced(self):
        """Sweep color modes and verify only 'white' or 'colour' is produced."""
        entity_id = "light.test"
        produced = set()
        # White mode variants
        for color_mode in ("color_temp", "brightness", "onoff"):
            entity = LightEntity(_make_entity_data(entity_id))
            entity.fill_by_ha_state(
                {
                    "state": "on",
                    "attributes": {
                        "brightness": 200,
                        "color_mode": color_mode,
                        "color_temp": 300,
                        "supported_color_modes": [color_mode],
                    },
                }
            )
            states = _get_states(entity, entity_id)
            mode = _get_enum_value(states, "light_mode")
            if mode:
                produced.add(mode)
        # Colour mode variants
        for color_mode in ("hs", "rgb", "xy", "rgbw", "rgbww"):
            entity = LightEntity(_make_entity_data(entity_id))
            entity.fill_by_ha_state(
                {
                    "state": "on",
                    "attributes": {
                        "brightness": 200,
                        "color_mode": color_mode,
                        "hs_color": [180.0, 50.0],
                        "supported_color_modes": [color_mode],
                    },
                }
            )
            states = _get_states(entity, entity_id)
            mode = _get_enum_value(states, "light_mode")
            if mode:
                produced.add(mode)
        undocumented = produced - SBER_LIGHT_MODE
        assert not undocumented, f"Undocumented light_mode values: {undocumented}"
