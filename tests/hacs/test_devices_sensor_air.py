"""Unit tests for SensorAirEntity + Sber air-quality features."""

from __future__ import annotations

import pytest

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
