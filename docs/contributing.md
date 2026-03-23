# Участие в разработке

## Настройка среды разработки

```bash
git clone https://github.com/dzerik/sber-mqtt-bridge.git
cd sber-mqtt-bridge
uv venv .venv
source .venv/bin/activate
uv pip install aiomqtt pytest pytest-asyncio pytest-homeassistant-custom-component pytest-cov ruff mypy
```

## Запуск тестов

```bash
source .venv/bin/activate
pytest tests/hacs/ -v -o asyncio_mode=auto
```

С отчётом покрытия:

```bash
pytest tests/hacs/ -v -o asyncio_mode=auto --cov=custom_components/sber_mqtt_bridge --cov-report=term-missing
```

## Линтинг и форматирование

```bash
ruff check custom_components/
ruff format custom_components/
mypy custom_components/sber_mqtt_bridge/
```

## Добавление нового типа устройства

Выберите подходящий базовый класс:

### Устройства вкл/выкл (switch, valve, socket)

Наследуйтесь от `OnOffEntity`:

- Переопределите `process_cmd` для маппинга команд Sber на вызовы HA-сервисов
- Методы `fill_by_ha_state`, `create_features_list`, `to_sber_current_state`, `process_state_change` уже реализованы

### Датчики только для чтения (temperature, humidity, motion, door, leak)

Наследуйтесь от `SimpleReadOnlySensor`:

- Установите атрибуты класса `_sber_value_key` и `_sber_value_type`
- Реализуйте `_get_sber_value()` и `fill_by_ha_state()`
- Методы `create_features_list`, `to_sber_current_state`, `process_cmd`, `process_state_change` уже реализованы

### Сложные устройства (climate, light, curtain)

Наследуйтесь от `BaseEntity`:

- Реализуйте все абстрактные методы: `to_sber_current_state`, `process_cmd`

### Шаги

1. Создайте новый класс в `custom_components/sber_mqtt_bridge/devices/`
2. Добавьте в фабрику в `sber_entity_map.py`
3. Напишите тесты в `tests/hacs/`
4. Используйте `_LOGGER = logging.getLogger(__name__)` для логирования

## Формат коммитов

Формат: `тип: описание`

Типы: `feat`, `fix`, `refactor`, `docs`, `chore`, `perf`, `test`

## Лицензия

Участвуя в проекте, вы соглашаетесь с лицензией [MIT](https://github.com/dzerik/sber-mqtt-bridge/blob/main/LICENSE.txt).
