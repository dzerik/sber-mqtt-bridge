"""Constants for the Sber Smart Home MQTT Bridge integration."""

from __future__ import annotations

DOMAIN = "sber_mqtt_bridge"
"""Home Assistant integration domain identifier."""

# Config entry data keys

CONF_SBER_LOGIN = "sber_login"
"""Config key for the Sber MQTT broker login/username."""

CONF_SBER_PASSWORD = "sber_password"  # noqa: S105
"""Config key for the Sber MQTT broker password."""

CONF_SBER_BROKER = "sber_broker"
"""Config key for the Sber MQTT broker hostname."""

CONF_SBER_PORT = "sber_port"
"""Config key for the Sber MQTT broker port number."""

CONF_SBER_VERIFY_SSL = "sber_verify_ssl"
"""Config key for enabling/disabling SSL certificate verification."""

# Options keys

CONF_EXPOSED_ENTITIES = "exposed_entities"
"""Options key for the list of HA entity IDs exposed to Sber."""

CONF_ENTITY_TYPE_OVERRIDES = "entity_type_overrides"
"""Options key for entity type overrides dict (entity_id → sber_category)."""

# Defaults

SBER_BROKER_DEFAULT = "mqtt-partners.iot.sberdevices.ru"
"""Default Sber MQTT broker hostname."""

SBER_PORT_DEFAULT = 8883
"""Default Sber MQTT broker port (TLS)."""

# MQTT topics

SBER_TOPIC_PREFIX = "sberdevices/v1"
"""Root MQTT topic prefix for Sber Smart Home protocol."""

SBER_GLOBAL_CONFIG_TOPIC = "sberdevices/v1/__config"
"""MQTT topic for receiving global Sber configuration (e.g. HTTP API endpoint)."""

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
    "fan",
    "water_heater",
]
"""List of HA entity domains that can be exported to Sber Smart Home."""
