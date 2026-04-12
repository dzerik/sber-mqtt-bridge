# WebSocket API

HA native WebSocket команды, обеспечивающие real-time данные об
устройствах и соединении для SPA-панели `Sber Bridge`.

В v1.25.1 модуль `websocket_api.py` (1567 LOC) разбит на **пакет** с 8
подмодулями:

| Подмодуль | Ответственность |
|---|---|
| `_common` | Общие хелперы `get_bridge` / `get_config_entry` |
| `status` | devices listing, status, republish, device_detail, publish-one, related_sensors |
| `entities` | add / remove / clear / override / bulk_add / available_entities |
| `links` | set_entity_links, suggest_links, auto_link_all, add_device_wizard |
| `raw` | raw_config, raw_states, send_raw_config, send_raw_state |
| `io_export` | export, import, update_redefinitions |
| `settings` | get_settings, update_settings |
| `log` | message_log, clear_message_log, subscribe_messages |

Пакетный `__init__.py` реэкспортирует все `ws_*` команды для обратной
совместимости и вызывает `async_setup_websocket_api()` с единой
регистрацией в `async_register_command`.

::: custom_components.sber_mqtt_bridge.websocket_api
    options:
      show_root_heading: false
      members: false
