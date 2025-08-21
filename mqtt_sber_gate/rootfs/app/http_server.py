# http_server.py
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
import re
import logging
from typing import Dict, Any

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
    def __init__(self, *args, devices_db, mqttc, sber_root_topic, ha_dev, **kwargs):
        # Сохраняем зависимости как атрибуты
        self.devices_db = devices_db
        self.mqttc = mqttc
        self.sber_root_topic = sber_root_topic
        self.ha_dev = ha_dev
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
        sf = static_request.get(self.path, None)
        if sf:
            self.send_file(sf)
        else:
            handler = getattr(self, f"handle_{self.path}", self.default_handler)
            handler()

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
            response += f"<p>{k}: {self.devices_db.DB[k]['name']}</p>"
        response += "</body></html>"
        self.wfile.write(response.encode("utf-8"))

    def handle_api_devices(self):
        data = self.devices_db.do_http_json_devices_list()
        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.end_headers()
        self.wfile.write(data.encode("utf-8"))
