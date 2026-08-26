"""Жёсткие тесты таймера автозакрытия импульсных ворот (``auto_close_time``).

Что именно проверяется и почему это важно в проде:

1. **Опция выключена по умолчанию.**  Плата ворот у большинства
   пользователей ничего сама не закрывает, и включать эмуляцию за них
   нельзя.  «Выключено» обязано означать буквально прежнее устройство:
   тот же набор фич, тот же ``allowed_values``, тот же ``model.id`` (это
   дайджест возможностей — при его смене в облаке появляются НОВЫЕ
   ворота, а имя, комната и сценарии у старых теряются) и та же
   последовательность публикуемых состояний.
2. **Объявление ``opening`` / ``closing``.**  Sber молча выбрасывает
   значение состояния, которого не было в ``allowed_values`` (корень
   issue #44).  Значит при включённом ``auto_close_time`` эти значения
   обязаны быть объявлены ДАЖЕ если ``travel_time`` равен нулю — иначе
   фабрикуемое ``closing`` уйдёт в никуда, а створка в приложении
   «залипнет» на ``open``.
3. **Источник отсчёта — геркон, а не команда.**  Плата запускает свой
   таймер, когда створка открылась, кто бы её ни открыл: пульт 433 МГц,
   звонок GSM-модулю, рука на кнопке, приложение Сбера.  Мост не видит
   ни пульта, ни звонка — единственное общее для всех этих случаев
   событие — показание геркона «открыто».  Отсчёт от команды оставил бы
   все ворота, открытые пультом, вечно «открытыми» в приложении.
4. **Геркон всегда истина.**  Новое положение от датчика отменяет и
   отсчёт, и уже фабрикуемое ``closing``; пропажа датчика — тоже (без
   него подтвердить движение нечем).
5. **Страховочный дедлайн.**  Фаза ``closing`` полностью выдумана: её
   обязан ограничивать дедлайн (``travel_time``, а без него — разумный
   предел), после которого публикуется последнее ИЗВЕСТНОЕ положение и
   пишется WARNING.  Иначе одна несработавшая плата навсегда оставит
   ворота «закрывающимися».
6. **Ровно один таймерный механизм.**  Отложенная публикация уже есть
   (``pending_confirm_delay`` → ``SberBridge.schedule_confirm``); второй
   параллельный таймер означал бы гонку двух публикаций и невозможность
   снять их все при выгрузке моста.

Правила файла:

* время двигается ТОЛЬКО через инъектируемые часы сущности (``_now``),
  подменённый ``asyncio.sleep`` моста и ``async_fire_time_changed``;
  ``asyncio.sleep`` в самих тестах запрещён;
* каждый временной тест проверяет И до порога, И после;
* сравниваются точные значения и ПОЛНЫЕ множества (``==``), а не ``in``
  и не ``assert result``;
* ожидания выведены из задания и спеки Sber для категории ``gate``, а не
  сняты с текущего вывода кода.  Единственное исключение —
  :data:`MODEL_ID_WITHOUT_ENTITY_OPTIONS`: он и обязан не меняться.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_service,
)

from custom_components.sber_mqtt_bridge.const import (
    CONF_SBER_BROKER,
    CONF_SBER_LOGIN,
    CONF_SBER_PASSWORD,
    CONF_SBER_PORT,
    CONF_SBER_VERIFY_SSL,
    DOMAIN,
)
from custom_components.sber_mqtt_bridge.devices.gate import ImpulseGateEntity, make_gate_entity
from custom_components.sber_mqtt_bridge.sber_bridge import SberBridge

RELAY = "switch.gate"
"""Импульсное реле — первичная сущность Sber-устройства."""

CONTACT = "binary_sensor.gate_contact"
"""Геркон в роли ``open_state`` — единственный источник правды о створке."""

GATE_LOGGER = "custom_components.sber_mqtt_bridge.devices.gate"
"""Логгер модуля ворот — по нему ловится WARNING о неподтверждённом ходе."""

AUTO_CLOSE = 60.0
"""Задержка автозакрытия в тестах (секунды) — типичная минута на плате."""

TRAVEL = 20.0
"""Время хода створки в тестах (секунды). Реальные ворота едут 15-25 с."""

ASSUMED_CLOSE = 30.0
"""Страховочный дедлайн фазы ``closing``, когда ``travel_time`` не задан.

Значение выведено из задания («разумный предел») и из оценки самого
модуля: створка едет 15-25 с, значит 30 с покрывают медленные ворота с
запасом и при этом ограничивают жизнь выдуманного ``closing``."""

CONFIRM_MARGIN = 0.5
"""Запас к отложенному подтверждению.

Мост спит на своих часах, а сущность меряет дедлайн своими, поэтому
запрошенная пауза обязана быть строго БОЛЬШЕ оставшегося времени —
иначе подтверждение проснётся до дедлайна и опубликует всё то же
``open``, а ``closing`` не выйдет в облако никогда."""

DEFAULT_CONFIRM_DELAY = 1.5
"""Штатная короткая пауза подтверждения (``SETTINGS_DEFAULTS[confirm_delay]``)."""

IMPULSE_COOLDOWN = 2.0
"""Антидребезг импульсов (секунды): второй импульс внутри окна гасится."""

MAX_AUTO_CLOSE = 3600.0
"""Верхняя граница ``auto_close_time``: час.

Больше часа — это уже не «плата закрывает ворота через N секунд», а
опечатка (или UI, приславший миллисекунды)."""

MODEL_ID_WITHOUT_ENTITY_OPTIONS = "Mdl_gate_c085645d"
"""``model.id`` импульсных ворот без единой включённой опции.

Снят с версии ДО появления ``travel_time`` (см. соседний файл
``test_impulse_gate_travel.py``, коммит 06a0245) и обязан совпадать
байт в байт: дайджест считается из набора фич и ``allowed_values``,
так что любое расхождение = новое устройство в облаке у КАЖДОГО, кто
уже подключил ворота."""

BASE_FEATURES = ["online", "open_set", "open_state"]
"""Полный набор фич импульсных ворот: ``online`` и ``open_state``
обязательны для категории ``gate``, ``open_set`` — способ управления.
``stop`` и ``open_percentage`` у одной кнопки без датчика положения
взяться неоткуда."""

OPEN_SET_ALLOWED = {"type": "ENUM", "enum_values": {"values": ["open", "close"]}}
"""``allowed_values.open_set``: только две команды, ``stop`` не заявлен."""

TRAVEL_OPEN_STATE_ALLOWED = {
    "type": "ENUM",
    "enum_values": {"values": ["open", "close", "opening", "closing"]},
}
"""``allowed_values.open_state`` при включённой любой из эмуляций."""

SBER_CREDENTIALS = {
    CONF_SBER_LOGIN: "test",
    CONF_SBER_PASSWORD: "pass",
    CONF_SBER_BROKER: "broker.test",
    CONF_SBER_PORT: 8883,
    CONF_SBER_VERIFY_SSL: False,
}
"""Учётные данные Sber для всех config entry этого файла."""

DEFERRED_SLOT = f"{RELAY}#deferred"
"""Слот моста для отложенной публикации, заказанной сущностью."""

REAL_SLEEP = asyncio.sleep
"""Настоящий ``asyncio.sleep``, сохранённый до всех подмен.

Подменённая пауза обязана всё-таки УСТУПИТЬ управление циклу: без
``await`` на настоящем ``sleep(0)`` ни ``async_block_till_done``, ни
шина событий HA не успевают отработать, и тест начинает проверять
несуществующий мир, где событие геркона так и не доехало до моста."""


# ---------------------------------------------------------------------------
# Хелперы уровня сущности
# ---------------------------------------------------------------------------


class FakeClock:
    """Подменяемые монотонные часы.

    Логика ворот обязана брать время только через инъектируемый ``_now``:
    прямой вызов ``time.monotonic()`` сделал бы и антидребезг, и дедлайны
    непроверяемыми, то есть незаметно сломанными.
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


class LoopClock:
    """Часы event loop со сдвигом, имитирующим реально прошедшее время.

    Нужны ровно там, где проверяется цепочка отложенных публикаций
    моста: ``_delayed_confirm`` перезаводит себя на следующую фазу
    только если дождался СВОЕГО дедлайна (``hass.loop.time() >= due``) —
    защита от самораскрутки при раннем пробуждении.  Подменённый
    ``asyncio.sleep`` спит мгновенно, поэтому без сдвига часов цикла эта
    ветка недостижима.
    """

    def __init__(self, real: Callable[[], float]) -> None:
        """Запомнить настоящие часы цикла.

        Args:
            real: Оригинальный ``hass.loop.time``.
        """
        self._real = real
        self.offset = 0.0

    def __call__(self) -> float:
        """Вернуть настоящее время цикла плюс накопленный сдвиг."""
        return self._real() + self.offset


def make_gate(
    *,
    auto_close_time: float | None = None,
    travel_time: float | None = None,
    contact: str | None = "off",
    invert: bool = False,
    relay_state: str = "off",
    link: bool = True,
    entity_id: str = RELAY,
) -> tuple[ImpulseGateEntity, FakeClock]:
    """Собрать импульсные ворота с инъектированными часами.

    Args:
        auto_close_time: Значение опции ``auto_close_time``; ``None`` —
            опция не передаётся вовсе (проверка поведения по умолчанию).
        travel_time: Значение опции ``travel_time``; ``None`` — не задано.
        contact: Состояние геркона (``None`` — показаний ещё не было).
        invert: Опция ``invert_contact``.
        relay_state: HA-состояние реле.
        link: Регистрировать ли связь ролью ``open_state``.
        entity_id: entity_id реле.

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
    if auto_close_time is not None:
        options["auto_close_time"] = auto_close_time
    if options:
        entity.apply_entity_options(options)
    entity.fill_by_ha_state({"entity_id": entity_id, "state": relay_state, "attributes": {}})
    if link:
        entity.register_link("open_state", CONTACT)
        if contact is not None:
            feed_contact(entity, contact)
    return entity, clock


def feed_contact(entity: ImpulseGateEntity, state: str) -> None:
    """Скормить сущности одно показание геркона."""
    entity.update_linked_data("open_state", {"entity_id": CONTACT, "state": state, "attributes": {}})


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


def toggle_call() -> dict:
    """Ожидаемый результат ``process_cmd`` — импульс ``switch.toggle``."""
    return {
        "url": {
            "type": "call_service",
            "domain": "switch",
            "service": "toggle",
            "target": {"entity_id": RELAY},
        }
    }


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
    """Собрать «подключённый» мост без сущностей: MQTT замокан, guard снят.

    ``_running`` выставляется вручную: без ``async_start`` мост считает
    себя остановленным, а именно этот флаг разрешает отложенному
    подтверждению перезавестись на следующую фазу.
    """
    bridge = SberBridge(hass, make_real_entry(hass))
    bridge._mqtt_client = AsyncMock()
    bridge._mqtt_service.publish = AsyncMock()
    bridge._connected = True
    bridge._running = True
    bridge._ack_audit.cancel()
    return bridge


async def make_gate_bridge(
    hass: HomeAssistant,
    *,
    auto_close_time: float | None = None,
    travel_time: float | None = None,
    contact_state: str | None = "off",
    invert: bool = False,
) -> tuple[SberBridge, ImpulseGateEntity, FakeClock]:
    """Поднять мост с одной импульсной калиткой на настоящем ``hass``.

    Args:
        hass: Настоящий HA из фикстуры.
        auto_close_time: Значение опции ``auto_close_time``.
        travel_time: Значение опции ``travel_time``.
        contact_state: Начальное состояние геркона.
        invert: Опция ``invert_contact``.

    Returns:
        Тройка (мост, сущность, часы сущности).
    """
    bridge = make_bare_bridge(hass)
    entity, clock = make_gate(
        auto_close_time=auto_close_time,
        travel_time=travel_time,
        contact=contact_state,
        invert=invert,
    )

    hass.states.async_set(RELAY, "off")
    if contact_state is not None:
        hass.states.async_set(CONTACT, contact_state, {"device_class": "garage_door"})
    await hass.async_block_till_done()

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
    }


def call_counts(recorders: dict[str, list]) -> dict[str, int]:
    """Свернуть перехватчики в карту «сервис → число вызовов»."""
    return {name: len(calls) for name, calls in recorders.items() if calls}


def cancel_all_confirms(bridge: SberBridge) -> dict[str, Any]:
    """Снять и вернуть все отложенные задачи моста.

    Тест не имеет права оставить после себя фоновую задачу, спящую
    десятки секунд: она переживёт тест и утащит за собой ``hass``.
    """
    tasks = dict(bridge._confirm_tasks)
    for task in tasks.values():
        task.cancel()
    return tasks


async def send_command(
    bridge: SberBridge,
    payload: bytes,
    hass: HomeAssistant,
    *,
    delays: list[float] | None = None,
) -> None:
    """Прогнать команду Sber через мост и дождаться всех эффектов.

    ``asyncio.sleep`` моста подменяется мгновенным (в тестах не спим), а
    запрошенные паузы при желании записываются в ``delays``.

    Args:
        bridge: Мост.
        payload: MQTT-payload команды.
        hass: HA.
        delays: Список для записи запрошенных пауз.
    """

    async def _sleep(delay: float, *args: Any, **kwargs: Any) -> None:
        if delays is not None:
            delays.append(delay)
        await REAL_SLEEP(0)

    with patch("custom_components.sber_mqtt_bridge.sber_bridge.asyncio.sleep", side_effect=_sleep):
        await bridge._handle_sber_command(payload)
        await hass.async_block_till_done()
        bridge._state_forwarder.flush_pending()
        await hass.async_block_till_done()


async def set_contact(
    bridge: SberBridge,
    hass: HomeAssistant,
    state: str,
    attributes: dict | None = None,
) -> None:
    """Изменить состояние геркона и отпустить дебаунс публикации.

    Дебаунс отпускается адресно (``flush_pending``), а не всеобщим
    ``async_fire_time_changed(fire_all=True)``: последний разбудил бы
    заодно и отложенное подтверждение автозакрытия — то самое, которое
    обязано спать до своего дедлайна.  Тест, который сам будит таймер,
    проверял бы не то.

    Args:
        bridge: Мост (его форвардер и держит дебаунс).
        hass: HA.
        state: Новое состояние геркона.
        attributes: Дополнительные атрибуты геркона.
    """
    hass.states.async_set(CONTACT, state, {"device_class": "garage_door", **(attributes or {})})
    await hass.async_block_till_done()
    bridge._state_forwarder.flush_pending()
    await hass.async_block_till_done()


async def run_deferred_confirm(
    bridge: SberBridge,
    hass: HomeAssistant,
    clock: FakeClock,
    delay: float,
) -> None:
    """Прожить отложенное подтверждение так, будто пауза реально прошла.

    Часы сущности и часы event loop сдвигаются ровно на ту паузу,
    которую мост попросил: только тогда ``_delayed_confirm`` увидит свой
    дедлайн наступившим и имеет право перезавестись на следующую фазу.

    Проживается РОВНО одна фаза: подтверждение следующей (мост заводит
    его немедленно и «жадно») остаётся спящим, иначе один вызов
    прокрутил бы всю цепочку и тест не смог бы сказать, что именно
    опубликовала каждая фаза.

    Args:
        bridge: Мост.
        hass: HA.
        clock: Часы сущности.
        delay: Пауза, на которую заведено подтверждение.
    """
    loop_clock = LoopClock(hass.loop.time)
    consumed: list[bool] = []

    async def _sleep(seconds: float, *args: Any, **kwargs: Any) -> None:
        if seconds and not consumed:
            consumed.append(True)
            loop_clock.offset += seconds
            clock.advance(seconds)
            await REAL_SLEEP(0)
            return
        if seconds:
            # Следующая фаза: пусть спит, её проживёт отдельный вызов.
            await REAL_SLEEP(3600)
            return
        await REAL_SLEEP(0)

    with (
        patch.object(hass.loop, "time", loop_clock),
        patch("custom_components.sber_mqtt_bridge.sber_bridge.asyncio.sleep", side_effect=_sleep),
    ):
        await bridge._delayed_confirm(RELAY, delay=delay, slot=DEFERRED_SLOT)
    await hass.async_block_till_done()


# ---------------------------------------------------------------------------
# 1. auto_close_time выключено по умолчанию — поведение обязано быть прежним
# ---------------------------------------------------------------------------


class TestAutoCloseDisabledByDefault:
    """Выключённый автозакрыватель обязан быть неотличим от версии без него."""

    def test_default_is_zero_and_contact_arms_nothing(self) -> None:
        """Без опции показание «открыто» не заводит ни таймера, ни движения.

        Если тест упадёт, у всех пользователей ворота начнут сами
        «закрываться» в приложении через выдуманное время, хотя плата
        ничего не закрывает: реальные ворота останутся открытыми, а
        приложение покажет закрытые — ровно та ложь, из-за которой
        человек уедет от открытых ворот.
        """
        entity, clock = make_gate(contact="off")

        feed_contact(entity, "on")

        assert entity.auto_close_time == 0.0
        assert entity.travel_direction is None
        assert entity.pending_confirm_delay is None
        assert open_state_of(entity) == "open"
        clock.advance(MAX_AUTO_CLOSE)
        assert entity.travel_direction is None
        assert entity.pending_confirm_delay is None
        assert open_state_of(entity) == "open"

    def test_model_descriptor_is_byte_identical_to_pre_option_version(self) -> None:
        """Фичи, ``allowed_values`` и ``model.id`` совпадают с версией до опции.

        ``model.id`` — дайджест возможностей устройства.  Если он
        поедет, у КАЖДОГО, кто уже подключил ворота, в облаке появится
        новое устройство: имя, комната и сценарии пропадут.
        """
        entity, _clock = make_gate(contact="off")

        assert entity.get_final_features_list() == BASE_FEATURES
        assert entity.create_allowed_values_list() == {"open_set": OPEN_SET_ALLOWED}
        assert entity.to_sber_state()["model"]["id"] == MODEL_ID_WITHOUT_ENTITY_OPTIONS

    def test_full_open_close_cycle_publishes_only_open_and_close(self) -> None:
        """Полный цикл без опций даёт ровно два значения ``open_state``.

        Никаких промежуточных состояний быть не может: они не объявлены,
        Sber их выбросит, и створка в приложении застрянет.
        """
        entity, clock = make_gate(contact="off")
        seen = [open_state_of(entity)]

        feed_contact(entity, "on")
        seen.append(open_state_of(entity))
        clock.advance(AUTO_CLOSE * 10)
        seen.append(open_state_of(entity))
        feed_contact(entity, "off")
        seen.append(open_state_of(entity))

        assert seen == ["close", "open", "open", "close"]
        assert set(states_map(entity)) == {"online", "open_state"}

    @pytest.mark.parametrize(
        "bad",
        [-0.5, -1, MAX_AUTO_CLOSE + 0.1, 100000, "60", True, [], {}, object()],
        ids=["negative_float", "negative_int", "over_max", "far_over_max", "string", "bool", "list", "dict", "object"],
    )
    def test_invalid_auto_close_time_keeps_the_feature_off(self, bad: Any) -> None:
        """Мусорное ``auto_close_time`` не включает автозакрытие.

        Опции переживают перезапуск HA.  Правка конфига руками (или UI,
        приславший миллисекунды) не должна ни пригвоздить створку к
        фальшивому ``closing``, ни — что хуже — объявить в модели
        значения, которых устройство не публикует.
        """
        entity, clock = make_gate(auto_close_time=bad, contact="off")

        assert entity.auto_close_time == 0.0
        feed_contact(entity, "on")
        clock.advance(MAX_AUTO_CLOSE)
        assert entity.travel_direction is None
        assert open_state_of(entity) == "open"
        assert declared_open_state_values(entity) is None
        assert entity.to_sber_state()["model"]["id"] == MODEL_ID_WITHOUT_ENTITY_OPTIONS

    @pytest.mark.parametrize(
        "bad",
        [MAX_AUTO_CLOSE + 1, -1, "sixty", True, []],
        ids=["over_max", "negative", "string", "bool", "list"],
    )
    def test_invalid_value_does_not_erase_a_valid_one(self, bad: Any) -> None:
        """Отклонённое значение не сбрасывает уже настроенное автозакрытие.

        «Игнорировать» обязано означать именно игнорировать, а не молча
        выключать фичу: иначе неудачный импорт конфигурации отключит
        автозакрытие у тех, кто его настроил, и никто не заметит.
        """
        entity, _clock = make_gate(auto_close_time=AUTO_CLOSE, contact="off")

        entity.apply_entity_options({"auto_close_time": bad})

        assert entity.auto_close_time == AUTO_CLOSE

    def test_zero_switches_the_feature_off_and_cancels_the_countdown(self) -> None:
        """``auto_close_time=0`` гасит отсчёт немедленно и убирает объявление.

        Пользователь выключает фичу именно тогда, когда она врёт про его
        ворота.  Если выключение не подействует до следующего события
        геркона — то есть, возможно, никогда, — ворота ещё раз «сами
        закроются» уже после отключения.
        """
        entity, clock = make_gate(auto_close_time=AUTO_CLOSE, contact="off")
        feed_contact(entity, "on")
        assert entity.pending_confirm_delay == pytest.approx(AUTO_CLOSE + CONFIRM_MARGIN)

        entity.apply_entity_options({"auto_close_time": 0})

        assert entity.auto_close_time == 0.0
        assert entity.pending_confirm_delay is None
        clock.advance(AUTO_CLOSE * 2)
        assert entity.travel_direction is None
        assert open_state_of(entity) == "open"
        assert declared_open_state_values(entity) is None

    def test_explicit_none_switches_the_feature_off_like_zero(self) -> None:
        """``auto_close_time=None`` эквивалентен нулю.

        UI, очистивший поле, присылает ``None``; если он не выключает
        фичу, поле «стереть» в панели перестанет работать вовсе.
        """
        entity, clock = make_gate(auto_close_time=AUTO_CLOSE, contact="off")
        feed_contact(entity, "on")

        entity.apply_entity_options({"auto_close_time": None})

        assert entity.auto_close_time == 0.0
        assert entity.pending_confirm_delay is None
        clock.advance(AUTO_CLOSE * 2)
        assert open_state_of(entity) == "open"

    async def test_bridge_arms_no_timer_when_the_option_is_off(self, hass: HomeAssistant) -> None:
        """Мост не заводит отложенных задач на воротах без опций.

        Лишний таймер на КАЖДОЕ событие геркона — это лишняя
        принудительная публикация на каждое движение ворот у всех
        пользователей и трафик в облако на пустом месте.
        """
        bridge, _entity, _clock = await make_gate_bridge(hass, contact_state="off")

        await set_contact(bridge, hass, "on")

        leftovers = cancel_all_confirms(bridge)
        assert leftovers == {}
        assert published_open_states(bridge) == ["open"]


class TestAutoCloseOptionIsStoredExactly:
    """Опция обязана доезжать до сущности без искажений и без сюрпризов."""

    @pytest.mark.parametrize(
        "value",
        [0.5, 1, 60, 90.5, MAX_AUTO_CLOSE],
        ids=["half_second", "one_int", "minute_int", "float", "max_allowed"],
    )
    def test_valid_values_are_stored_as_given(self, value: float) -> None:
        """Допустимые значения (включая границу в час) принимаются как есть.

        Граница проверяется отдельно от мусора: сдвиг на единицу
        («строго меньше» вместо «не больше») тихо отбросил бы ровно то
        значение, которое пользователь ввёл, и он бы решил, что фича
        просто не работает.
        """
        entity, clock = make_gate(auto_close_time=value, contact="off")

        assert entity.auto_close_time == float(value)
        feed_contact(entity, "on")
        assert entity.pending_confirm_delay == pytest.approx(float(value) + CONFIRM_MARGIN)
        clock.advance(float(value))
        assert open_state_of(entity) == "closing"

    def test_option_block_carries_every_field_the_form_submits(self) -> None:
        """Блок опций отдаёт ПОЛНЫЙ набор полей формы, включая автозакрытие.

        Форма в панели отправляет все поля разом.  Поле, которого нет в
        отдаваемом блоке, приедет из формы пустым и затрёт настройку
        пользователя, стоит ему тронуть соседнюю галочку.
        """
        entity, _clock = make_gate(auto_close_time=AUTO_CLOSE, travel_time=TRAVEL, contact="off")

        assert entity.entity_options_state() == {
            "invert_contact": False,
            "impulse_service": "auto",
            "contact_stale": False,
            "travel_time": TRAVEL,
            "auto_close_time": AUTO_CLOSE,
        }

    def test_resaving_the_same_value_does_not_disturb_a_running_countdown(self) -> None:
        """Повторное сохранение того же значения не сбрасывает отсчёт.

        Пользователь меняет в форме соседнее поле — форма присылает и
        ``auto_close_time`` тоже.  Если каждый такой сейв перезапускает
        (или гасит) отсчёт, автозакрытие будет промахиваться мимо
        реального таймера платы на всё время, проведённое в настройках.
        """
        entity, clock = make_gate(auto_close_time=AUTO_CLOSE, contact="off")
        feed_contact(entity, "on")
        clock.advance(AUTO_CLOSE / 2)

        entity.apply_entity_options({"auto_close_time": AUTO_CLOSE, "impulse_service": "turn_on"})

        assert entity.impulse_service_option == "turn_on"
        assert entity.pending_confirm_delay == pytest.approx(AUTO_CLOSE / 2 + CONFIRM_MARGIN)
        clock.advance(AUTO_CLOSE / 2)
        assert open_state_of(entity) == "closing"

    def test_changing_the_value_drops_the_countdown_armed_for_the_old_one(self) -> None:
        """Смена значения снимает отсчёт, заведённый под старую задержку.

        Иначе ворота закроются в приложении по СТАРОЙ настройке — в
        момент, который не соответствует ни прежнему, ни новому
        значению на плате.  Заново отсчёт заведёт следующее открытие.
        """
        entity, clock = make_gate(auto_close_time=AUTO_CLOSE, contact="off")
        feed_contact(entity, "on")

        entity.apply_entity_options({"auto_close_time": AUTO_CLOSE * 2})

        assert entity.auto_close_time == AUTO_CLOSE * 2
        assert entity.pending_confirm_delay is None
        clock.advance(AUTO_CLOSE * 3)
        assert open_state_of(entity) == "open"
        assert entity.travel_direction is None


# ---------------------------------------------------------------------------
# 2. Объявление opening / closing в allowed_values
# ---------------------------------------------------------------------------


class TestAllowedValuesFollowTheOption:
    """Публиковать можно только объявленное — иначе Sber молча выбросит."""

    def test_open_state_is_declared_even_without_travel_time(self) -> None:
        """При ``auto_close_time`` без ``travel_time`` объявлены все четыре значения.

        Это главный урок issue #44: недекларированное значение состояния
        Sber выбрасывает МОЛЧА.  Ворота с одним лишь автозакрытием
        публикуют ``closing`` — значит объявление обязано появиться, даже
        когда время хода не настроено.
        """
        entity, _clock = make_gate(auto_close_time=AUTO_CLOSE, travel_time=0, contact="off")

        assert entity.travel_time == 0.0
        assert entity.create_allowed_values_list() == {
            "open_set": OPEN_SET_ALLOWED,
            "open_state": TRAVEL_OPEN_STATE_ALLOWED,
        }
        assert entity.get_final_features_list() == BASE_FEATURES

    def test_declaration_disappears_together_with_both_options(self) -> None:
        """Выключение обеих опций возвращает модель к прежнему дайджесту.

        Объявление и публикация обязаны появляться и исчезать вместе:
        объявленное, но никогда не публикуемое значение — это чужая
        модель устройства в облаке и другой ``model.id``.
        """
        entity, _clock = make_gate(auto_close_time=AUTO_CLOSE, travel_time=TRAVEL, contact="off")
        assert declared_open_state_values(entity) == ["open", "close", "opening", "closing"]

        entity.apply_entity_options({"auto_close_time": 0, "travel_time": 0})

        assert entity.create_allowed_values_list() == {"open_set": OPEN_SET_ALLOWED}
        assert entity.to_sber_state()["model"]["id"] == MODEL_ID_WITHOUT_ENTITY_OPTIONS

    def test_model_id_changes_when_auto_close_is_enabled(self) -> None:
        """Включение автозакрытия меняет ``model.id`` — и это правильно.

        Набор объявленных значений стал другим, устройство в облаке
        обязано быть переописано.  Совпадение дайджестов означало бы,
        что ``allowed_values`` в облако не поехали.
        """
        off, _c1 = make_gate(contact="off")
        on, _c2 = make_gate(auto_close_time=AUTO_CLOSE, contact="off")

        assert off.to_sber_state()["model"]["id"] == MODEL_ID_WITHOUT_ENTITY_OPTIONS
        assert on.to_sber_state()["model"]["id"] != MODEL_ID_WITHOUT_ENTITY_OPTIONS

    def test_every_value_published_during_the_cycle_is_declared(self) -> None:
        """Все значения полного цикла с автозакрытием входят в объявленные.

        Проверка «от противного» к предыдущим: если код когда-нибудь
        начнёт публиковать, скажем, ``opening`` без объявления, цикл это
        поймает.
        """
        entity, clock = make_gate(auto_close_time=AUTO_CLOSE, contact="off")
        declared = declared_open_state_values(entity)
        assert declared == ["open", "close", "opening", "closing"]

        seen = {open_state_of(entity)}
        feed_contact(entity, "on")
        seen.add(open_state_of(entity))
        clock.advance(AUTO_CLOSE)
        seen.add(open_state_of(entity))
        clock.advance(ASSUMED_CLOSE)
        seen.add(open_state_of(entity))
        feed_contact(entity, "off")
        seen.add(open_state_of(entity))

        assert seen == {"close", "open", "closing"}
        assert seen <= set(declared)


# ---------------------------------------------------------------------------
# 3. Отсчёт стартует от геркона, а не от команды
# ---------------------------------------------------------------------------


class TestCountdownStartsFromTheContact:
    """Плата запускает таймер, когда створка открылась — кто бы её ни открыл."""

    def test_contact_transition_arms_the_countdown(self) -> None:
        """Переход геркона «закрыто → открыто» заводит отсчёт.

        Ворота открыли пультом 433 МГц: команды не было, HA видит только
        геркон.  Если отсчёт не заведётся, автозакрытие не сработает
        именно в самом частом сценарии — открытии не из приложения.
        """
        entity, _clock = make_gate(auto_close_time=AUTO_CLOSE, contact="off")

        feed_contact(entity, "on")

        assert entity.pending_confirm_delay == pytest.approx(AUTO_CLOSE + CONFIRM_MARGIN)
        assert entity.travel_direction is None
        assert open_state_of(entity) == "open"

    def test_first_ever_reading_open_arms_the_countdown(self) -> None:
        """Первое в жизни показание «открыто» тоже заводит отсчёт.

        HA перезапустили, пока ворота были открыты: плата свой таймер
        уже отсчитывает.  Не завести свой — значит показывать открытые
        ворота до следующего движения створки.
        """
        entity, _clock = make_gate(auto_close_time=AUTO_CLOSE, contact=None)

        feed_contact(entity, "on")

        assert entity.pending_confirm_delay == pytest.approx(AUTO_CLOSE + CONFIRM_MARGIN)

    def test_command_alone_does_not_arm_the_countdown(self) -> None:
        """Команда из Сбера сама по себе отсчёт не запускает.

        Импульс — это ещё не открытая створка: реле могло щёлкнуть
        вхолостую, привод — упереться в препятствие.  Отсчёт от команды
        объявил бы ворота закрывающимися, хотя они даже не открылись.
        """
        entity, clock = make_gate(auto_close_time=AUTO_CLOSE, contact="off")

        assert entity.process_cmd(open_set_cmd_dict("open")) == [toggle_call()]

        assert entity.pending_confirm_delay is None
        clock.advance(AUTO_CLOSE * 2)
        assert open_state_of(entity) == "close"
        assert entity.travel_direction is None

    def test_closed_reading_arms_nothing(self) -> None:
        """Показание «закрыто» не заводит отсчёт.

        Закрытые ворота закрывать нечем; отсчёт здесь означал бы
        публикацию ``closing`` на неподвижной створке.
        """
        entity, clock = make_gate(auto_close_time=AUTO_CLOSE, contact="on")

        feed_contact(entity, "off")

        assert entity.pending_confirm_delay is None
        clock.advance(AUTO_CLOSE * 2)
        assert open_state_of(entity) == "close"

    def test_inverted_contact_arms_on_its_open_value(self) -> None:
        """С ``invert_contact`` отсчёт заводит значение ``off``.

        Полярность геркона — отдельная опция; если автозакрытие смотрит
        на сырое значение датчика, у половины пользователей таймер будет
        стартовать ровно в момент ЗАКРЫТИЯ ворот.
        """
        entity, clock = make_gate(auto_close_time=AUTO_CLOSE, invert=True, contact="on")
        assert open_state_of(entity) == "close"

        feed_contact(entity, "off")

        assert open_state_of(entity) == "open"
        assert entity.pending_confirm_delay == pytest.approx(AUTO_CLOSE + CONFIRM_MARGIN)
        clock.advance(AUTO_CLOSE)
        assert open_state_of(entity) == "closing"

    def test_repeated_open_reading_does_not_push_the_deadline_away(self) -> None:
        """Повтор «всё ещё открыто» не продлевает отсчёт.

        Zigbee-геркон рапортует батарейку и ``linkquality``, MQTT с
        ``force_update`` — каждое сообщение.  Если каждый такой повтор
        перезаводит таймер, автозакрытие не сработает НИКОГДА, а таймер
        платы тем временем идёт.
        """
        entity, clock = make_gate(auto_close_time=AUTO_CLOSE, contact="off")
        feed_contact(entity, "on")

        clock.advance(AUTO_CLOSE / 2)
        feed_contact(entity, "on")

        assert entity.pending_confirm_delay == pytest.approx(AUTO_CLOSE / 2 + CONFIRM_MARGIN)
        clock.advance(AUTO_CLOSE / 2)
        assert open_state_of(entity) == "closing"

    def test_pending_delay_counts_down_with_the_clock(self) -> None:
        """Запрашиваемая пауза уменьшается ровно на прошедшее время.

        Мост спит именно столько, сколько попросит сущность.  Если пауза
        не уменьшается, каждая публикация (а их на воротах много)
        отодвигает автозакрытие на полную минуту.
        """
        entity, clock = make_gate(auto_close_time=AUTO_CLOSE, contact="off")
        feed_contact(entity, "on")

        clock.advance(10.0)
        assert entity.pending_confirm_delay == pytest.approx(AUTO_CLOSE - 10.0 + CONFIRM_MARGIN)
        clock.advance(49.0)
        assert entity.pending_confirm_delay == pytest.approx(1.0 + CONFIRM_MARGIN)

    async def test_countdown_survives_an_attribute_only_contact_event(self, hass: HomeAssistant) -> None:
        """Событие геркона без смены состояния не сбрасывает отсчёт.

        Через мост это самый частый случай: батарейка, RSSI, повторная
        публикация того же состояния.  Сброс здесь означал бы, что
        автозакрытие не срабатывает на любом «болтливом» датчике.
        """
        bridge, entity, clock = await make_gate_bridge(hass, auto_close_time=AUTO_CLOSE, contact_state="off")
        await set_contact(bridge, hass, "on")
        clock.advance(AUTO_CLOSE / 2)

        await set_contact(bridge, hass, "on", {"battery": 42})

        assert entity.pending_confirm_delay == pytest.approx(AUTO_CLOSE / 2 + CONFIRM_MARGIN)
        # Положение не изменилось — в облако уходить нечему: болтливый
        # датчик не должен превращаться в поток публикаций.
        assert published_open_states(bridge) == ["open"]
        cancel_all_confirms(bridge)


# ---------------------------------------------------------------------------
# 4. Публикация closing по истечении отсчёта
# ---------------------------------------------------------------------------


class TestClosingIsPublishedWhenTheDelayElapses:
    """По истечении задержки плата начинает закрывать — мост это показывает."""

    def test_state_flips_exactly_at_the_deadline(self) -> None:
        """До порога — ``open``, ровно на пороге — ``closing``.

        Ранний ``closing`` заблокирует кнопку в приложении, пока ворота
        ещё стоят открытыми; поздний — оставит пользователя без
        блокировки в момент, когда створка уже поехала.
        """
        entity, clock = make_gate(auto_close_time=AUTO_CLOSE, contact="off")
        feed_contact(entity, "on")

        clock.advance(AUTO_CLOSE - 0.001)
        assert open_state_of(entity) == "open"
        assert entity.travel_direction is None

        clock.advance(0.001)
        assert open_state_of(entity) == "closing"
        assert entity.travel_direction == "closing"

    def test_closing_payload_is_a_complete_state(self) -> None:
        """В фазе ``closing`` публикуется полный обязательный набор состояний.

        Категория ``gate`` требует и ``online``, и ``open_state``:
        payload без одного из них — известная причина молчаливого отказа
        облака от устройства (issue #44).
        """
        entity, clock = make_gate(auto_close_time=AUTO_CLOSE, contact="off")
        feed_contact(entity, "on")
        clock.advance(AUTO_CLOSE)

        published = states_map(entity)

        assert set(published) == {"online", "open_state"}
        assert published["online"] == {"type": "BOOL", "bool_value": True}
        assert published["open_state"] == {"type": "ENUM", "enum_value": "closing"}

    def test_closing_window_defaults_to_the_assumed_travel(self) -> None:
        """Без ``travel_time`` фаза ``closing`` живёт страховочные 30 с.

        Значение выдумано целиком, поэтому обязано быть ограничено:
        иначе одна несработавшая плата навсегда оставит ворота
        «закрывающимися» и без управления из приложения.
        """
        entity, clock = make_gate(auto_close_time=AUTO_CLOSE, contact="off")
        feed_contact(entity, "on")
        clock.advance(AUTO_CLOSE)

        assert entity.pending_confirm_delay == pytest.approx(ASSUMED_CLOSE + CONFIRM_MARGIN)
        clock.advance(ASSUMED_CLOSE - 0.001)
        assert open_state_of(entity) == "closing"
        clock.advance(0.001)
        assert open_state_of(entity) == "open"

    def test_closing_window_follows_travel_time_when_configured(self) -> None:
        """С ``travel_time`` фаза ``closing`` длится именно время хода.

        Пользователь измерил свою створку; держать выдуманное ``closing``
        дольше — значит блокировать кнопку в приложении после того, как
        ворота уже приехали.
        """
        entity, clock = make_gate(auto_close_time=AUTO_CLOSE, travel_time=TRAVEL, contact="off")
        feed_contact(entity, "on")
        clock.advance(AUTO_CLOSE)

        assert entity.pending_confirm_delay == pytest.approx(TRAVEL + CONFIRM_MARGIN)
        clock.advance(TRAVEL - 0.001)
        assert open_state_of(entity) == "closing"
        clock.advance(0.001)
        assert open_state_of(entity) == "open"

    def test_expiry_falls_back_to_the_last_known_position_with_one_warning(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Неподтверждённое закрытие даёт ровно один WARNING и возврат к ``open``.

        Геркон промолчал — значит створка, скорее всего, никуда не
        уехала (не сработала плата, помеха в проёме).  Публиковать
        ``close`` в этом случае — прямая ложь; а без предупреждения
        пользователь никогда не узнает, что его настройка не совпадает с
        реальностью.
        """
        entity, clock = make_gate(auto_close_time=AUTO_CLOSE, contact="off")
        feed_contact(entity, "on")
        clock.advance(AUTO_CLOSE)
        assert open_state_of(entity) == "closing"

        with caplog.at_level(logging.WARNING, logger=GATE_LOGGER):
            clock.advance(ASSUMED_CLOSE)
            settled = open_state_of(entity)
            open_state_of(entity)

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING and r.name == GATE_LOGGER]
        assert settled == "open"
        assert entity.travel_direction is None
        assert entity.pending_confirm_delay is None
        assert len(warnings) == 1
        message = warnings[0].getMessage()
        assert "closing" in message
        assert "'open'" in message

    def test_contact_confirming_the_close_ends_the_phase_without_a_warning(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Приехавшая створка гасит ``closing`` тихо и сразу.

        Штатный исход автозакрытия.  Если он тоже логируется как
        предупреждение, журнал пользователя будет полон ложной тревоги;
        если ``closing`` не снимается — приложение останется без кнопки
        до конца страховочного окна.
        """
        entity, clock = make_gate(auto_close_time=AUTO_CLOSE, contact="off")
        feed_contact(entity, "on")
        clock.advance(AUTO_CLOSE)
        assert open_state_of(entity) == "closing"

        with caplog.at_level(logging.WARNING, logger=GATE_LOGGER):
            clock.advance(ASSUMED_CLOSE / 2)
            feed_contact(entity, "off")

        assert open_state_of(entity) == "close"
        assert entity.travel_direction is None
        assert entity.pending_confirm_delay is None
        assert [r for r in caplog.records if r.levelno == logging.WARNING and r.name == GATE_LOGGER] == []

    def test_reopening_after_a_full_cycle_arms_a_fresh_countdown(self) -> None:
        """После закрытия следующее открытие снова заводит отсчёт.

        Одноразовый таймер — самый неприятный вид поломки: первый цикл
        работает, а дальше фича тихо мертва.
        """
        entity, clock = make_gate(auto_close_time=AUTO_CLOSE, contact="off")
        feed_contact(entity, "on")
        clock.advance(AUTO_CLOSE)
        feed_contact(entity, "off")
        assert open_state_of(entity) == "close"

        clock.advance(5.0)
        feed_contact(entity, "on")

        assert entity.pending_confirm_delay == pytest.approx(AUTO_CLOSE + CONFIRM_MARGIN)
        clock.advance(AUTO_CLOSE)
        assert open_state_of(entity) == "closing"


# ---------------------------------------------------------------------------
# 5. Геркон всегда истина
# ---------------------------------------------------------------------------


class TestContactAlwaysWins:
    """Датчик отменяет и отсчёт, и уже фабрикуемое закрытие."""

    def test_closed_reading_cancels_the_countdown(self) -> None:
        """Ворота закрыли раньше срока — отсчёт снимается.

        Иначе через минуту после уже состоявшегося закрытия мост
        опубликует ``closing`` на неподвижной створке и заблокирует
        кнопку в приложении на ровном месте.
        """
        entity, clock = make_gate(auto_close_time=AUTO_CLOSE, contact="off")
        feed_contact(entity, "on")

        clock.advance(AUTO_CLOSE / 2)
        feed_contact(entity, "off")

        assert entity.pending_confirm_delay is None
        clock.advance(AUTO_CLOSE * 2)
        assert entity.travel_direction is None
        assert open_state_of(entity) == "close"

    @pytest.mark.parametrize("dropped", ["unknown", "unavailable"])
    def test_contact_dropout_cancels_the_countdown(self, dropped: str) -> None:
        """Пропавший геркон снимает отсчёт и не даёт выдумать закрытие.

        Без датчика подтвердить движение нечем.  Фабриковать ``closing``
        на слепом мосту — это показывать пользователю закрытые ворота,
        которых никто не видел.
        """
        entity, clock = make_gate(auto_close_time=AUTO_CLOSE, contact="off")
        feed_contact(entity, "on")

        clock.advance(AUTO_CLOSE / 2)
        feed_contact(entity, dropped)

        assert entity.contact_stale is True
        assert entity.pending_confirm_delay is None
        clock.advance(AUTO_CLOSE * 2)
        assert entity.travel_direction is None
        assert open_state_of(entity) == "open"

    @pytest.mark.parametrize("dropped", ["unknown", "unavailable"])
    def test_contact_dropout_cancels_a_running_closing_phase(self, dropped: str) -> None:
        """Пропажа датчика во время ``closing`` возвращает известное положение.

        Продолжать «закрывать» вслепую нельзя: подтверждения уже не
        будет никогда, а кнопка в приложении останется заблокированной
        до конца страховочного окна.
        """
        entity, clock = make_gate(auto_close_time=AUTO_CLOSE, contact="off")
        feed_contact(entity, "on")
        clock.advance(AUTO_CLOSE)
        assert open_state_of(entity) == "closing"

        feed_contact(entity, dropped)

        assert entity.travel_direction is None
        assert open_state_of(entity) == "open"
        assert entity.pending_confirm_delay is None

    def test_contact_reporting_closed_beats_a_running_closing_phase(self) -> None:
        """Во время ``closing`` показание «закрыто» сразу даёт ``close``."""
        entity, clock = make_gate(auto_close_time=AUTO_CLOSE, travel_time=TRAVEL, contact="off")
        feed_contact(entity, "on")
        clock.advance(AUTO_CLOSE + TRAVEL / 2)
        assert open_state_of(entity) == "closing"

        feed_contact(entity, "off")

        assert open_state_of(entity) == "close"
        assert entity.pending_confirm_delay is None

    async def test_contact_event_publishes_the_real_position_through_the_bridge(
        self,
        hass: HomeAssistant,
    ) -> None:
        """Через мост приезд створки публикуется как ``close``, а не ``closing``.

        Сквозная проверка: даже если сущность внутри всё сделала верно,
        Sber увидит только то, что реально опубликовано.
        """
        bridge, _entity, clock = await make_gate_bridge(hass, auto_close_time=AUTO_CLOSE, contact_state="off")

        await set_contact(bridge, hass, "on")
        clock.advance(AUTO_CLOSE)
        await set_contact(bridge, hass, "off")

        assert published_open_states(bridge) == ["open", "close"]
        cancel_all_confirms(bridge)


# ---------------------------------------------------------------------------
# 6. Команда из Сбера отменяет автозакрытие
# ---------------------------------------------------------------------------


class TestSberCommandCancelsTheCountdown:
    """Пользователь вмешался — гадание про плату прекращается."""

    def test_command_on_an_already_open_gate_cancels_without_an_impulse(self) -> None:
        """``open_set=open`` на открытых воротах снимает отсчёт и не шлёт импульс.

        Импульс здесь закрыл бы ворота (одна кнопка!), а неснятый отсчёт
        через минуту показал бы ``closing`` уже после того, как
        пользователь взял управление на себя.
        """
        entity, clock = make_gate(auto_close_time=AUTO_CLOSE, contact="off")
        feed_contact(entity, "on")

        assert entity.process_cmd(open_set_cmd_dict("open")) == [{"update_state": True}]

        assert entity.pending_confirm_delay is None
        clock.advance(AUTO_CLOSE * 2)
        assert entity.travel_direction is None
        assert open_state_of(entity) == "open"

    def test_close_command_cancels_the_countdown_and_pulses(self) -> None:
        """``open_set=close`` шлёт импульс и снимает отсчёт.

        Створку закрывает пользователь, а не плата: второй, «платный»
        ``closing`` через минуту уже ничему не соответствует.
        """
        entity, clock = make_gate(auto_close_time=AUTO_CLOSE, contact="off")
        feed_contact(entity, "on")

        assert entity.process_cmd(open_set_cmd_dict("close")) == [toggle_call()]

        assert entity.pending_confirm_delay is None
        clock.advance(AUTO_CLOSE * 2)
        assert entity.travel_direction is None
        assert open_state_of(entity) == "open"

    def test_close_command_with_travel_time_leaves_only_the_travel_timer(self) -> None:
        """С ``travel_time`` после команды идёт ход створки, а не автозакрытие.

        Ровно один дедлайн: если бы оба таймера жили одновременно,
        приложение получило бы ``closing`` дважды — второй раз уже после
        приезда створки.
        """
        entity, clock = make_gate(auto_close_time=AUTO_CLOSE, travel_time=TRAVEL, contact="off")
        feed_contact(entity, "on")

        entity.process_cmd(open_set_cmd_dict("close"))

        assert entity.travel_direction == "closing"
        assert entity.pending_confirm_delay == pytest.approx(TRAVEL + CONFIRM_MARGIN)
        clock.advance(TRAVEL)
        assert open_state_of(entity) == "open"
        assert entity.pending_confirm_delay is None
        clock.advance(AUTO_CLOSE)
        assert open_state_of(entity) == "open"
        assert entity.travel_direction is None

    def test_ignored_command_value_still_leaves_the_countdown_running(self) -> None:
        """``stop`` (незаявленное значение) не трогает отсчёт.

        ``stop`` не объявлен в ``allowed_values`` и обязан быть
        проигнорирован целиком.  Если он гасит отсчёт, случайная команда
        из сценария Сбера бесшумно отключит автозакрытие.
        """
        entity, clock = make_gate(auto_close_time=AUTO_CLOSE, contact="off")
        feed_contact(entity, "on")

        assert entity.process_cmd(open_set_cmd_dict("stop")) == []

        assert entity.pending_confirm_delay == pytest.approx(AUTO_CLOSE + CONFIRM_MARGIN)
        clock.advance(AUTO_CLOSE)
        assert open_state_of(entity) == "closing"

    async def test_command_through_the_bridge_cancels_the_countdown(self, hass: HomeAssistant) -> None:
        """Сквозная проверка отмены: команда снимает и слот моста.

        Оставшийся слот выстрелит принудительной публикацией через
        минуту после команды — ровно то, чего пользователь не просил.
        """
        delays: list[float] = []
        recorders = service_recorders(hass)
        bridge, entity, clock = await make_gate_bridge(hass, auto_close_time=AUTO_CLOSE, contact_state="off")
        await set_contact(bridge, hass, "on")
        assert set(bridge._confirm_tasks) == {DEFERRED_SLOT}, "предусловие: отсчёт заведён"

        await send_command(bridge, open_set_cmd("close"), hass, delays=delays)

        assert entity.pending_confirm_delay is None
        # Ровно одна пауза — короткое подтверждение команды.  Вторая,
        # длинная, означала бы, что отсчёт автозакрытия пережил команду.
        assert sorted(d for d in delays if d) == [DEFAULT_CONFIRM_DELAY]
        # Отложенные подтверждения команды уже отработали на мгновенной
        # паузе; спрашиваем мост заново — заказа на отложенную публикацию
        # больше быть не должно, только короткое подтверждение команды.
        bridge.schedule_confirm(RELAY)
        leftovers = cancel_all_confirms(bridge)
        assert set(leftovers) == {RELAY}
        assert call_counts(recorders) == {"switch.toggle": 1}
        clock.advance(AUTO_CLOSE * 2)
        assert open_state_of(entity) == "open"

    def test_command_swallowed_by_the_cooldown_still_cancels_the_countdown(self) -> None:
        """Даже погашенная антидребезгом команда снимает отсчёт.

        Антидребезг гасит ИМПУЛЬС, а не намерение пользователя: он уже
        взял управление на себя.  Продолжать после этого гадать про
        таймер платы — значит показать ``closing`` человеку, который
        только что нажал кнопку сам.
        """
        entity, clock = make_gate(auto_close_time=AUTO_CLOSE, contact="off")
        assert entity.process_cmd(open_set_cmd_dict("open")) == [toggle_call()]
        clock.advance(0.5)
        feed_contact(entity, "on")
        assert entity.pending_confirm_delay == pytest.approx(AUTO_CLOSE + CONFIRM_MARGIN)

        clock.advance(0.5)
        assert entity.process_cmd(open_set_cmd_dict("close")) == [{"update_state": True}]

        assert entity.pending_confirm_delay is None
        clock.advance(AUTO_CLOSE * 2)
        assert open_state_of(entity) == "open"
        assert entity.travel_direction is None

    def test_gate_opened_from_sber_still_auto_closes(self) -> None:
        """Ворота, открытые командой из Сбера, тоже автозакрываются.

        Полный жизненный путь: команда → ход ``opening`` → геркон
        подтвердил открытие → отсчёт платы → ``closing``.  Отмена
        отсчёта командой не имеет права пережить приезд створки: иначе
        автозакрытие работает у всех, кроме тех, кто открыл ворота из
        приложения.
        """
        entity, clock = make_gate(auto_close_time=AUTO_CLOSE, travel_time=TRAVEL, contact="off")

        assert entity.process_cmd(open_set_cmd_dict("open")) == [toggle_call()]
        assert open_state_of(entity) == "opening"

        clock.advance(TRAVEL / 2)
        feed_contact(entity, "on")

        assert open_state_of(entity) == "open"
        assert entity.pending_confirm_delay == pytest.approx(AUTO_CLOSE + CONFIRM_MARGIN)
        clock.advance(AUTO_CLOSE)
        assert open_state_of(entity) == "closing"
        clock.advance(TRAVEL)
        assert open_state_of(entity) == "open"


# ---------------------------------------------------------------------------
# 7. Ровно один таймерный механизм
# ---------------------------------------------------------------------------


class TestSingleTimerMechanism:
    """Два конкурирующих таймера = две гонящиеся публикации."""

    def test_only_one_deadline_is_pending_at_any_moment(self) -> None:
        """Сущность всегда называет ровно один следующий момент.

        Последовательность обязана быть: отсчёт → ход → тишина.  Если
        после начала ``closing`` пауза снова станет «минутой», значит
        отсчёт не был снят и выстрелит второй раз.
        """
        entity, clock = make_gate(auto_close_time=AUTO_CLOSE, travel_time=TRAVEL, contact="off")
        feed_contact(entity, "on")
        pending = [entity.pending_confirm_delay]

        clock.advance(AUTO_CLOSE)
        pending.append(entity.pending_confirm_delay)
        clock.advance(TRAVEL)
        pending.append(entity.pending_confirm_delay)

        assert pending == [
            pytest.approx(AUTO_CLOSE + CONFIRM_MARGIN),
            pytest.approx(TRAVEL + CONFIRM_MARGIN),
            None,
        ]

    def test_impulse_during_the_closing_phase_does_not_add_a_second_timer(self) -> None:
        """Встречная команда во время ``closing`` снимает эмуляцию целиком.

        Одна кнопка: импульс во время закрытия либо остановит, либо
        развернёт створку — что именно, мост знать не может.  Любой
        оставшийся таймер продолжил бы врать про положение.
        """
        entity, clock = make_gate(auto_close_time=AUTO_CLOSE, travel_time=TRAVEL, contact="off")
        feed_contact(entity, "on")
        clock.advance(AUTO_CLOSE)
        assert open_state_of(entity) == "closing"

        clock.advance(IMPULSE_COOLDOWN + 0.1)
        assert entity.process_cmd(open_set_cmd_dict("open")) == [toggle_call()]

        assert entity.travel_direction is None
        assert entity.pending_confirm_delay is None
        clock.advance(AUTO_CLOSE + TRAVEL)
        assert open_state_of(entity) == "open"
        assert entity.travel_direction is None

    async def test_bridge_keeps_exactly_one_deferred_slot(self, hass: HomeAssistant) -> None:
        """На каждое событие геркона мост держит ровно один отложенный слот.

        Короткий слот подтверждения команды здесь не нужен — команды не
        было; а второй отложенный слот означал бы две публикации на один
        дедлайн.  Второе событие — «болтливый» датчик с новой батарейкой
        при том же положении: слот обязан быть переставлен, а не
        продублирован.
        """
        bridge, _entity, clock = await make_gate_bridge(hass, auto_close_time=AUTO_CLOSE, contact_state="off")

        await set_contact(bridge, hass, "on")
        first = dict(bridge._confirm_tasks)
        clock.advance(AUTO_CLOSE / 2)
        await set_contact(bridge, hass, "on", {"battery": 87})
        second = dict(bridge._confirm_tasks)

        cancel_all_confirms(bridge)
        assert set(first) == {DEFERRED_SLOT}
        assert set(second) == {DEFERRED_SLOT}
        assert first[DEFERRED_SLOT].cancelling() == 1, "старая задача обязана быть отменена, а не забыта"
        assert second[DEFERRED_SLOT] is not first[DEFERRED_SLOT]

    async def test_deferred_slot_is_a_background_task(self, hass: HomeAssistant) -> None:
        """Долгая пауза автозакрытия живёт фоновой задачей.

        Отслеживаемая задача, спящая минуту, держит каждый
        ``async_block_till_done`` и доживает до финальной стадии
        выключения HA — то есть ломает и тесты, и штатную выгрузку.
        """
        bridge, _entity, _clock = await make_gate_bridge(hass, auto_close_time=AUTO_CLOSE, contact_state="off")

        await set_contact(bridge, hass, "on")

        deferred = bridge._confirm_tasks[DEFERRED_SLOT]
        assert deferred in hass._background_tasks
        assert deferred not in hass._tasks
        cancel_all_confirms(bridge)


# ---------------------------------------------------------------------------
# 8. Сквозной путь: отложенная публикация через мост
# ---------------------------------------------------------------------------


class TestBridgePublishesTheClosingPhase:
    """Эмулированное значение обязано реально уйти в облако — и уйти вовремя."""

    async def test_contact_event_asks_for_the_auto_close_delay(self, hass: HomeAssistant) -> None:
        """Мост заказывает паузу ровно на задержку автозакрытия плюс запас.

        Штатные 1.5 с здесь бесполезны: подтверждение проснётся задолго
        до дедлайна и опубликует всё то же ``open``, а ``closing`` не
        выйдет никогда.
        """
        delays: list[float] = []
        bridge, _entity, _clock = await make_gate_bridge(hass, auto_close_time=AUTO_CLOSE, contact_state="off")

        async def _sleep(delay: float, *args: Any, **kwargs: Any) -> None:
            delays.append(delay)
            await REAL_SLEEP(0 if delay < ASSUMED_CLOSE else 3600)

        with patch("custom_components.sber_mqtt_bridge.sber_bridge.asyncio.sleep", side_effect=_sleep):
            await set_contact(bridge, hass, "on")

        cancel_all_confirms(bridge)
        assert sorted(d for d in delays if d) == [pytest.approx(AUTO_CLOSE + CONFIRM_MARGIN)]

    async def test_deferred_confirm_publishes_closing(self, hass: HomeAssistant) -> None:
        """Отложенное подтверждение публикует ``closing`` по истечении задержки.

        Это единственная публикация, ради которой фича существует.  Без
        неё в приложении Сбера ворота останутся открытыми, а кнопка —
        разблокированной, хотя створка уже едет.
        """
        bridge, _entity, clock = await make_gate_bridge(hass, auto_close_time=AUTO_CLOSE, contact_state="off")
        await set_contact(bridge, hass, "on")
        assert published_open_states(bridge) == ["open"]
        bridge._mqtt_service.publish.reset_mock()
        cancel_all_confirms(bridge)

        await run_deferred_confirm(bridge, hass, clock, AUTO_CLOSE + CONFIRM_MARGIN)

        assert published_open_states(bridge) == ["closing"]
        cancel_all_confirms(bridge)

    async def test_deferred_confirm_rearms_itself_for_the_closing_phase(self, hass: HomeAssistant) -> None:
        """Дожив до своего дедлайна, подтверждение заводит следующее.

        Фаза ``closing`` тоже обязана кончиться публикацией: без
        перезавода последним, что увидит облако, будет ``closing`` — и
        кнопка останется заблокированной навсегда.
        """
        bridge, _entity, clock = await make_gate_bridge(hass, auto_close_time=AUTO_CLOSE, contact_state="off")
        await set_contact(bridge, hass, "on")
        cancel_all_confirms(bridge)

        await run_deferred_confirm(bridge, hass, clock, AUTO_CLOSE + CONFIRM_MARGIN)

        rearmed = dict(bridge._confirm_tasks)
        cancel_all_confirms(bridge)
        assert set(rearmed) == {DEFERRED_SLOT}

    async def test_second_deferred_confirm_publishes_the_last_known_position(
        self,
        hass: HomeAssistant,
    ) -> None:
        """Второе подтверждение возвращает облаку ``open``, если геркон промолчал.

        Полная цепочка «минута → closing → 30 с → правда».  Если
        последняя публикация не случится, ворота в приложении навсегда
        останутся «закрывающимися».
        """
        bridge, _entity, clock = await make_gate_bridge(hass, auto_close_time=AUTO_CLOSE, contact_state="off")
        await set_contact(bridge, hass, "on")
        cancel_all_confirms(bridge)
        await run_deferred_confirm(bridge, hass, clock, AUTO_CLOSE + CONFIRM_MARGIN)
        cancel_all_confirms(bridge)
        bridge._mqtt_service.publish.reset_mock()

        await run_deferred_confirm(bridge, hass, clock, ASSUMED_CLOSE + CONFIRM_MARGIN)

        assert published_open_states(bridge) == ["open"]
        cancel_all_confirms(bridge)

    async def test_no_service_call_is_made_by_the_auto_close(self, hass: HomeAssistant) -> None:
        """Автозакрытие никогда не дёргает реле.

        Закрывает плата — сама.  Импульс от моста в этот момент означал
        бы вторую команду приводу: створка остановится посреди проёма
        или поедет обратно.
        """
        recorders = service_recorders(hass)
        bridge, _entity, clock = await make_gate_bridge(hass, auto_close_time=AUTO_CLOSE, contact_state="off")

        await set_contact(bridge, hass, "on")
        cancel_all_confirms(bridge)
        await run_deferred_confirm(bridge, hass, clock, AUTO_CLOSE + CONFIRM_MARGIN)

        cancel_all_confirms(bridge)
        assert call_counts(recorders) == {}


# ---------------------------------------------------------------------------
# 9. Выгрузка моста снимает таймеры
# ---------------------------------------------------------------------------


class TestShutdownCancelsTheTimers:
    """Задача, пережившая выгрузку, полезет в уже закрытый hass."""

    async def test_async_stop_cancels_the_pending_countdown(self, hass: HomeAssistant) -> None:
        """``async_stop`` отменяет отложенное подтверждение и забывает его.

        Минутный таймер, переживший выгрузку интеграции, проснётся уже
        после закрытия записи и попытается опубликовать состояние в
        мёртвый MQTT — в логе пользователя это выглядит как случайные
        ошибки при перезагрузке HA.
        """
        bridge, _entity, _clock = await make_gate_bridge(hass, auto_close_time=AUTO_CLOSE, contact_state="off")
        await set_contact(bridge, hass, "on")
        armed = bridge._confirm_tasks[DEFERRED_SLOT]

        await bridge.async_stop()
        await hass.async_block_till_done()

        assert bridge._confirm_tasks == {}
        assert armed.cancelled() or armed.cancelling() == 1

    async def test_contact_event_after_stop_arms_nothing(self, hass: HomeAssistant) -> None:
        """После остановки моста событие геркона не заводит новых таймеров.

        Подписки сняты — значит и новый отсчёт взяться неоткуда.  Иначе
        выгрузка не полная: одна задача уходит, другая тут же приходит.
        """
        bridge, _entity, _clock = await make_gate_bridge(hass, auto_close_time=AUTO_CLOSE, contact_state="off")
        await bridge.async_stop()

        await set_contact(bridge, hass, "on")

        leftovers = cancel_all_confirms(bridge)
        assert leftovers == {}


# ---------------------------------------------------------------------------
# 11. Отсчёт, заведённый не событием: смена настроек и загрузка сущностей
# ---------------------------------------------------------------------------


class TestTimerFollowsTheOptionValue:
    """Таймер моста обязан идти за значением опции, а не за моментом её ввода."""

    async def test_switching_the_option_off_releases_the_bridge_timer(self, hass: HomeAssistant) -> None:
        """Выключение автозакрытия снимает уже заведённый таймер моста.

        Отсчёт живёт в двух местах: дедлайн внутри сущности и спящая
        задача моста.  Сущность свой дедлайн сбрасывает, а задача моста
        остаётся спать — при максимальном значении опции это час, после
        которого она проснётся и сделает лишнюю принудительную
        публикацию давно отменённого движения.

        Если сломается: пользователь, передумавший включать фичу,
        получит одну необъяснимую публикацию через час после отказа.
        """
        bridge, entity, _clock = await make_gate_bridge(hass, auto_close_time=MAX_AUTO_CLOSE, contact_state="off")
        await set_contact(bridge, hass, "on")
        assert set(bridge._confirm_tasks) == {DEFERRED_SLOT}, "отсчёт обязан быть заведён"

        await bridge.async_update_entity_options(RELAY, {"auto_close_time": 0.0})

        leftovers = cancel_all_confirms(bridge)
        assert entity.auto_close_time == 0.0
        assert entity.pending_confirm_delay is None
        assert leftovers == {}

    async def test_changing_the_delay_does_not_leave_the_old_timer(self, hass: HomeAssistant) -> None:
        """Смена задержки снимает таймер, заведённый под прежнее значение.

        Сущность при смене значения бросает отсчёт целиком (он был
        заведён под другую задержку).  Мост обязан узнать об этом в тот
        же момент, иначе час старого таймера переживёт минуту нового.
        """
        bridge, entity, _clock = await make_gate_bridge(hass, auto_close_time=MAX_AUTO_CLOSE, contact_state="off")
        await set_contact(bridge, hass, "on")

        await bridge.async_update_entity_options(RELAY, {"auto_close_time": AUTO_CLOSE})

        leftovers = cancel_all_confirms(bridge)
        assert entity.auto_close_time == AUTO_CLOSE
        assert leftovers == {}
