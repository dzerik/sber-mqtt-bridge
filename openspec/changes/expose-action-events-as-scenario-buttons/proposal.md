# Proposal

## Why

Пользователь хочет проверить представление HA `input_button` и `scene` как
сценарных кнопок Sber. Текущий адаптер поддерживает `input_boolean` и `event`,
но не эти два домена. Это запрос из текущего обсуждения, без GitHub issue.

## What Changes

- Добавить выбор `input_button` и `scene` как `scenario_button` в существующем мастере.
- Передавать новые нажатия/активации как `button_event: click`, без выдуманного on/off.
- Объявлять для этих доменов только `click`; сохранять существующее поведение `event` и `input_boolean`.
- Проверить повторные активации, загрузку, недоступность и отсутствие повторов при перепубликации.
- Проверить интеграцию на целевой HA с отдельными тестовыми сущностями.
- Обратный запуск из Sber остаётся исследовательской проверкой: документация его не подтверждает.

## Capabilities

### New Capabilities

- `action-event-export`: экспорт нажатий helper и активаций сцен как событий Sber.

### Modified Capabilities

Нет.

## Impact

`sber_entity_map.py`, `devices/scenario_button.py`, мастер, документация и тесты.
Новые зависимости и изменения протокольных enum не нужны.

Источники проверены 2026-11-24 через Context7 и сайт:
- https://developers.sber.ru/docs/ru/smarthome/c2c/scenario_button
- https://developers.sber.ru/docs/ru/smarthome/c2c/button_event
- https://developers.sber.ru/docs/ru/smarthome/mqtt-integrators/devices-example
- https://www.home-assistant.io/integrations/input_button/
- https://www.home-assistant.io/integrations/scene/
