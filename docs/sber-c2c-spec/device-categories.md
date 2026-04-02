# Device Categories (категории устройств)

28 категорий устройств Sber Smart Home C2C протокола.

## Сводная таблица

| Категория | Название | Обязательные features |
|-----------|----------|----------------------|
| `curtain` | Шторы | `online` |
| `gate` | Ворота | `online` |
| `hub` | Хаб | `online` |
| `hvac_ac` | Кондиционер | `online`, `on_off` |
| `hvac_air_purifier` | Очиститель воздуха | `online`, `on_off` |
| `hvac_boiler` | Котёл / водонагреватель | `online`, `on_off` |
| `hvac_fan` | Вентилятор | `online`, `on_off` |
| `hvac_heater` | Обогреватель | `online`, `on_off` |
| `hvac_humidifier` | Увлажнитель воздуха | `online`, `on_off` |
| `hvac_radiator` | Терморегулятор | `online`, `on_off` |
| `hvac_underfloor_heating` | Тёплый пол | `online`, `on_off` |
| `intercom` | Домофон | `online` |
| `kettle` | Чайник | `online`, `on_off` |
| `led_strip` | Светодиодная лента | `online`, `on_off` |
| `light` | Осветительный прибор | `online`, `on_off` |
| `relay` | Реле | `online`, `on_off` |
| `scenario_button` | Сценарная кнопка | `online`, `button_event`* |
| `sensor_door` | Датчик открытия | `online`, `doorcontact_state` |
| `sensor_gas` | Датчик газа | `online`, `gas_leak_state` |
| `sensor_pir` | Датчик движения | `online`, `pir` |
| `sensor_smoke` | Датчик дыма | `online`, `smoke_state` |
| `sensor_temp` | Датчик температуры/влажности | `online` |
| `sensor_water_leak` | Датчик протечки | `online`, `water_leak_state` |
| `socket` | Розетка | `online`, `on_off` |
| `tv` | Телевизор | `online`, `on_off` |
| `vacuum_cleaner` | Пылесос | `online` |
| `valve` | Моторизованный кран | `online` |
| `window_blind` | Жалюзи / рулонные шторы | `online` |

*scenario_button: обязателен хотя бы один из `button_event`, `button_1_event`..`button_10_event`

---

## curtain

**Шторы.** Управление одно- и двустворчатыми шторами.

| Feature | Type | Обяз. | Описание |
|---------|------|:-----:|----------|
| `online` | BOOL | **Да** | Доступность |
| `open_set` | ENUM | | Управление: open, close, stop |
| `open_state` | ENUM | | Состояние: open, close |
| `open_percentage` | INTEGER | | Позиция 0–100% |
| `open_rate` | ENUM | | Скорость: auto, low, high |
| `open_left_percentage` | INTEGER | | Левая створка % |
| `open_left_set` | ENUM | | Левая створка управление |
| `open_left_state` | ENUM | | Левая створка состояние |
| `open_right_percentage` | INTEGER | | Правая створка % |
| `open_right_set` | ENUM | | Правая створка управление |
| `open_right_state` | ENUM | | Правая створка состояние |
| `battery_low_power` | BOOL | | Батарея разряжена |
| `battery_percentage` | INTEGER | | Заряд % |
| `signal_strength` | ENUM | | Сила сигнала |

```json
{
    "id": "QWERTY124",
    "manufacturer": "Xiaqara",
    "model": "SM1123456789",
    "category": "curtain",
    "features": ["battery_low_power", "battery_percentage", "online", "open_left_percentage", "open_rate", "open_right_percentage", "open_right_set", "open_right_state", "open_set", "open_state", "signal_strength"],
    "allowed_values": {
        "open_rate": {"type": "ENUM", "enum_values": {"values": ["auto", "low", "high"]}}
    }
}
```

---

## gate

**Ворота / гараж.**

| Feature | Type | Обяз. |
|---------|------|:-----:|
| `online` | BOOL | **Да** |
| `open_set` | ENUM | |
| `open_state` | ENUM | |
| `open_rate` | ENUM | |
| `open_left_percentage` | INTEGER | |
| `open_left_set` | ENUM | |
| `open_left_state` | ENUM | |
| `open_right_percentage` | INTEGER | |
| `open_right_set` | ENUM | |
| `open_right_state` | ENUM | |
| `signal_strength` | ENUM | |

```json
{
    "category": "gate",
    "features": ["online", "open_left_percentage", "open_left_set", "open_left_state", "open_rate", "open_right_percentage", "open_right_set", "open_right_state", "open_set", "open_state", "signal_strength"]
}
```

---

## hub

**Хаб.** Родительское устройство для дочерних.

| Feature | Type | Обяз. |
|---------|------|:-----:|
| `online` | BOOL | **Да** |

```json
{
    "id": "QWERTY124",
    "manufacturer": "Xiaqara",
    "model": "SM1123456789",
    "category": "hub",
    "features": ["online"]
}
```

---

## hvac_ac

**Кондиционер.**

| Feature | Type | Обяз. |
|---------|------|:-----:|
| `online` | BOOL | **Да** |
| `on_off` | BOOL | **Да** |
| `temperature` | INTEGER | |
| `hvac_temp_set` | INTEGER | |
| `hvac_work_mode` | ENUM | |
| `hvac_air_flow_power` | ENUM | |
| `hvac_air_flow_direction` | ENUM | |
| `hvac_humidity_set` | INTEGER | |
| `hvac_night_mode` | BOOL | |

```json
{
    "category": "hvac_ac",
    "features": ["online", "on_off", "hvac_temp_set", "hvac_air_flow_direction", "hvac_air_flow_power", "hvac_humidity_set", "hvac_night_mode", "hvac_work_mode"],
    "allowed_values": {
        "hvac_air_flow_power": {"type": "ENUM", "enum_values": {"values": ["auto", "high", "low", "medium", "turbo"]}}
    }
}
```

---

## hvac_air_purifier

**Очиститель воздуха.**

| Feature | Type | Обяз. |
|---------|------|:-----:|
| `online` | BOOL | **Да** |
| `on_off` | BOOL | **Да** |
| `hvac_air_flow_power` | ENUM | |
| `hvac_aromatization` | BOOL | |
| `hvac_decontaminate` | BOOL | |
| `hvac_ionization` | BOOL | |
| `hvac_night_mode` | BOOL | |
| `hvac_replace_filter` | BOOL | |
| `hvac_replace_ionizator` | BOOL | |

```json
{
    "category": "hvac_air_purifier",
    "features": ["online", "on_off", "hvac_air_flow_power", "hvac_aromatization", "hvac_ionization", "hvac_night_mode", "hvac_replace_filter", "hvac_replace_ionizator"],
    "allowed_values": {
        "hvac_air_flow_power": {"type": "ENUM", "enum_values": {"values": ["auto", "high", "low", "medium", "turbo"]}}
    }
}
```

---

## hvac_boiler

**Котёл / водонагреватель.**

| Feature | Type | Обяз. |
|---------|------|:-----:|
| `online` | BOOL | **Да** |
| `on_off` | BOOL | **Да** |
| `temperature` | INTEGER | |
| `hvac_temp_set` | INTEGER | |
| `hvac_thermostat_mode` | ENUM | |

```json
{
    "category": "hvac_boiler",
    "features": ["online", "on_off", "hvac_temp_set", "hvac_thermostat_mode", "temperature"],
    "allowed_values": {
        "hvac_temp_set": {"type": "INTEGER", "integer_values": {"min": "25", "max": "80", "step": "5"}}
    }
}
```

---

## hvac_fan

**Вентилятор.**

| Feature | Type | Обяз. |
|---------|------|:-----:|
| `online` | BOOL | **Да** |
| `on_off` | BOOL | **Да** |
| `hvac_air_flow_power` | ENUM | |

```json
{
    "category": "hvac_fan",
    "features": ["online", "on_off", "hvac_air_flow_power"],
    "allowed_values": {
        "hvac_air_flow_power": {"type": "ENUM", "enum_values": {"values": ["auto", "high", "low", "medium", "turbo"]}}
    }
}
```

---

## hvac_heater

**Обогреватель.**

| Feature | Type | Обяз. |
|---------|------|:-----:|
| `online` | BOOL | **Да** |
| `on_off` | BOOL | **Да** |
| `temperature` | INTEGER | |
| `hvac_temp_set` | INTEGER | |

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

## hvac_humidifier

**Увлажнитель воздуха.**

| Feature | Type | Обяз. |
|---------|------|:-----:|
| `online` | BOOL | **Да** |
| `on_off` | BOOL | **Да** |
| `humidity` | INTEGER | |
| `hvac_air_flow_power` | ENUM | |
| `hvac_humidity_set` | INTEGER | |
| `hvac_ionization` | BOOL | |
| `hvac_night_mode` | BOOL | |
| `hvac_replace_filter` | BOOL | |
| `hvac_replace_ionizator` | BOOL | |
| `hvac_water_low_level` | BOOL | |
| `hvac_water_percentage` | INTEGER | |

```json
{
    "category": "hvac_humidifier",
    "features": ["online", "on_off", "humidity", "hvac_air_flow_power", "hvac_humidity_set", "hvac_ionization", "hvac_night_mode", "hvac_replace_filter", "hvac_replace_ionizator", "hvac_water_low_level", "hvac_water_percentage"],
    "allowed_values": {
        "hvac_air_flow_power": {"type": "ENUM", "enum_values": {"values": ["auto", "high", "low", "medium", "turbo"]}}
    }
}
```

---

## hvac_radiator

**Терморегулятор для радиатора.**

| Feature | Type | Обяз. |
|---------|------|:-----:|
| `online` | BOOL | **Да** |
| `on_off` | BOOL | **Да** |
| `temperature` | INTEGER | |
| `hvac_temp_set` | INTEGER | |

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

## hvac_underfloor_heating

**Тёплый пол.**

| Feature | Type | Обяз. |
|---------|------|:-----:|
| `online` | BOOL | **Да** |
| `on_off` | BOOL | **Да** |
| `temperature` | INTEGER | |
| `hvac_temp_set` | INTEGER | |
| `hvac_thermostat_mode` | ENUM | |

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

## intercom

**Домофон.**

| Feature | Type | Обяз. |
|---------|------|:-----:|
| `online` | BOOL | **Да** |
| `incoming_call` | BOOL | |
| `reject_call` | BOOL | |
| `unlock` | BOOL | |

```json
{
    "category": "intercom",
    "features": ["online", "incoming_call", "reject_call", "unlock"]
}
```

---

## kettle

**Чайник.**

| Feature | Type | Обяз. |
|---------|------|:-----:|
| `online` | BOOL | **Да** |
| `on_off` | BOOL | **Да** |
| `child_lock` | BOOL | |
| `kitchen_water_level` | BOOL | |
| `kitchen_water_low_level` | BOOL | |
| `kitchen_water_temperature` | INTEGER | |
| `kitchen_water_temperature_set` | INTEGER | |

```json
{
    "category": "kettle",
    "features": ["child_lock", "kitchen_water_level", "kitchen_water_low_level", "kitchen_water_temperature", "kitchen_water_temperature_set", "on_off", "online"],
    "allowed_values": {
        "kitchen_water_temperature_set": {"type": "INTEGER", "integer_values": {"min": "60", "max": "100", "step": "10"}}
    }
}
```

---

## led_strip

**Светодиодная лента.** Идентична `light` по features.

| Feature | Type | Обяз. |
|---------|------|:-----:|
| `online` | BOOL | **Да** |
| `on_off` | BOOL | **Да** |
| `light_brightness` | INTEGER | |
| `light_colour` | COLOUR | |
| `light_colour_temp` | INTEGER | |
| `light_mode` | ENUM | |

```json
{
    "category": "led_strip",
    "features": ["online", "on_off", "light_mode", "light_brightness", "light_colour", "light_colour_temp"],
    "dependencies": {
        "light_colour": {"key": "light_mode", "value": [{"type": "ENUM", "enum_value": "colour"}]}
    }
}
```

---

## light

**Осветительный прибор.**

| Feature | Type | Обяз. |
|---------|------|:-----:|
| `online` | BOOL | **Да** |
| `on_off` | BOOL | **Да** |
| `light_brightness` | INTEGER | |
| `light_colour` | COLOUR | |
| `light_colour_temp` | INTEGER | |
| `light_mode` | ENUM | |

```json
{
    "category": "light",
    "features": ["online", "on_off", "light_mode", "light_brightness", "light_colour", "light_colour_temp"],
    "dependencies": {
        "light_colour": {"key": "light_mode", "value": [{"type": "ENUM", "enum_value": "colour"}]}
    },
    "allowed_values": {
        "light_brightness": {"type": "INTEGER", "integer_values": {"min": "100", "max": "900", "step": "1"}}
    }
}
```

---

## relay

**Реле.**

| Feature | Type | Обяз. |
|---------|------|:-----:|
| `online` | BOOL | **Да** |
| `on_off` | BOOL | **Да** |
| `current` | INTEGER | |
| `power` | INTEGER | |
| `voltage` | INTEGER | |

```json
{
    "category": "relay",
    "features": ["online", "on_off", "current", "power", "voltage"],
    "allowed_values": {
        "power": {"type": "INTEGER", "integer_values": {"min": "10", "max": "45000", "step": "1"}}
    }
}
```

---

## scenario_button

**Сценарная кнопка.**

| Feature | Type | Обяз. |
|---------|------|:-----:|
| `online` | BOOL | **Да** |
| `button_event` | ENUM | **Да*** |
| `button_1_event`..`button_10_event` | ENUM | |
| `button_left_event`, `button_right_event` | ENUM | |
| `button_top_left_event`, `button_top_right_event` | ENUM | |
| `button_bottom_left_event`, `button_bottom_right_event` | ENUM | |

*Обязателен хотя бы один button_*_event.

```json
{
    "category": "scenario_button",
    "features": ["online", "button_event"]
}
```

---

## sensor_door

**Датчик открытия двери/окна.**

| Feature | Type | Обяз. |
|---------|------|:-----:|
| `online` | BOOL | **Да** |
| `doorcontact_state` | BOOL | **Да** |
| `battery_low_power` | BOOL | |
| `battery_percentage` | INTEGER | |
| `sensor_sensitive` | ENUM | |
| `signal_strength` | ENUM | |
| `tamper_alarm` | BOOL | |

```json
{
    "category": "sensor_door",
    "features": ["online", "doorcontact_state", "battery_low_power", "battery_percentage", "sensor_sensitive", "signal_strength", "tamper_alarm"]
}
```

---

## sensor_gas

**Датчик газа.**

| Feature | Type | Обяз. |
|---------|------|:-----:|
| `online` | BOOL | **Да** |
| `gas_leak_state` | BOOL | **Да** |
| `battery_low_power` | BOOL | |
| `battery_percentage` | INTEGER | |
| `signal_strength` | ENUM | |

```json
{
    "category": "sensor_gas",
    "features": ["online", "gas_leak_state", "battery_low_power", "battery_percentage", "signal_strength"]
}
```

---

## sensor_pir

**Датчик движения.**

| Feature | Type | Обяз. |
|---------|------|:-----:|
| `online` | BOOL | **Да** |
| `pir` | ENUM | **Да** |
| `battery_low_power` | BOOL | |
| `battery_percentage` | INTEGER | |
| `sensor_sensitive` | ENUM | |
| `signal_strength` | ENUM | |

```json
{
    "category": "sensor_pir",
    "features": ["online", "pir", "battery_low_power", "battery_percentage", "sensor_sensitive", "signal_strength"]
}
```

---

## sensor_smoke

**Датчик дыма.**

| Feature | Type | Обяз. |
|---------|------|:-----:|
| `online` | BOOL | **Да** |
| `smoke_state` | BOOL | **Да** |
| `battery_low_power` | BOOL | |
| `battery_percentage` | INTEGER | |
| `signal_strength` | ENUM | |

```json
{
    "category": "sensor_smoke",
    "features": ["online", "smoke_state", "battery_low_power", "battery_percentage", "signal_strength"]
}
```

---

## sensor_temp

**Датчик температуры и влажности.**

| Feature | Type | Обяз. |
|---------|------|:-----:|
| `online` | BOOL | **Да** |
| `temperature` | INTEGER | |
| `humidity` | INTEGER | |
| `air_pressure` | INTEGER | |
| `battery_low_power` | BOOL | |
| `battery_percentage` | INTEGER | |
| `sensor_sensitive` | ENUM | |
| `signal_strength` | ENUM | |
| `temp_unit_view` | ENUM | |

```json
{
    "category": "sensor_temp",
    "features": ["online", "humidity", "temperature", "air_pressure", "battery_low_power", "battery_percentage", "sensor_sensitive", "signal_strength", "temp_unit_view"],
    "allowed_values": {
        "sensor_sensitive": {"type": "ENUM", "enum_values": {"values": ["auto", "high"]}}
    }
}
```

---

## sensor_water_leak

**Датчик протечки.**

| Feature | Type | Обяз. |
|---------|------|:-----:|
| `online` | BOOL | **Да** |
| `water_leak_state` | BOOL | **Да** |
| `battery_low_power` | BOOL | |
| `battery_percentage` | INTEGER | |
| `signal_strength` | ENUM | |

```json
{
    "category": "sensor_water_leak",
    "features": ["online", "water_leak_state", "battery_low_power", "battery_percentage", "signal_strength"]
}
```

---

## socket

**Розетка.**

| Feature | Type | Обяз. |
|---------|------|:-----:|
| `online` | BOOL | **Да** |
| `on_off` | BOOL | **Да** |
| `child_lock` | BOOL | |
| `current` | INTEGER | |
| `power` | INTEGER | |
| `voltage` | INTEGER | |

```json
{
    "category": "socket",
    "features": ["online", "on_off", "child_lock", "current", "power", "voltage"],
    "allowed_values": {
        "power": {"type": "INTEGER", "integer_values": {"min": "10", "max": "45000", "step": "1"}}
    }
}
```

---

## tv

**Телевизор.**

| Feature | Type | Обяз. |
|---------|------|:-----:|
| `online` | BOOL | **Да** |
| `on_off` | BOOL | **Да** |
| `channel` | ENUM | |
| `channel_int` | INTEGER | |
| `custom_key` | ENUM | |
| `direction` | ENUM | |
| `mute` | BOOL | |
| `number` | INTEGER | |
| `source` | ENUM | |
| `volume` | ENUM | |
| `volume_int` | INTEGER | |

```json
{
    "category": "tv",
    "features": ["channel", "channel_int", "custom_key", "direction", "mute", "number", "source", "volume", "volume_int", "on_off", "online"],
    "allowed_values": {
        "source": {"type": "ENUM", "enum_values": {"values": ["hdmi1", "hdmi2", "hdmi3", "tv", "av", "content", "+", "-"]}}
    }
}
```

---

## vacuum_cleaner

**Пылесос.**

| Feature | Type | Обяз. |
|---------|------|:-----:|
| `online` | BOOL | **Да** |
| `battery_percentage` | INTEGER | |
| `child_lock` | BOOL | |
| `vacuum_cleaner_cleaning_type` | ENUM | |
| `vacuum_cleaner_command` | ENUM | |
| `vacuum_cleaner_program` | ENUM | |
| `vacuum_cleaner_status` | ENUM | |

```json
{
    "category": "vacuum_cleaner",
    "features": ["battery_percentage", "child_lock", "vacuum_cleaner_cleaning_type", "vacuum_cleaner_command", "vacuum_cleaner_program", "vacuum_cleaner_status", "online"],
    "allowed_values": {
        "vacuum_cleaner_program": {"type": "ENUM", "enum_values": {"values": ["perimeter", "spot", "smart"]}}
    }
}
```

---

## valve

**Моторизованный кран.**

!!! warning "valve использует open_set/open_state, НЕ on_off"

| Feature | Type | Обяз. |
|---------|------|:-----:|
| `online` | BOOL | **Да** |
| `open_set` | ENUM | |
| `open_state` | ENUM | |
| `battery_low_power` | BOOL | |
| `battery_percentage` | INTEGER | |
| `signal_strength` | ENUM | |

```json
{
    "category": "valve",
    "features": ["online", "open_set", "open_state", "battery_low_power", "battery_percentage", "signal_strength"]
}
```

---

## window_blind

**Жалюзи / рулонные шторы.** Аналогичен `curtain`, но без двустворчатых features.

| Feature | Type | Обяз. |
|---------|------|:-----:|
| `online` | BOOL | **Да** |
| `open_percentage` | INTEGER | |
| `open_rate` | ENUM | |
| `open_set` | ENUM | |
| `open_state` | ENUM | |
| `light_transmission_percentage` | INTEGER | |
| `battery_low_power` | BOOL | |
| `battery_percentage` | INTEGER | |
| `signal_strength` | ENUM | |

```json
{
    "category": "window_blind",
    "features": ["online", "battery_low_power", "battery_percentage", "open_percentage", "open_rate", "open_set", "open_state", "signal_strength"]
}
```
