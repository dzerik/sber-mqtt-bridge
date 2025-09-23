import os
import unittest

from devices.device_data import DeviceData
from devices.light import LightEntity
from devices_db import json_read


class TestDevicesBase(unittest.TestCase):
    devices_list: dict[str, DeviceData]
    entities_list: dict[str, LightEntity]
    area_list: dict[str, dict[str, str]]
    entity_groups: dict[str, list[str]] = {}
    data_devices_path: str

    def setUp(self):
        self.maxDiff = None
        self.data_devices_path = os.path.join(os.path.dirname(__file__), "..", "data", "devices")
        devices_data_path = os.path.join(self.data_devices_path, "device_registry.json")
        area_data_path = os .path.join(self.data_devices_path, "ha_area.json")
        entities_data_path = os.path.join(self.data_devices_path, "lights", "ha_entities_light.json")
        states_data_path = os.path.join(self.data_devices_path, "lights", "ha_states_light.json")
        devices_data = json_read(devices_data_path, {})
        entities_data = json_read(entities_data_path, {})
        states_data = json_read(states_data_path, {})
        area_data = json_read(area_data_path, {})
        assert len(devices_data) > 0
        assert len(entities_data) > 0
        assert len(states_data) > 0
        assert len(area_data) > 0
        self.devices_list = {}
        for device_data_item in devices_data:
            device_item = DeviceData(device_data_item)
            self.devices_list[device_item.id] = device_item

        self.entities_list = {}
        for light_entities_data_item  in entities_data:
            light_entity = LightEntity(light_entities_data_item)
            self.entities_list[light_entity.entity_id] = light_entity

        for entity_state_data in states_data:
            entity_id = entity_state_data.get("entity_id")
            assert entity_id in self.entities_list.keys()
            self.entities_list[entity_id].fill_by_ha_state(entity_state_data)
        
        self.area_list = {}
        for area_data_item in area_data:
            self.area_list[area_data_item.get("area_id")] = {"name": area_data_item.get("name")}

        for light_entity in self.entities_list.values():
            if not light_entity.is_group_state():
                if light_entity.device_id is None:
                    continue
                light_entity.link_device(self.devices_list.get(light_entity.device_id))
            else:
                for child_entity_id in light_entity.attributes.get("entity_id"):
                    if child_entity_id not in self.entity_groups.keys():
                        self.entity_groups[child_entity_id] = []
                    self.entity_groups[child_entity_id].append(light_entity.entity_id)
        

        
