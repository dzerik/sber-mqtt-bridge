"""Тесты быстрого ack (echo) в SberPublisher — согласованность пакета.

Echo — единственная публикация, которую мост собирает сам, а не из
``to_sber_current_state``, поэтому проверяем именно её путь: команда →
``publish_command_echo`` → что реально ушло на ``up/status``.

Что ломается у пользователя, если тесты покраснеют: Сбер получает через
8-27 мс подтверждение состояния, которого у устройства не бывает, а через
~1.5 с — настоящее состояние, и элементы управления в приложении
перещёлкиваются.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from test_devices_base_entity import _ModeLampStub

from custom_components.sber_mqtt_bridge.sber_publisher import PublisherDeps, SberPublisher
from custom_components.sber_mqtt_bridge.schema_validator import ValidationCollector


def _make_publisher(
    entity: _ModeLampStub,
    *,
    validation: ValidationCollector | None = None,
) -> tuple[SberPublisher, list[tuple[str, str]]]:
    """Собрать publisher поверх одного устройства и перехватить публикации.

    Args:
        entity: Устройство, попадающее в ``get_entities``.
        validation: Настоящий сборщик замечаний вместо мока — для тестов,
            которым важно, что именно мост сообщает сам себе о пакете.

    Returns:
        Пара «publisher, список ушедших (topic, payload)».
    """
    published: list[tuple[str, str]] = []

    async def _publish(topic: str, payload: str) -> None:
        published.append((topic, payload))

    devtools = MagicMock()
    if validation is not None:
        devtools.validation_collector = validation

    deps = PublisherDeps(
        root_topic="sbdev/test",
        stats=MagicMock(messages_sent=0, publish_errors=0),
        devtools=devtools,
        is_connected=lambda: True,
        publish=AsyncMock(side_effect=_publish),
        log_message=MagicMock(),
        get_entities=lambda: {entity.entity_id: entity},
        get_enabled_entity_ids=lambda: [entity.entity_id],
        get_redefinitions=dict,
        get_config_context=MagicMock(),
        on_config_published=MagicMock(),
    )
    return SberPublisher(deps), published


def _lamp(mode: str = "colour") -> _ModeLampStub:
    """Собрать лампу-заглушку в заданном режиме."""
    lamp = _ModeLampStub({"entity_id": "light.stub", "name": "Stub"})
    lamp.fill_by_ha_state({"entity_id": "light.stub", "state": "on", "attributes": {}})
    lamp.mode = mode
    return lamp


def _echo_keys(published: list[tuple[str, str]]) -> dict[str, dict]:
    """Разложить единственный ушедший echo-пакет в ``{ключ: value}``."""
    assert len(published) == 1
    topic, payload = published[0]
    assert topic == "sbdev/test/up/status"
    states = json.loads(payload)["devices"]["light.stub"]["states"]
    return {state["key"]: state["value"] for state in states}


@pytest.mark.asyncio
async def test_echo_drops_state_contradicting_the_commanded_mode() -> None:
    """В ack на ``light_mode: white`` нет старого ``light_colour``.

    Мост сам объявляет Сберу зависимость ``light_colour → light_mode ==
    colour``.  Если тест упадёт, быстрый ack снова начнёт подтверждать
    пару, которую эта же зависимость запрещает.
    """
    publisher, published = _make_publisher(_lamp())
    await publisher.publish_command_echo(
        {"light.stub": {"states": [{"key": "light_mode", "value": {"type": "ENUM", "enum_value": "white"}}]}}
    )
    echo = _echo_keys(published)
    assert echo["light_mode"] == {"type": "ENUM", "enum_value": "white"}
    assert "light_colour" not in echo


@pytest.mark.asyncio
async def test_echo_does_not_publish_undeclared_command_keys() -> None:
    """Ключ вне объявленных фич в ack не уходит.

    Если тест упадёт, echo снова станет единственной публикацией в обход
    фильтра объявленных фич, и Сбер получит состояние по фиче, которой
    нет в config этого устройства.
    """
    publisher, published = _make_publisher(_lamp())
    await publisher.publish_command_echo(
        {"light.stub": {"states": [{"key": "hvac_work_mode", "value": {"type": "ENUM", "enum_value": "heating"}}]}}
    )
    assert "hvac_work_mode" not in _echo_keys(published)


@pytest.mark.asyncio
async def test_echo_keeps_the_commanded_value_itself() -> None:
    """Значение из команды остаётся в ack — фильтры не съедают сам ответ.

    Если тест упадёт, мост перестанет подтверждать команду вовремя, и
    Сбер отметит её неисполненной («у этого устройства нет такой
    возможности» на следующий голосовой запрос).
    """
    publisher, published = _make_publisher(_lamp())
    await publisher.publish_command_echo(
        {"light.stub": {"states": [{"key": "light_colour_temp", "value": {"type": "INTEGER", "integer_value": "900"}}]}}
    )
    echo = _echo_keys(published)
    assert echo["light_colour_temp"] == {"type": "INTEGER", "integer_value": "900"}


class _LampWithSilentColour(_ModeLampStub):
    """Лампа, объявляющая ``light_colour``, но никогда его не публикующая.

    Ровно тот случай, ради которого валидатор моста и проверяет полноту:
    Сбер обязан получить в ответе на запрос состояния все заявленные
    функции, а эта лампа одну из них молча теряет.
    """

    def _build_current_state(self) -> dict:
        """Собрать состояние без ``light_colour``."""
        state = super()._build_current_state()
        states = state[self.entity_id]["states"]
        state[self.entity_id]["states"] = [s for s in states if s["key"] != "light_colour"]
        return state


def _issue_types(collector: ValidationCollector, entity_id: str = "light.stub") -> list[str]:
    """Вернуть типы замечаний, накопленных валидатором по устройству."""
    return [issue["type"] for issue in collector.snapshot()["by_entity"].get(entity_id, [])]


@pytest.mark.asyncio
async def test_echo_is_not_judged_for_completeness() -> None:
    """Урезанный ack не считается неполной публикацией.

    ``sanitize_echo_states`` намеренно выбрасывает ключи, которые команда
    сделала неактуальными.  Если тест упадёт, собственный валидатор моста
    будет писать ``declared_not_published`` на каждое переключение режима
    лампы, и в DevTools здоровое устройство постоянно будет висеть
    «жёлтым» до следующей полной публикации.
    """
    collector = ValidationCollector()
    publisher, published = _make_publisher(_lamp(), validation=collector)
    await publisher.publish_command_echo(
        {"light.stub": {"states": [{"key": "light_mode", "value": {"type": "ENUM", "enum_value": "white"}}]}}
    )
    # Пакет действительно неполный — иначе проверять нечего.
    assert "light_colour" not in _echo_keys(published)
    assert _issue_types(collector) == []


@pytest.mark.asyncio
async def test_state_publish_is_still_judged_for_completeness() -> None:
    """Обычная публикация состояния проверку полноты не теряет.

    Послабление сделано только для echo.  Если тест упадёт, мост
    перестанет замечать устройство, которое объявило Сберу функцию и
    никогда не сообщает её значение, — а Сбер такое устройство считает
    неисправным.
    """
    collector = ValidationCollector()
    lamp = _LampWithSilentColour({"entity_id": "light.stub", "name": "Stub"})
    lamp.fill_by_ha_state({"entity_id": "light.stub", "state": "on", "attributes": {}})
    publisher, _published = _make_publisher(lamp, validation=collector)
    await publisher.publish_states(force=True)
    assert "declared_not_published" in _issue_types(collector)
