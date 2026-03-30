"""Tests for sber_protocol module."""

import json
import unittest

from custom_components.sber_mqtt_bridge.sber_protocol import (
    build_devices_list_json,
    build_hub_device,
    build_states_list_json,
    parse_sber_command,
    parse_sber_status_request,
)
from custom_components.sber_mqtt_bridge.devices.relay import RelayEntity
from custom_components.sber_mqtt_bridge.devices.sensor_temp import SensorTempEntity


RELAY_ENTITY_DATA = {
    "entity_id": "switch.lamp",
    "name": "Lamp",
    "original_name": "Lamp",
    "area_id": "room1",
}

SENSOR_ENTITY_DATA = {
    "entity_id": "sensor.temp",
    "name": "Temperature",
    "original_name": "Temp",
    "device_id": "dev2",
    "area_id": "room1",
}

HA_STATE_ON = {
    "entity_id": "switch.lamp",
    "state": "on",
    "attributes": {"friendly_name": "Lamp"},
}

HA_STATE_TEMP = {
    "entity_id": "sensor.temp",
    "state": "22.5",
    "attributes": {"device_class": "temperature"},
}


class TestBuildHubDevice(unittest.TestCase):

    def test_hub_device_structure(self):
        hub = build_hub_device("1.0.0")
        self.assertEqual(hub["id"], "root")
        self.assertEqual(hub["model"]["category"], "hub")
        self.assertIn("online", hub["model"]["features"])
        self.assertEqual(hub["hw_version"], "1.0.0")

    def test_hub_default_version(self):
        hub = build_hub_device()
        self.assertIsNotNone(hub["hw_version"])


class TestBuildDevicesListJson(unittest.TestCase):

    def setUp(self):
        self.relay = RelayEntity(RELAY_ENTITY_DATA)
        self.relay.fill_by_ha_state(HA_STATE_ON)
        self.entities = {"switch.lamp": self.relay}

    def test_includes_hub(self):
        result = json.loads(build_devices_list_json(self.entities, ["switch.lamp"]))
        devices = result["devices"]
        hub = devices[0]
        self.assertEqual(hub["id"], "root")

    def test_includes_enabled_entity(self):
        result = json.loads(build_devices_list_json(self.entities, ["switch.lamp"]))
        self.assertEqual(len(result["devices"]), 2)

    def test_excludes_not_enabled(self):
        result = json.loads(build_devices_list_json(self.entities, []))
        self.assertEqual(len(result["devices"]), 1)

    def test_skips_unfilled_entity(self):
        unfilled = RelayEntity(RELAY_ENTITY_DATA)
        entities = {"switch.lamp": unfilled}
        result = json.loads(build_devices_list_json(entities, ["switch.lamp"]))
        self.assertEqual(len(result["devices"]), 1)

    def test_applies_redefinitions(self):
        redefs = {"switch.lamp": {"home": "My Home", "room": "Kitchen", "name": "New Lamp"}}
        result = json.loads(build_devices_list_json(self.entities, ["switch.lamp"], redefs))
        device = result["devices"][1]
        self.assertEqual(device["home"], "My Home")
        self.assertEqual(device["room"], "Kitchen")
        self.assertEqual(device["name"], "New Lamp")


class TestBuildStatesListJson(unittest.TestCase):

    def setUp(self):
        self.relay = RelayEntity(RELAY_ENTITY_DATA)
        self.relay.fill_by_ha_state(HA_STATE_ON)
        self.sensor = SensorTempEntity(SENSOR_ENTITY_DATA)
        self.sensor.fill_by_ha_state(HA_STATE_TEMP)
        self.entities = {"switch.lamp": self.relay, "sensor.temp": self.sensor}
        self.enabled = ["switch.lamp", "sensor.temp"]

    def test_returns_valid_json(self):
        result = json.loads(build_states_list_json(self.entities, None, self.enabled)[0])
        self.assertIn("devices", result)

    def test_specific_entity_ids(self):
        result = json.loads(build_states_list_json(self.entities, ["switch.lamp"], self.enabled)[0])
        self.assertIn("switch.lamp", result["devices"])
        self.assertNotIn("sensor.temp", result["devices"])

    def test_all_enabled(self):
        result = json.loads(build_states_list_json(self.entities, None, self.enabled)[0])
        self.assertIn("switch.lamp", result["devices"])
        self.assertIn("sensor.temp", result["devices"])

    def test_empty_returns_root(self):
        result = json.loads(build_states_list_json({}, None, [])[0])
        self.assertIn("root", result["devices"])

    def test_relay_state_format(self):
        result = json.loads(build_states_list_json(self.entities, ["switch.lamp"], self.enabled)[0])
        states = result["devices"]["switch.lamp"]["states"]
        keys = [s["key"] for s in states]
        self.assertIn("online", keys)
        self.assertIn("on_off", keys)

    def test_sensor_state_format(self):
        result = json.loads(build_states_list_json(self.entities, ["sensor.temp"], self.enabled)[0])
        states = result["devices"]["sensor.temp"]["states"]
        temp = next(s for s in states if s["key"] == "temperature")
        self.assertEqual(temp["value"]["integer_value"], "225")


class TestParseSberCommand(unittest.TestCase):

    def test_parse_valid_command(self):
        payload = json.dumps({
            "devices": {
                "switch.lamp": {
                    "states": [{"key": "on_off", "value": {"type": "BOOL", "bool_value": True}}]
                }
            }
        })
        result = parse_sber_command(payload)
        self.assertIn("switch.lamp", result["devices"])

    def test_parse_bytes(self):
        payload = b'{"devices": {}}'
        result = parse_sber_command(payload)
        self.assertEqual(result["devices"], {})


class TestParseSberStatusRequest(unittest.TestCase):

    def test_parse_specific_devices(self):
        payload = json.dumps({"devices": ["light.a", "switch.b"]})
        result = parse_sber_status_request(payload)
        self.assertEqual(result, ["light.a", "switch.b"])

    def test_parse_empty_string_device(self):
        payload = json.dumps({"devices": [""]})
        result = parse_sber_status_request(payload)
        self.assertEqual(result, [])

    def test_parse_empty_list(self):
        payload = json.dumps({"devices": []})
        result = parse_sber_status_request(payload)
        self.assertEqual(result, [])

    def test_parse_invalid_json(self):
        result = parse_sber_status_request(b"not json")
        self.assertEqual(result, [])

    def test_parse_missing_devices(self):
        payload = json.dumps({"other": "data"})
        result = parse_sber_status_request(payload)
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
