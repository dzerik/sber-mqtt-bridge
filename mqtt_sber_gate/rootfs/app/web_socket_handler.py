"""
WebSocket handler module for SberGate integration
"""

import websocket
import json
import logging
import time
from threading import Thread

logger = logging.getLogger(__name__)

class WebSocketHandler:
    """Class for handling WebSocket communication with Home Assistant"""
    
    def __init__(self, ha_api_url, ha_api_token, devices_db, options):
        """
        Initialize WebSocket handler
        
        Args:
            ha_api_url (str): Home Assistant API URL
            ha_api_token (str): Authentication token
            devices_db (CDevicesDB): Devices database instance
            options (dict): Configuration options
        """
        self.ws_url = ha_api_url.replace('http', 'ws', 1) + '/api/websocket'
        self.ha_api_token = ha_api_token
        self.devices_db = devices_db
        self.options = options
        self.HA_AREA = {}
        self.running = True
        self.ws = None

    def on_open(self, ws):
        """Handle WebSocket open event"""
        logger.info("WebSocket: opened")
        self.ws = ws

    def on_close(self, ws, close_status_code, close_msg):
        """Handle WebSocket close event"""
        logger.info(f"WebSocket: Connection closed ({close_status_code}: {close_msg})")

    def on_message(self, ws, message):
        """Handle incoming WebSocket messages"""
        logger.debug(f"WebSocket: Received message: {message}")
        try:
            mdata = json.loads(message)
            handler_map = {
                'auth_required': self.handle_auth_required,
                'auth_ok': self.handle_auth_ok,
                'auth_invalid': self.handle_auth_invalid,
                'result': self.handle_result,
                'event': self.handle_event,
                'None': self.handle_default
            }
            handler = handler_map.get(mdata.get('type', 'None'), self.handle_default)
            handler(mdata)
        except Exception as e:
            logger.error(f"Error processing WebSocket message: {e}")

    def handle_auth_required(self, data):
        """Handle authentication required message"""
        logger.info("WebSocket: auth_required")
        self.ws.send(json.dumps({"type": "auth", "access_token": self.ha_api_token}))

    def handle_auth_ok(self, data):
        """Handle authentication success"""
        logger.info("WebSocket: auth_ok")
        self.ws.send(json.dumps({'id': 1, 'type': 'subscribe_events', 'event_type': 'state_changed'}))
        self.ws.send(json.dumps({'id': 2, 'type': 'config/area_registry/list'}))
        self.ws.send(json.dumps({'id': 4, 'type': 'config/entity_registry/list'}))

    def handle_auth_invalid(self, data):
        """Handle authentication failure"""
        logger.critical("WebSocket: auth_invalid")
        self.running = False

    def handle_result(self, data):
        """Handle result messages"""
        if data.get('id') == 2:
            logger.info(f"WebSocket: Получен список зон: {data}")
            self.HA_AREA = {a['area_id']: a['name'] for a in data.get('result', [])}
            logger.info(f"HA_AREA: {self.HA_AREA}")
            
        elif data.get('id') == 4:
            logger.info(f"WebSocket: Получен список сущностей.")
            logger.debug(f"Данные: {data}")
            entities = data.get('result', [])
            for entity in entities:
                entity_id = entity['entity_id']
                dev = self.devices_db.DB.get(entity_id)
                if dev and dev.get('enabled'):
                    room = self.HA_AREA.get(entity.get('area_id'), '')
                    db_room = dev.get('room', '')
                    if room != db_room:
                        logger.info(f"Изменилось расположение сущности {entity_id} с {db_room} на {room}")
                        self.devices_db.update_only(entity_id, {'entity_ha': True, 'room': room})

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
        from sber_gate import mqttc  # Assuming this is the main MQTT client
        mqttc.publish(sber_root_topic+'/up/status', 
                     DevicesDB.do_mqtt_json_states_list([entity_id]), 
                     qos=0)

    def handle_default(self, data):
        """Default message handler"""
        logger.info(f"WebSocket: default message: {data}")

    def start(self):
        """Start WebSocket connection in background thread"""
        def run():
            while self.running:
                try:
                    logger.info(f"Connecting to WebSocket URL: {self.ws_url}")
                    self.ws = websocket.WebSocketApp(
                        self.ws_url,
                        on_open=self.on_open,
                        on_message=self.on_message,
                        on_close=self.on_close
                    )
                    self.ws.run_forever()
                    logger.info("WebSocket disconnected. Reconnecting in 5 seconds...")
                    time.sleep(5)
                except Exception as e:
                    logger.error(f"WebSocket error: {e}. Reconnecting in 5 seconds...")
                    time.sleep(5)

        thread = Thread(target=run)
        thread.daemon = True
        thread.start()
