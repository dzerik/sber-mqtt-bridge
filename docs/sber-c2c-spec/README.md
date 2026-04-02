# Sber C2C Protocol Specification (Ground Truth)

> **Назначение:** эталонная спецификация Sber Smart Home C2C протокола, основанная **исключительно** на официальной документации Sber.
> Используется как ground truth для валидации тестов и проверки соответствия реализации.

!!! warning "Это НЕ описание текущей реализации"
    Данная спецификация описывает **ожидаемое** поведение по документации Sber,
    а не фактическое поведение нашего кода. Расхождения фиксируются в [Validation Rules](validation-rules.md).

## Источники данных

| Источник | URL |
|----------|-----|
| Устройства | <https://developers.sber.ru/docs/ru/smarthome/c2c/devices> |
| Функции | <https://developers.sber.ru/docs/ru/smarthome/c2c/functions> |
| Структуры | <https://developers.sber.ru/docs/ru/smarthome/c2c/structures> |
| MQTT Topics | <https://developers.sber.ru/docs/ru/smarthome/reference/mqtt-topics> |
| MQTT DIY | <https://developers.sber.ru/docs/ru/smarthome/mqtt-diy/agent-connect> |
| C2C API | <https://developers.sber.ru/docs/ru/smarthome/c2c/api> |
| Webhooks | <https://developers.sber.ru/docs/ru/smarthome/c2c/webhook> |

## Содержание

| Документ | Описание |
|----------|----------|
| [Data Structures](data-structures.md) | Device, Model, State, Value, allowed_values, dependencies |
| [MQTT Topics](mqtt-topics.md) | 5 MQTT топиков: payload schemas, sequence diagrams |
| [Device Categories](device-categories.md) | 28 категорий устройств с features и JSON-примерами |
| [Features](features.md) | 75+ функций: типы, значения, диапазоны |
| [MQTT vs REST](mqtt-vs-rest.md) | Различия между MQTT DIY и C2C REST API |
| [Validation Rules](validation-rules.md) | Пронумерованные инварианты для тестов |

## Как использовать

### Для написания тестов

1. Найдите нужную категорию устройства в [Device Categories](device-categories.md)
2. Посмотрите required/optional features и их типы
3. Используйте JSON-примеры как ожидаемые значения в assertions
4. Сверьтесь с [Validation Rules](validation-rules.md) для edge cases

### Для проверки реализации

1. Сравните ваш output с примерами в [Data Structures](data-structures.md)
2. Проверьте типы value (особенно `integer_value` как **string**)
3. Убедитесь, что dependencies корректно ограничивают features

## Дата синхронизации

Последняя сверка с документацией Sber: **2026-04-02**
