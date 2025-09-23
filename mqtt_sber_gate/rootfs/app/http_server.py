# http_server.py
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
import re
import logging
import sys
from typing import Dict, Any

import requests

logger = logging.getLogger(__name__)

ext_mime_types = {
    ".html": "text/html",
    ".js": "text/javascript",
    ".css": "text/css",
    ".jpg": "image/jpeg",
    ".png": "image/png",
    ".json": "application/json",
    ".ico": "image/vnd.microsoft.icon",
    ".log": "application/octet-stream",
    "default": "text/plain"
}

static_request = {
    '/SberGate.log': 'SberGate.log',
    '/': '../app/ui2/index.html',
    '/ui2/main.js': '../app/ui2/main.js',
    '/ui2/main.css': '../app/ui2/main.css',
    '/favicon.ico': '../app/ui2/favicon.ico',
    '/index.html': '../app/ui/index.html',
    '/static/css/2.b9b863b2.chunk.css': '../app/ui/static/css/2.b9b863b2.chunk.css',
    '/static/css/main.1359096b.chunk.css': '../app/ui/static/css/main.1359096b.chunk.css',
    '/static/js/2.e21fd42c.chunk.js': '../app/ui/static/js/2.e21fd42c.chunk.js',
    '/static/js/main.a57bb958.chunk.js': '../app/ui/static/js/main.a57bb958.chunk.js',
    '/static/js/runtime-main.ccc7405a.js': '../app/ui/static/js/runtime-main.ccc7405a.js'
}

class MyServer(BaseHTTPRequestHandler):
    def __init__(self, *args, devices_db, mqttc, sber_root_topic, options, **kwargs):
        # Сохраняем зависимости как атрибуты
        self.devices_db = devices_db
        self.mqttc = mqttc
        self.sber_root_topic = sber_root_topic
         
        self.sber_api_endpoint = options['sber-http_api_endpoint']
        self.ha_api_token = options['ha-api_token']
        self.sber_user = options["sber-mqtt_login"]
        self.sber_pass = options["sber-mqtt_password"]
        self.sber_broker = options["sber-mqtt_broker"]

        self.AgentStatus={
            "online": True, 
            "error": "",  
            "credentials": {
                    'username': self.sber_user,
                        "password": self.sber_pass,
                        'broker': self.sber_broker
            }
        }

        self.path_dict={
            '/': self.handle_api_root,

            '/api/v1/status': self.handle_api_status,
            '/api/v1/objects': self.handle_api_objects,
            '/api/v1/transformations': self.handle_api_transformations,
            '/api/v1/aggregations': self.handle_api_aggregations,

            '/api/v1/models': self.handle_api_models,
            '/api/v1/categories': self.handle_api_categories,
#            '/api/v1/categories/relay/features': api_categories_relay_features,

            '/api/v1/devices': self.handle_api_devices,
            '/api/v2/devices': self.handle_api2_devices

        }
        super().__init__(*args, **kwargs)

    def do_DELETE(self):
        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.end_headers()
        self.wfile.write(b'{}')
        logger.info(f'DELETE: {self.path}')
        if self.path.startswith('/api/v1/devices/'):
            device_id = self.path.split('/')[-1]
            self.devices_db.dev_del(device_id)
            self.mqttc.publish(
                f"{self.sber_root_topic}/up/config",
                self.devices_db.do_mqtt_json_devices_list(),
                qos=0
            )

    def do_GET(self):
        # sf = static_request.get(self.path, None)
        # if sf:
        #     self.send_file(sf)
        # else:
        #     handler = getattr(self, f"handle_{self.path}", self.default_handler)
        #     handler()
        sf=static_request.get(self.path, None)
        if sf is None:
            self.path_dict.get(self.path, self.handle_api_default )()
        else:
            self.static_answer(sf)

    def do_PUT(self):
        self.send_data('{}',"application/json")
        logger.info('PUT: '+self.path)
        data=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        api='/api/v1/devices/'
        if self.path[:len(api)] == api:
            dev=self.path[len(api):]
            if (dev == data['id']):
                self.devices_db.update(dev, data)
                infot = self.mqttc.publish(self.sber_root_topic+'/up/config', self.devices_db.do_mqtt_json_devices_list(), qos=0)
        else:
            dev=''
        
    def do_POST(self):
        self.send_data('{}',"application/json")
        logger.info('POST: '+self.path)
        d=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        dict={
            '/api/v1/devices': self.handle_api_devices_post,
            '/api/v2/devices': self.handle_api2_devices_post,
            '/api/v2/command': self.handle_api2_command_post
        }
        dict.get(self.path, self.handle_api_default_post )(d)

    def handle_api_status(self):
        self.send_data(self,json.dumps(self.AgentStatus),"application/json")

    def handle_api_objects(self):
        d='{"objects": [{"id": "__false","description": "Always false fake object","readonly": false},{"id": "__true","description": "Always true fake object","readonly": false}]}'
        self.send_data(self,d,"application/json")

    def handle_api_transformations(self):
        file_path = '../app/data/transformations.json'
        if os.path.exists(file_path):
            f =open( file_path,'r', encoding='utf-8')
            d=f.read()
            f.close()
        else:
            d = {}

        self.send_data(self,d,"application/json")

    def handle_api_aggregations(self):
        d='{"aggregations": ["bool_status_oneof"]}'
        self.send_data(self,d,"application/json")

    def handle_api_models(self):
        d='{"models":[{"id":"root_device","manufacturer":"MQTT","model":"MQTT Root Device","description":"Root device model","features":["online"],"category":"hub"},{"id":"ID_1","manufacturer":"Я","model":"Моя модель","hw_version":"1","sw_version":"1","description":"Моя модель","features":["online","on_off"],"category":"relay"},{"id":"temp_device","manufacturer":"tempDev","model":"Термометр","hw_version":"1","sw_version":"1","description":"Датчик температуры","features":["on_off","online"],"category":"relay"},{"id":"ID_2","manufacturer":"Я","model":"Датчик температуры","hw_version":"v1","sw_version":"v1","description":"Датчик температуры","features":["online","temperature"],"category":"sensor_temp","allowed_values":{"temperature":{"type":"INTEGER","integer_values":{"min":"-400","max":"2000"}}}}]}'
        self.send_data(self,d,"application/json")
        return 'models'

    def handle_api_categories(self):
        logger.info('Запрос категорий')
        #   d='{"categories": ["light","socket","relay","led_strip","hub","ipc","sensor_pir","sensor_door","sensor_temp","scenario_button","hvac_ac","hvac_fan","hvac_humidifier","hvac_air_purifier","hvac_heater","hvac_radiator","hvac_boiler","hvac_underfloor_heating","window_blind","curtain","gate","kettle","sensor_water_leak","valve"]}'
        resCategories = self.devices_db.categories
        d=json.dumps(resCategories)
        self.send_data(self,d,"application/json")

    def static_answer(self,file):
        p,e = os.path.splitext(file)
        m=ext_mime_types.get(e,ext_mime_types['default'])
        if (os.name == 'nt'):
            f=file.replace('/','\\')
        else:
            f=file
        logger.info('Отправка файла: '+f+'; MIME:'+m)
        self.send_file(f)

    def handle_api_default(self):
        #Проверка на запрос features
        get_feature=re.findall(r'/api/v1/categories/(.+)/features',self.path)
        if len(get_feature) == 1:
        #      logger.info('Запрошен: ' + get_feature[0])
            #Получаем список опций для категории в формате Сбер API для возврата по запросу
            resFeatures={'features':self.devices_db.categories.get(get_feature[0],[])}
        #      logger.info('Ответ: ' + json.dumps(resFeatures))
            self.send_data(self,json.dumps(resFeatures),"application/json")
        else:
        #Иначе прокси
            hds =  {'Authorization': 'Bearer '+self.ha_api_token, 'content-type': 'application/json'}
            api='/api/v1/'
            if self.path[:len(api)] == api:
                logger.info('PROXY '+api+': '+self.path)
                url=self.sber_api_endpoint+'/v1/mqtt-gate/' + self.path[len(api):]
                req_v1=requests.get(url, headers=hds, auth=(self.sber_user, self.sber_pass))
                if req_v1.status_code == 200:
        #         logger.info(req_v1.text)
                    self.send_data(req_v1.text,"application/json")
                else:
                    logger.info('ОШИБКА! Запрос: '+url+' завершился с ошибкой: '+str(req_v1.status_code))
            else:
                self.handle_api_default_d()
        #   dict.get(self.path, api_default )(self)

    def handle_api_default_d(self):
        d='<html><head><title>HA</title></head>'\
            '<p>Request: ' + self.path + '</p>'\
            '<body><p>This is an example web server.</p></body></html>'
        self.send_data(d,"text/html")
        return self.path

    # def send_file(self,file,ct):
    #     self.send_response(200) 
    #     self.send_header("Content-type", ct)
    #     self.end_headers()
    #     f = open(file, 'rb')
    #     self.wfile.write(f.read())

    def send_data(self,data,ct):
        self.send_response(200) 
        self.send_header("Content-type", ct)
        self.end_headers()
        self.wfile.write(bytes(data, "utf-8"))
        return 'send_sata'

    def send_file(self, file_path):
        p, e = os.path.splitext(file_path)
        mime_type = ext_mime_types.get(e, ext_mime_types['default'])
        if os.name == 'nt':
            file_path = file_path.replace('/', '\\')
        logger.info(f'Отправка файла: {file_path}; MIME:{mime_type}')
        try:
            with open(file_path, 'rb') as f:
                self.send_response(200)
                self.send_header("Content-type", f"{mime_type}; charset=utf-8")
                self.end_headers()
                self.wfile.write(f.read())
        except Exception as e:
            self.send_error(404, str(e))

    def default_handler(self):
        self.send_error(404, "Not Found")

    def handle_api_root(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        response = (
            "<!doctype html><html lang='en'>"
            "<head><meta charset='utf-8'/>"
            "<title>Интеграция с умным домом Сбер</title></head>"
            "<body><h1>Управление устройствами</h1>"
        )
        for k in self.devices_db.DB:
            # response += f"<p>{k}: {self.devices_db.DB[k]['name']}</p>"
          response += k + ':' + self.devices_db.DB[k]['name']+'<br>'
        response += "</body></html>"
        self.wfile.write(response.encode("utf-8"))

    def handle_api_devices(self):
        data = self.devices_db.do_http_json_devices_list()
        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.end_headers()
        self.wfile.write(data.encode("utf-8"))

    def handle_api2_devices(self):
        self.send_data(self.devices_db.do_http_json_devices_list_2(), "application/json")

    def handle_api_devices_post(self,d):
        logger.info('SberAgent добавляет новое устройство: '+str(d))
        cat=d.get('category','')
        if cat != '':
            id=self.devices_db.NewID(cat)
            self.devices_db.DB[id]={}
            self.devices_db.update(id, d)
            self.devices_db.save_DB()
            infot = self.mqttc.publish(self.sber_root_topic+'/up/config', self.devices_db.do_mqtt_json_devices_list(), qos=0)

    def handle_api_default_post(self,d):
        logger.info('Неизвестный POST запрос '+str(d))

    def handle_api2_devices_post(self,d):
        logger.info('Меняем данные для'+str(d['devices']))
        for i in d['devices']:
            for id,prop in i.items():
                logger.info("hapi2: LOG1"+id+':'+str(prop))
                if self.devices_db.entities_store.get(id):
                    if prop.get("enabled", False):
                        self.devices_db.entities_store.enable_entity(id)
                    else:
                        self.devices_db.entities_store.disable_entity(id)
                else:
                    self.devices_db.update(id, prop)
        devices_list = self.devices_db.do_mqtt_json_devices_list()
        if devices_list and len(devices_list) > 0:
            infot = self.mqttc.publish(self.sber_root_topic+'/up/config', devices_list, qos=0)
            logger.debug(f"(handle_api2_devices_post) Published: {devices_list}")
        self.devices_db.save_DB()

    def handle_api2_command_post(self,d):
        dict={
            'DB_delete': self.devices_db.clear,
            'exit': self._command_exit
        }
        command_func = dict.get(d.get('command', 'unknown'), self._command_default)
        command_func(d)

    def _command_exit(self, d):
        logger.info('Выход. '+str(d))
        sys.exit()

    def _command_default(d):
        logger.info('Получили неизвестную команду'+str(d))

