# Проверка

## Локальная реализация — 2026-11-24/25

- RED: 10 содержательных падений новых unit-тестов подтвердили отсутствие
  регистрации доменов, ошибочный double_click для timestamp, лишние allowed_values
  и offline для unknown. Две первоначальные ошибки сигнатуры теста исправлены.
- GREEN: 124 целевых теста; два дополнительных full-stack теста используют
  настоящие HA integrations/services input_button.press и scene.turn_on,
  настоящий WebSocket мастера и publisher до MQTT transport boundary.
- Первый полный прогон: 3 failed, 6962 passed; найдены отсутствующие
  DOMAIN_LABELS/DOMAIN_PRIORITY новых доменов и старое ожидание inventory.
  Метаданные добавлены, ожидание поддерживаемых доменов обновлено.
- Итоговый полный прогон: 6965 passed, 2 skipped, 25 warnings, 3 subtests passed;
  coverage98.08% при пороге95%; 5 snapshots passed. Использован Python3.14,
  pytest tests/hacs/ -n4 --timeout=30 --cov=custom_components/sber_mqtt_bridge.
- Ruff check/format исходников, mypy112files, codegen--check, strict OpenSpec
  validation и git diff--check прошли.
- Дополнительный lint старых тестовых файлов показывает прежние PT006/I001/ASYNC240;
  новая строка parametrize исправлена. Канонический CI lint проверяет исходники.
- Независимое read-only ревью: существенных замечаний нет; 20 целевых тестов прошли.
- Версия1.60.0b2 повышена штатным tools/bump_version.py, дата релиза2026-11-24.

## Границы

Обратный запуск HA-действия через scenario_button не реализован. Входящий click
не вызывает HA service, это проверяет unit-test. Отправка MQTT сама по себе не
доказывает выполнение сценария Sber. Существующий debounce и сетевые гарантии
не изменялись. Browser/Computer Use недоступен: CUA_REPL_ENABLED_SURFACES is required.

## Живая установка — 2026-11-25, HA2026.11.3

- Деплой1.60.0b2: 152файла сверены SHA256 до и после перезапуска.
  ha core check / restart завершились result=ok. Отдельный каталог previous
  сохранён для файлового отката; операционные детали сохранены в локальном контексте установки.
- Созданы отдельные input_button.sber_bridge_probe_button,
  input_boolean.sber_bridge_probe_target и scene.sber_bridge_probe_scene.
  Сцена включает только новый тестовый boolean; пользовательские сцены не запускались.
- Кнопка и сцена выбраны через API моста. Мастер видит обе без HA device;
  их модели имеют category=scenario_button, online+button_event, allowed_values=[click].
- Настоящее облако Sber прислало status_request с явным перечислением обоих
  новых entity_id. Оба появились в acknowledged_entities, never_confirmed=[]:
  это индивидуальное подтверждение распознавания, а не только факт отправки config.
- Два реальных input_button.press и две активации scene дали ровно четыре
  исходящих MQTT click: по два на сущность. После публикации raw_states содержит
  только online=true для обеих, без button_event. Сцена действительно установила
  тестовый boolean в on, включая после сброса в off перед повторной активацией.
- Финальный status: version1.60.0b2, phase=ready, connected=true, health=healthy,
  entities_count43 (41прежняя +2тестовые), errors_from_sber=0, publish_errors=0.
- Тестовые сущности оставлены для назначения сценария в Сбере. Пользователю
  отправлен вопрос о появлении кнопок и назначении сценария; подтверждения его
  фактического исполнения на момент этой записи нет.
- Commit/push/release/archive не выполнялись.
