# Sber Protocol Compliance Check (из Context7 + Playwright)

## Критические несоответствия нашего кода спецификации

### 1. integer_value — должен быть STRING, у нас int

Спецификация: `"integer_value": "220"` (string!)
Наш код: `"integer_value": 220` (int)

Пример из документации (temperature 22°C):
```json
{"key": "temperature", "value": {"type": "INTEGER", "integer_value": "220"}}
```

ОДНАКО! В примере MQTT agent-connect: `"integer_value": 256` (без кавычек!)
Вероятно Sber принимает оба варианта, но C2C API требует string.

### 2. pir — должен быть ENUM, у нас BOOL

Спецификация: `{"type": "ENUM", "enum_value": "pir"}`
Наш код: `{"type": "BOOL", "bool_value": true/false}`

### 3. doorcontact_state — должен быть BOOL, у нас ENUM

Спецификация: `{"type": "BOOL", "bool_value": false}` (true=open, false=closed)
Наш код: `{"type": "ENUM", "enum_value": "open"/"close"}`

### 4. water_leak_state (НЕ water_leak)

Правильное имя функции: `water_leak_state`, не `water_leak`
Спецификация: `{"type": "BOOL", "bool_value": true}`
Наш код: key="water_leak", type=BOOL — ключ неверный!

### 5. hvac_temp_set — обычные градусы, НЕ x10

Спецификация: `"integer_value": "25"` = 25°C (целые градусы, без x10!)
Наш код: `value.get("integer_value") / 10.0` — делим на 10, а не должны!

temperature (текущая) — x10: `"integer_value": "220"` = 22.0°C
hvac_temp_set (целевая) — БЕЗ x10: `"integer_value": "25"` = 25°C

### 6. open_percentage — integer_value как STRING

Спецификация: `"integer_value": "30"` (string)
Наш код: `int(value.get("integer_value", 0))` — принимаем int, шлём int

### 7. light_brightness — integer_value как STRING

Спецификация: `"integer_value": "500"` (string)

### 8. button_event — пропущен long_press

Спецификация: click, double_click, long_press
Наш код: click, double_click (нет long_press)

## Корректные реализации

| Функция | Спецификация | Наш код | Статус |
|---------|-------------|---------|--------|
| on_off | BOOL true/false | BOOL | OK |
| humidity | INTEGER "60" (0-100) | INTEGER round(humidity) | OK (значение верное, формат string?) |
| temperature | INTEGER "220" (x10) | INTEGER int(temp*10) | OK (значение верное) |
| light_colour | COLOUR {h,s,v} | COLOUR | OK |
| light_colour_temp | INTEGER "350" (0-1000) | INTEGER | OK |
| light_mode | ENUM white/colour | ENUM | OK |
| open_set | ENUM open/close/stop | ENUM | OK |
| open_state | ENUM open/close | ENUM | OK |
| button_event | ENUM click/double_click/long_press | ENUM (без long_press) | PARTIAL |
| hvac_work_mode | ENUM | ENUM | OK |

## Полный список категорий (27 штук, у нас 15)

Поддерживаются:
light, relay, socket, curtain, window_blind, gate, hvac_ac, hvac_radiator,
hvac_humidifier, sensor_temp, sensor_pir, sensor_door, sensor_water_leak,
valve, scenario_button

НЕ поддерживаются (12):
hub, hvac_air_purifier, hvac_boiler, hvac_fan, hvac_heater,
hvac_underfloor_heating, intercom, kettle, led_strip, sensor_gas,
sensor_smoke, tv, vacuum_cleaner
