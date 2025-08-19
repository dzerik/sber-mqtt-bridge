# sber-gate.py (фрагмент)
import json
from devices.base import BaseDevice

class CDevicesDB:
    def __init__(self, db_file):
        self.db_file = db_file
        self.devices = {}
        self._load()

    def _load(self):
        """Загружает устройства из файла"""
        try:
            with open(self.db_file, 'r') as f:
                data = json.load(f)
                for id, config in data.items():
                    device_class = self._get_device_class(config.get('category', 'relay'))
                    self.devices[id] = device_class(id)
                    # Инициализация состояний
                    for key, value in config.get('States', {}).items():
                        setattr(self.devices[id], key, value)
        except FileNotFoundError:
            pass

    def _save(self):
        """Сохраняет устройства в файл"""
        data = {id: {
            'category': device.category,
            'States': {k: v for k, v in device.__dict__.items() if not k.startswith('_')}
        } for id, device in self.devices.items()}
        
        with open(self.db_file, 'w') as f:
            json.dump(data, f, indent=2)

    def _get_device_class(self, category):
        """Динамически получает класс устройства по категории"""
        module = __import__(f'devices.{category}', fromlist=[category])
        return getattr(module, f'{category.capitalize()}Device')
