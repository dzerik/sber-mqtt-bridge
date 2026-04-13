"""Tests for OnOffEntity -- power/voltage/current features."""

import unittest

from custom_components.sber_mqtt_bridge.devices.relay import RelayEntity
from custom_components.sber_mqtt_bridge.devices.socket_entity import SocketEntity


RELAY_DATA = {"entity_id": "switch.relay1", "name": "Relay 1"}
SOCKET_DATA = {"entity_id": "switch.socket1", "name": "Socket 1"}


def _make_ha_state(state="on", **attrs):
    return {
        "entity_id": "switch.relay1",
        "state": state,
        "attributes": attrs,
    }


class TestOnOffEntityEnergyFeatures(unittest.TestCase):
    """Test power/voltage/current features in OnOffEntity."""

    def test_no_energy_attrs(self):
        entity = RelayEntity(RELAY_DATA)
        entity.fill_by_ha_state(_make_ha_state("on"))
        features = entity.get_final_features_list()
        self.assertNotIn("power", features)
        self.assertNotIn("voltage", features)
        self.assertNotIn("current", features)

    def test_power_in_features(self):
        entity = RelayEntity(RELAY_DATA)
        entity.fill_by_ha_state(_make_ha_state("on", power=150))
        features = entity.get_final_features_list()
        self.assertIn("power", features)

    def test_voltage_in_features(self):
        entity = RelayEntity(RELAY_DATA)
        entity.fill_by_ha_state(_make_ha_state("on", voltage=220))
        features = entity.get_final_features_list()
        self.assertIn("voltage", features)

    def test_current_in_features(self):
        entity = RelayEntity(RELAY_DATA)
        entity.fill_by_ha_state(_make_ha_state("on", current=500))
        features = entity.get_final_features_list()
        self.assertIn("current", features)

    def test_all_energy_in_state(self):
        entity = RelayEntity(RELAY_DATA)
        entity.fill_by_ha_state(_make_ha_state("on", power=150, voltage=220, current=500))
        result = entity.to_sber_current_state()
        states = result["switch.relay1"]["states"]

        power = next(s for s in states if s["key"] == "power")
        self.assertEqual(power["value"]["integer_value"], "150")

        voltage = next(s for s in states if s["key"] == "voltage")
        self.assertEqual(voltage["value"]["integer_value"], "220")

        current = next(s for s in states if s["key"] == "current")
        self.assertEqual(current["value"]["integer_value"], "500")

    def test_socket_also_supports_energy(self):
        entity = SocketEntity(SOCKET_DATA)
        entity.fill_by_ha_state({
            "entity_id": "switch.socket1",
            "state": "on",
            "attributes": {"power": 100},
        })
        features = entity.get_final_features_list()
        self.assertIn("power", features)

    def test_no_energy_in_state_when_absent(self):
        entity = RelayEntity(RELAY_DATA)
        entity.fill_by_ha_state(_make_ha_state("on"))
        result = entity.to_sber_current_state()
        states = result["switch.relay1"]["states"]
        keys = [s["key"] for s in states]
        self.assertNotIn("power", keys)
        self.assertNotIn("voltage", keys)
        self.assertNotIn("current", keys)
