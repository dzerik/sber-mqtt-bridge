"""Constants for the Sber Smart Home MQTT Bridge integration."""

DOMAIN = "sber_mqtt_bridge"

# Config entry data keys
CONF_SBER_LOGIN = "sber_login"
CONF_SBER_PASSWORD = "sber_password"
CONF_SBER_BROKER = "sber_broker"
CONF_SBER_PORT = "sber_port"
CONF_SBER_HTTP_ENDPOINT = "sber_http_endpoint"

# Options keys
CONF_EXPOSED_ENTITIES = "exposed_entities"

# Defaults
SBER_BROKER_DEFAULT = "mqtt-partners.iot.sberdevices.ru"
SBER_PORT_DEFAULT = 8883
SBER_HTTP_ENDPOINT_DEFAULT = "https://mqtt-partners.iot.sberdevices.ru"

# MQTT topics
SBER_TOPIC_PREFIX = "sberdevices/v1"
SBER_GLOBAL_CONFIG_TOPIC = "sberdevices/v1/__config"

# Supported HA domains for export to Sber
SUPPORTED_DOMAINS = [
    "light",
    "switch",
    "cover",
    "climate",
    "sensor",
    "binary_sensor",
    "humidifier",
    "valve",
    "input_boolean",
    "script",
    "button",
]
