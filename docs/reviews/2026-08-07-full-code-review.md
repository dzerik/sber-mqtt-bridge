# Полный code review — 2026-08-07

**Ветка:** `review/2026-08-07-full-code-review` (срез после v1.42.0, коммит `d39ac10`)

## Методология

Конкурентный двойной анализ: **8 измерений × 2 независимых ревьюера** (проход A — систематический обход файлов; проход B — сценарно-поточный анализ по жизненным циклам и потокам данных; ревьюеры не знали о существовании друг друга). Затем на каждое измерение — merge-судья: сопоставление находок, дедупликация, **верификация всех уникальных находок чтением реального кода**, отклонение неподтверждённых. Инструментально: radon (CC/MI), покрытие pytest-cov, grep-аудиты. Итого 24 агента, ~2.8M токенов, 726 обращений к инструментам.

## Сводка

| Измерение | Оценка | Консенсус | Уник. (подтв.) | Опровергнуто |
|---|---|---|---|---|
| Безопасность | **C** | 6 | 3 | 4 |
| Гонки состояний и async-корректность | **C** | 8 | 4 | 0 |
| Обработка ошибок и устойчивость | **C** | 8 | 6 | 0 |
| Архитектура и SOLID | **B** | 12 | 3 | 1 |
| Качество кода и DRY | **B** | 11 | 9 | 0 |
| Сложность | **B** | 6 | 7 | 0 |
| Качество тестов | **B** | 10 | 3 | 1 |
| Frontend (www/, LitElement SPA) | **B** | 9 | 5 | 0 |
| **Итого** | | **70** | **40** | **6** |

Подтверждённых находок: **110**, из них **4 critical**.

## Критические находки (сводно)

1. **Один некорректный inbound-payload от Sber навсегда убивает MQTT reconnect-loop: нет exception-барьера вокруг обработки сообщений, а run() ловит только MqttError/OSError/ValueError/RuntimeError.** — `custom_components/sber_mqtt_bridge/mqtt_client_service.py:170` (Обработка ошибок и устойчивость; консенсус обоих ревьюеров)
2. **Неожиданное исключение из обработчика сообщений навсегда и молча убивает MQTT reconnect-loop; последующий async_stop ре-рейзит его и ломает unload** — `custom_components/sber_mqtt_bridge/mqtt_client_service.py:170` (Гонки состояний и async-корректность; консенсус обоих ревьюеров)
3. **Type-confusion во входящем Sber-payload даёт AttributeError, который не ловится в reconnect-цикле — MQTT-луп умирает навсегда, мост молча уходит в оффлайн до перезапуска HA.** — `custom_components/sber_mqtt_bridge/mqtt_client_service.py:170` (Безопасность; консенсус обоих ревьюеров)
4. **Ни одна из 40+ WebSocket-команд не помечена `@websocket_api.require_admin` — любой аутентифицированный не-админ HA получает полный контроль над мостом, вплоть до эскалации привилегий через inject.** — `custom_components/sber_mqtt_bridge/websocket_api/__init__.py:192` (Безопасность; консенсус обоих ревьюеров)

## Безопасность — оценка C

Базовая гигиена измерения хорошая и подтверждена чтением: нет eval/exec/pickle/yaml.load, панель полностью на Lit-шаблонах без innerHTML/unsafeHTML (XSS-стоков нет), TLS-контекст — системный `ssl.create_default_context()` с проверкой цепочки и hostname и явным WARN при отключении, entity_id в WS-схемах валидируются через `cv.entity_id`, есть guard размера MQTT-payload и per-device pydantic-валидация исходящего конфига. Но два системных провала перевешивают. Первый — авторизация: ни одна из 40 WS-команд не помечена `require_admin` (регистрация в цикле, websocket_api/__init__.py:192), декораторы `requires_bridge`/`requires_entry` прав не проверяют, панель зарегистрирована с `require_admin=False`; в результате любой не-админ HA может публиковать произвольный JSON в облако Sber, отключить проверку TLS-сертификата, стереть/подменить конфигурацию, читать весь MQTT-трафик и через `inject_sber_message` вызывать `hass.services.async_call` с безличным `Context()` — то есть в обход per-user entity permissions. Второй — доверие к недоверенному вводу: входящий payload не проверяется структурно (воспроизведено: top-level не-объект и не-dict значения в `devices` дают AttributeError), а `run()` ловит слишком узкий набор исключений и таск создан без done-callback, поэтому одно битое сообщение навсегда убивает MQTT-луп без реконнекта; сюда же — логирование payload до guard'а по размеру, RecursionError на глубоком JSON и запись сырых значений из облака и из WS (`update_settings`, `import`, `change_group`/`rename_device`) в персистентные options без схем, вплоть до невозможности загрузить config entry. Эксплуатируемых RCE/XSS/инъекций нет, path traversal и ReDoS не обнаружены.

### Находки (9)

#### [CRITICAL] Ни одна из 40+ WebSocket-команд не помечена `@websocket_api.require_admin` — любой аутентифицированный не-админ HA получает полный контроль над мостом, вплоть до эскалации привилегий через inject.

- **Место:** `custom_components/sber_mqtt_bridge/websocket_api/__init__.py:192`
- **Источник:** консенсус обоих ревьюеров

Проверено чтением: в `_COMMANDS` (__init__.py:120-174) перечислены все 40 хендлеров, регистрация в цикле на строке 192 — без каких-либо проверок прав. Grep по всему `custom_components/` даёт единственное совпадение `require_admin=False` (__init__.py:111, регистрация панели). Декораторы `requires_bridge`/`requires_entry` (_common.py:83-160) проверяют только наличие bridge/entry, не пользователя. В HA `async_register_command` по умолчанию доступен ЛЮБОМУ залогиненному пользователю, включая non-admin с ограниченной policy. Подтверждённые последствия: (1) `ws_inject_sber_message` (replay.py:43) → `bridge.async_inject_sber_message` (sber_bridge.py:508-561) → `_mqtt_dispatch` → `SberCommandDispatcher` → `_call_ha_service` (command_dispatcher.py:240-250) вызывает `hass.services.async_call(..., context=Context())` — контекст создаётся в handle_command (command_dispatcher.py:107) без `user_id`, то есть per-user entity-permissions не проверяются вовсе → non-admin управляет любой экспонированной сущностью (включая lock.*); (2) `ws_send_raw_config`/`ws_send_raw_state` (raw.py:66-90) — публикация произвольного JSON в облако Sber от имени партнёрского аккаунта; (3) `ws_update_settings` (settings.py:54) — отключение `sber_verify_ssl`; (4) `ws_clear_all`/`ws_remove_entities` (entities.py) и `ws_import` (io_export.py:63) — уничтожение/подмена конфигурации интеграции; (5) `ws_message_log`/`ws_subscribe_messages` (log.py:24,58) и `ws_device_detail` — чтение всего MQTT-трафика и состояний в обход permission-фильтрации HA.

**Рекомендация:** Навесить `@websocket_api.require_admin` на все мутирующие и DevTools-команды (raw, replay, settings, entities, links, io_export, message_log); панель поставить `require_admin=True` либо явно разделить read-only и admin-команды. В `_call_ha_service` для WS-инициированных путей передавать `Context(user_id=connection.user.id)`.

#### [CRITICAL] Type-confusion во входящем Sber-payload даёт AttributeError, который не ловится в reconnect-цикле — MQTT-луп умирает навсегда, мост молча уходит в оффлайн до перезапуска HA.

- **Место:** `custom_components/sber_mqtt_bridge/mqtt_client_service.py:170`
- **Источник:** консенсус обоих ревьюеров

Воспроизведено локально: `parse_sber_command(b'[1,2,3]')` → `AttributeError: 'list' object has no attribute 'get'` (sber_protocol.py:265 — `json.loads` внутри try с `(JSONDecodeError, TypeError)`, а `data.get("devices")` на строке 271 уже вне try). Аналогично `{"devices":{"light.known":1}}` для известной сущности → `cmd_data.get("states", [])` (command_dispatcher.py:190 и devices/base_entity.py:764) → AttributeError; `handle_change_group`/`handle_rename_device`/`handle_global_config` (command_dispatcher.py:357,384,404) ловят только `json.JSONDecodeError`. Путь распространения проверен: `_handle_mqtt_message` (sber_bridge.py:917-950, без try) → `_consume_messages` (mqtt_client_service.py:191-196) → `run()`, где ловятся только `aiomqtt.MqttError`, `CancelledError` и `(OSError, ValueError, RuntimeError)` (строки 165-172) → `_mqtt_connection_loop` имеет лишь try/finally (sber_bridge.py:762-767) → таск создан голым `asyncio.create_task` (sber_bridge.py:639), в отличие от `_create_safe_task` с done-callback (sber_bridge.py:397-427). Итог: `self._running` остаётся True, реконнекта нет, статус не меняется, ошибка всплывает лишь как asyncio 'Task exception was never retrieved'. В tests/hacs/test_negative_scenarios.py:195-251 покрыты только неверные типы `devices`, но не top-level не-объект и не не-dict значения внутри `devices`.

**Рекомендация:** Обернуть обработку одного сообщения в `try/except Exception` (одно сообщение не должно ронять транспорт), добавить структурную валидацию (`isinstance(data, dict)`, `devices: dict[str, dict]`, `states: list[dict]`) в `parse_sber_command`/`process_cmd`, и создавать `_connection_task` через `_create_safe_task`.

#### [Major] SSL-контекст создаётся один раз до цикла реконнекта — обратное включение `verify_ssl` из панели никогда не применяется, пользователь остаётся с CERT_NONE, считая защиту восстановленной.

- **Место:** `custom_components/sber_mqtt_bridge/mqtt_client_service.py:156`
- **Источник:** консенсус обоих ревьюеров

Проверено: `run()` вычисляет `ssl_context = await hass.async_add_executor_job(create_ssl_context, self._credentials.verify_ssl)` на строке 156 — ДО `while self._running`, и переиспользует его в `_build_client(ssl_context)` (строка 183) на каждом переподключении. `update_verify_ssl` (строка 135) лишь пересобирает dataclass `SberMqttCredentials`, чей `verify_ssl` после старта нигде не читается. Путь из UI: `ws_update_settings` (settings.py:65-69) → `async_update_entry` + `bridge.apply_settings` (sber_bridge.py:467-489) без `async_reload`; grep по `add_update_listener` пуст — update-listener не зарегистрирован, `OptionsFlowWithReload` (config_flow.py:333) перезагружает только при завершении Options Flow, а этих настроек в нём нет. Docstring `apply_settings` («verify_ssl вступает в силу при следующем реконнекте») фактически неверен. При выключенной проверке контекст — `check_hostname=False` + `CERT_NONE` (config_flow.py:116-117), то есть MITM-окно на MQTT-сессию с кредами остаётся открытым, а UI показывает verify SSL = on.

**Рекомендация:** Пересоздавать `ssl_context` внутри цикла перед каждым `_build_client` (или в `update_verify_ssl`), либо форсировать `hass.config_entries.async_reload` при изменении `sber_verify_ssl`; поправить docstring.

#### [Major] `update_settings` и `import` пишут в `entry.options` произвольные значения без валидации типов/диапазонов — не-админ может заглушить приём команд или заблокировать загрузку config entry.

- **Место:** `custom_components/sber_mqtt_bridge/websocket_api/settings.py:63`
- **Источник:** консенсус обоих ревьюеров

Проверено: `ws_update_settings` фильтрует только имена ключей (`k in SETTINGS_DEFAULTS`, settings.py:63), схема — `vol.Required("settings"): dict` без валидаторов значений; `ws_import` (io_export.py:58-82) валидирует лишь `dict` верхнего уровня и кладёт произвольные `exposed_entities`/`type_overrides`/`redefinitions`/`entity_links` в options с последующим `async_reload`. Далее `_load_settings_from_options` (sber_bridge.py:449-465) делает `int(...)`/`float(...)`: (a) `{"max_mqtt_payload_size": "abc"}` уже персистится `async_update_entry` (settings.py:65), затем `apply_settings` бросает ValueError, а при следующем старте HA тот же `int()` падает в `SberBridge.__init__` → `async_setup_entry` (__init__.py:85) не проходит, entry не грузится; этих ключей нет в Options Flow (grep по config_flow.py пуст), а панельные команды используют `async_loaded_entries` (_common.py:66) → незагруженный entry чинится только правкой `.storage` или удалением интеграции; (b) `max_mqtt_payload_size: 0` → условие `len(payload) > 0` (sber_bridge.py:932) отбрасывает КАЖДОЕ входящее сообщение — мост молча перестаёт принимать команды Sber; (c) `message_log_size: -1` → `deque(maxlen=-1)` ValueError в `MessageLogger.resize` (message_logger.py:56); (d) `reconnect_interval_min: 0` → после следующего успешного коннекта `self._reconnect_interval = 0` и `min(0*2, max) == 0` (mqtt_client_service.py:212-213) → плотный цикл переподключений к брокеру Sber. Клиентская валидация есть только в HTML-инпутах панели и обходится прямым WS-вызовом.

**Рекомендация:** Описать per-key `vol.Schema` с `vol.Coerce(int/float)` + `vol.Range(...)` для `update_settings` и типизированную схему для `import` (list[str] / dict[str,str] / dict[str,dict]); отклонять запрос ДО `async_update_entry`.

#### [Major] Входящий MQTT-payload декодируется целиком и кладётся в кольцевые буферы DevTools ДО проверки лимита размера — удалённая сторона может держать десятки-сотни МБ в памяти HA.

- **Место:** `custom_components/sber_mqtt_bridge/sber_bridge.py:929`
- **Источник:** консенсус обоих ревьюеров

Проверено по строкам: `decoded = payload.decode(...)` (sber_bridge.py:928) и `self._log_message("in", topic, decoded)` (929) выполняются раньше guard'а `len(payload) > self._max_payload_size` (932-939), то есть сообщение, признанное «too large» и отброшенное, уже сохранено целиком. Усечение `[:500]` применяется только к не-bytes ветке. `MessageLogger.log` (message_logger.py:58-78) хранит payload без обрезки в deque на `message_log_size` записей (дефолт 50, const.py:89 — ограничение по числу записей, не по байтам) и синхронно рассылает копию всем WS-подписчикам (log.py:70-75), то есть гигантский payload ещё и уезжает в браузер. Тот же паттерн у `_open_command_trace` — весь распарсенный `devices` идёт в `trace_collector.begin(payload=devices)` (command_dispatcher.py:159-169). MQTT допускает payload до 256 МБ, так что 50 × N МБ остаются в RSS.

**Рекомендация:** Перенести проверку `_max_payload_size` в самое начало `_handle_mqtt_message` (до decode и лога), усекать сохраняемый payload в `MessageLogger.log` и трейсах до фиксированного лимита (4-8 КБ) с пометкой `truncated`, ограничить суммарный байтовый объём буферов.

#### [Major] `change_group`/`rename_device` из облака пишут непроверенные значения любого типа прямо в персистентный store редефиниций, минуя существующий санитайзер.

- **Место:** `custom_components/sber_mqtt_bridge/command_dispatcher.py:371`
- **Источник:** один ревьюер, подтверждено судьёй чтением кода

Подтверждено чтением: `handle_change_group` (command_dispatcher.py:367-374) кладёт `data.get("home")` / `data.get("room")` в `bridge._redef_store.raw[entity_id]`, а `handle_rename_device` (command_dispatcher.py:393-398) — `data.get("new_name")` в `redef["name"]`, без проверки типа, длины и без проверки, что `entity_id` вообще известен мосту. `RedefinitionsStore.raw` — живой dict (redefinitions_store.py:50-53), `_flush` персистит его в `ConfigEntry.options` (redefinitions_store.py:106-118). Рядом лежит правильный путь `RedefinitionsStore.async_update` (строки 84-96), который делает `strip()` и отбрасывает не-строки — он используется только WS-командой. Последствия: `{"device_id":"light.kitchen","new_name":{"$":1}}` → `redef.get("name")` истинно → `device_data["name"] = {...}` (sber_protocol.py:158-159) → `validate_device` отбраковывает устройство и оно исчезает из конфигурации Sber (sber_protocol.py:183-191) с одним WARN. Прунинг стойких мусорных ключей происходит только при следующей загрузке entity-лоадером (entity_registry.py:129), так что мегабайтные значения живут в `.storage` до перезагрузки.

**Рекомендация:** Валидировать вход (`isinstance(new_name, str)`, лимит длины ~128, `entity_id in bridge._entities`) и переиспользовать `RedefinitionsStore.async_update` вместо прямой записи в `.raw`.

#### [Minor] В diagnostics редактируется только пароль — Sber-логин (он же MQTT username и корневой топик) выгружается открытым текстом и виден не-админам в message log.

- **Место:** `custom_components/sber_mqtt_bridge/diagnostics.py:13`
- **Источник:** консенсус обоих ревьюеров

Проверено: `TO_REDACT = {CONF_SBER_PASSWORD}` (diagnostics.py:13), при этом `entry_data` отдаётся через `async_redact_data(dict(entry.data), TO_REDACT)` и `options` — как есть (diagnostics.py:54-55). `CONF_SBER_LOGIN` лежит в `entry.data` и формирует корневой топик `sberdevices/v1/{login}` (sber_bridge.py:162), который попадает во все записи message log (`_log_message`, sber_bridge.py:929/506) и отдаётся любому аутентифицированному пользователю через `sber_mqtt_bridge/message_log` (log.py:24). Diagnostics-файлы пользователи регулярно прикладывают к публичным GitHub-issue.

**Рекомендация:** Добавить `CONF_SBER_LOGIN` (и при желании `CONF_SBER_BROKER`) в `TO_REDACT`; в message log маскировать сегмент логина в топике (`sberdevices/v1/***/...`).

#### [Minor] Глубоко вложенный JSON во входящем payload вызывает RecursionError, который трактуется как транспортная ошибка — разрыв соединения и цикл реконнектов при повторной доставке.

- **Место:** `custom_components/sber_mqtt_bridge/sber_protocol.py:265`
- **Источник:** один ревьюер, подтверждено судьёй чтением кода

Проверено локально на Python 3.14.2: `json.loads(b'{"devices":' + b'['*100000 + b']'*100000 + b'}')` → `RecursionError` (~200 КБ, то есть в пределах дефолтного `max_mqtt_payload_size = 1_000_000`, const.py:90); при 5000 уровнях исключения ещё нет. В `parse_sber_command` (sber_protocol.py:264-266) ловятся только `(json.JSONDecodeError, TypeError)`, поэтому `RecursionError` (подкласс `RuntimeError`) всплывает до `run()` и попадает в ветку `except (OSError, ValueError, RuntimeError)` (mqtt_client_service.py:170) → `_after_error` → разрыв сессии и реконнект с backoff до 300 с. При retained-сообщении или QoS1-редоставке после resubscribe цикл повторяется. Это тот же корень, что и критическая находка по type-confusion (нет структурной валидации входящих данных), но с иным исходом — не смерть лупа, а деградация связи, поэтому severity ниже.

**Рекомендация:** Отклонять payload с чрезмерной вложенностью до `json.loads` (дешёвая проверка числа открывающих скобок) и расширить except до `(json.JSONDecodeError, TypeError, ValueError, RecursionError)` с возвратом пустого результата.

#### [Minor] `ws_set_entity_links` принимает `links` как нетипизированный dict — значения не валидируются как entity_id, в отличие от всех соседних команд.

- **Место:** `custom_components/sber_mqtt_bridge/websocket_api/links.py:33`
- **Источник:** один ревьюер, подтверждено судьёй чтением кода

Подтверждено: схема объявляет `vol.Required("links"): dict` (links.py:33), тогда как рядом для `entity_id` используется `WS_ENTITY_ID = vol.All(cv.string, cv.entity_id)`, и docstring этого валидатора прямо говорит, что он нужен, «чтобы не отравить entry.options» (_common.py:24-30). Любые строки или вложенные структуры попадают в `all_links[entity_id]` и персистятся в `CONF_ENTITY_LINKS` (links.py:66-74), после чего используются как entity_id при разрешении связей и подписке на state-события. Практический вред ограничен (сломанные ссылки, мусор в options), эксплуатации за пределами уже описанного отсутствия require_admin нет.

**Рекомендация:** Заменить схему на `vol.Schema({cv.string: WS_ENTITY_ID})` и отклонять неизвестные роли.

### Опровергнутые заявки ревьюеров

- ~~Отчёт A/B: XSS во фронтенд-панели (www/)~~ — Перепроверено grep'ом по `custom_components/sber_mqtt_bridge/www/` (исключая vendor/lit.js) по `innerHTML|unsafeHTML|insertAdjacentHTML|document.write|eval(|new Function` — ноль совпадений. Оба ревьюера сами пометили это как info/позитив; сток отсутствует, находкой не является.
- ~~Отчёт A/B: опасные конструкции в Python (eval/exec/pickle/yaml.load/subprocess)~~ — Перепроверено grep'ом по `custom_components/sber_mqtt_bridge/**/*.py` — ноль совпадений по `eval(`, `exec(`, `pickle`, `yaml.load`, `os.system`, `subprocess`. Наблюдение верное, но это не дефект — в находки не включено.
- ~~Отчёт A: TLS-настройки как отдельная находка (config_flow.py:109)~~ — Код корректен: `ssl.create_default_context()` даёт CERT_REQUIRED + check_hostname=True (config_flow.py:109), отключение сопровождается WARN (111-115), контекст создаётся в executor. Реальный дефект — только неприменение изменённого флага, он уже учтён в consensus-находке по mqtt_client_service.py:156; дублирующая info-запись отброшена.
- ~~Отчёт A: `_max_payload_size` не защищает от JSON-бомбы, потому что 400 КБ «легко проходит лимит»~~ — Уточнение по фактам, а не полное опровержение: замер показал, что RecursionError требует ~100 000 уровней вложенности (~200 КБ), а при 5 000 уровнях (~10 КБ) исключения нет. То есть атака возможна только при дефолтном лимите 1 МБ и не работает, если пользователь снизил `max_mqtt_payload_size`. Severity понижен с major до minor.

## Гонки состояний и async-корректность — оценка C

Async-дисциплина в целом зрелая: атомарный swap-on-replace при перезагрузке сущностей, _create_safe_task с логированием, ownership-проверка слота в _delayed_confirm (sber_bridge.py:1014), cancel-before-rearm в AckAudit.schedule_audit, SSL-контекст в executor. Но подтверждён один критический дефект: реконнект-цикл run() ловит лишь узкий список исключений, а data.get("devices") в parse_sber_command стоит вне try и dispatcher не валидирует cmd_data — один кривой (но JSON-валидный) payload из облака молча и навсегда убивает MQTT-задачу (голый create_task без done-callback скрывает исключение), а затем ломает и unload entry. Плюс три подтверждённых major: классический lost-update из-за mark_state_published после await publish (быстрый toggle теряется до следующего изменения), stale fallback-таймер ReconnectAckGuard, досрочно открывающий окно для stale-команд Sber при флапе соединения, и debounce-таймер RedefinitionsStore, переживающий unload и затирающий/теряющий пользовательские redefinitions. Системная тема — незакрытый lifecycle: async_stop/disconnect не гасит confirm-задачи, redefinitions-персист и ack-audit-таймер; hot-reload молча дропает pending-публикации. Каждая проблема точечно исправима, архитектурной перестройки не требуется.

### Находки (12)

#### [CRITICAL] Неожиданное исключение из обработчика сообщений навсегда и молча убивает MQTT reconnect-loop; последующий async_stop ре-рейзит его и ломает unload

- **Место:** `custom_components/sber_mqtt_bridge/mqtt_client_service.py:170`
- **Источник:** консенсус обоих ревьюеров

run() ловит только MqttError/CancelledError/OSError/ValueError/RuntimeError; hooks.on_message вызывается в _consume_messages без blanket-except. Подтверждённые внешние триггеры AttributeError: (1) JSON-корень не-dict (например "[]") на down/commands — sber_protocol.py:271 вызывает data.get("devices") ВНЕ try; (2) {"devices": {"<known_id>": null}} — command_dispatcher.py:190 cmd_data.get("states") на None (docstring process_cmd утверждает «dispatcher rejects None before reaching here» — это неправда) и :153 в grace-ветке; (3) не-dict корень на change_group — command_dispatcher.py:367 data.get("device_id"). Исключение вылетает из run(); сброс _client/_connected стоит после while (строки 174-175), а не в finally. Задача создана голым asyncio.create_task (sber_bridge.py:639) без done-callback, ссылка удерживается — «Task exception was never retrieved» не логируется, мост мёртв до перезапуска HA без единой строки в логе. Бонус: async_stop (sber_bridge.py:669-672) подавляет только CancelledError → сохранённый AttributeError ре-рейзится, async_unload_entry падает, reload ломается. Любой баг в process_cmd device-классов даёт тот же исход.

**Рекомендация:** Обернуть вызов hooks.on_message (или тело _consume_messages) в try/except Exception с логированием и продолжением; сброс _client/_connected перенести в finally; создавать connection_task через _create_safe_task; в dispatcher валидировать isinstance(data, dict) / isinstance(cmd_data, dict) до .get().

#### [Major] Lost update: mark_state_published() вызывается после await publish и снапшотит УЖЕ новое состояние, хотя на провод ушло старое

- **Место:** `custom_components/sber_mqtt_bridge/sber_publisher.py:181`
- **Источник:** консенсус обоих ревьюеров

publish_states строит payload из состояния S1 (build_states_list_json, :165), затем await mqtt_service.publish (:174) уступает event loop (TLS к облаку — десятки-сотни мс). Если в этом окне state_changed S2 синхронно мутирует тот же entity-объект (HaStateForwarder → process_state_change → fill_by_ha_state) и ставит debounce, то после publish цикл :181-184 вызывает entity.mark_state_published(), который снапшотит to_sber_current_state() = S2 (base_entity.py:835-843). Последующий debounce-flush для S2 отфильтровывается has_significant_change()==False (:156-163) → Sber остаётся с S1 до следующего изменения или status_request. Реалистичный триггер: быстрый toggle on→off из UI/автоматизации (командные потоки частично спасает _delayed_confirm force=True, чисто HA-инициированные — нет). Смежно: при entity_ids=None список для mark-цикла перечитывается из bridge._enabled_entity_ids уже после await — при hot-reload за время publish «опубликованными» помечаются entity, которых не было в payload.

**Рекомендация:** Снимать снапшот per-entity в момент построения payload (до await) и после успешного publish присваивать его в _previous_sber_state (mark_state_published(snapshot)).

#### [Major] activate() не отменяет предыдущий fallback-таймер — stale-таймер прошлого подключения досрочно снимает guard нового

- **Место:** `custom_components/sber_mqtt_bridge/reconnect_ack_guard.py:63`
- **Источник:** консенсус обоих ревьюеров

activate() (:61-63) перезаписывает _timeout_handle новым loop.call_later БЕЗ _cancel_timer(). Сценарий: connect#1 в t=0 → таймер T1 на t+30 (RECONNECT_GRACE_TIMEOUT=30); disconnect в t=10 без ack (guard при disconnect не очищается — _handle_disconnect/_handle_mqtt_disconnected не трогают _ack_audit); reconnect в t=15 → activate ставит T2 (t=45), T1 жив. В t=30 T1 срабатывает: _on_timeout (:89-93) проверяет только _awaiting=True и сбрасывает guard на 15 с раньше дедлайна. В окне t=30..45 stale «корректирующие» команды Sber-облака принимаются и перезаписывают реальное HA-состояние — ровно тот класс проблем, ради которого guard существует; при флапе соединения таймеры копятся и окно защиты стремится к нулю.

**Рекомендация:** В activate() первой строкой self._cancel_timer(); в _handle_disconnect вызывать AckAudit-очистку guard (clear), чтобы каждое подключение стартовало с чистого состояния.

#### [Major] Debounce-таймер персиста redefinitions не отменяется и не флашится при async_stop — переживает unload и затирает/теряет данные

- **Место:** `custom_components/sber_mqtt_bridge/redefinitions_store.py:103`
- **Источник:** консенсус обоих ревьюеров

schedule_persist ставит loop.call_later(2.0, _flush) на hass.loop; SberBridge.async_stop (sber_bridge.py:652-675) таймер не отменяет и финальный flush не делает. Последствия: (1) rename/change_group от Sber менее чем за 2 с до shutdown HA теряется; (2) при полном reload (ws_add_entities/import → async_reload) dirty-таймер СТАРОГО стора переживает выгрузку и через ≤2 с пишет {**entry.options, "redefinitions": старый_dict} — last-writer-wins затирает redefinitions, записанные визардом/новым инстансом в этом окне (например name/room из _build_options_patch в devices_grouped.py); (3) после удаления entry _flush зовёт async_update_entry на несуществующем entry. Дополнительно _flush (:116) кладёт живой мутабельный self._redefinitions в options — последующие in-memory мутации (handle_rename_device пишет прямо в raw, command_dispatcher.py:370-374) незаметно меняют options без персиста.

**Рекомендация:** Добавить async_shutdown(): cancel таймера + синхронный финальный _flush при dirty, вызывать из async_stop; в _flush писать копию dict и проверять, что мост всё ещё активный.

#### [Minor] Единый общий debounce-таймер на все entity без max-wait: болтливая сущность бесконечно откладывает публикацию всех накопленных

- **Место:** `custom_components/sber_mqtt_bridge/ha_state_forwarder.py:219`
- **Источник:** консенсус обоих ревьюеров

_schedule_debounced_publish (:214-219) отменяет и перевзводит ОДИН общий _publish_timer при каждом изменении ЛЮБОЙ отслеживаемой сущности. При дефолтных 0.1 с нужен источник >10 Гц (редко), но debounce_delay настраивается пользователем через панель без верхней границы: при 1-5 с любой частый linked-сенсор (мощность, температура) вечно сдвигает flush, и _pending_publish_ids (включая одноразовое включение лампы) не публикуется никогда — Sber не видит и важные изменения.

**Рекомендация:** Добавить максимальный возраст самой старой pending-записи (принудительный flush по дедлайну) либо per-entity таймеры.

#### [Minor] Hot-reload молча выбрасывает накопленные debounced-публикации: subscribe() → unsubscribe_all() чистит _pending_publish_ids без flush

- **Место:** `custom_components/sber_mqtt_bridge/ha_state_forwarder.py:113`
- **Источник:** консенсус обоих ревьюеров

subscribe() начинается с unsubscribe_all() (:123-131), который отменяет таймер и очищает pending. Путь: ws_add_ha_device → _hot_reload (devices_grouped.py:298-300) → _reload_entities_and_resubscribe → _subscribe_ha_events → forwarder.subscribe → pending-состояния, попавшие в debounce-окно, потеряны; _hot_reload затем публикует только config, но не states → Sber остаётся со stale-состоянием до следующего изменения или status_request. Для shutdown-пути поведение корректно, для reuse при reload — потеря данных. Отмечено обоими ревьюерами (у A — внутри находки про debounce).

**Рекомендация:** В subscribe() при непустом pending сначала синхронно вызывать _fire_debounced_publish(), либо в _hot_reload добавлять publish_states(force=True).

#### [Minor] async_stop не отменяет задачи _confirm_tasks — delayed-confirm задачи переживают unload/reload

- **Место:** `custom_components/sber_mqtt_bridge/sber_bridge.py:652`
- **Источник:** консенсус обоих ревьюеров

_confirm_tasks заполняется в command_dispatcher._schedule_confirms (:221-227), самоочистка есть только в finally _delayed_confirm (sber_bridge.py:1010-1015). async_stop (:652-675) их не отменяет: после выгрузки entry задачи старого моста досыпают confirm_delay (1.5 с), читают hass.states, мутируют entity старого моста (fill_by_ha_state) и зовут _publish_states — публикация гасится _connected=False, вреда для данных нет, но это зомби-задачи, обращающиеся к hass после unload, и нарушение инварианта «unload останавливает всё».

**Рекомендация:** В async_stop: for t in self._confirm_tasks.values(): t.cancel(); self._confirm_tasks.clear().

#### [Minor] _connected=True выставляется до _wait_for_ha_ready/_perform_initial_publish — состояния могут уйти в up/status раньше up/config

- **Место:** `custom_components/sber_mqtt_bridge/sber_bridge.py:781`
- **Источник:** консенсус обоих ревьюеров

_handle_mqtt_connected: _mark_connected() (:781, ставит _connected=True в :804) выполняется до await _wait_for_ha_ready() (:782), который при старте HA может висеть минуты. HaStateForwarder подписан с async_start (до коннекта), publish_states проверяет только bridge._connected (sber_publisher.py:153) — debounced-публикации и WS republish проходят до _perform_initial_publish, т.е. Sber после рестарта получает status для устройств (возможно полу-заполненных), о которых ещё не знает, нарушая задокументированный порядок config-before-states. Инвариант «publish до subscribe» (защита от stale-команд) не страдает — поэтому minor.

**Рекомендация:** Флипать _connected (или отдельный флаг «publish разрешён») только после _perform_initial_publish, либо гейтить publish_states по завершению initial publish.

#### [Minor] Аудит-таймер silent-rejection не отменяется при disconnect — срабатывает офлайн и генерирует ложные предупреждения/repair-issues

- **Место:** `custom_components/sber_mqtt_bridge/sber_bridge.py:884`
- **Источник:** один ревьюер, подтверждено судьёй чтением кода

Только B; подтверждено. schedule_audit взводится после каждого publish_config (sber_publisher.py:262, delay 60 с); _handle_disconnect (:884-915) сбрасывает _connected/_mqtt_client, но _ack_audit.cancel() не зовёт (cancel вызывается только в async_stop:664). _run_ack_audit (:859-882) не имеет раннего выхода при not self._connected: если связь упала вскоре после публикации config и не восстановилась за остаток delay, таймер видит все entity как unacknowledged (ack физически не мог прийти) → WARNING «Sber silent rejection detected», record_silent_rejection помечает трейсы failed, check_and_create_issues создаёт ложные repair-тайлы, маскируя реальную причину (сеть). При реконнекте новый publish_config пересхедулит таймер, поэтому окно ограничено длительным офлайном.

**Рекомендация:** В _handle_disconnect отменять аудит-таймер; в _run_ack_audit — ранний выход при not self._connected.

#### [Minor] ws_update_settings персистит значения настроек без валидации типов — некорректное значение ломает каждый следующий запуск моста

- **Место:** `custom_components/sber_mqtt_bridge/websocket_api/settings.py:63`
- **Источник:** один ревьюер, подтверждено судьёй чтением кода

Только B; подтверждено. Схема — vol.Required("settings"): dict, значения не проверяются, фильтруются только ключи (:62-63). Порядок: сначала async_update_entry (:65) персистит, потом apply_settings → _load_settings_from_options → float(options[...]) (sber_bridge.py:451-455) → ValueError уже ПОСЛЕ записи. Тот же _load_settings_from_options вызывается в __init__ моста (sber_bridge.py:186), поэтому debounce_delay="abc" валит каждый последующий async_setup_entry — интеграция не поднимается до ручной правки options. Требует некорректного WS-клиента (штатная панель шлёт числа), поэтому minor.

**Рекомендация:** Валидировать значения vol-схемой по типам SETTINGS_DEFAULTS до async_update_entry и/или coerce с fallback на default в _load_settings_from_options.

#### [Info] _hot_reload использует голый hass.async_create_task вместо bridge._create_safe_task

- **Место:** `custom_components/sber_mqtt_bridge/websocket_api/devices_grouped.py:300`
- **Источник:** один ревьюер, подтверждено судьёй чтением кода

Только A; подтверждено: hass.async_create_task(bridge._publish_config()) (:300) — fire-and-forget вызов, минующий safe-task обёртку с логирующим done-callback. publish_config ловит MqttError/RuntimeError внутри, но ошибки построения payload вне этих типов уйдут в default exception handler без контекста. Несогласованность стиля, не баг.

**Рекомендация:** Заменить на bridge._create_safe_task(bridge._publish_config(), name="hot_reload_publish_config").

#### [Info] WS-подписка на message log привязана к MessageLogger конкретного инстанса моста — после reload entry панель молча перестаёт получать события

- **Место:** `custom_components/sber_mqtt_bridge/websocket_api/log.py:74`
- **Источник:** один ревьюер, подтверждено судьёй чтением кода

Только A; подтверждено: unsub = bridge.subscribe_messages(forward_message) (:74) через @requires_bridge захватывает текущий инстанс; unsub корректно хранится в connection.subscriptions (:75) и снимается при закрытии WS. При пересоздании SberBridge (add/remove entities → async_reload) новый мост пишет в новый MessageLogger, а открытая клиентская подписка остаётся на старом — live-лог DevTools замирает до переподписки. Утечки нет, UX-наблюдение.

**Рекомендация:** Переподписываться на фронтенде по событию reload либо держать MessageLogger вне моста (hass.data / runtime-неймспейс уровня entry).

## Обработка ошибок и устойчивость — оценка C

Локальная дисциплина обработки ошибок высокая: узкие except-клаузы вместо огульных, per-device изоляция при сборке config-payload (build_devices_list_json с invalid_ids), _create_safe_task с done-callback для фоновых задач, защищённый JSON-парсинг (parse_sber_command/status_request), «must never break forwarding» вокруг DevTools-хуков и корректные backoff-ретраи с clamp и сбросом. Однако центральный контур устойчивости имеет подтверждённую чтением кода системную дыру: у inbound-пути MQTT (consume → on_message → dispatcher → device handlers) нет ни одного exception-барьера, а run() ловит лишь MqttError/OSError/ValueError/RuntimeError — валидный-но-кривой payload от Sber (строка вместо dict в devices, не-dict states-элемент, JSON-массив в change_group/rename/global_config) даёт AttributeError/TypeError, которые навсегда и почти беззвучно убивают reconnect-loop (таск создан голым create_task без done-callback, поэтому исключение даже не логируется, а при unload срывает выгрузку). Ту же асимметрию видно на границах: fill_by_ha_state защищён в форвардере, но не в загрузчике (одна лампа с вырожденным CCT-диапазоном роняет весь setup); primary-путь форвардера защищён, linked — нет; WS-импорт персистит невалидированный конфиг, способный намертво сломать последующие setup и запереть пользователя от панели; verify_ssl из панели молча не применяется. Паттерны защиты в проекте есть и хорошо отработаны — они просто не доведены до всех критических швов, прежде всего до транспортного.

### Находки (14)

#### [CRITICAL] Один некорректный inbound-payload от Sber навсегда убивает MQTT reconnect-loop: нет exception-барьера вокруг обработки сообщений, а run() ловит только MqttError/OSError/ValueError/RuntimeError.

- **Место:** `custom_components/sber_mqtt_bridge/mqtt_client_service.py:170`
- **Источник:** консенсус обоих ревьюеров

Проверено чтением кода. Цепочка _consume_messages (mqtt_client_service.py:196) → hooks.on_message → SberBridge._handle_mqtt_message (sber_bridge.py:950 `await handler(payload)`) → dispatcher не содержит ни одного top-level try. parse_sber_command (sber_protocol.py:271-277) валидирует только что devices — dict, но не значения: {"devices": {"light.x": "on"}} проходит → AttributeError на cmd.get в _handle_reconnect_grace (command_dispatcher.py:153) или cmd_data.get (command_dispatcher.py:190); states-элемент не-dict → AttributeError на item.get в BaseEntity.process_cmd (base_entity.py:765, докстринг которого ошибочно утверждает «dispatcher rejects None before reaching here»); parse_sber_status_request возвращает элементы без проверки типа → dict-элемент даёт TypeError (unhashable) в handle_status_request:282; handle_change_group/handle_rename_device/handle_global_config (command_dispatcher.py:360/386/408) ловят только JSONDecodeError — валидный JSON `[]`/`5` даёт AttributeError на data.get (:367/:393/:405). Ни один из этих TypeError/AttributeError не входит в except-клаузы run() (mqtt_client_service.py:165-172) → while-цикл завершается, реконнектов больше нет; _mqtt_connection_loop (sber_bridge.py:762-767) имеет только try/finally без except — бридж молча остаётся disconnected до перезагрузки интеграции.

**Рекомендация:** Обернуть вызов hooks.on_message в _consume_messages (или тело _handle_mqtt_message) в try/except Exception с _LOGGER.exception и продолжением цикла; ужесточить parse_sber_command/parse_sber_status_request (значения devices — dict, states — list[dict], элементы status_request — str); в run() добавить catch-all как last resort.

#### [Major] ws_import пишет невалидированные структуры в entry.options и делает reload — битый импорт ломает setup интеграции без возможности починки через UI.

- **Место:** `custom_components/sber_mqtt_bridge/websocket_api/io_export.py:82`
- **Источник:** консенсус обоих ревьюеров

Проверено: схема (io_export.py:55-59) валидирует лишь vol.Required("config"): dict; содержимое exposed_entities/type_overrides/redefinitions/entity_links копируется в options как есть (:70-80), затем async_update_entry + async_reload (:82-83). Если entity_links — list, при reload SberEntityLoader._apply_entity_links (entity_registry.py:263-266) вызовет raw_links.items() → AttributeError → load() → async_start → async_setup_entry падает; повторные setup читают те же испорченные options — интеграция мертва, а WS-хэндлеры требуют loaded entry, поэтому панель и повторный import недоступны (чинить — правкой .storage). Второй сценарий: redefinitions со строковыми значениями → redef.get("home") в sber_protocol.py:154 → AttributeError уже в publish-пути.

**Рекомендация:** Валидировать импорт voluptuous-схемой (exposed_entities: [str], type_overrides: {str: str}, redefinitions: {str: {str: str}}, entity_links: {str: {str: str}}) и отвечать send_error до записи в options.

#### [Major] Ошибка fill_by_ha_state одной entity роняет загрузку всех entities и весь async_setup_entry — нет per-entity изоляции в SberEntityLoader._create_entities.

- **Место:** `custom_components/sber_mqtt_bridge/entity_registry.py:201`
- **Источник:** один ревьюер, подтверждено судьёй чтением кода

Уникальная находка A, подтверждена чтением кода: sber_entity.fill_by_ha_state(ha_state_dict) (entity_registry.py:201) не обёрнут в try. Конкретный ValueError-путь существует: LightEntity.fill_by_ha_state при узком CCT-диапазоне (min_color_temp_kelvin=6493, max_color_temp_kelvin=6500 → округление даёт min_mireds==max_mireds==154) вызывает color_temp_converter.set_ha_limits (light.py:148-149), который кидает ValueError при min>=max (linear_converter.py:69-73). Исключение поднимается через load() → _load_exposed_entities (sber_bridge.py:637/697) → async_start → async_setup_entry: одна «плохая» лампа выводит из строя всю интеграцию. Показательно, что тот же вызов в HaStateForwarder защищён (ha_state_forwarder.py:191-197), а в загрузчике — нет; аналогично незащищён update_linked_data в _apply_entity_links (entity_registry.py:300).

**Рекомендация:** Обернуть fill_by_ha_state и update_linked_data в try/except (TypeError, ValueError, KeyError, AttributeError) с warning и пропуском entity; в LightEntity не вызывать set_ha_limits при min>=max.

#### [Major] Нет изоляции партиальных сбоев в handle_command: исключение из process_cmd одного устройства прерывает обработку остальных устройств батча, echo-ack и delayed-confirm.

- **Место:** `custom_components/sber_mqtt_bridge/command_dispatcher.py:194`
- **Источник:** один ревьюер, подтверждено судьёй чтением кода

Уникальная находка B, подтверждена: цикл for entity_id, cmd_data in devices.items() (command_dispatcher.py:111-113) → _process_one_entity → entity.process_cmd(cmd_data) (:194) без try/except. Сбой на первом устройстве (кривое value, states не list-of-dict, баг device-класса) означает, что остальные устройства мульти-девайсной команды не получат ни service call, ни publish_states (:118), ни publish_command_echo (:127), ни _schedule_confirms (:129) — ack-таймер Sber истечёт для всех. Это независимый дефект от транспортного kill-path: даже после добавления top-level барьера батч останется неатомарно-хрупким.

**Рекомендация:** Обернуть тело _process_one_entity в try/except Exception с per-entity логом и продолжением цикла; валидировать форму cmd_data в parse_sber_command.

#### [Major] Переключение verify_ssl из панели молча не действует: ssl_context создаётся один раз до while-цикла run() и никогда не пересоздаётся при реконнекте.

- **Место:** `custom_components/sber_mqtt_bridge/mqtt_client_service.py:156`
- **Источник:** один ревьюер, подтверждено судьёй чтением кода

Уникальная находка A, подтверждена: update_verify_ssl (mqtt_client_service.py:135-143) обновляет только self._credentials, но ssl_context строится единожды на строке 156 до цикла, и _build_client (:181-189) использует захваченный контекст. Docstring apply_settings (sber_bridge.py:472) обещает «take effect on next reconnect» — ложь. Дополнительно проверено: в интеграции нет ни одного add_update_listener (grep пуст), а ws_update_settings (websocket_api/settings.py:65-69) вызывает async_update_entry + apply_settings без reload — то есть панельный путь вообще не имеет способа применить verify_ssl. Сценарий-ловушка: бридж падает по SSL-ошибке, пользователь выключает verify_ssl в панели — реконнекты продолжают падать с той же ошибкой без какого-либо намёка, что нужен reload интеграции.

**Рекомендация:** Пересоздавать ssl_context в начале каждой итерации while (или по флагу «credentials changed» после update_verify_ssl).

#### [Minor] _connection_task создаётся голым asyncio.create_task без done-callback — фатальное исключение reconnect-цикла не логируется, а при unload вылетает из await и срывает выгрузку entry.

- **Место:** `custom_components/sber_mqtt_bridge/sber_bridge.py:639`
- **Источник:** консенсус обоих ревьюеров

Проверено: sber_bridge.py:639 — asyncio.create_task(self._mqtt_connection_loop()) вместо имеющегося _create_safe_task (:397, с done-callback логирования). _mqtt_connection_loop (:762-767) — только try/finally. Если run() умирает от неожиданного исключения (см. critical-находку), оно не логируется до GC («Task exception was never retrieved»), а в async_stop (:669-672) contextlib.suppress ловит только CancelledError — исключение перебрасывается из await self._connection_task и заваливает async_unload_entry.

**Рекомендация:** Создавать _connection_task через _create_safe_task; в async_stop подавлять/логировать не-Cancelled исключения при await.

#### [Minor] async_stop не отменяет debounce-таймер RedefinitionsStore и _confirm_tasks — колбэки переживают unload и могут перезаписать options устаревшими данными.

- **Место:** `custom_components/sber_mqtt_bridge/sber_bridge.py:652`
- **Источник:** консенсус обоих ревьюеров

Проверено: async_stop (sber_bridge.py:652-675) отменяет forwarder, lifecycle-listeners, ack_audit и mqtt, но не RedefinitionsStore._timer (redefinitions_store.py:103, loop.call_later 2.0s → _flush → async_update_entry) и не _confirm_tasks (delayed_confirm, command_dispatcher.py:225). Сценарий: rename/change_group от Sber или правка в панели, затем reload в течение 2 с — _flush старого инстанса срабатывает после создания нового бриджа и пишет в entry.options устаревший снапшот redefinitions поверх свежих (или пишет в удаляемую entry). AckAudit при этом отменяется корректно — обработка несимметрична.

**Рекомендация:** В async_stop: отменить таймер стора (cancel + синхронный финальный _flush при _dirty) и cancel всех _confirm_tasks.

#### [Minor] Linked-путь не защищён try/except в отличие от primary-пути: исключение из update_linked_data/get_final_features_list протекает в event-bus callback и срывает публикацию.

- **Место:** `custom_components/sber_mqtt_bridge/ha_state_forwarder.py:171`
- **Источник:** консенсус обоих ревьюеров

Проверено: _handle_primary_state_change оборачивает process_state_change в except (TypeError, ValueError, KeyError, AttributeError) (ha_state_forwarder.py:191-197), а _handle_linked_state_change (:157-180) вызывает get_final_features_list()/update_linked_data без защиты. Исключение на нестандартном атрибуте linked-сенсора даёт traceback в event loop HA на каждом изменении, и _schedule_debounced_publish не вызывается — обновление (батарея/температура) молча теряется до следующего события.

**Рекомендация:** Продублировать тот же узкий try/except с _LOGGER.exception и return вокруг тела _handle_linked_state_change.

#### [Minor] _send_raw ловит только RuntimeError — aiomqtt.MqttError при обрыве в момент publish уходит в панель как generic internal error, publish_errors не инкрементируется.

- **Место:** `custom_components/sber_mqtt_bridge/websocket_api/raw.py:121`
- **Источник:** консенсус обоих ревьюеров

Проверено: raw.py:119-123 — except RuntimeError только. bridge.async_publish_raw (sber_bridge.py:489-506) публикует напрямую через self._mqtt_client.publish без try/except и без учёта stats.publish_errors — в отличие от SberPublisher. При обрыве TCP между проверкой _connected и publish MqttError пролетает в websocket-фреймворк HA — пользователь DevTools видит unknown_error вместо not_connected/publish_failed.

**Рекомендация:** Добавить except aiomqtt.MqttError с send_error("publish_failed") и инкрементом stats.publish_errors, либо переиспользовать MqttClientService.publish.

#### [Minor] Экспоненциальный backoff без jitter: все инсталляции после сбоя брокера Sber реконнектятся синхронными волнами.

- **Место:** `custom_components/sber_mqtt_bridge/mqtt_client_service.py:213`
- **Источник:** консенсус обоих ревьюеров

Проверено: _after_error (mqtt_client_service.py:212-213) — sleep(interval), затем interval = min(interval*2, max), детерминированно. min/max ограничены и сброс на успешном коннекте есть (:162) — ретраи в остальном корректны. При массовом обрыве (рестарт mqtt-partners.iot.sberdevices.ru) все клиенты ретраятся синхронизированными волнами.

**Рекомендация:** Добавить случайный jitter (например interval * uniform(0.5, 1.5)) при вычислении задержки.

#### [Minor] ValueError/RuntimeError из логики обработки сообщений трактуются как ошибка транспорта: здоровое MQTT-соединение разрывается и уходит в backoff-реконнект.

- **Место:** `custom_components/sber_mqtt_bridge/mqtt_client_service.py:170`
- **Источник:** один ревьюер, подтверждено судьёй чтением кода

Уникальная находка B (facet критической, но отдельное следствие), подтверждена: except (OSError, ValueError, RuntimeError) в run() (mqtt_client_service.py:170) перехватывает и исключения, поднявшиеся из hooks.on_message (например ValueError из device-конвертера или RuntimeError из to_sber_state) — async with client закрывается, on_disconnected вызывается с unexpected=True, reconnect_count растёт, TCP-сессия переустанавливается, хотя брокер жив. Ошибки протокола/логики конфлируются с транспортными.

**Рекомендация:** После добавления барьера вокруг обработчиков сузить except в run() до транспортных ошибок connect/consume.

#### [Minor] Глобальный debounce-таймер без max-wait: быстро обновляющаяся entity бесконечно откладывает публикацию накопленных состояний всех остальных.

- **Место:** `custom_components/sber_mqtt_bridge/ha_state_forwarder.py:219`
- **Источник:** один ревьюер, подтверждено судьёй чтением кода

Уникальная находка A, подтверждена структурно: _schedule_debounced_publish (ha_state_forwarder.py:213-219) на каждое событие любой отслеживаемой entity отменяет и перевзводит единственный общий self._publish_timer. При непрерывных обновлениях чаще debounce_delay (default 0.1s — шумный power/illuminance-сенсор) _fire_debounced_publish не выполняется, и накопленные _pending_publish_ids других устройств не публикуются — Sber видит устаревшие состояния неограниченно долго.

**Рекомендация:** Добавить верхнюю границу коалесинга (max-wait, напр. 5×debounce) или per-entity таймеры.

#### [Minor] Guard на размер payload применяется после полного декодирования и записи payload в DevTools ring-buffer — защита от oversized-сообщений частично обесценена.

- **Место:** `custom_components/sber_mqtt_bridge/sber_bridge.py:928`
- **Источник:** один ревьюер, подтверждено судьёй чтением кода

Уникальная находка A, подтверждена: в _handle_mqtt_message сначала payload.decode("utf-8", errors="replace") и _log_message("in", topic, decoded) с полным телом (sber_bridge.py:928-929), и только затем проверка len(payload) > self._max_payload_size с drop (:932-939). Oversized-сообщение целиком декодируется и сохраняется в MessageLogger (deque хранит полные строки) — память расходуется до drop, что противоречит цели guard'а.

**Рекомендация:** Переставить size-guard первым; в ring-buffer логировать усечённый payload с пометкой truncated.

#### [Info] async_setup_entry без rollback: при сбое после bridge.async_start() (регистрация static path/панели или битые options) bridge не останавливается и ошибка не транслируется в ConfigEntryNotReady.

- **Место:** `custom_components/sber_mqtt_bridge/__init__.py:86`
- **Источник:** консенсус обоих ревьюеров

Проверено: __init__.py:85-114 — await bridge.async_start() на строке 86, затем регистрация WS API, static paths и панели без единого try/except. Если любой последующий шаг (или _load_exposed_entities внутри async_start на испорченных options) кидает — setup падает как generic «Error setting up entry» без авторетрая, а уже запущенные connection task и подписки на state_changed продолжают жить у незагруженной entry до рестарта HA.

**Рекомендация:** Обернуть тело setup в try/except с await bridge.async_stop() и raise ConfigEntryNotReady/ConfigEntryError по типу ошибки (или запускать бридж последним шагом).

## Архитектура и SOLID — оценка B

Архитектура заметно лучше средней HACS-интеграции: слой devices/ чист (только декларативные CommandResult-дескрипторы, ни MQTT, ни hass.services туда не протекают), CATEGORY_DOMAIN_MAP — рабочий single source of truth для добавления категорий, dispatch-таблицы вместо if/elif, транспорт/форвардер/ack-guard корректно развязаны через hooks и callbacks, граница websocket_api↔bridge почти полностью публичная. Главный системный долг, подтверждённый обоими ревьюерами и чтением кода: декомпозиция SberBridge выполнена как facade-split — SberPublisher, SberCommandDispatcher и RedefinitionsStore держат back-reference на мост и работают через его приватные поля (BridgeCommandContext — Protocol из приватных атрибутов и конкретных классов), а сам мост на 1089 строк сохраняет ~20 test-compat прокси, включая запись в чужие приватные поля, и дублирует connection-state с MqttClientService (латентный риск тихого дропа publish при рассинхроне). Вторичный пласт — консистентность: два одноимённых расходящихся OVERRIDABLE_CATEGORIES (WS принимает категории, которых нет в Options Flow), три пути записи redefinitions мимо стора, frozenset-гейты по категориям в базовых device-классах вопреки собственному паттерну _supports_*, нетипизированный контракт фабрики с инвертированными сигнатурами конструкторов, зависимость транспорта от config_flow. Критичных для пользователей архитектурных дефектов нет; эталонные паттерны (узкие hooks HaStateForwarder/MqttServiceHooks) уже присутствуют в кодбейсе — долг устраним их распространением на оставшиеся три компонента и миграцией тестов на публичные API.

### Находки (15)

#### [Major] SberPublisher и RedefinitionsStore держат back-reference на конкретный SberBridge и читают его приватные поля — декомпозиция v1.38.3/1.38.4 является facade-split, а не выделением компонентов.

- **Место:** `custom_components/sber_mqtt_bridge/sber_publisher.py:45`
- **Источник:** консенсус обоих ревьюеров

Подтверждено чтением: SberPublisher.__init__(bridge) (sber_publisher.py:45-52), далее методы читают bridge._connected, _mqtt_service, _entities, _enabled_entity_ids, _stats, _root_topic, _redefinitions (сам — compat-прокси), _entry.options, _hass.config, _ha_instance_id_prefix, _ha_serial_enabled, _ack_audit, _ack_audit_delay, _log_message, _trace_collector, _diff_collector, _validation_collector (строки 73, 106-132, 153, 165, 186-202, 216-269). RedefinitionsStore аналогично: __init__(bridge) (redefinitions_store.py:33), schedule_persist → bridge._hass.loop (строка 103), _flush → bridge._entry.options + bridge._hass.config_entries (116-117). Любая внутренняя правка моста ломает 2-3 «независимых» модуля; компоненты нетестируемы без полного моста. Контраст: HaStateForwarder, MqttClientService и AckAudit получают узкие callbacks/hooks (sber_bridge.py:201-243) — правильный паттерн в кодбейсе есть, применён к 3 из 6 компонентов.

**Рекомендация:** Передавать publisher/store узкие зависимости (mqtt publish callable, entities provider, stats, devtools hub, entry) в конструкторе по образцу HaStateForwarder; back-reference на мост убрать.

#### [Major] BridgeCommandContext Protocol состоит из приватных атрибутов SberBridge и конкретных классов-коллабораторов — «узкий интерфейс» только номинально.

- **Место:** `custom_components/sber_mqtt_bridge/command_dispatcher.py:51`
- **Источник:** консенсус обоих ревьюеров

Подтверждено: Protocol (command_dispatcher.py:51-72) перечисляет _hass, _stats, _ack_audit, _entities, _enabled_entity_ids, _confirm_tasks и конкретные типы _publisher: SberPublisher, _redef_store: RedefinitionsStore, _devtools: DevToolsHub, плюс приватные методы _create_safe_task/_delayed_confirm. Через конкретный SberPublisher (который сам держит bridge) диспетчер транзитивно достигает всего моста — нарушение Law of Demeter; альтернативная реализация или мок контекста требует воспроизведения приватной раскладки SberBridge, т.е. цели Protocol (подменяемость, ISP) не достигнуты.

**Рекомендация:** Переопределить Protocol в терминах публичных операций (publish_states, publish_config, ack, record_trace, stats) вместо приватных атрибутов и конкретных классов.

#### [Major] SberBridge (1089 строк) сохраняет God-интерфейс через ~20 backward-compat прокси «для тестов», включая запись в приватное поле чужого объекта и вызов его приватного метода.

- **Место:** `custom_components/sber_mqtt_bridge/sber_bridge.py:256`
- **Источник:** консенсус обоих ревьюеров

Подтверждено: сеттер _last_config_publish_time пишет напрямую в self._publisher._last_config_publish_time (строки 256-258); _flush_redefinitions вызывает self._redef_store._flush() (1043-1045); _on_ha_state_changed и _schedule_debounced_publish дергают приватные методы форвардера (1059, 1068); прокси _redefinitions (260-267), _msg_logger/_trace_collector/_diff_collector/_validation_collector (271-289), _publish_command_echo (976-983), _persist_redefinitions (1038-1040), _publish_states/_publish_config (1078-1089), _mqtt_connection_loop «kept for test compatibility» (755-767). Публичная поверхность класса формируется тестами, а не дизайном: каждый выделенный компонент добавляет пару прокси вместо их удаления, цементируя старую архитектуру.

**Рекомендация:** Мигрировать тесты на публичные API компонентов и поэтапно удалить прокси-слой; целевой размер моста — координатор ~400-500 строк.

#### [Minor] Дублированное connection-state bridge↔MqttClientService (два флага _connected и два указателя на клиент, ручная синхронизация в трёх местах) плюс обходной transport-путь async_publish_raw и мёртвое поле _reconnect_interval.

- **Место:** `custom_components/sber_mqtt_bridge/sber_bridge.py:894`
- **Источник:** консенсус обоих ревьюеров

Подтверждено: bridge._connected/_mqtt_client (строки 177-180) зеркалируют MqttClientService._connected/_client (mqtt_client_service.py:107-108); синхронизация вручную в _handle_mqtt_connected/_mark_connected (780, 802-806), _handle_mqtt_disconnected/_handle_disconnect (799, 894-895) и finally _mqtt_connection_loop (765-767). SberPublisher проверяет bridge._connected, а MqttClientService.publish — свой флаг (mqtt_client_service.py:224): рассинхрон даёт тихий дроп publish. async_publish_raw (строки 499-504) публикует через self._mqtt_client напрямую, минуя MqttClientService.publish. bridge._reconnect_interval (строки 450, 805) пишется, но нигде не читается — мост читает _mqtt_service.reconnect_interval (900).

**Рекомендация:** Сделать MqttClientService единственным владельцем connection-state (bridge.is_connected → делегат в service.is_connected), перевести async_publish_raw на _mqtt_service.publish, удалить _reconnect_interval и _mqtt_client с моста.

#### [Minor] Категорийные frozenset-гейты в базовых device-классах — база ветвится по строке category и перечисляет категории своих наследников, вопреки собственному паттерну _supports_* в ClimateEntity.

- **Место:** `custom_components/sber_mqtt_bridge/devices/on_off_entity.py:43`
- **Источник:** консенсус обоих ревьюеров

Подтверждено: OnOffEntity._CHILD_LOCK_CATEGORIES = frozenset({"socket"}) и _ENERGY_CATEGORIES = frozenset({"relay", "socket"}) (on_off_entity.py:43-51) с проверками self.category in ... в _create_features_list и to_sber_current_state (100-107, 121-128); CurtainEntity._TILT_CATEGORIES/_BATTERY_CATEGORIES (curtain.py:154-157, использование 179-185, 256-262); ClimateEntity._NIGHT_MODE_CATEGORIES = frozenset({"hvac_ac"}) (climate.py:340, использование 336, 555). Новая категория с battery/child_lock требует правки frozenset в базовом классе (OCP-разрыв). Рядом уже есть чистый паттерн переопределяемых флагов _supports_fan/_supports_swing/_supports_work_mode/_supports_thermostat_mode (climate.py:240-243). Симптом: KettleEntity живёт вне OnOffEntity и дублирует on_off-логику (kettle.py:27 наследует BaseEntity напрямую), хотя docstring _CHILD_LOCK_CATEGORIES перечисляет socket/kettle/vacuum.

**Рекомендация:** Заменить frozenset-гейты на переопределяемые ClassVar-флаги (_supports_child_lock, _supports_energy, _supports_tilt, _supports_battery, _supports_night_mode) по образцу _supports_* в ClimateEntity.

#### [Minor] Контракт фабрики spec.cls(entity_data) не типизирован и несовместим с сигнатурой заявленного базового типа: BaseEntity/OnOffEntity/SimpleReadOnlySensor принимают (category, entity_data), листовые классы — (entity_data[, category]) с перевёрнутым порядком.

- **Место:** `custom_components/sber_mqtt_bridge/sber_entity_map.py:459`
- **Источник:** консенсус обоих ревьюеров

Подтверждено grep-ом всех __init__: base_entity.py:319 и on_off_entity.py:60, simple_sensor.py:77 — (category, entity_data); все листовые — (entity_data) или (entity_data, category=DEFAULT) (relay.py:31, curtain.py:59); LightEntity именует параметр ha_entity_data (light.py:93) — третий вариант. Фабрика вызывает spec.cls(entity_data) (sber_entity_map.py:459 и 479) при аннотации cls: type[BaseEntity] — вызов базового/промежуточного класса по этому контракту молча создаст объект с category=dict. Сейчас в CATEGORY_DOMAIN_MAP только листовые классы, поэтому рантайм-падения нет — это латентная ловушка и нетипизированное соглашение, а не активный баг.

**Рекомендация:** Унифицировать порядок параметров по иерархии либо зафиксировать фабричный контракт типом (Callable[[dict], BaseEntity] в CategorySpec.cls или classmethod from_registry).

#### [Minor] Транспортный слой импортирует create_ssl_context из config_flow (UI-слоя) — обратное направление слоёв, скрытое отложенным импортом внутри run(); плюс docstring MqttServiceHooks описывает несуществующий атрибут get_connected_since.

- **Место:** `custom_components/sber_mqtt_bridge/mqtt_client_service.py:153`
- **Источник:** консенсус обоих ревьюеров

Подтверждено: `from .config_flow import create_ssl_context` внутри MqttClientService.run() (строка 153). MqttClientService декларирует независимость от прикладного слоя, но зависит от presentation-модуля ради SSL-утилиты; deferred import прячет зависимость от статического анализа. Docstring MqttServiceHooks (строки 52-53) документирует get_connected_since, которого нет среди атрибутов dataclass (56-58) — дрейф документации интерфейса.

**Рекомендация:** Вынести create_ssl_context в утилитный модуль (ssl_utils.py), импортируемый и config_flow, и транспортом; убрать get_connected_since из docstring.

#### [Minor] Две разные константы с одним именем OVERRIDABLE_CATEGORIES: ручной список из 21 категории в sber_entity_map.py:53 (используется config_flow) и производный из всех 29 ключей CATEGORY_DOMAIN_MAP в _common.py:36 (используется всей WS-валидацией) — плюс третья hardcoded-копия в JS.

- **Место:** `custom_components/sber_mqtt_bridge/websocket_api/_common.py:36`
- **Источник:** консенсус обоих ревьюеров

Подтверждено: sber_entity_map.OVERRIDABLE_CATEGORIES — 21 запись без sensor_* (строки 53-76), импортируется только config_flow.py:47/712. websocket_api/_common.OVERRIDABLE_CATEGORIES = sorted(CATEGORY_DOMAIN_MAP.keys()) — 29 значений, используется и devices_grouped.py:105/308, и entities.py:108 (импорт из _common, проверено). Итог: WS add_ha_device/set_entity_override принимают категории (все sensor_*), которых Options Flow не предлагает — два входных пути валидации расходятся; третья независимая копия списка захардкожена в www/components/sber-entity-row.js:10. Одинаковое имя при разной семантике провоцирует импорт не того списка; добавление категории требует синхронизации ручного списка (OCP-разрыв при заявленном single source of truth).

**Рекомендация:** Добавить в CategorySpec флаг user_overridable и выводить оба Python-списка из CATEGORY_DOMAIN_MAP; JS-копию генерировать/отдавать через WS; одну из констант переименовать.

#### [Minor] handle_change_group/handle_rename_device мутируют RedefinitionsStore.raw напрямую, минуя async_update, и дублируют его merge-логику без нормализации.

- **Место:** `custom_components/sber_mqtt_bridge/command_dispatcher.py:370`
- **Источник:** консенсус обоих ревьюеров

Подтверждено: handle_change_group пишет existing["home"]/["room"] = data.get(...) — без strip и с возможным None — в bridge._redef_store.raw (строки 370-374); handle_rename_device — raw.setdefault(entity_id, {})["name"] (396-398); оба сами вызывают schedule_persist. RedefinitionsStore.async_update (redefinitions_store.py:60-96) реализует ту же операцию с нормализацией (strip, удаление пустых/None ключей) — два пути записи с разной семантикой. Свойство raw задокументировано как «internal use only — for bridge proxies» (redefinitions_store.py:52), но используется внешним модулем.

**Рекомендация:** Дать стору sync-вариант update (или вызывать async_update) и перевести оба хендлера на него; raw сделать действительно внутренним.

#### [Minor] Блок DevTools-инструментации (~16 строк: log_message + trace + diff + validation collectors) продублирован дословно в publish_states и publish_command_echo, с пересбором categories/declared_features по ВСЕМ entities на каждый publish.

- **Место:** `custom_components/sber_mqtt_bridge/sber_publisher.py:189`
- **Источник:** консенсус обоих ревьюеров

Подтверждено: строки 115-132 (echo) и 186-202 (states) почти идентичны, включая одинаковые try/except Exception; в обоих местах на каждый publish строятся полные словари {eid: ent.category} и {eid: ent.get_final_features_list()} для всех entities, даже когда публикуется одна (124-125, 194-195). publish_config инструментирован асимметрично — только log_message (260). Публикатор знает о трёх конкретных коллекторах — второй SRP-центр после моста.

**Рекомендация:** Вынести хук DevToolsHub.record_outbound(topic, payload, entity_ids) и вызывать одну строку из всех трёх publish-методов; словари категорий строить лениво/инкрементально.

#### [Minor] WS-хендлеры пишут магический ключ "redefinitions" напрямую в entry.options, минуя RedefinitionsStore — три независимых пути записи с возможной потерей данных при отложенном флаше стора.

- **Место:** `custom_components/sber_mqtt_bridge/websocket_api/devices_grouped.py:277`
- **Источник:** один ревьюер, подтверждено судьёй чтением кода

Подтверждено (только отчёт A): _build_updated_options кладёт new_options["redefinitions"] напрямую (devices_grouped.py:277-285), io_export.ws_import — то же (io_export.py:77-78); ключ-строка независимо захардкожена также в entity_registry.py:118 и redefinitions_store.py:116. Механизм гонки: RedefinitionsStore._flush пишет {**bridge._entry.options, "redefinitions": self._redefinitions} по 2-секундному дебаунс-таймеру — если между прямой WS-записью и флашем стор держал устаревшую in-memory копию, прямая запись перезаписывается. Окно узкое (после add_ha_device идёт _hot_reload, который пересинхронизирует store через reload), но пути записи семантически расходятся.

**Рекомендация:** Все записи redefinitions вести через RedefinitionsStore (добавить replace/import API), ключ вынести в константу const.py.

#### [Minor] requires_bridge/requires_entry выполняют late-binding lookup через sys.modules «чтобы уважать тестовые патчи» — test-induced механика, продублированная в 4 обёртках.

- **Место:** `custom_components/sber_mqtt_bridge/websocket_api/_common.py:113`
- **Источник:** один ревьюер, подтверждено судьёй чтением кода

Подтверждено (только отчёт A): каждый из четырёх wrapper'ов (async/sync × bridge/entry) содержит идентичный блок sys.modules.get(_module_name) → getattr(_mod, "get_bridge"/"get_config_entry") → fallback (строки ~113-146 и далее в requires_entry). Production-код обслуживает механику тестовых моков; поведение декоратора зависит от наличия имени get_bridge/get_config_entry в модуле-хосте хендлера (entities.py даже реэкспортирует get_config_entry с пометкой «re-exported for test patching», entities.py:22), что хрупко при рефакторинге импортов.

**Рекомендация:** Патчить в тестах единую точку _common.get_bridge/_common.get_config_entry и убрать sys.modules-механику, либо параметризовать декоратор lookup-фабрикой.

#### [Info] _hot_reload — единственная протечка приватного API моста в websocket_api: вызывает bridge._reload_entities_and_resubscribe() и bridge._publish_config().

- **Место:** `custom_components/sber_mqtt_bridge/websocket_api/devices_grouped.py:298`
- **Источник:** консенсус обоих ревьюеров

Подтверждено (строки 289-300): остальной WS-пакет работает через публичные свойства (entities, stats, async_republish_config, async_update_redefinition). Hot-reload — легитимный сценарий панели, которому не хватает публичного метода.

**Рекомендация:** Добавить bridge.async_hot_reload() (reload + условный republish) и использовать его.

#### [Info] AttrSpec постепенно превращается в tagged union: поле converter при установке молча отключает parser/attr_keys, и используется в т.ч. для тривиальных случаев, где хватило бы attr_keys+default.

- **Место:** `custom_components/sber_mqtt_bridge/devices/base_entity.py:84`
- **Источник:** консенсус обоих ревьюеров

Подтверждено: base_entity.py:84-87 — «attr_keys are ignored when converter is provided», вторая ветвь исполнения в _apply_attr_specs (382-385); climate.py:230 — converter=lambda attrs: attrs.get("preset_modes") or [] при наличии default=[]. Ключевые сложные поля климата всё равно парсятся императивно в fill_by_ha_state. Наблюдение, не дефект: в остальных классах ATTR_SPECS работает уместно.

**Рекомендация:** При следующем расширении разделить AttrSpec и ConverterSpec (union в ATTR_SPECS); тривиальные списки объявлять через attr_keys+default.

#### [Info] diagnostics_advisor читает приватные bridge._entities/_enabled_entity_ids/_linked_reverse/_stats, хотя для большинства есть публичные свойства.

- **Место:** `custom_components/sber_mqtt_bridge/diagnostics_advisor.py:75`
- **Источник:** один ревьюер, подтверждено судьёй чтением кода

Подтверждено (только отчёт A): _collect_summary обращается к bridge._entities.get, bridge._enabled_entity_ids, bridge._linked_reverse.get, bridge._stats.acknowledged_entities (строки ~74-78), при том что тот же метод рядом использует публичные trace_collector/diff_collector/validation_collector. Для _linked_reverse публичного эквивалента с ролью нет (linked_entity_ids возвращает только set) — потребуется добавить свойство.

**Рекомендация:** Перейти на публичные entities/enabled_entity_ids/stats; добавить публичное свойство linked_reverse_map.

### Опровергнутые заявки ревьюеров

- ~~Отчёт A: «sber_entity_map.OVERRIDABLE_CATEGORIES используется websocket_api/entities.py:108» (в рамках находки о двух списках).~~ — Чтение кода показало обратное: entities.py:23 импортирует OVERRIDABLE_CATEGORIES из websocket_api/_common (производный список из 29 ключей CATEGORY_DOMAIN_MAP), а не из sber_entity_map. Ручной список из 21 категории используется только config_flow.py. Сама находка о расхождении двух одноимённых списков подтверждена и включена в consensus с исправленной атрибуцией (версия отчёта B точна); также A указал «28 ключей» — фактически их 29.

## Качество кода и DRY — оценка B

Кодовая база зрелая по DRY-меркам: декларативные AttrSpec/CategorySpec/LinkableRole и миксины (battery/signal, fan-speed) реально устраняют дублирование между 15+ device-классами, docstrings систематические. Главная системная проблема измерения — «расщеплённые реестры», дрейфующие независимо от заявленного single source of truth (CATEGORY_DOMAIN_MAP): ALL_LINKABLE_ROLES отстал от per-class LINKABLE_ROLES на 6 air-ролей (wizard не линкует air-сенсоры при работающем auto_link — три идиомы валидации одной связи), OVERRIDABLE_CATEGORIES существует в трёх несовпадающих копиях под одним именем (21 vs 28 категорий, sensor-override невозможен из UI-таблицы), JS/Python-зеркала имени-валидатора разошлись по дефису и строгости (wizard блокирует валидные имена вида «Смарт-ТВ»), плюс отставшие SUPPORTED_DOMAINS (нет lock), CATEGORY_LABELS (нет 5 категорий) и device_classes спека sensor_air (нет hcho). Все эти находки подтверждены чтением кода и имеют реальные функциональные следствия. Второй пласт — незавершённая уборка после серии экстракций v1.38.x: SberBridge несёт ~15 backward-compat прокси «для тестов» с 2-3 путями доступа к каждому коллектору и мутацией приватных полей коллабораторов (границы компонентов фиктивны), плюс кластер мёртвого кода (константы, поля BridgeStats, дубликат backoff-состояния, HAState, _sweep_traces) и локальные copy-paste (инструментирование в publisher, 4x wrapper в _common, F→C конверсия x3, дублированные fan-хендлеры). Ни одна находка обоих ревьюеров не опровергнута — оба отчёта точны. Долг существенный, но сконцентрированный и хорошо локализуемый: генерация производных реестров из одного источника + удаление прокси-слоя закрыли бы большинство находок.

### Находки (20)

#### [Major] Два рассинхронизированных реестра link-ролей: ALL_LINKABLE_ROLES не содержит 6 air-ролей (co2/pm1/pm25/pm10/tvoc/hcho), из-за чего wizard не может привязать air-датчики

- **Место:** `custom_components/sber_mqtt_bridge/devices/base_entity.py:227`
- **Источник:** консенсус обоих ревьюеров

Проверено чтением: ALL_LINKABLE_ROLES (base_entity.py:227-233) содержит только battery/battery_low/signal/temperature/humidity, тогда как SensorAirEntity.LINKABLE_ROLES (sensor_air.py:168-177) объявляет ещё ROLE_CO2/PM1/PM25/PM10/TVOC/HCHO (определены в base_entity.py:203-224). resolve_link_role() (base_entity.py:252) итерирует именно ALL_LINKABLE_ROLES и используется в device_grouper.py:439,492 (CO2/PM-сиблинги классифицируются как unsupported вместо linked_native) и websocket_api/devices_grouped.py:231 (add_ha_device отклоняет линк air-сенсора). При этом links.py:111 (ws_auto_link_all) матчит через per-class LINKABLE_ROLES и air-роли работают — три расходящиеся идиомы валидации одной связи (ws_set_entity_links роли вообще не валидирует). Wizard-тестов на air-роли нет (grep co2 по test_websocket_devices_grouped/test_device_grouper пуст). Docstring «Global registry of all known linkable roles» вводит в заблуждение.

**Рекомендация:** Собирать ALL_LINKABLE_ROLES автоматически из LINKABLE_ROLES всех device-классов (или из всех ROLE_*-констант), свести три пути валидации линков к одной функции, добавить wizard-тест на sensor_air с CO2-сиблингом.

#### [Major] OVERRIDABLE_CATEGORIES определён трижды с одним именем и разным содержимым: 21 категория (Python), 28 категорий (websocket_api/_common.py:36), 21+"auto" (JS-копия)

- **Место:** `custom_components/sber_mqtt_bridge/sber_entity_map.py:53`
- **Источник:** консенсус обоих ревьюеров

Проверено: sber_entity_map.py:53-74 — ручной список из 21 категории (используется Options Flow, config_flow.py:712); websocket_api/_common.py:36 — одноимённая константа sorted(CATEGORY_DOMAIN_MAP.keys()) = 28 категорий (валидация WS-схем set_override/add_ha_device); www/components/sber-entity-row.js:10-31 — ручная JS-копия 21 категории + "auto". Дрейф реален: backend через WS принимает override на любую из 28 категорий включая sensor_*, а дропдаун в таблице устройств не содержит ни одной sensor-категории — для устройства с sensor-категорией select показывает неверное значение и не позволяет корректный override. `from ... import OVERRIDABLE_CATEGORIES` даёт разную семантику в зависимости от модуля, при том что CATEGORY_DOMAIN_MAP заявлен как single source of truth.

**Рекомендация:** Одна константа, производная от CATEGORY_DOMAIN_MAP (при необходимости с флагом в CategorySpec «доступно для override»); переименовать один из Python-списков; JS получать список через существующий WS list_categories вместо хардкода.

#### [Major] SberBridge — фасад из ~15 backward-compat прокси «для тестов»: по 2-3 пути доступа к каждому коллектору, сеттеры мутируют приватные поля коллабораторов

- **Место:** `custom_components/sber_mqtt_bridge/sber_bridge.py:251`
- **Источник:** консенсус обоих ревьюеров

Проверено: _last_config_publish_time setter пишет в self._publisher._last_config_publish_time напрямую (:256-258); _redefinitions property+setter (:260-267); приватные прокси _msg_logger/_trace_collector/_diff_collector/_validation_collector (:271-289) ПЛЮС публичные trace_collector/diff_collector/validation_collector (:586-599) — два пути к каждому коллектору; sber_publisher обращается через приватные bridge._trace_collector, command_dispatcher — через bridge._devtools.* — три идиомы. _flush_redefinitions зовёт приватный self._redef_store._flush() (:1045), _on_ha_state_changed/_schedule_debounced_publish зовут приватные методы форвардера (:1052-1069) — докстринги прямо говорят «Kept for test compatibility». Обратная сторона той же проблемы: коллабораторы (SberPublisher, RedefinitionsStore) систематически читают приватные bridge._connected/_entities/_stats/_entry (22 вхождения в двух файлах), а BridgeCommandContext-Protocol легализует _-атрибуты вместо сужения интерфейса. Границы компонентов после экстракции v1.38.x фактически фиктивны.

**Рекомендация:** Перевести тесты на публичные API реальных владельцев (publisher/store/hub/forwarder), выбрать один канонический путь доступа к DevTools-коллекторам, убрать сеттеры в чужие приватные поля; коллабораторов перевести на существующие публичные свойства бриджа (is_connected, entities, stats).

#### [Major] JS-валидатор isValidSalutName разошёлся с Python-зеркалом name_utils: JS запрещает дефис и блокирует wizard, Python дефис разрешает и проверяет advisory (WARN)

- **Место:** `custom_components/sber_mqtt_bridge/www/utils.js:42`
- **Источник:** один ревьюер, подтверждено судьёй чтением кода

Подтверждено чтением обоих файлов. name_utils.py:74 (_SALUT_NAME = ^[а-яёА-ЯЁ0-9 \-]{3,33}$) с докстрингом, прямо цитирующим пример Sber-доков «Смарт-телевизор» и объявляющим проверку advisory-only. JS-регэксп в utils.js:43 (/^[а-яА-ЯЁё0-9 ]{3,33}$/) дефиса не содержит, а sber-wizard.js использует его как жёсткий гейт: _renderFooter (:605) дизейблит кнопку Add, _finish (:166) отклоняет отправку с ошибкой «Invalid name». Пользователь с именем «Смарт-ТВ» или «Люстра-1» не пройдёт мастер, хотя бэкенд такое имя опубликовал бы. name_utils.py при этом заявляет себя «Python equivalents of the frontend helpers in www/utils.js» — зеркала уже не эквивалентны.

**Рекомендация:** Добавить дефис в JS-регэксп и решить единожды, блокирующая проверка или advisory; в идеале отдавать правило валидации с бэкенда (WS), а не дублировать в двух языках.

#### [Minor] Кластер мёртвого кода после экстракций: неиспользуемые константы, поля BridgeStats, дубликат backoff-состояния, _sweep_traces, HAState, is_group_state и др.

- **Место:** `custom_components/sber_mqtt_bridge/sber_bridge.py:65`
- **Источник:** консенсус обоих ревьюеров

Всё проверено grep-ом: (1) RECONNECT_INTERVAL_MIN/MAX, MAX_MQTT_PAYLOAD_SIZE (sber_bridge.py:65-72) нигде не читаются — значения берутся из SETTINGS_DEFAULTS. (2) BridgeStats.last_ack_time (:122) никогда не пишется и не читается (ack-время живёт в AckAudit), докстринг лжёт; last_message_time (:110) пишется в :924, но не читается и не входит в as_dict(). (3) self._reconnect_interval присваивается в :450 и :805, но никогда не читается — реальный backoff в MqttClientService._reconnect_interval (mqtt_client_service.py:105-213), осиротевший дубликат состояния. (4) _sweep_traces (:601) — прокси без единого вызова (dispatcher зовёт bridge._devtools.sweep_traces() напрямую). (5) enum HAState (sber_constants.py:129) не используется вообще при докстринге модуля «Eliminates raw string literals»; BaseEntity.is_group_state (devices/base_entity.py:443), TraceCollector.set_trace_timeout (trace_collector.py:132), CustomConfig.has_override (custom_capabilities.py:86) — ни одного вызова в продакшн-коде.

**Рекомендация:** Удалить перечисленные символы (или реализовать last_message_time/last_ack_time в health-статусе, если задумывались); выбрать одну идиому (enum либо литералы) для state/feature-строк.

#### [Minor] Хвост «publish → stats → log → trace/diff/validation collectors» скопирован между publish_command_echo и publish_states (частично и в publish_config), с O(N)-пересборкой словарей на каждый publish

- **Место:** `custom_components/sber_mqtt_bridge/sber_publisher.py:117`
- **Источник:** консенсус обоих ревьюеров

Проверено: блоки :107-132 (echo) и :173-202 (states) почти идентичны — try-publish с одинаковым except (aiomqtt.MqttError, RuntimeError), publish_errors/messages_sent, _log_message, цикл record_publish, try/except record_publish_payload для diff- и validation-коллекторов; publish_config повторяет первую половину. Оба полных блока пересобирают categories и declared = {eid: ent.get_final_features_list()} для ВСЕХ entities бриджа (:124-125, :194-195) даже при публикации одного entity — лишняя работа в самом горячем пути (publish_states — самый сложный метод проекта). Правка инструментирования требует синхронных изменений в 2-3 местах.

**Рекомендация:** Вынести общий _publish_and_record(topic, payload, entity_ids) с единым хвостом инструментирования; categories/declared строить лениво или только по затронутым entity_ids.

#### [Minor] requires_bridge и requires_entry — четыре почти идентичных wrapper-блока (~120 строк copy-paste), различия только в имени lookup-функции, коде и тексте ошибки

- **Место:** `custom_components/sber_mqtt_bridge/websocket_api/_common.py:83`
- **Источник:** консенсус обоих ревьюеров

Проверено (:83-205): обе декораторные фабрики содержат по паре async_wrapped/sync_wrapped с одинаковой структурой — late-binding lookup через sys.modules по имени модуля хендлера, проверка None, connection.send_error, вызов handler'а с 4-м аргументом. Итого 4 копии одной логики; добавление логирования или третьего декоратора потребует правки в четырёх местах.

**Рекомендация:** Одна параметризованная фабрика _make_requires(lookup_name, default_fn, err_code, err_msg); requires_bridge/requires_entry — две однострочные инстанциации.

#### [Minor] Магическая строка "redefinitions" как ключ ConfigEntry.options хардкодится в 6 модулях (10 вхождений) без CONF_-константы, в отличие от остальных options-ключей

- **Место:** `custom_components/sber_mqtt_bridge/redefinitions_store.py:116`
- **Источник:** консенсус обоих ревьюеров

Проверено grep-ом: redefinitions_store.py:116, entity_registry.py:118, websocket_api/io_export.py:49,77-78, websocket_api/devices_grouped.py:277,284, diagnostics.py:60, websocket_api/status.py:360 — везде литерал, тогда как exposed_entities/entity_type_overrides/entity_links имеют CONF_* в const.py (CONF_REDEFINITIONS отсутствует). Опечатка в любом месте молча потеряет пользовательские name/room/home overrides при reload.

**Рекомендация:** Добавить CONF_REDEFINITIONS = "redefinitions" в const.py и заменить все литералы.

#### [Minor] Несогласованные идиомы применения options: 7 WS-хендлеров делают полный async_reload с задокументированным вредным UX-эффектом, от которого add-поток ушёл в _hot_reload

- **Место:** `custom_components/sber_mqtt_bridge/websocket_api/entities.py:62`
- **Источник:** консенсус обоих ревьюеров

Проверено: devices_grouped._hot_reload (:289-300) явно документирует «A full async_reload would remove the sidebar panel mid-navigation, kicking the user out of the UI», но ws_add_entities/ws_remove_entities/ws_set_type_override/ws_clear_all (entities.py:62,99,136,161), links.ws_set_entity_links/ws_auto_link_all (links.py:76,135) и io_export.ws_import (io_export.py:83) по-прежнему вызывают hass.config_entries.async_reload — операции того же уровня из той же панели дают именно тот эффект, ради избежания которого написан _hot_reload. Два подхода без объяснения различия.

**Рекомендация:** Вынести _hot_reload в _common и использовать где безопасно; там, где полный reload действительно нужен (import), задокументировать почему.

#### [Minor] Блок определения °F и конвертации Fahrenheit→Celsius продублирован дважды в sensor_air (fill_by_ha_state / update_linked_data) и третий раз инлайн-формулой в sensor_temp

- **Место:** `custom_components/sber_mqtt_bridge/devices/sensor_air.py:221`
- **Источник:** консенсус обоих ревьюеров

Проверено: sensor_air.py:221-228 и :243-251 — идентичные строки (чтение unit_of_measurement, установка _temp_unit, вызов _fahrenheit_to_celsius); sensor_temp.py:70-73 повторяет логику собственной формулой (self.temperature - 32.0) * 5.0 / 9.0 вместо переиспользования хелпера. Изменение правила определения юнита потребует трёх синхронных правок; расхождение даст разные значения для primary и linked путей. Смежное: _DEVICE_CLASS_ROUTING (:70) и _ROLE_ROUTING (:84) — два почти одинаковых словаря (field, parser), отличающиеся только ключами.

**Рекомендация:** Вынести parse_temperature(state, attrs) -> (celsius, unit) в общий модуль devices/utils и вызывать из всех трёх мест; роутинги свести к одному словарю с alias-ключами.

#### [Minor] Мёртвые распарсенные поля device-классов: light.rgb_color/xy_color, tv._media_content_id, curtain.min_position/max_position/battery_level

- **Место:** `custom_components/sber_mqtt_bridge/devices/light.py:83`
- **Источник:** консенсус обоих ревьюеров

Проверено grep-ом: LightEntity объявляет AttrSpec для rgb_color (:83-86) и xy_color (:87-90) и инициализирует поля (:110-111), но вся логика (включая LedStripEntity) работает только с hs_color — единственные вхождения этих имён в custom_components/ это их объявления. TvEntity._media_content_id (tv.py:109, :126) парсится и не используется. CurtainEntity объявляет class-level min_position/max_position/battery_level с докстрингами (curtain.py:50-56), которые никогда не читаются; battery_level по смыслу затеняет реальный _battery_level из BatteryAndSignalLinkMixin. Каждый state_changed выполняет лишний парсинг и вводит читателя в заблуждение о поддержке RGB/XY.

**Рекомендация:** Удалить неиспользуемые AttrSpec-записи и class-атрибуты (или реализовать fallback hs←rgb/xy, если он планировался).

#### [Minor] SUPPORTED_DOMAINS — ручной параллельный список доменов, разошёлся с CATEGORY_DOMAIN_MAP: отсутствует домен lock (intercom)

- **Место:** `custom_components/sber_mqtt_bridge/const.py:122`
- **Источник:** один ревьюер, подтверждено судьёй чтением кода

Подтверждено: SUPPORTED_DOMAINS (const.py:122-138) не содержит "lock", тогда как CATEGORY_DOMAIN_MAP["intercom"].domains = ("lock", "switch") (sber_entity_map.py:259-263). Fallback-пути Options Flow (config_flow.py:248,485,538,579,582,634 — EntitySelector filter, by_domain, by_label, add_all) не дадут выбрать lock-сущность, хотя wizard, работающий от CATEGORY_DOMAIN_MAP, её принимает. Классическая рассинхронизация двух ручных реестров.

**Рекомендация:** Вычислять SUPPORTED_DOMAINS как объединение spec.domains по CATEGORY_DOMAIN_MAP.

#### [Minor] CategorySpec sensor_air.device_classes (5 классов) разошёлся с _DEVICE_CLASS_ROUTING (8 классов) — HCHO-сенсор нельзя выбрать primary, хотя класс его обрабатывает

- **Место:** `custom_components/sber_mqtt_bridge/sber_entity_map.py:278`
- **Источник:** один ревьюер, подтверждено судьёй чтением кода

Подтверждено: спек sensor_air (sber_entity_map.py:278-287) перечисляет carbon_dioxide/pm1/pm25/pm10/volatile_organic_compounds, а _DEVICE_CLASS_ROUTING (devices/sensor_air.py:70-79) дополнительно умеет volatile_organic_compounds_parts (→ _hcho), temperature и humidity. _validate_primary в devices_grouped.py:190 через spec.matches() отклонит HCHO-сенсор как primary с ошибкой primary_category_mismatch. temperature/humidity исключены, вероятно, сознательно (роутинг в sensor_temp/sensor_humidity), но volatile_organic_compounds_parts выглядит как забытая синхронизация двух таблиц.

**Рекомендация:** Добавить volatile_organic_compounds_parts в device_classes спека или генерировать кортеж из _DEVICE_CLASS_ROUTING за вычетом temperature/humidity с комментарием.

#### [Minor] handle_change_group и handle_rename_device дублируют parse+persist-блок и мутируют redef_store.raw напрямую, минуя нормализацию async_update — change_group сохраняет None-значения

- **Место:** `custom_components/sber_mqtt_bridge/command_dispatcher.py:370`
- **Источник:** один ревьюер, подтверждено судьёй чтением кода

Подтверждено: оба хендлера (:353-399) повторяют одинаковый блок json.loads + debug-лог malformed payload + чтение device_id + прямая запись в bridge._redef_store.raw + schedule_persist. change_group пишет existing["home"] = data.get("home") и existing["room"] = data.get("room") без проверки (:371-372) — в персистентные options попадают ключи со значением None, тогда как канонический RedefinitionsStore.async_update (redefinitions_store.py:84-96) strip'ает строки и удаляет пустые/None значения. Три разных способа обновить один store; None-мусор безвреден лишь благодаря truthiness-фильтрации в build_devices_list_json.

**Рекомендация:** Прогонять оба хендлера через нормализацию store (async_update или sync-аналог) и вынести общий _parse_json_payload helper.

#### [Minor] CATEGORY_LABELS — третий параллельный реестр подписей категорий, неполный: нет led_strip, hvac_heater, hvac_boiler, hvac_underfloor_heating, hvac_fan

- **Место:** `custom_components/sber_mqtt_bridge/config_flow.py:79`
- **Источник:** один ревьюер, подтверждено судьёй чтением кода

Подтверждено: CATEGORY_LABELS (config_flow.py:79-96) содержит 16 записей против 21 в OVERRIDABLE_CATEGORIES — отсутствуют led_strip, hvac_heater, hvac_boiler, hvac_underfloor_heating, hvac_fan (fallback — сырой id категории в селекторе type_overrides). Параллельно существуют CATEGORY_UI_META.label_key (sber_entity_map.py:358+) для wizard и захардкоженные подписи в JS — три источника человекочитаемых имён. Также _build_entity_summary (:391) и _build_preview_text (:419) дублируют цикл entity_reg→create_sber_entity→cat_label.

**Рекомендация:** Единый источник label в CATEGORY_UI_META (дополнить недостающие), удалить CATEGORY_LABELS; общий цикл вынести в хелпер.

#### [Minor] _cmd_on_off и _cmd_air_flow_power продублированы дословно в HvacFanEntity и HvacAirPurifierEntity вместо размещения в общем FanSpeedMixin

- **Место:** `custom_components/sber_mqtt_bridge/devices/hvac_air_purifier.py:183`
- **Источник:** один ревьюер, подтверждено судьёй чтением кода

Подтверждено побайтовым сравнением: hvac_air_purifier.py:183-208 и hvac_fan.py:194-219 — идентичные тела (BOOL-проверка + _build_on_off_service_call(entity_id, "fan", on); ENUM-проверка + self._cmd_fan_speed(enum_value)), включая идентичные докстринги. Оба класса уже наследуют FanSpeedMixin, созданный для общей fan-логики.

**Рекомендация:** Перенести оба обработчика в FanSpeedMixin.

#### [Minor] Конвертация HA State → {entity_id, state, attributes} захардкожена в 4 местах вместо переиспользования HaStateForwarder._ha_state_to_dict

- **Место:** `custom_components/sber_mqtt_bridge/sber_bridge.py:1001`
- **Источник:** один ревьюер, подтверждено судьёй чтением кода

Подтверждено: идентичный трёхключевой dict строится вручную в sber_bridge._delayed_confirm (:1001-1007), entity_registry._create_entities (:196-200), entity_registry._apply_entity_links (:295-299), а канонический хелпер _ha_state_to_dict существует в ha_state_forwarder.py:149-155. Расширение внутреннего представления (context, last_updated) потребует поиска всех ручных копий.

**Рекомендация:** Вынести ha_state_to_dict(state) в общий модуль и использовать во всех четырёх местах.

#### [Info] Устаревшие docstrings: MqttServiceHooks описывает несуществующий hook get_connected_since; примеры/утверждения в ha_state_forwarder и state_diff не соответствуют коду

- **Место:** `custom_components/sber_mqtt_bridge/mqtt_client_service.py:52`
- **Источник:** консенсус обоих ревьюеров

Проверено: докстринг MqttServiceHooks (:42-53) перечисляет 4 callback'а включая get_connected_since, но у dataclass только 3 поля (on_message, on_connected, on_disconnected). Также (по отчёту A, структурно согласуется): модульный usage-пример ha_state_forwarder.py:10-18 ссылается на несуществующие bridge.linked_reverse_map/async_publish_entity_ids; state_diff.py:65 утверждает, что bridge вызывает reset_entity — не вызывает. Смежная проблема слоёв: MqttClientService.run импортирует create_ssl_context из config_flow (mqtt_client_service.py:153) — транспорт зависит от UI-модуля.

**Рекомендация:** Актуализировать докстринги; create_ssl_context вынести из config_flow в нейтральный utils-модуль.

#### [Info] Неверная аннотация: property redefinitions объявлен dict[str, str], фактически возвращает dict[str, dict]

- **Место:** `custom_components/sber_mqtt_bridge/sber_bridge.py:338`
- **Источник:** один ревьюер, подтверждено судьёй чтением кода

Подтверждено: sber_bridge.py:337-340 аннотирует dict[str, str], тогда как RedefinitionsStore.raw объявлен dict[str, dict] (redefinitions_store.py:51-56, значения — {name, room, home}), и потребители (diagnostics.py:60, status.py:360) работают с вложенными dict. Аннотация обманывает mypy и читателя.

**Рекомендация:** Исправить аннотацию на dict[str, dict]; заодно уточнить докстринг publish_states про условия применения diff.

#### [Info] async_publish_raw — третий путь публикации: пишет через сырой self._mqtt_client.publish, минуя MqttClientService.publish и учёт publish_errors

- **Место:** `custom_components/sber_mqtt_bridge/sber_bridge.py:489`
- **Источник:** один ревьюер, подтверждено судьёй чтением кода

Подтверждено: async_publish_raw (:489-506) вызывает await self._mqtt_client.publish(topic, payload) напрямую, тогда как обычные публикации идут через bridge._mqtt_service.publish, а publisher дополнительно инкрементит stats.publish_errors в except-ветке. При ошибке aiomqtt здесь publish_errors не учитывается и логирование не единообразно — инкогерентная идиома транспорта после экстракции MqttClientService.

**Рекомендация:** Переключить на self._mqtt_service.publish и переиспользовать общий error-путь.

## Сложность — оценка B

По метрикам кодовая база в отличной форме (подтверждено radon: средняя цикломатическая сложность 2.996/A на 736 блоков, лишь два D-блока — SberPublisher.publish_states D22 и build_devices_list_json D21; системно применяются декларативные таблицы ATTR_SPECS/CATEGORY_DOMAIN_MAP/_mqtt_dispatch вместо if/elif-цепочек). Весь существенный сложностной долг сконцентрирован на стыках свежей декомпозиции SberBridge (v1.38.x): извлечённые компоненты связаны с мостом по friend-class паттерну (~100 обращений к ~25 приватным атрибутам, Protocol из приватных полей), состояние соединения дублируется между мостом и транспортом с записью из 6+ мест, а сам мост на треть состоит из самоподдерживающегося backward-compat прокси-слоя «для тестов». Единственная находка с прямым пользовательским эффектом — разошедшаяся дупликация матчинга link-ролей (ALL_LINKABLE_ROLES из 5 ролей против полных LINKABLE_ROLES классов): wizard отвергает air-quality сенсоры, которые auto_link_all привязывает. Остальное — локальные дублирования (DevTools-хвост публикации, 4 копии WS-обёрток, options-flow, мёртвое поле _reconnect_interval) и два перегруженных, но читаемых D-блока. Все находки обоих ревьюеров подтвердились чтением кода, опровергнутых нет. Долг явно задокументирован и управляем, но его нужно гасить до, а не после следующих раундов экстракции.

### Находки (13)

#### [Major] Извлечённые компоненты (SberPublisher, SberCommandDispatcher, RedefinitionsStore) связаны с SberBridge по friend-class паттерну: ~100 обращений к ~25 приватным атрибутам моста; Protocol BridgeCommandContext состоит из приватных полей

- **Место:** `custom_components/sber_mqtt_bridge/command_dispatcher.py:51`
- **Источник:** консенсус обоих ревьюеров

Проверено grep-подсчётом: bridge._stats (18), bridge._entities (14), bridge._enabled_entity_ids (7), bridge._publisher (6), bridge._mqtt_service (6), bridge._redef_store (5), bridge._ack_audit (5) и ещё ~18 приватных имён читаются/мутируются из sber_publisher.py, command_dispatcher.py, redefinitions_store.py и websocket_api/*. BridgeCommandContext (command_dispatcher.py:51-72) — Protocol, декларирующий _hass, _stats, _ack_audit, _entities, _publisher, _redef_store, _devtools — «узкий интерфейс», легализующий доступ к внутренностям. SberPublisher (sber_publisher.py:72-73, 152-153, 215-227) читает bridge._connected/_mqtt_service/_entities/_redefinitions напрямую, а мост в ответ пишет в приватное поле паблишера (sber_bridge.py:256-258). Переименование любого приватного поля моста рикошетит по 5+ модулям; компоненты не тестируемы без полного моста.

**Рекомендация:** Переводить зависимости на публичные имена/явные конструкторные зависимости (паблишеру — mqtt_service, stats, devtools, get_entities вместо всего моста); в BridgeCommandContext оставить только публичные члены. Начать с самых частых — _stats и _entities.

#### [Major] SberBridge (1089 строк) на ~треть состоит из backward-compat прокси-слоя «для тестов»: ~25 делегатов, включая property-сеттер в приватное поле паблишера и сквозные вызовы приватных методов компонентов

- **Место:** `custom_components/sber_mqtt_bridge/sber_bridge.py:251`
- **Источник:** консенсус обоих ревьюеров

Проверено: _last_config_publish_time.setter пишет в self._publisher._last_config_publish_time (:256-258); _redefinitions property+setter → _redef_store.raw (:260-267); 4 приватных DevTools-прокси (:271-289) дублируются публичными trace_collector/diff_collector/validation_collector (:586-599); _flush_redefinitions → self._redef_store._flush() (:1042-1045); _on_ha_state_changed → self._state_forwarder._on_ha_state_changed (:1051-1059); _schedule_debounced_publish → приватный метод форвардера (:1061-1068); _mqtt_connection_loop сохранён «for test compatibility» (:755-767); _publish_states/_publish_config/_publish_command_echo — делегаты (:976-1089). Причина зафиксирована в докстрингах — тесты обращаются к приватным членам. Долг самоподдерживающийся: новые тесты пишутся против прокси, удорожая финальную чистку; реальной логики в крупнейшем файле проекта — около половины.

**Рекомендация:** Спланировать миграцию тестов на публичные API компонентов и удалять прокси поэтапно; запретить добавление новых прокси и пометить существующие deprecated.

#### [Major] Разошедшаяся дупликация матчинга link-ролей: resolve_link_role работает по неполному ALL_LINKABLE_ROLES (5 ролей), а ws_auto_link_all — по полным LINKABLE_ROLES класса; air-quality роли (co2/pm/tvoc/hcho) недоступны через wizard, но привязываются auto_link_all

- **Место:** `custom_components/sber_mqtt_bridge/devices/base_entity.py:227`
- **Источник:** один ревьюер, подтверждено судьёй чтением кода

Подтверждено чтением кода (уникальная находка ревьюера B). ALL_LINKABLE_ROLES (base_entity.py:227-234) документирован как «Global registry of all known linkable roles», но содержит только battery/battery_low/signal/temperature/humidity; SensorAirEntity.LINKABLE_ROLES (devices/sensor_air.py:168-179) добавляет ROLE_CO2/PM1/PM25/PM10/TVOC/HCHO (определены в base_entity.py:205-224, но НЕ включены в глобальный реестр). Путь визарда идёт через resolve_link_role (:237-255, итерирует только ALL_LINKABLE_ROLES): device_grouper.py:439 и :492 вернут "" для co2-сенсора → UNSUPPORTED; devices_grouped.py:231-235 отвергнет явно выбранный co2-сенсор ошибкой linked_role_not_accepted, хотя accepted_role_names для sensor_air содержит "co2". При этом ws_auto_link_all (websocket_api/links.py:111, :121-124) матчит lr.matches() напрямую по LINKABLE_ROLES и такие роли привяжет. Поведение зависит от пути линковки — реальный пользовательский эффект.

**Рекомендация:** Единая точка истины: генерировать ALL_LINKABLE_ROLES из объединения LINKABLE_ROLES всех классов, либо резолвить роль относительно LINKABLE_ROLES конкретного primary и удалить второй механизм.

#### [Major] Состояние соединения (_connected, _mqtt_client) дублируется между SberBridge и MqttClientService и мутируется из 6+ мест; async_publish_raw публикует через сырой клиент в обход guard'а сервиса

- **Место:** `custom_components/sber_mqtt_bridge/sber_bridge.py:769`
- **Источник:** один ревьюер, подтверждено судьёй чтением кода

Подтверждено (уникальная находка ревьюера A): MqttClientService владеет собственными _client/_connected (mqtt_client_service.py:107-108, 160-162, 174-175, 207-208) и guard'ом в publish() (:223-226). Мост зеркалит их в self._connected/self._mqtt_client: __init__ (:177-180), _mqtt_connection_loop finally (:765-767), _handle_mqtt_connected (:780) + _mark_connected (:804), _handle_mqtt_disconnected (:799), _handle_disconnect (:894-895), async_stop (:675). Читатели смешаны: SberPublisher проверяет bridge._connected (sber_publisher.py:73, :153, :216), а async_publish_raw (sber_bridge.py:499-504) публикует через bridge._mqtt_client.publish напрямую, минуя MqttClientService.publish. Между сбросом флагов сервиса в _after_error и обновлением флагов моста в хуке — await-граница: окно, где bridge._connected=True при мёртвом клиенте (в обычном пути деградирует в пойманный RuntimeError/MqttError, в async_publish_raw ошибка уходит вызывающему нефильтрованной).

**Рекомендация:** Сделать MqttClientService единственным владельцем: bridge.is_connected → self._mqtt_service.is_connected, зеркальные поля свести к thin-property, async_publish_raw переключить на _mqtt_service.publish().

#### [Minor] DevTools-хвост публикации (trace/diff/validation + пересборка categories/declared по ВСЕМ entity) скопирован в publish_command_echo и publish_states; на каждый publish — O(N) работа

- **Место:** `custom_components/sber_mqtt_bridge/sber_publisher.py:117`
- **Источник:** консенсус обоих ревьюеров

Проверено: блоки :117-132 и :187-202 идентичны (различаются только суффиксом «(echo)» в логах): record_publish на каждый eid, try/except вокруг diff_collector.record_publish_payload и validation_collector.record_publish_payload с построением двух полных словарей {eid: ent.category} и {eid: ent.get_final_features_list()} по всем entities даже при публикации одной сущности (get_final_features_list пересчитывает список фич). Основной вклад в D/C-блоки: publish_states D(22), publish_command_echo C(19) — radon подтверждён. Лишняя нагрузка горячего пути при частых state-изменениях.

**Рекомендация:** Вынести общий _record_devtools(topic, payload_str, entity_ids); строить categories/declared только для затронутых entity_ids или кэшировать до перезагрузки entity-набора.

#### [Minor] build_devices_list_json — ~100 строк, radon D(21): конвейер из 7 инлайн-пост-обработок device_data в одном цикле

- **Место:** `custom_components/sber_mqtt_bridge/sber_protocol.py:96`
- **Источник:** консенсус обоих ревьюеров

Проверено чтением :96-197: внутри одного for — skip-фильтры, to_sber_state с try/except, наложение redefinitions (3 if, :153-160), дефолты home/room (:162-166), auto parent_id (:168-169), inject ha_serial (:171-172), фильтрация None, advisory-предупреждения, per-device pydantic-валидация с exclude. Каждый шаг тривиален, но конкатенация даёт CC 21 (один из двух D-блоков на 736 блоков проекта); порядок и взаимовлияние правил видны только при полном прочтении, пошаговое тестирование возможно только через полный payload.

**Рекомендация:** Извлечь _build_one_device(entity, redef, defaults, ...) -> dict | None; build_devices_list_json оставить как цикл+сборку — уберёт D-рейтинг без изменения поведения.

#### [Minor] OptionsFlow пять раз копирует ручное сохранение CONF_ENTITY_TYPE_OVERRIDES при async_create_entry; блок entity_data + create_sber_entity для определения категории дублируется минимум в 6 местах проекта

- **Место:** `custom_components/sber_mqtt_bridge/config_flow.py:481`
- **Источник:** консенсус обоих ревьюеров

Проверено grep: «CONF_ENTITY_TYPE_OVERRIDES: self.config_entry.options.get(...)» повторяется в :481, :490, :525, :566, :622 (+ запись новых в :694) — забытая строка в новом шаге options-flow молча сотрёт overrides пользователя. Блок «entity_registry → entity_data dict → create_sber_entity → .category» скопирован в config_flow :406-412, :434-440, :722-727, а также в device_grouper._instantiate_primary, devices_grouped._validate_primary (:195-208) и ws_suggest_links; наборы полей entity_data между копиями различаются — новое обязательное поле легко обновить не везде.

**Рекомендация:** Хелперы _create_entry_preserving_overrides(data) в options-flow и build_probe_entity/resolve_sber_category в sber_entity_map для всех шести мест.

#### [Minor] RedefinitionsStore.raw отдаёт живой внутренний dict, мутируемый из трёх внешних мест — в том числе в обход нормализации async_update

- **Место:** `custom_components/sber_mqtt_bridge/redefinitions_store.py:51`
- **Источник:** один ревьюер, подтверждено судьёй чтением кода

Подтверждено (уникальная находка B): raw property/setter (redefinitions_store.py:50-58) отдаёт/заменяет живой dict. Мутации извне: command_dispatcher.handle_change_group (:370-374) пишет existing["home"]=data.get("home") — может сохранить None и минует strip/удаление пустых значений из async_update (:84-94); handle_rename_device (:396-398) — setdefault+запись; SberBridge._load_exposed_entities через сеттер _redefinitions (sber_bridge.py:265-267, :704) целиком заменяет dict при reload. Флаги _dirty/_timer — скрытое состояние, инварианты которого зависят от дисциплины внешних вызывающих; persisted options могут получить ненормализованные значения (None вместо отсутствия ключа).

**Рекомендация:** Закрыть raw: методы merge_fields(entity_id, fields)/replace_all(dict) с единой нормализацией и schedule_persist внутри.

#### [Minor] requires_bridge и requires_entry — четыре почти идентичных тела обёрток (~125 строк) с late-binding хаком через sys.modules ради патчинга в тестах

- **Место:** `custom_components/sber_mqtt_bridge/websocket_api/_common.py:83`
- **Источник:** один ревьюер, подтверждено судьёй чтением кода

Подтверждено чтением _common.py:83-208 (уникальная находка A): обе декораторные фабрики дублируют друг друга (async/sync × bridge/entry), различаясь только именем lookup-функции (get_bridge/get_config_entry), кодом и текстом ошибки. В каждом из четырёх врапперов повторён трюк sys.modules.get(_module_name) + getattr для уважения test-level monkeypatch — неочевидная динамика в production-коде, добавленная исключительно для тестов и скопированная четырежды.

**Рекомендация:** Одна параметризованная фабрика _make_requires(lookup_name, error_code, error_msg); патчинг в тестах — через фикстуру, подменяющую функцию в _common.

#### [Minor] Поле bridge._reconnect_interval — мёртвое дублирование состояния: записывается в двух местах, никогда не читается

- **Место:** `custom_components/sber_mqtt_bridge/sber_bridge.py:450`
- **Источник:** один ревьюер, подтверждено судьёй чтением кода

Подтверждено grep по всему проекту включая tests/ (уникальная находка A): присваивания только в _load_settings_from_options (sber_bridge.py:450) и _mark_connected (:805); ни одного чтения bridge._reconnect_interval нигде. Реальный backoff живёт в MqttClientService._reconnect_interval (mqtt_client_service.py:105, :162, :212-213), а _handle_disconnect читает self._mqtt_service.reconnect_interval (sber_bridge.py:900). Рудимент до-экстракционной эпохи, вводящий в заблуждение при чтении.

**Рекомендация:** Удалить оба присваивания.

#### [Info] sber-wizard.js — 914 строк, крупнейший фронтенд-компонент: state machine трёх шагов, сетевые вызовы и все рендеры в одном LitElement-классе

- **Место:** `custom_components/sber_mqtt_bridge/www/components/sber-wizard.js:1`
- **Источник:** консенсус обоих ревьюеров

Подтверждено wc: 914 строк, вдвое больше остальных компонентов www/ (sber-devtools.js 649). Внутренне декомпозирован (_renderStep1/2/3, _renderDeviceCard и т.д.), переходы — числовой _step с рассыпанными if. Для no-build SPA — осознанный компромисс, но файл продолжит расти с каждым новым шагом/полем.

**Рекомендация:** При следующем расширении визарда вынести шаги в дочерние компоненты (sber-wizard-step-category / -devices / -confirm) с передачей состояния через свойства.

#### [Info] ws_auto_link_all — CC 19, тройная вложенность циклов, полный проход по entity_registry для каждого exposed primary (O(P×E)) без await между итерациями

- **Место:** `custom_components/sber_mqtt_bridge/websocket_api/links.py:115`
- **Источник:** один ревьюер, подтверждено судьёй чтением кода

Подтверждено (уникальная находка B): links.py:103-124 — for primary → for e in entity_reg.entities.values() → for lr in linkable_roles; radon C(19). Для инсталляций с тысячами entities и десятками exposed — тысячи×десятки итераций в event loop. Функционально терпимо (редкая ручная операция), но группировка реестра по device_id одним проходом (как в device_grouper.list_for_category:189-198) убрала бы и вложенность, и квадратичность; это третья инлайн-реализация матчинга ролей в кодовой базе.

**Рекомендация:** Сгруппировать реестр по device_id до внешнего цикла; переиспользовать логику grouper'а.

#### [Info] _find_cross_device_links сканирует все устройства и их entities для каждого DeviceGroup — list_for_category в худшем случае O(devices × total_entities)

- **Место:** `custom_components/sber_mqtt_bridge/device_grouper.py:463`
- **Источник:** один ревьюер, подтверждено судьёй чтением кода

Подтверждено (уникальная находка A): list_for_category вызывает _build_group на каждое устройство с подходящим primary; каждый вызов проходит all_entities_by_device целиком (device_grouper.py:483-507) с resolve_link_role на каждую entity. Для «широкой» категории (relay) на крупной инсталляции — сотни тысяч итераций на один WS-запрос визарда. Пока это разовый интерактивный запрос — приемлемо.

**Рекомендация:** Построить индекс role → [entries] один раз в list_for_category и передавать в _build_group.

## Качество тестов — оценка B

Сьют из 2239 тестов двухслойный по качеству. Доменный слой покрыт образцово: devices/ — 33 модуля на 91-100% (большинство 100%), сильные negative-тесты (malformed payloads, out-of-range), compliance-тесты против выгруженных схем Sber, snapshot-контроль сериализации, детерминированные integration-flow тесты с явным управлением таймерами. Но инфраструктурный слой систематически недотестирован, и дыры концентрируются ровно там, где живут race-conditions и потеря пользовательских данных: MQTT-транспорт с reconnect/backoff — ноль тестов (52%), lifecycle моста и интеграции (async_start/stop, setup/unload — 42-72%), grace-timeout fallback ack-guard (единственная защита от вечной блокировки команд после reconnect — 0 тестов), loader entity links (59%, потеря пользовательских связей при рестарте), мутирующие WS-эндпоинты панели (23-58%). Усугубляют два процессных дефекта: CI полностью исключает тесты config_flow (они падают локально из-за отсутствующего hass_frontend — главный UI настройки без регрессионной защиты), и coverage-гейт деградировал до fail_under=50 при задекларированных и фактических 80+%, позволяя дырам расти незаметно. Все ключевые цифры подтверждены реальным прогоном coverage (total 82.15%). Итог — хорошая защита протокола при слабой защите связующего кода и эрозии процессных гейтов; путь до A конкретен и конечен.

### Находки (13)

#### [Major] CI исключает все тесты config_flow (-k "not test_config_flow"), и они падают локально — config_flow.py (753 строки) фактически без регрессионной защиты (0% coverage при CI-выборке).

- **Место:** `.github/workflows/ci.yaml:80`
- **Источник:** консенсус обоих ревьюеров

Проверено: pytest в CI запускается с -k "not test_config_flow"; локальный запуск tests/hacs/test_config_flow.py падает с ModuleNotFoundError: No module named 'hass_frontend' (manifest.json объявляет dependencies: ["frontend", "http"], пакет фронтенда не установлен в test-окружении). Coverage-прогон с CI-выборкой даёт config_flow.py 0% (267/267 строк не покрыты). OptionsFlow (выбор entities — главный пользовательский UI настройки) не имеет ни одного теста даже номинально. Любая регрессия в setup/options UI уедет в релиз незамеченной.

**Рекомендация:** Замокать/удовлетворить frontend-зависимость в тестовом окружении (home-assistant-frontend в test-deps или fixture-обход), убрать -k из CI, добавить тесты шагов OptionsFlow и reauth.

#### [Major] Транспортное ядро MqttClientService не имеет ни одного теста (52%): reconnect-петля run(), exponential backoff (_after_error) и RuntimeError-guards publish/subscribe не покрыты.

- **Место:** `custom_components/sber_mqtt_bridge/mqtt_client_service.py:145`
- **Источник:** консенсус обоих ревьюеров

Проверено: grep по tests/hacs/ не находит ни одного упоминания MqttClientService/mqtt_client_service. Coverage подтверждает непокрытые строки 153-175 (весь while-цикл run(): connect, сброс backoff на reconnect_min, обработка MqttError/CancelledError/OSError), 207-214 (_after_error: sleep(interval), удвоение с клэмпом на reconnect_max, выход по keep_running/_running), 193-196 (_consume_messages), 226 и 230-233 (RuntimeError при publish/subscribe в disconnected). Регрессия backoff (потеря удвоения/клэмпа/сброса) даст reconnect-шторм на боевой брокер Sber и не будет поймана.

**Рекомендация:** Добавить test_mqtt_client_service.py с фейковым aiomqtt.Client (async context manager, поднимающий MqttError) и мокнутым asyncio.sleep: последовательность backoff-интервалов, сброс на min после успешного connect, выход по stop() и on_disconnected→False, RuntimeError у publish() в disconnected.

#### [Major] Жизненный цикл моста и интеграции не тестируется: async_start/async_stop, handshake после коннекта, _handle_disconnect, payload-size guard и async_setup_entry/async_unload_entry — все без тестов.

- **Место:** `custom_components/sber_mqtt_bridge/sber_bridge.py:623`
- **Источник:** консенсус обоих ревьюеров

Coverage подтверждает: sber_bridge.py 72% с непокрытыми 630-648 (async_start: instance_id prefix, connection task, ветка EVENT_HOMEASSISTANT_STARTED), 654-675 (async_stop: unsubscribe forwarder, отмена ack-audit и connection task), 740-753 (_handle_mqtt_connected handshake), 894-915 (_handle_disconnect: сброс состояния, reconnect_count, check_and_create_issues, возврат False при !_running), 933-939 (отбрасывание payload > max_payload_size). __init__.py покрыт на 42% (58-68, 85-114, 127-135, 163-179): async_setup_entry/async_unload_entry не вызываются ни одним тестом. Это самые race-опасные участки (reconnect во время работы, shutdown с висящими таймерами, reload интеграции); grep по тестам подтверждает отсутствие ссылок на async_start/_handle_disconnect.

**Рекомендация:** Lifecycle-тесты через hass fixture: setup entry → unload entry с проверкой отписки listeners и отмены задач; эмуляция connect→disconnect→reconnect через hooks MqttClientService; отдельный тест payload > max_payload_size.

#### [Major] Grace-timeout fallback ack-guard не тестируется: _on_timeout (91-93) и timeout_check (84-86) не покрыты — сломанный fallback навсегда заблокирует входящие команды Sber после reconnect.

- **Место:** `custom_components/sber_mqtt_bridge/reconnect_ack_guard.py:89`
- **Источник:** консенсус обоих ревьюеров

Coverage подтверждает непокрытые строки 84-86 (timeout_check: очистка по дедлайну) и 91-93 (_on_timeout: авто-сброс по таймеру loop.call_later из activate()). test_ack_audit.py проверяет только activate/acknowledge/cancel и audit-таймер; отдельного test_reconnect_ack_guard.py нет, grep timeout_check/_on_timeout по tests/ пуст. Если Sber после reconnect не пришлёт status_request/config_request, этот fallback — единственная защита от вечной блокировки команд («устройства не реагируют»), и его регрессия не будет поймана ни одним тестом.

**Рекомендация:** Тесты с коротким grace_timeout и контролем времени (fake loop.call_later или monkeypatch time.monotonic): активировать guard, дождаться таймера, assert is_awaiting is False; плюс ветка timeout_check().

#### [Major] Мутирующие WS-эндпоинты панели почти не тестируются: links.py 23%, entities.py 33%, status.py 38%, io_export.py 46%, settings.py 55%, raw.py 58%, log.py 67%, replay.py 68%.

- **Место:** `custom_components/sber_mqtt_bridge/websocket_api/links.py:46`
- **Источник:** консенсус обоих ревьюеров

Coverage подтверждает: ws_set_entity_links/ws_auto_link_all (links.py 46-78, 95-137) — ноль тестов (grep set_entity_links/auto_link_all по tests/ пуст); entities.py: тела ws_add_entities/ws_remove_entities/ws_set_type_override/ws_clear_all полностью непокрыты (48-64, 82-101, 124-138, 155-163); io_export.py: ws_import и ws_update_redefinitions (70-85, 110-122) непокрыты; status.py 38% (2 теста на один handler из ~8). Это write-пути, мутирующие config entry options: регрессия (например, некорректный импорт затирает entity-список) молча ломает конфигурацию пользователя, при этом наличие test_websocket_* файлов создаёт ложное впечатление покрытия WS-слоя.

**Рекомендация:** Хотя бы happy-path + один invalid-input тест на каждый мутирующий handler с проверкой итоговых options config entry и вызова reload/republish, предпочтительно через hass_ws_client fixture.

#### [Major] Coverage-гейт fail_under=50 противоречит задекларированному в CLAUDE.md «Coverage minimum: 80% (enforced by pyproject.toml fail_under)» — гейт пропустит потерю трети покрытия.

- **Место:** `pyproject.toml:86`
- **Источник:** консенсус обоих ревьюеров

Проверено: [tool.coverage.report] fail_under = 50; CI не добавляет --cov-fail-under. Фактический прогон даёт 82.15% total — деградация на 32 п.п. (например, потеря всех тестов devices/) пройдёт CI зелёным. Разрыв «заявлено 80 / реально 50» — эрозия гейта, при том что дыры уже концентрируются в инфраструктурных модулях (transport 52%, lifecycle 42-72%, WS 23-58%).

**Рекомендация:** Поднять fail_under до 80 (текущие 82.15% дают запас) и синхронизировать с CLAUDE.md; рассмотреть diff-coverage для новых модулей.

#### [Major] SberEntityLoader покрыт на 59%: восстановление entity links из options (_apply_entity_links), привязка device registry, YAML- и room-overrides без тестов — включая guard от «linked одновременно primary».

- **Место:** `custom_components/sber_mqtt_bridge/entity_registry.py:267`
- **Источник:** консенсус обоих ревьюеров

Coverage подтверждает непокрытые строки 210-226 (_apply_yaml_overrides), 238-257 (device registry: MAC, hw/sw version, parent), 267-304 (_apply_entity_links: фильтрация несуществующих primary, guard дубликата primary/linked, начальное заполнение linked state), 342-346 (room overrides). test_entity_linking.py тестирует только уровень device-классов (LinkableRole/update_linked_data), но не путь загрузки loader'а — grep SberEntityLoader/_apply_entity_links по tests/ пуст. Регрессия здесь либо молча теряет настроенные пользователем связи при рестарте, либо даёт двойную публикацию устройства в облако — класс ошибок, из-за которых Sber молча отклоняет устройства.

**Рекомендация:** Тесты SberEntityLoader.load() с hass fixture и мокнутыми er/dr registries: options с CONF_ENTITY_LINKS (вкл. случай linked==primary), отсутствующий linked state, device с MAC/area, YAML и room overrides.

#### [Minor] Тесты аудита используют реальные wall-clock sleep (0.05–0.35 с) — флейк-риск на загруженном CI-раннере и ~0.65 с лишнего времени прогона.

- **Место:** `tests/hacs/test_ack_audit.py:97`
- **Источник:** консенсус обоих ревьюеров

Проверено (строки 86-118): test_reschedule_cancels_previous_timer делает schedule_audit(audit_delay=0.2) → asyncio.sleep(0.05) → reschedule → sleep(0.35); если event loop притормозит >150 мс между вызовами (shared-runner, pytest-xdist), первый таймер успеет сработать и calls == [1, 1] — ложное падение. Аналогично test_scheduled_audit_runs_after_delay и test_cancel_prevents_audit_from_running (окна 0.05/0.15). Остальной suite корректно управляет временем через async_fire_time_changed — эти тесты исключение.

**Рекомендация:** Детерминированное время: fake loop.call_later / прямой вызов callback / freezegun, по образцу test_integration_flows.

#### [Minor] Тесты обходят публичную поверхность: патчинг приватного метода коллаборатора (bridge._state_forwarder._schedule_debounced_publish) и вызов WS-handlers через __wrapped__.__wrapped__ (18 использований в 3 файлах).

- **Место:** `tests/hacs/test_bridge.py:320`
- **Источник:** консенсус обоих ревьюеров

Проверено: test_bridge.py строки 320 и 346 патчат _schedule_debounced_publish и ассертят вызов мока — тест зелёный, даже если метод перестанет приводить к реальной MQTT-публикации, и упадёт при переименовании приватного имени. Отдельно: 18 использований __wrapped__ в test_websocket_status.py, test_websocket_devices_grouped.py, test_replay_inject.py снимают декораторы @websocket_command/@async_response — voluptuous-схемы команд и admin-обёртки не исполняются ни в одном тесте, ошибка схемы даст invalid_format только в рантайме панели.

**Рекомендация:** Ассертить наблюдаемый эффект (mqtt publish после async_fire_time_changed); для WS — хотя бы по одному тесту на команду через hass_ws_client fixture (полный стек с валидацией схемы) либо общий helper, изолирующий __wrapped__-цепочку.

#### [Minor] В HaStateForwarder (88%) не покрыты exception-путь process_state_change (195-197), republish config при переходе entity в available (200-201) и unsubscribe_all с висящим debounce-таймером (129-130).

- **Место:** `custom_components/sber_mqtt_bridge/ha_state_forwarder.py:195`
- **Источник:** консенсус обоих ревьюеров

Coverage подтверждает пропуски 129-130, 195-197, 200-201. Основные пути (debounce, linked routing) покрыты интеграционно, но: если детекция «entity стал доступен» (unfilled→filled → republish_config_new_entity) сломается, устройства, недоступные на старте HA, никогда не попадут в Sber config; регрессия unsubscribe_all даст publish после reload/stop со stale-списком entity.

**Рекомендация:** Три юнит-теста: state change с исключением из process_state_change (publish не происходит); переход is_filled_by_state False→True (создан republish task); schedule publish → unsubscribe_all → fire timers → publish не вызван.

#### [Minor] test_real_hass_debounce_coalesces_rapid_changes заявляет «три изменения → один publish», но ассертит len(payloads) >= 1 — коалесцирование debounce фактически не проверяется нигде в suite.

- **Место:** `tests/hacs/test_integration_flows.py:1642`
- **Источник:** один ревьюер, подтверждено судьёй чтением кода

Подтверждено чтением: docstring (строки 1600-1601) обещает «single publish», ассерт на строке 1642 — assert len(payloads) >= 1, далее проверяется только on_off последнего payload. Если debounce сломается и каждый из трёх state changes даст отдельный publish, тест останется зелёным. В остальных ~20 местах паттерн >= 1 приемлем, но здесь количество публикаций — суть теста; единственная заявленная проверка коалесцирования не защищает от регрессии.

**Рекомендация:** Ассертить точное число publish после async_fire_time_changed (== 1) или сравнивать счётчик вызовов mqtt publish до/после.

#### [Minor] Два дублирующих snapshot-каталога (tests/hacs/snapshots/ и tests/hacs/__snapshots__/) с байт-идентичным .ambr синхронизируются вручную.

- **Место:** `tests/hacs/snapshots/test_protocol_snapshots.ambr:1`
- **Источник:** один ревьюер, подтверждено судьёй чтением кода

Подтверждено: md5 обоих test_protocol_snapshots.ambr идентичен (04145b67...). Какой каталог использует syrupy, зависит от его версии; при --snapshot-update обновится только один, второй тихо устареет — прогон под другой версией syrupy начнёт падать или проверять устаревший baseline.

**Рекомендация:** Удалить legacy-каталог (пин syrupy >=5,<6 уже есть в constraints), оставив один source of truth.

#### [Info] Тестовые файлы-«свалки», названные по фазам проекта (test_p4_tasks.py, test_devices_protocol_p2.py, test_devices_new_features.py), затрудняют поиск покрытия конкретного поведения.

- **Место:** `tests/hacs/test_p4_tasks.py:1`
- **Источник:** один ревьюер, подтверждено судьёй чтением кода

Подтверждено: test_p4_tasks.py (452 строки) смешивает TestRepairsEntityNotFound, TestRepairsConnectionIssues, TestFeaturesOverride, TestYamlFeaturesConfig, TestAutoRepublishConfig, TestPersistRedefinitions; test_devices_new_features.py — 527 строк разнородных проверок. Названия отражают историю разработки, а не тестируемое поведение — при добавлении фич непонятно, где лежат существующие тесты (риск дубликатов и пропусков).

**Рекомендация:** Раскидать содержимое по поведенческим файлам (test_repairs_*, test_redefinitions_*, test_devices_<class>) при следующем рефакторинге тестов.

### Опровергнутые заявки ревьюеров

- ~~Отчёт A: «coverage config_flow.py = 15%» (уточнение, не опровержение находки)~~ — Не опровергнута сама находка (она в consensus), но цифра неточна: при CI-эквивалентной выборке (-k "not test_config_flow") coverage config_flow.py = 0% (267/267 строк не исполняются) — ситуация хуже заявленной. 15%, вероятно, получены при прогоне с частично импортированным модулем.

## Frontend (www/, LitElement SPA) — оценка B

Фронтенд (www/, ~6500 строк, no-build LitElement SPA) архитектурно дисциплинирован: sber-panel — чистый координатор на 562 строки, 16 компонентов, однонаправленный поток (props вниз, CustomEvent вверх), vendored lit вместо хрупкого хака с прототипами HA, нулевая XSS-поверхность (подтверждено: ни одного innerHTML/unsafeHTML/eval), ошибки WS почти везде доводятся до пользователя. Оба ревьюера оказались точны — все находки подтвердились чтением кода, опровергнутых нет. Два системных дефекта: (1) асимметрия жизненного цикла подписок — панель явно рассчитана на detach/re-attach при HA-навигации и компенсирует это для себя, но пять DevTools-компонентов с одноразовым guard _hassReady после reattach молча теряют live-подписки навсегда; (2) полное отсутствие клавиатурной доступности и ARIA (0 вхождений aria-/role=/tabindex во всём www/ — вкладки, карточки визарда, сортировка, модалки без Escape/focus-trap). Заметный, но локальный долг: неограниченный рост live-буферов в 4 из 5 подписчиков (плюс дублирующая подписка devtools+replay на один поток), вездесущий setTimeout(1500) как негарантированный контракт с бэкендом, мёртвый shared-CSS при ручном дублировании стилей в 6+ местах, невалидная table-разметка, работающая на foster-parenting парсера, и неатомарный multi-add визарда. Главные риски — молча замерзающие DevTools-ленты после навигации и недоступность панели без мыши; всё остальное — качество жизни и сопровождение.

### Находки (14)

#### [Major] Все 5 подписочных DevTools-компонентов навсегда теряют WS-подписку после detach/re-attach: одноразовый guard _hassReady блокирует пересоздание, а disconnectedCallback её убивает.

- **Место:** `custom_components/sber_mqtt_bridge/www/components/sber-devtools.js:65`
- **Источник:** консенсус обоих ревьюеров

Проверено кодом: паттерн `updated(): if (changedProps.has("hass") && this.hass && !this._hassReady) { this._hassReady = true; this._subscribe(); }` + `disconnectedCallback(): this._unsubscribe()` идентично повторён в sber-devtools.js:59-67, sber-traces.js:51-59, sber-state-diff.js:34-42, sber-replay.js:69-77, sber-validation.js:43-51 (в sber-settings.js:78-80 тот же guard для одноразовой загрузки — мягче). Родительский sber-panel.js:71-72 явно рассчитан на re-attach того же инстанса при HA-навигации («Re-fetch immediately when element is re-attached») и компенсирует это для себя (_fetchAll + interval в connectedCallback), но у детей после reattach _hassReady=true и _unsub=null — подписка не восстанавливается, ошибок нет, живые ленты (MQTT log, traces, diffs, validation, replay-list) молча замирают. Переключение вкладок внутри панели баг не триггерит (lit создаёт новые инстансы), сценарий — навигация HA прочь от панели и обратно.

**Рекомендация:** Подписываться в connectedCallback (с проверкой this.hass) симметрично unsubscribe в disconnectedCallback, как сделано с interval в sber-panel; guard оставить только `if (this._unsub) return`.

#### [Major] Панель полностью недоступна с клавиатуры: во всём www/ (кроме vendor) ноль вхождений aria-*, role= и tabindex; все интерактивные элементы — div/span/th с @click.

- **Место:** `custom_components/sber_mqtt_bridge/www/sber-panel.js:465`
- **Источник:** консенсус обоих ревьюеров

Подтверждено grep (0 хитов). Вкладки панели (sber-panel.js:465-476) — div @click без role=tab/tabindex/keydown; карточки категорий и устройств визарда (sber-wizard.js:~360, ~429), сортируемые th (sber-device-table.js:390-414), collapse-заголовки (sber-devtools.js, sber-diagnose.js, sber-traces.js), кликабельное имя устройства span.name-link (sber-entity-row.js:329) — так же. Модалки (sber-wizard, sber-link-dialog, sber-detail-dialog) без role=dialog/aria-modal, без Escape и focus-trap; sber-toast без aria-live. Пользователь без мыши не может переключить вкладку, пройти визард или открыть детали устройства; screen reader не видит структуру вообще (A оценил minor, B major; принято major — отсутствие полное, а не частичное).

**Рекомендация:** Заменить кликабельные div на button (или добавить role/tabindex/keydown), вкладкам role=tablist/tab + aria-selected, диалогам role=dialog + aria-modal + Escape + возврат фокуса, toast — role=status/aria-live=polite.

#### [Minor] Live-буферы четырёх подписчиков растут без ограничения: каждый append копирует весь массив и перерисовывает всю таблицу; cap есть только в sber-traces.

- **Место:** `custom_components/sber_mqtt_bridge/www/components/sber-devtools.js:79`
- **Источник:** консенсус обоих ревьюеров

Подтверждено: `this._messages = [...this._messages, event.message]` (sber-devtools.js:79, sber-replay.js:89), `this._diffs = [...this._diffs, event.diff]` (sber-state-diff.js:56 — комментарий «trust the backend to trim» неверен: бэкенд обрезает только snapshot), `this._recent = [...this._recent, ...event.issues]` (sber-validation.js:77). Только sber-traces.js ограничивает буфер (MAX_TRACES=250, строки 69, 92-93). Открытая на часы вкладка DevTools при активном MQTT-трафике — неограниченный рост памяти и O(n)-перерисовка всё более длинных таблиц на каждое сообщение.

**Рекомендация:** Применить slice(-MAX) при каждом live-append по образцу sber-traces._applyLiveUpdate во всех четырёх подписчиках.

#### [Minor] Синхронизация с бэкендом построена на магическом `await new Promise((r) => setTimeout(r, 1500))` — 7 дублей в панели + 1 в detail-dialog, race-prone скрытый контракт.

- **Место:** `custom_components/sber_mqtt_bridge/www/sber-panel.js:141`
- **Источник:** консенсус обоих ревьюеров

Подтверждено: sber-panel.js:141, 158, 171, 204, 259, 275, 299 (после remove/set_override/clear_all/import/auto_link/links-saved/wizard-complete) + sber-detail-dialog.js:532. Если бэкенд применяет медленнее 1.5с — пользователь видит устаревшую таблицу до следующего 15-секундного poll («устройство не удалилось»); если быстрее — лишние 1.5с спиннера на каждое действие. Контракт «бэкенд успеет за 1500мс» ничем не гарантирован.

**Рекомендация:** WS-команды мутаций должны отвечать после применения (или возвращать свежий список) — тогда refetch сразу; как минимум вынести задержку в один именованный хелпер.

#### [Minor] Кастомный элемент <sber-entity-row> внутри <tr> foster-parent'ится HTML-парсером наружу: класс-биндинг на <tr> — мёртвый код, в DOM остаются пустые stray-<tr>.

- **Место:** `custom_components/sber_mqtt_bridge/www/components/sber-device-table.js:421`
- **Источник:** консенсус обоих ревьюеров

Подтверждено кодом: шаблон `<tr class="${d.is_online ? "online" : "offline"}"><sber-entity-row ...></sber-entity-row></tr>` (строки 421-433). Парсер не допускает не-td/th внутри <tr> — элемент выносится из строки, классы tr.online/offline нигде не стилизуются (CSS определяет .row-online/.row-offline на :host). Реальная строка — сам host с display:table-row, а online/offline навешиваются императивным classList-хаком в updated() (sber-entity-row.js:303-313). Работает по счастливому стечению поведения парсера, любая перестановка шаблона ломает таблицу неочевидно.

**Рекомендация:** Убрать обёртку <tr> и рендерить <sber-entity-row> напрямую в <tbody> (что фактически и происходит), задокументировав display:table-row контракт, либо заменить custom element рендер-функцией с настоящим <tr>.

#### [Minor] DIALOG_STYLES_CSS и filterEntities — мёртвые экспорты utils.js; диалоговые/кнопочные стили вместо этого продублированы вручную в 6+ компонентах с расходящимися значениями.

- **Место:** `custom_components/sber_mqtt_bridge/www/utils.js:67`
- **Источник:** консенсус обоих ревьюеров

Подтверждено grep: из utils.js импортируются только slugify и isValidSalutName (единственный потребитель — sber-wizard.js:15). DIALOG_STYLES_CSS (utils.js:67-116) и filterEntities (utils.js:53) не используются никем. При этом .overlay/.dialog/.close-btn/.btn-* скопированы почти дословно в sber-wizard.js:637+, sber-link-dialog.js:163+, sber-detail-dialog.js, а .btn-* повторяются в sber-toolbar, sber-devtools, sber-traces, sber-replay, sber-diagnose, sber-settings с разными радиусами/padding. В sber-devtools.js две параллельные реализации копирования в буфер (_copyToClipboard/_fallbackCopy и _copyPayload).

**Рекомендация:** Вынести общий CSS в shared-модуль (static styles = [sharedStyles, css`...`]) и удалить мёртвые экспорты; унифицировать кнопки и одну функцию копирования.

#### [Minor] Multi-add в визарде не атомарен: при падении N-го add_ha_device первые уже добавлены, wizard-complete не диспатчится, а повторный Finish пере-отправит весь батч.

- **Место:** `custom_components/sber_mqtt_bridge/www/components/sber-wizard.js:183`
- **Источник:** консенсус обоих ревьюеров

Подтверждено: _finish() последовательно вызывает add_ha_device в цикле (sber-wizard.js:183-197); catch ставит только общий `_error = "Add failed: ..."`. При ошибке в середине: таблица не обновляется, хотя часть устройств создана; повторное нажатие отправит уже добавленные primaries заново; linked-сенсоры прикрепляются только к первому primary (флаг linkedAttached), при retry уйдут к уже существующему устройству.

**Рекомендация:** Запоминать успешно добавленные primaries и исключать их из retry; при частичной ошибке всё равно диспатчить wizard-complete с фактическим added_count; показывать, на каком entity упало.

#### [Minor] sber-devtools и sber-replay держат две параллельные серверные подписки на один и тот же поток subscribe_messages на одной вкладке DevTools (уникальная находка B, подтверждена).

- **Место:** `custom_components/sber_mqtt_bridge/www/components/sber-replay.js:84`
- **Источник:** один ревьюер, подтверждено судьёй чтением кода

Подтверждено: _renderDevtools() (sber-panel.js:537-547) монтирует оба компонента одновременно, и оба вызывают hass.connection.subscribeMessage с type: "sber_mqtt_bridge/subscribe_messages" (sber-devtools.js:74-83, sber-replay.js:84-93). Каждое MQTT-сообщение пересылается по WS дважды и хранится в двух копиях _messages (обе без cap — усугубляет консенсус-находку о неограниченных буферах).

**Рекомендация:** Поднять подписку в sber-panel (или общий store/контроллер) и раздавать messages пропсами обоим потребителям.

#### [Minor] После Save диалог деталей безусловно переоткрывает себя через setTimeout(1500) без проверки open, а текст ошибки сохранения глотается (уникальная находка B, подтверждена).

- **Место:** `custom_components/sber_mqtt_bridge/www/components/sber-detail-dialog.js:532`
- **Источник:** один ревьюер, подтверждено судьёй чтением кода

Подтверждено: _onSave() при успехе ставит `setTimeout(() => this.show(this._data.entity_id), 1500)` — если пользователь закрыл диалог за 1.5с, show() снова его открывает. В catch (строки 533-536) _saveStatus="error" рендерится как «✗ Error» без e.message — в отличие от остальных компонентов, где текст ошибки доводится до пользователя через toast/banner.

**Рекомендация:** Проверять this.open в колбэке перед show(); в catch выводить e.message в save-status или toast.

#### [Minor] При сохранении ссылок несколько выбранных кандидатов с одинаковой suggested_role молча схлопываются в одну (last-wins), хотя чекбоксы позволяют выбрать обе (уникальная находка A, подтверждена).

- **Место:** `custom_components/sber_mqtt_bridge/www/components/sber-link-dialog.js:100`
- **Источник:** один ревьюер, подтверждено судьёй чтением кода

Подтверждено: в _save() цикл `links[c.suggested_role] = c.entity_id` перезаписывает предыдущий выбор без предупреждения (sber-link-dialog.js:98-102), UI — независимые чекбоксы без role-guard (строки 128-129). В sber-wizard для того же случая есть явный role-conflict guard (_toggleLink, sber-wizard.js:257-276) — поведение двух UI непоследовательно.

**Рекомендация:** Снимать/дизейблить конфликтующие чекбоксы по роли, как в мастере, либо предупреждать перед сохранением.

#### [Info] Нативные блокирующие confirm() (Clear All, строка 230) и alert('Invalid JSON file') (строка 254) выбиваются из toast/dialog-UX остальной панели.

- **Место:** `custom_components/sber_mqtt_bridge/www/components/sber-toolbar.js:230`
- **Источник:** консенсус обоих ревьюеров

Подтверждено кодом. Функционально работает; для деструктивного Clear All нативный confirm приемлем, но не темизирован и блокирует поток; в sandboxed-iframe контекстах confirm может молча вернуть false.

**Рекомендация:** При желании заменить на кастомный confirm-диалог и error-toast для консистентности; не срочно.

#### [Info] Позитивное наблюдение: XSS-поверхность нулевая (ни одного unsafeHTML/innerHTML/eval), vendored lit 3.x вместо хака с прототипами HA; top-level await и color-mix() требуют браузеров ~2022-2023+, что в рамках baseline HA.

- **Место:** `custom_components/sber_mqtt_bridge/www/sber-panel.js:15`
- **Источник:** консенсус обоих ревьюеров

Подтверждено grep: все данные (включая MQTT payload'ы) проходят через lit-экранирование. Top-level await (sber-panel.js:15, sber-wizard.js:15, sber-device-table.js:10) — Safari 15+; color-mix()/backdrop-filter деградируют косметически. Интервал и document-listeners панели корректно чистятся в disconnectedCallback.

**Рекомендация:** Действий не требуется; опционально зафиксировать минимальные версии браузеров в README.

#### [Info] Числовые настройки не валидируются на клиенте: min/max стоят только HTML-атрибутами, пустое поле превращается в 0 и уходит в update_settings как есть (уникальная находка B, подтверждена).

- **Место:** `custom_components/sber_mqtt_bridge/www/components/sber-settings.js:350`
- **Источник:** один ревьюер, подтверждено судьёй чтением кода

Подтверждено: `@input=${(e) => this._onInput(f.key, Number(e.target.value))}` (sber-settings.js:350) — Number('')=0; _onInput и _saveSettings (строки 102-116, 123-126) не клэмпят и не проверяют NaN/диапазон, значения вне min/max при ручном вводе отправляются на бэкенд. Защита целиком на стороне бэкенда.

**Рекомендация:** Перед сохранением клэмпить к f.min/f.max и блокировать Save при пустых/NaN значениях.

#### [Info] Cache-busting ?v= пропагируется на компоненты, но не на статические импорты lit-base.js и vendor/lit.js — после обновления vendored-бандла возможна stale-версия из кеша (уникальная находка A, подтверждена).

- **Место:** `custom_components/sber_mqtt_bridge/www/lit-base.js:17`
- **Источник:** один ревьюер, подтверждено судьёй чтением кода

Подтверждено: sber-panel.js:13-30 и компоненты проносят ?v в динамические импорты, но `import { LitElement, ... } from "./lit-base.js"` (sber-panel.js:32, sber-device-table.js:15 и др.) и `export ... from "./vendor/lit.js"` (lit-base.js:17-29) версии не имеют. Vendor-бандл уже менялся (issue #32, переход на vendored lit); при следующем изменении агрессивный кеш отдаст новые компоненты со старым lit.

**Рекомендация:** Пронести ?v и в импорт lit-base (динамический import с query, как для utils.js в wizard) либо явно полагаться на cache-заголовки статики HA.

## Приоритизация

**P0 (чинить немедленно):** все critical-находки — секция «Критические находки».

**P1:** major-находки измерений с оценкой C (безопасность, гонки, обработка ошибок).

**P2:** major-находки измерений B; систематизация friend-class связей bridge↔компоненты.

**P3:** minor/info — попутно при работе в соответствующих файлах.

---
*Отчёт сгенерирован автоматически по результатам мульти-агентного ревью (Claude Code). Каждая находка верифицирована чтением кода; опровергнутые заявки перечислены отдельно.*