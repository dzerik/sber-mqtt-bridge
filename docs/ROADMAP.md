# Roadmap — Sber Smart Home MQTT Bridge

Обновлено: 2026-04-02, версия: 1.18.0

---

## Текущий статус

| Метрика | Значение |
|---------|----------|
| Версия | 1.18.0 |
| Sber категории | **28/28 (100%)** (27 устройств + hub) |
| Sber features | **~47/55 (85%)** |
| HA домены | 15 |
| Тесты | 524+ |
| Ruff errors | 0 |

### Реализованные категории (28/28)

| Категория | Версия | HA Domain |
|-----------|--------|-----------|
| light | 0.2.0 | light |
| led_strip | 0.8.0 | light |
| relay | 0.2.0 | switch, script, button |
| socket | 0.2.0 | switch (outlet) |
| curtain | 0.2.0 | cover |
| window_blind | 0.2.0 | cover (blind/shade/shutter) |
| gate | 0.5.0 | cover (gate/garage_door) |
| hvac_ac | 0.2.0 | climate |
| hvac_radiator | 0.2.0 | climate (radiator) |
| hvac_heater | 0.8.0 | climate (heater) |
| hvac_boiler | 0.8.0 | water_heater |
| hvac_underfloor_heating | 0.8.0 | climate |
| hvac_humidifier | 0.2.0 | humidifier |
| hvac_fan | 0.8.0 | fan |
| hvac_air_purifier | 0.9.0 | fan (purifier) |
| sensor_temp | 0.2.0 | sensor (temperature) |
| sensor_humidity | 0.2.0 | sensor (humidity) |
| sensor_pir | 0.2.0 | binary_sensor (motion) |
| sensor_door | 0.2.0 | binary_sensor (door/window) |
| sensor_water_leak | 0.2.0 | binary_sensor (moisture) |
| sensor_smoke | 0.8.0 | binary_sensor (smoke) |
| sensor_gas | 0.8.0 | binary_sensor (gas) |
| valve | 0.8.0 (fix) | valve |
| scenario_button | 0.2.0 | input_boolean |
| kettle | 0.9.0 | water_heater |
| tv | 0.9.0 | media_player |
| vacuum_cleaner | 0.9.0 | vacuum |
| intercom | 0.9.0 | (override only) |
| hub | 0.2.0 | (auto, root device) |
| **Итого: 28 категорий** | | |

---

## Что осталось реализовать

### Приоритет 0 — Технический долг: Feature Coverage (85% → 100%)

**Статус:** 47/55 features реализовано. 8 features отсутствуют.

#### Нереализованные features

| Feature | Категории | Описание | Сложность |
|---------|-----------|----------|-----------|
| `sensor_sensitive` | sensor_door, sensor_pir, sensor_temp | Чувствительность датчика (ENUM: auto/high/low). Требует HA service для изменения. Большинство Zigbee датчиков не поддерживают. | Средняя |
| `sleep_timer` | light, tv | Таймер отключения (INTEGER, минуты). Требует HA automation/timer helper. | Средняя |
| `open_rate` | curtain, window_blind, gate | Скорость открытия/закрытия (ENUM: auto/low/high). Из HA cover speed attribute. | Низкая |
| `open_left_percentage` | curtain, gate | Позиция левой створки двустворчатых штор/ворот (INTEGER 0-100). | Средняя |
| `open_right_percentage` | curtain, gate | Позиция правой створки (INTEGER 0-100). | Средняя |
| `light_transmission_percentage` | curtain, window_blind | Процент пропускания света (INTEGER 0-100). Не в SberFeature enum. | Низкая |
| `custom_key` | tv | Отправка произвольных кнопок пульта (ENUM). Требует IR-blaster интеграцию. | Высокая |
| `number` | tv | Набор цифр на пульте (INTEGER). Аналогично custom_key. | Средняя |
| `channel_int` | tv | Переключение канала по номеру (INTEGER). Сейчас есть только channel ENUM (+/-). | Низкая |

#### Features реализованные частично (tech debt)

| Feature | Где есть | Где НЕТ | Что нужно |
|---------|----------|---------|-----------|
| `tamper_alarm` | sensor_pir, sensor_door | water_leak, smoke, gas | Добавить чтение tamper attribute |
| `alarm_mute` | smoke, gas | water_leak | Добавить для water_leak |
| `signal_strength` | curtain, valve, sensors (linked) | relay, socket, light | Добавить linked signal для всех |
| `child_lock` | kettle, relay/socket | climate, humidifier | Добавить если HA entity поддерживает |

#### План реализации полного покрытия

**Фаза 1 — Дополнение существующих (Patch, 1-2 дня):**
1. `tamper_alarm` → water_leak, smoke, gas (читать tamper attribute)
2. `alarm_mute` → water_leak (аналогично smoke/gas)
3. `channel_int` → tv (INTEGER, прямой набор канала)
4. `open_rate` → curtain/window_blind/gate (если speed attribute доступен)

**Фаза 2 — Новые capabilities (Minor, 2-3 дня):**
5. `sensor_sensitive` → все сенсоры. Требует: определить HA service/attribute для каждого типа датчика, ENUM allowed_values, process_cmd handler
6. `sleep_timer` → light, tv. Требует: создание HA timer helper или использование `async_call_later`, INTEGER allowed_values
7. `child_lock` → расширить на climate, humidifier (из HA attributes)

**Фаза 3 — Двустворчатые устройства (Minor, 2-3 дня):**
8. `open_left_percentage` + `open_right_percentage` → curtain, gate. Требует: определить HA cover entities для левой/правой створки, маппинг position
9. `light_transmission_percentage` → curtain. Из HA tilt_position attribute

**Фаза 4 — TV расширение (Minor, 1-2 дня):**
10. `custom_key` → tv. Маппинг на HA remote.send_command
11. `number` → tv. Отправка цифр через remote.send_command

### Приоритет 1 — Структурные улучшения протокола

| # | Задача | Описание |
|---|--------|----------|
| 11 | ~~`dependencies`~~ | ~~light_colour зависит от light_mode=colour~~ — **СДЕЛАНО** |
| 12 | `allowed_values` расширение | Добавить для valve, curtain, sensor_temp и др. |
| 13 | `nicknames` | Массив альтернативных имён устройства |
| 14 | `groups` | Группы устройств (Климат, Свет и т.д.) |
| 15 | `parent_id` | Иерархия устройств (hub → device) |

### Приоритет 2 — Архитектура и качество

| # | Задача | Описание |
|---|--------|----------|
| 16 | Полная pydantic сериализация | Заменить все dict на pydantic models в device classes |
| 17 | `partner_meta` | Произвольные метаданные устройства |
| 18 | Подача в HACS Default | Попадание в каталог HACS (бОльшая видимость) |
| 19 | CI/CD GitHub Actions | hassfest, HACS validate, pytest, ruff, mypy |
| 20 | Мульти-версия HA тестирование | Тесты на 3-4 версиях HA (как у Yandex Smart Home) |

### Приоритет 3 — Расширение функционала

| # | Задача | Описание |
|---|--------|----------|
| 21 | ~~HA Repairs~~ | ~~Автоматические HA Issues~~ — **СДЕЛАНО** |
| 22 | Custom capabilities через YAML | Расширение custom_capabilities: custom modes, ranges, toggles |
| 23 | Entity customization UI | Настройка features per entity через Options Flow |
| 24 | ~~Автоматический re-publish config~~ | ~~После получения state для entity без config~~ — **СДЕЛАНО** |
| 25 | ~~Persist redefinitions~~ | ~~Сохранять rename/room из Sber app~~ — **СДЕЛАНО** |
| 26 | ~~Entity Linking~~ | ~~Auto-link all кнопка, config migration v2→v3, расширение тестов~~ — **СДЕЛАНО в v1.10** |
| 27 | ~~Edit form в detail dialog~~ | ~~Name/room/home редактирование из панели~~ — **СДЕЛАНО в v1.17** |
| 28 | ~~Default home/room~~ | ~~Fallback из HA location_name~~ — **СДЕЛАНО в v1.16-1.17** |
| 29 | ~~Area name resolution~~ | ~~area_id slug → human name через area_registry~~ — **СДЕЛАНО в v1.17** |
| 30 | ~~Category-aware model_id~~ | ~~Суффикс категории для защиты от Sber override~~ — **СДЕЛАНО в v1.18** |

---

## Выполненные задачи (для справки)

### v1.18.0 — Category-aware model_id, Smart Fan, Curtain States
- Model ID: суффикс категории предотвращает Sber override (`TS0002_limited_hvac_fan`)
- Fan: простые on/off fan без speed → только `on_off` + `online` (без ложных `hvac_air_flow_power`)
- Curtain: передача `opening`/`closing` промежуточных состояний

### v1.17.x — Device Edit, Area Resolution, Room/Home Defaults
- Edit form в detail dialog: редактирование name/room/home с Save & Re-publish
- Area name resolution: slug → human-readable через area_registry
- Default home/room fallback из HA `location_name` (→ "Мой дом")
- Hub device: home/room/default_name по документации Sber
- Wizard: pre-fill room из HA area, сохранение name/room в redefinitions
- `effective_room` property: entity area → device area fallback
- PIR: event-based — `pir` только при движении, omit при idle
- Wizard linking: same-device siblings всегда compatible
- Sensor subclass: humidity корректно создаётся при sensor_temp override
- Naming: `friendly_name` для has_entity_name entities

### v1.16.x — Default Home, Friendly Name Fallback
- Default `home` для всех устройств из HA `location_name`
- `home` field в SberDevice Pydantic модели
- `friendly_name` fallback для устройств без custom name в registry

### v1.15.x — Responsive UI, Idle Fix, Toolbar
- Адаптивная мобильная вёрстка: карточки устройств на экранах ≤768px
- Fix: пустая панель после idle — `visibilitychange` listener, retry on WS reconnect
- Toolbar: Wizard первый, логические группы с вертикальными разделителями

### v1.10.0 — Typed Constants, Pydantic Helpers, Context & Echo Prevention
- `sber_constants.py`: SberFeature (61 ключ), SberValueType, HAState, MqttTopicSuffix — полная типизация протокола через StrEnum
- Pydantic-хелперы: `make_state()`, `make_bool_value()`, `make_integer_value()` (возвращает str), `make_enum_value()`, `make_colour_value()`
- HA Context propagation: команды от Sber выполняются с Context для корректной атрибуции в logbook
- Echo loop prevention: state changes от Sber-команд не переотправляются в Sber
- Value change diffing: `has_significant_change()` исключает лишние MQTT publish
- Online status logic: event-based binary_sensors unknown=online, value-based unknown=offline, "Loading..." badge

### v1.10.x — Entity Linking, Sidebar Panel, Entity Preview
- Entity Linking Phase 4 завершён: battery_low role, расширение тестов, UI polish
- Sidebar Panel: полный рефакторинг SPA, DevTools tab (сворачиваемые payloads, clipboard)
- Entity Preview Wizard: предварительный просмотр Sber features при добавлении/изменении типа устройства

### v1.6.0 — Entity Linking (первая реализация)
- Entity Linking: привязка battery, signal_strength, humidity, temperature сенсоров к основному устройству
- Wizard Step 2: автоопределение связанных entity по device_id, предвыбор совместимых
- WebSocket API: `set_entity_links`, `suggest_links`, `auto_link_all`
- Frontend: `sber-link-dialog.js`, фильтрация linked entities в Add dialog
- Cache-busting для панельных JS-файлов

### v1.5.3 — HA 2026.3 Compatibility
- Устранение deprecated API (HA 2026.3)
- Занято: binary_sensor occupancy/presence → sensor_pir
- DevTools: сворачиваемые payloads, исправление clipboard

### v1.5.2 — Climate & Humidifier Improvements
- Climate hvac_work_mode маппинг: cooling, heating, ventilation, dehumidification, auto
- Climate swing_mode маппинг
- Humidifier использует hvac_air_flow_power (вместо hvac_work_mode)
- Отображение версии в заголовке панели

### v1.5.0 — DevTools Tab
- Вкладка DevTools: raw config/states, MQTT message log

### v1.4.0 — Wizard & Device Management
- Мастер добавления устройств
- Автоопределение сенсоров
- Экспорт/импорт конфигурации
- Toast-уведомления

### v0.3.0 — Deep Audit
- 10 critical bugs fixed, deduplication, new base classes (OnOffEntity, SimpleReadOnlySensor)
- MQTT lifecycle fixes, init chain, logger convention
- Migration to GitHub, README, CHANGELOG

### v0.4.0 — Bulk Selection
- Bulk entity selection (all/by domain/by label/clear all)
- Device deduplication by device_id
- Infinite loop fix (change_group re-publish)

### v0.5.0 — Type Overrides & Docs
- Entity type overrides UI + YAML
- Options Flow menu
- Gate category, label filtering
- mkdocs GitHub Pages site
- Extended diagnostics per entity

### v0.5.1 — Migration & Testing
- Config Entry migration v1→v2
- Snapshot testing (syrupy)
- Strict mypy config

### v0.6.0 — Pydantic & YAML
- Pydantic protocol schemas
- Custom YAML capabilities (sber_type, sber_name, sber_room)

### v0.7.0 — Protocol Compliance
- pir: BOOL→ENUM, doorcontact_state: ENUM→BOOL
- water_leak→water_leak_state, hvac_temp_set without /10
- integer_value as string per spec

### v0.8.0 — 7 New Devices
- led_strip, sensor_smoke, sensor_gas, hvac_fan
- hvac_heater, hvac_boiler, hvac_underfloor_heating
- Valve fix (open_set/open_state)
- Battery + power monitoring

### v0.9.0 — All 27 Categories
- hvac_air_purifier, kettle, tv, vacuum_cleaner, intercom
- 27/27 Sber categories complete
- 396 tests

---

## Источники документации

- [Sber Smart Home Devices](https://developers.sber.ru/docs/ru/smarthome/c2c/devices)
- [Sber Smart Home Functions](https://developers.sber.ru/docs/ru/smarthome/c2c/functions)
- [Sber Smart Home Structures](https://developers.sber.ru/docs/ru/smarthome/c2c/structures)
- [MQTT Topics Reference](https://developers.sber.ru/docs/ru/smarthome/reference/mqtt-topics)
- [Context7: /websites/developers_sber_ru_ru](https://context7.com) (10723 сниппетов)
- Сохранённый reference: `docs/sber-api-reference/`
- [Yandex Smart Home (для сравнения)](https://github.com/dext0r/yandex_smart_home)
