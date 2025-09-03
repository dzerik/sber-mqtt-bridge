"""
WebSocket handler module for SberGate integration
"""

import threading
from devices.light import LightEntity
from devices_db import json_write
import websocket
import json
import logging
import time
from threading import Thread

logger = logging.getLogger(__name__)

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
        # self.options = options

        self.sber_api_endpoint = options['sber-http_api_endpoint']
        self.ha_api_token = options['ha-api_token']
        self.sber_user = options["sber-mqtt_login"],
        self.sber_pass = options["sber-mqtt_password"],
        self.sber_broker = options["sber-mqtt_broker"],
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
            'None': self.handle_default
        }


    def on_open(self, ws):
        """Handle WebSocket open event"""
        logger.info("WebSocket: opened")
        self.ws = ws

    def on_close(self, ws, close_status_code, close_msg):
        """Handle WebSocket close event"""
        logger.info(f"WebSocket: Connection closed ({close_status_code}: {close_msg})")

    def __process_event(self, entity_id, old_state, new_state):
        entity = self.devices_db.entitiesStore.get(entity_id)
        if entity:
            entity.process_state_change(old_state, new_state)
            logger.info(f"Device database is ready. Publishing device {entity_id}")
            sber_root_topic = self.sber_root_topic 
            self.mqttc.publish(sber_root_topic+'/up/status', self.devices_db.do_mqtt_json_states_list([entity_id]), qos=0)
        else:
            logger.debug(f"Process event: entity {entity_id} not found")

    def on_message(self, ws, message):
        """Handle incoming WebSocket messages"""
        try:
            mdata = json.loads(message)
            if "event" in mdata.keys():
                logger.debug(f"WebSocket: Received message {mdata['event']['event_type']} for {mdata['event']['data']['entity_id']}")
                event_data = mdata["event"]
                event_type = event_data["event_type"]
                if event_type == "state_changed":
                    data = event_data["data"]
                    entity_id = data["entity_id"]
                    old_state = data["old_state"]
                    new_state = data["new_state"]
                    self.__process_event(entity_id, old_state, new_state)

            else:
                logger.debug(f"WebSocket: Received message type: {mdata['type']}")
                json_write("ws_received_message.json", message)

            handler = self.handler_map.get(mdata.get('type', 'None'), self.handle_default)
            handler(mdata)
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
            # По идее, тут надо заполнять deviceStore, но мы умеем заполнять только lights пока.
            json_write("entity_registry.json", data)
            entities = data.get('result', [])
            for entity in entities:
                if not entity.get('entity_id', "").startswith('light'):
#                    logger.info(f"WebSocket: Пропускаю сущность {entity['entity_id']}")
                    continue

                entity_id = entity['entity_id']
                light_entity = LightEntity(entity)
                self.devices_db.entitiesStore.upsert(light_entity)
            
                # dev = self.devices_db.DB.get(entity_id)
                # if dev and dev.get('enabled'):
                #     room = self.HA_AREA.get(entity.get('area_id'), '')
                #     db_room = dev.get('room', '')
                #     if room != db_room:
                #         logger.info(f"Изменилось расположение сущности {entity_id} с {db_room} на {room}")
                #         self.devices_db.update_only(entity_id, {'entity_ha': True, 'room': room})
                        
        elif data.get('id') == 5:
            logger.info(f"WebSocket: Получены состояния сущностей.")
            states = data.get("result", [])
            self.devices_converter.update_entities(states)
            for state in states:
                entity_id = state.get('entity_id')
                if entity_id:
                    entity = self.devices_db.entitiesStore.get(entity_id)
                    if entity:
                        entity.fill_by_ha_state(state)
            self.devices_db.setReady()
            # logger.info("Device database is ready. Publishing devices...")
            # json_devices_list = self.devices_db.do_mqtt_json_devices_list()
            # sber_root_topic = self.sber_root_topic # self.options.get('sber_root_topic', 'home')
            # self.mqttc.publish(sber_root_topic+'/up/config', json_devices_list, qos=0)
        else: 
            logger.info(f"WebSocket: result: {data}")


    def handle_event(self, data):
        """Handle state change events"""
        event_data = data['event']['data']
        new_state = event_data['new_state']
        old_state = event_data['old_state']
        
        if not new_state or not old_state:
            return
            
        entity_id = new_state['entity_id']
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
        # from sber_gate import mqttc  # Assuming this is the main MQTT client
        sber_root_topic = self.sber_root_topic # self.options.get('sber_root_topic', 'home')
        self.mqttc.publish(sber_root_topic+'/up/status', 
                     self.devices_db.do_mqtt_json_states_list([entity_id]), 
                     qos=0)

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
                    on_close=self.on_close
                )
                self.ws.run_forever(ping_interval=30)
                logger.info("WebSocket disconnected. Reconnecting in 5 seconds...")
                time.sleep(1)
            except Exception as e:
                logger.error(f"WebSocket error: {e}. Reconnecting in 5 seconds...")
                time.sleep(5)

    def _send_ping(self):
        import time
        while self.running:
            if self.ws:
                try:
                    self.send_command({"type": "ping"})
                    # self.ws.send(json.dumps({"type": "ping"}))
                except Exception as e:
                    logger.warning(f"Failed to send ping: {e}")
            time.sleep(30)  # Отправлять пинг каждые 30 секунд

    def start(self):
        """Start WebSocket connection in background thread"""
        self.thread = Thread(target=self._run)
        self.ping_thread = Thread(target=self._send_ping)
        self.thread.daemon = True
        self.ping_thread.daemon = True
        self.thread.start()
        self.ping_thread.start()

    def stop(self):
        if self.thread != None and self.thread.is_alive():
            self.ws.close()
            self.thread.join()
        self.thread = None

    def join(self):
        if self.thread != None:
            self.thread.join()