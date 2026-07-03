"""Unit tests for SensorAirEntity + Sber air-quality features."""

from __future__ import annotations

import pytest

from custom_components.sber_mqtt_bridge.devices.base_entity import (
    ROLE_CO2, ROLE_HCHO, ROLE_HUMIDITY, ROLE_PM1, ROLE_PM10, ROLE_PM25,
    ROLE_TEMPERATURE, ROLE_TVOC, LinkableRole,
)
from custom_components.sber_mqtt_bridge.devices.sensor_air import (
    SENSOR_AIR_CATEGORY,
    SensorAirEntity,
)
from custom_components.sber_mqtt_bridge.sber_constants import SberFeature


class TestNewAirFeatures:
    """The 2026-05 spec added six air-quality features + two P2 telemetry
    features. Confirm they exist with the exact spec wire spellings."""

    @pytest.mark.parametrize(
        "attr,expected",
        [
            ("CO2", "co2"),
            ("PM1_0", "pm1_0"),
            ("PM2_5", "pm2_5"),
            ("PM10", "pm10"),
            ("TVOC_FLOAT", "tvoc_float"),
            ("HCHO_FLOAT", "hcho_float"),
            ("HVAC_WATER_PERCENTAGE", "hvac_water_percentage"),
            ("KITCHEN_WATER_TEMPERATURE", "kitchen_water_temperature"),
        ],
    )
    def test_new_feature_enum_values(self, attr, expected):
        assert getattr(SberFeature, attr).value == expected


class TestAirQualityRoles:
    """Each air-quality role must be a proper LinkableRole tied to
    the `sensor` HA domain and the correct HA device_class."""

    @pytest.mark.parametrize(
        "role,expected_role_name,expected_device_class",
        [
            (ROLE_CO2, "co2", "carbon_dioxide"),
            (ROLE_PM1, "pm1", "pm1"),
            (ROLE_PM25, "pm25", "pm25"),
            (ROLE_PM10, "pm10", "pm10"),
            (ROLE_TVOC, "tvoc", "volatile_organic_compounds"),
            (ROLE_HCHO, "hcho", "volatile_organic_compounds_parts"),
        ],
    )
    def test_role_shape(self, role, expected_role_name, expected_device_class):
        assert isinstance(role, LinkableRole)
        assert role.role == expected_role_name
        assert "sensor" in role.domains
        assert expected_device_class in role.device_classes


ENTITY_DATA = {
    "entity_id": "sensor.air_quality",
    "name": "Air Quality",
    "original_name": "Air Quality",
    "area_id": "living_room",
}


def _state(value, device_class):
    """Helper to build an HA state dict for a sensor entity."""
    return {
        "entity_id": "sensor.foo",
        "state": str(value),
        "attributes": {"device_class": device_class},
    }


class TestSensorAirBasics:
    def test_category_is_sensor_air(self):
        e = SensorAirEntity(ENTITY_DATA)
        assert e.category == SENSOR_AIR_CATEGORY
        assert SENSOR_AIR_CATEGORY == "sensor_air"

    def test_linkable_roles_include_all_measurements(self):
        role_names = {r.role for r in SensorAirEntity.LINKABLE_ROLES}
        # The eight sensor_air conditional measurements + standard sensor
        # links (battery, battery_low, signal_strength).
        assert {
            "co2", "pm1", "pm25", "pm10", "tvoc", "hcho",
            "temperature", "humidity",
            "battery", "battery_low", "signal_strength",
        }.issubset(role_names)


class TestPrimaryFill:
    """Primary HA sensor state routes into the field matching its
    device_class."""

    @pytest.mark.parametrize(
        "device_class,expected_field,input_state,expected_value",
        [
            ("carbon_dioxide", "_co2", "450", 450),
            ("pm25", "_pm25", "12.4", 12),   # INT truncation ok
            ("pm10", "_pm10", "22", 22),
            ("pm1", "_pm1", "4", 4),
            ("volatile_organic_compounds", "_tvoc", "0.35", pytest.approx(0.35)),
        ],
    )
    def test_primary_state_routes_to_matching_field(
        self, device_class, expected_field, input_state, expected_value
    ):
        e = SensorAirEntity(ENTITY_DATA)
        e.fill_by_ha_state(_state(input_state, device_class))
        assert getattr(e, expected_field) == expected_value

    def test_unknown_state_is_ignored(self):
        e = SensorAirEntity(ENTITY_DATA)
        e.fill_by_ha_state(_state("unknown", "carbon_dioxide"))
        assert e._co2 is None

    def test_unhandled_device_class_leaves_all_fields_none(self):
        e = SensorAirEntity(ENTITY_DATA)
        e.fill_by_ha_state(_state("42", "power"))
        # None of the measurement fields populated.
        for f in ("_co2", "_pm1", "_pm25", "_pm10", "_tvoc", "_hcho",
                  "_temperature", "_humidity"):
            assert getattr(e, f) is None


class TestLinkedFill:
    """Linked entities via update_linked_data fill their own field."""

    @pytest.mark.parametrize(
        "role_name,input_value,expected_field,expected_value",
        [
            ("co2", "600", "_co2", 600),
            ("pm25", "8", "_pm25", 8),
            ("pm10", "15", "_pm10", 15),
            ("pm1", "3", "_pm1", 3),
            ("tvoc", "0.12", "_tvoc", pytest.approx(0.12)),
            ("hcho", "0.04", "_hcho", pytest.approx(0.04)),
            ("humidity", "45", "_humidity", 45),
            ("temperature", "22.5", "_temperature", pytest.approx(22.5)),
        ],
    )
    def test_role_maps_to_field(self, role_name, input_value, expected_field, expected_value):
        e = SensorAirEntity(ENTITY_DATA)
        e.update_linked_data(role_name, _state(input_value, "irrelevant"))
        assert getattr(e, expected_field) == expected_value


class TestToSberCurrentState:
    """``to_sber_current_state`` returns ``{entity_id: {"states": [...]}}``
    (see BaseEntity.to_sber_current_state docstring / SimpleReadOnlySensor /
    SensorTempEntity for the established shape) — NOT a flat
    ``{"states": [...]}`` dict."""

    def test_no_measurements_emits_only_online(self):
        e = SensorAirEntity(ENTITY_DATA)
        e.is_filled_by_state = True
        states = e.to_sber_current_state()[e.entity_id]["states"]
        keys = {s["key"] for s in states}
        assert "online" in keys
        # No measurement features when all fields are None.
        assert not (keys & {
            "co2", "pm1_0", "pm2_5", "pm10", "tvoc_float", "hcho_float",
            "temperature", "humidity",
        })

    def test_only_populated_measurements_emitted(self):
        e = SensorAirEntity(ENTITY_DATA)
        e.is_filled_by_state = True
        e._co2 = 500
        e._pm25 = 10
        keys = {s["key"] for s in e.to_sber_current_state()[e.entity_id]["states"]}
        assert "co2" in keys
        assert "pm2_5" in keys
        # None values not emitted:
        assert "pm10" not in keys
        assert "hcho_float" not in keys

    def test_temperature_scaled_by_ten(self):
        """Sber wire format for temperature is INTEGER = °C × 10."""
        e = SensorAirEntity(ENTITY_DATA)
        e.is_filled_by_state = True
        e._temperature = 22.5
        temp_entry = next(
            s for s in e.to_sber_current_state()[e.entity_id]["states"]
            if s["key"] == "temperature"
        )
        assert temp_entry["value"]["integer_value"] == "225"

    def test_float_measurement_uses_float_value(self):
        """tvoc_float / hcho_float wire type is FLOAT, not INTEGER."""
        e = SensorAirEntity(ENTITY_DATA)
        e.is_filled_by_state = True
        e._tvoc = 0.35
        tvoc_entry = next(
            s for s in e.to_sber_current_state()[e.entity_id]["states"]
            if s["key"] == "tvoc_float"
        )
        assert tvoc_entry["value"]["type"] == "FLOAT"
        assert tvoc_entry["value"]["float_value"] == pytest.approx(0.35)


class TestBatterySignalLinking:
    """battery/battery_low/signal_strength roles are handled via the
    shared BatteryAndSignalLinkMixin, same as every other sensor class."""

    def test_battery_level_emits_percentage_and_low_power(self):
        e = SensorAirEntity(ENTITY_DATA)
        e.is_filled_by_state = True
        e.update_linked_data("battery", _state("15", "battery"))
        keys = {s["key"] for s in e.to_sber_current_state()[e.entity_id]["states"]}
        assert "battery_percentage" in keys
        assert "battery_low_power" in keys

    def test_signal_strength_emits_feature(self):
        e = SensorAirEntity(ENTITY_DATA)
        e.is_filled_by_state = True
        e.update_linked_data("signal_strength", _state("-60", "signal_strength"))
        keys = {s["key"] for s in e.to_sber_current_state()[e.entity_id]["states"]}
        assert "signal_strength" in keys


class TestCreateFeaturesList:
    """_create_features_list mirrors the conditional measurements actually
    populated, so the model descriptor never advertises a feature that
    to_sber_current_state won't emit."""

    def test_minimal_features_only_online(self):
        e = SensorAirEntity(ENTITY_DATA)
        assert e._create_features_list() == ["online"]

    def test_features_grow_with_populated_measurements(self):
        e = SensorAirEntity(ENTITY_DATA)
        e._co2 = 500
        e._temperature = 21.0
        features = e._create_features_list()
        assert "co2" in features
        assert "temperature" in features
        assert "pm10" not in features


class TestTempUnitView:
    """temp_unit_view should be emitted alongside temperature when
    temperature is populated."""

    def test_temp_unit_defaults_to_celsius(self):
        """Default temperature unit is Celsius."""
        e = SensorAirEntity(ENTITY_DATA)
        assert e._temp_unit == "c"

    def test_temp_unit_from_fill_by_ha_state_celsius(self):
        """fill_by_ha_state with primary temperature and no unit defaults to Celsius."""
        e = SensorAirEntity(ENTITY_DATA)
        e.fill_by_ha_state({
            "state": "22.5",
            "attributes": {"device_class": "temperature"},
        })
        assert e._temperature == pytest.approx(22.5)
        assert e._temp_unit == "c"

    def test_temp_unit_from_fill_by_ha_state_fahrenheit(self):
        """fill_by_ha_state with °F unit sets temp_unit to 'f' AND converts to °C.

        Sber's wire spec is °C × 10 for the ``temperature`` feature; the
        Fahrenheit value must be converted before storage so downstream
        emission produces the correct integer.  ``72°F ≈ 22.22°C``.
        """
        e = SensorAirEntity(ENTITY_DATA)
        e.fill_by_ha_state({
            "state": "72",
            "attributes": {
                "device_class": "temperature",
                "unit_of_measurement": "°F",
            },
        })
        assert e._temperature == pytest.approx((72 - 32) * 5 / 9)
        assert e._temp_unit == "f"

    def test_temp_unit_from_update_linked_data_celsius(self):
        """update_linked_data with temperature role and no unit defaults to Celsius."""
        e = SensorAirEntity(ENTITY_DATA)
        e.update_linked_data("temperature", {
            "state": "21.0",
            "attributes": {"device_class": "temperature"},
        })
        assert e._temperature == pytest.approx(21.0)
        assert e._temp_unit == "c"

    def test_temp_unit_from_update_linked_data_fahrenheit(self):
        """update_linked_data with °F unit sets temp_unit to 'f' AND converts to °C.

        ``68°F == 20.0°C`` exactly, which is a nice round check that the
        Fahrenheit-to-Celsius conversion is applied before storage.
        """
        e = SensorAirEntity(ENTITY_DATA)
        e.update_linked_data("temperature", {
            "state": "68",
            "attributes": {
                "device_class": "temperature",
                "unit_of_measurement": "°F",
            },
        })
        assert e._temperature == pytest.approx(20.0)
        assert e._temp_unit == "f"

    def test_temp_unit_view_in_features_when_temperature_set(self):
        """temp_unit_view feature is advertised only when temperature is populated."""
        e = SensorAirEntity(ENTITY_DATA)
        e._temperature = 20.0
        features = e._create_features_list()
        assert "temp_unit_view" in features

    def test_temp_unit_view_not_in_features_when_temperature_none(self):
        """temp_unit_view feature is NOT advertised when temperature is None."""
        e = SensorAirEntity(ENTITY_DATA)
        # _temperature is None by default
        features = e._create_features_list()
        assert "temp_unit_view" not in features

    def test_temp_unit_view_emitted_when_temperature_populated(self):
        """to_sber_current_state emits temp_unit_view when temperature is set."""
        e = SensorAirEntity(ENTITY_DATA)
        e.is_filled_by_state = True
        e._temperature = 22.5
        e._temp_unit = "c"
        states = e.to_sber_current_state()[e.entity_id]["states"]
        temp_unit_entry = next(
            (s for s in states if s["key"] == "temp_unit_view"), None
        )
        assert temp_unit_entry is not None
        assert temp_unit_entry["value"]["enum_value"] == "c"

    def test_temp_unit_view_not_emitted_when_temperature_none(self):
        """to_sber_current_state does NOT emit temp_unit_view when temperature is None."""
        e = SensorAirEntity(ENTITY_DATA)
        e.is_filled_by_state = True
        # _temperature is None by default
        states = e.to_sber_current_state()[e.entity_id]["states"]
        temp_unit_entry = next(
            (s for s in states if s["key"] == "temp_unit_view"), None
        )
        assert temp_unit_entry is None

    def test_temp_unit_view_fahrenheit_emitted(self):
        """to_sber_current_state emits temp_unit_view with 'f' when set to Fahrenheit."""
        e = SensorAirEntity(ENTITY_DATA)
        e.is_filled_by_state = True
        e._temperature = 72.0
        e._temp_unit = "f"
        states = e.to_sber_current_state()[e.entity_id]["states"]
        temp_unit_entry = next(
            (s for s in states if s["key"] == "temp_unit_view"), None
        )
        assert temp_unit_entry is not None
        assert temp_unit_entry["value"]["enum_value"] == "f"


class TestFahrenheitConversionOnWire:
    """Lock the semantic contract established by Sber's spec for
    ``temperature``: the ``integer_value`` is always temperature ×10 in
    **Celsius**, and ``temp_unit_view`` is a display-only hint that does
    NOT reinterpret the numeric value.

    Source: https://developers.sber.ru/docs/ru/smarthome/c2c/temperature
    ("The 'integer_value' should be set to the temperature multiplied
    by 10 (e.g., 220 for 22 degrees Celsius).")

    Regression guard: before this fix, a 72°F reading was emitted as
    ``720`` on the wire, which Sber decoded as 72°C — a ~50°C misread.
    """

    def _emit_temperature(self, entity: SensorAirEntity) -> int:
        entity.is_filled_by_state = True
        temp_entry = next(
            s for s in entity.to_sber_current_state()[entity.entity_id]["states"]
            if s["key"] == "temperature"
        )
        # Wire type is INTEGER; integer_value is serialised as str.
        return int(temp_entry["value"]["integer_value"])

    def test_primary_fahrenheit_wire_value_is_celsius_times_ten(self):
        """72°F primary fill → wire = 222 (22.2°C × 10, rounded)."""
        e = SensorAirEntity(ENTITY_DATA)
        e.fill_by_ha_state({
            "state": "72",
            "attributes": {
                "device_class": "temperature",
                "unit_of_measurement": "°F",
            },
        })
        wire = self._emit_temperature(e)
        # 72°F = 22.222…°C  → round(22.222… × 10) = 222
        assert wire == 222, (
            f"Expected wire=222 (22.2°C × 10); got {wire}. "
            "See https://developers.sber.ru/docs/ru/smarthome/c2c/temperature"
        )

    def test_linked_fahrenheit_wire_value_is_celsius_times_ten(self):
        """68°F via linked companion → wire = 200 (20.0°C × 10)."""
        e = SensorAirEntity(ENTITY_DATA)
        e.update_linked_data("temperature", {
            "state": "68",
            "attributes": {"unit_of_measurement": "°F"},
        })
        wire = self._emit_temperature(e)
        # 68°F = exactly 20.0°C → 200
        assert wire == 200, (
            f"Expected wire=200 (20.0°C × 10); got {wire}. "
            "See https://developers.sber.ru/docs/ru/smarthome/c2c/temperature"
        )

    def test_celsius_pass_through_unchanged(self):
        """Celsius input already matches the wire spec — no conversion."""
        e = SensorAirEntity(ENTITY_DATA)
        e.fill_by_ha_state({
            "state": "21.5",
            "attributes": {
                "device_class": "temperature",
                "unit_of_measurement": "°C",
            },
        })
        wire = self._emit_temperature(e)
        assert wire == 215

    def test_missing_unit_defaults_to_celsius(self):
        """No ``unit_of_measurement`` attribute → assume Celsius (HA default)."""
        e = SensorAirEntity(ENTITY_DATA)
        e.fill_by_ha_state({
            "state": "20",
            "attributes": {"device_class": "temperature"},
        })
        wire = self._emit_temperature(e)
        assert wire == 200
        assert e._temp_unit == "c"

    def test_negative_fahrenheit_converts_below_zero_celsius(self):
        """-4°F = -20°C ; wire = -200.  Guards against sign errors."""
        e = SensorAirEntity(ENTITY_DATA)
        e.fill_by_ha_state({
            "state": "-4",
            "attributes": {
                "device_class": "temperature",
                "unit_of_measurement": "°F",
            },
        })
        wire = self._emit_temperature(e)
        assert wire == -200

    def test_temp_unit_view_still_carries_display_hint(self):
        """Conversion happens but ``temp_unit_view`` remains ``"f"`` so
        the device screen still shows Fahrenheit."""
        e = SensorAirEntity(ENTITY_DATA)
        e.is_filled_by_state = True
        e.fill_by_ha_state({
            "state": "68",
            "attributes": {
                "device_class": "temperature",
                "unit_of_measurement": "°F",
            },
        })
        states = e.to_sber_current_state()[e.entity_id]["states"]
        temp_unit_entry = next(s for s in states if s["key"] == "temp_unit_view")
        assert temp_unit_entry["value"]["enum_value"] == "f"


def _entry(states: list[dict], key: str) -> dict | None:
    """Helper — pull a single state entry by key."""
    return next((s for s in states if s["key"] == key), None)


class TestWireRangeSafety:
    """Guard against garbage HA readings poisoning the Sber payload.

    A broken or mis-configured HA sensor can report physically-impossible
    values (negative CO2, PM readings in the thousands, humidity > 100 %).
    Sber cloud will silently reject the WHOLE device descriptor when any
    state is out of range — clamp at emit time so one buggy metric can't
    take down the other seven.  Mirrors the ``water_level`` clamp
    already applied by :class:`HumidifierEntity`.
    """

    def test_negative_co2_clamped_to_zero(self):
        e = SensorAirEntity(ENTITY_DATA)
        e.is_filled_by_state = True
        e._co2 = -50
        entry = _entry(e.to_sber_current_state()[e.entity_id]["states"], "co2")
        assert entry is not None
        assert int(entry["value"]["integer_value"]) == 0

    def test_extreme_co2_clamped_to_upper_bound(self):
        """Sber sensor_air co2 range is a few thousand ppm; 999999 is a
        broken sensor.  Clamp to 5000 (dangerous-atmosphere ceiling)."""
        e = SensorAirEntity(ENTITY_DATA)
        e.is_filled_by_state = True
        e._co2 = 999999
        entry = _entry(e.to_sber_current_state()[e.entity_id]["states"], "co2")
        assert int(entry["value"]["integer_value"]) == 5000

    @pytest.mark.parametrize("field,key", [
        ("_pm1", "pm1_0"),
        ("_pm25", "pm2_5"),
        ("_pm10", "pm10"),
    ])
    def test_negative_pm_clamped_to_zero(self, field, key):
        e = SensorAirEntity(ENTITY_DATA)
        e.is_filled_by_state = True
        setattr(e, field, -1)
        entry = _entry(e.to_sber_current_state()[e.entity_id]["states"], key)
        assert int(entry["value"]["integer_value"]) == 0

    @pytest.mark.parametrize("field,key", [
        ("_pm1", "pm1_0"),
        ("_pm25", "pm2_5"),
        ("_pm10", "pm10"),
    ])
    def test_extreme_pm_clamped_to_upper_bound(self, field, key):
        e = SensorAirEntity(ENTITY_DATA)
        e.is_filled_by_state = True
        setattr(e, field, 5000)
        entry = _entry(e.to_sber_current_state()[e.entity_id]["states"], key)
        assert int(entry["value"]["integer_value"]) == 999

    def test_humidity_over_100_clamped(self):
        e = SensorAirEntity(ENTITY_DATA)
        e.is_filled_by_state = True
        e._humidity = 150
        entry = _entry(e.to_sber_current_state()[e.entity_id]["states"], "humidity")
        assert int(entry["value"]["integer_value"]) == 100

    def test_humidity_negative_clamped(self):
        e = SensorAirEntity(ENTITY_DATA)
        e.is_filled_by_state = True
        e._humidity = -5
        entry = _entry(e.to_sber_current_state()[e.entity_id]["states"], "humidity")
        assert int(entry["value"]["integer_value"]) == 0

    def test_negative_tvoc_clamped(self):
        e = SensorAirEntity(ENTITY_DATA)
        e.is_filled_by_state = True
        e._tvoc = -0.1
        entry = _entry(e.to_sber_current_state()[e.entity_id]["states"], "tvoc_float")
        assert entry["value"]["float_value"] == pytest.approx(0.0)

    def test_negative_hcho_clamped(self):
        e = SensorAirEntity(ENTITY_DATA)
        e.is_filled_by_state = True
        e._hcho = -0.5
        entry = _entry(e.to_sber_current_state()[e.entity_id]["states"], "hcho_float")
        assert entry["value"]["float_value"] == pytest.approx(0.0)

    def test_valid_values_pass_through_unchanged(self):
        """Realistic mid-range values must not be modified by the clamp."""
        e = SensorAirEntity(ENTITY_DATA)
        e.is_filled_by_state = True
        e._co2 = 600
        e._pm25 = 15
        e._humidity = 45
        e._tvoc = 0.35
        states = e.to_sber_current_state()[e.entity_id]["states"]
        assert int(_entry(states, "co2")["value"]["integer_value"]) == 600
        assert int(_entry(states, "pm2_5")["value"]["integer_value"]) == 15
        assert int(_entry(states, "humidity")["value"]["integer_value"]) == 45
        assert _entry(states, "tvoc_float")["value"]["float_value"] == pytest.approx(0.35)


class TestPrimaryDeviceClassCoverage:
    """Complete coverage of the primary-fill routing table.

    ``TestPrimaryFill`` already covers five of the eight device_classes
    routed by ``_DEVICE_CLASS_ROUTING``.  Close the gap so a future
    refactor cannot silently drop ``humidity`` / ``temperature`` /
    ``volatile_organic_compounds_parts`` without a failing test.
    """

    def test_humidity_device_class_routes_to_humidity_field(self):
        e = SensorAirEntity(ENTITY_DATA)
        e.fill_by_ha_state(_state("42", "humidity"))
        assert e._humidity == 42
        assert e._co2 is None  # no cross-contamination

    def test_temperature_device_class_routes_to_temperature_field(self):
        e = SensorAirEntity(ENTITY_DATA)
        e.fill_by_ha_state({
            "state": "21.5",
            "attributes": {
                "device_class": "temperature",
                "unit_of_measurement": "°C",
            },
        })
        assert e._temperature == pytest.approx(21.5)
        assert e._humidity is None

    def test_hcho_device_class_routes_to_hcho_field(self):
        """HA's ``volatile_organic_compounds_parts`` is the HCHO analogue
        of ``volatile_organic_compounds`` for TVOC — must land in ``_hcho``,
        not ``_tvoc``."""
        e = SensorAirEntity(ENTITY_DATA)
        e.fill_by_ha_state(_state("0.05", "volatile_organic_compounds_parts"))
        assert e._hcho == pytest.approx(0.05)
        assert e._tvoc is None


class TestAdversarialStates:
    """Malformed HA states must not crash or promote NaN/Inf onto the wire."""

    @pytest.mark.parametrize("bad_state", [
        "unknown", "unavailable", None, "", "NaN", "inf", "-inf", "abc",
        # Empty-attribute variants:
    ])
    def test_bad_primary_state_leaves_field_none(self, bad_state):
        e = SensorAirEntity(ENTITY_DATA)
        e.fill_by_ha_state({
            "state": bad_state,
            "attributes": {"device_class": "carbon_dioxide"},
        })
        assert e._co2 is None

    @pytest.mark.parametrize("bad_state", [
        "unknown", "unavailable", None, "", "NaN", "inf", "abc",
    ])
    def test_bad_linked_state_leaves_field_none(self, bad_state):
        e = SensorAirEntity(ENTITY_DATA)
        e.update_linked_data("co2", {"state": bad_state, "attributes": {}})
        assert e._co2 is None

    def test_nan_temperature_not_emitted(self):
        """A NaN reading must not reach the wire — it would produce
        ``round(nan * 10)`` which raises ValueError."""
        e = SensorAirEntity(ENTITY_DATA)
        e.fill_by_ha_state({
            "state": "NaN",
            "attributes": {"device_class": "temperature"},
        })
        assert e._temperature is None
        states = e.to_sber_current_state()[e.entity_id]["states"]
        assert _entry(states, "temperature") is None
        assert _entry(states, "temp_unit_view") is None

    def test_infinity_tvoc_not_emitted(self):
        e = SensorAirEntity(ENTITY_DATA)
        e.update_linked_data("tvoc", {"state": "inf", "attributes": {}})
        assert e._tvoc is None
        states = e.to_sber_current_state()[e.entity_id]["states"]
        assert _entry(states, "tvoc_float") is None


class TestPopulatedToUnavailable:
    """A previously-populated field must clear back to ``None`` when its
    source sensor drops to ``unavailable`` — otherwise Sber sees a stale
    reading that never expires."""

    def test_co2_clears_when_linked_sensor_becomes_unavailable(self):
        e = SensorAirEntity(ENTITY_DATA)
        e.update_linked_data("co2", _state("500", "carbon_dioxide"))
        assert e._co2 == 500
        e.update_linked_data("co2", {"state": "unavailable", "attributes": {}})
        assert e._co2 is None

    def test_primary_temperature_clears_when_sensor_becomes_unknown(self):
        e = SensorAirEntity(ENTITY_DATA)
        e.fill_by_ha_state({
            "state": "20.0",
            "attributes": {"device_class": "temperature"},
        })
        assert e._temperature == pytest.approx(20.0)
        e.fill_by_ha_state({
            "state": "unknown",
            "attributes": {"device_class": "temperature"},
        })
        assert e._temperature is None

    def test_cleared_field_not_advertised_in_features(self):
        e = SensorAirEntity(ENTITY_DATA)
        e.update_linked_data("humidity", _state("55", "humidity"))
        assert "humidity" in e._create_features_list()
        e.update_linked_data("humidity", {"state": "unavailable", "attributes": {}})
        assert "humidity" not in e._create_features_list()

    def test_cleared_field_not_emitted_in_state(self):
        e = SensorAirEntity(ENTITY_DATA)
        e.is_filled_by_state = True
        e.update_linked_data("pm25", _state("10", "pm25"))
        states = e.to_sber_current_state()[e.entity_id]["states"]
        assert _entry(states, "pm2_5") is not None
        e.update_linked_data("pm25", {"state": "unavailable", "attributes": {}})
        states = e.to_sber_current_state()[e.entity_id]["states"]
        assert _entry(states, "pm2_5") is None


class TestCrossRoleIsolation:
    """A companion sensor with role X must never leak into field Y.

    The routing table maps eight roles into eight distinct measurement
    fields — a copy-paste bug that aliases two of them (e.g. CO2 into
    ``_pm10``) would silently mis-report a critical safety metric.
    """

    def test_co2_role_does_not_touch_pm_or_temperature(self):
        e = SensorAirEntity(ENTITY_DATA)
        e.update_linked_data("co2", _state("650", "carbon_dioxide"))
        assert e._co2 == 650
        assert e._pm1 is None
        assert e._pm25 is None
        assert e._pm10 is None
        assert e._temperature is None
        assert e._humidity is None
        assert e._tvoc is None
        assert e._hcho is None

    def test_pm25_role_does_not_touch_pm10_or_pm1(self):
        e = SensorAirEntity(ENTITY_DATA)
        e.update_linked_data("pm25", _state("12", "pm25"))
        assert e._pm25 == 12
        assert e._pm1 is None
        assert e._pm10 is None

    def test_tvoc_and_hcho_are_isolated(self):
        e = SensorAirEntity(ENTITY_DATA)
        e.update_linked_data("tvoc", _state("0.30", "volatile_organic_compounds"))
        e.update_linked_data("hcho", _state("0.05", "volatile_organic_compounds_parts"))
        assert e._tvoc == pytest.approx(0.30)
        assert e._hcho == pytest.approx(0.05)

    def test_unknown_role_touches_nothing(self):
        e = SensorAirEntity(ENTITY_DATA)
        e.update_linked_data("mystery_metric", _state("42", "anything"))
        for f in ("_co2", "_pm1", "_pm25", "_pm10",
                  "_tvoc", "_hcho", "_temperature", "_humidity"):
            assert getattr(e, f) is None


class TestFactoryIntegration:
    """``create_sber_entity`` must build a ``SensorAirEntity`` for each
    of the five HA device_classes declared in ``CATEGORY_DOMAIN_MAP``,
    when the user picks ``sensor_air`` explicitly OR when auto-detection
    routes the entity there.
    """

    @pytest.mark.parametrize("device_class", [
        "carbon_dioxide", "pm1", "pm25", "pm10", "volatile_organic_compounds",
    ])
    def test_auto_detection_picks_sensor_air(self, device_class):
        from custom_components.sber_mqtt_bridge.sber_entity_map import create_sber_entity
        entity = create_sber_entity(
            "sensor.air_quality",
            {"entity_id": "sensor.air_quality",
             "original_device_class": device_class,
             "name": "Air Quality"},
        )
        assert entity is not None
        assert isinstance(entity, SensorAirEntity)
        assert entity.category == SENSOR_AIR_CATEGORY

    def test_explicit_override_to_sensor_air(self):
        """Even for a sensor without a device_class, an explicit
        ``sber_category='sensor_air'`` override must construct the
        entity — otherwise a user with a bare custom sensor can't
        promote it via the wizard."""
        from custom_components.sber_mqtt_bridge.sber_entity_map import create_sber_entity
        entity = create_sber_entity(
            "sensor.custom_air",
            {"entity_id": "sensor.custom_air", "name": "Custom Air"},
            sber_category="sensor_air",
        )
        assert isinstance(entity, SensorAirEntity)

    def test_temperature_device_class_does_not_route_to_sensor_air(self):
        """Pure temperature sensors must still go to sensor_temp, not
        get stolen by sensor_air — otherwise every temperature sensor
        installation would be mis-categorised after this integration.
        """
        from custom_components.sber_mqtt_bridge.sber_entity_map import create_sber_entity
        entity = create_sber_entity(
            "sensor.living_temp",
            {"entity_id": "sensor.living_temp",
             "original_device_class": "temperature",
             "name": "Living Temp"},
        )
        assert entity is not None
        assert not isinstance(entity, SensorAirEntity)
