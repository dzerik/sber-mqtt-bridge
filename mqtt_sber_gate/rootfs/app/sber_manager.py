# managers/sber_manager.py
import logging

logger = logging.getLogger(__name__)

class SberManager:
    def __init__(self, devices_db):
        self.devices_db = devices_db

    def handle_command(self, command_data):
        """Обрабатывает команду от Sber"""
        logger.info("Received Sber command: %s", command_data)
        updated_devices = []
        
        for device_id, device_states in command_data['devices'].items():
            device = self.devices_db.devices.get(device_id)
            if not device:
                logger.warning("Device not found: %s", device_id)
                continue
                
            changes_made = device.process_cmd("sber", {s['key']: self._parse_sber_value(s) for s in device_states['states']})
            
            if changes_made:
                self.devices_db._save()
                updated_devices.append(device_id)
                
        return updated_devices

    def _parse_sber_value(self, state):
        """Преобразует значение из формата Sber в Python"""
        value_info = state['value']
        if 'bool_value' in value_info:
            return value_info['bool_value']
        elif 'integer_value' in value_info:
            return value_info['integer_value'] / 10  # Для температуры
        elif 'string_value' in value_info:
            return value_info['string_value']
        return None
