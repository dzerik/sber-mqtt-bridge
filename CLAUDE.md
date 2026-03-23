# Sber Smart Home MQTT Bridge — Project Rules

## Проект

**Sber Smart Home MQTT Bridge** — мост между Home Assistant и облаком Sber SmartHome через MQTT.
Реализован как HACS custom integration (`custom_components/sber_mqtt_bridge/`) и legacy addon (`mqtt_sber_gate/`).

- **Язык**: Python 3.13+ (тесты на 3.14)
- **Платформа**: Home Assistant (HACS custom component)
- **Транспорт**: MQTT через `aiomqtt` к Sber cloud broker (`mqtt-partners.iot.sberdevices.ru:8883`)
- **Версия**: `custom_components/sber_mqtt_bridge/manifest.json` (поле `"version"`)
- **Тесты**: `pytest` + `pytest-homeassistant-custom-component`, в `tests/hacs/`
- **Venv**: `uv venv .venv` → `source .venv/bin/activate`

## Структура проекта

```
custom_components/sber_mqtt_bridge/     # HACS integration (АКТИВНАЯ РАЗРАБОТКА)
  __init__.py          — HA lifecycle (async_setup_entry / async_unload_entry)
  config_flow.py       — Config Flow UI (Sber credentials) + Options Flow (entity selection)
  const.py             — DOMAIN, CONF_*, defaults
  sber_bridge.py       — Ядро: aiomqtt к Sber + HA event bus + command dispatch
  sber_protocol.py     — Sber JSON сериализация (devices list, states list)
  sber_entity_map.py   — Фабрики: HA domain → Sber entity class
  diagnostics.py       — HA diagnostics
  devices/             — 15 классов устройств (Sber protocol logic)
    base_entity.py     — BaseEntity (abstract base)
    light.py           — LightEntity (brightness, color, color_temp)
    climate.py         — ClimateEntity (HVAC)
    curtain.py         — CurtainEntity (cover)
    relay.py           — RelayEntity (switch, script, button)
    ...
    utils/
      color_converter.py   — HSV конвертация HA ↔ Sber
      linear_converter.py  — Линейное масштабирование значений
    on_off_entity.py   — OnOffEntity (base for relay, valve, socket)
    simple_sensor.py   — SimpleReadOnlySensor (base for 5 sensor types)
  strings.json         — UI строки (source of truth)
  translations/        — en.json, ru.json
  manifest.json        — HA manifest

tests/hacs/            — Тесты HACS integration
  test_config_flow.py  — Config Flow UI
  test_bridge.py       — SberBridge core
  test_sber_protocol.py — JSON serialization
  test_sber_entity_map.py — Entity factory mapping
```

## Архитектура HACS-интеграции

### Ключевые паттерны (HA 2025-2026)
- **`ConfigEntry.runtime_data`** — typed data (НЕ `hass.data[DOMAIN]`)
- **`OptionsFlowWithReload`** — auto-reload при смене настроек
- **`has_entity_name = True`** + `_attr_` pattern для entities
- **Service integration** — не создаёт entity platforms, выставляет чужие HA entity в Sber
- **aiomqtt** — async MQTT к внешнему Sber broker (НЕ HA built-in MQTT)
- **`async_track_state_change_event`** — подписка на HA state changes
- **`hass.services.async_call`** — выполнение Sber команд в HA

### Потоки данных
- **HA → Sber**: state_changed → fill_by_ha_state → to_sber_current_state → MQTT publish
- **Sber → HA**: MQTT message → process_cmd → hass.services.async_call

### 15 типов устройств

| HA Domain | Sber Category | Class |
|-----------|---------------|-------|
| light | light | LightEntity |
| cover | curtain / window_blind | CurtainEntity / WindowBlindEntity |
| switch / script / button | relay | RelayEntity |
| switch (outlet) | socket | SocketEntity |
| input_boolean | scenario_button | ScenarioButtonEntity |
| sensor (temperature) | sensor_temp | SensorTempEntity |
| sensor (humidity) | sensor_temp | HumiditySensorEntity |
| binary_sensor (motion) | sensor_pir | MotionSensorEntity |
| binary_sensor (door/window) | sensor_door | DoorSensorEntity |
| binary_sensor (moisture) | sensor_water_leak | WaterLeakSensorEntity |
| climate | hvac_ac | ClimateEntity |
| climate (radiator) | hvac_radiator | HvacRadiatorEntity |
| valve | valve | ValveEntity |
| humidifier | hvac_humidifier | HumidifierEntity |

## Docstrings (ОБЯЗАТЕЛЬНО!)

Все публичные элементы кода **ОБЯЗАНЫ** иметь docstrings:

- **Модули**: Описание назначения модуля в первой строке файла
- **Классы**: Описание назначения класса, Sber category, поддерживаемые features
- **Методы**: Google-style docstrings с `Args:`, `Returns:`, `Raises:`
- **Константы**: PEP 257 attribute docstrings (строка после присваивания)
- **Свойства (properties)**: Описание возвращаемого значения

Все файлы должны начинаться с `from __future__ import annotations`.

## Версионирование (ОБЯЗАТЕЛЬНО!)

### Формат версии
- Semantic Versioning: `MAJOR.MINOR.PATCH`
- **ЕДИНАЯ версия** во всех местах:
  - `custom_components/sber_mqtt_bridge/manifest.json` (поле `"version"`)
  - `custom_components/sber_mqtt_bridge/sber_protocol.py` (константа `VERSION`)
  - `pyproject.toml` (поле `version`)
  - `CHANGELOG.md` (запись для версии)

### Процесс при коммите
1. Определи уровень изменений (patch/minor/major)
2. Обнови **ВСЕ 4 места** с версией
3. Обнови `CHANGELOG.md` — добавь запись в `[Unreleased]` или создай новую секцию
4. Включи изменения версии в коммит

### CHANGELOG.md (ОБЯЗАТЕЛЬНО!)
- Формат: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
- Категории: `Added`, `Changed`, `Fixed`, `Removed`, `Deprecated`, `Security`
- Каждый релиз: дата + версия
- Секция `[Unreleased]` для текущей разработки
- Обновлять при **КАЖДОМ** значимом коммите

### Уровни версий
- **PATCH**: баг-фиксы, рефакторинг, мелкие улучшения
- **MINOR**: новая функциональность (backwards-compatible)
- **MAJOR**: breaking changes, крупные архитектурные изменения

## Git Workflow

### Branching
- Основная ветка: `main`
- Feature-ветки: `feat/<name>`, `fix/<name>`, `chore/<name>`, `refactor/<name>`

### Commit Messages
Формат: `тип: краткое описание`

Типы: `feat`, `fix`, `refactor`, `docs`, `chore`, `perf`, `test`

## Код

### Логирование
- `_LOGGER = logging.getLogger(__name__)` в каждом модуле

### Python
- Минимальная версия: Python 3.13
- Async/await для всего I/O

### Тесты
- Запуск: `source .venv/bin/activate && python -m pytest tests/hacs/ -v -o asyncio_mode=auto`
- Фреймворк: `pytest` + `pytest-homeassistant-custom-component`
- Coverage target: 95%+

### Линтинг
- `ruff check .` — linting
- `ruff format .` — formatting
- `mypy custom_components/sber_mqtt_bridge/` — type checking

## Quality Scale Target: Silver

См. `docs/HACS_SILVER_REQUIREMENTS.md` для полного чеклиста.
