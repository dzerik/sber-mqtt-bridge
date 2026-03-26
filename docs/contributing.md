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

### Использование типизированных констант

При реализации нового устройства **обязательно** используйте типизированные константы из `sber_constants.py`:

```python
from ..sber_constants import SberFeature, SberValueType, HAState

# Хорошо:
feature_key = SberFeature.ON_OFF
value_type = SberValueType.BOOL
state = HAState.ON

# Плохо (magic strings):
feature_key = "on_off"
value_type = "BOOL"
state = "on"
```

### Использование Pydantic-хелперов

Для формирования значений в протоколе Sber используйте хелперы из `sber_protocol.py`:

```python
from ..sber_protocol import make_bool_value, make_integer_value, make_enum_value, make_colour_value

# Булево значение:
value = make_bool_value(True)

# Целочисленное (integer_value всегда строка по спецификации Sber):
value = make_integer_value(220)  # → {"integer_value": "220"}

# Enum-значение:
value = make_enum_value("cooling")

# Цвет HSV:
value = make_colour_value(h=180, s=500, v=800)
```

### Шаги

1. Создайте новый класс в `custom_components/sber_mqtt_bridge/devices/`
2. Используйте `SberFeature`, `SberValueType` и Pydantic-хелперы вместо строк напрямую
3. Добавьте в фабрику в `sber_entity_map.py`
4. Напишите тесты в `tests/hacs/`
5. Используйте `_LOGGER = logging.getLogger(__name__)` для логирования
6. Сверьтесь с официальной документацией Sber C2C для выбранной категории (см. правило в `CLAUDE.md`)

## Формат коммитов

Формат: `тип: описание`

Типы: `feat`, `fix`, `refactor`, `docs`, `chore`, `perf`, `test`

## Лицензия

Участвуя в проекте, вы соглашаетесь с лицензией [MIT](https://github.com/dzerik/sber-mqtt-bridge/blob/main/LICENSE.txt).
