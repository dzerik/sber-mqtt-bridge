# Аудит кодовой базы — Sber Smart Home MQTT Bridge

**Дата**: 2026-03-23
**Версия**: 0.1.0
**Аудитор**: Claude Code (автоматизированный аудит)
**Код**: `custom_components/sber_mqtt_bridge/`
**Тесты**: `tests/hacs/`

---

## Резюме

| Категория | Оценка | Критических | Важных | Мелких |
|-----------|--------|-------------|--------|--------|
| Безопасность | **C** | 2 | 3 | 4 |
| Архитектура | **B** | 3 | 5 | 8 |
| Тесты и Coverage | **D** | 0 | 2 | 1 |
| Документация | **D** | 0 | 3 | 2 |
| Code Quality (ruff) | **B** | 0 | 0 | 24 |
| Type Safety (mypy) | **F** | 0 | 131 | 0 |
| **ОБЩАЯ** | **C** | **5** | **144** | **39** |

---

## Инструментальный аудит

### Ruff Lint: 24 ошибки

```
RUF005 ×10  list concatenation → use unpacking [*super()..., "item"]
TRY300 ×2   statement in try block should be in else
RUF012 ×2   mutable default class attribute (dict = {})
SIM108 ×1   nested if/else → ternary
SIM105 ×1   try/except/pass → contextlib.suppress
SIM103 ×1   return condition directly
SIM102 ×1   nested if → combined with and
S105   ×1   possible hardcoded password (false positive: CONF_SBER_PASSWORD = "sber_password")
RUF040 ×1   non-string assert message
G004   ×1   f-string in logging
F401   ×1   unused import (DOMAIN)
E711   ×1   comparison to None (== None → is None)
BLE001 ×1   blind except Exception
```

**Вердикт**: Только стилистические замечания. Нет блокирующих проблем. Оценка: **B**

### Mypy Type Check: 131 ошибка в 20 файлах

| Категория | Кол-во | Пример |
|-----------|--------|--------|
| `no-untyped-def` | ~80 | Все device-классы без type annotations |
| `assignment` (type mismatch) | ~30 | `BaseEntity` class-level annotations vs runtime |
| `attr-defined` / `index` | ~10 | `DeviceData` используется как dict, но аннотирован как класс |
| `no-any-return` | 2 | `parse_sber_command`, `parse_sber_status_request` |

**Вердикт**: Device-классы скопированы из legacy addon без type annotations. Нужен полный проход по типизации. Оценка: **F**

### Codespell: 6 false positives

Все 6 — `hass` → `hash` (false positive, `hass` — стандартное HA имя переменной).
Нужно добавить `hass` в `codespell` ignore list.

### Test Coverage: 54.94% (target: 80%, Silver: 95%)

| Модуль | Coverage | Статус |
|--------|----------|--------|
| `const.py` | 100% | OK |
| `sber_entity_map.py` | 100% | OK |
| `hvac_radiator.py` | 100% | OK |
| `socket_entity.py` | 100% | OK |
| `window_blind.py` | 100% | OK |
| `relay.py` | 94% | OK |
| `sber_protocol.py` | 87% | Needs work |
| `__init__.py` | 84% | Needs work |
| `sensor_temp.py` | 79% | Needs work |
| `base_entity.py` | 71% | Gap |
| `config_flow.py` | 62% | Gap |
| `door/motion/water_leak` | 62% | Gap |
| `scenario_button.py` | 57% | Gap |
| `sber_bridge.py` | 55% | **Major gap** |
| `humidity_sensor.py` | 54% | Gap |
| `valve.py` | 45% | **Major gap** |
| `curtain.py` | 31% | **Major gap** |
| `humidifier.py` | 30% | **Major gap** |
| `light.py` | 27% | **Critical** |
| `climate.py` | 26% | **Critical** |
| `color_converter.py` | 26% | **Critical** |
| `device_data.py` | 9% | **Critical** |
| `diagnostics.py` | 0% | **Not tested** |

**Итого**: 1165 statements, 525 missed, **55% coverage**. Оценка: **D**

---

## Скоринг

| Метрика | Значение | Оценка |
|---------|----------|--------|
| Security Score | 65/100 | **C** |
| Technical Debt Index | 18.2 | HIGH |
| Test Coverage | 55% | **D** |
| HA Quality Scale | Bronze done, Silver partial | **Bronze** |
| Ruff Issues | 24 (стиль) | **B** |
| Mypy Issues | 131 | **F** |

### Security Score (65/100)

| Проверка | Вес | Балл | Заметки |
|----------|-----|------|---------|
| Нет hardcoded secrets | 20 | **20** | OK |
| Input validation | 15 | **8** | `parse_sber_command` без try/except |
| Error handling | 15 | **10** | Payload логируется на INFO |
| Race conditions | 15 | **10** | Shared mutable state без lock |
| Config flow validation | 10 | **10** | OK |
| Dependencies pinned | 10 | **5** | `>=2.0` не pinned |
| .gitignore | 5 | **2** | Нет .env, *.pem |
| Entity mapping | 10 | **0** | TLS disabled (CERT_NONE) |

---

## Детальные находки

### 1. Безопасность

#### КРИТИЧЕСКИЕ

**SEC-01: TLS Certificate Verification Disabled**
- **Файлы**: `config_flow.py:57-58`, `sber_bridge.py` (`_mqtt_connection_loop`)
- `ssl.CERT_NONE` + `check_hostname = False` — MITM атака может перехватить credentials
- **Fix**: Удалить обе строки. `ssl.create_default_context()` уже проверяет сертификаты

**SEC-02: Unhandled JSON Parse in Command Handler**
- **Файл**: `sber_protocol.py:130`
- `parse_sber_command` — нет try/except вокруг `json.loads`. Malformed payload крашит MQTT loop
- **Fix**: Обернуть в try/except как в `parse_sber_status_request`

#### ВАЖНЫЕ

**SEC-03: Unsanitized MQTT Values → HA Service Calls**
- **Файл**: `climate.py:93-148` — enum values из MQTT передаются в `set_fan_mode` без валидации
- **Fix**: Валидировать enum'ы по allowed values

**SEC-04: Assert для runtime validation**
- **Файл**: `base_entity.py:96,100,123` — assert stripped при `python -O`
- **Fix**: Заменить на `if not ...: raise ValueError(...)`

**SEC-05: Full Command Payload в INFO лог**
- **Файл**: `sber_bridge.py:239` — credentials-adjacent data в логе по умолчанию
- **Fix**: Изменить на DEBUG

#### МЕЛКИЕ

- SEC-06: `.gitignore` не покрывает `.env*`, `*.pem`, `secrets.yaml`
- SEC-07: `aiomqtt>=2.0` не pinned (нет upper bound)
- SEC-08: Нет exponential backoff при reconnect (фиксированные 5s)
- SEC-09: Shared mutable state (`_entities`, `_redefinitions`) без asyncio.Lock

---

### 2. Архитектура

#### КРИТИЧЕСКИЕ

**ARCH-01: Shared mutable class-level state в LightEntity**
- **Файл**: `light.py:21-23` — `brightness_converter` и `color_temp_converter` — class-level
- Все инстансы LightEntity делят одни конвертеры. Мутация в `__init__` влияет на все
- **Fix**: Перенести в `__init__`

**ARCH-02: `attributes: dict = {}` на уровне класса**
- **Файл**: `base_entity.py:43` — Shared mutable default
- **Fix**: Инициализировать в `__init__`

**ARCH-03: Deprecated entity registry access**
- **Файл**: `sber_bridge.py:110`
- `self._hass.helpers.entity_registry.async_get(self._hass)` — deprecated
- **Fix**: `from homeassistant.helpers import entity_registry as er; er.async_get(hass)`

#### ВАЖНЫЕ

- ARCH-04: `DeviceData`/`linked_device` — dead code (никогда не вызывается в HACS integration)
- ARCH-05: `get_entity_domain()` использует `self.id` вместо `self.entity_id`
- ARCH-06: `process_cmd` возвращает `None` в LightEntity (строка 205), но caller ожидает `[]`
- ARCH-07: `build_devices_list_json` фильтрует falsy values (`if v`) — удалит `0`, `False`
- ARCH-08: Нет `async_step_reauth` в config_flow (Silver requirement)

#### МЕЛКИЕ

- ARCH-09: `HUMIDITY_SENSOR_CATEGORY = "sensor_temp"` — возможно неверно (Sber объединяет)
- ARCH-10: `callable` вместо `Callable` в type hint (`sber_entity_map.py:68`)
- ARCH-11: `assert self.linked_device is not None, True` — `True` как message
- ARCH-12: `BaseEntity` не наследует `ABC`, `to_sber_current_state` и `process_state_change` не `@abstractmethod`
- ARCH-13: Typo `unuque_id` в `device_data.py`
- ARCH-14: Stale comment `# devices/base.py` в `base_entity.py`
- ARCH-15: Missing `from __future__ import annotations` в device файлах
- ARCH-16: Mixed language (RU/EN) в device классах

---

### 3. Тесты и Runtime

#### ВАЖНЫЕ

**TEST-01: Coverage 55% — ниже минимума 80%**
- Не тестированы: `light.py` (27%), `climate.py` (26%), `curtain.py` (31%), `sber_bridge.py` (55%)
- Не тестирован вообще: `diagnostics.py` (0%)

**TEST-02: Edge cases не покрыты**
- Empty MQTT payloads, invalid JSON, None states, MQTT disconnect during publish
- `hass.services.async_call` exceptions, reconnect loop, options flow

#### МЕЛКИЕ

- TEST-03: Device-классы тестируются только через entity_map (конструктор), не через `fill_by_ha_state`/`process_cmd`

---

### 4. Документация

#### ВАЖНЫЕ

**DOC-01: README.md устарел** — описывает legacy addon, не HACS integration
**DOC-02: CHANGELOG.md отсутствует** — требуется для HACS Silver
**DOC-03: Нет документации по конфигурации** — Silver requirement

#### МЕЛКИЕ

- DOC-04: `quality_scale.yaml` — `diagnostics: done` но coverage 0%
- DOC-05: CLAUDE.md — `Python 3.13+` но фактически 3.14

---

## HA Quality Scale Status

### Bronze: **ДОСТИГНУТ** (18/18)

| Правило | Статус |
|---------|--------|
| config-flow | PASS |
| config-flow-test-coverage | PASS |
| runtime-data | PASS |
| entity-event-setup | PASS |
| test-before-configure | PASS |
| test-before-setup | PASS |
| unique-config-entry | PASS |
| dependency-transparency | PASS |
| common-modules | PASS |
| Остальные (exempt) | PASS |

### Silver: **НЕ ДОСТИГНУТ** (5/10)

| Правило | Статус | Блокер |
|---------|--------|--------|
| config-entry-unloading | PASS | |
| integration-owner | PASS | |
| log-when-unavailable | PASS | |
| reauthentication-flow | **FAIL** | Не реализован |
| test-coverage | **FAIL** | 55% < 95% |
| docs-configuration-parameters | **FAIL** | README устарел |
| docs-installation-parameters | **FAIL** | README устарел |
| Остальные (exempt) | PASS | |

---

## HACS Publishing Readiness

| Требование | Статус |
|------------|--------|
| manifest.json | PASS |
| hacs.json | PASS |
| config_flow.py | PASS |
| strings.json + translations | PASS |
| GitHub Actions (hassfest) | PASS |
| GitHub Actions (HACS) | PASS |
| Brand assets (icon.png) | **FAIL** |
| GitHub Release | **FAIL** |
| README (description) | **FAIL** |

---

## TOP-10 проблем по приоритету

| # | Проблема | Severity | Effort |
|---|----------|----------|--------|
| 1 | TLS CERT_NONE (SEC-01) | Critical | 5 min |
| 2 | JSON parse без try/except (SEC-02) | Critical | 5 min |
| 3 | Shared class-level state в LightEntity (ARCH-01) | Critical | 15 min |
| 4 | Deprecated entity_registry API (ARCH-03) | Critical | 5 min |
| 5 | Coverage 55% → 80% (TEST-01) | Important | 3-4 hr |
| 6 | README перезапись (DOC-01) | Important | 1 hr |
| 7 | Reauth flow (ARCH-08) | Important | 1 hr |
| 8 | 131 mypy error (typing) | Important | 3-4 hr |
| 9 | process_cmd None return (ARCH-06) | Important | 10 min |
| 10 | Falsy filter в build_devices_list (ARCH-07) | Important | 10 min |

---

## План действий

### Немедленно (критические баги, < 1 час)

1. Убрать `ssl.CERT_NONE` и `check_hostname = False`
2. Добавить try/except в `parse_sber_command`
3. Перенести converters из class-level в `__init__` (LightEntity)
4. Исправить `self._hass.helpers.entity_registry` → `er.async_get(hass)`
5. Исправить `process_cmd` return `None` → `[]`
6. Исправить falsy filter (`if v` → убрать или `if v is not None`)
7. Перенести `attributes: dict = {}` в `__init__` (BaseEntity)

### В течение спринта (Silver blockers)

8. Написать тесты для device-классов (light, climate, curtain) → coverage 80%+
9. Реализовать `async_step_reauth` в config_flow
10. Переписать README.md под HACS integration
11. Создать CHANGELOG.md
12. Создать brand/icon.png

### Плановый рефакторинг (quality improvement)

13. Type annotations для всех device-классов (131 mypy errors)
14. Исправить все 24 ruff замечания
15. Удалить dead code (DeviceData/linked_device в HACS integration)
16. Добавить `@abstractmethod` на `to_sber_current_state`, `process_state_change`
17. Exponential backoff для MQTT reconnect
18. asyncio.Lock для entity reload
19. Добавить `from __future__ import annotations` во все файлы
20. Достичь 95% coverage (Silver target)

---

## ФИНАЛЬНАЯ ОЦЕНКА

| Метрика | Значение |
|---------|----------|
| **Общая оценка** | **C** |
| **HACS Ready** | Нет (нет icon, release, README) |
| **HA Quality Scale** | Bronze (Silver — 3 блокера) |
| **Security Risk** | Medium (TLS disabled) |
| **Technical Debt** | HIGH (TDI 18.2) |
| **Refactor Required** | Да (critical bugs + typing) |
