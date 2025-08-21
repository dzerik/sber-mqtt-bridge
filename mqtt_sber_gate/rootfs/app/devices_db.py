# devices_db.py
import json
import os
import logging

logger = logging.getLogger(__name__)
VERSION = "0.0.1"

def json_read(f, defaultValue):
    try:
        with open(f, 'r', encoding='utf-8') as file:
            return json.load(file)
    except Exception as e:
        logger.info(f'!!! Неверная конфигурация в файле: {f} ({e})')
        return defaultValue

def json_write(f, d):
    with open(f, "w", encoding='utf-8') as file:
        json.dump(d, file, indent=4)

class DevicesStore:
    _store = []

    def __init__(self, logger):
        self.logger = logger

    def store(self, device):
        self._store.append(device)

class CDevicesDB:
    """Управление базой данных устройств"""
    _deviceStore = None
    
    def __init__(self, fDB, logger):
        self.fDB = fDB
        self.DB = json_read(fDB, {})
        self.logger = logger
        self._deviceStore = DevicesStore(logger)
        
        # Инициализация параметров устройств
        for id in self.DB:
            if self.DB[id].get('enabled', None) is None:
                self.DB[id]['enabled'] = False

        self.mqtt_json_devices_list = '{}'
        self.mqtt_json_states_list = '{}'
        self.http_json_devices_list = '{}'

    @property
    def deviceStore(self):
        return self._deviceStore

    def NewID(self, a):
        for i in range(1, 99):
            r = f"{a}_{str(i).zfill(2)}"
            if self.DB.get(r, None) is None:
                return r

    def save_DB(self):
        json_write(self.fDB, self.DB)

    def clear(self):
        self.DB = {}
        self.save_DB()
        logger.info("База устройств очищена!")

    def dev_del(self, id):
        self.DB.pop(id, None)
        self.save_DB()
        logger.info(f"Устройство удалено: {id}")

    def dev_inBase(self, id):
        return id in self.DB

    def change_state(self, id, key, value):
        if id not in self.DB:
            logger.info(f"Device id={id} не найден")
            return

        if self.DB[id].get('States', None) is None:
            self.DB[id]['States'] = {}

        self.DB[id]['States'][key] = value
        logger.debug(f"Состояние изменено: {id}.{key} = {value}")

    def get_states(self, id):
        return self.DB.get(id, {}).get('States', {})

    def get_state(self, id, key):
        return self.get_states(id).get(key, None)

    def update_only(self, id, d):
        if id in self.DB:
            for k, v in d.items():
                self.DB[id][k] = v
            self.save_DB()

    def update(self, id, d):
        defaults = {
            'enabled': False,
            'name': '',
            'default_name': '',
            'nicknames': [],
            'home': '',
            'room': '',
            'groups': [],
            'model_id': '',
            'category': '',
            'hw_version': f'Unknown',
            'sw_version': f'Unknown'
        }

        if id not in self.DB:
            self.DB[id] = defaults.copy()

        for k, v in d.items():
            self.DB[id][k] = v

        if not self.DB[id]['name']:
            self.DB[id]['name'] = self.DB[id]['friendly_name']

        self.save_DB()

    def do_mqtt_json_devices_list(self):
        # Реализация как в оригинале...
        device_list = {}
        device_list['devices']=[]
        device_list['devices'].append({"id": "root", "name": "Вумный контроллер", 'hw_version':VERSION, 'sw_version':VERSION })
        device_list['devices'][0]['model']={'id': 'ID_root_hub', 'manufacturer': 'Janch', 'model': 'VHub', 'description': "HA MQTT SberGate HUB", 'category': 'hub', 'features': ['online']}
        for k,v in self.DB.items():
            if v.get('enabled',False):
                d={'id': k, 'name': v.get('name',''), 'default_name': v.get('default_name','')}
                d['home']=v.get('home','Мой дом')
                d['room']=v.get('room','')
            #            d['groups']=['Спальня']
                d['hw_version']=v.get('hw_version','')
                d['sw_version']=v.get('sw_version','')
                dev_cat=v.get('category','relay')
                c=Categories.get(dev_cat)
                f=[]
                for ft in c:
                    if ft.get('required',False):
                        f.append(ft['name'])
                    else:
                        for st in self.get_states(k):
                            if ft['name'] == st:
                                f.append(ft['name'])

                d['model']={'id': 'ID_'+dev_cat, 'manufacturer': 'Janch', 'model': 'Model_'+dev_cat, 'category': dev_cat, 'features': f}
            #            logger.info(d['model'])
                d['model_id']=''
                device_list['devices'].append(d)
        self.mqtt_json_devices_list=json.dumps(device_list)
        logger.debug('New Devices List for MQTT: '+self.mqtt_json_devices_list)
        return self.mqtt_json_devices_list


    def do_mqtt_json_states_list(self, dl):
        DStat={}
        DStat['devices']={}
        if (len(dl) == 0):
            dl=self.DB.keys()
        for id in dl:
            device=self.DB.get(id,None)
            if not (device is None):
                if device['enabled']:
                    device_category=device.get('category',None)
                    if device_category is None:
                        device_category='relay'
                        self.DB[id]['category']=device_category
                    DStat['devices'][id]={}
                    features=Categories.get(device_category)
                    if self.DB[id].get('States',None) is None:
                        self.DB[id]['States']={}
                    r=[]
                    for ft in features:
                        state_value = self.DB[id]['States'].get(ft['name'],None)
                        if state_value is None:
                            if ft.get('required',False):
                                self.logger.info('отсутствует обязательное состояние сущности: ' + ft['name'])
                                self.DB[id]['States'][ft['name']]=self.DefaultValue(ft)
                        if not (self.DB[id]['States'].get(ft['name'], None) is None):
                            r.append(self.StateValue(id,ft))
                            if ft['name'] == 'button_event':
                                self.DB[id]['States']['button_event']=''
                    DStat['devices'][id]['states']=r
    #               if (s is None):
    #                  logger.info('У объекта: '+id+'отсутствует информация о состояниях')
    #                  self.DB[id]['States']={}
    #                  self.DB[id]['States']['online']=True
    #               DStat['devices'][id]['states']=self.DeviceStates_mqttSber(id)

        if (len(DStat['devices']) == 0):
            DStat['devices']={"root": {"states": [{"key": "online", "value": {"type": "BOOL", "bool_value": True}}]}}
        self.mqtt_json_states_list=json.dumps(DStat)
        self.logger.debug(f"Отправка состояний в Sber: {self.mqtt_json_states_list}")
        return self.mqtt_json_states_list

    def do_http_json_devices_list(self):
        Dev={}
        Dev['devices']=[]
        x=[]
        for k,v in self.DB.items():
            r={}
            r['id']=k
            r['name']=v.get('name','')
            r['default_name']=v.get('default_name','')
            r['nicknames']=v.get('nicknames',[])
            r['home']=v.get('home','')
            r['room']=v.get('room','')
            r['groups']=v.get('groops',[])
            r['model_id']=v['model_id']
            r['category']=v.get('category','')
            r['hw_version']=v.get('hw_version','')
            r['sw_version']=v.get('sw_version','')
            x.append(r)
            Dev['devices'].append(r)
        self.http_json_devices_list=json.dumps({'devices':x})
        return self.http_json_devices_list

    # Остальные методы и логика класса
    def do_http_json_devices_list_2(self):
        return json.dumps({'devices':self.DB})
    
    def DefaultValue(self,feature):
        t=feature['data_type']
        dv_dict={
            'BOOL': False,
            'INTEGER': 0,
            'ENUM': ''
        }
        v=dv_dict.get(t, None)
        if v is None:
            logger.info('Неизвестный тип даных: '+t)
            return False
        else:
            if feature['name'] == 'online':
                return True
            else:
                return v
      
    def StateValue(self,id,feature):
      #{'key':'online','value':{"type": "BOOL", "bool_value": True}}
        State=self.DB[id]['States'][feature['name']]
        if feature['name'] == 'temperature':
            State=State*10
        if feature['data_type'] == 'BOOL':
            r={'key':feature['name'],'value':{'type': 'BOOL', 'bool_value': bool(State)}}
        if feature['data_type'] == 'INTEGER':
            r={'key':feature['name'],'value':{'type': 'INTEGER', 'integer_value': int(State)}}
        if feature['data_type'] == 'ENUM':
            r={'key':feature['name'],'value':{'type': 'ENUM', 'enum_value': State}}
        logger.debug(id+': '+str(r))
        return r

