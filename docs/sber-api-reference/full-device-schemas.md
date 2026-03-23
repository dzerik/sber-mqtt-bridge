# Полные схемы всех устройств Sber Smart Home

Источник: официальная документация developers.sber.ru (Context7 + Playwright scraping)
Дата: 2026-03-23

---

## Общая структура value

```json
{
    "key": "<feature_name>",
    "value": {
        "type": "BOOL|INTEGER|FLOAT|STRING|ENUM|COLOUR",
        "<type>_value": <value>
    }
}
```

| type | Поле значения | Тип поля | Пример |
|------|--------------|----------|--------|
| BOOL | `bool_value` | boolean | `true` |
| INTEGER | `integer_value` | **string** | `"220"` |
| FLOAT | `float_value` | number | `22.5` |
| STRING | `string_value` | string | `"text"` |
| ENUM | `enum_value` | string | `"auto"` |
| COLOUR | `colour_value` | object | `{"h":360,"s":1000,"v":1000}` |

---

## 1. light — Осветительный прибор

**Категория:** `light`
**Обязательные features:** `online`, `on_off`

```json
{
    "category": "light",
    "features": [
        "online",
        "on_off",
        "light_mode",
        "light_brightness",
        "light_colour",
        "light_colour_temp"
    ],
    "dependencies": {
        "light_colour": {
            "key": "light_mode",
            "value": [{"type": "ENUM", "enum_value": "colour"}]
        }
    },
    "allowed_values": {
        "light_brightness": {
            "type": "INTEGER",
            "integer_values": {"min": "100", "max": "900", "step": "1"}
        }
    }
}
```

### Features

| Feature | Type | Обяз. | Описание | Значения |
|---------|------|-------|----------|----------|
| `online` | BOOL | Да | Доступность | true/false |
| `on_off` | BOOL | Да | Вкл/выкл | true/false |
| `light_brightness` | INTEGER | | Яркость | 50–1000 (промилле) |
| `light_colour` | COLOUR | | Цвет HSV | h:0–360, s:0–1000, v:100–1000 |
| `light_colour_temp` | INTEGER | | Цветовая температура | 0–1000 (0%=тёплый, 100%=холодный) |
| `light_mode` | ENUM | | Режим | `white`, `colour` |

### Состояние

```json
{
    "states": [
        {"key": "online", "value": {"type": "BOOL", "bool_value": true}},
        {"key": "on_off", "value": {"type": "BOOL", "bool_value": true}},
        {"key": "light_brightness", "value": {"type": "INTEGER", "integer_value": "500"}},
        {"key": "light_colour", "value": {"type": "COLOUR", "colour_value": {"h": 360, "s": 1000, "v": 1000}}},
        {"key": "light_colour_temp", "value": {"type": "INTEGER", "integer_value": "350"}},
        {"key": "light_mode", "value": {"type": "ENUM", "enum_value": "colour"}}
    ]
}
```

---

## 2. led_strip — Светодиодная лента

**Категория:** `led_strip`
**Обязательные features:** `online`, `on_off`
**Идентичен light** по features и поведению.

```json
{
    "category": "led_strip",
    "features": ["online", "on_off", "light_mode", "light_brightness", "light_colour", "light_colour_temp"],
    "dependencies": {
        "light_colour": {
            "key": "light_mode",
            "value": [{"type": "ENUM", "enum_value": "colour"}]
        }
    }
}
```

---

## 3. relay — Реле

**Категория:** `relay`
**Обязательные features:** `online`, `on_off`

```json
{
    "category": "relay",
    "features": ["online", "on_off", "current", "power", "voltage"]
}
```

### Features

| Feature | Type | Обяз. | Описание |
|---------|------|-------|----------|
| `online` | BOOL | Да | Доступность |
| `on_off` | BOOL | Да | Вкл/выкл |
| `current` | INTEGER | | Сила тока (мА) |
| `power` | INTEGER | | Мощность (Вт) |
| `voltage` | INTEGER | | Напряжение (В) |

### Состояние

```json
{
    "states": [
        {"key": "online", "value": {"type": "BOOL", "bool_value": true}},
        {"key": "on_off", "value": {"type": "BOOL", "bool_value": true}},
        {"key": "power", "value": {"type": "INTEGER", "integer_value": "150"}}
    ]
}
```

---

## 4. socket — Розетка

**Категория:** `socket`
**Обязательные features:** `online`, `on_off`

```json
{
    "category": "socket",
    "features": ["online", "on_off", "child_lock", "current", "power", "voltage"],
    "allowed_values": {
        "power": {"type": "INTEGER", "integer_values": {"min": "10", "max": "45000", "step": "1"}}
    }
}
```

### Features

| Feature | Type | Обяз. | Описание |
|---------|------|-------|----------|
| `online` | BOOL | Да | Доступность |
| `on_off` | BOOL | Да | Вкл/выкл |
| `child_lock` | BOOL | | Блокировка от детей |
| `current` | INTEGER | | Сила тока (мА) |
| `power` | INTEGER | | Мощность (Вт) |
| `voltage` | INTEGER | | Напряжение (В) |

---

## 5. curtain — Шторы

**Категория:** `curtain`
**Обязательные features:** `online`

```json
{
    "category": "curtain",
    "features": [
        "online",
        "battery_low_power", "battery_percentage",
        "open_left_percentage", "open_rate",
        "open_right_percentage", "open_right_set", "open_right_state",
        "open_set", "open_state",
        "signal_strength"
    ],
    "allowed_values": {
        "open_rate": {"type": "ENUM", "enum_values": {"values": ["auto", "low", "high"]}}
    }
}
```

### Features

| Feature | Type | Обяз. | Описание | Значения |
|---------|------|-------|----------|----------|
| `online` | BOOL | Да | Доступность | |
| `open_percentage` | INTEGER | | Процент открытия | 0–100 |
| `open_set` | ENUM | | Управление | open, close, stop |
| `open_state` | ENUM | | Текущее состояние | open, close |
| `open_rate` | ENUM | | Скорость | auto, low, high |
| `open_left_percentage` | INTEGER | | Левая створка % | 0–100 |
| `open_left_set` | ENUM | | Левая створка | open, close, stop |
| `open_left_state` | ENUM | | Состояние левой | open, close |
| `open_right_percentage` | INTEGER | | Правая створка % | 0–100 |
| `open_right_set` | ENUM | | Правая створка | open, close, stop |
| `open_right_state` | ENUM | | Состояние правой | open, close |
| `battery_low_power` | BOOL | | Батарея разряжена | |
| `battery_percentage` | INTEGER | | Заряд % | 0–100 |
| `signal_strength` | ENUM | | Сила сигнала | high, medium, low |

### Состояние

```json
{
    "states": [
        {"key": "online", "value": {"type": "BOOL", "bool_value": true}},
        {"key": "open_percentage", "value": {"type": "INTEGER", "integer_value": "30"}},
        {"key": "open_state", "value": {"type": "ENUM", "enum_value": "open"}}
    ]
}
```

---

## 6. window_blind — Жалюзи, рулонные шторы

**Категория:** `window_blind`
**Обязательные features:** `online`
**Аналогичен curtain**, но без двустворчатых features.

```json
{
    "category": "window_blind",
    "features": [
        "online",
        "battery_low_power", "battery_percentage",
        "open_percentage", "open_rate", "open_set", "open_state",
        "signal_strength"
    ]
}
```

---

## 7. gate — Ворота

**Категория:** `gate`
**Обязательные features:** `online`

```json
{
    "category": "gate",
    "features": [
        "online",
        "open_left_percentage", "open_left_set", "open_left_state",
        "open_rate",
        "open_right_percentage", "open_right_set", "open_right_state",
        "open_set", "open_state",
        "signal_strength"
    ]
}
```

---

## 8. hvac_ac — Кондиционер

**Категория:** `hvac_ac`
**Обязательные features:** `online`, `on_off`

```json
{
    "category": "hvac_ac",
    "features": [
        "online", "on_off",
        "hvac_temp_set", "hvac_air_flow_direction", "hvac_air_flow_power",
        "hvac_humidity_set", "hvac_night_mode", "hvac_work_mode"
    ],
    "allowed_values": {
        "hvac_air_flow_power": {
            "type": "ENUM",
            "enum_values": {"values": ["auto", "high", "low", "medium", "turbo"]}
        }
    }
}
```

### Features

| Feature | Type | Обяз. | Описание | Значения |
|---------|------|-------|----------|----------|
| `online` | BOOL | Да | Доступность | |
| `on_off` | BOOL | Да | Вкл/выкл | |
| `temperature` | INTEGER | | Текущая температура | -400..2000 (x10) |
| `hvac_temp_set` | INTEGER | | Целевая температура | 5..50 (°C, БЕЗ x10) |
| `hvac_air_flow_power` | ENUM | | Скорость вентилятора | auto, high, low, medium, quiet, turbo |
| `hvac_air_flow_direction` | ENUM | | Направление потока | auto, horizontal, no, rotation, swing, vertical |
| `hvac_work_mode` | ENUM | | Режим работы | (зависит от устройства) |
| `hvac_humidity_set` | INTEGER | | Целевая влажность | 0–100 (%) |
| `hvac_night_mode` | BOOL | | Ночной режим | |

### Состояние

```json
{
    "states": [
        {"key": "online", "value": {"type": "BOOL", "bool_value": true}},
        {"key": "on_off", "value": {"type": "BOOL", "bool_value": true}},
        {"key": "temperature", "value": {"type": "INTEGER", "integer_value": "220"}},
        {"key": "hvac_temp_set", "value": {"type": "INTEGER", "integer_value": "25"}},
        {"key": "hvac_air_flow_power", "value": {"type": "ENUM", "enum_value": "auto"}},
        {"key": "hvac_work_mode", "value": {"type": "ENUM", "enum_value": "cooling"}}
    ]
}
```

---

## 9. hvac_radiator — Терморегулятор

**Категория:** `hvac_radiator`
**Обязательные features:** `online`, `on_off`

```json
{
    "category": "hvac_radiator",
    "features": ["online", "on_off", "hvac_temp_set", "temperature"],
    "allowed_values": {
        "hvac_temp_set": {"type": "INTEGER", "integer_values": {"min": "25", "max": "40", "step": "5"}}
    }
}
```

---

## 10. hvac_humidifier — Увлажнитель воздуха

**Категория:** `hvac_humidifier`
**Обязательные features:** `online`, `on_off`

```json
{
    "category": "hvac_humidifier",
    "features": [
        "online", "on_off",
        "humidity",
        "hvac_air_flow_power", "hvac_humidity_set",
        "hvac_ionization", "hvac_night_mode",
        "hvac_replace_filter", "hvac_replace_ionizator",
        "hvac_water_low_level", "hvac_water_percentage"
    ],
    "allowed_values": {
        "hvac_air_flow_power": {
            "type": "ENUM",
            "enum_values": {"values": ["auto", "high", "low", "medium", "turbo"]}
        }
    }
}
```

### Features

| Feature | Type | Описание |
|---------|------|----------|
| `humidity` | INTEGER | Текущая влажность (0–100%) |
| `hvac_humidity_set` | INTEGER | Целевая влажность (0–100%) |
| `hvac_air_flow_power` | ENUM | Скорость вентилятора |
| `hvac_ionization` | BOOL | Ионизация вкл/выкл |
| `hvac_night_mode` | BOOL | Ночной режим |
| `hvac_replace_filter` | BOOL | Нужна замена фильтра |
| `hvac_replace_ionizator` | BOOL | Нужна замена ионизатора |
| `hvac_water_low_level` | BOOL | Мало воды |
| `hvac_water_percentage` | INTEGER | Уровень воды (0–100%) |

---

## 11. hvac_fan — Вентилятор

**Категория:** `hvac_fan`
**Обязательные features:** `online`, `on_off`

```json
{
    "category": "hvac_fan",
    "features": ["online", "on_off", "hvac_air_flow_power"],
    "allowed_values": {
        "hvac_air_flow_power": {
            "type": "ENUM",
            "enum_values": {"values": ["auto", "high", "low", "medium", "turbo"]}
        }
    }
}
```

---

## 12. hvac_heater — Обогреватель

**Категория:** `hvac_heater`
**Обязательные features:** `online`, `on_off`

```json
{
    "category": "hvac_heater",
    "features": ["online", "on_off", "hvac_temp_set", "temperature"],
    "allowed_values": {
        "hvac_temp_set": {"type": "INTEGER", "integer_values": {"min": "5", "max": "40", "step": "1"}}
    }
}
```

---

## 13. hvac_boiler — Котёл, водонагреватель

**Категория:** `hvac_boiler`
**Обязательные features:** `online`, `on_off`

```json
{
    "category": "hvac_boiler",
    "features": ["online", "on_off", "hvac_temp_set", "hvac_thermostat_mode", "temperature"],
    "allowed_values": {
        "hvac_temp_set": {"type": "INTEGER", "integer_values": {"min": "25", "max": "80", "step": "5"}}
    }
}
```

### Features

| Feature | Type | Описание | Значения |
|---------|------|----------|----------|
| `hvac_thermostat_mode` | ENUM | Режим термостата | cooling, drying, heating, ventilation |

---

## 14. hvac_underfloor_heating — Тёплый пол

**Категория:** `hvac_underfloor_heating`
**Обязательные features:** `online`, `on_off`

```json
{
    "category": "hvac_underfloor_heating",
    "features": ["online", "on_off", "hvac_temp_set", "hvac_thermostat_mode", "temperature"],
    "allowed_values": {
        "hvac_temp_set": {"type": "INTEGER", "integer_values": {"min": "25", "max": "50", "step": "5"}}
    }
}
```

---

## 15. hvac_air_purifier — Очиститель воздуха

**Категория:** `hvac_air_purifier`
**Обязательные features:** `online`, `on_off`

```json
{
    "category": "hvac_air_purifier",
    "features": [
        "online", "on_off",
        "hvac_air_flow_power", "hvac_aromatization",
        "hvac_ionization", "hvac_night_mode",
        "hvac_replace_filter", "hvac_replace_ionizator"
    ],
    "allowed_values": {
        "hvac_air_flow_power": {
            "type": "ENUM",
            "enum_values": {"values": ["auto", "high", "low", "medium", "turbo"]}
        }
    }
}
```

---

## 16. sensor_temp — Датчик температуры и влажности

**Категория:** `sensor_temp`
**Обязательные features:** `online`

```json
{
    "category": "sensor_temp",
    "features": [
        "online",
        "humidity", "temperature", "air_pressure",
        "battery_low_power", "battery_percentage",
        "sensor_sensitive", "signal_strength", "temp_unit_view"
    ],
    "allowed_values": {
        "sensor_sensitive": {"type": "ENUM", "enum_values": {"values": ["auto", "high"]}}
    }
}
```

### Состояние

```json
{
    "states": [
        {"key": "online", "value": {"type": "BOOL", "bool_value": true}},
        {"key": "temperature", "value": {"type": "INTEGER", "integer_value": "220"}},
        {"key": "humidity", "value": {"type": "INTEGER", "integer_value": "60"}},
        {"key": "battery_percentage", "value": {"type": "INTEGER", "integer_value": "85"}}
    ]
}
```

---

## 17. sensor_pir — Датчик движения

**Категория:** `sensor_pir`
**Обязательные features:** `online`, `pir`

```json
{
    "category": "sensor_pir",
    "features": [
        "online", "pir",
        "battery_low_power", "battery_percentage",
        "sensor_sensitive", "signal_strength"
    ]
}
```

### Состояние

```json
{
    "states": [
        {"key": "online", "value": {"type": "BOOL", "bool_value": true}},
        {"key": "pir", "value": {"type": "ENUM", "enum_value": "pir"}}
    ]
}
```

---

## 18. sensor_door — Датчик открытия

**Категория:** `sensor_door`
**Обязательные features:** `online`, `doorcontact_state`

```json
{
    "category": "sensor_door",
    "features": [
        "online", "doorcontact_state",
        "battery_low_power", "battery_percentage",
        "sensor_sensitive", "signal_strength", "tamper_alarm"
    ]
}
```

### Состояние

```json
{
    "states": [
        {"key": "online", "value": {"type": "BOOL", "bool_value": true}},
        {"key": "doorcontact_state", "value": {"type": "BOOL", "bool_value": false}}
    ]
}
```

Значения doorcontact_state:
- `true` — контакты разомкнуты (дверь/окно ОТКРЫТО)
- `false` — контакты сомкнуты (дверь/окно ЗАКРЫТО)

---

## 19. sensor_water_leak — Датчик протечки

**Категория:** `sensor_water_leak`
**Обязательные features:** `online`, `water_leak_state`

```json
{
    "category": "sensor_water_leak",
    "features": [
        "online", "water_leak_state",
        "battery_low_power", "battery_percentage",
        "signal_strength"
    ]
}
```

### Состояние

```json
{
    "states": [
        {"key": "online", "value": {"type": "BOOL", "bool_value": true}},
        {"key": "water_leak_state", "value": {"type": "BOOL", "bool_value": true}}
    ]
}
```

---

## 20. sensor_smoke — Датчик дыма

**Категория:** `sensor_smoke`
**Обязательные features:** `online`, `smoke_state`

```json
{
    "category": "sensor_smoke",
    "features": [
        "online", "smoke_state",
        "battery_low_power", "battery_percentage",
        "signal_strength"
    ]
}
```

### Состояние

```json
{
    "states": [
        {"key": "online", "value": {"type": "BOOL", "bool_value": true}},
        {"key": "smoke_state", "value": {"type": "BOOL", "bool_value": false}}
    ]
}
```

---

## 21. sensor_gas — Датчик газа

**Категория:** `sensor_gas`
**Обязательные features:** `online`, `gas_leak_state`

```json
{
    "category": "sensor_gas",
    "features": [
        "online", "gas_leak_state",
        "battery_low_power", "battery_percentage",
        "signal_strength"
    ]
}
```

### Состояние

```json
{
    "states": [
        {"key": "online", "value": {"type": "BOOL", "bool_value": true}},
        {"key": "gas_leak_state", "value": {"type": "BOOL", "bool_value": false}}
    ]
}
```

---

## 22. valve — Моторизованный кран

**Категория:** `valve`
**Обязательные features:** `online`
**ВАЖНО:** valve использует `open_set`/`open_state`, НЕ `on_off`!

```json
{
    "category": "valve",
    "features": [
        "online",
        "open_set", "open_state",
        "battery_low_power", "battery_percentage",
        "signal_strength"
    ]
}
```

### Features

| Feature | Type | Описание | Значения |
|---------|------|----------|----------|
| `open_set` | ENUM | Управление краном | open, close, stop |
| `open_state` | ENUM | Текущее состояние | open, close |

### Состояние

```json
{
    "states": [
        {"key": "online", "value": {"type": "BOOL", "bool_value": true}},
        {"key": "open_state", "value": {"type": "ENUM", "enum_value": "close"}}
    ]
}
```

---

## 23. scenario_button — Сценарная кнопка

**Категория:** `scenario_button`
**Обязательные features:** `online`, `button_event`

```json
{
    "category": "scenario_button",
    "features": ["online", "button_event"]
}
```

### Features

| Feature | Type | Описание | Значения |
|---------|------|----------|----------|
| `button_event` | ENUM | Тип нажатия | click, double_click, long_press |

Для кнопок с несколькими клавишами: `button_1_event`..`button_10_event`,
`button_left_event`, `button_right_event`, `button_top_left_event` и т.д.

---

## 24. kettle — Чайник

**Категория:** `kettle`
**Обязательные features:** `online`, `on_off`

```json
{
    "category": "kettle",
    "features": [
        "online", "on_off",
        "child_lock",
        "kitchen_water_level", "kitchen_water_low_level",
        "kitchen_water_temperature", "kitchen_water_temperature_set"
    ],
    "allowed_values": {
        "kitchen_water_temperature_set": {
            "type": "INTEGER",
            "integer_values": {"min": "60", "max": "100", "step": "10"}
        }
    }
}
```

---

## 25. tv — Телевизор

**Категория:** `tv`
**Обязательные features:** `online`, `on_off`

```json
{
    "category": "tv",
    "features": [
        "online", "on_off",
        "channel", "channel_int", "custom_key", "direction",
        "mute", "number", "source",
        "volume", "volume_int"
    ]
}
```

---

## 26. vacuum_cleaner — Пылесос

**Категория:** `vacuum_cleaner`
**Обязательные features:** `online`

```json
{
    "category": "vacuum_cleaner",
    "features": [
        "online",
        "battery_percentage", "child_lock",
        "vacuum_cleaner_cleaning_type", "vacuum_cleaner_command",
        "vacuum_cleaner_program", "vacuum_cleaner_status"
    ]
}
```

---

## 27. hub — Хаб

**Категория:** `hub`
**Обязательные features:** `online`

```json
{
    "category": "hub",
    "features": ["online"]
}
```

---

## Структура device (устройство пользователя)

```json
{
    "id": "entity_id",
    "parent_id": "hub_id",
    "name": "Имя от пользователя",
    "default_name": "Имя от производителя",
    "nicknames": ["Алиас 1", "Алиас 2"],
    "home": "Мой дом",
    "room": "Гостиная",
    "groups": ["Свет", "Автоматизация"],
    "model_id": "MODEL_123",
    "model": { /* ... если нет model_id ... */ },
    "hw_version": "1.0",
    "sw_version": "2.0",
    "partner_meta": {
        "custom_key": "custom_value"
    }
}
```

---

## Структура allowed_values

### INTEGER

```json
{
    "feature_name": {
        "type": "INTEGER",
        "integer_values": {
            "min": "0",
            "max": "100",
            "step": "1"
        }
    }
}
```

### ENUM

```json
{
    "feature_name": {
        "type": "ENUM",
        "enum_values": {
            "values": ["value1", "value2", "value3"]
        }
    }
}
```

### COLOUR

```json
{
    "feature_name": {
        "type": "COLOUR"
    }
}
```

---

## Структура dependencies

```json
{
    "dependencies": {
        "dependent_feature": {
            "key": "controlling_feature",
            "values": [
                {"type": "ENUM", "enum_value": "required_value"}
            ]
        }
    }
}
```

Пример: `light_colour` доступна только когда `light_mode` = `colour`.
