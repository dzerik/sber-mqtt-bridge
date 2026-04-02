# Features (функции устройств)

Полный справочник функций Sber Smart Home C2C протокола.

## Алфавитный указатель

| Feature | Type | R/W | Описание |
|---------|------|:---:|----------|
| `air_pressure` | INTEGER | R | Атмосферное давление (мм рт.ст.) |
| `alarm_mute` | BOOL | W | Отключение сигнала тревоги |
| `battery_low_power` | BOOL | R | Батарея разряжена |
| `battery_percentage` | INTEGER | R | Заряд батареи (0–100%) |
| `button_event` | ENUM | R | Событие нажатия кнопки |
| `button_1_event`..`button_10_event` | ENUM | R | Событие кнопки N |
| `button_left_event` | ENUM | R | Событие левой кнопки |
| `button_right_event` | ENUM | R | Событие правой кнопки |
| `button_top_left_event` | ENUM | R | Событие верхней левой кнопки |
| `button_top_right_event` | ENUM | R | Событие верхней правой кнопки |
| `button_bottom_left_event` | ENUM | R | Событие нижней левой кнопки |
| `button_bottom_right_event` | ENUM | R | Событие нижней правой кнопки |
| `channel` | ENUM | W | Переключение канала (next/prev) |
| `channel_int` | INTEGER | W | Прямой номер канала |
| `child_lock` | BOOL | RW | Блокировка от детей |
| `current` | INTEGER | R | Сила тока (мА) |
| `custom_key` | ENUM | W | Произвольная кнопка пульта |
| `direction` | ENUM | W | Направление (навигация) |
| `doorcontact_state` | BOOL | R | Состояние контакта двери/окна |
| `gas_leak_state` | BOOL | R | Утечка газа |
| `humidity` | INTEGER | R | Текущая влажность (0–100%) |
| `hvac_air_flow_direction` | ENUM | RW | Направление воздушного потока |
| `hvac_air_flow_power` | ENUM | RW | Скорость вентилятора |
| `hvac_aromatization` | BOOL | RW | Ароматизация вкл/выкл |
| `hvac_decontaminate` | BOOL | RW | Обеззараживание вкл/выкл |
| `hvac_direction_set` | ENUM | W | Установка направления потока |
| `hvac_heating_rate` | ENUM | RW | Мощность нагрева |
| `hvac_humidity_set` | INTEGER | RW | Целевая влажность (0–100%) |
| `hvac_ionization` | BOOL | RW | Ионизация вкл/выкл |
| `hvac_night_mode` | BOOL | RW | Ночной режим |
| `hvac_replace_filter` | BOOL | R | Требуется замена фильтра |
| `hvac_replace_ionizator` | BOOL | R | Требуется замена ионизатора |
| `hvac_temp_set` | INTEGER | RW | Целевая температура (°C, **без x10**) |
| `hvac_thermostat_mode` | ENUM | RW | Режим термостата |
| `hvac_water_level` | FLOAT | R | Уровень воды (литры) |
| `hvac_water_low_level` | BOOL | R | Мало воды |
| `hvac_water_percentage` | INTEGER | R | Уровень воды (0–100%) |
| `hvac_work_mode` | ENUM | RW | Режим работы HVAC |
| `incoming_call` | BOOL | R | Входящий вызов (домофон) |
| `kitchen_water_level` | BOOL | R | Наличие воды в чайнике |
| `kitchen_water_low_level` | BOOL | R | Мало воды в чайнике |
| `kitchen_water_temperature` | INTEGER | R | Текущая температура воды (°C) |
| `kitchen_water_temperature_set` | INTEGER | RW | Целевая температура воды (°C) |
| `light_brightness` | INTEGER | RW | Яркость (50–1000, промилле) |
| `light_colour` | COLOUR | RW | Цвет (HSV) |
| `light_colour_temp` | INTEGER | RW | Цветовая температура (0–1000) |
| `light_mode` | ENUM | RW | Режим освещения |
| `light_transmission_percentage` | INTEGER | R | Пропускание света (0–100%) |
| `mute` | BOOL | RW | Беззвучный режим |
| `number` | INTEGER | W | Набор цифры на пульте |
| `on_off` | BOOL | RW | Включение/выключение |
| `online` | BOOL | R | Доступность устройства |
| `open_left_percentage` | INTEGER | RW | Позиция левой створки (0–100%) |
| `open_left_set` | ENUM | W | Управление левой створкой |
| `open_left_state` | ENUM | R | Состояние левой створки |
| `open_percentage` | INTEGER | RW | Позиция открытия (0–100%) |
| `open_rate` | ENUM | RW | Скорость открытия/закрытия |
| `open_right_percentage` | INTEGER | RW | Позиция правой створки (0–100%) |
| `open_right_set` | ENUM | W | Управление правой створкой |
| `open_right_state` | ENUM | R | Состояние правой створки |
| `open_set` | ENUM | W | Управление открытием |
| `open_state` | ENUM | R | Текущее состояние |
| `pir` | ENUM | R | Обнаружение движения |
| `power` | INTEGER | R | Мощность (Вт) |
| `reject_call` | BOOL | W | Отклонение вызова (домофон) |
| `sensor_sensitive` | ENUM | RW | Чувствительность датчика |
| `signal_strength` | ENUM | R | Сила сигнала |
| `smoke_state` | BOOL | R | Обнаружение дыма |
| `source` | ENUM | RW | Источник сигнала (ТВ) |
| `tamper_alarm` | BOOL | R | Тревога вскрытия |
| `temp_unit_view` | ENUM | RW | Единица измерения температуры |
| `temperature` | INTEGER | R | Текущая температура (**x10**, 220 = 22.0°C) |
| `unlock` | BOOL | W | Открытие замка (домофон) |
| `vacuum_cleaner_cleaning_type` | ENUM | RW | Тип уборки |
| `vacuum_cleaner_command` | ENUM | W | Команда пылесосу |
| `vacuum_cleaner_program` | ENUM | RW | Программа уборки |
| `vacuum_cleaner_status` | ENUM | R | Статус пылесоса |
| `voltage` | INTEGER | R | Напряжение (В) |
| `volume` | ENUM | W | Громкость (next/prev) |
| `volume_int` | INTEGER | RW | Громкость (абсолютное значение) |
| `water_leak_state` | BOOL | R | Обнаружение протечки |

---

## Детальное описание по группам

### Common (общие)

#### online

- **Тип:** BOOL
- **R/W:** Read-only
- **Категории:** все (обязательная для всех)
- **Описание:** Доступность устройства. `true` — устройство на связи, `false` — оффлайн.

```json
{"key": "online", "value": {"type": "BOOL", "bool_value": true}}
```

#### on_off

- **Тип:** BOOL
- **R/W:** Read/Write
- **Категории:** light, led_strip, relay, socket, hvac_ac, hvac_radiator, hvac_heater, hvac_boiler, hvac_underfloor_heating, hvac_fan, hvac_air_purifier, hvac_humidifier, kettle, tv
- **Описание:** Включение/выключение устройства.

```json
{"key": "on_off", "value": {"type": "BOOL", "bool_value": false}}
```

#### battery_low_power

- **Тип:** BOOL
- **R/W:** Read-only
- **Категории:** curtain, window_blind, sensor_temp, sensor_pir, sensor_door, sensor_water_leak, sensor_smoke, sensor_gas, valve
- **Описание:** `true` — батарея разряжена.

#### battery_percentage

- **Тип:** INTEGER
- **R/W:** Read-only
- **Диапазон:** 0–100
- **Категории:** те же, что battery_low_power, + vacuum_cleaner

```json
{"key": "battery_percentage", "value": {"type": "INTEGER", "integer_value": "85"}}
```

#### signal_strength

- **Тип:** ENUM
- **R/W:** Read-only
- **Значения:** `high`, `medium`, `low`
- **Категории:** curtain, window_blind, gate, sensor_temp, sensor_pir, sensor_door, sensor_water_leak, sensor_smoke, sensor_gas, valve

```json
{"key": "signal_strength", "value": {"type": "ENUM", "enum_value": "high"}}
```

#### child_lock

- **Тип:** BOOL
- **R/W:** Read/Write
- **Категории:** socket, kettle, vacuum_cleaner
- **Описание:** Блокировка от детей.

#### sensor_sensitive

- **Тип:** ENUM
- **R/W:** Read/Write
- **Значения:** `auto`, `high`, `medium`, `low`
- **Категории:** sensor_temp, sensor_pir, sensor_door

```json
{"key": "sensor_sensitive", "value": {"type": "ENUM", "enum_value": "medium"}}
```

#### tamper_alarm

- **Тип:** BOOL
- **R/W:** Read-only
- **Категории:** sensor_pir, sensor_door
- **Описание:** Срабатывание тревоги вскрытия корпуса.

#### alarm_mute

- **Тип:** BOOL
- **R/W:** Write
- **Категории:** sensor_smoke, sensor_gas, sensor_water_leak
- **Описание:** Отключение звукового сигнала тревоги.

---

### Lighting (освещение)

#### light_brightness

- **Тип:** INTEGER
- **R/W:** Read/Write
- **Диапазон:** 50–1000 (промилле; типичный allowed_values: min=100, max=900)
- **Категории:** light, led_strip

```json
{"key": "light_brightness", "value": {"type": "INTEGER", "integer_value": "500"}}
```

#### light_colour

- **Тип:** COLOUR
- **R/W:** Read/Write
- **Диапазон:** h: 0–360, s: 0–1000, v: 100–1000
- **Категории:** light, led_strip
- **Зависимость:** доступна только при `light_mode` = `colour`

```json
{"key": "light_colour", "value": {"type": "COLOUR", "colour_value": {"h": 360, "s": 1000, "v": 1000}}}
```

#### light_colour_temp

- **Тип:** INTEGER
- **R/W:** Read/Write
- **Диапазон:** 0–1000 (0% = тёплый, 100% = холодный)
- **Категории:** light, led_strip

```json
{"key": "light_colour_temp", "value": {"type": "INTEGER", "integer_value": "350"}}
```

#### light_mode

- **Тип:** ENUM
- **R/W:** Read/Write
- **Значения:** `white`, `colour`
- **Категории:** light, led_strip

```json
{"key": "light_mode", "value": {"type": "ENUM", "enum_value": "colour"}}
```

#### light_transmission_percentage

- **Тип:** INTEGER
- **R/W:** Read-only
- **Диапазон:** 0–100
- **Категории:** window_blind
- **Описание:** Процент пропускания света.

---

### Climate / HVAC

#### temperature

- **Тип:** INTEGER
- **R/W:** Read-only
- **Диапазон:** -400..2000

!!! danger "temperature — значение x10"
    `"integer_value": "220"` = **22.0°C**

    Это **отличается** от `hvac_temp_set`, который передаётся **без x10**.

- **Категории:** hvac_ac, hvac_radiator, hvac_heater, hvac_boiler, hvac_underfloor_heating, sensor_temp

```json
{"key": "temperature", "value": {"type": "INTEGER", "integer_value": "220"}}
```

#### hvac_temp_set

- **Тип:** INTEGER
- **R/W:** Read/Write
- **Диапазон:** зависит от категории (5–50 для hvac_ac, 25–80 для hvac_boiler)

!!! danger "hvac_temp_set — НЕ x10"
    `"integer_value": "25"` = **25°C** (целые градусы)

- **Категории:** hvac_ac, hvac_radiator, hvac_heater, hvac_boiler, hvac_underfloor_heating

```json
{"key": "hvac_temp_set", "value": {"type": "INTEGER", "integer_value": "25"}}
```

#### humidity

- **Тип:** INTEGER
- **R/W:** Read-only
- **Диапазон:** 0–100 (%)
- **Категории:** sensor_temp, hvac_humidifier

```json
{"key": "humidity", "value": {"type": "INTEGER", "integer_value": "60"}}
```

#### hvac_humidity_set

- **Тип:** INTEGER
- **R/W:** Read/Write
- **Диапазон:** зависит от устройства (типичный: 35–85%, step 5)
- **Категории:** hvac_ac, hvac_humidifier

#### hvac_work_mode

- **Тип:** ENUM
- **R/W:** Read/Write
- **Значения:** зависят от категории (типичные: `cooling`, `heating`, `ventilation`, `dehumidification`, `auto`, `eco`)
- **Категории:** hvac_ac

```json
{"key": "hvac_work_mode", "value": {"type": "ENUM", "enum_value": "eco"}}
```

#### hvac_thermostat_mode

- **Тип:** ENUM
- **R/W:** Read/Write
- **Значения:** `cooling`, `drying`, `heating`, `ventilation`
- **Категории:** hvac_boiler, hvac_underfloor_heating

```json
{"key": "hvac_thermostat_mode", "value": {"type": "ENUM", "enum_value": "cooling"}}
```

#### hvac_air_flow_power

- **Тип:** ENUM
- **R/W:** Read/Write
- **Значения:** `auto`, `low`, `medium`, `high`, `turbo`, `quiet`
- **Категории:** hvac_ac, hvac_fan, hvac_air_purifier, hvac_humidifier
- **Типичный allowed_values:** `["auto", "high", "low", "medium", "turbo"]`

#### hvac_air_flow_direction

- **Тип:** ENUM
- **R/W:** Read/Write
- **Значения:** `auto`, `horizontal`, `no`, `rotation`, `swing`, `vertical`
- **Категории:** hvac_ac

#### hvac_night_mode

- **Тип:** BOOL
- **R/W:** Read/Write
- **Категории:** hvac_ac, hvac_humidifier, hvac_air_purifier

```json
{"key": "hvac_night_mode", "value": {"type": "BOOL", "bool_value": false}}
```

#### hvac_ionization

- **Тип:** BOOL
- **R/W:** Read/Write
- **Категории:** hvac_humidifier, hvac_air_purifier

#### hvac_aromatization

- **Тип:** BOOL
- **R/W:** Read/Write
- **Категории:** hvac_air_purifier

#### hvac_decontaminate

- **Тип:** BOOL
- **R/W:** Read/Write
- **Категории:** hvac_air_purifier

#### hvac_replace_filter

- **Тип:** BOOL
- **R/W:** Read-only
- **Категории:** hvac_humidifier, hvac_air_purifier

```json
{"key": "hvac_replace_filter", "value": {"type": "BOOL", "bool_value": true}}
```

#### hvac_replace_ionizator

- **Тип:** BOOL
- **R/W:** Read-only
- **Категории:** hvac_humidifier, hvac_air_purifier

#### hvac_heating_rate

- **Тип:** ENUM
- **R/W:** Read/Write
- **Значения:** `low`, `medium`, `high`
- **Категории:** hvac_heater

```json
{"key": "hvac_heating_rate", "value": {"type": "ENUM", "enum_value": "low"}}
```

#### hvac_water_level

- **Тип:** FLOAT
- **R/W:** Read-only
- **Категории:** hvac_humidifier
- **Описание:** Уровень воды в литрах.

#### hvac_water_low_level

- **Тип:** BOOL
- **R/W:** Read-only
- **Категории:** hvac_humidifier

#### hvac_water_percentage

- **Тип:** INTEGER
- **R/W:** Read-only
- **Диапазон:** 0–100
- **Категории:** hvac_humidifier

#### hvac_direction_set

- **Тип:** ENUM
- **R/W:** Write
- **Категории:** hvac_ac

#### air_pressure

- **Тип:** INTEGER
- **R/W:** Read-only
- **Категории:** sensor_temp
- **Описание:** Атмосферное давление в мм рт.ст.

```json
{"key": "air_pressure", "value": {"type": "INTEGER", "integer_value": "720"}}
```

#### temp_unit_view

- **Тип:** ENUM
- **R/W:** Read/Write
- **Значения:** `c` (Цельсий), `f` (Фаренгейт)
- **Категории:** sensor_temp

```json
{"key": "temp_unit_view", "value": {"type": "ENUM", "enum_value": "c"}}
```

---

### Covers / Openings (шторы, ворота, жалюзи)

#### open_set

- **Тип:** ENUM
- **R/W:** Write
- **Значения:** `open`, `close`, `stop`
- **Категории:** curtain, window_blind, gate, valve

```json
{"key": "open_set", "value": {"type": "ENUM", "enum_value": "open"}}
```

#### open_state

- **Тип:** ENUM
- **R/W:** Read-only
- **Значения:** `open`, `close`
- **Категории:** curtain, window_blind, gate, valve

```json
{"key": "open_state", "value": {"type": "ENUM", "enum_value": "open"}}
```

#### open_percentage

- **Тип:** INTEGER
- **R/W:** Read/Write
- **Диапазон:** 0–100
- **Категории:** curtain, window_blind

```json
{"key": "open_percentage", "value": {"type": "INTEGER", "integer_value": "30"}}
```

#### open_rate

- **Тип:** ENUM
- **R/W:** Read/Write
- **Значения:** `auto`, `low`, `high`
- **Категории:** curtain, window_blind, gate

#### open_left_percentage / open_left_set / open_left_state

- Аналогичны `open_percentage`/`open_set`/`open_state` для левой створки
- **Категории:** curtain, gate

#### open_right_percentage / open_right_set / open_right_state

- Аналогичны для правой створки
- **Категории:** curtain, gate

---

### Sensors (датчики)

#### pir

- **Тип:** ENUM
- **R/W:** Read-only
- **Значения:** `pir` (движение обнаружено)
- **Категории:** sensor_pir

!!! warning "pir — это ENUM, не BOOL"
    ```json
    {"key": "pir", "value": {"type": "ENUM", "enum_value": "pir"}}
    ```

#### doorcontact_state

- **Тип:** BOOL
- **R/W:** Read-only
- **Значения:** `true` = контакты разомкнуты (открыто), `false` = сомкнуты (закрыто)
- **Категории:** sensor_door

!!! warning "doorcontact_state — это BOOL, не ENUM"
    ```json
    {"key": "doorcontact_state", "value": {"type": "BOOL", "bool_value": false}}
    ```

#### water_leak_state

- **Тип:** BOOL
- **R/W:** Read-only
- **Категории:** sensor_water_leak

!!! note "Имя: water_leak_state, не water_leak"
    Правильное имя функции — `water_leak_state`.

```json
{"key": "water_leak_state", "value": {"type": "BOOL", "bool_value": true}}
```

#### smoke_state

- **Тип:** BOOL
- **R/W:** Read-only
- **Категории:** sensor_smoke

```json
{"key": "smoke_state", "value": {"type": "BOOL", "bool_value": false}}
```

#### gas_leak_state

- **Тип:** BOOL
- **R/W:** Read-only
- **Категории:** sensor_gas

---

### Buttons (кнопки)

#### button_event / button_N_event / button_*_event

- **Тип:** ENUM
- **R/W:** Read-only
- **Значения:** `click`, `double_click`, `long_press`
- **Категории:** scenario_button

Варианты именования:

- `button_event` — одна кнопка
- `button_1_event`..`button_10_event` — нумерованные кнопки
- `button_left_event`, `button_right_event` — боковые
- `button_top_left_event`, `button_top_right_event` — верхние
- `button_bottom_left_event`, `button_bottom_right_event` — нижние

```json
{"key": "button_1_event", "value": {"type": "ENUM", "enum_value": "click"}}
```

---

### Media / TV

#### volume

- **Тип:** ENUM
- **R/W:** Write
- **Значения:** `+` (громче), `-` (тише)
- **Категории:** tv

#### volume_int

- **Тип:** INTEGER
- **R/W:** Read/Write
- **Категории:** tv

```json
{"key": "volume_int", "value": {"type": "INTEGER", "integer_value": "30"}}
```

#### mute

- **Тип:** BOOL
- **R/W:** Read/Write
- **Категории:** tv

```json
{"key": "mute", "value": {"type": "BOOL", "bool_value": true}}
```

#### channel

- **Тип:** ENUM
- **R/W:** Write
- **Значения:** `+` (следующий), `-` (предыдущий)
- **Категории:** tv

#### channel_int

- **Тип:** INTEGER
- **R/W:** Read/Write
- **Категории:** tv

```json
{"key": "channel_int", "value": {"type": "INTEGER", "integer_value": "11"}}
```

#### source

- **Тип:** ENUM
- **R/W:** Read/Write
- **Значения:** зависят от устройства (типичные: `hdmi1`, `hdmi2`, `hdmi3`, `tv`, `av`, `content`, `+`, `-`)
- **Категории:** tv

```json
{"key": "source", "value": {"type": "ENUM", "enum_value": "HDMI1"}}
```

#### direction

- **Тип:** ENUM
- **R/W:** Write
- **Значения:** `up`, `down`, `left`, `right`, `ok`
- **Категории:** tv

```json
{"key": "direction", "value": {"type": "ENUM", "enum_value": "up"}}
```

#### number

- **Тип:** INTEGER
- **R/W:** Write
- **Значения:** 0–9 (цифра на пульте)
- **Категории:** tv

```json
{"key": "number", "value": {"type": "INTEGER", "integer_value": "1"}}
```

#### custom_key

- **Тип:** ENUM
- **R/W:** Write
- **Категории:** tv
- **Описание:** Произвольная кнопка пульта, значения зависят от устройства.

---

### Kitchen (кухня)

#### kitchen_water_temperature

- **Тип:** INTEGER
- **R/W:** Read-only
- **Описание:** Текущая температура воды (°C).
- **Категории:** kettle

```json
{"key": "kitchen_water_temperature", "value": {"type": "INTEGER", "integer_value": "60"}}
```

#### kitchen_water_temperature_set

- **Тип:** INTEGER
- **R/W:** Read/Write
- **Диапазон:** типичный 60–100, step 10
- **Категории:** kettle

#### kitchen_water_level

- **Тип:** BOOL
- **R/W:** Read-only
- **Категории:** kettle
- **Описание:** Наличие воды.

#### kitchen_water_low_level

- **Тип:** BOOL
- **R/W:** Read-only
- **Категории:** kettle
- **Описание:** `true` = воды мало/нет.

```json
{"key": "kitchen_water_low_level", "value": {"type": "BOOL", "bool_value": true}}
```

---

### Energy (энергия)

#### current

- **Тип:** INTEGER
- **R/W:** Read-only
- **Описание:** Сила тока (мА).
- **Категории:** relay, socket

```json
{"key": "current", "value": {"type": "INTEGER", "integer_value": "9000"}}
```

#### power

- **Тип:** INTEGER
- **R/W:** Read-only
- **Описание:** Мощность (Вт).
- **Категории:** relay, socket

#### voltage

- **Тип:** INTEGER
- **R/W:** Read-only
- **Описание:** Напряжение (В).
- **Категории:** relay, socket

---

### Vacuum (пылесос)

#### vacuum_cleaner_command

- **Тип:** ENUM
- **R/W:** Write
- **Значения:** `start`, `stop`, `pause`, `home`, `find`
- **Категории:** vacuum_cleaner

#### vacuum_cleaner_status

- **Тип:** ENUM
- **R/W:** Read-only
- **Значения:** `cleaning`, `charging`, `paused`, `standby`, `error`, `docked`
- **Категории:** vacuum_cleaner

#### vacuum_cleaner_program

- **Тип:** ENUM
- **R/W:** Read/Write
- **Значения:** типичные: `perimeter`, `spot`, `smart`
- **Категории:** vacuum_cleaner

#### vacuum_cleaner_cleaning_type

- **Тип:** ENUM
- **R/W:** Read/Write
- **Значения:** `dry`, `wet`, `dry_and_wet`
- **Категории:** vacuum_cleaner

```json
{"key": "vacuum_cleaner_cleaning_type", "value": {"type": "ENUM", "enum_value": "wet"}}
```

---

### Intercom (домофон)

#### incoming_call

- **Тип:** BOOL
- **R/W:** Read-only
- **Категории:** intercom
- **Описание:** `true` = входящий вызов.

#### reject_call

- **Тип:** BOOL
- **R/W:** Write
- **Категории:** intercom
- **Описание:** Отклонение вызова.

#### unlock

- **Тип:** BOOL
- **R/W:** Write
- **Категории:** intercom
- **Описание:** Открытие замка.
