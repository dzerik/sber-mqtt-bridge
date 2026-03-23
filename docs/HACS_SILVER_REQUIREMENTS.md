# Требования HA Integration Quality Scale — Silver уровень

Актуально на 2026 год. Источник: [developers.home-assistant.io/docs/core/integration-quality-scale](https://developers.home-assistant.io/docs/core/integration-quality-scale/)

---

## Bronze (18 правил) — БАЗОВЫЙ УРОВЕНЬ

| # | Правило | Статус | Описание |
|---|---------|--------|----------|
| 1 | `config-flow` | done | UI-конфигурация через config_flow.py |
| 2 | `config-flow-test-coverage` | done | Тесты config flow (test_config_flow.py) |
| 3 | `runtime-data` | done | `ConfigEntry.runtime_data` с типизацией |
| 4 | `has-entity-name` | exempt | Service integration, не создаёт entity |
| 5 | `entity-unique-id` | exempt | Service integration |
| 6 | `entity-event-setup` | done | `async_track_state_change_event` в bridge |
| 7 | `test-before-setup` | done | Валидация MQTT подключения при setup |
| 8 | `test-before-configure` | done | Валидация в config_flow |
| 9 | `unique-config-entry` | done | `async_set_unique_id` по sber_login |
| 10 | `action-setup` | exempt | Нет custom actions/services |
| 11 | `appropriate-polling` | exempt | Push-based (MQTT), не polling |
| 12 | `brands` | todo | Нужно создать brand/ с icon.png |
| 13 | `common-modules` | done | sber_protocol.py, sber_entity_map.py |
| 14 | `dependency-transparency` | done | aiomqtt в manifest.json requirements |
| 15 | `docs-actions` | exempt | Нет custom actions |
| 16 | `docs-high-level-description` | todo | README.md нужно обновить |
| 17 | `docs-installation-instructions` | todo | README.md |
| 18 | `docs-removal-instructions` | todo | README.md |

## Silver (10 правил) — ЦЕЛЕВОЙ УРОВЕНЬ

| # | Правило | Статус | Описание |
|---|---------|--------|----------|
| 1 | `action-exceptions` | exempt | Нет custom actions |
| 2 | `config-entry-unloading` | done | `async_unload_entry` в __init__.py |
| 3 | `docs-configuration-parameters` | todo | Документация параметров config flow |
| 4 | `docs-installation-parameters` | todo | Документация параметров установки |
| 5 | `entity-unavailable` | exempt | Service integration |
| 6 | `integration-owner` | done | codeowners в manifest.json |
| 7 | `log-when-unavailable` | done | Логирование reconnect в sber_bridge.py |
| 8 | `parallel-updates` | exempt | Не polling integration |
| 9 | `reauthentication-flow` | todo | Нужно добавить reauth step в config_flow |
| 10 | `test-coverage` | todo | Нужно 95%+ покрытие |

## Gold (21 правило) — БУДУЩЕЕ

| # | Ключевые правила | Статус |
|---|------------------|--------|
| 1 | `devices` | exempt |
| 2 | `diagnostics` | done |
| 3 | `entity-translations` | exempt |
| 4 | `reconfiguration-flow` | todo |
| 5 | `docs-troubleshooting` | todo |
| 6 | `docs-known-limitations` | todo |

---

## Что нужно для Silver

### Сделано
- [x] Config Flow с валидацией подключения
- [x] Options Flow с EntitySelector
- [x] Config Entry Unloading
- [x] Runtime Data (typed)
- [x] Integration Owner (codeowners)
- [x] Log when unavailable / reconnect
- [x] Diagnostics
- [x] Translations (en, ru)
- [x] Тесты (66 тестов)

### Нужно доделать
- [ ] **Reauthentication Flow** — `async_step_reauth` в config_flow.py
- [ ] **Test Coverage 95%+** — добавить тесты для edge cases
- [ ] **Документация** — README с installation, configuration, removal
- [ ] **Brand Assets** — icon.png в brand/ директории
- [ ] **GitHub Release** — минимум один release для HACS

---

## HACS Publishing Requirements

### Обязательные файлы
- [x] `custom_components/sber_mqtt_bridge/manifest.json` — valid manifest
- [x] `custom_components/sber_mqtt_bridge/__init__.py` — entry point
- [x] `hacs.json` — HACS metadata
- [ ] `brand/icon.png` — brand icon (минимум 256x256)
- [ ] README.md — обновлённый, с описанием интеграции

### Обязательные GitHub Actions
- [ ] `.github/workflows/hassfest.yaml` — hassfest validation
- [ ] `.github/workflows/hacs.yaml` — HACS validation

### GitHub Repository
- [ ] Описание репозитория заполнено
- [ ] Topics установлены (homeassistant, hacs, sber, smart-home)
- [ ] Issues включены
- [ ] Минимум один GitHub Release (не просто tag)

---

## Инструменты качества кода

### Обязательные
- [x] `ruff` — linting + formatting (aligned with HA Core)
- [x] `mypy` — strict type checking
- [x] `pytest` — тестирование
- [ ] `pytest-cov` — coverage reporting
- [ ] `pre-commit` — git hooks (ruff, mypy, codespell)
- [ ] `codespell` — поиск опечаток

### CI/CD (GitHub Actions)
- [ ] hassfest validation
- [ ] HACS validation
- [ ] Ruff lint + format check
- [ ] Mypy type checking
- [ ] Pytest + coverage
- [ ] Release automation

### Рекомендуемые
- [ ] `dependabot.yml` — автообновление зависимостей
- [ ] `.github/CODEOWNERS` — автоназначение reviewers
- [ ] `.github/ISSUE_TEMPLATE/` — шаблоны issue

---

## GitHub Community Standards

| Файл | Статус | Расположение |
|------|--------|--------------|
| README.md | нужно обновить | корень |
| LICENSE | есть | LICENSE.txt |
| CONTRIBUTING.md | нужно создать | корень |
| CODE_OF_CONDUCT.md | нужно создать | корень |
| SECURITY.md | нужно создать | .github/ |
| Bug Report Template | нужно создать | .github/ISSUE_TEMPLATE/ |
| Feature Request Template | нужно создать | .github/ISSUE_TEMPLATE/ |
| PR Template | нужно создать | .github/ |
| CODEOWNERS | нужно создать | .github/ |
| FUNDING.yml | опционально | .github/ |
