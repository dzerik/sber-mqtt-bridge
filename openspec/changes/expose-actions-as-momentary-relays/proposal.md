# Proposal

## Why

Живая проверка scenario_button подтвердила экспорт событий HA→Sber, но при
работе с карточками в приложении Сбера управляющие команды не приходят.
Пользователь выбрал путь relay для запуска input_button и scene из Сбера.

## What Changes

- Добавить явный выбор Relay для input_button и scene.
- Команда on вызывает press или scene.turn_on; off ничего не исполняет.
- В состоянии и ответе возвращать off как готовность к следующей активации,
  без искусственного состояния активности сцены.
- Объяснить в мастере два направления; сохранить текущий Auto для совместимости.
- Перевести две тестовые сущности в Relay, сохранив их имена/комнату.

## Capabilities

### New Capabilities

- `momentary-action-control`: запуск разовых HA действий через on/off интерфейс реле Sber.

### Modified Capabilities

Нет. Ранее реализованный action-event-export остаётся отдельным направлением.

## Impact

Адаптер Relay, карта доменов, command dispatcher/forwarder, пояснения мастера,
документация и поведенческие тесты. Зависимости и протокольные enum не меняются.
Источники проверены через Context7 и сайт Sber 2026-11-25:
https://developers.sber.ru/docs/ru/smarthome/c2c/relay
https://developers.sber.ru/docs/ru/smarthome/c2c/on-off

Импульсный адаптер — решение моста: документация Sber описывает обычное on/off реле.
