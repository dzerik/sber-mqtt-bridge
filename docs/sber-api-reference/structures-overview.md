# Sber Smart Home API Reference (scraped via Playwright)

## Полный список категорий устройств

- curtain — шторы
- gate — ворота
- hub — хаб
- hvac_ac — кондиционер
- hvac_air_purifier — очиститель воздуха
- hvac_boiler — котел, контроллер отопления
- hvac_fan — вентилятор
- hvac_heater — обогреватель
- hvac_humidifier — увлажнитель воздуха
- hvac_radiator — термоголовка, терморегулятор для радиатора
- hvac_underfloor_heating — теплый пол
- intercom — домофон
- kettle — чайник
- led_strip — светодиодная лента
- light — осветительный прибор
- relay — реле
- scenario_button — сценарная кнопка
- sensor_door — датчик открытия
- sensor_gas — датчик газа
- sensor_pir — датчик движения
- sensor_smoke — датчик дыма
- sensor_temp — датчик температуры и влажности
- sensor_water_leak — датчик протечки
- socket — розетка
- tv — телевизор
- vacuum_cleaner — пылесос
- valve — моторизованный кран
- window_blind — жалюзи, рулонные шторы

## Полный список функций (features)

air_pressure, alarm_mute, battery_low_power, battery_percentage,
button_1_event..button_10_event, button_bottom_left_event, button_bottom_right_event,
button_event, button_left_event, button_right_event, button_top_left_event, button_top_right_event,
channel, channel_int, child_lock, current, custom_key, direction,
doorcontact_state, gas_leak_state, humidity,
hvac_air_flow_direction, hvac_air_flow_power, hvac_aromatization, hvac_decontaminate,
hvac_direction_set, hvac_heating_rate, hvac_humidity_set, hvac_ionization, hvac_night_mode,
hvac_replace_filter, hvac_replace_ionizator, hvac_temp_set, hvac_thermostat_mode,
hvac_water_level, hvac_water_low_level, hvac_water_percentage, hvac_work_mode,
incoming_call, kitchen_water_level, kitchen_water_low_level, kitchen_water_temperature,
kitchen_water_temperature_set, light_brightness, light_colour, light_colour_temp, light_mode,
light_transmission_percentage, mute, number, on_off, online,
open_left_percentage, open_left_set, open_left_state,
open_percentage, open_rate, open_right_percentage, open_right_set, open_right_state,
open_set, open_state, pir, power, reject_call, source,
sensor_sensitive, signal_strength, smoke_state, tamper_alarm, temp_unit_view, temperature,
unlock, vacuum_cleaner_cleaning_type, vacuum_cleaner_command, vacuum_cleaner_program,
vacuum_cleaner_status, voltage, volume, volume_int, water_leak_state

## Структура value (значение функции)

| Поле | Тип | Обяз. | Описание |
|------|-----|-------|----------|
| type | string | Да | FLOAT, INTEGER, STRING, BOOL, ENUM, COLOUR |
| float_value | number | | Вещественное значение |
| integer_value | string | | Целочисленное значение long, записанное в виде строки (!) |
| string_value | string | | Строковое значение |
| bool_value | boolean | | Логическое значение |
| enum_value | string | | Перечисляемое значение |
| colour_value | object | | HSV: {"h":int,"s":int,"v":int}. h:0-360, s:0-1000, v:100-1000 |

## Структура state (состояние устройства)

| Поле | Тип | Обяз. | Описание |
|------|-----|-------|----------|
| key | string | Да | Название функции |
| value | object | Да | Значение функции (см. value) |

```json
{"states": [{"key": "light_mode", "value": {"type": "ENUM", "enum_value": "colour"}}]}
```

## Структура model (модель устройства)

| Поле | Тип | Обяз. | Описание |
|------|-----|-------|----------|
| id | string | Да | ID модели |
| manufacturer | string | Да | Производитель |
| model | string | Да | Название модели |
| hw_version | string | | Версия оборудования |
| sw_version | string | | Версия прошивки |
| description | string | | Описание |
| category | string | Да | Категория (см. Устройства) |
| features | list<string> | Да | Список функций |
| allowed_values | map<string, object> | | Допустимые значения |

## Структура device (устройство пользователя)

| Поле | Тип | Обяз. | Описание |
|------|-----|-------|----------|
| id | string | Да | ID устройства в системе вендора |
| parent_id | string | | ID родительского устройства (хаба) |
| name | string | Да | Название от пользователя |
| default_name | string | Да | Название от производителя |
| home | string | | Группа помещений |
| room | string | | Помещение |
| groups | list<string> | | Группы устройств |
| model_id | string | Да | ID модели (или model object) |
| model | object | Да | Описание модели (если нет model_id) |
| hw_version | string | | Версия оборудования |
| sw_version | string | | Версия прошивки |
| partner_meta | object | | Произвольная информация (max 1024 chars JSON) |

## allowed_values (допустимые значения)

INTEGER пример:
```json
{"hvac_temp_set": {"type": "INTEGER", "integer_values": {"min": "25", "max": "40", "step": "5"}}}
```

ENUM пример:
```json
{"hvac_air_flow_power": {"type": "ENUM", "enum_values": {"values": ["auto","high","low","medium","turbo"]}}}
```

INTEGER (light_brightness) пример:
```json
{"light_brightness": {"type": "INTEGER", "integer_values": {"min": "100", "max": "900", "step": "1"}}}
```

## hvac_radiator — терморегулятор

Обязательные функции: online, on_off
Опциональные: hvac_temp_set, temperature

Пример модели:
```json
{
  "id": "QWERTY124",
  "manufacturer": "Xiaqara",
  "model": "SM1123456789",
  "category": "hvac_radiator",
  "features": ["hvac_temp_set", "on_off", "online", "temperature"],
  "allowed_values": {
    "hvac_temp_set": {"type": "INTEGER", "integer_values": {"min": "25", "max": "40", "step": "5"}}
  }
}
```

Пример устройства пользователя:
```json
{
  "id": "ABCD_004",
  "name": "Мой терморегулятор",
  "default_name": "Умный терморегулятор",
  "home": "Мой дом",
  "room": "Гостиная",
  "groups": ["Климат", "Обогрев"],
  "model_id": "QWERTY124"
}
```
