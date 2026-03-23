from devices_db import CDevicesDB


class DevicesConverter:
    """
    Класс преобразует устройства из Home Assistant в внутренний формат
    и регистрирует их в EntitiesStore через update_by_ha_state.
    """
    def __init__(self, deviceDB: CDevicesDB, logger):
        self._deviceDB = deviceDB
        self._logger = logger

    def create_by_entities_store(self, id, s):
        attr = s['attributes'].get('friendly_name', '')
        self._logger.debug('registering : ' + s['entity_id'] + ' ' + attr)
        self._deviceDB.entities_store.update_by_ha_state(s)

    def update_entities(self, ha_dev):
        for s in ha_dev:
            entity_id = s['entity_id']
            self.create_by_entities_store(entity_id, s)

        self._deviceDB.save_DB()
