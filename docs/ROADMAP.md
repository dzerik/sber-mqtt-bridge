# Roadmap — Sber Smart Home MQTT Bridge

Обновлено: 2026-03-24, версия: 1.6.0

---

## Текущий статус

| Метрика | Значение |
|---------|----------|
| Версия | 1.6.0 |
| Sber категории | **27/27 (100%)** |
| HA домены | 15 |
| Тесты | 498+ |
| Ruff errors | 0 |

### Реализованные категории (27/27)

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

---

## Что осталось реализовать

### Приоритет 1 — Расширение features существующих устройств

| # | Задача | Категории | Описание |
|---|--------|-----------|----------|
| 1 | `air_pressure` feature | sensor_temp | Атмосферное давление из HA sensor (device_class=pressure) |
| 2 | `signal_strength` feature | все сенсоры, covers | RSSI/signal_strength из HA attributes |
| 3 | `tamper_alarm` feature | sensor_door, sensor_pir | Вскрытие датчика (binary_sensor tamper attribute) |
| 4 | `battery_low_power` feature | все сенсоры, covers | Разряжена ли батарея (bool, из battery_level < 20%) |
| 5 | `child_lock` feature | socket, kettle | Блокировка от детей из HA attributes |
| 6 | `sensor_sensitive` feature | sensor_temp, sensor_door, sensor_pir | Чувствительность датчика |
| 7 | `hvac_humidity_set` feature | hvac_ac | Целевая влажность кондиционера |
| 8 | `hvac_night_mode` feature | hvac_ac, hvac_humidifier | Ночной режим |
| 9 | `open_rate` feature | curtain, window_blind, gate | Скорость открытия (auto/low/high) |
| 10 | `open_left/right_*` features | curtain, gate | Двустворчатые шторы/ворота (6 features) |

### Приоритет 2 — Структурные улучшения протокола

| # | Задача | Описание |
|---|--------|----------|
| 11 | `dependencies` | light_colour зависит от light_mode=colour (JSON dependencies) |
| 12 | `allowed_values` расширение | Добавить для valve, curtain, sensor_temp и др. |
| 13 | `nicknames` | Массив альтернативных имён устройства |
| 14 | `groups` | Группы устройств (Климат, Свет и т.д.) |
| 15 | `parent_id` | Иерархия устройств (hub → device) |

### Приоритет 3 — Архитектура и качество

| # | Задача | Описание |
|---|--------|----------|
| 16 | Полная pydantic сериализация | Заменить все dict на pydantic models в device classes |
| 17 | `partner_meta` | Произвольные метаданные устройства |
| 18 | Подача в HACS Default | Попадание в каталог HACS (бОльшая видимость) |
| 19 | CI/CD GitHub Actions | hassfest, HACS validate, pytest, ruff, mypy |
| 20 | Мульти-версия HA тестирование | Тесты на 3-4 версиях HA (как у Yandex Smart Home) |

### Приоритет 4 — Расширение функционала

| # | Задача | Описание |
|---|--------|----------|
| 21 | ~~HA Repairs~~ | ~~Автоматические HA Issues~~ — **СДЕЛАНО** |
| 22 | Custom capabilities через YAML | Расширение custom_capabilities: custom modes, ranges, toggles |
| 23 | Entity customization UI | Настройка features per entity через Options Flow |
| 24 | ~~Автоматический re-publish config~~ | ~~После получения state для entity без config~~ — **СДЕЛАНО** |
| 25 | ~~Persist redefinitions~~ | ~~Сохранять rename/room из Sber app~~ — **СДЕЛАНО** |
| 26 | Entity Linking Phase 4 | Auto-link all кнопка, config migration v2→v3, расширение тестов |

---

## Выполненные задачи (для справки)

### v1.6.0 — Entity Linking
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
