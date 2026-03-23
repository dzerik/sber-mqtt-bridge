"""Tests for GasSensorEntity -- Sber gas sensor device mapping."""

import unittest

from custom_components.sber_mqtt_bridge.devices.gas_sensor import GasSensorEntity


ENTITY_DATA = {"entity_id": "binary_sensor.gas", "name": "Gas Detector"}


def _make_ha_state(state="off", **attrs):
    return {
        "entity_id": "binary_sensor.gas",
        "state": state,
        "attributes": attrs,
    }


class TestGasSensorCreate(unittest.TestCase):
    """Test GasSensorEntity initialization."""

    def test_category(self):
        entity = GasSensorEntity(ENTITY_DATA)
        self.assertEqual(entity.category, "sensor_gas")

    def test_initial_state(self):
        entity = GasSensorEntity(ENTITY_DATA)
        self.assertFalse(entity.gas_detected)

    def test_sber_value_key(self):
        entity = GasSensorEntity(ENTITY_DATA)
        self.assertEqual(entity._sber_value_key, "gas_leak_state")


class TestGasSensorToSberCurrentState(unittest.TestCase):
    """Test to_sber_current_state."""

    def test_gas_detected(self):
        entity = GasSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("on"))
        result = entity.to_sber_current_state()
        states = result["binary_sensor.gas"]["states"]
        gas = next(s for s in states if s["key"] == "gas_leak_state")
        self.assertEqual(gas["value"]["type"], "BOOL")
        self.assertTrue(gas["value"]["bool_value"])

    def test_no_gas(self):
        entity = GasSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("off"))
        result = entity.to_sber_current_state()
        states = result["binary_sensor.gas"]["states"]
        gas = next(s for s in states if s["key"] == "gas_leak_state")
        self.assertFalse(gas["value"]["bool_value"])

    def test_online_status(self):
        entity = GasSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("unavailable"))
        result = entity.to_sber_current_state()
        states = result["binary_sensor.gas"]["states"]
        online = next(s for s in states if s["key"] == "online")
        self.assertFalse(online["value"]["bool_value"])


class TestGasSensorProcessCmd(unittest.TestCase):
    """Test process_cmd (read-only)."""

    def test_cmd_is_noop(self):
        entity = GasSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("off"))
        result = entity.process_cmd({"states": []})
        self.assertEqual(result, [])
