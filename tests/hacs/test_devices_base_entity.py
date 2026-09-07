"""Тесты общего механизма BaseEntity: многоключевые команды и echo-ack.

Обе проверяемые здесь вещи живут в :class:`BaseEntity`, а не в конкретном
классе устройства, поэтому и тестовое устройство здесь своё
(:class:`_ModeLampStub`) — оно повторяет контракт лампы (селектор
``light_mode`` + зависящий от него ``light_colour``), но не зависит от
правок в ``devices/light.py``.

Что ломается у пользователя, если эти тесты покраснеют:

* команда «белый режим, температура 900» из приложения Сбера снова
  превратится в несколько вызовов ``light.turn_on`` подряд, и последний
  из них откатит только что заданную температуру на докомандную —
  пользователь двигает ползунок, а лампа возвращается к прежнему свету;
* быстрый ack (echo) снова начнёт сообщать Сберу состояние, которого не
  бывает (``light_mode: white`` рядом со старым ``light_colour``), и
  интерфейс приложения будет «перещёлкиваться» через ~1.5 с, когда
  придёт настоящее состояние.
"""

from __future__ import annotations

from collections.abc import Callable

import voluptuous as vol
from homeassistant.components.light import LIGHT_TURN_ON_SCHEMA

from custom_components.sber_mqtt_bridge.devices.base_entity import (
    AttrSpec,
    BaseEntity,
    CommandResult,
    _safe_float_parser,
    _safe_int_parser,
)

ENTITY_DATA = {"entity_id": "light.stub", "name": "Stub"}


class _ModeLampStub(BaseEntity):
    """Минимальная лампа с селектором режима — повторяет контракт LightEntity.

    Объявляет зависимость ``light_colour`` → ``light_mode == colour`` и
    обработчик ``light_mode``, который (как настоящий) не имеет
    собственного значения и синтезирует его из **докомандного** состояния
    сущности — именно на этом ломался порядок ключей.
    """

    def __init__(self, entity_data: dict) -> None:
        """Создать заглушку в категории ``light`` с исходным состоянием."""
        super().__init__("light", entity_data)
        self.colour_temp: int = 100
        """Докомандная температура — то, что подставляет обработчик режима."""

        self.mode: str = "colour"
        """Текущий режим лампы, попадающий в состояние и в echo."""

        self.colour: dict = {"h": 30, "s": 800, "v": 800}
        """Текущий цвет — состояние, зависящее от ``light_mode``."""

    def _create_features_list(self) -> list[str]:
        """Вернуть объявленные фичи заглушки."""
        return [*super()._create_features_list(), "on_off", "light_colour", "light_mode", "light_colour_temp"]

    def create_dependencies(self) -> dict[str, dict]:
        """Объявить ту же зависимость, что и настоящая лампа."""
        return {"light_colour": {"key": "light_mode", "values": [{"type": "ENUM", "enum_value": "colour"}]}}

    def _build_current_state(self) -> dict:
        """Собрать текущее состояние — все state-holding фичи сразу."""
        return {
            self.entity_id: {
                "states": [
                    {"key": "online", "value": {"type": "BOOL", "bool_value": True}},
                    {"key": "on_off", "value": {"type": "BOOL", "bool_value": True}},
                    {"key": "light_colour", "value": {"type": "COLOUR", "colour_value": self.colour}},
                    {"key": "light_colour_temp", "value": {"type": "INTEGER", "integer_value": str(self.colour_temp)}},
                    {"key": "light_mode", "value": {"type": "ENUM", "enum_value": self.mode}},
                ]
            }
        }

    @property
    def _cmd_handlers(self) -> dict[str, Callable[[dict], list[CommandResult]]]:
        """Разослать ключи команды по обработчикам."""
        return {
            "on_off": self._cmd_on_off,
            "light_mode": self._cmd_mode,
            "light_colour_temp": self._cmd_colour_temp,
        }

    def _cmd_on_off(self, value: dict) -> list[CommandResult]:
        """Включить/выключить лампу."""
        return [self._build_on_off_service_call(self.entity_id, "light", value.get("bool_value", False))]

    def _cmd_mode(self, value: dict) -> list[CommandResult]:
        """Перевести лампу в режим, подставив ДОкомандное значение канала."""
        if value.get("enum_value") == "white":
            return [
                self._build_service_call("light", "turn_on", self.entity_id, {"color_temp_kelvin": self.colour_temp})
            ]
        return [self._build_service_call("light", "turn_on", self.entity_id, {"hs_color": [30, 80]})]

    def _cmd_colour_temp(self, value: dict) -> list[CommandResult]:
        """Задать температуру, пришедшую в команде."""
        return [
            self._build_service_call(
                "light", "turn_on", self.entity_id, {"color_temp_kelvin": int(value["integer_value"])}
            )
        ]


class _PlainSwitchStub(BaseEntity):
    """Устройство без зависимостей — контрольная группа для порядка ключей."""

    def __init__(self, entity_data: dict) -> None:
        """Создать заглушку в категории ``relay``."""
        super().__init__("relay", entity_data)
        self.calls: list[str] = []
        """Ключи в том порядке, в котором их получили обработчики."""

    def _create_features_list(self) -> list[str]:
        """Вернуть объявленные фичи заглушки."""
        return [*super()._create_features_list(), "on_off", "button_event"]

    def _build_current_state(self) -> dict:
        """Собрать минимальное текущее состояние."""
        return {self.entity_id: {"states": [{"key": "on_off", "value": {"type": "BOOL", "bool_value": True}}]}}

    @property
    def _cmd_handlers(self) -> dict[str, Callable[[dict], list[CommandResult]]]:
        """Разослать ключи команды по обработчикам."""
        return {"on_off": self._record("on_off"), "button_event": self._record("button_event")}

    def _record(self, key: str) -> Callable[[dict], list[CommandResult]]:
        """Вернуть обработчик, запоминающий факт и порядок вызова."""

        def handler(_value: dict) -> list[CommandResult]:
            self.calls.append(key)
            return [{"update_state": True}]

        return handler


def _lamp() -> _ModeLampStub:
    """Собрать заглушку лампы с заполненным HA-состоянием."""
    lamp = _ModeLampStub(dict(ENTITY_DATA))
    lamp.fill_by_ha_state({"entity_id": "light.stub", "state": "on", "attributes": {}})
    return lamp


class TestMultiKeyCommand:
    """process_cmd: несколько ключей одной команды не затирают друг друга."""

    def test_commanded_value_survives_the_mode_selector(self) -> None:
        """Заданная температура доходит до HA, даже если ``light_mode`` идёт после.

        Если тест упадёт — пользователь в приложении Сбера выбирает белый
        режим и температуру одним жестом, а лампа встаёт на прежнюю
        температуру: обработчик ``light_mode`` подставляет ДОкомандное
        значение и оказывается последним вызовом.
        """
        lamp = _lamp()
        result = lamp.process_cmd(
            {
                "states": [
                    {"key": "light_colour_temp", "value": {"type": "INTEGER", "integer_value": "900"}},
                    {"key": "light_mode", "value": {"type": "ENUM", "enum_value": "white"}},
                ]
            }
        )
        assert [call["url"]["service_data"] for call in result] == [{"color_temp_kelvin": 900}]

    def test_result_does_not_depend_on_key_order(self) -> None:
        """Тот же результат при обратном порядке ключей в payload.

        Сбер не обещает порядок ключей; если тест упадёт, одна и та же
        команда будет исполняться по-разному от раза к разу.
        """
        first = _lamp().process_cmd(
            {
                "states": [
                    {"key": "light_mode", "value": {"type": "ENUM", "enum_value": "white"}},
                    {"key": "light_colour_temp", "value": {"type": "INTEGER", "integer_value": "900"}},
                ]
            }
        )
        second = _lamp().process_cmd(
            {
                "states": [
                    {"key": "light_colour_temp", "value": {"type": "INTEGER", "integer_value": "900"}},
                    {"key": "light_mode", "value": {"type": "ENUM", "enum_value": "white"}},
                ]
            }
        )
        assert first == second

    def test_one_service_call_per_service(self) -> None:
        """Один Sber-command → один ``light.turn_on`` с объединёнными данными.

        Если тест упадёт, на одну команду снова уйдёт несколько вызовов
        подряд: лампа видимо проходит промежуточные состояния, а HA шлёт
        лишние ``state_changed``.
        """
        lamp = _lamp()
        result = lamp.process_cmd(
            {
                "states": [
                    {"key": "on_off", "value": {"type": "BOOL", "bool_value": True}},
                    {"key": "light_colour_temp", "value": {"type": "INTEGER", "integer_value": "700"}},
                ]
            }
        )
        assert len(result) == 1
        assert result[0]["url"]["service"] == "turn_on"
        assert result[0]["url"]["service_data"] == {"color_temp_kelvin": 700}

    def test_different_services_stay_separate(self) -> None:
        """Разные HA-сервисы не сливаются и сохраняют порядок.

        Если тест упадёт, выключение и установка яркости схлопнутся в
        один вызов и устройство получит не ту команду.
        """
        lamp = _lamp()
        result = lamp.process_cmd(
            {
                "states": [
                    {"key": "light_colour_temp", "value": {"type": "INTEGER", "integer_value": "700"}},
                    {"key": "on_off", "value": {"type": "BOOL", "bool_value": False}},
                ]
            }
        )
        assert [call["url"]["service"] for call in result] == ["turn_on", "turn_off"]

    def test_update_state_results_are_preserved(self) -> None:
        """Результаты ``update_state`` проходят через агрегацию как есть.

        Если тест упадёт, устройства, отвечающие на команду только
        переподтверждением состояния (ворота, интерком), перестанут
        подтверждать её Сберу.
        """
        switch = _PlainSwitchStub({"entity_id": "switch.stub", "name": "Stub"})
        switch.fill_by_ha_state({"entity_id": "switch.stub", "state": "on", "attributes": {}})
        result = switch.process_cmd(
            {
                "states": [
                    {"key": "on_off", "value": {"type": "BOOL", "bool_value": True}},
                    {"key": "button_event", "value": {"type": "ENUM", "enum_value": "click"}},
                ]
            }
        )
        assert result == [{"update_state": True}, {"update_state": True}]

    def test_device_without_dependencies_keeps_payload_order(self) -> None:
        """Без объявленных зависимостей порядок ключей остаётся исходным.

        Перестановка ключей — точечное лекарство для селекторов режима;
        если тест упадёт, она начнёт менять порядок у всех остальных
        категорий, где Сбер рассчитывает на порядок payload.
        """
        switch = _PlainSwitchStub({"entity_id": "switch.stub", "name": "Stub"})
        switch.fill_by_ha_state({"entity_id": "switch.stub", "state": "on", "attributes": {}})
        switch.process_cmd(
            {
                "states": [
                    {"key": "button_event", "value": {"type": "ENUM", "enum_value": "click"}},
                    {"key": "on_off", "value": {"type": "BOOL", "bool_value": True}},
                ]
            }
        )
        assert switch.calls == ["button_event", "on_off"]

    def test_exclusive_fields_never_share_one_call(self) -> None:
        """Взаимоисключающие поля HA не сливаются в один ``light.turn_on``.

        Схема ``light.turn_on`` в HA объявляет цветовые поля группой
        взаимного исключения и отклоняет **весь** вызов, если их пришло
        два.  Если тест упадёт, команда «цветной режим + температура»
        (или «белый режим + цвет») перестанет исполняться целиком —
        вместе с яркостью, — а в журнале останется только предупреждение
        от диспетчера.
        """
        lamp = _lamp()
        result = lamp.process_cmd(
            {
                "states": [
                    {"key": "light_mode", "value": {"type": "ENUM", "enum_value": "colour"}},
                    {"key": "light_colour_temp", "value": {"type": "INTEGER", "integer_value": "900"}},
                ]
            }
        )
        schema = vol.Schema(LIGHT_TURN_ON_SCHEMA)
        for call in result:
            schema(dict(call["url"]["service_data"]))
        # Последним писателем остаётся значение из команды, как и до слияния.
        assert result[-1]["url"]["service_data"] == {"color_temp_kelvin": 900}

    def test_selector_reordering_needs_a_declared_dependency(self) -> None:
        """Без объявленной зависимости защита от отката НЕ работает — и это норма.

        Классы строят ``create_dependencies`` из финального списка фич,
        поэтому у лампы, у которой пользователь убрал ``light_colour``
        (``sber_features_remove``), селектор режима перестаёт быть
        селектором и ключи идут в порядке payload.  Тест фиксирует
        границу починки: если он упадёт, значит порядок стал зависеть от
        чего-то ещё, и документацию :meth:`process_cmd` надо переписать.
        """

        class _LampWithoutDependencies(_ModeLampStub):
            """Та же лампа, но без объявленной зависимости цвета от режима."""

            def create_dependencies(self) -> dict[str, dict]:
                """Вернуть пустой словарь — как после удаления ``light_colour``."""
                return {}

        lamp = _LampWithoutDependencies(dict(ENTITY_DATA))
        lamp.fill_by_ha_state({"entity_id": "light.stub", "state": "on", "attributes": {}})
        result = lamp.process_cmd(
            {
                "states": [
                    {"key": "light_colour_temp", "value": {"type": "INTEGER", "integer_value": "900"}},
                    {"key": "light_mode", "value": {"type": "ENUM", "enum_value": "white"}},
                ]
            }
        )
        assert [call["url"]["service_data"] for call in result] == [{"color_temp_kelvin": lamp.colour_temp}]


class TestEchoStateSanitizing:
    """sanitize_echo_states: быстрый ack не сообщает невозможное состояние."""

    @staticmethod
    def _echo(lamp: _ModeLampStub, cmd_states: list[dict]) -> dict[str, dict]:
        """Собрать echo так же, как это делает SberPublisher, и разложить по ключам."""
        baseline = lamp.to_sber_current_state()[lamp.entity_id]["states"]
        commanded = {state["key"]: state for state in cmd_states}
        merged = [commanded.get(state["key"], state) for state in baseline]
        merged += [state for key, state in commanded.items() if key not in {s["key"] for s in baseline}]
        return {state["key"]: state["value"] for state in lamp.sanitize_echo_states(merged, set(commanded))}

    def test_stale_dependent_key_is_dropped(self) -> None:
        """Команда ``light_mode: white`` не тащит в ack старый ``light_colour``.

        Если тест упадёт, Сбер получает через 8-27 мс пакет с белым
        режимом и цветом одновременно (мост сам объявляет такую пару
        невозможной), а через ~1.5 с — настоящее состояние; в приложении
        это выглядит как перещёлкивание элементов управления.
        """
        echo = self._echo(_lamp(), [{"key": "light_mode", "value": {"type": "ENUM", "enum_value": "white"}}])
        assert echo["light_mode"] == {"type": "ENUM", "enum_value": "white"}
        assert "light_colour" not in echo

    def test_selector_follows_the_commanded_dependent_key(self) -> None:
        """Команда ``light_colour`` переводит в ack и сам ``light_mode``.

        Если тест упадёт, ack подтвердит новый цвет при старом режиме
        ``white`` — и вкладка режима в приложении прыгнет обратно, как
        только придёт настоящее состояние.
        """
        lamp = _lamp()
        lamp.mode = "white"
        echo = self._echo(
            lamp,
            [{"key": "light_colour", "value": {"type": "COLOUR", "colour_value": {"h": 200, "s": 900, "v": 900}}}],
        )
        assert echo["light_mode"] == {"type": "ENUM", "enum_value": "colour"}
        assert echo["light_colour"]["colour_value"] == {"h": 200, "s": 900, "v": 900}

    def test_own_state_is_never_censored(self) -> None:
        """Несогласованность самого состояния устройства echo не трогает.

        Обычная публикация обязана нести все state-holding фичи (issue
        #63); если тест упадёт, echo начнёт выбрасывать ключи, которых
        команда не касалась, и ответы на ``status_request`` разойдутся с
        быстрым ack.
        """
        lamp = _lamp()
        lamp.mode = "white"
        echo = self._echo(lamp, [{"key": "on_off", "value": {"type": "BOOL", "bool_value": True}}])
        assert echo["light_mode"] == {"type": "ENUM", "enum_value": "white"}
        assert "light_colour" in echo

    def test_undeclared_command_key_is_not_echoed(self) -> None:
        """Ключ, которого устройство не объявляло, в ack не попадает.

        Echo был единственной публикацией в обход фильтра объявленных
        фич; если тест упадёт, Сбер снова получит состояние по фиче,
        которой нет в config, и нарисует неработающий элемент управления.
        """
        echo = self._echo(_lamp(), [{"key": "hvac_work_mode", "value": {"type": "ENUM", "enum_value": "heating"}}])
        assert "hvac_work_mode" not in echo


class _ForeignFeatureStub(BaseEntity):
    """Устройство, которое пытается объявить функцию не своей категории.

    Ровно то, что делали настоящие классы: домофон получал ``on_off``
    по наследству от ``OnOffEntity``, датчик протечки — ``tamper_alarm``
    от общего миксина.
    """

    def __init__(self, category: str, entity_data: dict) -> None:
        """Создать заглушку в указанной категории Sber."""
        super().__init__(category, entity_data)

    def _create_features_list(self) -> list[str]:
        """Объявить обязательный ``online`` и чужой ``on_off``."""
        return [*super()._create_features_list(), "on_off"]

    def _build_current_state(self) -> dict:
        """Опубликовать обе функции — фильтр обязан снять чужую."""
        return {
            self.entity_id: {
                "states": [
                    {"key": "online", "value": {"type": "BOOL", "bool_value": True}},
                    {"key": "on_off", "value": {"type": "BOOL", "bool_value": True}},
                ]
            }
        }


class TestFeaturesForeignToTheCategory:
    """Ни одна категория не объявляет функцию вне своего справочника Sber.

    Таблица «Доступные функции устройства» на странице категории —
    закрытая. Функция вне её для облака не «лишняя строчка»: модель с
    ней облако вправе отбросить целиком, молча, и пользователь увидит
    не «кнопку, которая не работает», а исчезнувшее устройство.

    Правило живёт в :class:`BaseEntity`, а не в классах устройств,
    потому что ошибка каждый раз приезжает по наследству или из общего
    миксина. Если эти тесты упадут, дыра снова станет
    поклассовой — и следующая категория провалится в неё так же тихо.
    """

    def test_inherited_foreign_feature_is_dropped(self) -> None:
        """Унаследованный ``on_off`` не попадает в объявление домофона."""
        entity = _ForeignFeatureStub("intercom", {"entity_id": "switch.i", "name": "I"})
        assert entity.get_final_features_list() == ["online"]

    def test_dropped_feature_is_not_published_either(self) -> None:
        """Снятая функция не уезжает и в состоянии."""
        entity = _ForeignFeatureStub("intercom", {"entity_id": "switch.i", "name": "I"})
        published = {s["key"] for s in entity.to_sber_current_state()["switch.i"]["states"]}
        assert published == {"online"}

    def test_declaration_still_shows_what_the_class_asked_for(self) -> None:
        """``declared_features`` показывает объявление классов ДО фильтра.

        На этом свойстве держится
        ``TestDeclaredFeaturesBelongToTheCategory``: если оно начнёт
        отдавать уже отфильтрованный список, тот тест станет сверять
        фильтр с самим собой и перестанет ловить что бы то ни было —
        ровно то состояние, в котором чужие функции жили девяти
        категориями и не были видны.
        """
        entity = _ForeignFeatureStub("intercom", {"entity_id": "switch.i", "name": "I"})
        assert sorted(entity.declared_features) == ["on_off", "online"]
        assert entity.get_final_features_list() == ["online"]

    def test_documented_feature_survives(self) -> None:
        """Та же функция в категории, где она документирована, остаётся.

        Страховка от «фильтр включили — устройства онемели»: у ``relay``
        ``on_off`` документирован, и снимать его нельзя.
        """
        entity = _ForeignFeatureStub("relay", {"entity_id": "switch.r", "name": "R"})
        assert sorted(entity.get_final_features_list()) == ["on_off", "online"]

    def test_user_added_feature_is_not_filtered(self) -> None:
        """``sber_features_add`` фильтр не трогает — только предупреждает.

        Справочник категорий — выгрузка документации, и она доказуемо
        неполна: на странице ``led_strip`` в собственном примере Sber
        есть ``sleep_timer``, а в таблице функций, которую читает
        генератор, его нет. Пользователь, скопировавший функцию со
        страницы, которую он видит своими глазами, получил бы её
        молчаливое удаление и совет убрать верную строчку.

        Если тест упадёт, задокументированная в README возможность
        ``sber_features_add`` перестанет работать для всего, чего не
        досчитал скрапер, и обойти это будет нечем.
        """
        entity = _ForeignFeatureStub("relay", {"entity_id": "switch.r", "name": "R"})
        entity.extra_features = ["sleep_timer"]
        assert "sleep_timer" in entity.get_final_features_list()

    def test_user_added_documented_feature_survives(self) -> None:
        """Законное добавление по-прежнему работает."""
        entity = _ForeignFeatureStub("relay", {"entity_id": "switch.r", "name": "R"})
        entity.extra_features = ["power"]
        assert "power" in entity.get_final_features_list()

    def test_user_added_feature_survives_next_to_a_dropped_one(self) -> None:
        """Разделение по источнику: наше снимается, пользовательское — нет.

        Одна и та же публикация: класс подсунул чужой ``on_off``
        домофону, пользователь добавил своё имя. Уехать должно только
        второе.
        """
        entity = _ForeignFeatureStub("intercom", {"entity_id": "switch.i", "name": "I"})
        entity.extra_features = ["sleep_timer"]
        assert sorted(entity.get_final_features_list()) == ["online", "sleep_timer"]

    def test_unknown_category_is_passed_through(self) -> None:
        """Категория, которой нет в справочнике, не фильтруется.

        Справочник — свидетельство того, что Sber документирует, а не
        того, что он запрещает. Раздеть устройство из-за пробела в
        нашей выгрузке документации было бы хуже чужого ключа.
        """
        entity = _ForeignFeatureStub("category_sber_never_heard_of", {"entity_id": "switch.x", "name": "X"})
        assert sorted(entity.get_final_features_list()) == ["on_off", "online"]

    def test_user_added_foreign_feature_is_warned_about(self, caplog) -> None:
        """Про пропущенное переопределение пользователю говорят в журнале.

        Это единственная разновидность, о которой человек может принять
        решение сам, — поэтому WARNING, а не DEBUG. Функция уезжает, но
        в журнале сказано, чем это грозит.
        """
        entity = _ForeignFeatureStub("relay", {"entity_id": "switch.r", "name": "R"})
        entity.extra_features = ["sleep_timer"]
        with caplog.at_level("WARNING"):
            entity.get_final_features_list()
        assert "sleep_timer" in caplog.text

    def test_class_contributed_feature_is_not_warned_about(self, caplog) -> None:
        """А про унаследованную — нет: пользователь на неё не влияет.

        Список функций пересобирается на каждой публикации; предупреждать
        о том, что человек не может изменить, значит залить журнал шумом.
        """
        entity = _ForeignFeatureStub("intercom", {"entity_id": "switch.i", "name": "I"})
        with caplog.at_level("WARNING"):
            entity.get_final_features_list()
        assert "on_off" not in caplog.text


class _NumericStub(BaseEntity):
    """Устройство, читающее числовой атрибут HA через :class:`AttrSpec`.

    Спека без ``parser`` — самый частый случай в проекте (значение уже
    число, разбирать нечего) и ровно тот, через который ``NaN``
    просачивался мимо ``_safe_float_parser``.
    """

    ATTR_SPECS = (
        AttrSpec(field="reading", attr_keys=("reading",)),
        AttrSpec(field="kept", attr_keys=("kept",), preserve_on_missing=True),
    )

    def __init__(self, entity_data: dict) -> None:
        """Создать заглушку в категории ``sensor_temp``."""
        super().__init__("sensor_temp", entity_data)
        self.reading: float | None = None
        self.kept: float | None = None

    def fill_by_ha_state(self, ha_state: dict) -> None:
        """Разобрать состояние HA через объявленные спеки."""
        super().fill_by_ha_state(ha_state)
        self._apply_attr_specs(ha_state.get("attributes", {}))

    def _build_current_state(self) -> dict:
        """Опубликовать одно значение — в тестах не используется."""
        return {self.entity_id: {"states": []}}


class TestNonFiniteNumbersFromHomeAssistant:
    """``NaN`` и бесконечность из HA не должны доходить до протокола.

    Они приезжают буднично: шаблонный сенсор, поделивший на ноль,
    modbus-регистр с мусором, MQTT-полезная нагрузка ``"nan"``. Дальше
    ``int(float('nan'))`` бросает ``ValueError``,
    ``sber_protocol.build_states_list_json`` его глотает — и устройство
    молча пропадает из ``up/status``. Сбер, не получив в ответе
    объявленных функций, считает устройство неисправным: пользователь
    видит «климат исчез», а в журнале одна строка исключения без всякой
    связи с испорченным атрибутом. ``inf`` хуже: ``OverflowError`` этот
    обработчик не ловит вовсе и уносит с собой всю публикацию.
    """

    def test_int_parser_rejects_nan(self) -> None:
        """``NaN`` для целочисленного парсера — отсутствующее значение."""
        assert _safe_int_parser(float("nan")) is None

    def test_int_parser_rejects_infinity(self) -> None:
        """Бесконечность — тоже."""
        assert _safe_int_parser(float("inf")) is None
        assert _safe_int_parser(float("-inf")) is None

    def test_int_parser_still_reads_numbers(self) -> None:
        """Обычные значения, включая строки, читаются как раньше."""
        assert _safe_int_parser("22.5") == 22
        assert _safe_int_parser(0) == 0
        assert _safe_int_parser(-7) == -7

    def test_float_parser_rejects_non_finite(self) -> None:
        """То же для дробного парсера."""
        assert _safe_float_parser(float("nan")) is None
        assert _safe_float_parser(float("inf")) is None
        assert _safe_float_parser("21.5") == 21.5

    def test_attr_spec_without_parser_drops_nan(self) -> None:
        """``NaN`` не оседает в поле устройства даже без явного парсера."""
        entity = _NumericStub({"entity_id": "sensor.s", "name": "S"})
        entity.fill_by_ha_state({"state": "21", "attributes": {"reading": float("nan")}})
        assert entity.reading is None

    def test_preserved_field_keeps_the_last_good_reading(self) -> None:
        """Испорченное число не затирает последнее исправное.

        Для ``preserve_on_missing`` «не число» означает то же, что
        «атрибута нет»: связанный датчик уже прислал показание, и
        мусор от основной сущности не должен его стирать.
        """
        entity = _NumericStub({"entity_id": "sensor.s", "name": "S"})
        entity.fill_by_ha_state({"state": "21", "attributes": {"kept": 21.5}})
        entity.fill_by_ha_state({"state": "21", "attributes": {"kept": float("nan")}})
        assert entity.kept == 21.5


class TestModelIdentity:
    """``model.id`` — имя модели в облаке, и оно обязано быть точным.

    Облако Sber хранит одну модель на идентификатор и сливает описания
    всех устройств, которые её заявляют. Слишком грубый идентификатор
    склеивает разное железо в одну карточку; слишком подробный заводит
    новую модель на каждый чих и заставляет облако перерегистрировать
    устройства.
    """

    @staticmethod
    def _switch(entity_id: str, device: dict | None, name: str = "Стенд") -> _ForeignFeatureStub:
        """Собрать заглушку категории ``relay`` с заданным HA-устройством."""
        entity = _ForeignFeatureStub("relay", {"entity_id": entity_id, "name": name})
        entity.linked_device = device
        entity.fill_by_ha_state({"state": "on", "attributes": {}})
        return entity

    def test_same_hardware_shares_one_model(self) -> None:
        """Две одинаковые железки остаются одной моделью.

        В этом весь смысл слова «модель»: если тест упадёт, у
        пользователя с десятком одинаковых реле в облаке заведётся
        десять моделей вместо одной.
        """
        first = self._switch("switch.a", {"manufacturer": "Aqara", "model": "SP-EUC01"})
        second = self._switch("switch.b", {"manufacturer": "Aqara", "model": "SP-EUC01"})
        assert first.to_sber_state()["model"]["id"] == second.to_sber_state()["model"]["id"]

    def test_different_manufacturer_splits_the_model(self) -> None:
        """Разные производители — разные модели.

        Если упадёт: в одном пакете уедут два описания под одним
        идентификатором, и какое из них останется в облаке — не
        определено (#63).
        """
        aqara = self._switch("switch.a", {"manufacturer": "Aqara", "model": "SP-EUC01"})
        sonoff = self._switch("switch.b", {"manufacturer": "SONOFF", "model": "S26R2"})
        assert aqara.to_sber_state()["model"]["id"] != sonoff.to_sber_state()["model"]["id"]

    def test_renaming_the_entity_keeps_the_model(self) -> None:
        """Переименование устройства не заводит новую модель.

        Включать имя в идентификатор значило бы перерегистрировать модель
        на каждое переименование — цена куда выше, чем у коллизии, ради
        которой это делалось бы.
        """
        before = self._switch("switch.a", {"manufacturer": "Aqara", "model": "SP-EUC01"}, name="Чайник")
        after = self._switch("switch.a", {"manufacturer": "Aqara", "model": "SP-EUC01"}, name="Кофеварка")
        assert before.to_sber_state()["model"]["id"] == after.to_sber_state()["model"]["id"]

    def test_entity_without_a_device_keeps_its_old_id(self) -> None:
        """Сущность без HA-устройства не меняет идентификатор из-за правки.

        Сверка с **зафиксированным** значением, а не с пересчитанным той
        же функцией: пересчёт доказал бы только, что функция равна себе.
        ``ad856069`` — дайджест реле с функциями ``online`` + ``on_off``
        без ``allowed_values``, тот же, что в замороженном снимке
        ``test_protocol_snapshots.ambr`` (``Mdl_relay_ad856069``) до этой
        правки.

        Если тест упадёт, у всех сущностей без HA-устройства (а это
        template-сенсоры, helper'ы, всё, что заведено через YAML)
        идентификаторы моделей сдвинутся, и Сбер перерегистрирует их без
        всякой на то причины.
        """
        entity = self._switch("switch.a", None)
        assert entity.to_sber_state()["model"]["id"] == "Mdl_relay_ad856069"

    def test_hardware_reaches_the_description(self) -> None:
        """``model.description`` описывает модель, а не конкретный прибор.

        Раньше туда клали отображаемое имя сущности, и два одинаковых
        датчика одного вендора с разными именами уезжали в одном пакете
        под одним ``model.id`` с разным содержимым — тот же дефект #63,
        только внутри вендора.
        """
        entity = self._switch("switch.a", {"manufacturer": "Aqara", "model": "SP-EUC01"}, name="Чайник")
        assert entity.to_sber_state()["model"]["description"] == "Aqara SP-EUC01"

    def test_same_hardware_gives_the_same_descriptor(self) -> None:
        """Одинаковое железо — полностью одинаковый дескриптор модели.

        Один ``model.id`` теперь означает ровно один набор полей: в
        облаке нечему конфликтовать, какое бы из устройств ни приехало
        первым.
        """
        first = self._switch("switch.a", {"manufacturer": "Aqara", "model": "SP-EUC01"}, name="Кухня")
        second = self._switch("switch.b", {"manufacturer": "Aqara", "model": "SP-EUC01"}, name="Спальня")
        assert first.to_sber_state()["model"] == second.to_sber_state()["model"]
