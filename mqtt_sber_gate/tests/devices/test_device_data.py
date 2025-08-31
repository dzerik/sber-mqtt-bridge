from os import path
from devices.device_data import DeviceData
from devices_db import json_read
from mqtt_sber_gate.tests.devices.test_device_base import TestDevicesBase


class TestDeviceData(TestDevicesBase):

    def test_device_registry_load(self):
        file_name = path.join(self.data_devices_path, "device_registry.json")
        self.deviceList = json_read(file_name, {})
        i = 0
        for device_data in self.deviceList:
            device_inst = DeviceData(device_data)
            assert device_inst.id is not None
            assert device_inst.original_name is not None, f"Device {device_inst.id} has no original_name"
            i = i + 1
        assert i > 0

