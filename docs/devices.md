# Поддерживаемые устройства

Интеграция поддерживает **28 категорий Sber**: 27 типов устройств с автоматическим маппингом между доменами Home Assistant и категориями Sber Smart Home, плюс виртуальный hub (корневое устройство, создаётся автоматически).

## Таблица соответствий

| Домен HA | Device class | Категория Sber | Класс | Возможности | Роли связывания |
|----------|-------------|----------------|-------|-------------|-----------------|
| `light` | -- | light | LightEntity | Вкл/выкл, яркость, цвет (HSV), цветовая температура | -- |
| `light` | -- (LED) | led_strip | LedStripEntity | LED-лента с цветом/яркостью | -- |
| `switch` | -- | relay | RelayEntity | Вкл/выкл | -- |
| `switch` | `outlet` | socket | SocketEntity | Вкл/выкл (иконка розетки в Сбер) | -- |
| `script` | -- | relay | RelayEntity | Запуск скрипта | -- |
| `button` | -- | relay | RelayEntity | Нажатие кнопки | -- |
| `cover` | -- | curtain | CurtainEntity | Открыть/закрыть/стоп, позиция 0-100% | -- |
| `cover` | `blind` / `shade` | window_blind | WindowBlindEntity | Открыть/закрыть/стоп, позиция 0-100% | -- |
| `climate` | -- | hvac_ac | ClimateEntity | Вкл/выкл, температура, вентилятор, качание, режим HVAC | temperature |
| `climate` | `radiator` | hvac_radiator | HvacRadiatorEntity | Вкл/выкл, температура (25-40 C) | -- |
| `climate` | `heater` | hvac_heater | HvacHeaterEntity | Обогреватель | -- |
| `climate` | -- | hvac_underfloor_heating | HvacUnderfloorHeatingEntity | Тёплый пол | -- |
| `sensor` | `temperature` | sensor_temp | SensorTempEntity | Показания температуры (точность 0.1 C) | battery, signal_strength, humidity |
| `sensor` | `humidity` | sensor_humidity | HumiditySensorEntity | Показания влажности (0-100%) | battery, signal_strength, temperature |
| `binary_sensor` | `motion` / `occupancy` / `presence` | sensor_pir | MotionSensorEntity | Обнаружение движения | battery, signal_strength |
| `binary_sensor` | `door` / `window` | sensor_door | DoorSensorEntity | Состояние открыто/закрыто | battery, signal_strength |
| `binary_sensor` | `moisture` | sensor_water_leak | WaterLeakSensorEntity | Обнаружение протечки | battery, signal_strength |
| `binary_sensor` | `smoke` | sensor_smoke | SmokeSensorEntity | Датчик дыма | battery, signal_strength |
| `binary_sensor` | `gas` | sensor_gas | GasSensorEntity | Датчик утечки газа | battery, signal_strength |
| `input_boolean` | -- | scenario_button | ScenarioButtonEntity | Клик / двойной клик | -- |
| `valve` | -- | valve | ValveEntity | Открыть/закрыть вентиль | -- |
| `humidifier` | -- | hvac_humidifier | HumidifierEntity | Вкл/выкл, влажность, режим работы | humidity |
| `fan` | -- | hvac_fan | HvacFanEntity | Вентилятор | -- |
| `fan` | `air_purifier` | hvac_air_purifier | HvacAirPurifierEntity | Очиститель воздуха | -- |
| `water_heater` | -- | hvac_boiler | HvacBoilerEntity | Бойлер/водонагреватель | -- |
| `water_heater` | `kettle` | kettle | KettleEntity | Умный чайник | -- |
| `media_player` | -- | tv | TvEntity | Телевизор | -- |
| `vacuum` | -- | vacuum_cleaner | VacuumCleanerEntity | Робот-пылесос | -- |
| -- | -- (override only) | intercom | IntercomEntity | Домофон | -- |
| -- | -- (автоматически) | hub | -- | Виртуальный хаб (корневое устройство) | -- |

## Освещение (light)

**Категория Sber**: `light`

Поддерживаемые возможности:

- **on_off** -- включение/выключение
- **light_brightness** -- яркость (0-100%)
- **light_colour** -- цвет в формате HSV (Hue, Saturation, Value)
- **light_colour_temp** -- цветовая температура

При получении команды от Sber интеграция вызывает `light.turn_on` / `light.turn_off` с соответствующими параметрами. Конвертация цвета между форматами HA и Sber выполняется автоматически.

## Переключатели (switch, script, button)

**Категория Sber**: `relay`

Простые устройства вкл/выкл. Скрипты и кнопки также маппятся как relay, но с соответствующими HA-сервисами (`script.turn_on`, `button.press`).

## Розетки (switch с device_class=outlet)

**Категория Sber**: `socket`

Аналогичны relay, но в приложении Сбер отображаются с иконкой розетки. Автоматически определяются по `device_class: outlet` у switch-сущности.

## Шторы и жалюзи (cover)

**Категории Sber**: `curtain` / `window_blind`

Поддерживаемые возможности:

- **open_state** -- состояние открыто/закрыто
- **curtain_position** -- позиция (0-100%)

Тип определяется по `device_class`: жалюзи (`blind`, `shade`) маппятся как `window_blind`, остальные -- как `curtain`.

## Климат (climate)

**Категория Sber**: `hvac_ac` / `hvac_radiator`

### Кондиционер (hvac_ac)

- **on_off** -- включение/выключение
- **temperature** -- целевая температура
- **fan_speed** -- скорость вентилятора (turbo, high, medium, low, quiet, auto)
- **hvac_swing** -- качание (on/off)
- **hvac_work_mode** -- режим работы: cooling, heating, ventilation, dehumidification, auto

**Роли связывания**: `temperature` — внешний датчик температуры может быть привязан для передачи фактической температуры в помещении.

### Радиатор (hvac_radiator)

- **on_off** -- включение/выключение
- **temperature** -- целевая температура (диапазон 25-40 C по умолчанию)

## Датчики

### Датчик температуры (sensor с device_class=temperature)

**Категория Sber**: `sensor_temp`

Передаёт показания температуры с точностью до 0.1 C (значение умножается на 10 для протокола Sber).

**Роли связывания**: `battery`, `signal_strength`, `humidity` — уровень заряда батареи, уровень сигнала и показания влажности могут быть привязаны к этому устройству через Entity Linking.

### Датчик влажности (sensor с device_class=humidity)

**Категория Sber**: `sensor_humidity`

Передаёт показания влажности в процентах (0-100%). Целочисленное значение.

**Роли связывания**: `battery`, `signal_strength`, `temperature` — уровень заряда, уровень сигнала и показания температуры могут быть привязаны к этому устройству через Entity Linking.

### Датчик движения (binary_sensor с device_class=motion/occupancy/presence)

**Категория Sber**: `sensor_pir`

Передаёт boolean-значение: движение обнаружено / не обнаружено. Поддерживает device_class: `motion`, `occupancy`, `presence`.

**Роли связывания**: `battery`, `signal_strength`.

### Датчик двери/окна (binary_sensor с device_class=door/window)

**Категория Sber**: `sensor_door`

Передаёт состояние: открыто / закрыто.

**Роли связывания**: `battery`, `signal_strength`.

### Датчик протечки (binary_sensor с device_class=moisture)

**Категория Sber**: `sensor_water_leak`

Передаёт boolean-значение: протечка обнаружена / не обнаружена.

**Роли связывания**: `battery`, `signal_strength`.

## Сценарная кнопка (input_boolean)

**Категория Sber**: `scenario_button`

Сущности `input_boolean` маппятся как сценарные кнопки Sber. Поддерживают события клика и двойного клика.

## Вентиль (valve)

**Категория Sber**: `valve`

Простое устройство вкл/выкл для управления вентилями (запорная арматура).

## Увлажнитель (humidifier)

**Категория Sber**: `hvac_humidifier`

Поддерживаемые возможности:

- **on_off** -- включение/выключение
- **humidity** -- целевая влажность (0-100%)
- **hvac_air_flow_power** -- мощность потока воздуха (режим работы из доступных режимов HA-сущности)

**Роли связывания**: `humidity` — внешний датчик влажности может быть привязан для передачи фактического уровня влажности в помещении.

## Связывание entity (Entity Linking)

Entity Linking позволяет объединить несколько HA-сущностей в одно устройство Sber. Это решает проблему, когда одно физическое устройство (например, Zigbee-датчик) создаёт несколько entity в HA: основную (leak, motion, temperature) и вспомогательные (battery, signal).

### Принцип работы

Привязанные entity не публикуются как отдельные устройства Sber. Вместо этого их данные включаются в состояние основного устройства при каждой публикации. При изменении состояния привязанной entity немедленно выполняется повторная публикация основного устройства.

Привязанные entity скрываются из списка доступных entity в панели управления — ими управляет основное устройство.

### Хранение конфигурации

Связи хранятся в `config_entry.options` под ключом `entity_links`:

```
{
  "binary_sensor.water_leak": {
    "battery": "sensor.water_leak_battery",
    "signal_strength": "sensor.water_leak_signal"
  }
}
```

### Автоопределение в мастере

При добавлении нового устройства через мастер интеграция автоматически ищет entity с тем же `device_id` в HA и предлагает совместимые для привязки. Несовместимые entity отображаются серым с пояснением "(not supported)".

### Поддерживаемые роли по категории

| Категория Sber | Доступные роли связывания |
|----------------|--------------------------|
| sensor_water_leak | battery, battery_low, signal_strength |
| sensor_pir | battery, battery_low, signal_strength |
| sensor_door | battery, battery_low, signal_strength |
| sensor_temp | battery, battery_low, signal_strength, humidity |
| sensor_humidity | battery, battery_low, signal_strength, temperature |
| hvac_ac | temperature |
| hvac_humidifier | humidity |

### Hub (корневое устройство)

Hub создаётся автоматически и не требует настройки. Он является корневым устройством в иерархии Sber и отвечает за идентификацию интеграции в облаке. Все экспортируемые устройства логически подчинены hub через поле `parent_id` в протоколе Sber.

## Статус тестирования на реальном оборудовании

!!! info "Данные из продакшен-инсталляции"
    Таблица отражает реальный опыт работы с Sber cloud. Устройства помечены статусом тестирования на физическом оборудовании.

### Протестировано на реальном оборудовании

| Категория Sber | Кол-во | Платформы HA | Примечания |
|----------------|:------:|-------------|------------|
| `light` | 15 | Zigbee (MQTT), ESPHome, switch_as_x | Яркость, цветовая температура, RGB (ESPHome). Все режимы проверены с Sber |
| `hvac_ac` | 2 | SmartIR | Кондиционеры: режимы, температура, вентилятор |
| `curtain` | 1 | Zigbee (MQTT) | Мотор штор: позиция 0-100%, open/close/stop |
| `valve` | 2 | switch_as_x | Моторизованные краны: ввод горячей/холодной воды |
| `hvac_fan` | 3 | switch_as_x | Вытяжная вентиляция: кухня, ванная, туалет |
| `sensor_pir` | 3 | Zigbee (MQTT) | Датчики движения/присутствия: Aqara, Tuya |
| `sensor_temp` | 3 | Zigbee (MQTT) | Датчики температуры + линковка humidity и battery |
| `sensor_water_leak` | 4 | Zigbee (MQTT) | Датчики протечки: Aqara, Tuya. С battery linking |
| `hvac_humidifier` | 1 | xiaomi_miio | Увлажнитель Xiaomi: режимы, влажность, humidity linking |
| `tv` | 4 | yandex_station, cast | Яндекс Станции + Haier Android TV (cast) |
| `scenario_button` | 1 | input_boolean | Эмуляция присутствия: click/double_click |
| `hub` | 1 | (автоматически) | Корневое устройство, parent_id для всех |

### Не тестировалось (нет оборудования)

!!! warning "Требуется помощь сообщества"
    Если у вас есть эти устройства и вы используете Sber Smart Home — помогите протестировать! Создайте issue с результатами.

| Категория Sber | Что нужно проверить | Приоритет |
|----------------|--------------------:|:---------:|
| `relay` | Zigbee/Wi-Fi реле (отдельное устройство, не switch_as_x) | Высокий |
| `socket` | Умная розетка с мониторингом энергии (power/voltage/current) | Высокий |
| `sensor_door` | Датчик открытия двери/окна: doorcontact_state (BOOL) | Высокий |
| `sensor_smoke` | Датчик дыма: smoke_state, alarm_mute | Средний |
| `sensor_gas` | Датчик утечки газа: gas_leak_state, alarm_mute | Средний |
| `hvac_radiator` | Термоголовка/терморегулятор на радиатор (Zigbee/Z-Wave) | Средний |
| `hvac_heater` | Электрический обогреватель с контролем температуры | Средний |
| `hvac_boiler` | Водонагреватель/бойлер | Средний |
| `hvac_underfloor_heating` | Контроллер тёплого пола | Средний |
| `hvac_air_purifier` | Очиститель воздуха с режимами и ионизацией | Средний |
| `kettle` | Умный чайник с контролем температуры | Низкий |
| `vacuum_cleaner` | Робот-пылесос с программами уборки | Низкий |
| `gate` | Ворота/гараж: open/close/stop | Низкий |
| `window_blind` | Жалюзи/рулонные шторы с позицией и tilt | Низкий |
| `led_strip` | Светодиодная лента (отдельно от обычного light) | Низкий |
| `intercom` | Домофон: входящий вызов, открытие замка | Низкий |
