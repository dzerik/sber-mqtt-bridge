# WebSocket API

HA native WebSocket команды, обеспечивающие real-time данные об
устройствах и соединении для SPA-панели `Sber Bridge`.

В v1.25.1 модуль `websocket_api.py` разбит на **пакет** с несколькими
тематическими подмодулями. В v1.26.0 добавлен `devices_grouped`
(device-centric wizard), старые `ws_add_device_wizard` /
`ws_get_available_entities` / `ws_bulk_add` удалены:

| Подмодуль | Ответственность |
|---|---|
| `_common` | Общие хелперы `get_bridge` / `get_config_entry` |
| `status` | devices listing, status, republish, device_detail, publish-one, related_sensors |
| `entities` | add / remove / clear / override |
| `links` | set_entity_links, auto_link_all |
| `devices_grouped` | **v1.26.0**: list_categories, list_devices_for_category, add_ha_device, suggest_links |
| `raw` | raw_config, raw_states, send_raw_config, send_raw_state |
| `io_export` | export, import, update_redefinitions |
| `settings` | get_settings, update_settings |
| `log` | message_log, clear_message_log, subscribe_messages |

Пакетный `__init__.py` реэкспортирует все `ws_*` команды и вызывает
`async_setup_websocket_api()` с единой регистрацией в
`async_register_command`.

## Device-centric wizard commands (v1.26.0)

Новый type-first flow для добавления устройств из UI-панели,
реализованный в `websocket_api/devices_grouped.py`:

### `sber_mqtt_bridge/list_categories`

Возвращает registry категорий Sber для Step 1 визарда — сетку
«тип устройства». Сериализует `CATEGORY_DOMAIN_MAP` +
`CATEGORY_UI_META` + `CATEGORY_GROUPS` в один payload.

Фильтрует подкатегории с `user_selectable=False` (например
`sensor_humidity` — пользователь выбирает родительский `sensor_temp`,
а subcategory подбирается автоматически при добавлении).

**Ответ:**
```json
{
  "categories": [
    {
      "id": "light",
      "group": "control",
      "icon": "💡",
      "label": "category.light",
      "domains": ["light"],
      "device_classes": null,
      "preferred_rank": 5
    }
  ],
  "groups": [
    {"id": "control", "label": "Control"},
    {"id": "sensors", "label": "Sensors"},
    {"id": "automations", "label": "Automations"}
  ]
}
```

### `sber_mqtt_bridge/list_devices_for_category`

**Параметры:** `{category: str}`

Возвращает список HA-устройств, чья primary entity промотируется в
указанную Sber-категорию. Каждое устройство представлено как
`DeviceGroup` (см. `device_grouper.py`) с полями:

- `device` — `{id, name, area}`
- `primary` — выбранная primary entity
- `primary_alternatives` — другие кандидаты в той же категории
- `linked_native` — родные датчики того же устройства, совместимые с
  ролями primary (preselected в UI)
- `linked_compatible` — cross-device совместимые датчики (opt-in,
  с указанием origin device)
- `unsupported` — prочие entity устройства (для контекста, disabled)
- `already_exposed` — экспонировано ли устройство уже

Сортировка: unexposed → exposed, затем по area и device.name.

**Ошибки:**
- `unknown_category` — категория не зарегистрирована в
  `CATEGORY_DOMAIN_MAP`.

### `sber_mqtt_bridge/add_ha_device`

**Параметры:**
- `device_id: str` — HA device registry ID
- `primary_entity_id: str` — entity, которая станет primary
- `category: str` — Sber category
- `linked_entity_ids: list[str]` (опционально) — связанные сенсоры
- `name: str` (опционально) — redefinition name
- `room: str` (опционально) — redefinition room

Атомарно патчит config entry options (`exposed_entities` +
`entity_type_overrides` + `entity_links` + `redefinitions`) и
триггерит один reload. Заменяет устаревший `ws_add_device_wizard`.

**Ошибки:**
- `entry_not_found` — config entry отсутствует
- `unknown_category` — категория не зарегистрирована
- `primary_not_found` — primary entity не в registry
- `primary_device_mismatch` — primary entity не принадлежит device_id
- `primary_category_mismatch` — primary не промотируется в category
- `linked_not_found` — linked entity не в registry
- `linked_role_not_accepted` — роль не принимается primary Sber-классом
- `role_conflict` — два linked entity претендуют на одну роль

### `sber_mqtt_bridge/suggest_links`

**Параметры:** `{entity_id: str, category?: str}`

Тонкая обёртка над `HaDeviceGrouper.preview_for_category` для
post-add edit flow (`sber-link-dialog.js`). Возвращает
`{candidates, allowed_roles, category}`, где `candidates` — список
потенциальных линков с пометкой `currently_linked` и
`suggested_role` для уже существующих связей.

::: custom_components.sber_mqtt_bridge.websocket_api
    options:
      show_root_heading: false
      members: false
