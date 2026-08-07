"""Tests for allowed_values ↔ features reconciliation (issue #44 audit, group A).

Guards two systemic failure modes:

* ``sber_features_remove`` on a feature that has allowed_values left an
  orphaned allowed_values key; the pydantic validator rejected the
  descriptor and the whole device silently disappeared from the Sber
  config payload.
* Features/allowed_values built from different conditions (climate
  thermostat/work mode, unmapped HA enum passthrough) shipped ENUM
  features without values or with non-Sber values.
"""

import unittest

from custom_components.sber_mqtt_bridge.devices.climate import ClimateEntity
from custom_components.sber_mqtt_bridge.devices.humidifier import HumidifierEntity
from custom_components.sber_mqtt_bridge.devices.hvac_boiler import HvacBoilerEntity
from custom_components.sber_mqtt_bridge.devices.light import LightEntity

CLIMATE_DATA = {"entity_id": "climate.ac", "name": "AC"}


def _climate_state(**attrs):
    return {"entity_id": "climate.ac", "state": "cool", "attributes": attrs}


class TestRemovedFeaturesDropAllowedValues(unittest.TestCase):
    """sber_features_remove must drop the matching allowed_values key."""

    def test_removed_feature_leaves_no_orphaned_allowed_values(self):
        """Removing hvac_air_flow_power drops its allowed_values entry."""
        entity = ClimateEntity(CLIMATE_DATA)
        entity.fill_by_ha_state(
            _climate_state(hvac_modes=["off", "cool"], fan_modes=["auto", "low"], min_temp=16, max_temp=30)
        )
        entity.removed_features = ["hvac_air_flow_power"]
        descriptor = entity.to_sber_state()["model"]
        self.assertNotIn("hvac_air_flow_power", descriptor["features"])
        self.assertNotIn("hvac_air_flow_power", descriptor.get("allowed_values", {}))

    def test_descriptor_survives_validation_after_removal(self):
        """The reconciled descriptor passes the device validator."""
        from custom_components.sber_mqtt_bridge.sber_models import validate_device

        entity = ClimateEntity(CLIMATE_DATA)
        entity.fill_by_ha_state(
            _climate_state(hvac_modes=["off", "cool"], fan_modes=["auto", "low"], min_temp=16, max_temp=30)
        )
        entity.removed_features = ["hvac_air_flow_power"]
        device = entity.to_sber_state()
        device["id"] = "climate.ac"
        validate_device(device)  # must not raise

    def test_light_removed_brightness_drops_allowed_values(self):
        """Same reconciliation applies to every device class (via base)."""
        entity = LightEntity({"entity_id": "light.room", "name": "Room"})
        entity.fill_by_ha_state(
            {
                "entity_id": "light.room",
                "state": "on",
                "attributes": {"supported_color_modes": ["color_temp"], "brightness": 100},
            }
        )
        entity.removed_features = ["light_brightness"]
        descriptor = entity.to_sber_state()["model"]
        self.assertNotIn("light_brightness", descriptor.get("allowed_values", {}))


class TestClimateEnumFeatureConsistency(unittest.TestCase):
    """ENUM features must be declared only when at least one mode maps."""

    def test_unmappable_thermostat_modes_omit_feature(self):
        """hvac_boiler with only off/cool modes gets no hvac_thermostat_mode."""
        entity = HvacBoilerEntity({"entity_id": "water_heater.boiler", "name": "Boiler"})
        entity.fill_by_ha_state(
            {
                "entity_id": "water_heater.boiler",
                "state": "off",
                "attributes": {"hvac_modes": ["off", "cool"], "min_temp": 30, "max_temp": 80},
            }
        )
        features = entity.get_final_features_list()
        self.assertNotIn("hvac_thermostat_mode", features)

    def test_mappable_thermostat_modes_have_matching_allowed_values(self):
        """heat-capable boiler declares the feature WITH enum_values."""
        entity = HvacBoilerEntity({"entity_id": "water_heater.boiler", "name": "Boiler"})
        entity.fill_by_ha_state(
            {
                "entity_id": "water_heater.boiler",
                "state": "heat",
                "attributes": {"hvac_modes": ["off", "heat"], "min_temp": 30, "max_temp": 80},
            }
        )
        features = entity.get_final_features_list()
        allowed = entity.create_allowed_values_list()
        self.assertIn("hvac_thermostat_mode", features)
        self.assertIn("hvac_thermostat_mode", allowed)

    def test_unmapped_fan_modes_filtered_from_enum_values(self):
        """Device-specific fan modes must not leak into Sber enum_values."""
        entity = ClimateEntity(CLIMATE_DATA)
        entity.fill_by_ha_state(
            _climate_state(
                hvac_modes=["off", "cool"],
                fan_modes=["auto", "MyWeirdMode", "low"],
                min_temp=16,
                max_temp=30,
            )
        )
        allowed = entity.create_allowed_values_list()
        values = allowed["hvac_air_flow_power"]["enum_values"]["values"]
        self.assertEqual(values, ["auto", "low"])

    def test_all_unmapped_fan_modes_omit_feature(self):
        """Only unmapped fan modes → no hvac_air_flow_power at all."""
        entity = ClimateEntity(CLIMATE_DATA)
        entity.fill_by_ha_state(
            _climate_state(hvac_modes=["off", "cool"], fan_modes=["WeirdA", "WeirdB"], min_temp=16, max_temp=30)
        )
        self.assertNotIn("hvac_air_flow_power", entity.get_final_features_list())
        self.assertNotIn("hvac_air_flow_power", entity.create_allowed_values_list())

    def test_unmapped_fan_mode_state_not_published(self):
        """Current unmapped fan mode must not be published as ENUM state."""
        entity = ClimateEntity(CLIMATE_DATA)
        entity.fill_by_ha_state(
            _climate_state(
                hvac_modes=["off", "cool"],
                fan_modes=["auto", "MyWeirdMode"],
                fan_mode="MyWeirdMode",
                min_temp=16,
                max_temp=30,
            )
        )
        states = entity.to_sber_current_state()["climate.ac"]["states"]
        self.assertNotIn("hvac_air_flow_power", [s["key"] for s in states])

    def test_climate_child_lock_off_spec(self):
        """No hvac_* category has child_lock in the Sber spec."""
        entity = ClimateEntity(CLIMATE_DATA)
        entity.fill_by_ha_state(_climate_state(hvac_modes=["off", "cool"], child_lock=True, min_temp=16, max_temp=30))
        self.assertNotIn("child_lock", entity.get_final_features_list())
        states = entity.to_sber_current_state()["climate.ac"]["states"]
        self.assertNotIn("child_lock", [s["key"] for s in states])


class TestHumidifierEnumFiltering(unittest.TestCase):
    """Humidifier modes: unmapped HA strings must not reach Sber."""

    HUM_DATA = {"entity_id": "humidifier.h", "name": "Hum"}

    def _state(self, **attrs):
        return {"entity_id": "humidifier.h", "state": "on", "attributes": attrs}

    def test_unmapped_modes_filtered(self):
        """Only mapped modes appear in enum_values."""
        entity = HumidifierEntity(self.HUM_DATA)
        entity.fill_by_ha_state(self._state(available_modes=["Auto", "Weird", "High"], humidity=50))
        allowed = entity.create_allowed_values_list()
        self.assertEqual(allowed["hvac_air_flow_power"]["enum_values"]["values"], ["auto", "high"])

    def test_all_unmapped_modes_omit_feature(self):
        """Only unmapped modes → no hvac_air_flow_power feature."""
        entity = HumidifierEntity(self.HUM_DATA)
        entity.fill_by_ha_state(self._state(available_modes=["WeirdA"], humidity=50))
        self.assertNotIn("hvac_air_flow_power", entity.get_final_features_list())

    def test_unmapped_current_mode_state_not_published(self):
        """Unmapped current mode must not be published as ENUM state."""
        entity = HumidifierEntity(self.HUM_DATA)
        entity.fill_by_ha_state(self._state(available_modes=["Auto", "Weird"], mode="Weird", humidity=50))
        states = entity.to_sber_current_state()["humidifier.h"]["states"]
        self.assertNotIn("hvac_air_flow_power", [s["key"] for s in states])

    def test_humidifier_child_lock_off_spec(self):
        """hvac_humidifier has no child_lock in the Sber spec."""
        entity = HumidifierEntity(self.HUM_DATA)
        entity.fill_by_ha_state(self._state(humidity=50, child_lock=True))
        self.assertNotIn("child_lock", entity.get_final_features_list())
        states = entity.to_sber_current_state()["humidifier.h"]["states"]
        self.assertNotIn("child_lock", [s["key"] for s in states])


if __name__ == "__main__":
    unittest.main()
