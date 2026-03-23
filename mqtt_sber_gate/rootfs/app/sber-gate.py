#!/usr/bin/python3
# -*- coding: utf-8 -*-

import asyncio
import os
import sys
import ssl
import time
import json
import logging

from devices.devices_converter import DevicesConverter
from devices_db import CDevicesDB, json_read, json_write
from http_server import MyServer
import paho
import random
import requests
from web_socket_handler import WebSocketHandler, async_publish
import websocket
import threading
# deprecated import pkg_resources
import paho.mqtt.client as mqtt
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

import importlib.metadata

try:
    VERSION = importlib.metadata.version("mqtt-sber-gate-oop")
except importlib.metadata.PackageNotFoundError:
    # Фallback-значение, если пакет не найден
    VERSION = "0.0.3"

#import locale
#locale.getpreferredencoding()
import importlib.metadata

try:
    # Замените "sber-gate" на имя вашего пакета (как указано в setup.py/pyproject.toml)
    VERSION = importlib.metadata.version("sber-gate")
except importlib.metadata.PackageNotFoundError:
    # Фallback-значение, если пакет не найден
    VERSION = "0.0.3"


# VERSION = '0.0.3'
LOG_FILE = 'SberGate.log'
LOG_FILE_MAX_SIZE = 1024*1024*7
# log_level = 3
HA_AREA = {}

# Проверка размера файла логов
if os.path.isfile(LOG_FILE):
    if os.path.getsize(LOG_FILE) > LOG_FILE_MAX_SIZE:
        os.remove(LOG_FILE)

# Инициализация корневого логгера
root_logger = logging.getLogger()
root_logger.setLevel(logging.DEBUG)  # Значение по умолчанию

# Формат сообщений
formatter = logging.Formatter('%(asctime)s %(levelname)s: %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

# Логирование в файл
file_handler = logging.FileHandler(LOG_FILE, mode='w')
file_handler.setFormatter(formatter)
root_logger.addHandler(file_handler)

# Логирование в консоль
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
root_logger.addHandler(console_handler)

# Используем отдельный логгер для модуля
logger = logging.getLogger(__name__)


# fOptions=os.path.join(os.getcwd(), "data", "debug-data", "options.json")
fOptions='options.json'
fDevicesDB='devices.json'
fCategories='categories.json'

#*******************************
def options_change(k,v):
   t=Options.get(k,None)
   if (t is None):
      logger.info('В настройках отсутствует параметр: '+k+' (добавляю.)')
   if (t != v):
      Options[k]=v
      logger.info('В настройках изменился параметр: '+k+' с '+str(t)+' на '+str(v)+' (обновляю и сохраняю).')
      json_write(fOptions,Options)

#-------------------------------------------------
def on_connect_local(mqttc, obj, flags, rc):
   logger.info("HA Connect Local Broker, rc: " + str(rc))

#-------------------------------------------------
def on_connect(mqttc, obj, flags, rc):
   if rc==0:
      logger.info("Connect OK SberDevices Broker, rc: " + str(rc))
      mqttc.subscribe(stdown+"/#", 0)
      mqttc.subscribe("sberdevices/v1/__config", 0)
   else:
      logger.info("Connect Fail SberDevices Broker, rc: " + str(rc))
#0: Connection successful
#1: Connection refused – incorrect protocol version
#2: Connection refused – invalid client identifier
#3: Connection refused – server unavailable
#4: Connection refused – bad username or password
#5: Connection refused – not authorised
#6-255: Currently unused.

def on_disconnect(client, userdata, rc):
    if rc != 0:
        logger.info("Unexpected MQTT disconnection. Will auto-reconnect. rc: "+str(rc))

def on_message(mqtts, ws, msg):
   logger.info("OnMESSAGE: "+msg.topic + " " + str(msg.qos) + " " + str(msg.payload))
   if msg.topic and msg.topic.endswith('/down/change_group_device_request'):
      try:
         data = json.loads(msg.payload)
      except json.JSONDecodeError as e:
         logger.error(f"Ошибка декодирования JSON: {e}")      
         return
      device_id = data.get("device_id")
      if device_id is not None:
         DevicesDB.entities_store.redefine_placement(device_id, data.get("home", None), data.get("room", None))
         DevicesDB.entities_store.save()
         payload = DevicesDB.do_mqtt_json_devices_list([device_id])
         if payload is not None and len(payload) > 0:
           mqttc.publish(sber_root_topic+'/up/config', payload, qos=0)

   if msg.topic.endswith('/down/rename_device_request'):
      data = json.loads(msg.payload)
      device_id = data.get("device_id", None)
      new_name = data.get("new_name", None)
      if device_id is not None and new_name is not None:
         DevicesDB.entities_store.rename_entity(device_id, new_name)
         DevicesDB.entities_store.save()
         payload = DevicesDB.do_mqtt_json_devices_list([device_id])
         if payload is not None and len(payload) > 0:
            mqttc.publish(sber_root_topic+'/up/config', payload, qos=0)

def on_publish(mqttc, obj, mid):
    logger.info("mid: " + str(mid))

def on_subscribe(mqttc, obj, mid, granted_qos):
    logger.info("SD Subscribed: " + str(mid) + " " + str(granted_qos))

def on_log(mqttc, obj, level, string):
    logger.info("OnLOG: "+string)

def send_status(mqttc, s):
    infot = mqttc.publish(sber_root_topic+'/up/status', s, qos=0)

#*** sber MQTT client setup *****************************************
def on_message_cmd(mqttc, obj, msg):
   data=json.loads(msg.payload)
   logger.info("(on_message_cmd) Sber MQTT Command: " + str(data))
   for id,cmd_data in data['devices'].items():
      entity = DevicesDB.entities_store.get(id)
      if entity is None:
         logger.warning(f'(on_message_cmd) Неизвестная сущность: {id}')
         continue
      logger.info(f"(on_message_cmd) Изменяем состояние объекта: {id}")
      processing_result = entity.process_cmd(cmd_data)
      for payload in processing_result:
         command_to_send = payload.get("url", None)
         if command_to_send is not None:
            ws_server.send_command(command_to_send)

def on_message_stat(mqttc, obj, msg):
   try:
      data=json.loads(msg.payload).get('devices',[])
      if (len(data) == 1) and data[0] == "": # Это какой-то непонятный приход от сбера - пустой идентификатор сущности.
         data = [] 
   except:
      data=[]
   logger.info("GetStatus: "  +  str(msg.payload))
   send_status(mqttc,DevicesDB.do_mqtt_json_states_list(data))
   logger.info("Answer: "+DevicesDB.mqtt_json_states_list)

def on_errors(mqttc, obj, msg):
   error_message = str(msg.payload)
   logger.info("Sber MQTT Errors: " + msg.topic + " " + str(msg.qos) + " " + error_message)

def on_message_conf(mqttc, obj, msg):
   logger.info("Config: wait for readiness device DB")
   DevicesDB.waitReady()
   logger.info("Config: " + msg.topic + " " + str(msg.qos) + " " + str(msg.payload))
   device_list = DevicesDB.do_mqtt_json_devices_list()
   mqttc.publish(sber_root_topic+'/up/config', device_list, qos=0)

def on_global_conf(mqttc, obj, msg):
   data=json.loads(msg.payload)
   options_change('sber-http_api_endpoint',data.get('http_api_endpoint',''))

#********** Start **********************************

Options=json_read(fOptions, {})
log_level = Options.get('log_level','INFO')

# Установка уровня логирования из опций
log_level_str = Options.get('log_level', 'INFO').upper()
log_level = getattr(logging, log_level_str, logging.INFO)
root_logger.setLevel(log_level)


#https://developers.sber.ru/docs/ru/smarthome/c2c/value
sber_types={'FLOAT':'float_value','INTEGER':'integer_value','STRING':'string_value','BOOL':'bool_value','ENUM':'enum_value','JSON':'','COLOUR':'colour_value'}
#
if os.path.isfile(LOG_FILE):
   if os.path.getsize(LOG_FILE)>LOG_FILE_MAX_SIZE:
      os.remove(LOG_FILE)
logger.info('Start MQTT SberGate IoT Agent for Home Assistant version: '+VERSION)
logger.info("Запущено в системе: "+ os.name)
logger.info("Версия Python     : "+ sys.version)
logger.info("Размещение скрипта: "+ os.path.realpath(__file__))
logger.info("Текущая директория: "+ os.getcwd())
logger.info("Размер Log файла  : "+ str(os.path.getsize(LOG_FILE)))
logger.info("Log Level         : "+ Options.get('log_level','info'))
#logger.info("LOG_FILE_MAX_SIZE : "+ str(LOG_FILE_MAX_SIZE)
logger.info("Кодировка         : "+ sys.getdefaultencoding())
logger.info("Список файлов     : "+ str(os.listdir('.')))
#logger.info("Список файлов2   : "+ str(os.listdir('../app/data')))
#logger.info(": "+ sys.getfilesystemencoding())
#logger.info(": "+ sys.getfilesystemencodeerrors())
#logger.info(": "+ str(sys.maxunicode))

#installed_packages = pkg_resources.working_set
#installed_packages_list = sorted(["%s==%s" % (i.key, i.version) for i in installed_packages])
#pkg=[]
#for i in pkg_resources.working_set:
#   pkg.append(i.key)
#logger.info(pkg)

#sys.setdefaultencoding('utf8')
#print(sys.stdout.encoding)

# TODO remove fDevicesDB - it's not used
if not os.path.exists(fDevicesDB):
   json_write(fDevicesDB,{})

DevicesDB=CDevicesDB(fDevicesDB, logger, VERSION)
DevicesConverterInstance = DevicesConverter(DevicesDB, logger)

#******************* Configure Local client (HA Broker)
#mqttHA = mqtt.Client("SberDevicesAgent local client")
#mqttHA.on_connect = on_connect_local
#mqttHA.username_pw_set(Options['ha-mqtt_login'], Options['ha-mqtt_password'])
#mqttHA.connect(Options['ha-mqtt_broker'], Options['ha-mqtt_broker_port'], 60)

#******************* Configure client (SberDevices Broker)
#mqttc = mqtt.Client("HA client")
mqttc = mqtt.Client()
mqttc.on_connect = on_connect
mqttc.on_subscribe = on_subscribe
#mqttc.on_publish = on_publish
mqttc.on_message = on_message
mqttc.on_disconnect = on_disconnect
# Uncomment to enable debug messages
#mqttc.on_log = on_log
mqttc.message_callback_add("sberdevices/v1/__config", on_global_conf)
sber_root_topic='sberdevices/v1/'+Options['sber-mqtt_login']
stdown=sber_root_topic + "/down"
mqttc.message_callback_add(stdown+"/errors", on_errors)
mqttc.message_callback_add(stdown+"/commands", on_message_cmd)
mqttc.message_callback_add(stdown+"/status_request", on_message_stat)
mqttc.message_callback_add(stdown+"/config_request", on_message_conf)

#mqttc = mqtt.Client("",0)
mqttc.username_pw_set(Options['sber-mqtt_login'], Options['sber-mqtt_password'])
mqttc.tls_set(certfile=None, keyfile=None, cert_reqs=ssl.CERT_NONE, tls_version=None)
mqttc.tls_insecure_set(True)
mqttc.connect(Options['sber-mqtt_broker'], Options['sber-mqtt_broker_port'], 60)

#*********************************
mqttc.loop_start()
#mqttHA.loop_start()

#Хитрое получение sber-http_api_endpoint от Сберовского MQTT из глобальной конфигурации. Типа только после этого можно идти дальше, но...
if Options.get('sber-http_api_endpoint',None) is None:
   options_change('sber-http_api_endpoint','')
while (Options['sber-http_api_endpoint'] == ''):
   logger.info('Ожидаем получение SberDevice http_api_endpoint')
   time.sleep(1)
logger.info('SberDevice http_api_endpoint: '+Options['sber-http_api_endpoint'])

hds = {'content-type': 'application/json'}
if not os.path.exists('models.json'):
   logger.info('Файл моделей отсутствует. Получаем...')
   SD_Models = requests.get(Options['sber-http_api_endpoint']+'/v1/mqtt-gate/models', headers=hds,auth=(Options['sber-mqtt_login'], Options['sber-mqtt_password']))
   if SD_Models.status_code == 200:
#      logger.info(SD_Models.text)
      json_write('models.json',SD_Models.json())
   else:
      logger.info('ОШИБКА! Запрос models завершился с ошибкой: '+str(SD_Models.status_code))
   
def GetCategories():
   if not os.path.exists(fCategories):
      logger.info('Файл категорий отсутствует. Получаем...')
      Categories={}
      SD_Categories = requests.get(Options['sber-http_api_endpoint']+'/v1/mqtt-gate/categories', headers=hds,auth=(Options['sber-mqtt_login'], Options['sber-mqtt_password'])).json()
      for id in SD_Categories['categories']:
         logger.info('Получаем опции для категории: '+id)
         SD_Features = requests.get(Options['sber-http_api_endpoint']+'/v1/mqtt-gate/categories/'+id+'/features', headers=hds,auth=(Options['sber-mqtt_login'], Options['sber-mqtt_password'])).json()
         Categories[id]=SD_Features['features']
      json_write('categories.json',Categories)
   else:
      logger.info('Список категорий получен из файла: ' + fCategories)
      Categories=json_read(fCategories, {})
   return Categories

categories=GetCategories()

if categories.get('categories',False):
   logger.info('Старая версия файла категорий, удаляем.')
   os.remove(fCategories)
   logger.info('Повторное получения категорий.')
   categories=GetCategories()

DevicesDB.setCategories(categories)

def start_webserver():
    hostName = ''
    serverPort = 9123

    # Создание HTTP-сервера с передачей зависимостей
    webServer = HTTPServer(
        (hostName, serverPort),
        lambda *args, **kwargs: MyServer(
            *args,
            devices_db=DevicesDB,
            mqttc=mqttc,
            sber_root_topic=sber_root_topic,
            options = Options,
            **kwargs
        )
    )
    logger.info("Server started http://%s:%s" % (hostName, serverPort))

    # Сохраняем ссылку на сервер для последующего закрытия
    global webServer_instance
    webServer_instance = webServer

    tsrv = threading.Thread(target=webServer.serve_forever)
    tsrv.daemon = True
    tsrv.start()
    return {"server": webServer, "thread": tsrv}

def stop_webserver(webServer, tsrv):
    try:
        # Останавливаем сервер
        webServer.shutdown()
        logger.info("Shutting down HTTP server...")
        
        # Ждём завершения потока
        tsrv.join(timeout=5)
        
        # Закрываем сервер
        webServer.server_close()
        logger.info("HTTP server closed.")
    except Exception as e:
        logger.error(f"Error stopping HTTP server: {e}")
ws_url=Options['ha-api_url'].replace('http','ws',1) + '/api/websocket'
logger.info('Start WebSocket Client URL: ' + ws_url)
## websocket.enableTrace(True)

web_server = start_webserver();

ws_server = WebSocketHandler(DevicesDB, DevicesConverterInstance, mqttc, Options)
ws_server.start()

ws_server.join()

stop_webserver(web_server["server"], web_server["thread"])

logger.info("Server stopped.")

#---------------------------------------------

while True:
   time.sleep(10)
   logger.info('Agent HB')
