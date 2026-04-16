"""Tests for sber_protocol module."""

import json
import unittest

from custom_components.sber_mqtt_bridge.sber_protocol import (
    build_devices_list_json,
    build_hub_device,
    build_states_list_json,
    parse_sber_command,
    parse_sber_status_request,
    resolve_ha_serial_number,
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
        result = json.loads(build_devices_list_json(self.entities, ["switch.lamp"])[0])
        devices = result["devices"]
        hub = devices[0]
        self.assertEqual(hub["id"], "root")

    def test_includes_enabled_entity(self):
        result = json.loads(build_devices_list_json(self.entities, ["switch.lamp"])[0])
        self.assertEqual(len(result["devices"]), 2)

    def test_excludes_not_enabled(self):
        result = json.loads(build_devices_list_json(self.entities, [])[0])
        self.assertEqual(len(result["devices"]), 1)

    def test_skips_unfilled_entity(self):
        unfilled = RelayEntity(RELAY_ENTITY_DATA)
        entities = {"switch.lamp": unfilled}
        result = json.loads(build_devices_list_json(entities, ["switch.lamp"])[0])
        self.assertEqual(len(result["devices"]), 1)

    def test_applies_redefinitions(self):
        redefs = {"switch.lamp": {"home": "My Home", "room": "Kitchen", "name": "New Lamp"}}
        result = json.loads(build_devices_list_json(self.entities, ["switch.lamp"], redefs)[0])
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


class TestPerHaSerialNumber(unittest.TestCase):
    """Per-HA ``ha_serial_number`` marker emitted in ``partner_meta``."""

    HA_PREFIX_A = "8f2a1b3c"
    HA_PREFIX_B = "deadbeef"

    def setUp(self) -> None:
        self.entities = {"switch.lamp": RelayEntity(RELAY_ENTITY_DATA)}
        self.entities["switch.lamp"].fill_by_ha_state(HA_STATE_ON)

    # ----- resolve_ha_serial_number -----

    def test_real_serial_wins_over_fallback(self) -> None:
        entity = RelayEntity({**RELAY_ENTITY_DATA, "device_id": "dev1"})
        entity.link_device({"id": "dev1", "serial_number": "ABC-1234", "mac": "aa:bb:cc:dd:ee:ff"})
        self.assertEqual(resolve_ha_serial_number(entity, self.HA_PREFIX_A), "ABC-1234")

    def test_mac_used_when_no_serial(self) -> None:
        entity = RelayEntity({**RELAY_ENTITY_DATA, "device_id": "dev1"})
        entity.link_device({"id": "dev1", "mac": "aa:bb:cc:dd:ee:ff"})
        self.assertEqual(resolve_ha_serial_number(entity, self.HA_PREFIX_A), "aa:bb:cc:dd:ee:ff")

    def test_fallback_uses_ha_prefix(self) -> None:
        entity = RelayEntity(RELAY_ENTITY_DATA)
        # No linked_device at all → fallback path.
        self.assertEqual(resolve_ha_serial_number(entity, self.HA_PREFIX_A), f"ha-{self.HA_PREFIX_A}")

    def test_two_ha_instances_get_distinct_fallbacks(self) -> None:
        entity = RelayEntity(RELAY_ENTITY_DATA)
        a = resolve_ha_serial_number(entity, self.HA_PREFIX_A)
        b = resolve_ha_serial_number(entity, self.HA_PREFIX_B)
        self.assertNotEqual(a, b)
        self.assertTrue(a.startswith("ha-"))
        self.assertTrue(b.startswith("ha-"))

    # ----- end-to-end through build_devices_list_json -----

    def test_marker_absent_when_disabled(self) -> None:
        result = json.loads(build_devices_list_json(self.entities, ["switch.lamp"])[0])
        for device in result["devices"]:
            self.assertNotIn("partner_meta", device, msg=f"unexpected partner_meta in {device['id']}")

    def test_marker_added_to_hub_when_enabled(self) -> None:
        result = json.loads(
            build_devices_list_json(self.entities, ["switch.lamp"], ha_serial_prefix=self.HA_PREFIX_A)[0]
        )
        hub = result["devices"][0]
        self.assertEqual(hub["id"], "root")
        self.assertEqual(hub["partner_meta"]["ha_serial_number"], f"ha-{self.HA_PREFIX_A}")

    def test_marker_added_to_entity_when_enabled(self) -> None:
        result = json.loads(
            build_devices_list_json(self.entities, ["switch.lamp"], ha_serial_prefix=self.HA_PREFIX_A)[0]
        )
        device = result["devices"][1]
        self.assertEqual(device["partner_meta"]["ha_serial_number"], f"ha-{self.HA_PREFIX_A}")


if __name__ == "__main__":
    unittest.main()
