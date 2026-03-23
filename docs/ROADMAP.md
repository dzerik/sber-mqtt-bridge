# Roadmap — Sber Smart Home MQTT Bridge

Анализ на основе официальной документации Sber Smart Home (Context7, Playwright scraping).
Дата: 2026-03-23, версия: 0.7.0

---

## 1. Нереализованные категории устройств (12 из 27)

| Категория Sber | Описание | Маппинг в HA | Сложность | Приоритет |
|----------------|----------|-------------|-----------|-----------|
| `led_strip` | LED лента | `light` (rgbw/rgb) | Низкая (= light) | **P1** |
| `sensor_smoke` | Датчик дыма | `binary_sensor` (smoke) | Низкая | **P1** |
| `sensor_gas` | Датчик газа | `binary_sensor` (gas) | Низкая | **P1** |
| `hvac_fan` | Вентилятор | `fan` | Средняя | P2 |
| `hvac_heater` | Обогреватель | `climate` (heater) | Средняя | P2 |
| `hvac_boiler` | Котёл/бойлер | `climate`/`water_heater` | Средняя | P2 |
| `hvac_underfloor_heating` | Тёплый пол | `climate` | Средняя | P2 |
| `hvac_air_purifier` | Очиститель воздуха | `fan` (purifier) | Средняя | P3 |
| `kettle` | Чайник | `switch`/`water_heater` | Высокая | P3 |
| `tv` | Телевизор | `media_player` | Высокая | P3 |
| `vacuum_cleaner` | Пылесос | `vacuum` | Высокая | P3 |
| `intercom` | Домофон | Нет стандартного | Очень высокая | P4 |

---

## 2. Пропущенные features в существующих устройствах

### relay — пропущено 3

| Feature | Тип | Описание |
|---------|-----|----------|
| `current` | INTEGER | Сила тока (мА) |
| `power` | INTEGER | Потребляемая мощность (Вт) |
| `voltage` | INTEGER | Напряжение (В) |

### socket — пропущено 4

| Feature | Тип | Описание |
|---------|-----|----------|
| `child_lock` | BOOL | Блокировка от детей |
| `current` | INTEGER | Сила тока |
| `power` | INTEGER | Мощность |
| `voltage` | INTEGER | Напряжение |

### sensor_temp — пропущено 6

| Feature | Тип | Описание |
|---------|-----|----------|
| `air_pressure` | INTEGER | Атмосферное давление |
| `battery_low_power` | BOOL | Батарея разряжена |
| `battery_percentage` | INTEGER | Уровень заряда % |
| `sensor_sensitive` | ENUM (auto/high) | Чувствительность |
| `signal_strength` | INTEGER | Сила сигнала |
| `temp_unit_view` | ENUM (c/f) | Единицы измерения |

### sensor_door — пропущено 5

| Feature | Тип | Описание |
|---------|-----|----------|
| `battery_low_power` | BOOL | Батарея разряжена |
| `battery_percentage` | INTEGER | Уровень заряда |
| `sensor_sensitive` | ENUM | Чувствительность |
| `signal_strength` | INTEGER | Сила сигнала |
| `tamper_alarm` | BOOL | Вскрытие датчика |

### sensor_water_leak — пропущено 3

| Feature | Тип | Описание |
|---------|-----|----------|
| `battery_low_power` | BOOL | Батарея разряжена |
| `battery_percentage` | INTEGER | Уровень заряда |
| `signal_strength` | INTEGER | Сила сигнала |

### sensor_pir — пропущено 4 (аналогично sensor_door без tamper_alarm)

### curtain / window_blind / gate — пропущено 4+

| Feature | Тип | Описание |
|---------|-----|----------|
| `battery_low_power` | BOOL | Батарея разряжена |
| `battery_percentage` | INTEGER | Уровень заряда |
| `open_rate` | ENUM (auto/low/high) | Скорость открытия |
| `signal_strength` | INTEGER | Сила сигнала |
| `open_left/right_*` | — | Двустворчатые шторы (6 features) |

### hvac_ac — пропущено 2

| Feature | Тип | Описание |
|---------|-----|----------|
| `hvac_humidity_set` | INTEGER | Целевая влажность |
| `hvac_night_mode` | BOOL | Ночной режим |

### hvac_humidifier — пропущено 6

| Feature | Тип | Описание |
|---------|-----|----------|
| `hvac_air_flow_power` | ENUM | Скорость вентилятора |
| `hvac_humidity_set` | INTEGER | Целевая влажность |
| `hvac_ionization` | BOOL | Ионизация |
| `hvac_night_mode` | BOOL | Ночной режим |
| `hvac_water_low_level` | BOOL | Мало воды |
| `hvac_water_percentage` | INTEGER | Уровень воды % |

### valve — КРИТИЧНО: неверная реализация + пропущено 4

Спецификация: valve использует `open_set`/`open_state` (ENUM: open/close/stop), НЕ `on_off`.
Наш код: ValveEntity наследует OnOffEntity с on_off — **НЕВЕРНО**.

| Feature | Тип | Описание |
|---------|-----|----------|
| `open_set` | ENUM | Открыть/закрыть/стоп (ВМЕСТО on_off) |
| `open_state` | ENUM | Текущее состояние (open/close) |
| `battery_low_power` | BOOL | Батарея |
| `battery_percentage` | INTEGER | Заряд |
| `signal_strength` | INTEGER | Сигнал |

---

## 3. Структурные несоответствия протоколу

| Проблема | Описание | Приоритет |
|----------|----------|-----------|
| **valve = on_off** | Спецификация: open_set/open_state. Наш: on_off. Неверно! | **P1** |
| Нет `nicknames` | Sber поддерживает массив альтернативных имён | P3 |
| Нет `groups` | Sber поддерживает группы устройств | P3 |
| Нет `parent_id` | Sber поддерживает иерархию устройств (hub→device) | P3 |
| Нет `partner_meta` | Sber хранит произвольные метаданные | P4 |
| Нет `dependencies` | light_colour зависит от light_mode=colour | P2 |
| Нет `allowed_values` для большинства | Только climate/humidifier/light | P2 |
| HA `fan` не поддерживается | Нужен для hvac_fan, hvac_air_purifier | P2 |
| HA `media_player` не поддерживается | Нужен для tv | P3 |
| HA `vacuum` не поддерживается | Нужен для vacuum_cleaner | P3 |
| HA `water_heater` не поддерживается | Нужен для kettle, hvac_boiler | P3 |

---

## 4. Полная спецификация features (из документации Sber)

### Типы данных по features

| Feature | Type | Значения/Диапазон |
|---------|------|-------------------|
| `online` | BOOL | true/false |
| `on_off` | BOOL | true/false |
| `temperature` | INTEGER | -400..2000 (x10, т.е. -40.0..200.0°C) |
| `humidity` | INTEGER | 0..100 (%) |
| `hvac_temp_set` | INTEGER | 5..50 (°C, БЕЗ x10!) |
| `hvac_humidity_set` | INTEGER | 0..100 (%) |
| `light_brightness` | INTEGER | 50..1000 (промилле) |
| `light_colour_temp` | INTEGER | 0..1000 (промилле) |
| `light_colour` | COLOUR | {h:0-360, s:0-1000, v:100-1000} |
| `light_mode` | ENUM | white, colour |
| `open_percentage` | INTEGER | 0..100 (%) |
| `open_set` | ENUM | open, close, stop |
| `open_state` | ENUM | open, close |
| `pir` | ENUM | pir (event-based) |
| `doorcontact_state` | BOOL | true=open, false=closed |
| `water_leak_state` | BOOL | true=leak, false=no leak |
| `smoke_state` | BOOL | true=smoke, false=no smoke |
| `gas_leak_state` | BOOL | true=gas, false=no gas |
| `button_event` | ENUM | click, double_click, long_press |
| `battery_percentage` | INTEGER | 0..100 (%) |
| `battery_low_power` | BOOL | true/false |
| `signal_strength` | ENUM | high, medium, low |
| `tamper_alarm` | BOOL | true/false |
| `child_lock` | BOOL | true/false |
| `current` | INTEGER | мА |
| `power` | INTEGER | Вт |
| `voltage` | INTEGER | В |
| `air_pressure` | INTEGER | Па или мм рт.ст. |
| `hvac_air_flow_power` | ENUM | auto, high, low, medium, quiet, turbo |
| `hvac_air_flow_direction` | ENUM | auto, horizontal, no, rotation, swing, vertical |
| `hvac_work_mode` | ENUM | (зависит от устройства) |
| `hvac_thermostat_mode` | ENUM | cooling, drying, heating, ventilation |
| `hvac_night_mode` | BOOL | true/false |
| `hvac_ionization` | BOOL | true/false |
| `hvac_decontaminate` | BOOL | true/false |
| `hvac_aromatization` | BOOL | true/false |
| `hvac_water_low_level` | BOOL | true/false |
| `hvac_water_percentage` | INTEGER | 0..100 (%) |
| `sensor_sensitive` | ENUM | auto, high |
| `temp_unit_view` | ENUM | c, f |

### Важно: integer_value всегда string!

По спецификации C2C API `integer_value` передаётся как строка:
```json
{"type": "INTEGER", "integer_value": "220"}
```

---

## 5. Приоритеты реализации

### P1 — Быстрые фиксы (критичные, < 1 час каждый)

1. **valve fix** — переписать на open_set/open_state вместо on_off
2. **`led_strip`** — alias для light (одинаковый класс, другая category)
3. **`sensor_smoke`** — SimpleReadOnlySensor с key=`smoke_state`, BOOL
4. **`sensor_gas`** — SimpleReadOnlySensor с key=`gas_leak_state`, BOOL
5. **battery features** — добавить battery_percentage/battery_low_power во все сенсоры

### P2 — Средние (расширение, 2-4 часа каждый)

6. **hvac_fan** — новый класс + domain `fan` в SUPPORTED_DOMAINS
7. **hvac_heater/hvac_boiler/hvac_underfloor_heating** — варианты ClimateEntity
8. **power/voltage/current** — для relay и socket (из HA attributes)
9. **dependencies** — light_colour зависит от light_mode=colour
10. **allowed_values** — добавить для valve, curtain, sensor_temp

### P3 — Сложные (новые домены, день+)

11. **kettle** — domain water_heater, features kitchen_water_*
12. **tv** — domain media_player, features channel, volume, source, mute
13. **vacuum_cleaner** — domain vacuum, features program, command, status
14. **hvac_air_purifier** — domain fan, features aromatization, ionization
15. **nicknames, groups, parent_id** — расширение device descriptor

### P4 — На перспективу

16. **intercom** — нет стандартного HA domain
17. **partner_meta** — произвольные метаданные
18. **Полная pydantic сериализация** — заменить все dict на pydantic models

---

## 6. Источники документации

- [Устройства](https://developers.sber.ru/docs/ru/smarthome/c2c/devices)
- [Функции](https://developers.sber.ru/docs/ru/smarthome/c2c/functions)
- [Структуры](https://developers.sber.ru/docs/ru/smarthome/c2c/structures)
- [Value](https://developers.sber.ru/docs/ru/smarthome/c2c/value)
- [State](https://developers.sber.ru/docs/ru/smarthome/c2c/state)
- [Model](https://developers.sber.ru/docs/ru/smarthome/c2c/model)
- [Device](https://developers.sber.ru/docs/ru/smarthome/c2c/device)
- [MQTT Topics](https://developers.sber.ru/docs/ru/smarthome/reference/mqtt-topics)
- [Context7 library: /websites/developers_sber_ru_ru](https://context7.com) (10723 сниппетов)
- Сохранённый reference: `docs/sber-api-reference/`
