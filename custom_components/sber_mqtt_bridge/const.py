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

# Bridge settings keys (stored in config_entry.options)

CONF_RECONNECT_MIN = "reconnect_interval_min"
"""Options key for minimum MQTT reconnect interval in seconds."""

CONF_RECONNECT_MAX = "reconnect_interval_max"
"""Options key for maximum MQTT reconnect interval in seconds."""

CONF_DEBOUNCE_DELAY = "debounce_delay"
"""Options key for state-change publish debounce delay in seconds."""

CONF_MESSAGE_LOG_SIZE = "message_log_size"
"""Options key for DevTools MQTT message ring buffer size."""

CONF_MAX_MQTT_PAYLOAD = "max_mqtt_payload_size"
"""Options key for maximum allowed MQTT payload size in bytes."""

CONF_HUB_AUTO_PARENT = "hub_auto_parent_id"
"""Options key for auto-assigning parent_id=root to all child devices."""

CONF_CONFIRM_DELAY = "confirm_delay"
"""Options key for delay (seconds) before confirming state back to Sber after a command."""

CONF_ACK_AUDIT_DELAY = "ack_audit_delay"
"""Options key for delay (seconds) before auditing unacknowledged entities after config publish."""

CONF_HA_SERIAL_NUMBER = "ha_serial_number_enabled"
"""Options key for emitting per-HA serial markers in ``partner_meta.ha_serial_number``.

When enabled, every device payload (including the root hub) carries a
``ha_serial_number`` entry inside ``partner_meta``.  The value is either
the real ``DeviceEntry.serial_number`` / MAC address from HA's device
registry, or a fallback derived from this Home Assistant instance UUID
(``ha-<8-char-prefix>``).  Sister projects that import these devices
back into HA can use the marker to detect import loops.
"""

CONF_SILENT_REJECTION_ALERTS = "silent_rejection_alerts"
"""Options key for surfacing silent-rejection audits as HA repair issues.

When ``False`` (default) the bridge keeps running the silent-rejection
audit and logs ``WARN`` for unacknowledged entities, but does not raise
an HA repair issue.  Empirically the 60-second post-publish window is
not always enough — Sber cloud can accept a device, dispatch commands
for it, and never send ``status_request`` until the user pulls to
refresh the Sber app.  Surfacing every such case as a repair was noisy
and false-positive-prone.

Power users can flip this to ``True`` from the panel **Settings** tab
to keep the historical loud behaviour.
"""

SETTINGS_DEFAULTS: dict[str, int | float | bool] = {
    CONF_RECONNECT_MIN: 5,
    CONF_RECONNECT_MAX: 300,
    CONF_DEBOUNCE_DELAY: 0.1,
    CONF_MESSAGE_LOG_SIZE: 50,
    CONF_MAX_MQTT_PAYLOAD: 1_000_000,
    CONF_SBER_VERIFY_SSL: True,
    CONF_HUB_AUTO_PARENT: False,
    CONF_CONFIRM_DELAY: 1.5,
    CONF_ACK_AUDIT_DELAY: 60,
    CONF_HA_SERIAL_NUMBER: False,
    CONF_SILENT_REJECTION_ALERTS: False,
}
"""Default values for bridge operational settings."""

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
