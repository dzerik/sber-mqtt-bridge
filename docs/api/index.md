# API Reference

Автоматически сгенерированная документация из исходного кода Sber Smart Home MQTT Bridge.

## Архитектура

| Модуль | Назначение |
|--------|-----------|
| [SberBridge](bridge.md) | Ядро: MQTT-соединение, диспетчеризация команд, отслеживание состояний |
| [Протокол](protocol.md) | JSON-сериализация для Sber Smart Home API |
| [Модели](models.md) | Pydantic-модели протокола (валидация, схемы) |
| [Entity Map](entity-map.md) | Фабрики: маппинг HA domain -> Sber entity class |
| [Устройства](devices/index.md) | 15+ классов устройств Sber Smart Home |
| [Утилиты](utils.md) | Конвертеры цветов и значений |

## Потоки данных

- **HA -> Sber**: `state_changed` -> `fill_by_ha_state()` -> `to_sber_current_state()` -> MQTT publish
- **Sber -> HA**: MQTT message -> `process_cmd()` -> `hass.services.async_call()`
