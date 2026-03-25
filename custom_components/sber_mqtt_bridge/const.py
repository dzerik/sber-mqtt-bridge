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

CONF_ENTITY_LINKS = "entity_links"
"""Options key for entity linking config: {primary_entity_id: {role: linked_entity_id}}."""

# Allowed link roles per Sber category (based on Sber docs: developers.sber.ru/docs/ru/smarthome/c2c/)
ALLOWED_LINK_ROLES: dict[str, list[str]] = {
    "sensor_water_leak": ["battery", "battery_low", "signal_strength"],
    "sensor_pir": ["battery", "battery_low", "signal_strength"],
    "sensor_door": ["battery", "battery_low", "signal_strength"],
    "sensor_smoke": ["battery", "battery_low", "signal_strength"],
    "sensor_gas": ["battery", "battery_low", "signal_strength"],
    "sensor_temp": ["battery", "battery_low", "signal_strength", "humidity"],
    "sensor_humidity": ["battery", "battery_low", "signal_strength", "temperature"],
    "curtain": ["battery", "battery_low", "signal_strength"],
    "window_blind": ["battery", "battery_low", "signal_strength"],
    "gate": ["battery", "battery_low", "signal_strength"],
    "valve": ["battery", "battery_low", "signal_strength"],
    "hvac_ac": ["temperature"],
    "hvac_humidifier": ["humidity"],
}
"""Map Sber category to list of linkable roles."""

# HA device_class → link role (domain-aware overrides in ws_suggest_links)
HA_DEVICE_CLASS_TO_LINK_ROLE: dict[str, str] = {
    "battery": "battery",
    "temperature": "temperature",
    "humidity": "humidity",
    "signal_strength": "signal_strength",
}
"""Map HA sensor device_class to entity link role name.

Note: binary_sensor domain overrides are applied in ws_suggest_links:
- battery → battery_low (binary_sensor is bool, not percentage)
- moisture is excluded (it's a leak sensor, not humidity)
"""

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
    "media_player",
    "vacuum",
]
"""List of HA entity domains that can be exported to Sber Smart Home."""
