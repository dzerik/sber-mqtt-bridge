"""Unit tests for SensorAirEntity + Sber air-quality features."""

from __future__ import annotations

import pytest

from custom_components.sber_mqtt_bridge.devices.base_entity import (
    ROLE_CO2, ROLE_HCHO, ROLE_HUMIDITY, ROLE_PM1, ROLE_PM10, ROLE_PM25,
    ROLE_TEMPERATURE, ROLE_TVOC, LinkableRole,
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
