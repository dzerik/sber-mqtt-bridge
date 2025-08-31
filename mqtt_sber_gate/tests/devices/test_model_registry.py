import os
import unittest

from devices_db import json_read
from model_registry import ModelRegistry
from test_device_base import TestDevicesBase


class TestModelRegistry(TestDevicesBase):

    def setUp(self) -> None:
        super().setUp()

    def test_get_model(self):
        assert len(self.model_registry.get_models()) == 2

    def test_to_sber_json(self):
        json_data = self.model_registry.to_sber_json()
        sample_data = json_read(os.path.join(self.data_devices_path, "lights", "sample_sber_light_models.json"), {})
        assert json_data is not None
        assert sample_data is not None

        self.assertDictEqual(sample_data, json_data)
        

