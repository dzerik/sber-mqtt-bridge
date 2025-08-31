from devices.base_entity import BaseEntity
from devices.device_data import DeviceData
from devices.device_model import DeviceModel


class ModelRegistry:
    registry: dict[str, DeviceModel] = {}

    def register(self, entity: BaseEntity):
        assert entity.is_filled_by_state
        assert entity.linked_device is not None
        if entity.linked_device.model not in self.registry.keys():
            self.registry[entity.linked_device.model] = DeviceModel(entity)

    def get_models(self):
        return self.registry
    
    def to_sber_json(self):
        res = []
        for model in self.registry.values():
            if model.id not in res:
                res.append(
                    {
                        "id": model.id,
                        "manufacturer": model.manufacturer,
                        "model": model.model_name,
                        "hw_version": model.hw_version,
                        "sw_version": model.sw_version,
                        "description": model.description,
                        "category": model.category,
                        "features": model.features,
                        "dependencies": {},
                        "allowed_values": {},
                    }
                )
        return {"models": res}
