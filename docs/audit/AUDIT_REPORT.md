# Аудит кодовой базы — Sber Smart Home MQTT Bridge

**Дата**: 2026-03-23 (аудит v3 — глубокий)
**Версия**: 0.2.0
**Аудитор**: Claude Code (4 параллельных ревьюера)
**Код**: `custom_components/sber_mqtt_bridge/`
**Тесты**: `tests/hacs/`
**Метод**: jscpd (дублирование) + 4 специализированных code review агента

---

## Резюме

| Категория | Оценка | Critical | High | Medium |
|-----------|--------|----------|------|--------|
| Бизнес-логика ядра | **D** | 3 | 4 | 4 |
| Device-классы | **D** | 4 | 7 | 3 |
| HA Integration lifecycle | **D** | 1 | 4 | 4 |
| Документация | **C** | 2 | 4 | 6 |
| Дублирование кода | **B** | 0 | 0 | 9 клонов (3.4%) |
| **ОБЩАЯ** | **D+** | **10** | **19** | **26** |

---

## CRITICAL (10 находок)

### C1. `ConfigEntryNotReady` — мёртвый код
**Файлы:** `__init__.py:48-52`, `sber_bridge.py:86-90`
**Confidence:** 95

`async_start()` запускает MQTT как фоновый `asyncio.Task` и возвращает управление немедленно. `try/except ConfigEntryNotReady` в `async_setup_entry` никогда не сработает. Интеграция всегда показывает "загружена", даже если брокер недоступен.

**Статус:** OPEN

---

### C2. Race condition: `_mqtt_client` вне context manager
**Файл:** `sber_bridge.py:229-230, 353, 357`
**Confidence:** 90

Между exit `async with aiomqtt.Client` и установкой `_connected = False` задачи из очереди могут пройти guard `if not self._connected`, но клиент уже закрыт. `MqttError` ловится, но guard ненадёжен.

**Статус:** OPEN (P2)

---

### C3. Entities с `device_id` не попадают в Sber
**Файлы:** `base_entity.py:176`, `sber_bridge.py:140`
**Confidence:** 95

`_load_exposed_entities()` никогда не вызывает `entity.link_device()`. Для entities с `device_id != None` метод `to_sber_state()` бросает `RuntimeError`. Перехватывается `try/except` в `build_devices_list_json`, но entity молча пропускается. Подавляющее большинство реальных HA entities имеют `device_id`.

**Статус: **FIXED** — добавлен link_device в _load_exposed_entities

---

### C4. `curtain.py:152` — `elif open_set` пропускает команду
**Файл:** `curtain.py:114-152`
**Confidence:** 100

`open_percentage` использует `if`, `cover_position` тоже `if`, но `open_set` использует `elif` от `cover_position`. Если Sber отправит `cover_position` и `open_set` в одном пакете — `open_set` молча игнорируется.

**Статус: **FIXED** — объединён дубль open_percentage/cover_position, elif→if

---

### C5. `curtain.py:231-233` — возвращает `None` вместо `dict`
**Файл:** `curtain.py:231-233`
**Confidence:** 100

При `state == "unavailable"` строит `states` список, добавляет `online=False`, затем возвращает `None`. Контракт `BaseEntity` требует `dict`. Вызывающий код упадёт с `TypeError`.

**Статус: **FIXED** — возвращает dict с online=False вместо None

---

### C6. `light.py:250-253` — `int(None)` crash
**Файл:** `light.py:250-253`
**Confidence:** 100

```python
sber_color_temp = int(cmd_value.get("integer_value", 0))
if sber_color_temp is None:   # unreachable после int()
```

Если `integer_value` = `None`, `int(None)` бросает `TypeError`. Guard после `int()` — unreachable dead code.

**Статус: **FIXED** — int(value or 0), убран dead code

---

### C7. `light.py:153` — несовпадение ключа state
**Файл:** `light.py:153` vs `light.py:83,99,249`
**Confidence:** 95

`to_sber_current_state` публикует `"colour_temperature"`, но `create_features_list` регистрирует `"light_colour_temp"`, `process_cmd` обрабатывает `"light_colour_temp"`. Sber не может связать state с feature.

**Статус: **FIXED** — colour_temperature→light_colour_temp

---

### C8. `CHANGELOG.md:86` — хронология версий нарушена
**Файл:** `CHANGELOG.md:86-118`
**Confidence:** 100

Legacy addon 1.x после HACS 0.x нарушает Keep a Changelog newest-first.

**Статус:** OPEN

---

### C9. `CHANGELOG.md:45-83` — дубликаты fixes
**Файл:** `CHANGELOG.md:45-83`
**Confidence:** 100

[0.1.0] и [0.2.0] имеют одинаковую дату и дублируют списки Fixed.

**Статус:** OPEN

---

### C10. `docs/audit/audit-02-architecture.md` — чужой проект
**Файл:** `docs/audit/audit-02-architecture.md`
**Confidence:** 100

Весь файл описывает `xiaomi_miio_airpurifier_ng`, не `sber_mqtt_bridge`. Содержит ссылки на `fans/*.py`, `FanMiot`, `Fan1C` и grep-команды для чужого пути.

**Статус: **FIXED** — файл удалён

---

## HIGH (19 находок)

### H1. Потеря state events до первого MQTT connect
**Файл:** `sber_bridge.py:86-90, 163-175`

HA events подписываются только после успешного MQTT connect. Все state changes до этого теряются.

### H2. `_redefinitions` — key mismatch device_id/entity_id
**Файл:** `sber_bridge.py:290-317`

Ключи `device_id` из Sber совпадают с `entity_id` случайно (потому что `to_sber_state` публикует `entity_id` как `id`).

### H3. `_redefinitions` — memory leak + потеря при reload
**Файл:** `sber_bridge.py:71, 299, 315`

Не персистируется, теряется при каждом OptionsFlow reload.

### H4. Оптимистичная мутация state в `process_cmd`
**Файлы:** `climate.py`, `humidifier.py`, `relay.py`, `valve.py`

State мутируется до выполнения HA service call (`blocking=False`). При ошибке — расхождение.

### H5. `logger` vs `_LOGGER` convention
**Файлы:** Все `devices/*.py`

CLAUDE.md требует `_LOGGER`, все device-файлы используют `logger`.

### H6. `ssl.create_default_context()` блокирует event loop
**Файл:** `config_flow.py:87-88`

Синхронное I/O в async-контексте при валидации credentials.

### H7. Reauth не показывает аккаунт
**Файл:** `config_flow.py:149-155`

Пользователь не знает, для какого логина вводит пароль.

### H8. `_load_exposed_entities()` при startup до полной инициализации
**Файл:** `sber_bridge.py:89, 117`

Нет подписки на `EVENT_HOMEASSISTANT_STARTED` для повторной загрузки.

### H9. Diagnostics выставляет приватные атрибуты raw
**Файл:** `diagnostics.py:26-29`

`_entities`, `_redefinitions` — мутабельные ссылки без redaction.

### H10. `light.py:197` — brightness min=50 в HA-пространстве
**Файл:** `light.py:197`

`max(50, ...)` — Sber minimum применяется к HA значению. Dim-to-off заблокирован.

### H11. `humidifier.py:107` — humidity ×10 вероятно ошибка
**Файл:** `humidifier.py:107`

HA humidity = integer 0-100. `*10` отправляет 550 для 55%. Temperature ×10 обоснован (дробные), humidity — нет.

### H12. Прямой вызов `BaseEntity.__init__` минуя parent
**Файлы:** `socket_entity.py:32`, `window_blind.py:32`, `hvac_radiator.py:33`

Новые атрибуты parent `__init__` не инициализируются.

### H13. `curtain.py:247` — ENUM `"close"` вместо `"closed"`
**Файл:** `curtain.py:247`

**Статус:** **FIXED** — close→closed

Sber стандарт: `open/closed`, не `open/close`.

### H14. `scenario_button.py:42-43` — spurious `double_click`
**Файл:** `scenario_button.py:42-43`

**Статус:** **FIXED** — guard для unavailable/unknown

`unavailable`/`unknown` маппятся на `"double_click"` вместо игнорирования.

### H15. `climate.py:170` — hardcoded 22°C fallback
**Файл:** `climate.py:170`

**Статус:** **FIXED** — continue при отсутствии integer_value

`value.get("integer_value", 220)` — при отсутствии значения термостат сбрасывается на 22°C.

### H16. `light.py:1` — missing `from __future__ import annotations`
**Файл:** `light.py:1`

**Статус:** **FIXED** — добавлен from __future__ import annotations

Единственный device-файл без этого импорта, нарушает CLAUDE.md.

### H17. CLAUDE.md — не упоминает `on_off_entity.py`, `simple_sensor.py`
**Файл:** `CLAUDE.md`, секция "Структура проекта"

### H18. CONTRIBUTING.md — устаревшие инструкции
**Файл:** `CONTRIBUTING.md:30`

"Inherit from BaseEntity" и список abstract methods не учитывает `OnOffEntity`/`SimpleReadOnlySensor`.

### H19. HACS_SILVER_REQUIREMENTS.md — противоречия
**Файл:** `docs/HACS_SILVER_REQUIREMENTS.md`

Чеклист говорит "todo", `quality_scale.yaml` говорит "done".

---

## MEDIUM (26 находок)

| # | Файл | Проблема |
|---|------|----------|
| M1 | `sber_protocol.py:137` | `_LOGGER.exception` для ожидаемого `JSONDecodeError` |
| M2 | `sber_bridge.py:253` | Нет лимита размера MQTT payload |
| M3 | `sber_protocol.py:120` | `root` online=True безусловно |
| M4 | `sber_bridge.py:353` | Неограниченные `async_create_task` при burst |
| M5 | `manifest.json` | `quality_scale` поле отсутствует |
| M6 | `const.py:22` | `CONF_SBER_HTTP_ENDPOINT` dead code |
| M7 | `sber_bridge.py:163-175` | Race window в `_subscribe_ha_events()` |
| M8 | `climate.py:107-110` | `create_features_list()` вызывается дважды |
| M9 | `curtain.py:204` | In-place `+=` мутация vs `[*super(), ...]` |
| M10 | `hvac_radiator.py:33-44` | Полное дублирование `ClimateEntity.__init__` |
| M11 | `curtain.py:117-130, 139-152` | Внутреннее дублирование `set_cover_position` |
| M12 | `humidifier.py:152` | `self.mode = mode` без `if mode is not None` |
| M13 | `README.md:5` | Hardcoded badge "219 tests" |
| M14 | `quality_scale.yaml:50` | 3 разных coverage target (80/82/95%) |
| M15 | `manifest.json:7` | documentation URL на корень репо |
| M16 | `CONTRIBUTING.md:20` | `mypy` не упомянут в Linting |
| M17 | `HACS_SILVER_REQUIREMENTS.md:128` | Community files "нужно создать" — все уже существуют |
| M18-M26 | Разные | 9 jscpd клонов (3.4% дублирования) |

---

## Delta vs предыдущий аудит (v0.2.0 → v0.3.0)

| Проблема | Предыдущий | Текущий | Статус |
|----------|-----------|---------|--------|
| SEC-01..SEC-09 | Fixed | Fixed | FIXED |
| ARCH-01..ARCH-15 | Fixed | Fixed | FIXED |
| TEST-01: Coverage 55% | Fixed (82%) | 82% | FIXED |
| DOC-01..DOC-03 | Fixed | Fixed | FIXED |
| DUP: process_state_change 6x | — | Вынесен в BaseEntity | **NEW+FIXED** |
| DUP: is_online 5x | — | `_is_online` property в BaseEntity | **NEW+FIXED** |
| DUP: type_key_map | — | Class-level `_TYPE_KEY_MAP` | **NEW+FIXED** |
| C1: ConfigEntryNotReady dead | — | — | **NEW** |
| C2: Race _mqtt_client | — | — | **NEW** |
| C3: link_device not called | — | — | **NEW** |
| C4-C7: Device bugs | — | — | **NEW** |
| H1-H19: High issues | — | — | **NEW** |

---

## Скоринг

| Метрика | v0.2.0 | v0.3.0 (текущий) |
|---------|--------|------------------|
| Security Score | 95/100 | 78/100 |
| Technical Debt Index | 4.8 | 12.5 |
| Test Coverage | 82% | 82% |
| Critical Issues | 0 | **10** |
| High Issues | 0 | **19** |
| Duplication | 4.34% | 3.38% (после fix) |

### Security Score breakdown (78/100)

| Проверка | Вес | Балл | Примечание |
|----------|-----|------|------------|
| Нет hardcoded secrets | 20 | **20** | |
| Input validation | 15 | **10** | C6, M2 |
| Error handling | 15 | **8** | C1, C5, H4 |
| Race conditions | 15 | **8** | C2, M7 |
| Config flow validation | 10 | **8** | H6, H7 |
| Dependencies pinned | 10 | **10** | |
| .gitignore | 5 | **5** | |
| Entity mapping | 10 | **9** | C3 |

---

## Приоритеты исправления

### P0 — Немедленно (блокируют работу)
1. C3: `link_device` не вызывается
2. C5: `curtain.to_sber_current_state` возвращает `None`
3. C6: `int(None)` в light
4. C7: key mismatch в light

### P1 — Важно (функциональные баги)
5. C4: curtain `elif open_set`
6. H11: humidity ×10
7. H13: "close" vs "closed"
8. H14: spurious double_click
9. H15: hardcoded 22°C
10. H16: missing future annotations

### P2 — Архитектура
11. C1: ConfigEntryNotReady
12. C2: Race _mqtt_client
13. H1: State events до connect
14. H4: Оптимистичная мутация
15. H8: startup ordering
16. H12: init chain bypass

### P3 — Документация
17. C8-C10: CHANGELOG, audit file
18. H5: logger naming
19. H17-H19: CLAUDE.md, CONTRIBUTING, HACS requirements
