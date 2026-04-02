# Validation Rules

Пронумерованные инварианты протокола для использования в тестах. Каждое правило основано на официальной документации Sber.

## Структуры данных

### VR-001: model_id и model взаимоисключающие

В объекте Device используется **строго одно** из двух: `model_id` или `model`. Передавать оба одновременно запрещено.

**Источник:** [structures — device](https://developers.sber.ru/docs/ru/smarthome/c2c/structures)

```python
# Test assertion
assert not (device.get("model_id") and device.get("model")), \
    "model_id and model are mutually exclusive"
assert device.get("model_id") or device.get("model"), \
    "Either model_id or model must be present"
```

### VR-002: integer_value — string в C2C API

В C2C API поле `integer_value` передаётся как **строка**, не как число.

**Источник:** [structures — value](https://developers.sber.ru/docs/ru/smarthome/c2c/value)

```python
# Test assertion
if state["value"]["type"] == "INTEGER":
    assert isinstance(state["value"]["integer_value"], str), \
        f"integer_value must be string, got {type(state['value']['integer_value'])}"
```

### VR-003: partner_meta max 1024 chars

Поле `partner_meta` при сериализации в JSON не должно превышать 1024 символа.

**Источник:** [structures — device](https://developers.sber.ru/docs/ru/smarthome/c2c/structures)

```python
import json
assert len(json.dumps(device.get("partner_meta", {}))) <= 1024
```

### VR-004: colour_value диапазоны

HSV цвет: h: 0–360, s: 0–1000, v: **100**–1000 (минимум v = 100, не 0).

**Источник:** [light-colour](https://developers.sber.ru/docs/ru/smarthome/c2c/light-colour)

```python
colour = state["value"]["colour_value"]
assert 0 <= colour["h"] <= 360
assert 0 <= colour["s"] <= 1000
assert 100 <= colour["v"] <= 1000  # v minimum is 100!
```

### VR-005: allowed_values integer_values — строки

В `allowed_values` для типа INTEGER поля `min`, `max`, `step` — **строки**.

**Источник:** [allowed_values](https://developers.sber.ru/docs/ru/smarthome/c2c/allowed_values)

```python
av = model["allowed_values"]["hvac_temp_set"]
assert av["type"] == "INTEGER"
for field in ("min", "max", "step"):
    assert isinstance(av["integer_values"][field], str)
```

---

## Категории и features

### VR-010: online обязателен для всех категорий

Каждая категория устройств **обязана** включать `online` в списке features.

**Источник:** все страницы категорий

```python
assert "online" in model["features"], \
    f"Category {model['category']} must include 'online'"
```

### VR-011: on_off обязателен для управляемых устройств

Категории light, led_strip, relay, socket, hvac_ac, hvac_radiator, hvac_heater, hvac_boiler, hvac_underfloor_heating, hvac_fan, hvac_air_purifier, hvac_humidifier, kettle, tv **обязаны** включать `on_off`.

```python
ON_OFF_REQUIRED = {"light", "led_strip", "relay", "socket", "hvac_ac",
    "hvac_radiator", "hvac_heater", "hvac_boiler", "hvac_underfloor_heating",
    "hvac_fan", "hvac_air_purifier", "hvac_humidifier", "kettle", "tv"}
if model["category"] in ON_OFF_REQUIRED:
    assert "on_off" in model["features"]
```

### VR-012: valve использует open_set/open_state, НЕ on_off

Категория `valve` управляется через `open_set`/`open_state`, а **не** через `on_off`.

**Источник:** [valve](https://developers.sber.ru/docs/ru/smarthome/c2c/valve)

### VR-013: sensor_pir — pir обязателен

Категория `sensor_pir` обязана включать feature `pir`.

### VR-014: sensor_door — doorcontact_state обязателен

Категория `sensor_door` обязана включать feature `doorcontact_state`.

### VR-015: sensor_water_leak — water_leak_state обязателен

Категория `sensor_water_leak` обязана включать feature `water_leak_state` (не `water_leak`!).

### VR-016: scenario_button — минимум один button event

Категория `scenario_button` обязана включать хотя бы один из: `button_event`, `button_1_event`..`button_10_event`, `button_left_event`, и т.д.

---

## Типы данных features

### VR-020: pir — тип ENUM

Feature `pir` имеет тип **ENUM**, не BOOL. Значение: `"pir"`.

**Источник:** [pir](https://developers.sber.ru/docs/ru/smarthome/c2c/pir)

```python
# Correct
{"key": "pir", "value": {"type": "ENUM", "enum_value": "pir"}}
# Wrong
{"key": "pir", "value": {"type": "BOOL", "bool_value": true}}
```

### VR-021: doorcontact_state — тип BOOL

Feature `doorcontact_state` имеет тип **BOOL**, не ENUM. `true` = открыто, `false` = закрыто.

**Источник:** [doorcontact_state](https://developers.sber.ru/docs/ru/smarthome/c2c/doorcontact_state)

```python
# Correct
{"key": "doorcontact_state", "value": {"type": "BOOL", "bool_value": false}}
# Wrong
{"key": "doorcontact_state", "value": {"type": "ENUM", "enum_value": "open"}}
```

### VR-022: water_leak_state — имя и тип

Правильное имя: `water_leak_state` (не `water_leak`). Тип: **BOOL**.

**Источник:** [sensor_water_leak](https://developers.sber.ru/docs/ru/smarthome/c2c/sensor_water_leak)

### VR-023: temperature — x10

Feature `temperature` (текущая) передаётся с множителем **x10**: `"220"` = 22.0°C.

**Источник:** [temperature](https://developers.sber.ru/docs/ru/smarthome/c2c/temperature)

```python
# 22.0°C = "220"
actual_temp = int(state["value"]["integer_value"]) / 10.0
```

### VR-024: hvac_temp_set — НЕ x10

Feature `hvac_temp_set` (целевая) передаётся **без** множителя: `"25"` = 25°C.

**Источник:** [hvac_temp_set](https://developers.sber.ru/docs/ru/smarthome/c2c/hvac_temp_set)

```python
# 25°C = "25" (NOT "250")
target_temp = int(state["value"]["integer_value"])
```

### VR-025: button_event — три значения

Feature `button_event` (и все `button_*_event`) поддерживают три значения: `click`, `double_click`, `long_press`.

**Источник:** [button_event](https://developers.sber.ru/docs/ru/smarthome/c2c/button_event)

```python
VALID_BUTTON_EVENTS = {"click", "double_click", "long_press"}
assert state["value"]["enum_value"] in VALID_BUTTON_EVENTS
```

---

## MQTT Payload

### VR-030: up/config — devices массив

В `up/config` поле `devices` — **массив** объектов Device.

```python
assert isinstance(config_payload["devices"], list)
```

### VR-031: up/status — devices словарь

В `up/status` поле `devices` — **словарь** `{device_id: {states: [...]}}`.

```python
assert isinstance(status_payload["devices"], dict)
```

### VR-032: down/commands — devices словарь

В `down/commands` поле `devices` — **словарь**, аналогично `up/status`.

### VR-033: down/status_request — devices массив строк

В `down/status_request` поле `devices` — **массив строк** (device_id).

```python
assert isinstance(request_payload["devices"], list)
assert all(isinstance(d, str) for d in request_payload["devices"])
```

### VR-034: down/config_request — пустой объект

Payload `down/config_request` — пустой JSON объект `{}`.

---

## Dependencies

### VR-040: light_colour зависит от light_mode

Feature `light_colour` доступна **только** когда `light_mode` = `colour`.

**Источник:** [light](https://developers.sber.ru/docs/ru/smarthome/c2c/light)

```python
# In model dependencies
assert model["dependencies"]["light_colour"]["key"] == "light_mode"
assert model["dependencies"]["light_colour"]["value"] == [
    {"type": "ENUM", "enum_value": "colour"}
]
```

---

## Полный список по номерам

| ID | Правило | Раздел |
|----|---------|--------|
| VR-001 | model_id и model взаимоисключающие | Структуры |
| VR-002 | integer_value — string | Структуры |
| VR-003 | partner_meta max 1024 chars | Структуры |
| VR-004 | colour_value: h 0-360, s 0-1000, v 100-1000 | Структуры |
| VR-005 | allowed_values integer min/max/step — строки | Структуры |
| VR-010 | online обязателен для всех категорий | Категории |
| VR-011 | on_off обязателен для управляемых устройств | Категории |
| VR-012 | valve: open_set/open_state, не on_off | Категории |
| VR-013 | sensor_pir: pir обязателен | Категории |
| VR-014 | sensor_door: doorcontact_state обязателен | Категории |
| VR-015 | sensor_water_leak: water_leak_state (не water_leak) | Категории |
| VR-016 | scenario_button: минимум один button event | Категории |
| VR-020 | pir — ENUM, не BOOL | Типы |
| VR-021 | doorcontact_state — BOOL, не ENUM | Типы |
| VR-022 | water_leak_state — правильное имя и тип BOOL | Типы |
| VR-023 | temperature — x10 | Типы |
| VR-024 | hvac_temp_set — НЕ x10 | Типы |
| VR-025 | button_event — click, double_click, long_press | Типы |
| VR-030 | up/config: devices — массив | MQTT |
| VR-031 | up/status: devices — словарь | MQTT |
| VR-032 | down/commands: devices — словарь | MQTT |
| VR-033 | down/status_request: devices — массив строк | MQTT |
| VR-034 | down/config_request: пустой объект | MQTT |
| VR-040 | light_colour зависит от light_mode=colour | Dependencies |
