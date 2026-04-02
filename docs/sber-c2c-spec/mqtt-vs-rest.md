# MQTT vs REST API

Сравнение двух способов интеграции с Sber Smart Home: MQTT DIY протокол и C2C REST API (webhooks).

## Сводная таблица

| Параметр | MQTT DIY | C2C REST API (Webhooks) |
|----------|----------|------------------------|
| **Модель** | Pub/Sub (асинхронная) | Request/Response (синхронная) |
| **Инициация** | Агент подключается к брокеру | Облако вызывает webhook вендора |
| **Аутентификация** | Username/Password (MQTT) | Bearer Token (HTTP) |
| **Endpoint** | `mqtts://mqtt-partners.iot.sberdevices.ru:8883` | `https://partners.iot.sberdevices.ru/v1/...` |
| **TLS** | MQTT over TLS (порт 8883) | HTTPS |
| **Регистрация устройств** | `up/config` (publish) | `POST /v1/devices` |
| **Регистрация моделей** | inline `model` в device | `POST /v1/models` |
| **Отправка состояния** | `up/status` (publish) | Webhook `POST /query` (response) |
| **Получение команд** | `down/commands` (subscribe) | Webhook `POST /command` (request) |
| **Запрос состояния** | `down/status_request` (subscribe) | `GET /v1/state` |
| **Гарантии доставки** | MQTT QoS | HTTP status codes |

## Ключевые различия payload

### Регистрация устройств

**MQTT (`up/config`):** устройство с inline `model` или `model_id`:

```json
{
    "devices": [
        {
            "id": "temp1",
            "name": "temp1",
            "default_name": "temp1",
            "model_id": "my_temp_sensor"
        }
    ]
}
```

**REST (`POST /v1/devices`):** аналогичная структура, но модели регистрируются отдельно через `POST /v1/models`.

### Состояние устройств

**MQTT (`up/status`):** словарь `device_id → {states}`:

```json
{
    "devices": {
        "temp1": {
            "states": [
                {"key": "temperature", "value": {"type": "INTEGER", "integer_value": "256"}}
            ]
        }
    }
}
```

**REST (`GET /v1/state` response):** идентичная структура.

### integer_value

| Контекст | Тип | Пример |
|----------|-----|--------|
| C2C REST API (docs) | **string** | `"integer_value": "220"` |
| MQTT DIY (agent-connect example) | number | `"integer_value": 256` |

!!! warning "Расхождение в документации"
    В C2C спецификации `integer_value` определён как **string** (`long, записанное в виде строки`).
    В примерах MQTT DIY (`agent-connect`) встречается числовой вариант.
    Сбер, вероятно, принимает оба формата, но C2C API формально требует строку.

## Когда использовать какой протокол

| Сценарий | Рекомендация |
|----------|-------------|
| DIY интеграция (Home Assistant, локальный контроллер) | **MQTT** — проще в настройке, не требует публичного endpoint |
| Коммерческий продукт (облако вендора) | **REST API** — стандартный webhook-based подход |
| Интеграторы (Wiren Board, zigbee2mqtt) | **MQTT** — нативная поддержка через mqtt-integrators |

## REST API Endpoints

| Метод | Endpoint | Описание |
|-------|----------|----------|
| POST | `/v1/devices` | Добавить устройства пользователя |
| GET | `/v1/devices` | Получить список устройств |
| PUT | `/v1/devices` | Обновить устройства |
| DELETE | `/v1/devices` | Удалить устройства |
| POST | `/v1/models` | Добавить модели устройств |
| PUT | `/v1/models` | Обновить модели |
| GET | `/v1/state` | Получить состояние устройств |

## Webhook Endpoints (реализуемые вендором)

| Метод | Endpoint | Описание |
|-------|----------|----------|
| POST | `/v1/devices` | Облако запрашивает список устройств |
| POST | `/query` | Облако запрашивает состояние устройств |
| POST | `/command` | Облако отправляет команду на устройство |
