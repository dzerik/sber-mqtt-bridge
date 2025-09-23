from devices_db import CDevicesDB

class DevicesConverter:
    """ 
    Класс предназначен для преобразования устройств из Home Assistant в внутренний формат и диспетчеризации их регистрации в deviceDB.
    Это касается старых устройств. Устройства, унаследованные от BaseEntity обрабатываются единым способом - через update_by_ha_state.
    """
    def __init__(self, deviceDB: CDevicesDB, logger):
        self._deviceDB = deviceDB
        self._logger = logger
        self.ha_device_converters_dict={
        'switch': self.upd_sw,
        'light': self.create_by_entities_store,
        'script': self.upd_scr,
        'sensor': self.upd_sensor,
        'button': self.upd_button,
        'input_boolean': self.upd_input_boolean,
        'climate': self.upd_climate,
        'hvac_radiator': self.upd_hvac_radiator,
        'cover': self.create_by_entities_store
        }

    def create_by_entities_store(self, id, s):
        attr=s['attributes'].get('friendly_name','')
        self._logger.debug('registering : ' + s['entity_id'] + ' '+attr)
        self._deviceDB.entities_store.update_by_ha_state(s)

    def upd_sw(self, id, s):
        attr=s['attributes'].get('friendly_name','')
        self._logger.debug('switch: ' + s['entity_id'] + ' '+attr)
        self._deviceDB.upsert(s['entity_id'],{'entity_ha': True,'entity_type': 'sw','friendly_name':attr,'category': 'relay'})

    def upd_scr(self, id, s):
        attr=s['attributes'].get('friendly_name','')
        self._logger.debug('script: ' + s['entity_id'] + ' '+attr)
        self._deviceDB.upsert(s['entity_id'],{'entity_ha': True,'entity_type': 'scr','friendly_name':attr,'category': 'relay'})

    def upd_sensor(self, id, s):
        dc=s['attributes'].get('device_class','')
        fn=s['attributes'].get('friendly_name','')
        if dc == 'temperature':
        #      self.logger.info('Сенсор температуры: ' + id + ' ' + fn)
            self._deviceDB.upsert(id,{'entity_ha': True,'entity_type': 'sensor_temp', 'friendly_name': fn,'category': 'sensor_temp'})
        #   if dc == 'pressure':
        #      self.deviceDB.update(id,{'entity_ha': True,'entity_type': 'sensor_pressure', 'friendly_name': fn,'category': 'sensor_pressure'})


    def upd_button(self, id, s):
        dc=s['attributes'].get('device_class','')
        fn=s['attributes'].get('friendly_name','')
        self._logger.debug('button: ' + s['entity_id'] + ' '+fn+'('+dc+')')
        self._deviceDB.upsert(id,{'entity_ha': True,'entity_type': 'button', 'friendly_name': fn,'category': 'relay'})

    def upd_input_boolean(self, id, s):
        dc=s['attributes'].get('device_class','')
        fn=s['attributes'].get('friendly_name','')
        self._logger.debug('input_boolean: ' + s['entity_id'] + ' '+fn+'('+dc+')')
        self._deviceDB.upsert(id,{'entity_ha': True,'entity_type': 'input_boolean', 'friendly_name': fn,'category': 'scenario_button'})

    def upd_climate(self, id, s):
        dc=s['attributes'].get('device_class','')
        fn=s['attributes'].get('friendly_name','')
        self._logger.debug('climate: ' + s['entity_id'] + ' '+fn+'('+dc+')')
        self._deviceDB.upsert(id,{'entity_ha': True,'entity_type': 'climate', 'friendly_name': fn,'category': 'hvac_ac'})

    def upd_hvac_radiator(self, id, s):
        dc=s['attributes'].get('device_class','')
        fn=s['attributes'].get('friendly_name','')
        if dc == 'temperature':
        #      self.logger.info('Радиатор отопления: ' + id + ' ' + fn)
            self._deviceDB.upsert(id,{'entity_ha': True,'entity_type': 'hvac_radiator', 'friendly_name': fn,'category': 'hvac_radiator'})

    def upd_default(self, id, s):
        self._logger.debug('Неиспользуемый тип: ' + s['entity_id'])
        pass

    def update_entities(self, ha_dev):
        # Converting ha devices to internal representation
        for s in ha_dev:
            entity_id = s['entity_id']
            a,_=entity_id.split('.',1)
            self.ha_device_converters_dict.get(a, self.upd_default)(s['entity_id'],s)

        self._deviceDB.save_DB()
