from mqtt_sber_gate.tests.devices.test_device_base import TestDevicesBase


class TestConfigurationStructures (TestDevicesBase):
    def setUp(self):
        return super().setUp()
    
    def test_device_up_config(self):
        device_objects = []
        for [entity_id, entity] in self.entities_list.items():
            if not entity.is_group_state():
                entity_config = entity.to_sber_state()
                device_objects.append(entity_config)
        
        assert len(device_objects) > 0
