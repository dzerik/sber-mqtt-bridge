# Проверка

## Локально — 2026-11-25

- Новые unit-tests: RED15failed/9passed подтвердили отсутствие explicit relay,
  ошибочный input_button.turn_on, опасный turn_off для разовых действий,
  offline для unknown и неправильный echo on. Затем GREEN54целевыхтеста.
- Настоящие HA integrations/services через dispatcher:2full-stack tests
  проверяют on/on/off, timestamp каждой активации, off без действия,
  отсутствие button_event, безопасный echo, metadata/full config,
  online=false после удаления и восстановление без запуска.
- UI:4новых RED cases; затем12frontendtests GREEN (настоящие Lit-компоненты,
  оба домена, ru/en, wizard и row с доступной подсказкой направления).
- Первый полный прогон:2failed/6993passed. Ветвление по category обращалось
  к неполным объектам в двух старых fault-isolation тестах. Проверка сначала
  ограничена доменами; лишние поля других сущностей больше не читаются.
  Целевой повтор81passed.
- Итоговый полный прогон:6995passed,2skipped,27warnings,3subtests; coverage98.08%
  при пороге95. Команда pytest tests/hacs/ -n4 --timeout=30
  --cov=custom_components/sber_mqtt_bridge; локальный лог полного прогона.
- Ruff source check/format, mypy112files, codegen--check, strict OpenSpec и
  git diff--check прошли.
- Независимое read-only ревью: материальных находок нет;26целевыхtests passed.
- Beta1.60.0b3 повышена штатным tools/bump_version.py с датой2026-11-25.

## Контракт и границы

Explicit Relay — адаптация разового действия к Sber on_off. Auto остаётся
scenario_button, чтобы не мигрировать существующие экспорты молча. Для управления
нужен явный Relay. Гарантия exactly-once поверх MQTT не вводилась. On/off
сцены не означает состояние всех её устройств; успешный сервис не доказывает
их физическое состояние.

Подтверждение callback обработчика через DevTools Inject будет отмечено replay,
а не настоящим входящим сообщением облака. Вид карточки и пользовательское
нажатие проверяются пользователем в приложении Sber, UI недоступен в сессии.

## Живая установка

- Beta1.60.0b3 установлена на тестовой установке, HA2026.11.3;152файла SHA256
  совпали на staging и после рестарта. ha core check/restart result=ok.
  Предыдущая beta сохранена для файлового отката.
- set_override(category=relay) для input_button.sber_bridge_probe_button и
  scene.sber_bridge_probe_scene успешно применён. Модели online+on_off,
  прежние имена Sber Bridge Probe Button/Кнопа2 и Мой дом/Коридор сохранены.
  Все44ID config, включая hub, сохранились;43экспортируемые сущности.
- Inject(topic=commands, mark_replay=true) для обеих сущностей: on/on/off.
  Каждый on поменял оба времени активации, scene включила только созданный
  тестовый boolean. Перед off target сброшен в off; off не поменял timestamps
  и не включил target. Это подтверждение обработчика на живом HA, не команды
  из приложения Sber.
- raw_states после команд: online=true,on_off=false у обоих. В command_confirmations
  нет ожиданий для тестовых сущностей. Реальные входящие status_request от
  Sber содержат оба ID; диагностические команды в журнале помечены replay.
- Финальный status:1.60.0b3, ready/connected/healthy,43сущности,
  errors_from_sber=0,publish_errors=0. HTTP entity-row.js совпал с локальным.
- Тестовый target оставлен off для пользовательской проверки. Конечный вид
  карточек и настоящее нажатие Sber ещё проверяет пользователь.
- Git commit/push/release/archive не выполнялись.

## Настоящие нажатия Sber — подтверждены 2026-11-25

По просьбе пользователя проверены message_log (direction=in, не replay),
корреляционные traces и состояния HA. Время ниже — Europe/Moscow:

- 00:54:41: команда on для scene.sber_bridge_probe_scene → настоящий
  scene.turn_on и новый timestamp сцены. Тестовый boolean стал on.
- 00:55:32: команда on для input_button.sber_bridge_probe_button →
  настоящий input_button.press и новый timestamp кнопки.
- 00:55:33: BOOL без bool_value для кнопки трактуется как off;
  сервис не вызывался, повторного нажатия нет.
- Обе команды on получили исходящий online=true/on_off=false; off также
  получил off. Три traces имеют status=success, ошибок Sber/публикации0.

Тем самым проверена цепочка от настоящей команды облака Sber до HA и ответа.
Тестовый target после пользовательской активации сцены находится в on.
