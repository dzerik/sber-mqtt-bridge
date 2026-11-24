# Tasks

## 1. Импульсный адаптер

- [x] 1.1 Добавить unit-tests on/on/off, proto3 false, unknown/offline и безопасного echo; подтвердить RED и реализовать GREEN.
- [x] 1.2 Проверить настоящий dispatcher→HA services→MQTT, исключить ложное ожидание on в DevTools и проверить удаление состояния.

## 2. Выбор направления

- [x] 2.1 Проверить Relay в мастере для обоих доменов без HA device, сохранение metadata/full config при override.
- [x] 2.2 Обновить подсказки ru/en и README/configuration/CHANGELOG с импульсным контрактом и явным выбором Relay.

## 3. Проверка и стенд

- [x] 3.1 Выполнить полный pytest+coverage, ruff/format, mypy, codegen, strict OpenSpec и независимое ревью.
- [x] 3.2 Поднять beta штатным скриптом, развернуть на тестовой установке с файловым откатом и SHA256, проверить готовность.
- [x] 3.3 Перевести две тестовые сущности в Relay, проверить модели/команды/off и сохранить текущие имена/комнату.

## Workflow follow-up

- Настоящие команды пользователя из Sber подтверждены: 2026-11-25 00:54:41 scene on, 00:55:32 input_button on, 00:55:33 input_button off (MSK). Проверены direction=in, HA services/timestamps и исходящий off; см. verification.md. Архивирование отдельно.
