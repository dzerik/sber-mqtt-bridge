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

CONF_CONFIG_SETTLE_DELAY = "config_settle_delay"
"""Options key for the quiet window (seconds) before publishing ``up/config``.

Sber treats every config payload as the complete device list, so a partial
one makes it drop — and later re-create — the missing devices, losing their
room.  While entities are still loading, each new arrival re-arms this timer;
the publish happens once the stream goes quiet (issue #44)."""

CONF_CONFIG_MAX_WAIT = "config_max_wait"
"""Options key for the upper bound (seconds) on waiting for entities to load.

Guards against waiting forever when an entity never reports state (a Zigbee
stick that did not come up).  Once exceeded, the config is published without
the missing entities and a warning naming them is logged."""

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
    # 5 s comfortably spans the gaps between devices inside one Zigbee/Z-Wave
    # burst without noticeably delaying a small setup; 120 s covers a large
    # mesh coming up while still bounding a stick that never reports.
    CONF_CONFIG_SETTLE_DELAY: 5.0,
    CONF_CONFIG_MAX_WAIT: 120.0,
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

CONF_ENTITY_LINKS = "entity_links"
"""Options key for entity linking config: {primary_entity_id: {role: linked_entity_id}}."""

CONF_ENTITY_OPTIONS = "gate_options"
"""Options key for per-entity device settings.

Shape — ``entity_id → {option: value}``::

    {
        "switch.gate": {"invert_contact": False, "impulse_service": "auto",
                        "travel_time": 0, "auto_close_time": 0},
        "water_heater.kettle": {"boil_mode": "Boil", "heat_mode": "Heat"},
    }

Which keys are meaningful is decided by the device class alone (see
``BaseEntity.ENTITY_OPTION_KEYS``); everything between the config entry
and the entity — loader, bridge, WebSocket commands, export/import — is
category-agnostic.  Entries for entities whose class declares no options
are ignored.

**The literal key is ``"gate_options"`` on purpose.**  The store shipped
in v1.42 for impulse gates only (issue #53) and was generalised in
v1.47; renaming it would orphan the settings of every user who already
configured a gate, and a migration buys nothing but risk.  Read the name
as historical, not as a scope limit.
"""

CONF_GATE_OPTIONS = CONF_ENTITY_OPTIONS
"""Legacy alias of :data:`CONF_ENTITY_OPTIONS` (same key, gate-era name)."""

# NOTE: the list of HA domains exportable to Sber lives in
# ``sber_entity_map.SUPPORTED_DOMAINS`` — it is derived from
# CATEGORY_DOMAIN_MAP so it cannot drift from the category registry.
# (It used to be a hand-written copy here and lost the ``lock`` domain.)
