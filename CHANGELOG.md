# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.36.3] - 2026-04-24

### Added

- **Advisory WARN-логирование для `device.name` / `device.id`** (модуль
  `name_utils`).  Перед publish проверяется, что `id` содержит только
  `[A-Za-z0-9_.-]`, а `name` — не пустой, не длиннее 63 символов.  При
  нарушении печатается WARN с entity_id — удобно для диагностики silent
  rejection (#32).  Валидация **advisory**: устройство всё равно
  публикуется, потому что Sber C2C docs не формализуют эти ограничения.
- **`slugify_sber_id(text)`** — Python-аналог `www/utils.js:slugify`.
  Кириллица → латиница, всё не-`[a-z0-9]` → `_`.  Для будущих YAML/API
  хелперов, которые строят `device.id` из человеческой строки.
- **`is_salut_friendly_name` / `is_safe_sber_id`** — предикаты для той
  же задачи, используются в pydantic/UI.

### Fixed

- Snapshot-тестов `test_protocol_snapshots.ambr` `hw_version`/`sw_version`
  для root hub обновлены под новый `VERSION`.

## [1.36.2] - 2026-04-24

### Added

- **DEBUG-логирование MQTT-payload.** При
  `custom_components.sber_mqtt_bridge: debug` в лог пишется полный JSON,
  публикуемый в `up/config` и `up/status`.  Нужно для диагностики silent
  rejection на стороне Sber cloud (issue #32): без payload невозможно
  понять, какая именно часть схемы отклоняется.

### Fixed

- **`sber_protocol.VERSION`** отставал на релиз (`1.36.0` при manifest
  `1.36.1`) — теперь синхронизирован с `manifest.json` и `pyproject.toml`.

## [1.36.1] - 2026-04-24

### Fixed

- **Panel: `css is not a function` в чистых HA-установках** (#32).
  Раньше компоненты получали `LitElement`, `html`, `css` через
  `Object.getPrototypeOf(customElements.get("ha-panel-lovelace"))` —
  этот подход зависит от того, гидратируют ли `html`/`css` через
  prototype сторонние HACS-карты.  В «толстых» установках с
  несколькими Lovelace-картами панель работала, в «чистых» —
  падала при первом рендере.

### Changed

- **Vendored lit 3.2.1** — `www/vendor/lit.js` (16 КБ, self-contained).
- **Новый shim** `www/lit-base.js` реэкспортирует `LitElement`,
  `html`, `css` и базовые helpers.
- **Все 16 компонентов** + `sber-panel.js` используют
  `import { LitElement, html, css } from "./lit-base.js"`
  (или `"../lit-base.js"` в `components/`).  Поведение не
  изменилось для пользователей, у которых панель уже работала;
  у пользователей «чистого» HA — теперь тоже работает.

## [1.36.0] - 2026-04-22

### Added

- **DevTools: «Why isn't it working?» per-entity diagnose** —
  один запрос собирает всю картину по конкретной entity из всех
  уже подключённых источников (entity registry, ack-stats,
  correlation trace, state diff, schema validation) и выдаёт
  вердикт `ok` / `warning` / `broken` с конкретными findings и
  actionable recommendations. Восемь правил:
  - `not_known_to_bridge` (error) — entity не загружена.
  - `not_enabled` (error) — загружена, но не включена.
  - `linked_sensor` (info) — это linked sensor, диагностируй
    primary.
  - `not_filled_by_state` (warning) — HA ещё не прислал state.
  - `never_acknowledged` (error) — Sber не подтвердил device
    (silent rejection).
  - `validation_errors` / `validation_warnings` (error/warning)
    — найдены schema-validation issues.
  - `recent_trace_failed` (error) — последняя trace ended as
    failed.
  - `recent_trace_timeout` (warning) — trace закрыт по timeout.

  Verdict берёт худшую severity из findings. Новые компоненты:
  - `diagnostics_advisor.py` — pure-функция
    `diagnose_entity(bridge, entity_id) -> DiagnosticReport`;
    каждое правило — независимая функция, легко добавлять новые.
  - WebSocket API: `sber_mqtt_bridge/diagnose_entity`
    (request/response, не subscribe).
  - UI-компонент `sber-diagnose.js` во вкладке DevTools —
    `entity_id` input + кнопка Diagnose, цветной verdict, список
    findings с action-подсказкой, collapsible raw summary и
    кнопка Copy report (для багрепортов).

## [1.35.0] - 2026-04-22

### Added

- **DevTools: Schema Validation** — каждый исходящий state-publish
  проверяется против авто-генерированной Sber-спецификации
  (`_generated/feature_types.py`,
  `_generated/obligatory_features.py`,
  `_generated/category_features.py`), найденные проблемы попадают в
  панель как actionable issues с severity. Четыре класса проверок:
  - `missing_obligatory` (error) — не хватает feature из
    обязательного списка category → Sber молча дропает устройство.
  - `type_mismatch` (error) — `value.type` не совпадает с
    `FEATURE_TYPES[key]` (например, `STRING` вместо `ENUM`).
  - `unknown_for_category` (warning) — feature не в reference set
    category.
  - `not_declared` (info) — feature в payload, но не в
    `features`-списке устройства.

  Новые компоненты:
  - `schema_validator.py` — pure-Python `validate_publish(...)` +
    `ValidationCollector` с ring-buffer'ом и per-entity
    latest-snapshot (чтобы UI мог и хронологически, и «что сломано
    прямо сейчас»).
  - Интеграция в `SberBridge._publish_states` — читает
    `entity.category` и `entity.get_final_features_list()` из уже
    загруженных entity'ов, не меняет publish-код.
  - WebSocket API: `sber_mqtt_bridge/validation_issues`,
    `.../clear_validation_issues`, `.../subscribe_validation_issues`.
  - UI-компонент `sber-validation.js` во вкладке DevTools — две
    вкладки (By entity / Timeline), счётчики errors/warnings/info,
    цветные severity-badges.

## [1.34.0] - 2026-04-22

### Added

- **DevTools: Replay / Inject** — кнопка «Replay» на каждой входящей
  записи MQTT-лога возвращает тот же payload обратно в диспетчер
  моста так, будто Sber прислал его снова. Сетевой round-trip не
  происходит, работает и в offline — тот же `SberCommandDispatcher`,
  тот же correlation trace, тот же state diff, тот же ack audit.
  Рядом — ручной JSON-editor с выбором topic suffix
  (`commands` / `status_request` / `config_request` / `errors` /
  `change_group` / `rename_device`) для инъекции произвольной
  команды. Синтетический трафик помечается в логе
  `direction="replay"`, чтобы UI не предлагал «реплеить реплей» и
  не зацикливал пользователя. Новые компоненты:
  - `SberBridge.async_inject_sber_message(topic, payload, *,
    mark_replay=True)` — публичный entrypoint, роутит через
    существующий `_mqtt_dispatch`.
  - WebSocket API: `sber_mqtt_bridge/inject_sber_message`,
    `.../replay_message`.
  - UI-компонент `sber-replay.js` во вкладке DevTools — manual
    inject form + список последних 15 incoming сообщений с кнопкой
    Replay.

## [1.33.0] - 2026-04-22

### Added

- **DevTools: State Diffs** — для каждой исходящей Sber-публикации
  считается delta по каждому устройству относительно предыдущей
  публикации и сохраняется только то, что реально изменилось
  (`added` / `removed` / `changed` с `before` и `after`). Sber-пейлоады
  повторяют всё состояние при каждой публикации — этот вид убирает
  шум и показывает одной строкой: `brightness: 50 → 75`,
  `color: — → [255, 0, 0]`, `on_off (removed)`. Пустые delta не
  записываются. Новые компоненты:
  - `state_diff.py` — `DiffCollector` с ring-buffer'ом, per-entity
    baseline и subscribe для live-потока.
  - Интеграция в `SberBridge._publish_states` через
    `DiffCollector.record_publish_payload` (парсит уже сериализованный
    JSON, ничего не ломая в publish-пути).
  - WebSocket API: `sber_mqtt_bridge/state_diffs`,
    `.../clear_state_diffs`, `.../subscribe_state_diffs`.
  - UI-компонент `sber-state-diff.js` во вкладке DevTools — таблица
    delta-строк с цветной подсветкой `+` / `−` / `~`.

## [1.32.0] - 2026-04-22

### Added

- **DevTools: Correlation Timeline** — группировка MQTT + HA событий в
  логические трассы по `HomeAssistant.Context.id` (встроенный в HA
  correlation ID, который автоматически распространяется через
  `service_call` → `state_changed`). Каждая трасса отображает полную
  цепочку: `sber_command` → `ha_service_call` → `ha_state_changed` →
  `publish_out` (и `silent_rejection` при молчаливом отказе Sber),
  позволяя одним взглядом понять, где оборвалась цепочка. Новые
  компоненты:
  - `trace_collector.py` — in-memory ring-buffer активных и закрытых
    трасс, с subscribe для live-потока и sweep по timeout.
  - Интеграция в `SberCommandDispatcher.handle_command`,
    `HaStateForwarder._handle_primary_state_change`,
    `SberBridge._publish_states` и `AckAudit` (silent rejection → trace
    failed).
  - WebSocket API: `sber_mqtt_bridge/traces`, `.../trace`,
    `.../clear_traces`, `.../subscribe_traces`.
  - UI-компонент `sber-traces.js` во вкладке DevTools — expandable
    timeline с цветной индикацией статуса (active / success / failed /
    timeout).

## [1.31.0] - 2026-04-15

### Added

- **Per-HA `ha_serial_number` marker** для loop-detection. Когда новая
  настройка `ha_serial_number_enabled` включена в панели (Settings →
  Loop detection), каждое опубликованное устройство (включая root hub)
  получает в `partner_meta.ha_serial_number` идентификатор:
  - реальный `DeviceEntry.serial_number` из HA, либо
  - нормализованный MAC из `DeviceEntry.connections`, либо
  - fallback `ha-<8-char-prefix>` от UUID этого Home Assistant.

  Поле кладётся в стандартное `partner_meta` (см. Sber spec
  `data-structures.md` и VR-003), новых полей в Sber-payload не
  добавляется. Совместимо с sister-проектом
  [`dzerik/ha-sberhome`](https://github.com/dzerik/ha-sberhome) v2.9.0+
  для определения import-loop'ов; более старые версии просто
  игнорируют поле, обратная совместимость сохраняется.

- Новая настройка `ha_serial_number_enabled` (default `False`) — toggle
  в группе **Loop detection** на странице настроек панели.

## [1.30.1] - 2026-04-15

### Changed

- Проект переведён в стадию **Public Testing** (из pre-alpha): обновлены
  README.md и README_ENG.md с призывом к тестерам и ссылками на шаблоны issue.

### Added

- Новый issue template `tester_feedback.yml` — структурированная форма для
  отчётов участников публичного тестирования (HA domain, Sber category,
  модель устройства, что работает / что нет, логи).
- Кнопка **«Open in HACS»** в README (обе локализации) — прямая установка
  в Home Assistant через my.home-assistant.io.

## [1.30.0] - 2026-04-13

### Changed

- **Architectural cleanup** of five long-standing duplications / API
  smells identified by a code audit:
  - Public feature-list API unified to `get_final_features_list()`; the
    subclass extension point is `_create_features_list()`.  Removed the
    `hasattr` fallback from two WebSocket endpoints (status, device).
  - Module-level `_safe_int_parser` / `_safe_float_parser` /
    `_safe_bool_parser` are now the single implementations; the static
    `BaseEntity._safe_int` / `_safe_float` / `_safe_clamped_int` helpers
    were duplicates and are gone.  `_safe_clamped_int_parser` added to
    complete the set.
  - `BaseEntity.update_linked_data` now has a concrete no-op default —
    `ha_state_forwarder` and `entity_registry` no longer probe with
    `hasattr` before calling it.
  - Entity factory: `CATEGORY_DOMAIN_MAP` is now the single source of
    truth for *every* Sber category, carrying the entity class via a
    new `CategorySpec.cls` field.  Deleted the parallel
    `CATEGORY_CONSTRUCTORS` / `ENTITY_CONSTRUCTORS` dicts and the seven
    `_create_sensor` / `_create_binary_sensor` / `_create_switch` /
    `_create_cover` / `_create_climate` / `_create_water_heater` /
    `_create_fan` / `_create_media_player` dispatchers.
  - New `AckAudit` helper collapses the reconnect guard, the
    silent-rejection audit timer, and the shutdown cancellation into
    one module.  The bridge loses three private methods and an
    `asyncio.TimerHandle` field.

### Added

- `tests/hacs/test_safe_parsers.py` — 36 contract tests for the
  `_safe_*_parser` helpers.
- `tests/hacs/test_ack_audit.py` — 7 contract tests describing the
  post-reconnect handshake protocol independent of bridge internals.
- `tests/hacs/test_entity_linking.py` — 2 tests locking in the
  `update_linked_data` no-op default.

## [1.29.1] - 2026-04-13

### Fixed

- **`ValveEntity` now emits `open_percentage`** (obligatory ✔︎ per Sber
  docs for the `valve` category). Before this fix, Sber cloud could
  silently reject any valve device since our payload was missing a
  mandatory feature. Value is derived from `is_open` (0 or 100) —
  HA valves are binary, so no position information is lost.

### Changed

- **`CATEGORY_REQUIRED_FEATURES` is now derived from the auto-generated
  `CATEGORY_OBLIGATORY_FEATURES`** (scraped from the ✔︎ markers in
  Sber's "Доступные функции устройства" table). Replaces the previous
  hand-curated dict and closes six gaps where our list was looser than
  Sber's spec: `curtain`, `window_blind`, `gate`, `valve` (now require
  `open_percentage`/`open_set`/`open_state`), `hvac_ac` (now requires
  `hvac_temp_set`).
- **`sensor_temp` override**: Sber's reference device is a combo
  temperature+humidity sensor (both ✔︎). HA models them as separate
  entities, so we loosen compliance for `sensor_temp` to `{online}`
  via an explicit, documented `_CATEGORY_OBLIGATORY_OVERRIDES`
  mechanism. Users who want combo semantics can link a humidity
  sensor to the temperature sensor via the panel.

## [1.29.0] - 2026-04-12

### Added

- **Strict pydantic validation** — all Sber protocol models rewritten
  with `extra="forbid"`. Invalid payloads are now **rejected before
  MQTT publish**, not after Sber silently drops the device.
- **Per-device validation** — each device validated individually via
  `validate_device()`. Invalid devices excluded from config payload
  (logged at WARNING), valid devices proceed normally.
- **Category compliance validator** — `CATEGORY_REQUIRED_FEATURES`
  dict with required features per category (28 categories, verified
  via Context7 against official Sber C2C docs). Catches missing
  `on_off` for control devices, missing `pir` for sensors, etc.
- **Typed allowed_values** — `SberAllowedValue` discriminated union
  replaces `dict[str, Any]`. Catches type errors (e.g. integer
  min/max as int instead of string).
- **TV bug prevention** — validator checks `allowed_values` keys are
  subset of `features` list. Extra keys (which caused silent device
  rejection) now caught at validation time.
- **Validation failure repair issue** — new HA repair issue
  `validation_failures` with list of excluded entity IDs.
- **97 new tests** in `test_sber_models_strict.py` — strict model
  validation, category compliance, integration tests verifying real
  device class output against schema.

## [1.28.0] - 2026-04-12

### Added

- **Silent rejection detection** — ack audit runs 60s after config
  publish, creates HA repair issue
  (`Settings > System > Repairs`) when entities remain unacknowledged
  by Sber cloud. Configurable via `CONF_ACK_AUDIT_DELAY`.
- **Sber error tracking** — `handle_error` now parses error payload
  and stores `last_error_detail` in stats. New repair issue
  `sber_errors` with error count and detail.
- **Health scoring** in `ws_get_status` response: `healthy` /
  `degraded` / `unhealthy` with issue list.
- **Health badge** in toolbar (yellow/red pill) when degraded or
  unhealthy.

### Fixed

- **scenario_button** missing `long_press` in `button_event`
  allowed_values (Sber protocol compliance).

## [1.27.0] - 2026-04-12

### Changed

- **Architecture debt fully resolved** (ARCHITECTURE_RESEARCH.md §10,
  all 7 items closed):
  - **10.1** `LightEntity.LINKABLE_ROLES` now accepts battery / signal
    linked sensors (was empty tuple).
  - **10.2** `_publish_config` / `_publish_states` now route through
    `MqttClientService.publish()` instead of raw `_mqtt_client` access.
  - **10.3** `SberCommandDispatcher` takes `BridgeCommandContext` Protocol
    instead of full `SberBridge` reference — explicit, narrow coupling.
  - **10.4** Extracted `ReconnectAckGuard` component (`reconnect_ack_guard.py`)
    from scattered bridge fields.
  - **10.5** Hardcoded `1.5s` in `_delayed_confirm` → configurable
    `CONF_CONFIRM_DELAY` in `SETTINGS_DEFAULTS`.
  - **10.6** `process_cmd` returns `list[CommandResult]` (union of
    `ServiceCallResult | UpdateStateResult` TypedDicts) instead of
    untyped `list[dict]`. Applied across all 14 device classes.
  - **10.7** All 8 complex device classes migrated to declarative
    `AttrSpec` (extended with `converter` field for full-attrs access):
    tv, hvac_fan, hvac_air_purifier, humidifier, kettle,
    vacuum_cleaner, light, climate.

## [1.26.1] - 2026-04-12

### Fixed

- **TV entities silently rejected by Sber** — `allowed_values` contained
  7 extra keys (volume_int, channel, channel_int, direction, volume,
  custom_key, number) beyond what Sber TV reference specifies. Sber cloud
  accepted the config but never sent `status_request` for TV devices.
  Now only `source` is sent in `allowed_values` (per reference model).
- **Orphan entities (SmartIR, templates) invisible in wizard** — entities
  without `device_id` were skipped by `HaDeviceGrouper`. Now each orphan
  becomes its own "virtual" device group. `ws_add_ha_device` also
  recognizes orphan entities (device_id == entity_id).
- **Panel kick-out after adding device** — `ws_add_ha_device` called
  `async_reload` which tore down the sidebar panel mid-navigation.
  Replaced with hot-reload via `bridge._reload_entities_and_resubscribe()`
  + `_publish_config()`.
- **Unique model_id for TV with instance-specific source_list** — added
  `_has_instance_allowed_values()` hook; TV entities with different
  source lists now get unique model IDs (MD5 suffix).

## [1.26.0] - 2026-04-12

### Added

- **Device-centric wizard (type-first flow)** — полностью переписанный
  Add Device Wizard, заменяющий старый entity-first pipeline. Новый
  поток: Step 1 сетка категорий Sber → Step 2 HA-устройство целиком с
  раскрытыми linked-native (preselected) + linked-compatible (opt-in)
  датчиками → Step 3 имя / комната / атомарный submit.
- **`custom_components/sber_mqtt_bridge/device_grouper.py`** — новый
  модуль, домен-агностичный `HaDeviceGrouper` с публичными методами
  `list_for_category(sber_category)` и
  `preview_for_category(device_id, sber_category)`. Возвращает
  `DeviceGroup` с полями `primary`, `primary_alternatives`,
  `linked_native`, `linked_compatible`, `unsupported`,
  `already_exposed`, отсортированный по
  `(not already_exposed, area, name.casefold())`.
- **Реестр категорий в `sber_entity_map.py`**: фрозен-датакласс
  `CategorySpec` (domains / device_classes / preferred_rank /
  fallback_when_no_device_class) + `CATEGORY_DOMAIN_MAP` (28
  категорий), `CategoryUiMeta` + `CATEGORY_UI_META`, `CATEGORY_GROUPS`,
  хелпер `categories_for_domain(domain, device_class)`. Это new source
  of truth для promotion HA domain → Sber category (было хардкод в
  frontend `DEVICE_GROUPS`).
- **Новые WebSocket команды** (`websocket_api/devices_grouped.py`):
  - `sber_mqtt_bridge/list_categories` — сетка Step 1 (фильтрует
    подкатегории с `user_selectable=False`).
  - `sber_mqtt_bridge/list_devices_for_category` — список HA-устройств
    для Step 2.
  - `sber_mqtt_bridge/add_ha_device` — атомарный add (patch
    `exposed_entities` + `entity_type_overrides` + `entity_links` +
    `redefinitions` → один reload).
  - `sber_mqtt_bridge/suggest_links` — переписан как тонкая обёртка
    над `HaDeviceGrouper.preview_for_category` для post-add edit flow
    в `sber-link-dialog.js`.
- **77 новых тестов**: `test_category_domain_map.py` (32),
  `test_device_grouper.py` (25), `test_websocket_devices_grouped.py`
  (20).

### Changed

- **`sber-wizard.js`** полностью переписан как LitElement type-first
  компонент с role-conflict guard (селект датчика с той же ролью
  автоматически снимает предыдущий). Переиспользует существующий
  стиль панели (HA CSS vars, color-mix, stepper).
- **`sber-toolbar.js`**: убраны кнопка *"Add Devices"* и пункт *"Add
  All Entities"* из bulk-меню; dropdown переименован в *"Maintenance"*;
  primary-кнопка *"Add device"* диспатчит `toolbar-wizard` напрямую.
- **`sber-panel.js`**: удалены методы `_addEntities`, `_bulkAddAll`,
  `_onAddEntities`, `_onToolbarBulkAdd` и элемент `<sber-add-dialog>`.

### Removed

- **`sber-add-dialog.js`** (477 LOC) — заменён визардом, backwards
  compat пути не сохраняются (pre-alpha, один пользователь).
- **`ws_add_device_wizard`** — заменён на `ws_add_ha_device`.
- **`ws_get_available_entities`** — данные теперь берутся из
  `list_devices_for_category`.
- **`ws_bulk_add`** — функция встроена в `ws_add_ha_device`.

## [1.25.1] - 2026-04-12

### Changed

- **P1 completion — physical class extraction**: finished the architectural
  decomposition left open in 1.25.0.
  - New module **`mqtt_client_service.py`** (`MqttClientService`,
    `MqttServiceHooks`, `SberMqttCredentials`) owns the persistent MQTT
    connection, exponential-backoff reconnect loop, publish / subscribe
    primitives and message consumption.  `SberBridge` no longer hosts
    the transport logic — it only injects callbacks.
  - New module **`command_dispatcher.py`** (`SberCommandDispatcher`) owns
    all Sber-protocol command handling: ``handle_command``,
    ``handle_status_request``, ``handle_config_request``,
    ``handle_error``, ``handle_change_group``, ``handle_rename_device``,
    ``handle_global_config``.  Bridge methods ``_handle_sber_*`` are now
    thin proxies kept only for test compatibility.
  - New module **`ha_state_forwarder.py`** (`HaStateForwarder`) owns HA
    state-change subscription, linked-entity routing, debouncing and
    feature-change detection.  Bridge methods ``_on_ha_state_changed``
    and ``_schedule_debounced_publish`` are now thin proxies for tests.
  - `SberBridge` shrank from 1440 → 1007 LOC and now acts as a
    coordinator around five collaborators: `MqttClientService`,
    `SberCommandDispatcher`, `HaStateForwarder`, `SberEntityLoader`,
    `MessageLogger`.  Further LOC reduction is gated on rewriting ~2000
    lines of mock-heavy tests that reach into bridge internals.

- **P2.1 — declarative attribute parsing**: added a mini-framework in
  `devices/base_entity.py`:
  - New dataclass **`AttrSpec`** (field / attr_keys / parser / default /
    preserve_on_missing) describes how to read one HA attribute into one
    instance field.
  - New method **`BaseEntity._apply_attr_specs(attrs)`** walks the
    class-level ``ATTR_SPECS`` tuple and does the parsing in one pass,
    replacing 6–15 lines of hand-rolled try/except/int() boilerplate per
    device.
  - Migrated device classes: `OnOffEntity` (power / voltage / current /
    child_lock), `SimpleReadOnlySensor` (battery / signal, with
    ``preserve_on_missing=True`` to honour linked-sensor injection),
    `CurtainEntity` (battery / tilt / signal), `ValveEntity` (battery /
    signal).  These base classes cascade to 12 of 15 device
    implementations.  Sensors with special mapping logic (climate,
    humidifier, light, tv, kettle, vacuum_cleaner) keep imperative
    parsing — the AttrSpec system is opt-in and coexists cleanly.

- **P2.4 — `SETTINGS_DEFAULTS`-driven init**: new
  `SberBridge._load_settings_from_options(options)` drives attribute
  assignment from `const.SETTINGS_DEFAULTS` instead of scattered
  `opts.get(key, hardcoded_default)` calls.  `apply_settings()` now
  reuses the same loader, eliminating duplicate default values.

### Fixed

- `_delayed_confirm` tasks now use ``self._create_safe_task`` (unified
  error logging) and stop pointlessly re-raising `CancelledError`.

## [1.25.0] - 2026-04-12

### Changed

- **Large-scale refactoring** per deep code review (P0 + P1 + P2 tasks):
  - **Device classes**: all 15 `process_cmd` implementations migrated to the new
    `BaseEntity._build_service_call(domain, service, entity_id, service_data)`
    helper, eliminating ~60 hand-written `{"url": {"type": "call_service"...}}`
    literals and the typo surface they carried.
  - **Command pattern**: `ClimateEntity.process_cmd` (220 lines) and
    `LightEntity.process_cmd` (156 lines) rewritten via dispatch tables
    plus small per-feature handler methods; cognitive complexity dropped
    from ~45 to ~3 per handler.
  - **`SberFeature` enum everywhere**: magic string keys (`"on_off"`,
    `"hvac_temp_set"`, …) in `process_cmd` replaced with `SberFeature.*`
    constants across all device modules.
  - **`BaseEntity` cleanup**:
    - Added `_build_service_call` and `_safe_clamped_int` helpers.
    - Unified `to_sber_state` `device_id is None / else` branches into a
      single code path via `_resolve_display_name`, `_resolve_default_name`
      and `_build_model_descriptor` helpers.
    - Replaced raw `"unavailable" / "unknown"` literals with
      `STATE_UNAVAILABLE` / `STATE_UNKNOWN` imports.
    - `DeviceData` promoted to `TypedDict` for better type safety.
  - **`SberBridge` decomposition**:
    - `_mqtt_connection_loop` split into `_handle_connected`,
      `_mark_connected`, `_wait_for_ha_ready`, `_perform_initial_publish`,
      `_subscribe_down_topics`, `_setup_ack_guard`, `_consume_messages`.
    - `_on_ha_state_changed` split into `_handle_linked_state_change` and
      `_handle_primary_state_change`.
    - `_handle_mqtt_message` replaced with a dispatch table keyed by topic
      suffix (`_mqtt_dispatch`).
    - New **`SberEntityLoader`** (`entity_registry.py`) owns HA registry
      lookup, YAML overrides, link resolution and conflict detection;
      `SberBridge._load_exposed_entities` is now a 30-line orchestrator.
    - New **`MessageLogger`** (`message_logger.py`) owns the DevTools ring
      buffer and real-time subscriber fan-out.
    - `_delayed_confirm` extracted from nested closure, routed through
      `_create_safe_task` for consistent error handling.
  - **WebSocket API split**: 1567-line `websocket_api.py` converted to a
    package with 8 focused submodules (`status`, `entities`, `links`,
    `raw`, `io_export`, `settings`, `log`, `_common`).  Package
    `__init__.py` re-exports all `ws_*` commands for backwards compat.
  - **Public API** for redefinitions: `SberBridge.async_update_redefinition`
    and `async_republish_config`; WebSocket `ws_update_redefinitions` no
    longer reaches into `bridge._redefinitions` / `bridge._publish_config`.
  - **`validate_config_payload`** return value threaded through
    `build_devices_list_json` — both serialisers now return
    `(json_string, validation_passed)` for consistency.

### Fixed

- **TOCTOU race** in `SberBridge._publish_states` / `_publish_config`:
  MQTT client reference is now snapshotted to a local variable before the
  connectivity check, eliminating the `except (AttributeError, TypeError)`
  fallback that previously masked unrelated bugs.
- **Exception handling** in `_handle_sber_command`: replaced the narrow
  `(TimeoutError, KeyError, ValueError, AttributeError)` catch with
  `HomeAssistantError`, `ServiceNotFound`, `ServiceValidationError`,
  `Unauthorized`, `TimeoutError` — the actual exception types raised by
  `hass.services.async_call`.

### Security

- `create_ssl_context(verify=False)` now logs a `WARNING` — previously the
  caller could silently disable certificate verification without any
  audit trail.

## [1.24.2] - 2026-04-02

### Added
- **Connection phase indicator**: UI shows lifecycle phases after restart — Starting, Connecting, Awaiting Sber, Ready, Disconnected (with pulsing animation for in-progress states)
- **Hardware testing status**: README callout + devices page with tested (12) vs untested (16) categories

### Fixed
- **Settings UI**: toggle switches no longer stretch full width
- **Test count**: badge updated to 1470+

## [1.24.0] - 2026-04-02

### Added
- **Hub Device in Settings UI**: Hub (root device) now visible in Settings tab with name, home, room, version, online status, and children count
- **Auto parent_id**: All child devices automatically get `parent_id: "root"` linking them to the hub in Sber hierarchy (configurable toggle in Settings)
- **Hub info in WebSocket API**: `sber_mqtt_bridge/status` now returns `hub` object with full hub metadata

### Changed
- **Protocol**: `build_devices_list_json` now accepts `auto_parent_id` parameter (default: True)

## [1.23.1] - 2026-04-02

### Fixed
- **Curtain/Gate/WindowBlind**: Position fallback checked `"opened"` but HA cover uses `"open"` — open covers without `current_position` attribute defaulted to 0 (closed) instead of 100
- **Climate**: NaN temperature no longer crashes `to_sber_current_state` (guarded with `math.isfinite`)
- **Climate**: Negative humidity commands now clamped to 0-100 range
- **SensorTemp**: NaN/Inf state values no longer crash `_get_sber_value` (guarded with `math.isfinite`)

## [1.23.0] - 2026-04-02

### Fixed
- **CRITICAL: Light brightness** — `ha_to_sber_hsv` received Sber-scaled brightness (100-900) instead of HA raw (0-255), causing all color lights to report max brightness to Sber cloud
- **CRITICAL: Delayed confirm accumulation** — N rapid Sber commands produced N simultaneous MQTT publishes after 1.5s; now deduped per entity (cancel previous task)
- **CRITICAL: Entry reload mid-MQTT-loop** — `_persist_redefinitions` triggered OptionsFlowWithReload during message processing; now debounced to 2s
- **Color converter** — `sber_value=None` or values <100 now correctly map to brightness 0 instead of erroneously clamping to 100
- **Linear converter** — reversed mode (color_temp) had wrong min/max clamping for out-of-range values
- **Light brightness=0 command** — `_safe_int(...) or 50` replaced valid 0 with 50; now uses proper None guard
- **Light color_temp command** — same `or 0` pattern fixed with None guard
- **Curtain position** — `current_position` now cast to int and clamped 0-100 in `fill_by_ha_state`
- **Curtain position command** — `or 0` pattern fixed; parse failure no longer closes curtains
- **TV volume_level** — added `_safe_float` guard to prevent crash on non-numeric attribute
- **Climate night_mode off** — now finds first non-night preset instead of blindly sending `"none"`
- **Humidifier humidity command** — parse failure no longer sends `set_humidity(0)`
- **Kettle temperature command** — parse failure no longer sends `set_temperature(0)`
- **Sensor linked data** — `fill_by_ha_state` no longer resets battery/signal from linked sensors to None
- **old_state type** — `process_state_change` now receives dict instead of raw HA `State` object
- **Reconnect ack timeout** — one-shot timer auto-clears `_awaiting_sber_ack` after timeout

### Changed
- **Vacuum** — `vacuum_cleaner_status` and `vacuum_cleaner_cleaning_type` removed from `allowed_values` (read-only features, no HA service handler)
- **Curtain** — `open_rate` removed from `allowed_values` (read-only, HA cover has no set_speed service)
- **BaseEntity** — `process_cmd` now returns `[]` by default (defensive against None cmd_data)
- **Bridge** — `_reload_entities_and_resubscribe` encapsulates coupled load+subscribe calls

## [1.22.1] - 2026-04-02

### Fixed
- **Protocol**: `SberValue.integer_value` type `int` → `str` to match C2C spec (VR-002)
- **Protocol**: `SberValue` now supports all 6 Sber types (added FLOAT, STRING)
- **Protocol**: `parse_sber_command()` validates `devices` is dict (VR-032)
- **ScenarioButton**: Remove `long_press` from allowed_values — HA input_boolean cannot produce it

## [1.21.0] - 2026-04-02

### Fixed
- **Light RGB**: `hs_color` tuple support — HA returns tuple not list, broke colour mode detection for all RGB lights
- **Light**: `color_temp` → `color_temp_kelvin` for HA 2025+ (deprecated mireds in service_data)
- **Light**: Minimum brightness=1 on color command to prevent accidental turn-off
- **Light**: Dependencies field `"value"` → `"values"` per Sber protobuf spec (fixed ESPHome lamp rejection)
- **Bridge**: Delayed state confirmation (1.5s) after Sber commands — ensures colour mode published back to Sber
- **DevTools**: Copy payload button in MQTT Message Log

## [1.22.0] - 2026-04-02

### Fixed
- **Light RGB**: `hs_color` tuple support — HA returns tuples, not lists (broke colour mode)
- **Light**: `color_temp` → `color_temp_kelvin` for HA 2025+
- **Light**: Min brightness=1 on colour command prevents accidental turn-off
- **Light**: Dependencies `"value"` → `"values"` per Sber protobuf
- **Vacuum**: Status enums: `returning`→`go_home`, `docked`→`standby`, `paused`→`standby` (per Sber docs)
- **TV**: Direction `left`/`right`/`ok` now handled (→ prev_track/next_track/play_pause)
- **Protocol**: `hw_version`/`sw_version` fallback `"Unknown"` → `"1"`

### Added
- **Bridge**: Delayed 1.5s state confirmation after Sber commands (fixes async ESPHome)
- **DevTools**: Copy payload button in MQTT Message Log
- **Tests**: 553 Sber C2C compliance tests (structure + enum values for all 15+ device classes)

## [1.20.1] - 2026-04-02

### Fixed
- **Protocol**: Remove `dependencies` from MQTT config payload — Sber protobuf rejects `"value"` field in dependencies structure via MQTT (fixes ESPHome RGB lamps and all devices with dependencies being silently rejected)
- **Protocol**: Replace `"Unknown"` with `"1"` for missing hw_version/sw_version (Sber may reject "Unknown")
- **DevTools**: Copy payload button in MQTT Message Log

## [1.20.0] - 2026-04-02

### Added
- **Curtain**: `light_transmission_percentage` from HA `tilt_position` attribute (for blinds)
- **TV**: `direction` command handling (up=volume_up, down=volume_down)
- **Constants**: `LIGHT_TRANSMISSION_PERCENTAGE` added to SberFeature enum

### Deferred
- `open_left/right_percentage` — no standard HA mapping for double curtains
- `custom_key` / `number` — no standard HA service for remote key press in media_player

## [1.19.0] - 2026-04-02

### Added
- **Sensors**: `sensor_sensitive` for all sensor types — reads sensitivity/motion_sensitivity from HA attributes (ENUM: auto/high/low)
- **Climate**: `child_lock` support from HA attributes
- **Humidifier**: `child_lock` support from HA attributes

### Deferred
- `sleep_timer` for light/tv — requires async scheduling architecture in bridge (separate PR)

## [1.18.1] - 2026-04-02

### Added
- **Sensors**: `tamper_alarm` for water_leak, smoke, gas sensors (from HA tamper attribute)
- **Sensors**: `alarm_mute` for water_leak sensor (parity with smoke/gas)
- **TV**: `channel_int` feature — switch channel by number via `media_player.play_media`
- **Curtain**: `open_rate` feature (ENUM: auto/low/high) when HA cover has speed attribute

## [1.18.0] - 2026-04-02

### Changed
- **Model ID**: Category suffix appended to all model_ids (`TS0002_limited` → `TS0002_limited_hvac_fan`) to prevent Sber cloud from overriding device category based on its own model database
- **Fan**: Simple on/off fans (no speed support) no longer declare `hvac_air_flow_power` feature — only `on_off` + `online`
- **Curtain**: Pass `opening`/`closing` intermediate states to Sber (previously collapsed to `open`/`close`)

## [1.17.2] - 2026-04-02

### Fixed
- **PIR sensor**: Event-based — only emit `pir` on motion, omit key when idle (fixes "always detecting" in Sber)
- **Wizard linking**: Same-device siblings always compatible regardless of LINKABLE_ROLES
- **Wizard linking**: Create temporary entity via factory with category override for correct LINKABLE_ROLES in wizard flow
- **Sensor subclass**: Humidity sensor created correctly even with `sensor_temp` category override (device_class aware)
- **Naming**: `friendly_name` used when entity name matches `original_name` (fixes "Температура" instead of "Климат детская Температура")

## [1.17.1] - 2026-04-02

### Fixed
- **Rooms**: `effective_room` property — entity area → device area fallback, so devices without their own area inherit room from device registry
- **Rooms**: Hub device now includes `home` and `room` fields (per Sber C2C docs)
- **Rooms**: Default `home`/`room` fallback hardcoded to "Мой дом" when HA `location_name` is not set
- **Rooms**: Area name resolution in `ws_device_detail` and device registry display
- **Wizard**: Pre-fills room from HA area; saves name/room to redefinitions on device creation
- **API**: `available_entities` endpoint now returns resolved `area` name per entity

## [1.17.0] - 2026-04-02

### Added
- **UI**: Edit form in device detail dialog — edit Sber name, room, and home directly from the panel with Save & Re-publish
- **Protocol**: Default room fallback from HA `location_name` for devices without an area
- **Protocol**: Area name resolution — `area_id` slugs (e.g. "living_room") now resolve to human-readable names (e.g. "Гостиная") via HA area registry
- **API**: New WebSocket endpoint `sber_mqtt_bridge/update_redefinitions` for saving device overrides from UI

## [1.16.1] - 2026-04-02

### Fixed
- **Naming**: Use `friendly_name` from HA state attributes as fallback when entity registry has no custom name — devices like `light.svet_nad_stolom` now show their human-readable name instead of entity_id

## [1.16.0] - 2026-04-02

### Added
- **Protocol**: Default `home` field for all devices — uses HA `location_name` as fallback when not set via redefinitions, fixing Sber cloud silently rejecting devices without `home`
- **Model**: `home` field added to `SberDevice` Pydantic model

## [1.15.3] - 2026-04-02

### Changed
- **UI**: Toolbar button order — Wizard first, then logical groups (entity management, sync, import/export) separated by vertical dividers

## [1.15.2] - 2026-04-02

### Fixed
- **UI**: Panel goes blank after long idle — added `visibilitychange` listener for instant re-fetch when tab returns to foreground, retry on WS reconnect when in error state, re-fetch on DOM re-attach

## [1.15.1] - 2026-04-01

### Changed
- **UI**: Adaptive responsive layout for mobile devices — device list renders as cards on screens ≤768px, toolbar buttons compact, tabs horizontally scrollable, detail dialog fullscreen on mobile

## [1.15.0] - 2026-03-31

### Changed
- **Architecture**: Entity link roles are now declared on device classes via `LINKABLE_ROLES` class attribute (`LinkableRole` dataclass) instead of centralized `ALLOWED_LINK_ROLES` / `HA_DEVICE_CLASS_TO_LINK_ROLE` dicts — each device class self-describes which sensor roles it accepts, with domain+device_class matching built into the role definition
- **Entity linking**: `ws_suggest_links` and `ws_auto_link_all` now query device class `LINKABLE_ROLES` directly — no more manual domain overrides or separate mapping tables

### Removed
- `ALLOWED_LINK_ROLES` dict from `const.py` (replaced by `LINKABLE_ROLES` on device classes)
- `HA_DEVICE_CLASS_TO_LINK_ROLE` dict from `const.py` (replaced by `resolve_link_role()` using `ALL_LINKABLE_ROLES` registry)

## [1.14.1] - 2026-03-31

### Fixed
- **Entity linking**: `number` entities with `device_class=humidity` (target humidity) now get distinct role `target_humidity` instead of clashing with `sensor` humidity role — fixes inability to link external humidity sensor to `hvac_humidifier`
- **Humidifier linked sensor**: `HumidifierEntity` now implements `update_linked_data()` — linked humidity sensor value is used as `current_humidity` for Sber `humidity` feature

## [1.14.0] - 2026-03-30

### Added
- **Reconnect guard**: after (re)connect, Sber commands are rejected until Sber acknowledges our states via `status_request` or `config_request` (30s fallback timeout) — replaces unreliable fixed-timer grace period

### Fixed
- **Critical**: Sber cloud no longer overrides HA device state after integration restart — publish-before-subscribe ensures Sber knows the real HA state before it can send commands; reconnect guard waits for real Sber acknowledgment before accepting commands
- **Startup noise**: linked entity "state not yet available" warnings downgraded to DEBUG during early startup (entities load after HA started event)
- **False-positive repairs**: `check_and_create_issues` deferred until HA is fully started — prevents "broken link" repair issues during early async_setup_entry when linked entities are still loading

### Changed
- MQTT connection loop now publishes config + states BEFORE subscribing to `down/#` — MQTT broker only delivers messages after SUBSCRIBE, so stale commands never enter the buffer
- Reconnect guard uses Sber acknowledgment (`status_request` / `config_request`) instead of fixed 5-second timer

## [1.13.2] - 2026-03-30

### Fixed
- **Race condition**: fire-and-forget `async_create_task` calls now use safe wrapper with error logging — prevents silent state update drops (structural cousin of [#3](https://github.com/dzerik/sber-mqtt-bridge/issues/3))
- **Race condition**: `_message_subscribers` set iteration now uses snapshot to prevent `RuntimeError` if a WebSocket disconnect triggers `unsub()` during callback dispatch
- **Race condition**: TOCTOU `_mqtt_client` null-check now logs at DEBUG level when publish is dropped due to disconnect race, instead of failing silently
- **State desync**: `light_mode` command no longer prematurely mutates `current_color_mode` — waits for HA state confirmation via `fill_by_ha_state` to avoid publishing stale mode to Sber
- **State desync**: `mark_state_published` is now skipped when `validate_status_payload` fails — prevents the bridge from thinking an invalid payload was accepted by Sber
- **Startup perf**: removed redundant double `_load_exposed_entities` + `_subscribe_ha_events` call on integration reload path

### Changed
- `build_states_list_json` now returns `tuple[str, bool]` (payload, validation_passed) instead of just `str`

## [1.13.1] - 2026-03-30

### Fixed
- **Critical**: Sber-originated commands (via Salute app) now correctly publish state confirmation back to Sber cloud — previously the echo suppression mechanism blocked the publish, causing Salute to show stale device state ([#3](https://github.com/dzerik/sber-mqtt-bridge/issues/3))

### Removed
- Echo loop prevention (`_sber_context_ids`) — unnecessary because Sber commands arrive on `down/commands` while state updates are published on `up/status` (no feedback loop possible)
- `context_cleanup_threshold` setting from UI (no longer needed)

## [1.13.0] - 2026-03-26

### Added
- **Settings Tab**: new 4th tab in panel for bridge operational settings (reconnect intervals, debounce delay, message log size, payload limit, context cleanup threshold, SSL verification) — changes applied immediately where possible
- **DevTools: Raw JSON Send**: textarea + "Send to Sber" button for config and state payloads — pre-fills with current payload on Load, validates JSON before sending
- **DevTools: WebSocket Push**: MQTT message log now uses real-time WebSocket subscription instead of 5-second polling — messages appear instantly
- **WS API**: `get_settings`, `update_settings`, `send_raw_config`, `send_raw_state`, `subscribe_messages` commands

### Changed
- Bridge operational parameters (reconnect, debounce, log size, payload limit) now read from `config_entry.options` with `SETTINGS_DEFAULTS` fallbacks instead of hardcoded constants
- `_log_message()` helper centralizes message logging + subscriber notification (replaces 3 inline `_message_log.append()` calls)

## [1.12.4] - 2026-03-26

### Changed
- **Refactor**: split `_load_exposed_entities` (200 lines, complexity ~18) into 7 focused helpers: `_create_entities`, `_apply_yaml_overrides`, `_link_device_registry`, `_apply_entity_links`, `_check_device_conflicts`, `_apply_room_overrides`, `_finalize_entity_load`
- **Refactor**: extract `_handle_disconnect` helper to DRY MQTT error handling (was duplicated for MqttError and generic exceptions)
- **Fix**: replace bare `except Exception` with `(OSError, ValueError, RuntimeError)` in MQTT loop (ruff BLE001)

## [1.12.3] - 2026-03-26

### Added
- **Climate**: `eco` work mode mapping (HA `eco` hvac_mode -> Sber `eco`); `turbo`/`quiet` work modes from HA preset_modes (`boost`->`turbo`, `sleep`->`quiet`)
- **TV**: `channel` (+/-), `direction` (up/down/left/right/ok) features with channel switching via media_next/previous_track
- **Vacuum**: `vacuum_cleaner_cleaning_type` feature (dry/wet/dry_and_wet) from HA `cleaning_type` attribute
- **Humidifier**: `hvac_water_percentage` and `hvac_water_low_level` features from HA attributes
- **Sensor temp**: `temp_unit_view` feature (c/f) from HA `unit_of_measurement`

### Fixed
- **Humidifier**: `hvac_humidity_set` range now reads `min_humidity`/`max_humidity` from HA entity (default 35-85 per Sber spec, was 0-100)
- **Translations**: added missing `broken_entity_links` issue translation key in strings.json, en.json, ru.json

## [1.12.2] - 2026-03-26

### Fixed
- **Лампы отображаются как вентиляторы в Sber**: при первом подключении к MQTT конфиг публиковался до полной загрузки HA — entity features (brightness, color, color_temp) были пустыми, и Sber cloud неправильно классифицировал устройства; теперь первая публикация ожидает `EVENT_HOMEASSISTANT_STARTED`

## [1.12.1] - 2026-03-26

### Fixed
- **Stale states after HA restart**: MQTT could connect and publish states before `EVENT_HOMEASSISTANT_STARTED`, when many entities are still `unavailable`/`unknown`; now `_on_homeassistant_started` also republishes config + states with fresh data once all integrations have fully loaded

## [1.12.0] - 2026-03-26

### Added
- **Proactive state publish on connect**: bridge now publishes device config and all current states immediately after MQTT connection, instead of waiting for Sber to send `config_request`/`status_request` or a state change event — fixes stale states after HA restart

## [1.11.2] - 2026-03-26

### Fixed
- **Panel detail dialog crash**: fixed persistent `Cannot read properties of undefined (reading 'callWS')` — `sber-device-table` was not receiving `hass` property from parent panel, so `sber-detail-dialog` always had `this.hass === undefined`; added `hass` to device table properties and pass-through from panel

## [1.11.1] - 2026-03-26

### Fixed
- **Entity links badges**: links now always visible in panel after HA restart — previously `_entity_links` was empty until any link was re-saved because `_load_exposed_entities` skipped links when linked entity state was not yet available
- **Panel callWS crash**: fixed `Cannot read properties of undefined (reading 'callWS')` in `sber-panel.js` and `sber-devtools.js` — `connectedCallback` called WS before HA set `hass` property; now deferred to `updated()` lifecycle

## [1.11.0] - 2026-03-26

### Added
- **Device Detail Dialog**: click entity name in device table to see full overview — Sber states table, linked entities with current values, model config (allowed_values, dependencies), HA attributes, device registry info, redefinitions
- **WS endpoint** `sber_mqtt_bridge/device_detail`: returns comprehensive data for a single entity

### Changed
- **Documentation**: full rewrite of README.md, README_ENG.md, and 7 docs files updated to v1.10.3+ — 28 categories, Sidebar Panel, DevTools, Entity Linking, typed constants, Pydantic helpers

## [1.10.3] - 2026-03-26

### Fixed
- **online status**: per-sensor-type `unknown` handling — event-based binary_sensors (motion, door, water_leak, smoke, gas) treat `unknown` as online (device reachable, no events yet); value-based sensors (temperature, humidity) and all other entities treat `unknown` as offline (prevents reporting fake 0°C/0% to Sber)

## [1.10.2] - 2026-03-26

### Fixed
- **online status**: `unknown` state now treated as online — event-based sensors (motion, water_leak, door) no longer falsely show "Offline" when they simply haven't triggered yet; only `unavailable` means truly offline

## [1.10.1] - 2026-03-26

### Fixed
- **entity linking**: links not displayed after HA restart — `EVENT_HOMEASSISTANT_STARTED` listener never fired on integration reload; now checks `hass.is_running` and reloads immediately
- **UI**: entities show yellow "Loading..." badge instead of grey "Offline" when state not yet received (prevents false alarm during startup/reload)
- **UI**: row dimming skipped for entities in loading state

## [1.10.0] - 2026-03-25

### Added
- **sber_constants.py**: new module with StrEnum typed constants — `SberValueType`, `SberFeature` (61 feature keys), `HAState`, `MqttTopicSuffix`; eliminates raw string literals, enables IDE autocomplete
- **HA Context propagation**: Sber commands now include HA `Context` in service calls — proper logbook attribution ("triggered by Sber Smart Home")
- **Echo loop prevention**: state changes caused by Sber commands detected via context ID and not re-published back (bounded set, max 200)
- **Value change diffing**: `BaseEntity.has_significant_change()` compares current Sber state with last published — skips unnecessary MQTT publishes when only irrelevant HA attributes changed; `force=True` for status_request responses

### Changed
- **All 20 device files**: migrated to Pydantic helpers (`make_state`, `make_bool_value`, `make_integer_value`, `make_enum_value`, `make_colour_value`) with `SberFeature` constants instead of inline dicts
- **sber_models.py**: `make_integer_value()` now outputs `str(value)` per Sber C2C specification
- **sber_bridge.py**: MQTT topic routing uses `MqttTopicSuffix` constants instead of hardcoded strings

## [1.9.1] - 2026-03-25

### Fixed
- **entity linking**: split battery link role — `sensor.battery` (%) → `battery` role, `binary_sensor.battery_low` (bool) → `battery_low` role; both can now be linked simultaneously
- **entity linking**: removed incorrect `moisture` → `humidity` mapping (moisture binary_sensor is a leak detector, not a humidity sensor)
- **entity linking**: added curtain, window_blind, gate, valve to linkable categories for battery/signal from separate HA entities

### Added
- **curtain**: `update_linked_data` for linked battery, battery_low, signal_strength entities; battery_percentage/battery_low_power features when battery data available
- **valve**: `update_linked_data` for linked battery, battery_low, signal_strength entities
- **simple_sensor**: `battery_low` linked role support — uses linked binary_sensor value for `battery_low_power` when available

## [1.9.0] - 2026-03-25

### Fixed
- **light**: fixed fallback color conversion in `process_cmd` — was using `ha_to_sber_hsv` instead of zero tuple, causing brightness=100 instead of 0 on malformed commands
- **light**: `light_mode` command now sends HA service call to actually switch lamp mode (was only updating local state, lamp stayed in previous mode)
- **light**: fixed docstring brightness range — was "50-1000", corrected to "100-900" per Sber spec
- **hvac_fan**: added missing `"quiet"` to `SBER_SPEED_VALUES` per Sber C2C specification; adjusted percentage thresholds for 5-speed mapping
- **climate**: fan modes now mapped through `HA_TO_SBER_FAN_MODE` dict instead of raw passthrough — ensures Sber-standard enum values (auto, low, medium, high, turbo, quiet) in `allowed_values` and state reports
- **climate**: reverse fan mode mapping in `process_cmd` — finds matching HA fan_mode for Sber enum values
- **curtain**: enforced open_state ↔ open_percentage consistency — if percentage > 0, state forced to "open"; if 0, forced to "close"

### Added
- **valve**: battery_percentage, battery_low_power, and signal_strength features — reads from HA attributes (battery, rssi, linkquality)
- **utils/signal.py**: shared `rssi_to_signal_strength()` function — extracted from duplicated code in simple_sensor.py and curtain.py
- **base_entity**: `create_allowed_values_list()` and `create_dependencies()` hook methods — unified pattern for all subclasses, eliminates `to_sber_state()` overrides
- **climate**: `HA_TO_SBER_FAN_MODE` mapping dict with 20+ HA fan mode names → Sber standard values
- **__init__**: `async_remove_entry()` — cleans up `hass.data[DOMAIN]` when last config entry is removed

### Changed
- **architecture**: all `to_sber_state()` overrides in subclasses removed — `allowed_values` and `dependencies` now injected via base class hooks
- **simple_sensor/curtain**: `_rssi_to_signal_strength` static method replaced with shared `utils.signal.rssi_to_signal_strength()`
- **linear_converter**: class-level attributes moved to `__init__` — prevents potential shared state between instances
- **config_flow**: removed emoji from Options Flow selector labels — follows HA style guide

## [1.8.1] - 2026-03-25

### Fixed
- **light**: `light_brightness` allowed_values now `min=100, max=900, step=1` per Sber spec (was `min=50, max=1000`, no step)
- **light**: dependencies key `"values"` renamed to `"value"` per Sber C2C specification
- **light**: brightness-only lamps (no color) now correctly report `light_brightness` feature
- **hvac_heater**: restored `hvac_air_flow_power` and `hvac_thermostat_mode` features per Sber spec (were incorrectly disabled)
- **hvac_radiator/boiler/underfloor**: temperature step now matches Sber spec (`step=5` instead of `step=1`)
- **kettle**: added missing `kitchen_water_level` feature per Sber spec
- **climate**: `temp_step` parameter added to `ClimateEntity.__init__` for per-category temperature step

## [1.8.0] - 2026-03-25

### Fixed
- **HVAC radiator/boiler/underfloor**: removed incorrect `hvac_work_mode` and `hvac_air_flow_power` features per Sber spec; boiler and underfloor now use `hvac_thermostat_mode` instead of `hvac_work_mode`
- **Entity linking**: `suggest_links` now returns candidates from ALL devices (not just same device), grouped by `same_device` flag; fixes linking battery/signal sensors from different HA devices
- **Link dialog**: error messages now shown instead of silent "No related entities" on WS failure
- **Type safety**: all `int()`/`float()` conversions in `process_cmd` wrapped with `_safe_int()`/`_safe_float()` — prevents crashes on malformed Sber payloads (light, curtain, climate, humidifier, tv, kettle)
- **None-safety**: `attrs.get("fan_modes", [])` → `or []` pattern across climate, light, humidifier — prevents crash when HA sends explicit `null`
- **Enum passthrough**: `hvac_work_mode`, `hvac_air_flow_direction` no longer pass unknown values to Sber/HA — only mapped enums accepted
- **sber_protocol.py**: `parse_sber_status_request` handles `devices: null` without crash
- **sber_bridge.py**: `_linked_entities` moved to BaseEntity — prevents AttributeError when linking non-sensor entities
- **sber_bridge.py**: `_handle_change_group` now merges redefinitions instead of overwriting (preserves device name)
- **Test fix**: `test_cmd_hvac_mode_valid` now sends Sber enum `"heating"` instead of HA value `"heat"`

### Added
- `BaseEntity._safe_float()` and `BaseEntity._safe_int()` static helper methods for defensive type conversion
- Class-level feature flags on ClimateEntity: `_supports_fan`, `_supports_swing`, `_supports_work_mode`, `_supports_thermostat_mode`
- `HA_TO_SBER_THERMOSTAT_MODE` / `SBER_TO_HA_THERMOSTAT_MODE` mapping dicts in climate.py
- `_create_media_player()` factory function in sber_entity_map.py (documents speaker/receiver → tv mapping)
- Link dialog: "Same device" / "Other devices" section grouping for candidates
- `docs/ENTITY_REGISTRY.md` — full entity reference
- `docs/AUDIT_REPORT.md` — Sber protocol compliance audit

## [1.7.0] - 2026-03-25

### Added
- **Entity type preview** wizard step in Options Flow — shows all exposed entities grouped by Sber device type before editing
- Entity count summary with type breakdown displayed on the init step (with `---` divider)
- Preview is the first (default) option in the settings menu
- Entities with manual type overrides marked with ✏️ in preview
- Pre-alpha warning banner in README.md and README_ENG.md

## [1.6.2] - 2026-03-24

### Changed
- **Atomic wizard endpoint** `add_device_wizard` — single WS call replaces triple add+override+links (one reload instead of three)
- **Shared utils** — `filterEntities()` and `DIALOG_STYLES_CSS` extracted to `utils.js`, used by wizard and add-dialog
- **`ws_bulk_add` deduplication** — now uses same device_id deduplication as Options Flow (light > switch priority)
- **`ws_clear_all` cleanup** — now also clears `entity_links`
- **Cleaned .gitignore** — removed duplicates, added egg-info exclusion

## [1.6.1] - 2026-03-24

### Added
- **Link Dialog** for existing devices — chain icon button in device table opens link management
- **Auto-Link All** button in toolbar dropdown — auto-links battery/signal/humidity for all exposed devices
- **Auto-republish** config when features list changes due to linked entity state update
- **Broken link detection** — HA Repairs issue for linked entities that no longer exist
- **Circular link validation** — prevents linking entity to itself or to another primary
- **Config migration v2→v3** — initializes `entity_links: {}` on upgrade
- **13 entity linking tests** — coverage for linked battery, humidity, temperature, signal, features change

### Fixed
- `suggest_links` now accepts explicit `category` from wizard (entity not yet in bridge)

## [1.6.0] - 2026-03-24

### Added
- **Entity Linking**: link auxiliary HA entities (battery, humidity, temperature, signal) to a primary Sber device
- **Auto-detection in Wizard**: Step 2 shows related entities from the same physical device with compatibility info
- **`suggest_links` WS command**: auto-detects linkable entities by shared `device_id` and `device_class`
- **`set_entity_links` WS command**: save/remove entity links with validation
- **Linked entity state tracking**: state changes from linked entities propagate to primary device
- **Device table linked badge**: shows link count (chain icon) next to device name
- **Export/import v2**: entity_links included in export payload

### Changed
- Available entities list now filters out linked entities (they won't appear in Add dialog or Wizard)
- Remove entities also cleans up associated entity links
- Sensor entities (`SimpleReadOnlySensor`) support `update_linked_data()` for battery/signal injection
- `SensorTempEntity` supports linked humidity feature
- `HumiditySensorEntity` supports linked temperature feature

## [1.5.3] - 2026-03-24

### Fixed
- **Humidifier uses `hvac_air_flow_power`** instead of `hvac_work_mode` — per Sber `hvac_humidifier` docs
- **Humidifier mode mapping**: HA modes (`Low`→`low`, `Mid`→`medium`, `High`→`high`, `Auto`→`auto`, `boost`→`turbo`, `sleep`→`quiet`)
- **Humidifier `hvac_humidity_set`** added to features — target humidity now settable from Sber
- **Humidifier `humidity` state** now sends `current_humidity` (reading), `hvac_humidity_set` sends target
- **Binary sensor `occupancy`/`presence`** mapped to `sensor_pir` (was unmapped → null)
- **Binary sensor `opening`** mapped to `sensor_door`
- **Binary sensor `water`** mapped to `sensor_water_leak`

### Changed
- Added critical Sber protocol rule to CLAUDE.md — always check docs before implementing device types

## [1.5.2] - 2026-03-24

### Fixed
- **Climate hvac_work_mode mapping**: HA modes now mapped to Sber values (`cool`→`cooling`, `heat`→`heating`, `fan_only`→`ventilation`, `dry`→`dehumidification`, `heat_cool`→`auto`). Mode `off` excluded from work modes (handled by `on_off`)
- **Climate swing_mode mapping**: HA swing modes mapped to Sber values (`off`→`no`, `both`→`rotation`)
- **Bidirectional mode mapping**: Sber commands correctly reverse-mapped back to HA modes
- **sber_name override for linked devices**: fixed name not applying when device has registry entry

## [1.5.1] - 2026-03-24

### Fixed
- **failed_unload crash**: replaced deprecated `hass.components.frontend.async_remove_panel` with proper import
- **repairs.py crash**: `bridge.stats` returns dict, not object — fixed attribute access
- **sber_name ignored for linked devices**: YAML name override now applies to devices with device registry entries
- **Disconnected status after reload**: fixed `failed_unload` state caused by panel removal error
- **DevTools clipboard crash**: fallback copy method for non-secure contexts (no `navigator.clipboard`)
- **Unacknowledged count mismatch**: acknowledged count now filters to current exposed entities only

### Changed
- **Removed `hass.data[DOMAIN]["bridge"]`**: WebSocket API now uses `entry.runtime_data` exclusively
- **WebSocket idempotent registration**: guard prevents duplicate command registration on reload
- **Public bridge API**: added `async_republish()` and `async_publish_entity_status()` — WebSocket API no longer calls private methods
- **Public feature attributes**: renamed `_extra_features`/`_removed_features` to public attributes
- **`device_class` → `original_device_class`**: fixed deprecated attribute usage in available entities list
- **Removed `hasattr(entry, "labels")`**: unnecessary compatibility guard for HA 2023.4+
- **Config flow**: added `ConfigEntry` type annotation to `async_get_options_flow`
- **DevTools payloads collapsible**: Raw Config/State sections now collapse/expand on click

## [1.5.0] - 2026-03-23

### Added
- **DevTools tab** in SPA panel for MQTT protocol debugging
- **Raw Config Payload** viewer: loads and displays the full JSON sent to Sber `up/config` topic
- **Raw State Payload** viewer: loads and displays the full JSON sent to Sber `up/status` topic
- **MQTT Message Log**: real-time ring buffer of last 50 MQTT messages (incoming/outgoing) with auto-refresh
- New WS commands: `sber_mqtt_bridge/raw_config`, `sber_mqtt_bridge/raw_states`, `sber_mqtt_bridge/message_log`, `sber_mqtt_bridge/clear_message_log`
- Copy-to-clipboard for JSON payloads
- Color-coded message direction (blue=incoming, green=outgoing)

## [1.4.1] - 2026-03-23

### Fixed
- **Light color mode mapping**: support hs/rgb/rgbw/rgbww color modes (not just xy) for Sber colour features
- **Climate turbo/quiet preset**: map Sber turbo/quiet air flow power to HA boost/sleep preset modes
- **Cover opening/closing states**: correctly map HA transitional states (opening/closing) to Sber open_state
- **Wizard "already added" badge**: entities already exposed to Sber are visually marked in the Add Device wizard

## [1.4.0] - 2026-03-23

### Added
- **Add Device Wizard** (`sber-wizard.js`): 3-step guided flow for adding devices (type selection with icon cards, entity picker with search, Salut name validation + auto-slug ID)
- **Related sensors auto-detection**: new WS command `sber_mqtt_bridge/related_sensors` finds power, current, voltage, battery, temperature sensors by shared device_id
- **Publish one device**: new WS command `sber_mqtt_bridge/publish_one_status` to sync a single entity to Sber cloud; sync button on each device row
- **Export / Import**: new WS commands `sber_mqtt_bridge/export` and `sber_mqtt_bridge/import` for backing up and restoring device configuration as JSON
- **Toast notifications** (`sber-toast.js`): lightweight popup for success/error/info feedback on all panel actions
- **Slugify utility** (`utils.js`): Cyrillic-to-Latin transliteration for generating Sber device IDs
- **Salut name validation**: regex check for 3-33 character Cyrillic device names
- **Row coloring**: device table rows tinted green (online) or red (offline)
- **Toolbar buttons**: Wizard, Export, Import added to the action bar

## [1.3.0] - 2026-03-23

### Added
- **SPA Panel decomposition**: split monolithic `sber-panel.js` into 6 component files (`sber-device-table`, `sber-status-card`, `sber-stats-grid`, `sber-add-dialog`, `sber-entity-row`, `sber-toolbar`)
- **WebSocket API — entity management**: 6 new WS commands for full device lifecycle from the panel
  - `sber_mqtt_bridge/available_entities` — list HA entities available for export
  - `sber_mqtt_bridge/add_entities` — add entities to exposed list
  - `sber_mqtt_bridge/remove_entities` — remove entities from exposed list
  - `sber_mqtt_bridge/set_override` — set/clear Sber category override per entity
  - `sber_mqtt_bridge/bulk_add` — bulk add entities by domain or all
  - `sber_mqtt_bridge/clear_all` — remove all entities and overrides
- **Device table**: sortable columns, text search/filter, bulk selection with checkboxes, inline delete and category override dropdown
- **Add dialog**: modal for selecting entities with domain grouping, search filter, multi-select, "Add All" / "Add Selected" actions
- **Toolbar**: action bar with Refresh, Re-publish, Add Devices, Bulk Actions dropdown, live connection indicator and device counter

## [1.1.0] - 2026-03-23

### Added
- **HA Repairs**: issue registry integration for missing entities, stateless entities, and persistent connection failures (`repairs.py`)
- **Feature overrides**: `sber_features_add` / `sber_features_remove` YAML options to customize Sber features per entity
- **Auto re-publish config**: bridge automatically re-publishes config when Sber asks about unknown entities
- **Persist redefinitions**: Sber room/name overrides now saved to config entry options and survive restarts
- **Features info in UI**: entity type overrides step now shows detected Sber features for each entity (read-only)
- `get_final_features_list()` method in `BaseEntity` for applying feature overrides
- `_persist_redefinitions()` in `SberBridge` for saving redefinitions to entry options
- Repair issue translations in English and Russian

## [1.0.0] - 2026-03-23

### Added
- **pydantic validation**: `build_devices_list_json()` and `build_states_list_json()` now validate output payloads via `validate_config_payload()` / `validate_status_payload()` (pydantic models from `sber_models.py`)
- **partner_meta**: new `sber_partner_meta` YAML option for arbitrary key-value metadata passed to Sber (`EntityCustomConfig.sber_partner_meta`, `BaseEntity.partner_meta`); included in `to_sber_state()` output and `SberDevice` pydantic model
- **CI/CD**: GitHub Actions workflows for HACS validation (`hacs.yml`), Hassfest (`hassfest.yml`), and full CI pipeline (`ci.yaml`) with lint, test (Python 3.13 + 3.14 matrix), hassfest, and HACS validation
- **multi-version testing**: CI test matrix runs on Python 3.13 and 3.14

## [0.9.2] - 2026-03-23

### Added
- **dependencies**: `LightEntity.to_sber_state()` now includes `dependencies` block when light supports colour mode (light_colour depends on light_mode == "colour")
- **allowed_values**: added `allowed_values` to `ValveEntity` (open_set ENUM), `CurtainEntity` (open_set ENUM + open_percentage INTEGER), `ScenarioButtonEntity` (button_event ENUM), `ClimateEntity` (hvac_temp_set INTEGER), and `HumidifierEntity` (hvac_humidity_set INTEGER)
- **nicknames**: new `sber_nicknames` YAML option for alternative voice names in Sber (`EntityCustomConfig.sber_nicknames`, `BaseEntity.nicknames`)
- **groups**: new `sber_groups` YAML option for device groups in Sber (`EntityCustomConfig.sber_groups`, `BaseEntity.groups`)
- **parent_id**: new `sber_parent_id` YAML option for hub-device hierarchy (`EntityCustomConfig.sber_parent_id`, `BaseEntity.parent_entity_id`)
- 30 new tests covering all P2 structural improvements

## [0.9.1] - 2026-03-23

### Added
- **air_pressure**: `SensorTempEntity` now reports `air_pressure` (INTEGER) when HA entity has `pressure` attribute
- **signal_strength**: `SimpleReadOnlySensor` and `CurtainEntity` now report `signal_strength` (ENUM: high/medium/low) from `rssi`, `signal_strength`, or `linkquality` HA attributes
- **tamper_alarm**: `DoorSensorEntity` and `MotionSensorEntity` now report `tamper_alarm` (BOOL) when HA entity has `tamper` attribute
- **battery_low_power**: `SimpleReadOnlySensor` now reports `battery_low_power` (BOOL, true when battery < 20%) alongside `battery_percentage`
- **child_lock**: `OnOffEntity` (relay/socket) now reports `child_lock` (BOOL) when HA entity has `child_lock` attribute
- **hvac_humidity_set**: `ClimateEntity` now supports `hvac_humidity_set` (INTEGER 0-100) for target humidity control
- **hvac_night_mode**: `ClimateEntity` and `HumidifierEntity` now support `hvac_night_mode` (BOOL) mapped to sleep/night preset modes
- 54 new tests covering all added features

## [0.9.0] - 2026-03-23

### Added
- **hvac_air_purifier**: new air purifier entity (Sber `hvac_air_purifier` category) mapped from HA `fan` with `purifier`/`air_purifier` device class
- **kettle**: new smart kettle entity (Sber `kettle` category) mapped from HA `water_heater`
- **tv**: new TV entity (Sber `tv` category) mapped from HA `media_player` — supports volume, mute, source selection
- **vacuum_cleaner**: new vacuum cleaner entity (Sber `vacuum_cleaner` category) mapped from HA `vacuum` — supports start/stop/pause/return_to_base, fan speed, battery
- **intercom**: new intercom entity (Sber `intercom` category) — available via type override only, supports on/off and read-only call features
- Added `media_player` and `vacuum` to `SUPPORTED_DOMAINS`
- Added all 5 new categories to `OVERRIDABLE_CATEGORIES` and `CATEGORY_CONSTRUCTORS`
- Fan device_class routing: `purifier`/`air_purifier` → `HvacAirPurifierEntity`, default → `HvacFanEntity`

## [0.8.0] - 2026-03-23

### Fixed
- **valve**: replaced incorrect `on_off` feature with `open_set`/`open_state` per Sber specification (ENUM open/close/stop)

### Added
- **led_strip**: new `LedStripEntity` for LED strip devices (same features as light, different category)
- **sensor_smoke**: new `SmokeSensorEntity` for smoke detector binary sensors (`smoke_state` BOOL)
- **sensor_gas**: new `GasSensorEntity` for gas leak detector binary sensors (`gas_leak_state` BOOL)
- **hvac_fan**: new `HvacFanEntity` for fan devices with `on_off` and `hvac_air_flow_power` features
- **hvac_heater**: new `HvacHeaterEntity` for space heaters (ClimateEntity subclass, 5-40 C)
- **hvac_boiler**: new `HvacBoilerEntity` for water heaters (ClimateEntity subclass, 25-80 C)
- **hvac_underfloor_heating**: new `HvacUnderfloorEntity` for underfloor heating (ClimateEntity subclass, 25-50 C)
- **battery_percentage**: optional battery level reporting for all `SimpleReadOnlySensor` subclasses
- **power/voltage/current**: optional energy monitoring features for `OnOffEntity` (relay, socket)
- **fan** and **water_heater** HA domains now supported in entity mapping
- Smoke (`device_class=smoke`) and gas (`device_class=gas`) binary sensors now supported

## [0.7.0] - 2026-03-23

### Fixed
- **pir sensor**: changed value type from BOOL to ENUM per Sber specification (`"pir"` event value)
- **doorcontact_state**: changed value type from ENUM (`"open"/"close"`) to BOOL (`true/false`) per Sber specification
- **water_leak_state**: fixed Sber key from `water_leak` to `water_leak_state` per Sber specification
- **hvac_temp_set**: removed incorrect x10 scaling — Sber sends/receives whole degrees, not tenths
- **integer_value serialization**: all `integer_value` fields now serialized as strings per Sber C2C API specification

## [0.6.0] - 2026-03-23

### Added
- **Pydantic models** for Sber protocol (`sber_models.py`): typed schemas for device config, states, commands
- Helper constructors (`make_bool_value`, `make_integer_value`, `make_enum_value`, `make_colour_value`, `make_state`)
- Optional payload validation functions (`validate_config_payload`, `validate_status_payload`)
- **Custom YAML capabilities** (`custom_capabilities.py`): per-entity overrides via `configuration.yaml`
  - `sber_type` — override Sber device category (UI Options Flow override takes precedence)
  - `sber_name` — override display name in Sber
  - `sber_room` — set room/area in Sber
- `async_setup()` in `__init__.py` for parsing YAML platform config
- `pydantic>=2.0,<3.0` added to manifest.json requirements

## [0.5.1] - 2026-03-23

### Added
- **Config entry migration v1 to v2**: adds `entity_type_overrides` to options on upgrade
- **Snapshot tests**: syrupy-based snapshot tests for Sber protocol JSON responses
- **Strict mypy config**: enabled `disallow_untyped_defs`, `warn_return_any` and other strict checks

## [0.5.0] - 2026-03-23

### Added
- **Entity type overrides**: override Sber device category per entity in Options Flow
  (e.g. expose `switch.kitchen` as `light` in Sber)
- **Options Flow menu**: reorganized as menu with "Entity selection" and "Entity type overrides"
- **Gate/garage door support**: new `GateEntity` for cover entities with `gate`/`garage_door` device class
- **Label-based entity filtering**: select entities by HA labels in Options Flow
- **Extended diagnostics**: per-entity details (sber_category, features, state, linked device)
- `CATEGORY_CONSTRUCTORS` mapping for direct Sber category to entity class resolution
- `OVERRIDABLE_CATEGORIES` list of categories available for user overrides
- `CONF_ENTITY_TYPE_OVERRIDES` option key for storing overrides

### Changed
- `create_sber_entity()` now accepts optional `sber_category` parameter for overrides
- `_create_cover()` now maps `gate`/`garage_door` device classes to `GateEntity`
- Options Flow `init` step is now a menu instead of a form
- Entity selection steps preserve `entity_type_overrides` across options changes

## [0.4.1] - 2026-03-23

### Added
- "Remove ALL entities" option in Options Flow — clear list in one click

### Fixed
- Device deduplication: bulk add now keeps only the richest entity per
  physical device (light > switch for same device_id)
- Warning logged when multiple entities share the same device_id
- Manifest.json stray characters removed
- Entity mapping debug logging (domain → Sber category with device_class)

## [0.4.0] - 2026-03-23

### Added
- Bulk entity selection in Options Flow: "Add ALL supported entities" one-click
- Domain-based selection: "Add all by domain" with entity counts per domain
- Three selection modes: manual, by domain, add all

### Fixed
- **CRITICAL**: Infinite loop — `change_group_device_request` no longer triggers config re-publish
- **CRITICAL**: Humidity sensor sent value x10 (550 instead of 55%) — now plain INTEGER(0-100) per Sber docs
- **CRITICAL**: Batch commands triggered N separate MQTT publishes — now batched into one
- Curtain `open_state` ENUM reverted to correct `"close"` (not `"closed"`) per Sber protocol
- TOCTOU race: `AttributeError` caught when `_mqtt_client` becomes None during publish
- `acknowledged_entities` and `_redefinitions` pruned on entity reload (memory leak fix)
- Humidifier docstring corrected: "plain percentage" not "divided by 10"
- HSV color values clamped to min 0 to prevent negative values from Sber

## [0.3.1] - 2026-03-23

### Fixed
- Debounce timer not cancelled on bridge teardown (orphaned task prevention)
- `_handle_change_group` / `_handle_rename_device` variable naming (`device_id` → `entity_id`)
- `humidifier.set_humidity` uses `round()` instead of `int()` for correct rounding
- LightEntity: removed optimistic state mutation from `process_cmd`
- LightEntity: added missing `online` key in `to_sber_current_state`
- LightEntity: `ha_state["attributes"]` → `.get("attributes", {})` (KeyError prevention)
- CurtainEntity: same `.get()` fix for attributes access
- SSL `create_default_context()` offloaded to executor (no longer blocks event loop)
- Startup ordering: `EVENT_HOMEASSISTANT_STARTED` listener for entity registry reload

### Added
- `BridgeStats` dataclass with connection health metrics (uptime, counters, reconnects)
- Device acknowledgment tracking (entities confirmed by Sber via status_request/command)
- State publish debounce (100ms coalescing for burst HA state changes)
- MQTT payload size guard (1MB max, prevents DoS)
- Enhanced debug logging: all MQTT messages, Sber commands, HA service calls, errors

### Changed
- `_unsub_listeners` split into `_unsub_state_listeners` + `_unsub_lifecycle_listeners`
- Diagnostics now shows `stats` and `unacknowledged_entities`

### Removed
- Dead code: `EntityContext` class, `device_data.py`, `CONF_SBER_HTTP_ENDPOINT`
- Redundant `to_sber_state` override in `CurtainEntity`

## [0.3.0] - 2026-03-23

### Added
- `OnOffEntity` base class for relay, valve, socket (eliminates duplication)
- `SimpleReadOnlySensor` base class for 5 sensor types (eliminates duplication)
- `_is_online` property in `BaseEntity` (replaces duplicated inline checks)
- Device registry linking in `_load_exposed_entities` — entities with device_id now appear in Sber
- HA state event subscription at startup (independent of MQTT connectivity)
- `category` parameter in `RelayEntity`, `ClimateEntity`, `CurtainEntity` for clean subclassing
- Acknowledgments and legal trademark notice in README
- Migrated to GitHub: `dzerik/sber-mqtt-bridge`

### Fixed
- **CRITICAL**: Entities with `device_id` silently skipped from Sber (link_device never called)
- **CRITICAL**: `CurtainEntity.to_sber_current_state` returned `None` instead of `dict` on unavailable
- **CRITICAL**: `LightEntity` `int(None)` crash on missing `integer_value` in color temp command
- **CRITICAL**: `LightEntity` state key `colour_temperature` mismatched registered feature `light_colour_temp`
- **CRITICAL**: `CurtainEntity` `elif open_set` silently dropped command when `cover_position` was present
- Curtain open_state ENUM value `"close"` corrected to `"closed"`
- ScenarioButton spurious `double_click` on `unavailable`/`unknown` states
- Climate hardcoded 22°C fallback on missing `integer_value` — now skips command
- Humidifier `set_mode` with `None` mode guard
- Race condition: `_connected` and `_mqtt_client` now reset atomically on disconnect
- Dead code `ConfigEntryNotReady` try/except removed (bridge uses background reconnect)
- HA events no longer lost during MQTT reconnect window

### Changed
- `process_state_change` default implementation moved to `BaseEntity` (removed from 6 subclasses)
- Logger convention: `logger` renamed to `_LOGGER` in all 17 device files
- `SocketEntity`, `WindowBlindEntity`, `HvacRadiatorEntity` use proper `super().__init__()` chain
- `HvacRadiatorEntity` no longer duplicates `ClimateEntity.__init__` body
- Removed dead code: `CONF_SBER_HTTP_ENDPOINT`, `SBER_HTTP_ENDPOINT_DEFAULT`
- `LightEntity` added `from __future__ import annotations`
- jscpd duplication reduced: 13 clones → 9 (4.34% → 3.38%)

### Removed
- Wrong-project audit file `docs/audit/audit-02-architecture.md` (described xiaomi_miio)

## [0.2.0] - 2026-03-23

### Added
- Reauthentication flow (`async_step_reauth`) for Silver quality scale
- 153 new unit tests (219 total), achieving 82% code coverage
- Exponential backoff for MQTT reconnection (5s → 300s max)
- Enum validation for climate commands (fan_mode, swing_mode, hvac_mode)
- Comprehensive docstrings for all public classes, methods, constants
- `from __future__ import annotations` in all modules
- README.md rewritten for HACS integration (installation, config, troubleshooting)
- CHANGELOG.md in Keep a Changelog format

### Fixed
- TLS verify configurable via Config Flow (was hardcoded CERT_NONE)
- JSON parse error handling in `parse_sber_command`
- LightEntity shared class-level converters causing cross-instance bugs
- BaseEntity mutable default `attributes: dict = {}` moved to `__init__`
- Deprecated entity_registry API updated to `er.async_get(hass)`
- LightEntity `process_cmd` returns `[]` instead of `None`
- LightEntity `process_cmd` UnboundLocalError on empty states
- Falsy value filter in `build_devices_list_json`
- `assert` replaced with `raise RuntimeError/ValueError`
- `callable` → `Callable` type hint
- Typo `unuque_id` → `unique_id` in device_data.py
- All 24 ruff lint issues resolved (0 remaining)
- ruff format applied to all files
- Swap-on-replace pattern for entity reload (race condition fix)
- .gitignore extended with .env, *.pem, secrets.yaml

### Changed
- HA Quality Scale: Bronze → **Silver** (all 28 rules done/exempt)
- aiomqtt dependency pinned to `>=2.0,<3.0`
- Command payload logging moved from INFO to DEBUG
- BaseEntity uses ABC with 3 `@abstractmethod`s

## [0.1.0] - 2026-03-23

### Added
- **HACS custom integration** `sber_mqtt_bridge` — native HA integration replacing standalone addon
- Config Flow UI for Sber MQTT credentials with SSL verification option
- Options Flow with EntitySelector for choosing which HA entities to expose to Sber
- SberBridge core: async MQTT via aiomqtt + HA event bus integration
- Sber protocol serialization (device config, state lists, command parsing)
- Entity factory mapping 11 HA domains to 15 Sber device types
- 15 device classes migrated to BaseEntity OOP system:
  - LightEntity (brightness, color, color_temp)
  - ClimateEntity, HvacRadiatorEntity (HVAC)
  - CurtainEntity, WindowBlindEntity (covers)
  - RelayEntity, SocketEntity (switches)
  - ScenarioButtonEntity (input_boolean)
  - SensorTempEntity, HumiditySensorEntity (sensors)
  - MotionSensorEntity, DoorSensorEntity, WaterLeakSensorEntity (binary sensors)
  - ValveEntity, HumidifierEntity (new Sber categories)
- Diagnostics support with credential redaction
- Translations: English and Russian
- quality_scale.yaml targeting Silver tier
- 66 unit tests (config flow, bridge, protocol, entity map)
- GitHub Actions CI/CD (ruff, pytest, hassfest, HACS validation, release)
- Pre-commit hooks (ruff, codespell)
- GitHub community files (CONTRIBUTING, CODE_OF_CONDUCT, SECURITY, issue templates)
- Comprehensive docstrings for all public classes, methods, and constants

### Fixed
- TLS certificate verification is now configurable (was hardcoded CERT_NONE)
- JSON parse error handling in Sber command parser (was crashing MQTT loop)
- LightEntity shared class-level converters (was causing cross-instance bugs)
- BaseEntity mutable default `attributes: dict = {}` moved to `__init__`
- Deprecated entity_registry API updated to modern `er.async_get(hass)`
- LightEntity `process_cmd` returns `[]` instead of `None`
- Falsy value filter in `build_devices_list_json` uses `is not None` instead of truthiness

### Changed
- BaseEntity now uses ABC with all 3 abstract methods (`process_cmd`, `to_sber_current_state`, `process_state_change`)
- `assert` statements replaced with proper `raise RuntimeError/ValueError`
- Command payload logging changed from INFO to DEBUG level

## [1.2.0] - 2026-03-23

### Changed
- **OOP migration complete**: All 15 device types migrated from old dict-based system to BaseEntity
- All old REST API command handlers removed (`ha_OnOff`, `ha_climate`, etc.)
- `handle_event_new` removed — all state changes go through `_process_event`
- DevicesConverter simplified to single `create_by_entities_store` method

### Added
- 6 new device types: SocketEntity, DoorSensorEntity, WaterLeakSensorEntity, WindowBlindEntity, ValveEntity, HumidifierEntity
- Factory functions with device_class routing for sensor, binary_sensor, switch, cover, climate domains
- 96 unit tests for all device classes

### Removed
- Old device system code from `sber-gate.py` and `web_socket_handler.py`
- `shutter.py`, `pressure_sensor.py` (replaced/unsupported)
- All `upd_*` methods from `DevicesConverter`

## [1.1.0] - 2025-09-23

### Changed
- Refactored service classes into separate modules
- New device management system based on BaseEntity OOP
- Light entity: added color and color temperature modes

### Added
- LightEntity and CurtainEntity with full OOP implementation

[Unreleased]: https://github.com/dzerik/sber-mqtt-bridge/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/dzerik/sber-mqtt-bridge/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/dzerik/sber-mqtt-bridge/releases/tag/v0.1.0
[1.2.0]: https://github.com/dzerik/sber-mqtt-bridge/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/dzerik/sber-mqtt-bridge/releases/tag/v1.1.0
