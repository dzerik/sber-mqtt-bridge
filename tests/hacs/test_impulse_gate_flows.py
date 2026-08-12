"""Сквозные потоки композитных ворот (Sber ``gate``, issue #53).

Тесты уровня моста: Sber-команда → сервисный вызов HA → событие геркона →
публикация ``open_state``.  Всё, что проверяется здесь, ломается в проде
одним из двух способов — ворота открываются/закрываются не тогда, когда
надо (физическая опасность), либо облако Sber молча выбрасывает
устройство из-за неверного набора фич.

Правила файла:

* время двигается только через ``async_fire_time_changed`` / подменяемые
  часы сущности (``_now``); ``asyncio.sleep`` в тестах запрещён;
* проверяются точные значения и полные множества (``==``), а не
  ``in`` / ``assert result``;
* ожидания выведены из спеки Sber и дизайна issue #53, а не сняты с
  текущего вывода кода (исключение — слепок ``model.id`` cover-ворот,
  который специально снят с версии ДО изменений);
* набор проверен мутационным прогоном: 36 мутаций реализации, 35 из них
  роняют поимённо названные тесты этого файла.  Единственный выживший —
  удаление явного ``async_reload`` в ``ws_update_gate_options``, и он
  эквивалентен: HA всё равно пересоздаёт entry на ``async_update_entry``.
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
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
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
from custom_components.sber_mqtt_bridge.devices.gate import (
    GateEntity,
    ImpulseGateEntity,
    make_gate_entity,
)
from custom_components.sber_mqtt_bridge.entity_registry import SberEntityLoader
from custom_components.sber_mqtt_bridge.sber_bridge import SberBridge
from custom_components.sber_mqtt_bridge.sber_entity_map import categories_for_domain
from custom_components.sber_mqtt_bridge.schema_validator import validate_publish

RELAY = "switch.gate"
"""Импульсное реле — первичная сущность Sber-устройства."""

CONTACT = "binary_sensor.gate_contact"
"""Геркон — единственный источник правды о положении створки."""

WINDOW_CONTACT = "binary_sensor.gate_window"
"""Оконный геркон на том же устройстве — НЕ кандидат на роль ``open_state``."""

PLAIN_COVER = "cover.plain"
"""``cover`` без device_class — обязан оставаться шторой, а не воротами."""

GATE_CATEGORY = "gate"

EXPECTED_FEATURES = ["online", "open_set", "open_state"]
"""Ровно тот набор фич, который обязана объявлять импульсная калитка.

``open_percentage`` отсутствует намеренно (у импульсного привода нет
позиции), ``battery`` в спеке ``gate`` нет вовсе.
"""

EXPECTED_OPEN_SET_VALUES = ["open", "close"]
"""``stop`` не объявляется: одной кнопкой створку не остановить."""


# ---------------------------------------------------------------------------
# Хелперы
# ---------------------------------------------------------------------------


SBER_CREDENTIALS = {
    CONF_SBER_LOGIN: "test",
    CONF_SBER_PASSWORD: "pass",
    CONF_SBER_BROKER: "broker.test",
    CONF_SBER_PORT: 8883,
    CONF_SBER_VERIFY_SSL: False,
}
"""Учётные данные Sber для всех config entry этого файла."""


def _make_entry(options: dict | None = None) -> MagicMock:
    """Собрать mock ConfigEntry (для чисто синхронных потребителей — загрузчика)."""
    entry = MagicMock()
    entry.data = dict(SBER_CREDENTIALS)
    entry.options = options or {}
    return entry


def _make_real_entry(hass: HomeAssistant, options: dict | None = None) -> MockConfigEntry:
    """Создать настоящий (зарегистрированный в hass) config entry без setup.

    Нужен там, где мост пишет в ``entry.options`` — например при
    публикации config, когда реестр облачных устройств сохраняет список
    уже отданных Sber id.  MagicMock здесь молча ломает запись.
    """
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=dict(SBER_CREDENTIALS),
        options=options or {},
        version=3,
    )
    entry.add_to_hass(hass)
    return entry


def _sber_cmd(entity_id: str, key: str, value: dict) -> bytes:
    """Собрать payload команды Sber на одну фичу одной сущности."""
    return json.dumps({"devices": {entity_id: {"states": [{"key": key, "value": value}]}}}).encode()


def _open_set_cmd(action: str, entity_id: str = RELAY) -> bytes:
    """Команда ``open_set`` с ENUM-значением ``action``."""
    return _sber_cmd(entity_id, "open_set", {"type": "ENUM", "enum_value": action})


def _status_payloads(bridge: SberBridge) -> list[dict]:
    """Все опубликованные payload'ы ``up/status``."""
    out = []
    for call in bridge._mqtt_service.publish.call_args_list:
        args = call.args if call.args else call[0]
        if "up/status" in str(args[0]):
            out.append(json.loads(args[1]))
    return out


def _config_payloads(bridge: SberBridge) -> list[dict]:
    """Все опубликованные payload'ы ``up/config``."""
    out = []
    for call in bridge._mqtt_service.publish.call_args_list:
        args = call.args if call.args else call[0]
        if "up/config" in str(args[0]):
            out.append(json.loads(args[1]))
    return out


def _states_of(payload: dict, entity_id: str = RELAY) -> list[dict]:
    """Список ``states`` устройства из payload'а ``up/status``."""
    devices = payload["devices"]
    assert entity_id in devices, f"{entity_id} отсутствует в публикации: {sorted(devices)}"
    return devices[entity_id]["states"]


def _state_keys(payload: dict, entity_id: str = RELAY) -> set[str]:
    """Полное множество ключей состояния в публикации."""
    return {s["key"] for s in _states_of(payload, entity_id)}


def _enum(payload: dict, key: str, entity_id: str = RELAY) -> str | None:
    """ENUM-значение фичи ``key`` из публикации (``None``, если ключа нет)."""
    for state in _states_of(payload, entity_id):
        if state["key"] == key:
            return state["value"].get("enum_value")
    return None


def _bool(payload: dict, key: str, entity_id: str = RELAY) -> bool | None:
    """BOOL-значение фичи ``key`` из публикации."""
    for state in _states_of(payload, entity_id):
        if state["key"] == key:
            return state["value"].get("bool_value")
    return None


def _open_states(bridge: SberBridge) -> list[str | None]:
    """``open_state`` из каждой публикации ``up/status``, по порядку."""
    return [_enum(p, "open_state") for p in _status_payloads(bridge) if RELAY in p["devices"]]


class _FakeClock:
    """Подменяемые монотонные часы для антидребезга импульсов.

    Сущность обязана брать время только через инъектируемый ``_now``:
    прямой вызов ``time.monotonic()`` внутри логики сделал бы cooldown
    непроверяемым, а значит — незаметно сломанным.
    """

    def __init__(self) -> None:
        """Начать отсчёт с нуля."""
        self.value = 0.0

    def __call__(self) -> float:
        """Вернуть текущее «время»."""
        return self.value

    def advance(self, seconds: float) -> None:
        """Сдвинуть часы вперёд."""
        self.value += seconds


def _make_bare_bridge(hass: HomeAssistant) -> SberBridge:
    """Собрать «подключённый» мост без сущностей: MQTT замокан, guard снят."""
    bridge = SberBridge(hass, _make_real_entry(hass))
    bridge._mqtt_client = AsyncMock()
    bridge._mqtt_service.publish = AsyncMock()
    bridge._connected = True
    bridge._ack_audit.cancel()
    return bridge


async def _make_gate_bridge(
    hass: HomeAssistant,
    *,
    relay_id: str = RELAY,
    relay_state: str = "off",
    contact_state: str | None = "off",
    invert_contact: bool = False,
    linked: bool = True,
) -> tuple[SberBridge, ImpulseGateEntity]:
    """Поднять мост с одной импульсной калиткой на настоящем ``hass``.

    Args:
        hass: Настоящий HA из фикстуры.
        relay_id: entity_id импульсного реле (домен задаёт вид импульса).
        relay_state: Начальное HA-состояние реле.
        contact_state: Начальное состояние геркона; ``None`` — геркон
            вообще не создаётся в HA.
        invert_contact: Значение опции ``invert_contact``.
        linked: Регистрировать ли связь ролью ``open_state``.

    Returns:
        Пара (мост, сущность калитки).
    """
    bridge = _make_bare_bridge(hass)

    entity = make_gate_entity({"entity_id": relay_id, "name": "Gate"})
    assert isinstance(entity, ImpulseGateEntity)
    if invert_contact:
        entity.apply_gate_options({"invert_contact": True})
    entity.fill_by_ha_state({"entity_id": relay_id, "state": relay_state, "attributes": {}})

    hass.states.async_set(relay_id, relay_state)
    if contact_state is not None:
        hass.states.async_set(CONTACT, contact_state, {"device_class": "garage_door"})
    await hass.async_block_till_done()

    if linked and contact_state is not None:
        entity.update_linked_data("open_state", {"entity_id": CONTACT, "state": contact_state, "attributes": {}})
    if linked:
        entity.register_link("open_state", CONTACT)
        bridge._entity_links = {relay_id: {"open_state": CONTACT}}
        bridge._linked_reverse = {CONTACT: (relay_id, "open_state")}

    bridge._entities[relay_id] = entity
    bridge._enabled_entity_ids = [relay_id]
    bridge._subscribe_ha_events()
    return bridge, entity


def _service_recorders(hass: HomeAssistant) -> dict[str, list]:
    """Перехватить все сервисы, которыми теоретически можно дёрнуть реле.

    Возвращается полная карта, чтобы тест мог утверждать «ровно один
    ``switch.toggle`` и НОЛЬ всего остального» — проверка только на
    ``toggle`` пропустила бы мутацию «вместо toggle шлём и turn_on».
    """
    return {
        "switch.toggle": async_mock_service(hass, "switch", "toggle"),
        "switch.turn_on": async_mock_service(hass, "switch", "turn_on"),
        "switch.turn_off": async_mock_service(hass, "switch", "turn_off"),
        "button.press": async_mock_service(hass, "button", "press"),
        "button.toggle": async_mock_service(hass, "button", "toggle"),
        "input_button.press": async_mock_service(hass, "input_button", "press"),
        "input_button.toggle": async_mock_service(hass, "input_button", "toggle"),
        "script.turn_on": async_mock_service(hass, "script", "turn_on"),
        "script.toggle": async_mock_service(hass, "script", "toggle"),
        "cover.open_cover": async_mock_service(hass, "cover", "open_cover"),
        "cover.close_cover": async_mock_service(hass, "cover", "close_cover"),
        "cover.stop_cover": async_mock_service(hass, "cover", "stop_cover"),
        "cover.set_cover_position": async_mock_service(hass, "cover", "set_cover_position"),
    }


def _call_counts(recorders: dict[str, list]) -> dict[str, int]:
    """Свернуть перехватчики в карту «сервис → число вызовов»."""
    return {name: len(calls) for name, calls in recorders.items() if calls}


async def _send(bridge: SberBridge, payload: bytes, hass: HomeAssistant) -> None:
    """Прогнать команду Sber через мост и дождаться всех эффектов.

    ``asyncio.sleep`` внутри отложенного подтверждения подменяется, чтобы
    подтверждение отработало в том же цикле (в тестах не спим).
    """
    with patch(
        "custom_components.sber_mqtt_bridge.sber_bridge.asyncio.sleep",
        new_callable=AsyncMock,
    ):
        await bridge._handle_sber_command(payload)
        await hass.async_block_till_done()
        async_fire_time_changed(hass, fire_all=True)
        await hass.async_block_till_done()


async def _set_contact(hass: HomeAssistant, state: str, *, settle: bool = True) -> None:
    """Изменить состояние геркона и (по умолчанию) отпустить дебаунс."""
    hass.states.async_set(CONTACT, state, {"device_class": "garage_door"})
    await hass.async_block_till_done()
    if settle:
        async_fire_time_changed(hass, fire_all=True)
        await hass.async_block_till_done()


# ---------------------------------------------------------------------------
# 1. Команда → импульс → геркон → публикация
# ---------------------------------------------------------------------------


class TestOpenCommandFlow:
    """Полный цикл «Sber сказал открыть» → реле → геркон → Sber узнал."""

    async def test_open_command_pulses_relay_once_then_contact_reports_open(
        self,
        hass: HomeAssistant,
    ) -> None:
        """Команда ``open_set=open`` даёт РОВНО один ``switch.toggle``, затем геркон публикует ``open``.

        Если тест упадёт: либо на команду «открой» ворота получают не один
        импульс (два импульса = открыть и тут же закрыть, третий сценарий —
        вообще ничего не поедет), либо положение створки после срабатывания
        геркона не доезжает до облака, и в приложении Салют ворота навсегда
        остаются «закрыты».
        """
        recorders = _service_recorders(hass)
        bridge, _ = await _make_gate_bridge(hass, contact_state="off")

        await _send(bridge, _open_set_cmd("open"), hass)

        assert _call_counts(recorders) == {"switch.toggle": 1}
        toggle_call = recorders["switch.toggle"][0]
        assert toggle_call.data["entity_id"] == RELAY

        bridge._mqtt_service.publish.reset_mock()
        await _set_contact(hass, "on")

        payloads = _status_payloads(bridge)
        assert len(payloads) == 1, f"ожидалась ровно одна публикация после события геркона, получено {len(payloads)}"
        assert _enum(payloads[0], "open_state") == "open"
        assert _state_keys(payloads[0]) == {"online", "open_state"}

    async def test_close_command_pulses_relay_once_from_open_position(
        self,
        hass: HomeAssistant,
    ) -> None:
        """Команда ``open_set=close`` на открытых воротах — один импульс.

        Если тест упадёт: команда «закрой» на открытых воротах не доходит
        до реле, ворота остаются открытыми (а пользователь уверен, что
        закрыл их голосом).
        """
        recorders = _service_recorders(hass)
        bridge, _ = await _make_gate_bridge(hass, contact_state="on")

        await _send(bridge, _open_set_cmd("close"), hass)

        assert _call_counts(recorders) == {"switch.toggle": 1}
        assert recorders["switch.toggle"][0].data["entity_id"] == RELAY

    async def test_open_when_already_open_makes_no_service_call(
        self,
        hass: HomeAssistant,
    ) -> None:
        """«Открой» на уже открытых воротах не шлёт НИ ОДНОГО сервисного вызова.

        Ключевой тест безопасности.  Физически кнопка одна, поэтому импульс
        на открытых воротах их закроет — возможно, на стоящую под ними
        машину.  Если тест упадёт, эта защита исчезла.
        """
        recorders = _service_recorders(hass)
        bridge, _ = await _make_gate_bridge(hass, contact_state="on")

        await _send(bridge, _open_set_cmd("open"), hass)

        assert _call_counts(recorders) == {}
        # Ворота обязаны подтвердить облаку своё реальное положение.
        open_states = _open_states(bridge)
        assert open_states, "отказ от импульса всё равно обязан подтвердить состояние облаку"
        assert set(open_states) == {"open"}

    async def test_close_when_already_closed_makes_no_service_call(
        self,
        hass: HomeAssistant,
    ) -> None:
        """«Закрой» на уже закрытых воротах не шлёт сервисных вызовов.

        Зеркальная половина гарда: без неё команда «закрой» на закрытых
        воротах их ОТКРОЕТ, что для гаража равносильно взлому.
        """
        recorders = _service_recorders(hass)
        bridge, _ = await _make_gate_bridge(hass, contact_state="off")

        await _send(bridge, _open_set_cmd("close"), hass)

        assert _call_counts(recorders) == {}
        open_states = _open_states(bridge)
        assert open_states, "отказ от импульса всё равно обязан подтвердить состояние облаку"
        assert set(open_states) == {"close"}

    @pytest.mark.parametrize("contact_state", ["off", "on"], ids=["closed", "opened"])
    @pytest.mark.parametrize("action", ["stop", "opening", "", "OPEN"], ids=["stop", "opening", "empty", "OPEN"])
    async def test_undeclared_enum_values_never_pulse(
        self,
        hass: HomeAssistant,
        contact_state: str,
        action: str,
    ) -> None:
        """Ни одно необъявленное значение ``open_set`` не приводит к импульсу.

        В ``allowed_values`` объявлены только ``open`` и ``close``.  Всё
        остальное («останови ворота», регистр не тот, пустая строка) —
        рассинхрон с облаком.  Импульс в ответ на такую команду
        реверсирует створку в произвольный момент; проверяется в обоих
        положениях, потому что в одном из них ошибку маскирует гард
        «уже в нужном состоянии».
        """
        recorders = _service_recorders(hass)
        bridge, _ = await _make_gate_bridge(hass, contact_state=contact_state)

        await _send(bridge, _open_set_cmd(action), hass)

        assert _call_counts(recorders) == {}

    @pytest.mark.parametrize("contact_state", ["off", "on"], ids=["closed", "opened"])
    async def test_non_enum_open_set_is_ignored(self, hass: HomeAssistant, contact_state: str) -> None:
        """``open_set``, пришедший не как ENUM, не двигает ворота даже с полем ``enum_value``.

        ``open_set`` объявлен ENUM'ом.  Payload с чужим ``type`` — признак
        рассинхрона протокола; выполнять его «на всякий случай» означает
        открывать гараж по мусору в канале.
        """
        recorders = _service_recorders(hass)
        bridge, _ = await _make_gate_bridge(hass, contact_state=contact_state)
        wanted = "open" if contact_state == "off" else "close"

        await _send(
            bridge,
            _sber_cmd(RELAY, "open_set", {"type": "BOOL", "bool_value": True, "enum_value": wanted}),
            hass,
        )

        assert _call_counts(recorders) == {}

    @pytest.mark.parametrize(
        ("relay_id", "expected_service"),
        [
            ("switch.gate", "switch.toggle"),
            ("button.gate", "button.press"),
            ("input_button.gate", "input_button.press"),
            ("script.gate", "script.turn_on"),
        ],
        ids=["switch", "button", "input_button", "script"],
    )
    async def test_impulse_service_is_chosen_by_primary_domain(
        self,
        hass: HomeAssistant,
        relay_id: str,
        expected_service: str,
    ) -> None:
        """Каждому домену первички соответствует ровно один свой сервис импульса.

        У ``button``/``input_button`` нет ``toggle``, у ``script`` нет
        ``press``.  Если карта поедет, у части пользователей команда
        уйдёт в несуществующий сервис: ворота не двинутся, а в логе будет
        только ``ServiceNotFound``, который легко не заметить.
        """
        recorders = _service_recorders(hass)
        bridge, _ = await _make_gate_bridge(hass, relay_id=relay_id, contact_state="off")

        await _send(bridge, _open_set_cmd("open", relay_id), hass)

        assert _call_counts(recorders) == {expected_service: 1}
        assert recorders[expected_service][0].data["entity_id"] == relay_id

    async def test_impulse_service_turn_on_option_switches_service(
        self,
        hass: HomeAssistant,
    ) -> None:
        """Опция ``impulse_service="turn_on"`` меняет ``switch.toggle`` на ``switch.turn_on``.

        Часть железа реагирует только на запись значения, а не на его
        смену.  Если опция перестанет действовать, у таких пользователей
        ворота молча перестанут открываться.
        """
        recorders = _service_recorders(hass)
        bridge, entity = await _make_gate_bridge(hass, contact_state="off")
        entity.apply_gate_options({"impulse_service": "turn_on"})

        await _send(bridge, _open_set_cmd("open"), hass)

        assert _call_counts(recorders) == {"switch.turn_on": 1}


# ---------------------------------------------------------------------------
# 2. Состояние реле не должно влиять на публикуемое положение
# ---------------------------------------------------------------------------


class TestRelayStateNeverLeaksIntoPosition:
    """Реле «залипает» — его HA-состояние нельзя читать как положение."""

    async def test_relay_toggling_never_changes_published_open_state(
        self,
        hass: HomeAssistant,
    ) -> None:
        """Пляска реле ``on/off/on`` не меняет опубликованное ``open_state``.

        Реле — эхо последней записи в DP, а не датчик.  Если тест упадёт,
        облако будет показывать «ворота открыты» каждый раз, когда реле
        просто щёлкнуло, — вплоть до автоматики, закрывающей открытые
        ворота «на всякий случай».
        """
        bridge, _ = await _make_gate_bridge(hass, contact_state="on", relay_state="off")

        published: list[str | None] = []
        for relay_state in ("on", "off", "on"):
            hass.states.async_set(RELAY, relay_state)
            await hass.async_block_till_done()
            async_fire_time_changed(hass, fire_all=True)
            await hass.async_block_till_done()
            bridge._mqtt_service.publish.reset_mock()
            await bridge._publish_states([RELAY], force=True)
            payloads = _status_payloads(bridge)
            assert len(payloads) == 1
            published.append(_enum(payloads[0], "open_state"))

        assert published == ["open", "open", "open"]

    async def test_delayed_confirm_does_not_clobber_open_state(
        self,
        hass: HomeAssistant,
    ) -> None:
        """Отложенное подтверждение публикует положение геркона, а не эхо реле.

        После команды мост через ``confirm_delay`` перечитывает HA-состояние
        первички и публикует его.  Створка ещё не доехала, геркон говорит
        «закрыто», а реле уже показывает ``on``.  Если тест упадёт, Sber
        получит «ворота открыты» сразу после нажатия — то есть карточка
        соврёт, а автоматика «закрыть, если открыто» ударит в створку
        навстречу.
        """
        recorders = _service_recorders(hass)
        bridge, _ = await _make_gate_bridge(hass, contact_state="off", relay_state="off")

        with patch(
            "custom_components.sber_mqtt_bridge.sber_bridge.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            await bridge._handle_sber_command(_open_set_cmd("open"))
            # Реле отзеркалило импульс раньше, чем створка тронулась.
            hass.states.async_set(RELAY, "on")
            await hass.async_block_till_done()
            async_fire_time_changed(hass, fire_all=True)
            await hass.async_block_till_done()

        assert _call_counts(recorders) == {"switch.toggle": 1}
        open_states = _open_states(bridge)
        assert open_states, "после команды обязана быть хотя бы одна публикация состояния"
        assert set(open_states) == {"close"}, f"положение соврало по эху реле: {open_states}"


# ---------------------------------------------------------------------------
# 3. Дребезг геркона и дебаунс публикаций
# ---------------------------------------------------------------------------


class TestContactBounceAndDebounce:
    """Дребезг контакта не должен превращаться в шторм публикаций."""

    async def test_contact_bounce_coalesces_into_single_publish(
        self,
        hass: HomeAssistant,
    ) -> None:
        """Дребезг ``on→off→on`` внутри окна дебаунса — ровно одна публикация с финальным значением.

        Механические герконы дребезжат.  Без склейки каждый скачок уходит
        в облако отдельным сообщением: Sber ограничивает частоту, и мост
        рискует получить троттлинг ровно в тот момент, когда важно
        доставить финальное положение.
        """
        bridge, _ = await _make_gate_bridge(hass, contact_state="off")

        for state in ("on", "off", "on"):
            await _set_contact(hass, state, settle=False)

        assert _status_payloads(bridge) == [], "дебаунс не имеет права публиковать до срабатывания таймера"

        async_fire_time_changed(hass, fire_all=True)
        await hass.async_block_till_done()

        assert _open_states(bridge) == ["open"]

    async def test_settled_contact_changes_publish_one_by_one(
        self,
        hass: HomeAssistant,
    ) -> None:
        """Базовая линия для склейки: с прокруткой таймера публикуется каждое изменение.

        Без этого теста утверждение «ровно одна публикация» выше не
        отличает работающую склейку от полностью проглоченной публикации.
        """
        bridge, _ = await _make_gate_bridge(hass, contact_state="off")

        for state in ("on", "off", "on"):
            await _set_contact(hass, state)

        assert _open_states(bridge) == ["open", "close", "open"]

    async def test_contact_unavailable_holds_last_known_position(
        self,
        hass: HomeAssistant,
    ) -> None:
        """Пропавший геркон не обнуляет положение: держим последнее известное.

        Если тест упадёт, засыпающий/подсевший датчик будет каждый раз
        рапортовать «ворота закрыты», и голосовое «закрой ворота» на
        реально открытых воротах не сработает (сработает гард), а «открой»
        — наоборот, закроет их.
        """
        bridge, _ = await _make_gate_bridge(hass, contact_state="off")
        await _set_contact(hass, "on")
        assert _open_states(bridge) == ["open"]

        for lost in ("unavailable", "unknown"):
            await _set_contact(hass, lost)
            bridge._mqtt_service.publish.reset_mock()
            await bridge._publish_states([RELAY], force=True)
            payloads = _status_payloads(bridge)
            assert len(payloads) == 1
            assert _enum(payloads[0], "open_state") == "open", f"после {lost} потеряно последнее положение"
            assert _bool(payloads[0], "online") is True, f"после {lost} калитка перестала быть управляемой"


# ---------------------------------------------------------------------------
# 4. Антидребезг импульсов (инъектируемые часы)
# ---------------------------------------------------------------------------


class TestImpulseCooldown:
    """Повторная команда внутри окна не превращается во второй импульс."""

    async def test_cooldown_suppresses_second_impulse_and_releases_after_window(
        self,
        hass: HomeAssistant,
    ) -> None:
        """``close`` при t=0 — импульс, при t=1.5 подавлен, при t=2.5 снова импульс.

        Тест проверяет обе стороны окна: только «до» не отличает
        работающий cooldown от намертво заблокированного управления.
        Моменты подобраны так, чтобы отличить фиксированное окно от
        «скользящего» (когда подавленная команда сама сдвигает отсчёт):
        при скользящем окне третья команда тоже была бы подавлена и
        ворота перестали бы слушаться при частых нажатиях.

        Быстрые повторные импульсы — классический способ довести привод
        до реверса створки в момент, когда под ней машина.
        """
        recorders = _service_recorders(hass)
        bridge, entity = await _make_gate_bridge(hass, contact_state="on")
        clock = _FakeClock()
        entity._now = clock
        assert entity.impulse_cooldown == 2.0, "окно антидребезга должно быть 2 с по дизайну"

        await _send(bridge, _open_set_cmd("close"), hass)
        assert _call_counts(recorders) == {"switch.toggle": 1}

        clock.advance(1.5)
        await _send(bridge, _open_set_cmd("close"), hass)
        assert _call_counts(recorders) == {"switch.toggle": 1}, "импульс внутри окна cooldown обязан быть подавлен"

        clock.advance(1.0)
        await _send(bridge, _open_set_cmd("close"), hass)
        assert _call_counts(recorders) == {"switch.toggle": 2}, (
            "окно обязано отсчитываться от последнего реального импульса, а не от подавленной команды"
        )


# ---------------------------------------------------------------------------
# 5. Reconnect-grace
# ---------------------------------------------------------------------------


class TestReconnectGrace:
    """Команда, «зависшая» в облаке до реконнекта, не должна открыть ворота."""

    async def test_command_during_reconnect_grace_is_rejected_then_accepted(
        self,
        hass: HomeAssistant,
    ) -> None:
        """Во время grace-периода импульса нет, состояние переопубликовано; после — импульс проходит.

        После реконнекта облако может доставить команду, отправленную
        человеком минуты назад.  Если тест упадёт, ворота будут
        самопроизвольно открываться при каждом восстановлении связи —
        самый опасный класс дефекта во всей интеграции.
        """
        recorders = _service_recorders(hass)
        bridge, _ = await _make_gate_bridge(hass, contact_state="off")
        bridge._ack_audit.activate_post_connect()

        await _send(bridge, _open_set_cmd("open"), hass)

        assert _call_counts(recorders) == {}
        open_states = _open_states(bridge)
        assert open_states, "во время grace мост обязан переопубликовать реальное положение"
        assert set(open_states) == {"close"}

        bridge._ack_audit.cancel()
        bridge._mqtt_service.publish.reset_mock()

        await _send(bridge, _open_set_cmd("open"), hass)

        assert _call_counts(recorders) == {"switch.toggle": 1}


# ---------------------------------------------------------------------------
# 6. Отсутствие связи
# ---------------------------------------------------------------------------


class TestMissingContactLink:
    """Без геркона врать «открыто» опаснее, чем признаться «закрыто»."""

    async def test_missing_link_publishes_close_and_warns(
        self,
        hass: HomeAssistant,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Без связи публикуется ``close`` + WARNING, но реле остаётся управляемым.

        Если тест упадёт: либо ворота с оторванной связью начнут
        рапортовать «открыто» (и автоматика попытается их «закрыть»,
        реально открыв), либо потеря связи станет молчаливой и
        пользователь никогда не узнает, почему карточка врёт.
        """
        recorders = _service_recorders(hass)
        with caplog.at_level(logging.WARNING, logger="custom_components.sber_mqtt_bridge.devices.gate"):
            bridge, _ = await _make_gate_bridge(hass, contact_state=None, linked=False)
            await bridge._publish_states([RELAY], force=True)

            payloads = _status_payloads(bridge)
            assert len(payloads) == 1
            assert _enum(payloads[0], "open_state") == "close"
            assert _state_keys(payloads[0]) == {"online", "open_state"}
            assert _bool(payloads[0], "online") is True

            warnings = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
        assert any("open_state" in message and RELAY in message for message in warnings), (
            f"отсутствие связи обязано быть отражено предупреждением, получено: {warnings}"
        )

        bridge._mqtt_service.publish.reset_mock()
        await _send(bridge, _open_set_cmd("open"), hass)
        assert _call_counts(recorders) == {"switch.toggle": 1}, "без геркона реле обязано остаться управляемым"

    async def test_never_seen_contact_reports_offline(self, hass: HomeAssistant) -> None:
        """Связь есть, но контакт не рапортовал ни разу → ``online=false``.

        Показывать «онлайн, закрыто» для ворот, положение которых
        неизвестно, — прямая ложь: пользователь решит, что гараж заперт.
        """
        bridge, _ = await _make_gate_bridge(hass, contact_state="unknown")

        await bridge._publish_states([RELAY], force=True)

        payloads = _status_payloads(bridge)
        assert len(payloads) == 1
        assert _bool(payloads[0], "online") is False
        assert _enum(payloads[0], "open_state") == "close"

    async def test_unavailable_relay_reports_offline_but_keeps_position(
        self,
        hass: HomeAssistant,
    ) -> None:
        """Недоступное реле → ``online=false``, но положение геркона сохраняется.

        Если тест упадёт, обесточенные/выпавшие из сети ворота продолжат
        притворяться онлайн: облако будет принимать команды, которые
        физически некуда доставить, а пользователь решит, что гараж
        закрылся.  Вторая половина проверки не даёт «починить» это
        обнулением положения — оно всё ещё известно от геркона.
        """
        bridge, _ = await _make_gate_bridge(hass, contact_state="on", relay_state="on")

        hass.states.async_set(RELAY, "unavailable")
        await hass.async_block_till_done()
        async_fire_time_changed(hass, fire_all=True)
        await hass.async_block_till_done()
        bridge._mqtt_service.publish.reset_mock()
        await bridge._publish_states([RELAY], force=True)

        payloads = _status_payloads(bridge)
        assert len(payloads) == 1
        assert _bool(payloads[0], "online") is False
        assert _enum(payloads[0], "open_state") == "open"


# ---------------------------------------------------------------------------
# 7. Опции gate_options при загрузке сущностей
# ---------------------------------------------------------------------------


def _register_gate_hardware(hass: HomeAssistant) -> str:
    """Создать в HA устройство «реле + геркон» и выставить их состояния.

    Returns:
        ``device_id`` созданного HA-устройства (нужен мастеру).
    """
    owner = MockConfigEntry(domain="test_gate_devices")
    owner.add_to_hass(hass)
    device_reg = dr.async_get(hass)
    entity_reg = er.async_get(hass)

    device = device_reg.async_get_or_create(
        config_entry_id=owner.entry_id,
        identifiers={("test_gate_devices", "gate")},
        name="Gate opener",
    )
    entity_reg.async_get_or_create(
        "switch",
        "test_gate_devices",
        "gate-relay-uid",
        suggested_object_id="gate",
        config_entry=owner,
        device_id=device.id,
    )
    entity_reg.async_get_or_create(
        "binary_sensor",
        "test_gate_devices",
        "gate-contact-uid",
        suggested_object_id="gate_contact",
        config_entry=owner,
        device_id=device.id,
        original_device_class="garage_door",
    )
    entity_reg.async_get_or_create(
        "binary_sensor",
        "test_gate_devices",
        "gate-window-uid",
        suggested_object_id="gate_window",
        config_entry=owner,
        device_id=device.id,
        original_device_class="window",
    )
    entity_reg.async_get_or_create(
        "cover",
        "test_gate_devices",
        "plain-cover-uid",
        suggested_object_id="plain",
        config_entry=owner,
        device_id=device.id,
    )
    hass.states.async_set(RELAY, "off", {"friendly_name": "Gate"})
    hass.states.async_set(CONTACT, "on", {"device_class": "garage_door"})
    hass.states.async_set(WINDOW_CONTACT, "off", {"device_class": "window"})
    hass.states.async_set(PLAIN_COVER, "open", {"current_position": 100})
    return device.id


def _gate_entry_options(gate_options: dict | None = None) -> dict:
    """Опции config entry, описывающие пару «реле + геркон» как ворота."""
    options: dict[str, Any] = {
        CONF_EXPOSED_ENTITIES: [RELAY],
        CONF_ENTITY_TYPE_OVERRIDES: {RELAY: GATE_CATEGORY},
        CONF_ENTITY_LINKS: {RELAY: {"open_state": CONTACT}},
    }
    if gate_options is not None:
        options[CONF_GATE_OPTIONS] = gate_options
    return options


class TestGateOptionsAtLoad:
    """``gate_options`` обязаны примениться ДО первого чтения геркона."""

    @pytest.mark.parametrize(
        ("gate_options", "expected"),
        [
            (None, "open"),
            ({RELAY: {"invert_contact": False}}, "open"),
            ({RELAY: {"invert_contact": True}}, "close"),
        ],
        ids=["default_polarity", "explicit_no_invert", "inverted"],
    )
    async def test_invert_contact_from_entry_options(
        self,
        hass: HomeAssistant,
        gate_options: dict | None,
        expected: str,
    ) -> None:
        """Геркон ``on`` читается как ``open``, а с ``invert_contact`` — как ``close``.

        Полярность применяется в загрузчике до первичной заливки связанного
        состояния.  Если тест упадёт, пользователи самодельных шаблонных
        герконов получат инвертированные ворота: «закрой» будет открывать.
        """
        _register_gate_hardware(hass)
        loader = SberEntityLoader(hass, _make_entry(_gate_entry_options(gate_options)))

        result = loader.load()

        entity = result.entities[RELAY]
        assert isinstance(entity, ImpulseGateEntity)
        assert result.entity_links == {RELAY: {"open_state": CONTACT}}
        assert result.linked_reverse == {CONTACT: (RELAY, "open_state")}
        states = entity.to_sber_current_state()[RELAY]["states"]
        assert {str(s["key"]) for s in states} == {"online", "open_state"}
        actual = next(str(s["value"]["enum_value"]) for s in states if str(s["key"]) == "open_state")
        assert actual == expected


# ---------------------------------------------------------------------------
# 8. Публикация конфигурации
# ---------------------------------------------------------------------------


class TestConfigPublish:
    """Набор фич и allowed_values обязаны быть ровно такими, как в спеке."""

    async def test_config_declares_exact_feature_set(self, hass: HomeAssistant) -> None:
        """В ``up/config`` уходят ровно ``online``/``open_set``/``open_state`` и ENUM без ``stop``.

        Sber молча выбрасывает устройство с необъявленной или лишней фичей.
        Если тест упадёт, ворота просто не появятся в приложении Салют, и
        никакой ошибки пользователь не увидит.
        """
        bridge, _ = await _make_gate_bridge(hass, contact_state="off")

        await bridge._publish_config()

        configs = _config_payloads(bridge)
        assert len(configs) == 1
        device = next((d for d in configs[0]["devices"] if d.get("id") == RELAY), None)
        assert device is not None, f"калитка отсутствует в config: {[d.get('id') for d in configs[0]['devices']]}"

        model = device["model"]
        assert model["category"] == GATE_CATEGORY
        assert model["features"] == EXPECTED_FEATURES
        assert model["allowed_values"] == {
            "open_set": {"type": "ENUM", "enum_values": {"values": EXPECTED_OPEN_SET_VALUES}}
        }

    async def test_publish_is_clean_for_the_sber_schema(self, hass: HomeAssistant) -> None:
        """``validate_publish`` не находит ни одной претензии к публикуемому состоянию.

        Ловит сразу три способа получить молчаливый отказ облака:
        необъявленный ключ, отсутствующую обязательную фичу и ключ, чужой
        для категории ``gate``.
        """
        _, entity = await _make_gate_bridge(hass, contact_state="off")

        issues = validate_publish(
            entity_id=RELAY,
            category=GATE_CATEGORY,
            states=entity.to_sber_current_state()[RELAY]["states"],
            declared_features=entity.get_final_features_list(),
        )

        assert [(issue.type, issue.key) for issue in issues] == []

    async def test_features_do_not_drift_between_positions(self, hass: HomeAssistant) -> None:
        """Набор фич одинаков в любом положении створки и до первого события геркона.

        Плавающий набор фич заставляет мост переопубликовывать модель, а
        облако — пересоздавать устройство: у пользователя теряются имя,
        комната и сценарии.
        """
        _, entity = await _make_gate_bridge(hass, contact_state=None, linked=True)
        snapshots = [list(entity.get_final_features_list())]

        for contact in ("on", "off", "unavailable"):
            entity.update_linked_data("open_state", {"entity_id": CONTACT, "state": contact, "attributes": {}})
            snapshots.append(list(entity.get_final_features_list()))

        assert snapshots == [EXPECTED_FEATURES] * 4


# ---------------------------------------------------------------------------
# 9. Регресс для cover-ворот
# ---------------------------------------------------------------------------


class TestCoverGateRegression:
    """HA-``cover`` обязан ходить прежним путём — байт в байт."""

    async def test_cover_gate_uses_cover_services(self, hass: HomeAssistant) -> None:
        """``cover``-ворота по-прежнему получают ``cover.open_cover`` и ``cover.set_cover_position``.

        Хардкод домена в ``curtain`` заменён на ``get_entity_domain()``.
        Если подмена ошиблась, у всех существующих пользователей штор,
        жалюзи и cover-ворот команды уедут в несуществующий сервис — вся
        категория перестанет управляться.
        """
        recorders = _service_recorders(hass)
        bridge = _make_bare_bridge(hass)

        entity = make_gate_entity(
            {"entity_id": "cover.gate", "name": "Cover gate", "original_device_class": "garage_door"}
        )
        assert isinstance(entity, GateEntity)
        entity.fill_by_ha_state({"entity_id": "cover.gate", "state": "closed", "attributes": {"current_position": 0}})
        bridge._entities["cover.gate"] = entity
        bridge._enabled_entity_ids = ["cover.gate"]
        hass.states.async_set("cover.gate", "closed", {"current_position": 0})
        await hass.async_block_till_done()

        await _send(bridge, _open_set_cmd("open", "cover.gate"), hass)
        assert _call_counts(recorders) == {"cover.open_cover": 1}
        assert recorders["cover.open_cover"][0].data["entity_id"] == "cover.gate"

        await _send(
            bridge,
            _sber_cmd("cover.gate", "open_percentage", {"type": "INTEGER", "integer_value": 40}),
            hass,
        )
        assert _call_counts(recorders) == {"cover.open_cover": 1, "cover.set_cover_position": 1}
        position_call = recorders["cover.set_cover_position"][0]
        assert position_call.data["entity_id"] == "cover.gate"
        assert position_call.data["position"] == 40

    async def test_cover_gate_still_declares_position_features(self, hass: HomeAssistant) -> None:
        """У ``cover``-ворот остаются позиционные фичи — модель в облаке не переезжает.

        ``model.id`` считается из набора фич и allowed_values.  Любое
        изменение здесь = новое устройство в облаке у всех, кто уже
        подключил ворота: пропадут имя, комната и сценарии.
        """
        entity = make_gate_entity(
            {"entity_id": "cover.gate", "name": "Cover gate", "original_device_class": "garage_door"}
        )
        entity.fill_by_ha_state({"entity_id": "cover.gate", "state": "open", "attributes": {"current_position": 100}})

        features = entity.get_final_features_list()
        assert entity.category == GATE_CATEGORY
        assert "open_percentage" in features
        assert set(EXPECTED_FEATURES) <= set(features)
        # Слепок снят с версии ДО изменений issue #53 (проверено прогоном на
        # ``git archive HEAD``): дайджест обязан совпасть байт в байт.
        assert entity.to_sber_state()["model"]["id"] == "Mdl_gate_d687d574"


# ---------------------------------------------------------------------------
# 10. WebSocket update_gate_options на полном стеке
# ---------------------------------------------------------------------------


class _Recorder:
    """Транспорт-заглушка: копит публикации вместо сети."""

    def __init__(self) -> None:
        """Начать с пустого журнала."""
        self.published: list[tuple[str, str | bytes]] = []

    async def publish(self, topic: str, payload: str | bytes) -> None:
        """Записать публикацию."""
        self.published.append((topic, payload))


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


@pytest.fixture
async def gate_entry(hass: HomeAssistant) -> AsyncGenerator[MockConfigEntry]:
    """Поднять интеграцию с настроенной парой «реле + геркон»."""
    assert await async_setup_component(hass, "frontend", {})
    _register_gate_hardware(hass)

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_SBER_LOGIN: "test",
            CONF_SBER_PASSWORD: "pass",
            CONF_SBER_BROKER: "broker.test",
            CONF_SBER_PORT: 8883,
            CONF_SBER_VERIFY_SSL: False,
        },
        options=_gate_entry_options(),
        version=3,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    yield entry

    if entry.state is ConfigEntryState.LOADED:
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


def _gate_device_id(hass: HomeAssistant) -> str:
    """Вернуть ``device_id`` HA-устройства ворот (мастер требует его явно)."""
    entry = er.async_get(hass).async_get(RELAY)
    assert entry is not None
    assert entry.device_id is not None
    return entry.device_id


def _live_open_state(entry: MockConfigEntry) -> str:
    """Прочитать ``open_state``, который мост опубликовал бы прямо сейчас."""
    entity = entry.runtime_data.bridge._entities[RELAY]
    states = entity.to_sber_current_state()[RELAY]["states"]
    return next(str(s["value"]["enum_value"]) for s in states if str(s["key"]) == "open_state")


class TestWebSocketGateOptions:
    """Панель обязана уметь переключать полярность на живом мосте."""

    async def test_update_gate_options_flips_published_open_state(
        self,
        hass: HomeAssistant,
        hass_ws_client: Any,
        gate_entry: MockConfigEntry,
    ) -> None:
        """WS ``update_gate_options`` с ``invert_contact`` разворачивает публикуемое положение.

        Если тест упадёт: переключатель в панели либо не сохраняется в
        опции, либо не доезжает до работающего моста (нет reload), и
        пользователь с инвертированным герконом будет крутить тумблер без
        всякого эффекта.
        """
        client = await hass_ws_client(hass)
        assert _live_open_state(gate_entry) == "open"

        await client.send_json_auto_id(
            {
                "type": "sber_mqtt_bridge/update_gate_options",
                "entity_id": RELAY,
                "invert_contact": True,
            }
        )
        response = await client.receive_json()
        assert response["success"], response.get("error")
        assert response["result"] == {
            "entity_id": RELAY,
            "gate_options": {"invert_contact": True},
        }
        await hass.async_block_till_done()

        assert gate_entry.options[CONF_GATE_OPTIONS] == {RELAY: {"invert_contact": True}}
        assert gate_entry.state is ConfigEntryState.LOADED
        assert _live_open_state(gate_entry) == "close", "мост не перечитал опции — reload не сработал"

    async def test_update_gate_options_is_partial(
        self,
        hass: HomeAssistant,
        hass_ws_client: Any,
        gate_entry: MockConfigEntry,
    ) -> None:
        """Второй вызов меняет только присланный ключ и не сбрасывает первый.

        Панель шлёт по одному тумблеру за раз.  Если тест упадёт,
        переключение вида импульса будет сбрасывать полярность геркона —
        ворота начнут показывать положение наоборот после безобидного
        действия в UI.
        """
        client = await hass_ws_client(hass)

        for payload in ({"invert_contact": True}, {"impulse_service": "turn_on"}):
            await client.send_json_auto_id(
                {"type": "sber_mqtt_bridge/update_gate_options", "entity_id": RELAY, **payload}
            )
            response = await client.receive_json()
            assert response["success"], response.get("error")
            await hass.async_block_till_done()

        assert gate_entry.options[CONF_GATE_OPTIONS] == {RELAY: {"invert_contact": True, "impulse_service": "turn_on"}}
        entity = gate_entry.runtime_data.bridge._entities[RELAY]
        assert isinstance(entity, ImpulseGateEntity)
        assert (entity.invert_contact, entity.impulse_service_option) == (True, "turn_on")

    async def test_update_gate_options_rejects_unknown_impulse_service(
        self,
        hass: HomeAssistant,
        hass_ws_client: Any,
        gate_entry: MockConfigEntry,
    ) -> None:
        """Мусорное значение ``impulse_service`` отвергается схемой и не попадает в опции.

        Опции переживают перезагрузку HA.  Записанное туда невалидное
        значение сломало бы загрузку сущностей навсегда — с точки зрения
        пользователя ворота просто исчезли бы из Sber.
        """
        client = await hass_ws_client(hass)

        await client.send_json_auto_id(
            {
                "type": "sber_mqtt_bridge/update_gate_options",
                "entity_id": RELAY,
                "impulse_service": "explode",
            }
        )
        response = await client.receive_json()

        assert response["success"] is False
        assert response["error"]["code"] == "invalid_format"
        assert CONF_GATE_OPTIONS not in gate_entry.options


# ---------------------------------------------------------------------------
# 11. Мастер: обязательность связи
# ---------------------------------------------------------------------------


class TestWizardRequiredRole:
    """Импульсная калитка без геркона не должна создаваться вовсе."""

    async def test_add_ha_device_without_contact_is_rejected(
        self,
        hass: HomeAssistant,
        hass_ws_client: Any,
        gate_entry: MockConfigEntry,
    ) -> None:
        """Добавление ворот без связи ``open_state`` → ошибка ``missing_required_role``.

        Иначе мастер создаст «ворота», которые всегда рапортуют «закрыто»
        и всегда шлют импульс на любую команду — пользователь получит
        неуправляемое устройство и не поймёт почему.
        """
        client = await hass_ws_client(hass)

        await client.send_json_auto_id(
            {
                "type": "sber_mqtt_bridge/add_ha_device",
                "device_id": _gate_device_id(hass),
                "primary_entity_id": RELAY,
                "category": GATE_CATEGORY,
                "linked_entity_ids": [],
            }
        )
        response = await client.receive_json()

        assert response["success"] is False
        assert response["error"]["code"] == "missing_required_role"
        assert "open_state" in response["error"]["message"]

    async def test_add_ha_device_with_contact_is_accepted(
        self,
        hass: HomeAssistant,
        hass_ws_client: Any,
        gate_entry: MockConfigEntry,
    ) -> None:
        """Пара «реле + геркон» принимается и записывается связью ``open_state``.

        Если тест упадёт, проверка обязательной роли стала слишком
        жадной: пользователь не сможет добавить корректно собранные
        ворота вообще.
        """
        client = await hass_ws_client(hass)

        await client.send_json_auto_id(
            {
                "type": "sber_mqtt_bridge/add_ha_device",
                "device_id": _gate_device_id(hass),
                "primary_entity_id": RELAY,
                "category": GATE_CATEGORY,
                "linked_entity_ids": [CONTACT],
            }
        )
        response = await client.receive_json()
        assert response["success"], response.get("error")
        await hass.async_block_till_done()

        assert gate_entry.options[CONF_ENTITY_LINKS][RELAY] == {"open_state": CONTACT}
        assert gate_entry.options[CONF_ENTITY_TYPE_OVERRIDES][RELAY] == GATE_CATEGORY
        assert RELAY in gate_entry.options[CONF_EXPOSED_ENTITIES]
        assert CONTACT not in gate_entry.options[CONF_EXPOSED_ENTITIES], (
            "геркон не должен уезжать в облако отдельным устройством"
        )

    async def test_window_contact_is_not_accepted_as_gate_position(
        self,
        hass: HomeAssistant,
        hass_ws_client: Any,
        gate_entry: MockConfigEntry,
    ) -> None:
        """Датчик с device_class ``window`` не годится на роль ``open_state``.

        Оконных герконов в типовом доме десятки.  Если ``window`` попадёт
        в роль, мастер начнёт молча подставлять первый попавшийся оконный
        датчик как положение ворот — карточка будет показывать «ворота
        открыты», когда всего лишь открыта форточка, а голосовой «закрой
        ворота» упрётся в гард и ничего не сделает.
        """
        client = await hass_ws_client(hass)

        await client.send_json_auto_id(
            {
                "type": "sber_mqtt_bridge/add_ha_device",
                "device_id": _gate_device_id(hass),
                "primary_entity_id": RELAY,
                "category": GATE_CATEGORY,
                "linked_entity_ids": [WINDOW_CONTACT],
            }
        )
        response = await client.receive_json()

        assert response["success"] is False
        assert response["error"]["code"] == "linked_role_not_accepted"


# ---------------------------------------------------------------------------
# 12. Автодетект не должен перехватывать обычные реле
# ---------------------------------------------------------------------------


class TestAutodetectIsolation:
    """Новая категория не имеет права красть автодетект у ``relay``."""

    async def test_plain_switch_still_loads_as_relay(self, hass: HomeAssistant) -> None:
        """Обычный ``switch`` без device_class грузится как ``relay``, а не как ворота.

        Ранг ``gate`` подобран так, чтобы категория была доступна только
        явным выбором.  Если тест упадёт, у КАЖДОГО пользователя все
        обычные розетки и реле превратятся в ворота: пропадёт ``on_off``,
        появится ``open_set`` — то есть сломается вся интеграция разом.
        """
        _register_gate_hardware(hass)
        loader = SberEntityLoader(hass, _make_entry({CONF_EXPOSED_ENTITIES: [RELAY]}))

        entity = loader.load().entities[RELAY]

        assert entity.category == "relay"
        assert not isinstance(entity, ImpulseGateEntity)

    async def test_plain_cover_still_loads_as_curtain(self, hass: HomeAssistant) -> None:
        """``cover`` без device_class остаётся ``curtain`` — fallback ворот его не трогает.

        Fallback «нет device_class → подходит» у категории ``gate`` обязан
        действовать только на не-cover домены.  Если ограничение исчезнет,
        обычные шторы у существующих пользователей переедут в категорию
        ``gate``: сменится ``model.id``, и в облаке появится новое
        устройство без имени, комнаты и сценариев.
        """
        _register_gate_hardware(hass)
        loader = SberEntityLoader(hass, _make_entry({CONF_EXPOSED_ENTITIES: [PLAIN_COVER]}))

        entity = loader.load().entities[PLAIN_COVER]

        assert entity.category == "curtain"
        assert categories_for_domain("cover", None) == ["curtain"]


# ---------------------------------------------------------------------------
# 13. Связь регистрируется раньше, чем у геркона появляется состояние
# ---------------------------------------------------------------------------


class TestLinkRegisteredBeforeContactHasState:
    """Порядок запуска HA не имеет права «отвязывать» геркон."""

    async def test_link_survives_a_contact_without_state_object(
        self,
        hass: HomeAssistant,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Геркон без объекта состояния — всё ещё связанный геркон.

        Штатная ситуация при старте HA: интеграция геркона (Zigbee, MQTT)
        поднимается позже моста, поэтому ``hass.states.get(contact)``
        возвращает ``None`` — сам загрузчик логирует это как ожидаемое
        (``debug`` до ``hass.is_running``).  Если в этот момент связь не
        зарегистрировать, ворота решат, что геркона нет вовсе: опубликуют
        ``online=true`` с выдуманным ``open_state='close'`` и снимут гард,
        и голосовое «открой ворота» отправит импульс в РЕАЛЬНО открытые
        ворота — то есть закроет их.
        """
        _register_gate_hardware(hass)
        hass.states.async_remove(CONTACT)
        assert hass.states.get(CONTACT) is None

        with caplog.at_level(logging.WARNING, logger="custom_components.sber_mqtt_bridge.devices.gate"):
            result = SberEntityLoader(hass, _make_entry(_gate_entry_options())).load()
            entity = result.entities[RELAY]
            assert isinstance(entity, ImpulseGateEntity)
            states = {str(s["key"]): s["value"] for s in entity.to_sber_current_state()[RELAY]["states"]}

        assert states["online"]["bool_value"] is False, "положение неизвестно — притворяться онлайн нельзя"
        assert states["open_state"]["enum_value"] == "close"
        assert "has no linked contact sensor" not in caplog.text, "связь настроена, предупреждение вводит в заблуждение"

    async def test_late_contact_state_arms_the_guard(self, hass: HomeAssistant) -> None:
        """Пришедшее позже показание включает и онлайн, и защиту от реверса.

        Контроль к предыдущему тесту: связь должна быть именно
        зарегистрирована, а не просто «молча пропущена без вреда».
        """
        _register_gate_hardware(hass)
        hass.states.async_remove(CONTACT)
        entity = SberEntityLoader(hass, _make_entry(_gate_entry_options())).load().entities[RELAY]

        entity.update_linked_data("open_state", {"entity_id": CONTACT, "state": "on", "attributes": {}})

        states = {str(s["key"]): s["value"] for s in entity.to_sber_current_state()[RELAY]["states"]}
        assert states["online"]["bool_value"] is True
        assert states["open_state"]["enum_value"] == "open"
        cmd = {"states": [{"key": "open_set", "value": {"type": "ENUM", "enum_value": "open"}}]}
        assert entity.process_cmd(cmd) == [{"update_state": True}], "гард обязан работать после позднего показания"


# ---------------------------------------------------------------------------
# 14. Жизненный цикл gate_options в опциях записи
# ---------------------------------------------------------------------------


async def _set_gate_option(hass: HomeAssistant, client: Any, **payload: Any) -> None:
    """Выставить ``gate_options`` через WS и дождаться перезагрузки записи."""
    await client.send_json_auto_id({"type": "sber_mqtt_bridge/update_gate_options", "entity_id": RELAY, **payload})
    response = await client.receive_json()
    assert response["success"], response.get("error")
    await hass.async_block_till_done()


async def _ws_ok(hass: HomeAssistant, client: Any, type_: str, **payload: Any) -> dict:
    """Вызвать WS-команду, убедиться в успехе и вернуть результат."""
    await client.send_json_auto_id({"type": f"sber_mqtt_bridge/{type_}", **payload})
    response = await client.receive_json()
    assert response["success"], response.get("error")
    await hass.async_block_till_done()
    return response["result"]


class TestGateOptionsLifecycle:
    """``gate_options`` обязаны жить и умирать вместе с самой сущностью."""

    async def test_remove_entity_drops_its_gate_options(
        self,
        hass: HomeAssistant,
        hass_ws_client: Any,
        gate_entry: MockConfigEntry,
    ) -> None:
        """Удалённые ворота не оставляют за собой полярность геркона.

        Иначе пользователь, удаливший ворота именно из-за неверной
        полярности, добавит их заново мастером и снова получит
        инвертированные показания — без единого следа в UI.
        """
        client = await hass_ws_client(hass)
        await _set_gate_option(hass, client, invert_contact=True)
        assert gate_entry.options[CONF_GATE_OPTIONS] == {RELAY: {"invert_contact": True}}

        await _ws_ok(hass, client, "remove_entities", entity_ids=[RELAY])

        assert gate_entry.options[CONF_GATE_OPTIONS] == {}

    async def test_clear_all_drops_gate_options(
        self,
        hass: HomeAssistant,
        hass_ws_client: Any,
        gate_entry: MockConfigEntry,
    ) -> None:
        """«Очистить всё» обязано очищать и настройки ворот.

        Команда обнуляет exposed / overrides / links; оставшиеся
        ``gate_options`` — это скрытое состояние, которое молча воскреснет
        на следующем добавлении той же сущности.
        """
        client = await hass_ws_client(hass)
        await _set_gate_option(hass, client, invert_contact=True, impulse_service="turn_on")

        await _ws_ok(hass, client, "clear_all")

        assert gate_entry.options[CONF_GATE_OPTIONS] == {}

    async def test_export_import_round_trips_gate_options(
        self,
        hass: HomeAssistant,
        hass_ws_client: Any,
        gate_entry: MockConfigEntry,
    ) -> None:
        """Экспорт/импорт переносит полярность и вид импульса.

        Без этого перенос конфигурации на новый HA молча теряет
        ``invert_contact``: закрытые ворота показываются открытыми,
        «закрой» гасится гардом, а «открой» отправляет импульс в реально
        открытые ворота.
        """
        client = await hass_ws_client(hass)
        await _set_gate_option(hass, client, invert_contact=True, impulse_service="turn_on")
        expected = {RELAY: {"invert_contact": True, "impulse_service": "turn_on"}}

        exported = await _ws_ok(hass, client, "export")
        assert exported["gate_options"] == expected

        await _ws_ok(hass, client, "clear_all")
        assert gate_entry.options[CONF_GATE_OPTIONS] == {}

        await _ws_ok(hass, client, "import", config=exported)

        assert gate_entry.options[CONF_GATE_OPTIONS] == expected

    @pytest.mark.parametrize(
        "bad",
        [
            {RELAY: {"impulse_service": "explode"}},
            {RELAY: {"invert_contact": "yes"}},
            {"not an entity id": {"invert_contact": True}},
        ],
        ids=["unknown_service", "non_bool_invert", "bad_entity_id"],
    )
    async def test_import_rejects_malformed_gate_options(
        self,
        hass: HomeAssistant,
        hass_ws_client: Any,
        gate_entry: MockConfigEntry,
        bad: dict,
    ) -> None:
        """Мусорные ``gate_options`` не должны попадать в опции.

        Опции переживают перезапуск HA, поэтому невалидное значение,
        записанное импортом, ломало бы загрузку сущностей навсегда.
        """
        client = await hass_ws_client(hass)

        await client.send_json_auto_id({"type": "sber_mqtt_bridge/import", "config": {"gate_options": bad}})
        response = await client.receive_json()

        assert response["success"] is False
        assert response["error"]["code"] == "invalid_config"
        assert CONF_GATE_OPTIONS not in gate_entry.options
