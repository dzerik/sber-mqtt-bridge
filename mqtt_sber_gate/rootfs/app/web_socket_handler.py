"""
WebSocket handler module for SberGate integration
"""

import asyncio
import threading
# from devices.light import LightEntity
from devices_db import json_write
import websocket
import json
import logging
import time
from threading import Thread

logger = logging.getLogger(__name__)

async def async_publish(mqttc, topic, payload, qos=0):
   """Асинхронная обертка для mqttc.publish"""
   if (mqttc.is_connected()):
    await asyncio.to_thread(mqttc.publish, topic, payload, qos)


class WebSocketHandler:
    """Class for handling WebSocket communication with Home Assistant"""
    
    def __init__(self, devices_db, devices_converter, mqttc, options):
        """
        Initialize WebSocket handler
        
        Args:
            ha_api_url (str): Home Assistant API URL
            ha_api_token (str): Authentication token
            devices_db (CDevicesDB): Devices database instance
            options (dict): Configuration options
        """
        ha_api_url = options['ha-api_url']
        self.ws_url = ha_api_url.replace('http', 'ws', 1) + '/api/websocket'
        self.devices_db = devices_db
        self.devices_converter = devices_converter

        self.sber_api_endpoint = options['sber-http_api_endpoint']
        self.ha_api_token = options['ha-api_token']
        self.sber_user = options["sber-mqtt_login"]
        self.sber_pass = options["sber-mqtt_password"]
        self.sber_broker = options["sber-mqtt_broker"]
        self.sber_root_topic='sberdevices/v1/'+options['sber-mqtt_login']

        self.mqttc = mqttc
        self.HA_AREA = {}
        self.running = True
        self.ws = None
        self.thread = None

        self.command_lock = threading.Lock()

        self.command_counter = 0

        self.handler_map = {
            'auth_required': self.handle_auth_required,
            'auth_ok': self.handle_auth_ok,
            'auth_invalid': self.handle_auth_invalid,
            'result': self.handle_result,
            'event': self.handle_event,
            'pong' : self.handle_pong,
            'None': self.handle_default
        }

        self.dont_log_messages_for = ["sensor.archer_ax58", "sensor.datchik_kachestva_vozdukha", "sensor.yandex_pogoda", "sensor.datchik_osveshchennosti_i_prisutstviia_osveshchennost", "sun.sun", "device_tracker", "person"]
#        self.dont_log_messages_for = []


    def on_open(self, ws):
        """Handle WebSocket open event"""
        logger.info("WebSocket: opened")
        self.ws = ws

    def on_close(self, ws, close_status_code, close_msg):
        """Handle WebSocket close event"""
        logger.info(f"WebSocket: Connection closed ({close_status_code}: {close_msg})")

    # async def _process_event(self, entity_id, old_state, new_state):
    def on_message(self, ws, message):
    # async def on_message_async(self, ws, message):
        """Handle incoming WebSocket messages"""
        try:
            message_data = json.loads(message)
            if "event" in message_data:
                for dont_log in self.dont_log_messages_for:
                    if message_data['event']['data']['entity_id'].startswith(dont_log):
                        return
                
                event_data = message_data["event"]
                event_type = event_data["event_type"]
                if event_type == "state_changed":
                    data = event_data["data"]
                    entity_id = data["entity_id"]
                    old_state = data["old_state"]
                    new_state = data["new_state"]
                    logger.debug(f"WebSocket: Received message {event_type} for {entity_id}: {new_state}")
                    self._process_event(entity_id, old_state, new_state)
                    # await self._process_event(entity_id, old_state, new_state)
                else:
                    logger.debug(f"Unknown event type is got: {event_type}")
            else:
                logger.debug(f"WebSocket: Received message type: {message_data['type']}")
                json_write("ws_received_message.json", message)

                msg_type = message_data.get('type')
                if msg_type is None:
                    logger.warning("Received message with unknown type or missing 'type' field.")
                    return
                handler = self.handler_map.get(msg_type, self.handle_default)
                handler(message_data)
        except Exception as e:
            logger.error(f"Error processing WebSocket message: {e}")

    def handle_auth_required(self, data):
        """Handle authentication required message"""
        logger.info("WebSocket: auth_required")
        with self.command_lock:
            self.ws.send(json.dumps({"type": "auth", "access_token": self.ha_api_token}))

    def handle_auth_ok(self, data):
        """Handle authentication success"""
        logger.info("WebSocket: auth_ok")
        with self.command_lock:
            self.ws.send(json.dumps({'id': 1, 'type': 'subscribe_events', 'event_type': 'state_changed'}))
            self.ws.send(json.dumps({'id': 2, 'type': 'config/area_registry/list'}))
            self.ws.send(json.dumps({'id': 3, 'type': 'config/device_registry/list'}))
            self.ws.send(json.dumps({'id': 4, 'type': 'config/entity_registry/list'}))
            self.ws.send(json.dumps({'id': 5, 'type': 'get_states'}))
            self.command_counter = 6

    def send_command(self, command):
        logger.debug(f"(WebSocketHandler.send_command) WebSocket: sending command [{self.command_counter}]: {command}")
        with self.command_lock:
            command["id"] = self.command_counter
            self.command_counter += 1
            self.ws.send(json.dumps(command))

    def handle_auth_invalid(self, data):
        """Handle authentication failure"""
        logger.critical("WebSocket: auth_invalid")
        self.running = False

    def handle_result(self, data):
        """Handle result messages"""
        if data.get('id') == 2:
            logger.info(f"WebSocket: Получен список зон: {data}")
            json_write("ha_area.json", data)
            self.HA_AREA = {a['area_id']: a['name'] for a in data.get('result', [])}
            logger.info(f"HA_AREA: {self.HA_AREA}")
            
        elif data.get('id') == 3:
            json_write("device_registry.json", data)
            device_data = data.get('result', [])
            for device_data_item in device_data:
                self.devices_db.upsert_device_data(device_data_item)

        elif data.get('id') == 4:
            logger.info(f"WebSocket: Получен список сущностей.")
            json_write("entity_registry.json", data)
            entities = data.get('result', [])
            for ha_entity in entities:
                entity_id = ha_entity['entity_id']
                entity = self.devices_db.entities_store.create(entity_id, ha_entity)
                if entity:
                    self.devices_db.entities_store.upsert(entity)
                                   
        elif data.get('id') == 5:
            logger.info(f"WebSocket: Получены состояния сущностей.")
            states = data.get("result", [])
            json_write("states_registry.json", states)
            self.devices_converter.update_entities(states)
            for state in states:
                entity_id = state.get('entity_id')
                if entity_id:
                    entity = self.devices_db.entities_store.get(entity_id)
                    if entity:
                        entity.fill_by_ha_state(state)
            self.devices_db.setReady()

        else: 
            logger.info(f"WebSocket: result: {data}")

    def _process_event(self, entity_id, old_state, new_state):
        if entity_id is None or new_state is None:
            logger.info(f"Either entity_id or new_state is None. entity_id: {entity_id}, new_state: {new_state}. Skipping.")
            return
        
        entity = self.devices_db.entities_store.get(entity_id)
        if entity:
            entity.process_state_change(old_state, new_state)
            logger.info(f"(_process_event) Publishing device {entity_id}")
            sber_root_topic = self.sber_root_topic 
            assert self.mqttc is not None, "MQTT client is not initialized"
            self.mqttc.publish(sber_root_topic+'/up/status', self.devices_db.do_mqtt_json_states_list([entity_id]), qos=0)
        else:
            self.handle_event_new(entity_id, old_state, new_state)
            # logger.debug(f"Process event: entity {entity_id} not found")

#    async def handle_event(self, data):
    def handle_event(self, data):
        """Handle state change events"""
        event_data = data['event']['data']
        new_state = event_data['new_state']
        old_state = event_data['old_state']
        
        if not new_state or not old_state:
            return
            
        entity_id = new_state['entity_id']
        self.handle_event_new(entity_id, old_state, new_state)

    def handle_event_new(self, entity_id, old_state, new_state):
        dev = self.devices_db.DB.get(entity_id)
        
        if not dev or not dev.get('enabled'):
            return
            
        logger.info(f'HA Event: {entity_id}: {old_state["state"]} -> {new_state["state"]}')
        
        if dev['category'] == 'sensor_temp':
            self.devices_db.change_state(entity_id, 'temperature', float(new_state['state']))
        elif new_state['state'] == 'on':
            self.devices_db.change_state(entity_id, 'on_off', True)
            if 'button_event' in dev.get('States', {}):
                self.devices_db.change_state(entity_id, 'button_event', 'click')
        else:
            if dev.get('entity_type') == 'climate':
                if new_state['state'] == 'off':
                    self.devices_db.change_state(entity_id, 'on_off', False)
                else:
                    self.devices_db.change_state(entity_id, 'on_off', True)
            else:
                self.devices_db.change_state(entity_id, 'on_off', False)
                if 'button_event' in dev.get('States', {}):
                    self.devices_db.change_state(entity_id, 'button_event', 'double_click')
                    
        # Send updated states
        sber_root_topic = self.sber_root_topic 
        # Async publishing here leads to hang all processes. So remain sync publishing here.
        self.mqttc.publish(sber_root_topic+'/up/status', 
                     self.devices_db.do_mqtt_json_states_list([entity_id]), 
                     qos=0)

    def handle_pong(self, data):
        """Handle ping message response. Just ignoring"""
        return
    
    def on_data(self, app, data, ivalue, bvalue):
        logger.debug(f"Hello, onData: {data}, {ivalue}, {bvalue}")

    def handle_default(self, data):
        """Default message handler"""
        logger.info(f"WebSocket: default message: {data}")

    def _run(self):
        while self.running:
            try:
                logger.info(f"Connecting to WebSocket URL: {self.ws_url}")
                self.ws = websocket.WebSocketApp(
                    self.ws_url,
                    on_open=self.on_open,
                    on_message=self.on_message,
                    on_close=self.on_close,
                    # on_data=self.on_data

                )
                self.ws.run_forever(ping_interval=60, ping_timeout=30)
                logger.info("WebSocket disconnected. Reconnecting in 1 second...")
                time.sleep(1)
            except Exception as e:
                logger.error(f"WebSocket error: {e}. Reconnecting in 5 seconds...")
            finally:
                time.sleep(5)

    def start(self):
        """Start WebSocket connection in background thread"""
        self.thread = Thread(target=self._run)
        self.thread.daemon = True
        self.thread.start()

    def stop(self):
        if self.thread != None and self.thread.is_alive():
            self.ws.close()
            self.thread.join()
        self.thread = None

    def join(self):
        if self.thread != None:
            self.thread.join()