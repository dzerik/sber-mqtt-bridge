# ПОЛНЫЙ АУДИТ КОДОВОЙ БАЗЫ — Sber Smart Home MQTT Bridge

Проведи **полный аудит кодовой базы проекта**. Ни один шаг не пропускать.

**Проект**: Sber Smart Home MQTT Bridge — Home Assistant custom integration (HACS)
**Язык**: Python 3.13+, aiomqtt (MQTT to Sber cloud)
**Код**: `custom_components/sber_mqtt_bridge/`
**Тесты**: `tests/hacs/`

---

## РЕЖИМ РАБОТЫ

- Работай **полностью автономно**. Не задавай вопросов — решай сам.
- Все проверки выполнять **на реальном коде**, не на предположениях.
- Результат оформить в файл `audit/AUDIT_REPORT.md`.

### Использование предыдущего отчёта как базы

- Если существует предыдущий отчёт, прочитать его ПЕРЕД началом аудита.
- Использовать как **baseline для сравнения**: что улучшилось, что ухудшилось.
- В новом отчёте включить секцию **"Delta vs предыдущий аудит"** с маркерами:
  - FIXED — проблема исправлена
  - NEW — новая проблема
  - REGRESSED — проблема ухудшилась
  - UNCHANGED — проблема осталась

---

## ЖЁСТКИЕ ПРАВИЛА ОЦЕНКИ

| # | Правило | Последствие |
|---|---------|-------------|
| 1 | Hardcoded secret (пароль, token в коде) | Безопасность = **F** |
| 2 | MQTT credentials в открытом виде в коде | Безопасность: **критическая** проблема |
| 3 | Bare `except: pass` без логирования | Каждый случай = **важная** проблема |
| 4 | Race condition в async коде / coordinator | Каждый случай = **критическая** проблема |
| 5 | Нет тестов на ключевые модули (coordinator, config_flow) | Тесты = **F** |
| 6 | Покрытие тестами < 70% | Тесты **не выше C** |
| 7 | Покрытие тестами < 50% | Тесты = **D** |
| 8 | Отсутствие version pinning в manifest.json requirements | **Важная** проблема |
| 9 | Утечка стектрейсов в HA логи при нормальных device disconnects | **Важная** проблема |
| 10 | Любая критическая проблема в категории | Оценка категории **не выше D** |

---

## ОБЯЗАТЕЛЬНЫЕ ТРЕБОВАНИЯ К ПРОЕКТУ

### HA Integration Best Practices (ОБЯЗАТЕЛЬНО проверить!)

Интеграция **ОБЯЗАНА** соответствовать [Home Assistant Quality Scale](https://developers.home-assistant.io/docs/integration_quality_scale_index):

#### Обязательные файлы и настройки
- [ ] `manifest.json` — корректный domain, version, requirements, iot_class, config_flow
- [ ] `config_flow.py` — UI-конфигурация (НЕ YAML!)
- [ ] `strings.json` — source of truth для всех UI строк
- [ ] `translations/en.json` — английский перевод (ОБЯЗАТЕЛЬНО совпадает с strings.json)
- [ ] `translations/ru.json` — русский перевод
- [ ] `services.yaml` — описание всех сервисов с proper selectors
- [ ] `quality_scale.yaml` — отслеживание Quality Scale уровня
- [ ] `hacs.json` — HACS metadata
- [ ] `.gitignore` — покрывает __pycache__, .venv, secrets
- [ ] `README.md` — установка, настройка, поддерживаемые устройства
- [ ] `CHANGELOG.md` — история изменений в формате Keep a Changelog
- [ ] `LICENSE` — лицензия проекта

#### HA Architecture Patterns
- [ ] `DataUpdateCoordinator` для polling (НЕ `async_update` в entities!)
- [ ] `CoordinatorEntity` как base class для всех entities
- [ ] `ConfigEntry` (НЕ YAML `platform:` configuration!)
- [ ] `async_setup_entry` / `async_unload_entry` lifecycle
- [ ] `device_info` единообразен через все entities
- [ ] `unique_id` стабилен и уникален
- [ ] `available` property корректно отражает состояние устройства
- [ ] Entity naming: `_attr_has_entity_name = True`
- [ ] Proper entity categories (config, diagnostic)
- [ ] `async_forward_entry_setups` для platform registration

#### CHANGELOG Requirements (ОБЯЗАТЕЛЬНО!)
- [ ] Файл `CHANGELOG.md` СУЩЕСТВУЕТ в корне проекта
- [ ] Формат: [Keep a Changelog](https://keepachangelog.com/)
- [ ] Категории: Added, Changed, Fixed, Removed, Deprecated, Security
- [ ] Каждый релиз имеет дату и версию
- [ ] Секция `[Unreleased]` для текущей разработки
- [ ] История отражает ВСЕ значимые изменения
- [ ] Ведётся при КАЖДОМ коммите/релизе

---

## ПОРЯДОК ВЫПОЛНЕНИЯ

### Шаг 0. Изучить правила проекта

Прочитать:
- `CLAUDE.md` — правила проекта
- `manifest.json` — зависимости, версия
- `hacs.json` — HACS конфигурация
- `README.md` — документация
- `CHANGELOG.md` — история изменений

### Шаг 0.5. Прочитать предыдущий аудит (если есть)

### Шаг 1. Изучить структуру проекта

```bash
find custom_components tests -type f -name "*.py" | xargs wc -l | sort -n
```

### Шаг 2. Выполнить модули аудита последовательно

1. **`audit-00-setup.md`** — Подготовка среды
2. **`audit-01-security.md`** — Безопасность
3. **`audit-02-architecture.md`** — Архитектура
4. **`audit-03-runtime.md`** — Тесты и runtime
5. **`audit-04-llm-analysis.md`** — LLM-анализ бизнес-логики

### Шаг 3. Собрать отчёт по шаблону ниже

---

## ШКАЛА ОЦЕНОК

- **A** — Отлично. Соответствует best practices.
- **B** — Хорошо. Незначительные проблемы.
- **C** — Удовлетворительно. Заметные проблемы.
- **D** — Плохо. Много нарушений.
- **F** — Критично. Требуется немедленное вмешательство.

## УРОВНИ ПРОБЛЕМ

| Уровень | Описание | Примеры |
|---------|----------|---------|
| **Критический** | Безопасность, crash, потеря данных | Race conditions, неправильный device mapping, broken Sber MQTT protocol |
| **Важный** | Архитектурные проблемы, отсутствие тестов | Layer violations, no error handling, missing tests, missing CHANGELOG |
| **Мелкий** | Стиль, naming, документация | Code smells, missing docstrings |

---

## ФОРМУЛЫ СКОРИНГА

### Technical Debt Index (TDI)

```
TDI = (critical * 10 + important * 3 + minor * 1) / total_checks * 100
```

- TDI < 5 -> LOW
- TDI 5-15 -> MODERATE
- TDI 15-30 -> HIGH
- TDI > 30 -> CRITICAL

### Security Score (0-100)

| Проверка | Вес |
|----------|-----|
| Нет hardcoded secrets/tokens | 20 |
| Input validation (MQTT messages, Sber API responses, config) | 15 |
| Error handling не утекает sensitive data | 15 |
| Race conditions в async коде отсутствуют | 15 |
| Config flow валидирует input | 10 |
| Dependencies pinned и без CVE | 10 |
| `.gitignore` покрывает secrets | 5 |
| Entity-to-Sber-category mapping корректен | 10 |

| Score | Оценка |
|-------|--------|
| 90-100 | **A** |
| 75-89 | **B** |
| 60-74 | **C** |
| 40-59 | **D** |
| < 40 | **F** |

### HA Integration Quality Checklist

- [ ] Config flow корректен (manual setup + reauth + reconfigure)
- [ ] Entities правильно наследуют HA base classes
- [ ] DataUpdateCoordinator корректно реализован
- [ ] `available` property отражает device state
- [ ] Unique IDs стабильны
- [ ] Translations полные и корректные
- [ ] Services зарегистрированы через `services.yaml`
- [ ] HACS-compatible manifest
- [ ] Тесты покрывают ключевые пути
- [ ] Device info единообразен
- [ ] CHANGELOG.md ведётся и актуален
- [ ] quality_scale.yaml актуален

---

## ШАБЛОН ОТЧЁТА

Создать `audit/AUDIT_REPORT.md`:

```markdown
# Аудит кодовой базы Sber Smart Home MQTT Bridge
Дата: YYYY-MM-DD
Версия: X.Y.Z
Аудитор: Claude Code (автоматизированный аудит)

## Резюме
| Категория | Оценка (A-F) | Критических | Важных | Мелких |
(все категории + ОБЩАЯ)

## Delta vs предыдущий аудит
(если есть предыдущий)

## Скоринг
| Security Score | TDI | Test Coverage | HA Quality |

## Детальные находки

### 1. Безопасность
#### Secrets management
#### Input validation (MQTT messages, Sber API responses)
#### Config flow security
#### Dependencies

### 2. Архитектура
#### HA integration patterns
#### Bridge lifecycle (MQTT connection, reconnect)
#### Entity-to-Sber mapping
#### Entity design
#### Sber protocol serialization
#### Обязательные файлы и настройки

### 3. Тесты и Runtime
#### Test coverage
#### Error handling
#### Performance (MQTT connection, event handling)

### 4. LLM Analysis
#### Device control flow (light, climate, cover, relay, sensors)
#### Entity mapping correctness (HA domain → Sber category)
#### MQTT bridge data flow (HA events → Sber, Sber commands → HA)
#### Граничные случаи
#### Именование и читаемость

### 5. Документация и процессы
#### CHANGELOG.md
#### README.md
#### Translations
#### Quality Scale

## TOP проблем
## План действий
### Немедленно (24 часа)
### В течение спринта
### Плановый рефакторинг

## ФИНАЛЬНАЯ ОЦЕНКА
| Общая оценка | HACS Ready | Security Risk | Refactor Required |
```
