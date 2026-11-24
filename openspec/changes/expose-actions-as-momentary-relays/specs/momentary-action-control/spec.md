# Spec Delta

## Purpose

Позволяет запускать виртуальную кнопку или сцену Home Assistant из приложения
и сценариев Sber через явно выбранное реле с разовым действием.

## ADDED Requirements

### Requirement: Explicit relay selection
Мост SHALL предлагать Relay для input_button и scene без HA device, сохраняя автоматический выбор scenario_button и приоритет UI override над YAML и Auto.

#### Scenario: Choose the control direction
- **WHEN** пользователь выбирает Relay для input_button или scene
- **THEN** модель содержит online и on_off без button_event
- **AND** подсказка объясняет запуск HA из Sber

### Requirement: On executes one action
Мост SHALL вызывать input_button.press или scene.turn_on один раз на каждую принятую команду on, даже если предыдущей командой также была on.

#### Scenario: Consecutive commands
- **WHEN** поступают две отдельные команды on для одной сущности
- **THEN** соответствующий HA service вызывается дважды

### Requirement: Off is inert
Мост SHALL NOT запускать или отменять действие при off, включая отсутствующий bool_value в BOOL. Значения другого протокольного типа SHALL NOT запускать действие.

#### Scenario: Turn off a scene relay
- **WHEN** поступает off для scene
- **THEN** scene.turn_off не вызывается и сцена не активируется повторно

### Requirement: Ready state stays off
Мост SHALL показывать on_off=false для разового действия, включая ответ на on, повторную публикацию, ошибку и задержку сервиса. Это готовность к новому запуску, а не состояние физических устройств сцены.

#### Scenario: Action completed
- **WHEN** команда on выполнена
- **THEN** публикуется on_off=false без button_event
- **AND** в диагностике нет ожидания устойчивого состояния on для этого разового действия

#### Scenario: Service failed
- **WHEN** HA service завершился ошибкой
- **THEN** ошибка видна в журнале, ответ не утверждает состояние on

### Requirement: Availability and lifecycle
Мост SHALL считать ещё не использованную сущность с unknown доступной, а отсутствующую/unavailable — недоступной. Загрузка и восстановление соединения SHALL NOT исполнять действие.

#### Scenario: First use after startup
- **WHEN** загружается unknown или сохранённое время активации
- **THEN** реле онлайн и выключено, HA service не вызывается

#### Scenario: Entity removed
- **WHEN** HA удаляет состояние экспортированной сущности
- **THEN** мост сообщает online=false

### Requirement: Preserve existing representations
Мост SHALL сохранять обычное on/off физических реле и input_boolean, а также существующее поведение button/script. Явная смена категории SHALL сохранять имя и размещение и публиковать полный список устройств.

#### Scenario: Change the test scene category
- **WHEN** сохранённый override сцены меняется на relay
- **THEN** её имя и комната сохраняются, а остальные экспортированные устройства остаются в config
