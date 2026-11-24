# Spec Delta

## Purpose

Позволяет использовать нажатия виртуальных кнопок и активации сцен Home Assistant
как события для запуска сценариев Sber, сохраняя разовый характер этих событий.

## ADDED Requirements

### Requirement: Action domains can be selected
Мост SHALL предлагать `input_button` и `scene` как `scenario_button`, включая сущности без HA device.

#### Scenario: Select an orphan action
- **WHEN** пользователь открывает список сценарных кнопок
- **THEN** доступные `input_button` и `scene` без HA device присутствуют в списке
- **AND** после добавления их модель имеет категорию `scenario_button`

### Requirement: Fresh activations become clicks
Мост SHALL преобразовывать новое нажатие `input_button` или активацию `scene` в `button_event: click`.

#### Scenario: Repeated activations
- **GIVEN** предыдущий клик уже опубликован
- **WHEN** время последней активации сущности изменяется снова
- **THEN** мост отправляет новый `click`, даже если предыдущим событием также был `click`

#### Scenario: Attribute-only update
- **WHEN** меняются только атрибуты без изменения времени активации
- **THEN** новый клик не отправляется

### Requirement: Only actual capabilities are advertised
Модель новых доменов SHALL объявлять только одиночное нажатие и не SHALL объявлять on/off или двойное/долгое нажатие.

#### Scenario: Build a scene model
- **WHEN** мост описывает модель экспортированной сцены
- **THEN** допустимым значением `button_event` является только `click`
- **AND** функция `on_off` отсутствует

### Requirement: Initial state does not trigger scenarios
Мост SHALL использовать загруженное время активации как исходное состояние без клика. `unknown` для ещё не использованной сущности SHALL означать доступность, а `unavailable` — недоступность.

#### Scenario: First ever activation
- **GIVEN** при загрузке состояние сущности было `unknown`
- **WHEN** приходит первая активация с временем запуска
- **THEN** публикуется `click`

#### Scenario: Reload and status request
- **WHEN** мост загружает сохранённое время активации либо перепубликует уже отправленное состояние
- **THEN** старый клик не повторяется

#### Scenario: Recover from unavailable initial state
- **GIVEN** сущность при загрузке была недоступна
- **WHEN** впервые становится доступно сохранённое время активации
- **THEN** оно принимается за исходное состояние без клика

### Requirement: Existing representations remain compatible
Мост SHALL сохранять текущие события `input_boolean` и `event` и не SHALL добавлять управление HA-сценой через on/off в рамках этого изменения.

#### Scenario: Boolean changes
- **WHEN** legacy `input_boolean` переходит в on или off
- **THEN** сохраняются соответственно `click` или `double_click`

#### Scenario: Incoming button event
- **WHEN** приходит команда для сценарной кнопки
- **THEN** мост не вызывает `scene.turn_on` или `input_button.press` без отдельной реализации такого контракта
