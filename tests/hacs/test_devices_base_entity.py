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

from custom_components.sber_mqtt_bridge.devices.base_entity import BaseEntity, CommandResult

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
