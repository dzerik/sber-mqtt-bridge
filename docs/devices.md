# Поддерживаемые устройства

Интеграция поддерживает 15 типов устройств с автоматическим маппингом между доменами Home Assistant и категориями Sber Smart Home.

## Таблица соответствий

| Домен HA | Device class | Категория Sber | Класс | Возможности |
|----------|-------------|----------------|-------|-------------|
| `light` | -- | light | LightEntity | Вкл/выкл, яркость, цвет (HSV), цветовая температура |
| `switch` | -- | relay | RelayEntity | Вкл/выкл |
| `switch` | `outlet` | socket | SocketEntity | Вкл/выкл (иконка розетки в Сбер) |
| `script` | -- | relay | RelayEntity | Запуск скрипта |
| `button` | -- | relay | RelayEntity | Нажатие кнопки |
| `cover` | -- | curtain | CurtainEntity | Открыть/закрыть/стоп, позиция 0-100% |
| `cover` | `blind` / `shade` | window_blind | WindowBlindEntity | Открыть/закрыть/стоп, позиция 0-100% |
| `climate` | -- | hvac_ac | ClimateEntity | Вкл/выкл, температура, вентилятор, качание, режим HVAC |
| `climate` | `radiator` | hvac_radiator | HvacRadiatorEntity | Вкл/выкл, температура (25-40 C) |
| `sensor` | `temperature` | sensor_temp | SensorTempEntity | Показания температуры (точность 0.1 C) |
| `sensor` | `humidity` | sensor_temp | HumiditySensorEntity | Показания влажности (0-100%) |
| `binary_sensor` | `motion` | sensor_pir | MotionSensorEntity | Обнаружение движения |
| `binary_sensor` | `door` / `window` | sensor_door | DoorSensorEntity | Состояние открыто/закрыто |
| `binary_sensor` | `moisture` | sensor_water_leak | WaterLeakSensorEntity | Обнаружение протечки |
| `input_boolean` | -- | scenario_button | ScenarioButtonEntity | Клик / двойной клик |
| `valve` | -- | valve | ValveEntity | Открыть/закрыть вентиль |
| `humidifier` | -- | hvac_humidifier | HumidifierEntity | Вкл/выкл, влажность, режим работы |

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
- **fan_speed** -- скорость вентилятора
- **hvac_swing** -- качание
- **hvac_mode** -- режим (охлаждение, нагрев, авто и т.д.)

### Радиатор (hvac_radiator)

- **on_off** -- включение/выключение
- **temperature** -- целевая температура (диапазон 25-40 C по умолчанию)

## Датчики

### Датчик температуры (sensor с device_class=temperature)

**Категория Sber**: `sensor_temp`

Передаёт показания температуры с точностью до 0.1 C (значение умножается на 10 для протокола Sber).

### Датчик влажности (sensor с device_class=humidity)

**Категория Sber**: `sensor_temp`

Передаёт показания влажности в процентах (0-100%). Целочисленное значение.

### Датчик движения (binary_sensor с device_class=motion)

**Категория Sber**: `sensor_pir`

Передаёт boolean-значение: движение обнаружено / не обнаружено.

### Датчик двери/окна (binary_sensor с device_class=door/window)

**Категория Sber**: `sensor_door`

Передаёт состояние: открыто / закрыто.

### Датчик протечки (binary_sensor с device_class=moisture)

**Категория Sber**: `sensor_water_leak`

Передаёт boolean-значение: протечка обнаружена / не обнаружена.

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
- **work_mode** -- режим работы (берётся из доступных режимов HA-сущности)
