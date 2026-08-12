"""Жёсткие тесты «слабых мест» импульсных ворот: ход створки, обязательная связь, сохранение опций.

Файл закрывает ровно три подсистемы, добавленные поверх базовой категории
``gate`` (issue #53):

1. **Эмуляция хода створки** (``gate_options.travel_time``).  Опция
   выключена по умолчанию, и это обязано быть буквально «как раньше»:
   тот же набор фич, тот же ``allowed_values`` и тот же ``model.id`` —
   любое расхождение означает НОВОЕ устройство в облаке у всех, кто уже
   подключил ворота (потеряются имя, комната, сценарии).  Включённая
   опция обязана публиковать ``opening`` / ``closing`` в правильную
   сторону и объявлять эти значения в ``allowed_values.open_state``
   ровно тогда, когда может их отправить: Sber молча выбрасывает
   необъявленное значение состояния (корень issue #44).
2. **Отсутствие обязательной связи** (``REQUIRED_LINK_ROLES``).  Ворота
   без геркона вечно рапортуют «закрыто», и это обязано быть видно
   пользователю: ремонт (repair issue) с осмысленным текстом,
   диагностика и карточка устройства в панели.
3. **Сохранение опций без перезагрузки записи.**  Перезагрузка entry
   рвёт MQTT-сессию; галочка в панели не должна стоить пользователю
   разрыва моста.

Правила файла (те же, что и у остальных тестов ворот):

* время двигается ТОЛЬКО через инъектируемые часы сущности (``_now``)
  и подменённый ``asyncio.sleep`` моста; ``asyncio.sleep`` в самих
  тестах запрещён;
* проверяются точные значения и полные множества (``==``), а не ``in``
  и не ``assert result``;
* ожидания выведены из спеки Sber (обязательные фичи категории ``gate``,
  ENUM ``open_state``) и из дизайна issue #53, а НЕ сняты с текущего
  вывода кода.  Единственное исключение — слепок ``model.id``, который
  специально снят с версии ДО появления ``travel_time``
  (``git archive HEAD`` на коммите 06a0245): он и обязан не меняться.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    async_mock_service,
)

from custom_components.sber_mqtt_bridge.const import (
    CONF_ENTITY_LINKS,
    CONF_ENTITY_TYPE_OVERRIDES,
    CONF_EXPOSED_ENTITIES,
    CONF_GATE_OPTIONS,
    CONF_SBER_BROKER,
    CONF_SBER_LOGIN,
    CONF_SBER_PASSWORD,
    CONF_SBER_PORT,
    CONF_SBER_VERIFY_SSL,
    DOMAIN,
)
from custom_components.sber_mqtt_bridge.devices.gate import ImpulseGateEntity, make_gate_entity
from custom_components.sber_mqtt_bridge.diagnostics import async_get_config_entry_diagnostics
from custom_components.sber_mqtt_bridge.repairs import check_and_create_issues
from custom_components.sber_mqtt_bridge.sber_bridge import SberBridge

RELAY = "switch.gate"
"""Импульсное реле — первичная сущность Sber-устройства."""

CONTACT = "binary_sensor.gate_contact"
"""Геркон в роли ``open_state`` — единственный источник правды о створке."""

GATE_CATEGORY = "gate"
"""Категория Sber, в которую промотируется пара «реле + геркон»."""

GATE_LOGGER = "custom_components.sber_mqtt_bridge.devices.gate"
"""Логгер модуля ворот — по нему ловится WARNING о неподтверждённом ходе."""

TRAVEL = 20.0
"""Время хода створки в тестах (секунды). Реальные ворота едут 15-25 с."""

CONFIRM_MARGIN = 0.5
"""Запас к отложенному подтверждению.

Мост спит на своих часах, а сущность меряет дедлайн своими, поэтому
запрошенная пауза обязана быть строго БОЛЬШЕ времени хода — иначе
подтверждение опубликует ``opening`` ещё раз и створка «застрянет» в
движении до следующего события геркона."""

DEFAULT_CONFIRM_DELAY = 1.5
"""Штатная короткая пауза подтверждения (``SETTINGS_DEFAULTS[confirm_delay]``)."""

IMPULSE_COOLDOWN = 2.0
"""Антидребезг импульсов (секунды): второй импульс внутри окна гасится."""

MAX_TRAVEL = 600.0
"""Верхняя граница ``travel_time``: 10 минут."""

MODEL_ID_BEFORE_TRAVEL_FEATURE = "Mdl_gate_c085645d"
"""``model.id`` импульсных ворот ДО появления ``travel_time``.

Снят прогоном на ``git archive HEAD`` (коммит 06a0245, до этой правки).
Дайджест считается из набора фич и ``allowed_values``; с выключенной
опцией он обязан совпасть байт в байт, иначе у каждого пользователя в
облаке появится новое устройство вместо уже настроенных ворот."""

TRAVEL_OPEN_STATE_SET = {"open", "close", "opening", "closing"}
"""Полное множество ``open_state``, объявляемое при включённой эмуляции."""

SBER_CREDENTIALS = {
    CONF_SBER_LOGIN: "test",
    CONF_SBER_PASSWORD: "pass",
    CONF_SBER_BROKER: "broker.test",
    CONF_SBER_PORT: 8883,
    CONF_SBER_VERIFY_SSL: False,
}
"""Учётные данные Sber для всех config entry этого файла."""


# ---------------------------------------------------------------------------
# Хелперы уровня сущности
# ---------------------------------------------------------------------------


class FakeClock:
    """Подменяемые монотонные часы.

    Логика ворот обязана брать время только через инъектируемый ``_now``:
    прямой вызов ``time.monotonic()`` сделал бы и антидребезг, и дедлайн
    хода непроверяемыми, то есть незаметно сломанными.
    """

    def __init__(self) -> None:
        """Начать отсчёт с нуля."""
        self.value = 0.0

    def __call__(self) -> float:
        """Вернуть текущее «время»."""
        return self.value

    def advance(self, seconds: float) -> None:
        """Сдвинуть часы вперёд на ``seconds``."""
        self.value += seconds


def make_gate(
    *,
    travel_time: float | None = None,
    contact: str | None = "off",
    invert: bool = False,
    relay_state: str = "off",
    link: bool = True,
    entity_id: str = RELAY,
) -> tuple[ImpulseGateEntity, FakeClock]:
    """Собрать импульсные ворота с инъектированными часами.

    Args:
        travel_time: Значение опции ``travel_time``; ``None`` — опция не
            передаётся вовсе (проверка поведения по умолчанию).
        contact: Состояние геркона (``None`` — показаний ещё не было).
        invert: Опция ``invert_contact``.
        relay_state: HA-состояние реле.
        link: Регистрировать ли связь ролью ``open_state``.
        entity_id: entity_id реле (домен задаёт вид импульса).

    Returns:
        Пара (сущность, часы).
    """
    entity = make_gate_entity({"entity_id": entity_id, "name": "Gate"})
    assert isinstance(entity, ImpulseGateEntity)
    clock = FakeClock()
    entity._now = clock
    options: dict[str, Any] = {}
    if invert:
        options["invert_contact"] = True
    if travel_time is not None:
        options["travel_time"] = travel_time
    if options:
        entity.apply_gate_options(options)
    entity.fill_by_ha_state({"entity_id": entity_id, "state": relay_state, "attributes": {}})
    if link:
        entity.register_link("open_state", CONTACT)
        if contact is not None:
            entity.update_linked_data("open_state", {"entity_id": CONTACT, "state": contact, "attributes": {}})
    return entity, clock


def open_set_cmd_dict(action: str) -> dict:
    """Команда ``open_set`` для прямого вызова ``process_cmd``."""
    return {"states": [{"key": "open_set", "value": {"type": "ENUM", "enum_value": action}}]}


def states_map(entity: ImpulseGateEntity) -> dict[str, dict]:
    """Свернуть публикуемое состояние в карту «фича → значение»."""
    payload = entity.to_sber_current_state()[entity.entity_id]["states"]
    return {str(state["key"]): state["value"] for state in payload}


def open_state_of(entity: ImpulseGateEntity) -> str:
    """Публикуемое сейчас значение ``open_state``."""
    return str(states_map(entity)["open_state"]["enum_value"])


def declared_open_state_values(entity: ImpulseGateEntity) -> list[str] | None:
    """``allowed_values.open_state`` из модели (``None``, если не объявлено)."""
    allowed = entity.create_allowed_values_list()
    declared = allowed.get("open_state")
    if declared is None:
        return None
    return list(declared["enum_values"]["values"])


# ---------------------------------------------------------------------------
# Хелперы уровня моста
# ---------------------------------------------------------------------------


def make_real_entry(hass: HomeAssistant, options: dict | None = None) -> MockConfigEntry:
    """Создать зарегистрированный в hass config entry (без setup)."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=dict(SBER_CREDENTIALS),
        options=options or {},
        version=3,
    )
    entry.add_to_hass(hass)
    return entry


def make_bare_bridge(hass: HomeAssistant) -> SberBridge:
    """Собрать «подключённый» мост без сущностей: MQTT замокан, guard снят."""
    bridge = SberBridge(hass, make_real_entry(hass))
    bridge._mqtt_client = AsyncMock()
    bridge._mqtt_service.publish = AsyncMock()
    bridge._connected = True
    bridge._ack_audit.cancel()
    return bridge


async def make_gate_bridge(
    hass: HomeAssistant,
    *,
    travel_time: float | None = None,
    contact_state: str | None = "off",
    invert: bool = False,
    link: bool = True,
) -> tuple[SberBridge, ImpulseGateEntity, FakeClock]:
    """Поднять мост с одной импульсной калиткой на настоящем ``hass``.

    Args:
        hass: Настоящий HA из фикстуры.
        travel_time: Значение опции ``travel_time`` (``None`` — не задана).
        contact_state: Начальное состояние геркона (``None`` — геркона нет).
        invert: Опция ``invert_contact``.
        link: Регистрировать ли связь ролью ``open_state``.

    Returns:
        Тройка (мост, сущность, часы сущности).
    """
    bridge = make_bare_bridge(hass)
    entity, clock = make_gate(
        travel_time=travel_time,
        contact=contact_state,
        invert=invert,
        link=link,
    )

    hass.states.async_set(RELAY, "off")
    if contact_state is not None:
        hass.states.async_set(CONTACT, contact_state, {"device_class": "garage_door"})
    await hass.async_block_till_done()

    if link:
        bridge._entity_links = {RELAY: {"open_state": CONTACT}}
        bridge._linked_reverse = {CONTACT: (RELAY, "open_state")}

    bridge._entities[RELAY] = entity
    bridge._enabled_entity_ids = [RELAY]
    bridge._subscribe_ha_events()
    return bridge, entity, clock


def sber_cmd(entity_id: str, key: str, value: dict) -> bytes:
    """Собрать payload команды Sber на одну фичу одной сущности."""
    return json.dumps({"devices": {entity_id: {"states": [{"key": key, "value": value}]}}}).encode()


def open_set_cmd(action: str, entity_id: str = RELAY) -> bytes:
    """MQTT-команда ``open_set`` с ENUM-значением ``action``."""
    return sber_cmd(entity_id, "open_set", {"type": "ENUM", "enum_value": action})


def status_payloads(bridge: SberBridge) -> list[dict]:
    """Все опубликованные payload'ы ``up/status``."""
    out: list[dict] = []
    for call in bridge._mqtt_service.publish.call_args_list:
        args = call.args if call.args else call[0]
        if "up/status" in str(args[0]):
            out.append(json.loads(args[1]))
    return out


def config_payloads(bridge: SberBridge) -> list[dict]:
    """Все опубликованные payload'ы ``up/config``."""
    out: list[dict] = []
    for call in bridge._mqtt_service.publish.call_args_list:
        args = call.args if call.args else call[0]
        if "up/config" in str(args[0]):
            out.append(json.loads(args[1]))
    return out


def config_device(payload: dict, entity_id: str = RELAY) -> dict:
    """Описание одного устройства из payload'а ``up/config``."""
    devices = payload["devices"]
    device = next((d for d in devices if d.get("id") == entity_id), None)
    assert device is not None, f"{entity_id} отсутствует в config: {[d.get('id') for d in devices]}"
    return device


def published_open_states(bridge: SberBridge, entity_id: str = RELAY) -> list[str]:
    """``open_state`` из каждой публикации ``up/status``, по порядку.

    Публикации без ключа ``open_state`` (эхо команды ``open_set``)
    пропускаются: интересна именно последовательность положений створки,
    которую увидит облако.
    """
    values: list[str] = []
    for payload in status_payloads(bridge):
        device = payload.get("devices", {}).get(entity_id)
        if not device:
            continue
        values.extend(s["value"]["enum_value"] for s in device["states"] if s["key"] == "open_state")
    return values


def service_recorders(hass: HomeAssistant) -> dict[str, list]:
    """Перехватить все сервисы, которыми теоретически можно дёрнуть реле.

    Полная карта нужна, чтобы утверждать «ровно один ``switch.toggle`` и
    НОЛЬ всего остального»: проверка только на ``toggle`` пропустила бы
    мутацию «шлём и toggle, и turn_on».
    """
    return {
        "switch.toggle": async_mock_service(hass, "switch", "toggle"),
        "switch.turn_on": async_mock_service(hass, "switch", "turn_on"),
        "switch.turn_off": async_mock_service(hass, "switch", "turn_off"),
        "button.press": async_mock_service(hass, "button", "press"),
        "script.turn_on": async_mock_service(hass, "script", "turn_on"),
        "cover.open_cover": async_mock_service(hass, "cover", "open_cover"),
        "cover.close_cover": async_mock_service(hass, "cover", "close_cover"),
    }


def call_counts(recorders: dict[str, list]) -> dict[str, int]:
    """Свернуть перехватчики в карту «сервис → число вызовов»."""
    return {name: len(calls) for name, calls in recorders.items() if calls}


async def send_command(
    bridge: SberBridge,
    payload: bytes,
    hass: HomeAssistant,
    *,
    delays: list[float] | None = None,
) -> None:
    """Прогнать команду Sber через мост и дождаться всех эффектов.

    ``asyncio.sleep`` моста подменяется мгновенным (в тестах не спим), а
    запрошенные паузы при желании записываются в ``delays`` — именно они
    доказывают, что отложенное подтверждение заказано на время хода
    створки, а не на штатные 1.5 с.

    Args:
        bridge: Мост.
        payload: MQTT-payload команды.
        hass: HA.
        delays: Список для записи запрошенных пауз.
    """

    async def _sleep(delay: float, *args: Any, **kwargs: Any) -> None:
        if delays is not None:
            delays.append(delay)

    with patch("custom_components.sber_mqtt_bridge.sber_bridge.asyncio.sleep", side_effect=_sleep):
        await bridge._handle_sber_command(payload)
        await hass.async_block_till_done()
        async_fire_time_changed(hass, fire_all=True)
        await hass.async_block_till_done()


async def set_contact(hass: HomeAssistant, state: str) -> None:
    """Изменить состояние геркона и отпустить дебаунс публикации."""
    hass.states.async_set(CONTACT, state, {"device_class": "garage_door"})
    await hass.async_block_till_done()
    async_fire_time_changed(hass, fire_all=True)
    await hass.async_block_till_done()


# ---------------------------------------------------------------------------
# 1. travel_time выключено по умолчанию — поведение обязано быть прежним
# ---------------------------------------------------------------------------


class TestTravelTimeDisabledByDefault:
    """Выключенная эмуляция обязана быть неотличима от версии без неё."""

    def test_default_is_zero_and_nothing_is_emulated(self) -> None:
        """Без опций ворота не эмулируют движение и ничего не откладывают.

        Если тест упадёт, эмуляция включится у всех пользователей сама:
        ворота начнут сообщать ``opening`` в облако, которое об этом
        значении не предупреждали, — Sber молча выбросит состояние, и
        положение створки в приложении «залипнет».
        """
        entity, _clock = make_gate()

        assert entity.travel_time == 0.0
        assert entity.travel_direction is None
        assert entity.pending_confirm_delay is None

    def test_impulse_does_not_change_published_position(self) -> None:
        """Импульс на выключенной эмуляции не меняет публикуемое положение.

        Положение обязано меняться только по событию геркона.  Иначе
        ворота отрапортуют «открываются», геркон промолчит (он ещё не
        сработал), и облако получит значение, которого нет в модели.
        """
        entity, clock = make_gate(contact="off")

        results = entity.process_cmd(open_set_cmd_dict("open"))

        assert results == [
            {
                "url": {
                    "type": "call_service",
                    "domain": "switch",
                    "service": "toggle",
                    "target": {"entity_id": RELAY},
                }
            }
        ]
        assert open_state_of(entity) == "close"
        assert entity.travel_direction is None
        assert entity.pending_confirm_delay is None
        clock.advance(TRAVEL * 2)
        assert open_state_of(entity) == "close"

    def test_model_descriptor_is_byte_identical_to_pre_feature_version(self) -> None:
        """Набор фич, ``allowed_values`` и ``model.id`` совпадают с версией до фичи.

        ``model.id`` — дайджест возможностей устройства.  Если он
        поедет, у КАЖДОГО, кто уже подключил ворота, в облаке появится
        новое устройство: имя, комната и сценарии пропадут.
        """
        entity, _clock = make_gate(contact="off")

        assert entity.get_final_features_list() == ["online", "open_set", "open_state"]
        assert entity.create_allowed_values_list() == {
            "open_set": {"type": "ENUM", "enum_values": {"values": ["open", "close"]}},
        }
        assert entity.to_sber_state()["model"]["id"] == MODEL_ID_BEFORE_TRAVEL_FEATURE

    @pytest.mark.parametrize(
        "bad",
        [-0.5, -1, MAX_TRAVEL + 0.1, 6000, "20", True, [], {}, object()],
        ids=["negative_float", "negative_int", "over_max", "far_over_max", "string", "bool", "list", "dict", "object"],
    )
    def test_invalid_travel_time_keeps_emulation_off(self, bad: Any) -> None:
        """Мусорное ``travel_time`` не включает эмуляцию.

        Опции переживают перезапуск HA.  Правка конфига руками (или UI,
        приславший миллисекунды) не должна пригвоздить створку к
        фальшивому ``opening`` на часы — пользователь потеряет
        управление воротами из приложения.
        """
        entity, _clock = make_gate(travel_time=bad, contact="off")

        assert entity.travel_time == 0.0
        entity.process_cmd(open_set_cmd_dict("open"))
        assert entity.travel_direction is None
        assert open_state_of(entity) == "close"
        assert declared_open_state_values(entity) is None

    @pytest.mark.parametrize(
        "bad",
        [MAX_TRAVEL + 1, -1, "twenty", True, []],
        ids=["over_max", "negative", "string", "bool", "list"],
    )
    def test_invalid_value_does_not_erase_a_valid_one(self, bad: Any) -> None:
        """Отклонённое значение не сбрасывает уже настроенное время хода.

        Контроль к предыдущему тесту: «игнорировать» обязано означать
        именно игнорировать, а не молча выключать эмуляцию — иначе
        неудачный импорт конфигурации отключит фичу у тех, кто её
        настроил, и никто этого не заметит.
        """
        entity, _clock = make_gate(travel_time=TRAVEL, contact="off")

        entity.apply_gate_options({"travel_time": bad})

        assert entity.travel_time == TRAVEL

    def test_zero_switches_the_feature_off_and_cancels_running_emulation(self) -> None:
        """``travel_time=0`` гасит движение немедленно и убирает объявление.

        Пользователь выключает фичу именно тогда, когда она врёт про его
        ворота.  Если тест упадёт, выключение не подействует до
        следующего события геркона — то есть, возможно, никогда.
        """
        entity, _clock = make_gate(travel_time=TRAVEL, contact="off")
        entity.process_cmd(open_set_cmd_dict("open"))
        assert open_state_of(entity) == "opening"

        entity.apply_gate_options({"travel_time": 0})

        assert entity.travel_time == 0.0
        assert entity.travel_direction is None
        assert entity.pending_confirm_delay is None
        assert open_state_of(entity) == "close"
        assert declared_open_state_values(entity) is None
        assert entity.to_sber_state()["model"]["id"] == MODEL_ID_BEFORE_TRAVEL_FEATURE

    def test_explicit_none_switches_the_feature_off_like_zero(self) -> None:
        """``travel_time: null`` — это «выключено», а не «проигнорировать».

        JSON-импорт конфигурации и правка руками кладут в опции именно
        ``null`` там, где UI кладёт ``0``.  Если ``None`` попадёт в общую
        ветку «нечисловое значение — игнорируем», выключение фичи из
        импортированного конфига молча не сработает: у пользователя
        останется старое время хода, створка продолжит эмулировать
        движение, а в опциях будет написано, что фича выключена.
        """
        entity, _clock = make_gate(travel_time=TRAVEL, contact="off")
        entity.process_cmd(open_set_cmd_dict("open"))
        assert open_state_of(entity) == "opening"

        entity.apply_gate_options({"travel_time": None})

        assert entity.travel_time == 0.0
        assert entity.travel_direction is None
        assert entity.pending_confirm_delay is None
        assert open_state_of(entity) == "close"
        assert declared_open_state_values(entity) is None
        assert entity.to_sber_state()["model"]["id"] == MODEL_ID_BEFORE_TRAVEL_FEATURE

    async def test_bridge_asks_for_no_deferred_confirm_when_disabled(self, hass: HomeAssistant) -> None:
        """С выключенной эмуляцией мост заводит ровно один таймер подтверждения.

        Второй (отложенный) слот — это лишняя публикация в облако через
        десятки секунд.  На выключенной фиче его быть не должно вовсе,
        иначе поведение по умолчанию перестанет быть «как раньше».
        """
        bridge, _entity, _clock = await make_gate_bridge(hass, travel_time=None, contact_state="off")

        bridge.schedule_confirm(RELAY)
        slots = set(bridge._confirm_tasks)

        for task in bridge._confirm_tasks.values():
            task.cancel()
        assert slots == {RELAY}


# ---------------------------------------------------------------------------
# 2. Включённая эмуляция: направление и объявление значений
# ---------------------------------------------------------------------------


class TestTravelDirection:
    """Направление эмуляции берётся из известного положения створки."""

    @pytest.mark.parametrize(
        ("contact", "action", "expected"),
        [
            ("off", "open", "opening"),
            ("on", "close", "closing"),
        ],
        ids=["closed_gate_opens", "open_gate_closes"],
    )
    def test_impulse_publishes_direction(self, contact: str, action: str, expected: str) -> None:
        """После импульса публикуется ``opening`` / ``closing`` в нужную сторону.

        Перепутанное направление — это «закрываются» на открывающихся
        воротах: пользователь увидит в приложении, что створка едет
        закрываться, и отправит вторую команду, которая реально
        остановит ворота посреди проёма.
        """
        entity, _clock = make_gate(travel_time=TRAVEL, contact=contact)

        entity.process_cmd(open_set_cmd_dict(action))

        assert entity.travel_direction == expected
        assert open_state_of(entity) == expected
        # Эмуляция не имеет права ни добавлять ключи состояния, ни ронять
        # ``online``: и то, и другое — повод для облака выбросить публикацию.
        assert set(states_map(entity)) == {"online", "open_state"}
        assert states_map(entity)["online"]["bool_value"] is True

    def test_direction_follows_logical_position_not_raw_contact(self) -> None:
        """С инвертированным герконом направление считается по логическому положению.

        ``invert_contact`` есть у самодельных герконов.  Если направление
        брать из сырого ``on``/``off``, у таких пользователей эмуляция
        будет показывать ровно противоположное движение.
        """
        entity, _clock = make_gate(travel_time=TRAVEL, contact="on", invert=True)
        assert open_state_of(entity) == "close", "инверсия: геркон 'on' означает закрытые ворота"

        entity.process_cmd(open_set_cmd_dict("open"))

        assert open_state_of(entity) == "opening"

    def test_pending_confirm_delay_covers_the_whole_travel(self) -> None:
        """Отложенное подтверждение заказывается на время хода плюс запас.

        Мост спит по своим часам, сущность меряет дедлайн по своим.  Если
        пауза окажется не больше времени хода, подтверждение опубликует
        ``opening`` ещё раз, и створка «застрянет» в движении до
        следующего события геркона.
        """
        entity, clock = make_gate(travel_time=TRAVEL, contact="off")

        entity.process_cmd(open_set_cmd_dict("open"))
        assert entity.pending_confirm_delay == TRAVEL + CONFIRM_MARGIN

        clock.advance(5.0)
        assert entity.pending_confirm_delay == TRAVEL - 5.0 + CONFIRM_MARGIN

    def test_pending_confirm_delay_is_none_at_rest(self) -> None:
        """Пока створка стоит, откладывать нечего.

        Иначе мост будет бесконечно перезапускать отложенную публикацию
        на каждую команду, включая те, что вообще не дали импульса.
        """
        entity, _clock = make_gate(travel_time=TRAVEL, contact="off")

        assert entity.pending_confirm_delay is None


class TestAllowedValuesFollowTheOption:
    """``allowed_values.open_state`` появляется и исчезает вместе с фичей."""

    def test_declared_only_when_enabled(self) -> None:
        """С включённой эмуляцией объявляются ровно четыре значения, с выключенной — ноль.

        Sber молча игнорирует значение состояния, о котором устройство не
        предупредило (корень issue #44): без объявления публикация
        ``opening`` пропадёт бесследно, а с объявлением на выключенной
        фиче в приложении появятся состояния, которых устройство никогда
        не пришлёт.
        """
        entity, _clock = make_gate(travel_time=TRAVEL, contact="off")

        declared = declared_open_state_values(entity)
        assert declared is not None, "включённая эмуляция обязана объявить open_state"
        assert set(declared) == TRAVEL_OPEN_STATE_SET
        assert len(declared) == len(TRAVEL_OPEN_STATE_SET), f"дубликаты в enum: {declared}"
        assert entity.create_allowed_values_list()["open_state"]["type"] == "ENUM"
        assert entity.create_allowed_values_list()["open_set"] == {
            "type": "ENUM",
            "enum_values": {"values": ["open", "close"]},
        }, "команда open_set остаётся двузначной: 'opening' нельзя приказать"

    def test_model_id_changes_only_with_the_option(self) -> None:
        """Включение фичи меняет ``model.id``, выключение — возвращает прежний.

        Дайджест обязан следовать за реально объявленными
        возможностями: иначе облако будет держать устаревшее описание
        модели и снова отбрасывать ``opening``.
        """
        entity, _clock = make_gate(travel_time=TRAVEL, contact="off")
        travelling_model_id = entity.to_sber_state()["model"]["id"]

        assert travelling_model_id != MODEL_ID_BEFORE_TRAVEL_FEATURE

        entity.apply_gate_options({"travel_time": 0})
        assert entity.to_sber_state()["model"]["id"] == MODEL_ID_BEFORE_TRAVEL_FEATURE

    @pytest.mark.parametrize(
        ("contact", "action", "expected"),
        [
            ("off", "open", "opening"),
            ("on", "close", "closing"),
        ],
        ids=["opening", "closing"],
    )
    def test_every_published_value_is_declared(self, contact: str, action: str, expected: str) -> None:
        """Публикуемое во время хода значение обязано быть среди объявленных.

        Это и есть защита от issue #44: несовпадение публикации и
        ``allowed_values`` означает, что облако молча выбросит состояние,
        и створка в приложении останется в прежнем положении навсегда.
        """
        entity, _clock = make_gate(travel_time=TRAVEL, contact=contact)

        entity.process_cmd(open_set_cmd_dict(action))

        assert open_state_of(entity) == expected
        assert expected in (declared_open_state_values(entity) or [])

    def test_enabled_gate_publishes_nothing_beyond_the_declaration(self) -> None:
        """За полный цикл включённая эмуляция публикует РОВНО объявленные значения.

        Предыдущий тест смотрит только на транзитные ``opening`` /
        ``closing``.  Створка в покое при включённой опции публикует
        ``open`` / ``close`` — и они обязаны остаться в объявлении: если
        из ``allowed_values.open_state`` выкинуть «покоящиеся» значения,
        облако молча выбросит именно тот финальный ``open``, ради
        которого всё и затевалось, и створка в приложении навсегда
        застрянет в «открывается» (issue #44).

        Равенство множеств, а не вложение: лишнее объявленное значение —
        это состояние, которое устройство никогда не пришлёт, то есть
        мёртвый пункт в интерфейсе приложения.
        """
        entity, clock = make_gate(travel_time=TRAVEL, contact="off")
        declared = declared_open_state_values(entity)
        assert declared is not None, "включённая эмуляция обязана объявить open_state"

        seen = {open_state_of(entity)}
        entity.process_cmd(open_set_cmd_dict("open"))
        seen.add(open_state_of(entity))
        clock.advance(3.0)
        entity.update_linked_data("open_state", {"entity_id": CONTACT, "state": "on", "attributes": {}})
        seen.add(open_state_of(entity))
        clock.advance(IMPULSE_COOLDOWN + 0.1)
        entity.process_cmd(open_set_cmd_dict("close"))
        seen.add(open_state_of(entity))
        clock.advance(TRAVEL + 0.1)
        seen.add(open_state_of(entity))

        assert seen == TRAVEL_OPEN_STATE_SET, "цикл обязан пройти через все четыре значения"
        assert seen == set(declared)

    def test_disabled_gate_publishes_only_open_and_close(self) -> None:
        """С выключенной фичей за весь цикл публикуются только ``open``/``close``.

        Полное множество, а не отдельная проверка: любое транзитное
        значение на выключенной эмуляции необъявлено и будет отброшено
        облаком.
        """
        entity, clock = make_gate(contact="off")
        seen = {open_state_of(entity)}

        entity.process_cmd(open_set_cmd_dict("open"))
        seen.add(open_state_of(entity))
        clock.advance(TRAVEL)
        seen.add(open_state_of(entity))
        entity.update_linked_data("open_state", {"entity_id": CONTACT, "state": "on", "attributes": {}})
        seen.add(open_state_of(entity))

        assert seen == {"open", "close"}


# ---------------------------------------------------------------------------
# 3. Геркон отменяет эмуляцию немедленно
# ---------------------------------------------------------------------------


class TestContactCancelsEmulation:
    """Догадка не имеет права пережить появление реальных данных."""

    def test_contact_report_ends_travel_immediately(self) -> None:
        """Срабатывание геркона мгновенно отменяет эмуляцию и публикует факт.

        Если тест упадёт, ворота будут показывать «открываются» ещё
        десяток секунд после того, как реально открылись — и всё это
        время команда «открой» будет гаситься как «уже едем туда».
        """
        entity, clock = make_gate(travel_time=TRAVEL, contact="off")
        entity.process_cmd(open_set_cmd_dict("open"))
        assert open_state_of(entity) == "opening"

        clock.advance(3.0)
        entity.update_linked_data("open_state", {"entity_id": CONTACT, "state": "on", "attributes": {}})

        assert entity.travel_direction is None
        assert entity.pending_confirm_delay is None
        assert open_state_of(entity) == "open"

    def test_contact_repeating_the_old_position_keeps_the_travel_alive(self) -> None:
        """Показание «створка всё ещё закрыта» НЕ отменяет эмуляцию.

        На первой секунде двадцатисекундного хода геркон обязан читать
        «закрыто»: створка ещё не отошла от магнита.  Это показание
        ничего не сообщает о движении, а поводов прилететь у него полно —
        Zigbee-геркон отчитывается о ``battery``/``linkquality``,
        MQTT-биндинг с ``force_update`` шлёт то же состояние на каждое
        сообщение, а сохранение опций прогоняет текущее состояние через
        ``_refresh_entity_from_ha``.  Отмена по такому событию убивала
        фичу в первые секунды хода на типовом железе — и вместе с ней
        гард «уже едем туда», так что следующая команда давала второй
        импульс и физически останавливала створку посреди проёма.

        Реально заклинившие ворота геркон вообще не комментирует: их
        разбирает дедлайн хода (см. ``TestTravelDeadline``).
        """
        entity, clock = make_gate(travel_time=TRAVEL, contact="off")
        entity.process_cmd(open_set_cmd_dict("open"))

        clock.advance(1.0)
        entity.update_linked_data("open_state", {"entity_id": CONTACT, "state": "off", "attributes": {}})

        assert entity.travel_direction == "opening"
        assert open_state_of(entity) == "opening"

    def test_stuck_gate_is_settled_by_the_deadline_not_by_the_contact(self) -> None:
        """Заклинившие ворота всё равно возвращаются к правде — по дедлайну.

        Контроль к предыдущему тесту: отказавшись отменять ход по
        неинформативному показанию, эмуляция не имеет права стать
        вечной.
        """
        entity, clock = make_gate(travel_time=TRAVEL, contact="off")
        entity.process_cmd(open_set_cmd_dict("open"))

        clock.advance(1.0)
        entity.update_linked_data("open_state", {"entity_id": CONTACT, "state": "off", "attributes": {}})
        clock.advance(TRAVEL)

        assert entity.travel_direction is None
        assert open_state_of(entity) == "close"

    @pytest.mark.parametrize("dropped", ["unavailable", "unknown"])
    def test_contact_dropout_ends_travel_and_shows_last_known_position(self, dropped: str) -> None:
        """Пропажа геркона обрывает эмуляцию и возвращает последнее известное положение.

        Пока датчик недоступен, эмуляция подтвердить себя уже не сможет
        ничем: продолжать её — значит держать в облаке вечное
        «открываются».
        """
        entity, _clock = make_gate(travel_time=TRAVEL, contact="on")
        entity.process_cmd(open_set_cmd_dict("close"))
        assert open_state_of(entity) == "closing"

        entity.update_linked_data("open_state", {"entity_id": CONTACT, "state": dropped, "attributes": {}})

        assert entity.travel_direction is None
        assert entity.contact_stale is True
        assert open_state_of(entity) == "open"

    async def test_contact_event_publishes_real_position_through_the_bridge(
        self,
        hass: HomeAssistant,
    ) -> None:
        """Событие геркона доезжает до облака и заменяет эмулированное значение.

        Сквозная проверка: сущность может отменить эмуляцию у себя
        внутри, но если мост не опубликует новое состояние, в приложении
        Салют ворота так и останутся «открывающимися».
        """
        bridge, _entity, _clock = await make_gate_bridge(hass, travel_time=TRAVEL, contact_state="off")
        await send_command(bridge, open_set_cmd("open"), hass)
        assert published_open_states(bridge)[-1] == "opening"

        bridge._mqtt_service.publish.reset_mock()
        await set_contact(hass, "on")

        assert published_open_states(bridge) == ["open"]

    async def test_attribute_only_contact_event_does_not_touch_the_travel(
        self,
        hass: HomeAssistant,
    ) -> None:
        """Событие геркона «то же состояние, новый атрибут» не трогает эмуляцию.

        ``HaStateForwarder`` пробрасывает связанной сущности КАЖДОЕ
        ``state_changed`` геркона, включая те, где изменился только
        атрибут.  Типовой Zigbee-геркон репортит ``battery`` /
        ``linkquality`` чаще, чем едет створка, — на таком железе
        эмуляция умирала в первые секунды хода, а в облако уезжало
        «закрыто» на едущих воротах.
        """
        bridge, entity, _clock = await make_gate_bridge(hass, travel_time=TRAVEL, contact_state="off")
        await send_command(bridge, open_set_cmd("open"), hass)
        assert published_open_states(bridge)[-1] == "opening"

        bridge._mqtt_service.publish.reset_mock()
        hass.states.async_set(CONTACT, "off", {"device_class": "garage_door", "battery_level": 91})
        await hass.async_block_till_done()
        async_fire_time_changed(hass, fire_all=True)
        await hass.async_block_till_done()

        assert entity.travel_direction == "opening"
        assert set(published_open_states(bridge)) <= {"opening"}, "положение створки не менялось"

    async def test_saving_options_mid_travel_does_not_cancel_it(self, hass: HomeAssistant) -> None:
        """Сохранение опций не имеет права остановить эмуляцию.

        ``SberBridge._refresh_entity_from_ha`` (его зовёт
        ``async_update_gate_options``) прогоняет ТЕКУЩЕЕ состояние
        геркона обратно в сущность.  Пока это считалось «геркон
        отчитался», галочка «инвертировать контакт», нажатая во время
        хода, гасила движение — мимо всякого forwarder'а.
        """
        bridge, entity, _clock = await make_gate_bridge(hass, travel_time=TRAVEL, contact_state="off")
        await send_command(bridge, open_set_cmd("open"), hass)
        assert entity.travel_direction == "opening"

        bridge._refresh_entity_from_ha(RELAY)

        assert entity.travel_direction == "opening"
        assert open_state_of(entity) == "opening"


class TestUnknownPositionIsNotEmulated:
    """Догадка о направлении требует достоверного положения створки."""

    @pytest.mark.parametrize(
        ("contact", "stale", "action", "expected"),
        [
            ("on", True, "open", "open"),
            ("off", True, "close", "close"),
            (None, False, "open", "close"),
            (None, False, "close", "close"),
        ],
        ids=["stale_open_asked_open", "stale_close_asked_close", "never_seen_open", "never_seen_close"],
    )
    def test_no_direction_is_published_while_the_position_is_unknown(
        self,
        contact: str | None,
        stale: bool,
        action: str,
        expected: str,
    ) -> None:
        """Недостоверное положение не даёт эмулировать ход.

        Направление выводится из последнего известного положения.  Если
        положение — заглушка (геркон ни разу не отчитался) или протухло
        (датчик отваливался), догадка строится на пустом месте и
        публикует направление, ПРОТИВОПОЛОЖНОЕ просьбе пользователя:
        «открой» на воротах, ошибочно считающихся открытыми, уезжало в
        облако как ``closing``.  Честный ответ — не эмулировать вовсе и
        ждать геркон.
        """
        entity, _clock = make_gate(travel_time=TRAVEL, contact=contact)
        if stale:
            entity.update_linked_data("open_state", {"entity_id": CONTACT, "state": "unavailable", "attributes": {}})

        entity.process_cmd(open_set_cmd_dict(action))

        assert entity.travel_direction is None
        assert entity.pending_confirm_delay is None
        assert open_state_of(entity) == expected

    def test_emulation_resumes_once_the_contact_speaks(self) -> None:
        """Как только геркон отчитался, эмуляция снова работает.

        Контроль: отказ эмулировать при неизвестном положении не имеет
        права стать постоянным — иначе один пропавший на минуту датчик
        выключит фичу до перезагрузки HA.
        """
        entity, _clock = make_gate(travel_time=TRAVEL, contact=None)
        entity.update_linked_data("open_state", {"entity_id": CONTACT, "state": "off", "attributes": {}})

        entity.process_cmd(open_set_cmd_dict("open"))

        assert entity.travel_direction == "opening"
        assert open_state_of(entity) == "opening"


# ---------------------------------------------------------------------------
# 4. Истечение дедлайна
# ---------------------------------------------------------------------------


class TestTravelDeadline:
    """Неподтверждённое движение обязано честно закончиться.

    Единственный источник правды — геркон.  Если он молчит всё время
    хода, честный ответ ровно один: «створка там, где была», плюс
    предупреждение в журнал для владельца.
    """

    def test_direction_holds_until_the_deadline(self) -> None:
        """До истечения времени хода публикуется движение.

        Контроль к следующему тесту: досрочное «схлопывание» эмуляции
        сделало бы фичу бессмысленной — облако увидело бы движение на
        доли секунды.
        """
        entity, clock = make_gate(travel_time=TRAVEL, contact="off")
        entity.process_cmd(open_set_cmd_dict("open"))

        clock.advance(TRAVEL - 0.1)

        assert open_state_of(entity) == "opening"
        assert entity.travel_direction == "opening"

    @pytest.mark.parametrize(
        ("contact", "action", "moving", "expected"),
        [
            ("off", "open", "opening", "close"),
            ("on", "close", "closing", "open"),
        ],
        ids=["stuck_while_opening", "stuck_while_closing"],
    )
    def test_expiry_falls_back_to_last_known_position(
        self,
        contact: str,
        action: str,
        moving: str,
        expected: str,
    ) -> None:
        """По истечении времени хода возвращается последнее известное положение.

        Привод заклинило / пропало питание — геркон не сработал.
        Оставить «открываются» значило бы навсегда заблокировать команду
        «открой» гардом «мы уже едем туда»: ворота станут неуправляемыми
        из приложения.
        """
        entity, clock = make_gate(travel_time=TRAVEL, contact=contact)
        entity.process_cmd(open_set_cmd_dict(action))
        assert open_state_of(entity) == moving

        clock.advance(TRAVEL)

        assert entity.travel_direction is None
        assert entity.pending_confirm_delay is None
        assert open_state_of(entity) == expected

    def test_expiry_logs_exactly_one_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """Неподтверждённый ход пишет ровно одно предупреждение с id и положением.

        Молчаливый откат к прежнему положению выглядит для владельца как
        «Sber глючит».  Предупреждение — единственный след неисправного
        геркона или привода; повтор на каждом чтении состояния, наоборот,
        зальёт журнал.
        """
        entity, clock = make_gate(travel_time=TRAVEL, contact="off")
        entity.process_cmd(open_set_cmd_dict("open"))

        with caplog.at_level(logging.WARNING, logger=GATE_LOGGER):
            clock.advance(TRAVEL)
            assert open_state_of(entity) == "close"
            assert open_state_of(entity) == "close"

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING and r.name == GATE_LOGGER]
        assert len(warnings) == 1, [r.getMessage() for r in warnings]
        message = warnings[0].getMessage()
        assert RELAY in message
        assert "opening" in message
        assert "close" in message

    def test_expired_gate_accepts_the_same_direction_again(self) -> None:
        """После истечения хода команда в ту же сторону снова даёт импульс.

        Это обратная сторона отката: если гард «уже едем туда» переживёт
        дедлайн, повторная команда «открой» на застрявших воротах не
        сделает ничего, и пользователь не сможет дёрнуть привод из
        приложения.
        """
        entity, clock = make_gate(travel_time=TRAVEL, contact="off")
        entity.process_cmd(open_set_cmd_dict("open"))
        clock.advance(TRAVEL)

        results = entity.process_cmd(open_set_cmd_dict("open"))

        assert len(results) == 1
        assert results[0]["url"] == {
            "type": "call_service",
            "domain": "switch",
            "service": "toggle",
            "target": {"entity_id": RELAY},
        }


# ---------------------------------------------------------------------------
# 5. Команды во время эмулированного хода
# ---------------------------------------------------------------------------


class TestCommandsDuringTravel:
    """Одна кнопка: направление команды решает, слать ли импульс."""

    async def test_same_direction_sends_no_service_call(self, hass: HomeAssistant) -> None:
        """Команда в ту же сторону, куда едем, не даёт НИ ОДНОГО вызова.

        Второй импульс на едущей створке физически её останавливает.
        Пользователь, дважды сказавший «открой ворота», получил бы
        ворота, замершие посреди проёма.
        """
        recorders = service_recorders(hass)
        bridge, _entity, clock = await make_gate_bridge(hass, travel_time=TRAVEL, contact_state="off")

        await send_command(bridge, open_set_cmd("open"), hass)
        assert call_counts(recorders) == {"switch.toggle": 1}

        clock.advance(IMPULSE_COOLDOWN + 1.0)
        await send_command(bridge, open_set_cmd("open"), hass)

        assert call_counts(recorders) == {"switch.toggle": 1}, "второй импульс остановил бы створку"
        assert published_open_states(bridge)[-1] == "opening", "отказ от импульса обязан подтвердить состояние"

    async def test_opposite_direction_sends_a_second_impulse(self, hass: HomeAssistant) -> None:
        """Команда в противоположную сторону даёт импульс — это и есть «стоп/реверс».

        Пользователь, передумавший на середине хода, обязан иметь
        возможность дёрнуть привод.  Если тест упадёт, «закрой» во время
        открывания будет проигнорирована — створка доедет до конца.
        """
        recorders = service_recorders(hass)
        bridge, entity, clock = await make_gate_bridge(hass, travel_time=TRAVEL, contact_state="off")

        await send_command(bridge, open_set_cmd("open"), hass)
        clock.advance(IMPULSE_COOLDOWN + 1.0)
        await send_command(bridge, open_set_cmd("close"), hass)

        assert call_counts(recorders) == {"switch.toggle": 2}
        assert entity.travel_direction is None, "после встречной команды положение створки неизвестно"
        assert published_open_states(bridge)[-1] == "close", "правду знает только геркон"

    async def test_counter_command_inside_cooldown_is_swallowed(self, hass: HomeAssistant) -> None:
        """Встречная команда внутри антидребезга не шлёт импульс и не ломает эмуляцию.

        Дубль команды (повтор из приложения, ретрай после потерянного
        ack) обязан гаситься: иначе одна кнопка получит два импульса
        подряд и створка дёрнется туда-обратно.
        """
        recorders = service_recorders(hass)
        bridge, entity, clock = await make_gate_bridge(hass, travel_time=TRAVEL, contact_state="off")

        await send_command(bridge, open_set_cmd("open"), hass)
        clock.advance(IMPULSE_COOLDOWN / 2)
        await send_command(bridge, open_set_cmd("close"), hass)

        assert call_counts(recorders) == {"switch.toggle": 1}
        assert entity.travel_direction == "opening"


# ---------------------------------------------------------------------------
# 6. Отложенная публикация: мост обязан довести эмуляцию до конца
# ---------------------------------------------------------------------------


class TestDeferredConfirmPublication:
    """Эмулированное значение обязано быть заменено настоящим."""

    async def test_bridge_arms_two_slots_and_asks_for_the_travel_delay(
        self,
        hass: HomeAssistant,
    ) -> None:
        """Мост заводит отдельный отложенный слот на время хода створки.

        Если отложенное подтверждение отменит короткое (общий слот),
        Sber не получит быстрого ответа на команду и посчитает её
        неисполненной; если паузу заказать штатные 1.5 с, подтверждение
        опубликует всё то же ``opening``.
        """
        delays: list[float] = []
        service_recorders(hass)
        bridge, _entity, _clock = await make_gate_bridge(hass, travel_time=TRAVEL, contact_state="off")

        await send_command(bridge, open_set_cmd("open"), hass, delays=delays)

        # ``sleep(0)`` — это точки уступки управления в других местах моста,
        # к подтверждениям они отношения не имеют.
        assert sorted(d for d in delays if d) == [DEFAULT_CONFIRM_DELAY, TRAVEL + CONFIRM_MARGIN]

    async def test_deferred_slot_does_not_replace_the_short_one(self, hass: HomeAssistant) -> None:
        """Короткое и отложенное подтверждения живут в разных слотах.

        Иначе одно из них будет отменено сразу после создания: либо Sber
        не увидит быстрый ответ, либо створка навсегда останется
        «едущей».
        """
        bridge, entity, _clock = await make_gate_bridge(hass, travel_time=TRAVEL, contact_state="off")
        entity.process_cmd(open_set_cmd_dict("open"))

        bridge.schedule_confirm(RELAY)
        slots = dict(bridge._confirm_tasks)

        for task in slots.values():
            task.cancel()
        assert set(slots) == {RELAY, f"{RELAY}#deferred"}
        assert not any(task.cancelled() for task in slots.values())

    async def test_deferred_slot_is_cleared_when_no_travel_is_pending(self, hass: HomeAssistant) -> None:
        """Слот отложенного подтверждения снимается вместе с эмуляцией.

        Встречная команда (а также приезд геркона и выключение опции)
        отменяет ход — заказ на отложенную публикацию исчезает.  Таймер,
        заведённый под уже отменённое движение, доживал до конца хода
        (до 10 минут) и выстреливал лишней принудительной публикацией.
        """
        bridge, entity, clock = await make_gate_bridge(hass, travel_time=TRAVEL, contact_state="off")
        entity.process_cmd(open_set_cmd_dict("open"))
        bridge.schedule_confirm(RELAY)
        armed = bridge._confirm_tasks[f"{RELAY}#deferred"]

        clock.advance(IMPULSE_COOLDOWN + 1.0)
        entity.process_cmd(open_set_cmd_dict("close"))
        assert entity.pending_confirm_delay is None, "предусловие: встречная команда сняла эмуляцию"
        bridge.schedule_confirm(RELAY)

        leftovers = dict(bridge._confirm_tasks)
        for task in leftovers.values():
            task.cancel()

        assert set(leftovers) == {RELAY}, "отложенный слот обязан исчезнуть вместе с эмуляцией"
        assert armed.cancelling() == 1, "снятый таймер обязан быть отменён, а не просто забыт"

    async def test_deferred_slot_is_not_a_tracked_task(self, hass: HomeAssistant) -> None:
        """Отложенное подтверждение — фоновая задача, а не отслеживаемая HA.

        Пауза здесь измеряется целым временем хода створки (до 600.5 с),
        а ``_create_safe_task`` своим же docstring'ом разрешает только
        короткую работу: отслеживаемая задача такой длины держит каждый
        ``async_block_till_done`` (то есть каждый тест, задевший едущие
        ворота) и доживает до финальной стадии выключения HA.
        """
        bridge, entity, _clock = await make_gate_bridge(hass, travel_time=TRAVEL, contact_state="off")
        entity.process_cmd(open_set_cmd_dict("open"))

        bridge.schedule_confirm(RELAY)

        short = bridge._confirm_tasks[RELAY]
        deferred = bridge._confirm_tasks[f"{RELAY}#deferred"]
        assert deferred in hass._background_tasks, "долгая пауза обязана быть фоновой"
        assert deferred not in hass._tasks
        assert short in hass._tasks, "короткое подтверждение остаётся отслеживаемым"
        for task in (short, deferred):
            task.cancel()

    async def test_deferred_confirm_publishes_the_settled_position(self, hass: HomeAssistant) -> None:
        """Отложенное подтверждение публикует уже осевшее положение, а не движение.

        Это последняя публикация всей цепочки.  Если она отправит
        ``opening``, ворота в приложении Салют останутся открывающимися
        навсегда — до следующего события геркона.
        """
        bridge, _entity, clock = await make_gate_bridge(hass, travel_time=TRAVEL, contact_state="off")
        await send_command(bridge, open_set_cmd("open"), hass)
        assert published_open_states(bridge)[-1] == "opening"

        bridge._mqtt_service.publish.reset_mock()
        clock.advance(TRAVEL + CONFIRM_MARGIN)
        with patch(
            "custom_components.sber_mqtt_bridge.sber_bridge.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            await bridge._delayed_confirm(RELAY, delay=TRAVEL + CONFIRM_MARGIN, slot=f"{RELAY}#deferred")
            await hass.async_block_till_done()

        assert published_open_states(bridge) == ["close"]


# ---------------------------------------------------------------------------
# 7. Отсутствие обязательной связи: ремонт, диагностика, карточка устройства
# ---------------------------------------------------------------------------


def issue_ids(registry: ir.IssueRegistry) -> set[str]:
    """Идентификаторы всех проблем, которыми владеет интеграция."""
    return {issue_id for (domain, issue_id) in registry.issues if domain == DOMAIN}


class TestMissingRequiredLinkIsVisible:
    """Ворота без геркона обязаны быть ЗАМЕТНЫ, а не тихо врать «закрыто»."""

    async def test_bridge_reports_the_unmapped_role(self, hass: HomeAssistant) -> None:
        """Мост перечисляет незаполненные обязательные роли.

        Источник данных сразу для трёх потребителей (ремонт,
        диагностика, панель).  Пустой ответ здесь означает, что все три
        промолчат.
        """
        bridge, _entity, _clock = await make_gate_bridge(hass, contact_state=None, link=False)

        assert bridge.entities_missing_required_links == {RELAY: ["open_state"]}

    async def test_fully_linked_gate_reports_nothing(self, hass: HomeAssistant) -> None:
        """Настроенные ворота не порождают ложной тревоги.

        Контроль: постоянно висящая плитка ремонта обесценивает сам
        механизм — пользователь перестаёт читать предупреждения.
        """
        bridge, _entity, _clock = await make_gate_bridge(hass, contact_state="off", link=True)

        assert bridge.entities_missing_required_links == {}

    async def test_repair_issue_created_with_meaningful_placeholders(
        self,
        hass: HomeAssistant,
        issue_registry: ir.IssueRegistry,
    ) -> None:
        """Заводится ремонт ``missing_required_links`` с числом и списком ролей.

        Текст плитки собирается из плейсхолдеров.  Если их набор не
        совпадёт с шаблоном перевода, HA покажет пустую или сломанную
        плитку — то есть единственный сигнал о неработающих воротах
        исчезнет.
        """
        bridge, _entity, _clock = await make_gate_bridge(hass, contact_state=None, link=False)

        await check_and_create_issues(hass, bridge)

        assert "missing_required_links" in issue_ids(issue_registry)
        issue = issue_registry.async_get_issue(DOMAIN, "missing_required_links")
        assert issue is not None
        assert issue.translation_key == "missing_required_links"
        assert issue.translation_placeholders == {"count": "1", "entities": f"{RELAY} (open_state)"}
        assert issue.severity == ir.IssueSeverity.WARNING
        assert issue.is_fixable is False

    @pytest.mark.parametrize("translations", ["strings.json", "translations/en.json", "translations/ru.json"])
    def test_issue_text_is_translated_and_uses_exactly_the_given_placeholders(
        self,
        translations: str,
    ) -> None:
        """Текст ремонта существует во всех переводах и использует ровно те плейсхолдеры, что даёт код.

        HA подставляет плейсхолдеры по имени: лишний ``{roles}`` в
        шаблоне уронит рендер плитки, а недостающий ``{entities}``
        оставит пользователя без имени сломанного устройства — он не
        поймёт, какое устройство чинить.
        """
        import re
        from pathlib import Path

        root = Path(__file__).resolve().parents[2] / "custom_components" / "sber_mqtt_bridge"
        data = json.loads((root / translations).read_text(encoding="utf-8"))
        issue = data["issues"]["missing_required_links"]

        assert set(issue) >= {"title", "description"}
        assert issue["title"].strip() != ""
        assert set(re.findall(r"{(\w+)}", issue["description"])) == {"count", "entities"}
        assert set(re.findall(r"{(\w+)}", issue["title"])) == set()
        assert len(issue["description"]) > 60, "описание обязано объяснять, что делать, а не только констатировать"

    async def test_repair_issue_disappears_once_the_contact_is_linked(
        self,
        hass: HomeAssistant,
        issue_registry: ir.IssueRegistry,
    ) -> None:
        """Появление связи снимает плитку ремонта.

        Незакрывающийся ремонт хуже отсутствующего: пользователь
        привяжет геркон, увидит ту же ошибку и решит, что интеграция
        сломана.
        """
        bridge, entity, _clock = await make_gate_bridge(hass, contact_state=None, link=False)
        await check_and_create_issues(hass, bridge)
        assert issue_registry.async_get_issue(DOMAIN, "missing_required_links") is not None

        hass.states.async_set(CONTACT, "off", {"device_class": "garage_door"})
        await hass.async_block_till_done()
        entity.register_link("open_state", CONTACT)
        bridge._entity_links = {RELAY: {"open_state": CONTACT}}

        await check_and_create_issues(hass, bridge)

        assert bridge.entities_missing_required_links == {}
        assert issue_registry.async_get_issue(DOMAIN, "missing_required_links") is None

    async def test_diagnostics_carry_the_flag(self, hass: HomeAssistant) -> None:
        """Флаг попадает в диагностику — и в сводку, и в карточку сущности.

        Диагностика — то, что пользователь приложит к issue на GitHub.
        Без флага сопровождающий будет искать причину «ворота всегда
        закрыты» в протоколе, а не в отсутствующей связи.
        """
        bridge, _entity, _clock = await make_gate_bridge(hass, contact_state=None, link=False)
        entry = MagicMock()
        entry.data = dict(SBER_CREDENTIALS)
        entry.options = {}
        entry.runtime_data = MagicMock()
        entry.runtime_data.bridge = bridge

        result = await async_get_config_entry_diagnostics(hass, entry)

        assert result["bridge"]["entities_missing_required_links"] == {RELAY: ["open_state"]}
        gate_entry = next(e for e in result["entities"] if e["entity_id"] == RELAY)
        assert gate_entry["missing_required_links"] == ["open_state"]

    async def test_diagnostics_are_clean_for_a_linked_gate(self, hass: HomeAssistant) -> None:
        """У настроенных ворот флаг присутствует и пуст.

        Ключ обязан быть всегда: потребитель (панель/скрипт) не должен
        отличать «поле не пришло» от «всё хорошо».
        """
        bridge, _entity, _clock = await make_gate_bridge(hass, contact_state="off", link=True)
        entry = MagicMock()
        entry.data = dict(SBER_CREDENTIALS)
        entry.options = {}
        entry.runtime_data = MagicMock()
        entry.runtime_data.bridge = bridge

        result = await async_get_config_entry_diagnostics(hass, entry)

        assert result["bridge"]["entities_missing_required_links"] == {}
        gate_entry = next(e for e in result["entities"] if e["entity_id"] == RELAY)
        assert gate_entry["missing_required_links"] == []


# ---------------------------------------------------------------------------
# Полный стек: WebSocket + настоящая загрузка интеграции
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _enable_custom_integrations(enable_custom_integrations: Any) -> None:
    """Разрешить HA загружать custom-компонент в тестах этого файла."""
    return


@pytest.fixture(autouse=True)
def _no_mqtt_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    """Отключить бесконечный reconnect-цикл MQTT, оставив всё остальное настоящим."""

    async def _noop(self: SberBridge) -> None:
        return

    monkeypatch.setattr(SberBridge, "_mqtt_connection_loop", _noop)


def register_gate_hardware(hass: HomeAssistant) -> str:
    """Создать в HA устройство «реле + геркон» и выставить их состояния.

    Returns:
        ``device_id`` созданного HA-устройства.
    """
    owner = MockConfigEntry(domain="test_gate_travel_devices")
    owner.add_to_hass(hass)
    device_reg = dr.async_get(hass)
    entity_reg = er.async_get(hass)

    device = device_reg.async_get_or_create(
        config_entry_id=owner.entry_id,
        identifiers={("test_gate_travel_devices", "gate")},
        name="Gate opener",
    )
    entity_reg.async_get_or_create(
        "switch",
        "test_gate_travel_devices",
        "gate-relay-uid",
        suggested_object_id="gate",
        config_entry=owner,
        device_id=device.id,
    )
    entity_reg.async_get_or_create(
        "binary_sensor",
        "test_gate_travel_devices",
        "gate-contact-uid",
        suggested_object_id="gate_contact",
        config_entry=owner,
        device_id=device.id,
        original_device_class="garage_door",
    )
    hass.states.async_set(RELAY, "off", {"friendly_name": "Gate"})
    hass.states.async_set(CONTACT, "off", {"device_class": "garage_door"})
    return device.id


def gate_entry_options(*, linked: bool = True) -> dict[str, Any]:
    """Опции config entry, описывающие пару «реле + геркон» как ворота."""
    options: dict[str, Any] = {
        CONF_EXPOSED_ENTITIES: [RELAY],
        CONF_ENTITY_TYPE_OVERRIDES: {RELAY: GATE_CATEGORY},
    }
    if linked:
        options[CONF_ENTITY_LINKS] = {RELAY: {"open_state": CONTACT}}
    return options


async def _setup_gate_entry(hass: HomeAssistant, *, linked: bool) -> MockConfigEntry:
    """Поднять интеграцию с воротами (со связью или без неё)."""
    assert await async_setup_component(hass, "frontend", {})
    register_gate_hardware(hass)

    entry = MockConfigEntry(
        domain=DOMAIN,
        data=dict(SBER_CREDENTIALS),
        options=gate_entry_options(linked=linked),
        version=3,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


@pytest.fixture
async def gate_entry(hass: HomeAssistant) -> AsyncGenerator[MockConfigEntry]:
    """Интеграция с полностью настроенными воротами (реле + геркон)."""
    entry = await _setup_gate_entry(hass, linked=True)
    yield entry
    if entry.state is ConfigEntryState.LOADED:
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


@pytest.fixture
async def unlinked_gate_entry(hass: HomeAssistant) -> AsyncGenerator[MockConfigEntry]:
    """Интеграция с воротами, которым забыли привязать геркон.

    Путь ``set_override``: категорию назначили руками, связь ещё не
    настроили — мастер такое создать не даёт, а этот путь остаётся
    легальным.
    """
    entry = await _setup_gate_entry(hass, linked=False)
    yield entry
    if entry.state is ConfigEntryState.LOADED:
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


def live_gate(entry: MockConfigEntry) -> ImpulseGateEntity:
    """Живая сущность ворот внутри работающего моста."""
    entity = entry.runtime_data.bridge.entities[RELAY]
    assert isinstance(entity, ImpulseGateEntity)
    return entity


def arm_publish_capture(entry: MockConfigEntry) -> SberBridge:
    """Сделать мост «подключённым» с перехватом публикаций.

    Returns:
        Тот же мост — для чтения ``_mqtt_service.publish``.
    """
    bridge = entry.runtime_data.bridge
    bridge._mqtt_client = AsyncMock()
    bridge._mqtt_service.publish = AsyncMock()
    bridge._connected = True
    bridge._ack_audit.cancel()
    return bridge


async def ws_call(client: Any, payload: dict) -> dict:
    """Отправить WS-команду и вернуть сырой ответ."""
    await client.send_json_auto_id(payload)
    return await client.receive_json()


class TestDeviceDetailShowsTheProblem:
    """Карточка устройства в панели обязана показать недостающую связь."""

    async def test_flag_is_in_device_detail_for_a_broken_gate(
        self,
        hass: HomeAssistant,
        hass_ws_client: Any,
        unlinked_gate_entry: MockConfigEntry,
    ) -> None:
        """``device_detail`` называет незаполненную роль ``open_state``.

        Панель — единственное место, где пользователь может связь
        добавить.  Без флага он увидит исправно выглядящие ворота,
        которые всегда «закрыты», и не поймёт, что настройка не
        закончена.
        """
        client = await hass_ws_client(hass)

        response = await ws_call(client, {"type": "sber_mqtt_bridge/device_detail", "entity_id": RELAY})

        assert response["success"], response.get("error")
        assert response["result"]["missing_required_links"] == ["open_state"]

    async def test_flag_is_empty_for_a_healthy_gate(
        self,
        hass: HomeAssistant,
        hass_ws_client: Any,
        gate_entry: MockConfigEntry,
    ) -> None:
        """У настроенных ворот ключ есть и пуст.

        Ключ обязан присутствовать всегда: панель рисует баннер по
        непустому списку и не должна проверять наличие поля.
        """
        client = await hass_ws_client(hass)

        response = await ws_call(client, {"type": "sber_mqtt_bridge/device_detail", "entity_id": RELAY})

        assert response["success"], response.get("error")
        assert response["result"]["missing_required_links"] == []


# ---------------------------------------------------------------------------
# 8. Сохранение опций БЕЗ перезагрузки записи
# ---------------------------------------------------------------------------


class TestGateOptionsSavedWithoutReload:
    """Галочка в панели не должна стоить пользователю MQTT-сессии."""

    async def test_saving_travel_time_does_not_reload_the_entry(
        self,
        hass: HomeAssistant,
        hass_ws_client: Any,
        gate_entry: MockConfigEntry,
    ) -> None:
        """Сохранение опции не перезагружает запись и не пересоздаёт сущность.

        Перезагрузка рвёт MQTT-сессию с облаком: команды, отправленные в
        эти секунды, теряются, а Sber успевает пометить устройства
        офлайн.  Тот же объект сущности после сохранения — доказательство
        того, что мост не пересобирали.
        """
        client = await hass_ws_client(hass)
        entity_before = live_gate(gate_entry)

        with patch.object(
            hass.config_entries,
            "async_reload",
            new_callable=AsyncMock,
        ) as reload_mock:
            response = await ws_call(
                client,
                {
                    "type": "sber_mqtt_bridge/update_gate_options",
                    "entity_id": RELAY,
                    "travel_time": 12.5,
                },
            )
            await hass.async_block_till_done()

        assert response["success"], response.get("error")
        assert response["result"] == {"entity_id": RELAY, "gate_options": {"travel_time": 12.5}}
        reload_mock.assert_not_called()
        assert gate_entry.state is ConfigEntryState.LOADED
        assert live_gate(gate_entry) is entity_before, "сущность пересоздана — значит запись всё-таки перезагрузили"

    async def test_saved_travel_time_reaches_the_live_entity(
        self,
        hass: HomeAssistant,
        hass_ws_client: Any,
        gate_entry: MockConfigEntry,
    ) -> None:
        """Значение доезжает до работающей сущности и меняет её модель.

        Без reload единственный способ применить опцию — протолкнуть её в
        живой объект.  Если этого не произошло, пользователь настроит
        время хода и не увидит никакого эффекта до перезапуска HA.
        """
        client = await hass_ws_client(hass)

        response = await ws_call(
            client,
            {"type": "sber_mqtt_bridge/update_gate_options", "entity_id": RELAY, "travel_time": 12.5},
        )
        await hass.async_block_till_done()

        assert response["success"], response.get("error")
        entity = live_gate(gate_entry)
        assert entity.travel_time == 12.5
        assert gate_entry.options[CONF_GATE_OPTIONS] == {RELAY: {"travel_time": 12.5}}
        declared = declared_open_state_values(entity)
        assert declared is not None, "включённая эмуляция обязана объявить open_state"
        assert set(declared) == TRAVEL_OPEN_STATE_SET

    async def test_saving_republishes_config_and_state(
        self,
        hass: HomeAssistant,
        hass_ws_client: Any,
        gate_entry: MockConfigEntry,
    ) -> None:
        """После сохранения переопубликованы и конфигурация, и состояние ворот.

        Новое ``allowed_values.open_state`` обязано доехать до облака
        ДО первого ``opening``, иначе Sber выбросит первое же
        эмулированное значение (issue #44).  Конфигурация публикуется
        целиком: частичный список устройств заставит облако пересоздать
        всё остальное.
        """
        bridge = arm_publish_capture(gate_entry)
        client = await hass_ws_client(hass)

        response = await ws_call(
            client,
            {"type": "sber_mqtt_bridge/update_gate_options", "entity_id": RELAY, "travel_time": 12.5},
        )
        await hass.async_block_till_done()

        assert response["success"], response.get("error")
        configs = config_payloads(bridge)
        assert configs, "модель устройства обязана уехать в облако до первого 'opening'"
        gate_model = config_device(configs[-1])["model"]
        assert set(gate_model["allowed_values"]["open_state"]["enum_values"]["values"]) == TRAVEL_OPEN_STATE_SET
        assert published_open_states(bridge) == ["close"]

    async def test_invert_contact_is_re_applied_to_the_existing_reading(
        self,
        hass: HomeAssistant,
        hass_ws_client: Any,
        gate_entry: MockConfigEntry,
    ) -> None:
        """Смена полярности перечитывает уже полученное показание геркона.

        Раньше это делал reload.  Без него сущность обязана
        переинтерпретировать последнее значение сама — иначе ворота
        останутся «закрытыми» до следующего физического срабатывания
        геркона, то есть, возможно, часы.
        """
        client = await hass_ws_client(hass)
        hass.states.async_set(CONTACT, "on", {"device_class": "garage_door"})
        await hass.async_block_till_done()
        assert open_state_of(live_gate(gate_entry)) == "open"

        response = await ws_call(
            client,
            {"type": "sber_mqtt_bridge/update_gate_options", "entity_id": RELAY, "invert_contact": True},
        )
        await hass.async_block_till_done()

        assert response["success"], response.get("error")
        assert open_state_of(live_gate(gate_entry)) == "close"

    async def test_call_without_any_option_is_rejected(
        self,
        hass: HomeAssistant,
        hass_ws_client: Any,
        gate_entry: MockConfigEntry,
    ) -> None:
        """Вызов без единой опции отклоняется и ничего не сохраняет.

        Пустой вызов раньше записывал пустой словарь опций и
        перезагружал интеграцию впустую — рвал MQTT-сессию ни за что.
        """
        client = await hass_ws_client(hass)

        response = await ws_call(client, {"type": "sber_mqtt_bridge/update_gate_options", "entity_id": RELAY})
        await hass.async_block_till_done()

        assert response["success"] is False
        assert response["error"]["code"] == "invalid_format"
        assert CONF_GATE_OPTIONS not in gate_entry.options

    @pytest.mark.parametrize(
        "bad",
        [-1, MAX_TRAVEL + 1, "twenty", None, [20]],
        ids=["negative", "over_max", "not_a_number", "none", "list"],
    )
    async def test_schema_rejects_out_of_range_travel_time(
        self,
        hass: HomeAssistant,
        hass_ws_client: Any,
        gate_entry: MockConfigEntry,
        bad: Any,
    ) -> None:
        """Недопустимое ``travel_time`` не попадает ни в опции, ни в сущность.

        Опции переживают перезапуск HA: записанное туда мусорное
        значение осталось бы навсегда, а створка — навсегда «едущей».
        """
        client = await hass_ws_client(hass)

        response = await ws_call(
            client,
            {"type": "sber_mqtt_bridge/update_gate_options", "entity_id": RELAY, "travel_time": bad},
        )
        await hass.async_block_till_done()

        assert response["success"] is False
        assert response["error"]["code"] == "invalid_format"
        assert CONF_GATE_OPTIONS not in gate_entry.options
        assert live_gate(gate_entry).travel_time == 0.0

    async def test_boolean_travel_time_is_rejected(
        self,
        hass: HomeAssistant,
        hass_ws_client: Any,
        gate_entry: MockConfigEntry,
    ) -> None:
        """``travel_time: true`` не имеет права стать «одной секундой хода».

        Сама сущность отвергает ``bool`` явно и с комментарием («``True``
        молча стал бы одной секундой»), но WS-схема приводит значение к
        числу ДО того, как сущность его увидит, — защита обходится.
        Практически: битый клиент или чекбокс в панели, приславший
        ``true``, включит эмуляцию с бессмысленным ходом в 1 с, сменит
        ``model.id`` устройства в облаке и на каждой команде будет писать
        WARNING «движение не подтверждено».
        """
        client = await hass_ws_client(hass)

        response = await ws_call(
            client,
            {"type": "sber_mqtt_bridge/update_gate_options", "entity_id": RELAY, "travel_time": True},
        )
        await hass.async_block_till_done()

        assert response["success"] is False
        assert response["error"]["code"] == "invalid_format"
        assert CONF_GATE_OPTIONS not in gate_entry.options
        assert live_gate(gate_entry).travel_time == 0.0

    async def test_numeric_string_is_stored_as_a_real_number(
        self,
        hass: HomeAssistant,
        hass_ws_client: Any,
        gate_entry: MockConfigEntry,
    ) -> None:
        """Числовая строка от JSON-клиента сохраняется числом, а не строкой.

        ``apply_gate_options`` молча игнорирует нечисловое значение.  Если
        в опции запишется строка ``"20"``, пользователь увидит
        сохранённую настройку, но эмуляция после перезапуска HA не
        включится — и никакой ошибки нигде не будет.
        """
        client = await hass_ws_client(hass)

        response = await ws_call(
            client,
            {"type": "sber_mqtt_bridge/update_gate_options", "entity_id": RELAY, "travel_time": "20"},
        )
        await hass.async_block_till_done()

        assert response["success"], response.get("error")
        assert gate_entry.options[CONF_GATE_OPTIONS] == {RELAY: {"travel_time": 20.0}}
        assert live_gate(gate_entry).travel_time == 20.0

    async def test_unknown_entity_is_reported_as_not_found(
        self,
        hass: HomeAssistant,
        hass_ws_client: Any,
        gate_entry: MockConfigEntry,
    ) -> None:
        """Опции для незагруженной сущности отвергаются с ``not_found``.

        Иначе панель молча запишет опции «в никуда»: пользователь будет
        уверен, что настроил ворота, которых в мосте нет.
        """
        client = await hass_ws_client(hass)

        response = await ws_call(
            client,
            {"type": "sber_mqtt_bridge/update_gate_options", "entity_id": "switch.nope", "travel_time": 10},
        )

        assert response["success"] is False
        assert response["error"]["code"] == "not_found"
        assert CONF_GATE_OPTIONS not in gate_entry.options

    async def test_options_for_a_non_impulse_gate_are_refused(
        self,
        hass: HomeAssistant,
        hass_ws_client: Any,
        gate_entry: MockConfigEntry,
    ) -> None:
        """Опции импульсных ворот нельзя записать обычным воротам-``cover``.

        Категория ``gate`` обслуживает два разных устройства: пару «реле +
        геркон» и настоящий HA ``cover`` с позицией
        (:func:`make_gate_entity` их и разводит).  У ``cover``-ворот нет
        ни импульса, ни эмуляции хода — они и метода
        ``apply_gate_options`` не знают.  Молчаливое сохранение показало
        бы пользователю настройку, которая ничего не делает, а падение
        обработчика на ``AttributeError`` вернуло бы в панель
        ``unknown_error`` без единого намёка на причину.
        """
        bridge = gate_entry.runtime_data.bridge
        cover_gate = make_gate_entity({"entity_id": "cover.gate", "name": "Cover gate"})
        assert not isinstance(cover_gate, ImpulseGateEntity), "cover-ворота обязаны быть другим классом"
        bridge._entities["cover.gate"] = cover_gate
        client = await hass_ws_client(hass)

        response = await ws_call(
            client,
            {"type": "sber_mqtt_bridge/update_gate_options", "entity_id": "cover.gate", "travel_time": 12.5},
        )
        await hass.async_block_till_done()

        assert response["success"] is False
        assert response["error"]["code"] == "not_a_gate"
        assert CONF_GATE_OPTIONS not in gate_entry.options

    async def test_failed_republish_is_reported_instead_of_a_silent_success(
        self,
        hass: HomeAssistant,
        hass_ws_client: Any,
        gate_entry: MockConfigEntry,
    ) -> None:
        """Сорвавшаяся перепубликация конфигурации возвращается ошибкой в панель.

        Это худший из возможных «успехов»: опция уже применена к живой
        сущности, а облако о новом ``allowed_values.open_state`` не
        узнало — первое же ``opening`` будет молча выброшено (issue #44),
        и створка в приложении застрянет.  Пользователь обязан увидеть
        ошибку и нажать «сохранить» ещё раз, а не радоваться зелёной
        галочке.
        """
        arm_publish_capture(gate_entry)
        client = await hass_ws_client(hass)

        with patch.object(
            SberBridge,
            "_publish_config",
            new_callable=AsyncMock,
            side_effect=HomeAssistantError("broker is down"),
        ) as publish_mock:
            response = await ws_call(
                client,
                {"type": "sber_mqtt_bridge/update_gate_options", "entity_id": RELAY, "travel_time": 12.5},
            )
            await hass.async_block_till_done()

        assert response["success"] is False
        assert response["error"]["code"] == "publish_failed"
        publish_mock.assert_awaited()

    async def test_missing_contact_state_does_not_block_saving(
        self,
        hass: HomeAssistant,
        hass_ws_client: Any,
        gate_entry: MockConfigEntry,
    ) -> None:
        """Исчезнувший из HA геркон не мешает сохранить опции ворот.

        Связь живёт в опциях записи и переживает удаление сущности
        (переименование, отключённая интеграция, севшая батарейка при
        ``restore_state`` off).  Если перечитывание состояний на этом
        споткнётся, пользователь не сможет сохранить даже те опции,
        которыми чинил бы ситуацию.
        """
        hass.states.async_remove(CONTACT)
        await hass.async_block_till_done()
        client = await hass_ws_client(hass)

        response = await ws_call(
            client,
            {"type": "sber_mqtt_bridge/update_gate_options", "entity_id": RELAY, "travel_time": 12.5},
        )
        await hass.async_block_till_done()

        assert response["success"], response.get("error")
        assert live_gate(gate_entry).travel_time == 12.5

    async def test_broken_refresh_is_logged_and_does_not_break_the_save(
        self,
        hass: HomeAssistant,
        hass_ws_client: Any,
        gate_entry: MockConfigEntry,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Сбой перечитывания одной связи не роняет команду сохранения.

        Перечитывание — вспомогательный шаг (нужен ради
        ``invert_contact``), а не смысл операции.  Кривое показание
        связанного датчика не имеет права утащить за собой сохранение
        опций: иначе одна битая связь запирает настройку ворот наглухо.
        При этом факт обязан попасть в лог — молчаливое проглатывание
        исключения превратило бы сопровождение в гадание.
        """
        entity = live_gate(gate_entry)
        entity.update_linked_data = MagicMock(side_effect=ValueError("broken contact payload"))
        client = await hass_ws_client(hass)

        with caplog.at_level(logging.WARNING, logger="custom_components.sber_mqtt_bridge.sber_bridge"):
            response = await ws_call(
                client,
                {"type": "sber_mqtt_bridge/update_gate_options", "entity_id": RELAY, "travel_time": 12.5},
            )
            await hass.async_block_till_done()

        assert response["success"], response.get("error")
        assert entity.travel_time == 12.5
        assert entity.update_linked_data.call_count == 1, "перечитывание связи обязано было произойти"
        assert [r for r in caplog.records if "Failed to refresh" in r.getMessage()], (
            "сбой перечитывания обязан быть виден в логе"
        )

    async def test_device_detail_reports_the_saved_travel_time(
        self,
        hass: HomeAssistant,
        hass_ws_client: Any,
        gate_entry: MockConfigEntry,
    ) -> None:
        """Сохранённое время хода видно в карточке устройства.

        Панель рисует поле по данным ``device_detail``.  Если значение не
        возвращается, пользователь при каждом открытии карточки видит
        пустое поле и, сохранив соседнюю галочку, обнулит время хода.
        """
        client = await hass_ws_client(hass)
        await ws_call(
            client,
            {"type": "sber_mqtt_bridge/update_gate_options", "entity_id": RELAY, "travel_time": 12.5},
        )
        await hass.async_block_till_done()

        response = await ws_call(client, {"type": "sber_mqtt_bridge/device_detail", "entity_id": RELAY})

        assert response["success"], response.get("error")
        assert response["result"]["gate_options"] == {
            "invert_contact": False,
            "impulse_service": "auto",
            "contact_stale": False,
            "travel_time": 12.5,
        }
