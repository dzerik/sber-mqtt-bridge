# devices_db.py
import copy
import json
import os
import logging
from threading import Lock
import threading
from typing import Dict

from devices.device_data import DeviceData
from devices.base_entity import BaseEntity
from devices.climate import ClimateDevice
from devices.light import LightEntity

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

class EntityPlacement_Sber:
    entity_id: str
    home: str = None
    room: str = None
    def __init__(self, entity_id: str, home, room):
        self.entity_id = entity_id
        self.home = home
        self.room = room
        

class EntitiesStore:
    _store: Dict[str, BaseEntity] = {}
    _device_data_store = {}
    _entity_placement_redirection: dict[str, EntityPlacement_Sber] = {} # Тут лежит информация о месте, в котором размещается устройство с т.з. сбера. 
    # Сбер может прислать команду OnMESSAGE: sberdevices/v1/d2ebe7l94jevif0sq1eg/down/change_group_device_request 0 b'{"device_id":"light.spot5_sp","home":"\xd0\x9e\xd0\xb1\xd0\xbe\xd0\xb3\xd0\xb0\xd1\x82\xd0\xb8\xd1\x82\xd0\xb5\xd0\xbb\xd1\x8c\xd0\xbd\xd0\xb0\xd1\x8f","room":"\xd0\xa1\xd0\xbf\xd0\xb0\xd0\xbb\xd1\x8c\xd0\xbd\xd1\x8f"}'
    # и по ней надо поменять атрибуты home и room для устройства. И запомнить их, чтобы в следующий раз уже его размещать в этом месте.
    _deviceConstructorsMap = {
        "light":    lambda ha_state: LightEntity(ha_state),
        "climate":  lambda ha_state: ClimateDevice(ha_state)
    }

    def __init__(self, logger):
        self.logger = logger

    def upsert_device_data(self, data: DeviceData):
        id = data.get("id", None)
        self._device_data_store[id] = data

    def upsert(self, entity: BaseEntity):
        if entity.entity_id in self._store:
            self.logger.info(f"Обновление устройства: {entity.entity_id}")
        else:
            self.logger.info(f"Добавление устройства: {entity.entity_id}")
        self._store[entity.entity_id] = entity
        if entity.linked_device is None:
            if entity.device_id in self._device_data_store:
                entity.link_device(self._device_data_store[entity.device_id])

    def get(self, id: str) -> BaseEntity:
        if id in self._store:
            return self._store[id]
        else:
            return None
    
    @staticmethod
    def _is_ha_state(state: dict) -> bool:
        return "attributes" in state.keys() and "category" in state.keys()

    def create(self, ha_state: dict):
        if EntitiesStore._is_ha_state(ha_state) and ha_state.get('category') in self._deviceConstructorsMap:
            return self._deviceConstructorsMap[ha_state['category']](ha_state)
        else:
            return None
        
    def update_by_ha_state(self, ha_state: dict):
        entity = self._store.get(ha_state['entity_id'], None)
        if entity is not None:
            entity.fill_by_ha_state(ha_state)
   
    def save(self, f):
        saving_objects = {}
        for id, device in self._store.items():
            saving_objects[id] = device.to_ha_state()
        json_write("store_"+f, saving_objects)
        json_write("store_placements.json", self._entity_placement_redirection)

    # def _restore_from_dict(self, data_dict):
    #     """Восстанавливает состояние объекта из словаря"""
    #     for key, value in data_dict.items():
    #         if hasattr(self, key):
    #             setattr(self, key, value)
    #     return self

    def load(self, f):
        loaded_objects = json_read("store_"+f, {})
        for id, ha_state in loaded_objects.items():
            device = self.create(ha_state)
            if device is not None:
                self.upsert(device)
        
        self._entity_placement_redirection = json_read("store_placements.json", {})
        
    def get_placment(self, entity_id: str, default_home: str, default_room: str) -> EntityPlacement_Sber:
        if entity_id in self._entity_placement_redirection:
            return self._entity_placement_redirection[entity_id]
        else:
            return EntityPlacement_Sber(entity_id=entity_id, home=default_home, room=default_room)
    
    def redefine_placement(self, entity_id: str, home: str, room: str):
        self._entity_placement_redirection[entity_id] = EntityPlacement_Sber(entity_id=entity_id, home=home, room=room)

class CDevicesDB:
    """Управление базой данных устройств"""
    _entitiesStore: EntitiesStore = None
    lock: Lock = Lock()
    _dbReadyEvent = threading.Event()
    _db_is_ready = False
    
    def __init__(self, fDB, logger, version):
        self.fDB = fDB
        self.DB = json_read(fDB, {})
        self.logger = logger
        self._entitiesStore = EntitiesStore(logger)
        self._entitiesStore.load(fDB)
        self._categories = {}
        VERSION = version
        
        known_categories = ["light", "climate"]

        # Инициализация параметров устройств
        for id, device in self.DB.items():
            if self.DB[id].get('enabled', None) is None:
                self.DB[id]['enabled'] = False    
            device_instance = self._entitiesStore.create(device)
            if device_instance is not None:
                self._entitiesStore.upsert(device_instance)

        self.mqtt_json_devices_list = '{}'
        self.mqtt_json_states_list = '{}'
        self.http_json_devices_list = '{}'

    @property
    def entitiesStore(self):
        return self._entitiesStore

    @property
    def resCategories(self):
        resCategories = {"categories": []}
        for id in self._categories:
            resCategories["categories"].append(id)
        return resCategories
    
    @property
    def categories(self):
        return self._categories
    
    def setReady(self):
        self._db_is_ready = True
        self._dbReadyEvent.set()

    def waitReady(self):
        if not self._db_is_ready:
            self._dbReadyEvent.wait()

    def setCategories(self, categories):
        self._categories = categories.copy()

    def NewID(self, a):
        for i in range(1, 99):
            r = f"{a}_{str(i).zfill(2)}"
            if self.DB.get(r, None) is None:
                return r

    def save_DB(self):
        logger.debug("Сохранение базы устройств - fake")
        # json_write(self.fDB, self.DB)
        # self._deviceStore.save(self.fDB)

    def clear(self):
        self.DB = {}
        # self.save_DB()
        logger.info("База устройств очищена!")

    def dev_del(self, id):
        self.DB.pop(id, None)
        # self.save_DB()
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
        with self.lock:
            if id in self.DB:
                for k, v in d.items():
                    self.DB[id][k] = v
                self.save_DB()

    def upsert(self, id, d):
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
            self.DB[id] = copy.deepcopy(defaults)

        for k, v in d.items():
            self.DB[id][k] = v

        if not self.DB[id]['name']:
            self.DB[id]['name'] = self.DB[id]['friendly_name']


    def update(self, id, d):
        with self.lock:
            self.upsert(id, d)
        # self.save_DB()

    # def save_DB(self):
    #     json_write(self.fDB, self.DB)
    #     self._deviceStore.save(self.fDB)


    def do_mqtt_json_devices_list(self, entitiesList = None):
        if not self._db_is_ready:
            return None
        
        # Реализация как в оригинале...
        device_list = {}
        device_list['devices']=[]
        device_list['devices'].append(
            {
                "id": "root", 
                "name": "Вумный контроллер", 
                'hw_version':VERSION, 
                'sw_version':VERSION,
                'model': {
                    'id': 'ID_root_hub', 
                    'manufacturer': 'Janch', 
                    'model': 'VHub', 
                    'description': "HA MQTT SberGate HUB", 
                    'category': 'hub', 
                    'features': ['online']
                }
             })
        
        with self.lock:
            for k,v in self.DB.items():
                if entitiesList is not None and k not in entitiesList:
                    continue

                entity = None
                default_home = v.get("home", None)
                default_room = v.get("room", None)

                entity = self.entitiesStore.get(k)
                if entity is None:
                    if not v.get('enabled',False):
                        continue

                    d={'id': k, 'name': v.get('name',''), 'default_name': v.get('default_name','')}

                    d['room']=v.get('room','')
                    d['hw_version']=v.get('hw_version','')
                    d['sw_version']=v.get('sw_version','')
                    dev_cat=v.get('category','relay')
                    c=self.categories.get(dev_cat)
                    f=[]
                    for ft in c:
                        if ft.get('required',False):
                            f.append(ft['name'])
                        else:
                            for st in self.get_states(k):
                                if ft['name'] == st:
                                    f.append(ft['name'])

                    d['model']={'id': 'ID_'+dev_cat, 'manufacturer': 'Janch', 'model': 'Model_'+dev_cat, 'category': dev_cat, 'features': f}
                    d['model_id']=''
                else:
                    d = entity.to_sber_state()
                    if 'room' in d:
                        default_room = d["room"]
                    if 'home' in d:
                        default_home = d["home"]

                device_placement = self.entitiesStore.get_placment(k, default_home, default_room)
                if device_placement is not None:
                    if device_placement.home is not None:
                        d['home'] = device_placement.home
                    if device_placement.room is not None:
                        d['room'] = device_placement.room

                if d is not None:
                    filtered = {k: v for k, v in d.items() if v}
                    device_list['devices'].append(filtered)

        self.mqtt_json_devices_list=json.dumps(device_list)
#        logger.debug('New Devices List for MQTT ')
        json_write("new_devices_list.json", self.mqtt_json_devices_list)
        logger.debug('Sent new Devices List for MQTT ') #+self.mqtt_json_devices_list)
        return self.mqtt_json_devices_list


    def do_mqtt_json_states_list(self, dl):
        if not self._db_is_ready:
            return None
        DStat={}
        DStat['devices']={}
        if len(dl) == 0:
            dl=self.DB.keys()
        with self.lock:
            for id in dl:
                entity = self.entitiesStore.get(id)
                if (entity is None):
                    device=self.DB.get(id,None)
                    if not (device is None):
                        if device['enabled']:
                            device_category=device.get('category',None)
                            if device_category is None:
                                device_category='relay'
                                self.DB[id]['category']=device_category
                            DStat['devices'][id]={}
                            features=self.categories.get(device_category)
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
                else:
                    entityState = entity.to_sber_current_state()
                    if entityState is not None:
                        DStat['devices']  |= entityState

        if (len(DStat['devices']) == 0):
            DStat['devices']={"root": {"states": [{"key": "online", "value": {"type": "BOOL", "bool_value": True}}]}}
        self.mqtt_json_states_list=json.dumps(DStat)
        json_write("new_states_list.json", self.mqtt_json_states_list)
        self.logger.debug("Отправка состояний в Sber 'new_states_list.json'")
        return self.mqtt_json_states_list

    def do_http_json_devices_list(self):
        if not self._db_is_ready:
            logger.info("DB is not ready")
            return None
        Dev={}
        Dev['devices']=[]
        x=[]
        with self.lock:
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
        json_write("http_devices_list.json", self.http_json_devices_list)
        self.logger.debug("Sent http device list ('http_devices_list.json')")
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
    
    def upsert_device_data(self, device_data):
        with self.lock:
            self._entitiesStore.upsert_device_data(device_data)
