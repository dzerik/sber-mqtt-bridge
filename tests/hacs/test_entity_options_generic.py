"""Обобщённый механизм per-entity опций: обратная совместимость и полный стек.

До v1.47 пользовательские настройки уровня сущности существовали только у
импульсных ворот (``gate_options``, issue #53).  Чайнику понадобился ровно
тот же механизм, поэтому он обобщён: класс устройства объявляет
``ENTITY_OPTION_KEYS``, а всё остальное — загрузчик, мост, WebSocket,
export/import — про категории ничего не знает.

Файл проверяет именно эту «проводку», а не логику конкретных устройств:

1. **Обратная совместимость хранилища.**  У пользователей v1.42-v1.46 в
   ``entry.options`` уже лежит ключ ``gate_options``.  Апгрейд обязан
   прочитать его как есть: миграции нет, а значит переименование ключа
   осиротило бы настройки всех, кто уже настроил ворота.
2. **Обратная совместимость WebSocket.**  Панель, закешированная в
   браузере, зовёт ``sber_mqtt_bridge/update_gate_options`` и разбирает
   ответ по ключу ``gate_options``.  Имя команды, форма ответа и коды
   ошибок — публичный контракт v1.42.
3. **Сохранение без перезагрузки записи** для ЛЮБОЙ категории с опциями:
   перезагрузка рвёт MQTT-сессию с облаком, и галочка в панели не должна
   стоить пользователю разрыва моста.
4. **Круговой рейс export → import** с опциями и ворот, и чайника:
   выгруженный конфиг обязан загружаться обратно без правки руками.
5. **``device_detail``** отдаёт текущие значения опций той категории,
   которая их объявила, и НИЧЕГО не отдаёт категории без опций.

Правила файла:

* ожидания выведены из задания и из контракта v1.42, а не сняты с
  текущего вывода кода;
* проверяются точные значения и ПОЛНЫЕ множества (``==``), а не ``in``
  и не ``assert result``;
* тесты идут через настоящую загрузку интеграции и настоящий WebSocket:
  обобщение затрагивает пять модулей сразу, и заглушки в такой связке
  доказывают только то, что заглушки согласованы между собой.
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sber_mqtt_bridge.cloud_device_registry import HUB_DEVICE_ID
from custom_components.sber_mqtt_bridge.const import (
    CONF_ENTITY_LINKS,
    CONF_ENTITY_OPTIONS,
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
from custom_components.sber_mqtt_bridge.devices.base_entity import BaseEntity
from custom_components.sber_mqtt_bridge.devices.gate import ImpulseGateEntity
from custom_components.sber_mqtt_bridge.devices.kettle import KettleEntity
from custom_components.sber_mqtt_bridge.devices.relay import RelayEntity
from custom_components.sber_mqtt_bridge.sber_bridge import SberBridge

# ---------------------------------------------------------------------------
# Константы стенда
# ---------------------------------------------------------------------------

GATE = "switch.gate"
"""Импульсное реле ворот — категория с опциями №1."""

CONTACT = "binary_sensor.gate_contact"
"""Геркон в роли ``open_state``: без него ворота не считаются настроенными."""

KETTLE = "water_heater.kettle"
"""Умный чайник — категория с опциями №2 (режимы работы)."""

LAMP = "switch.lamp"
"""Обычное реле — категория БЕЗ опций, контрольная группа."""

PLATFORM = "test_entity_options_devices"
"""Платформа-владелец тестовых HA-сущностей."""

LEGACY_OPTIONS_KEY = "gate_options"
"""Литеральный ключ хранилища опций, каким он ушёл пользователям в v1.42.

Тесты пишут именно строку, а не константу: смысл проверки — что у
пользователя со старым ``entry.options`` ничего не пропало, а константа
переехала бы вместе с кодом и проверять было бы нечего."""

OFF_MODE = "Выключен"
"""Режим «выключено» тестового чайника."""

BOIL_MODE = "Кипячение"
"""Режим «кипятить» тестового чайника."""

HEAT_MODE = "Подогрев"
"""Режим «греть до уставки» тестового чайника."""

KETTLE_MODES = [OFF_MODE, BOIL_MODE, HEAT_MODE]
"""``operation_list`` тестового чайника.

Имена НЕ английские специально: автоопределение по словарю
(``off`` / ``boil`` / ``heat``) на них обязано промахнуться, поэтому
любое совпадение в тестах ниже доказывает, что сработала именно
пользовательская опция, а не угадайка."""

GATE_OPEN_STATE_FULL = {"open", "close", "opening", "closing"}
"""Полное множество ``open_state`` при включённой эмуляции движения."""

SBER_CREDENTIALS = {
    CONF_SBER_LOGIN: "test",
    CONF_SBER_PASSWORD: "pass",
    CONF_SBER_BROKER: "broker.test",
    CONF_SBER_PORT: 8883,
    CONF_SBER_VERIFY_SSL: False,
}
"""Учётные данные Sber для всех config entry этого файла."""


# ---------------------------------------------------------------------------
# Стенд: настоящая интеграция, настоящий WebSocket
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


def register_hardware(hass: HomeAssistant) -> None:
    """Создать в HA три устройства: ворота (реле + геркон), чайник и лампу."""
    owner = MockConfigEntry(domain=PLATFORM)
    owner.add_to_hass(hass)
    device_reg = dr.async_get(hass)
    entity_reg = er.async_get(hass)

    gate_device = device_reg.async_get_or_create(
        config_entry_id=owner.entry_id,
        identifiers={(PLATFORM, "gate")},
        name="Gate opener",
    )
    entity_reg.async_get_or_create(
        "switch",
        PLATFORM,
        "gate-relay-uid",
        suggested_object_id="gate",
        config_entry=owner,
        device_id=gate_device.id,
    )
    entity_reg.async_get_or_create(
        "binary_sensor",
        PLATFORM,
        "gate-contact-uid",
        suggested_object_id="gate_contact",
        config_entry=owner,
        device_id=gate_device.id,
        original_device_class="garage_door",
    )

    kettle_device = device_reg.async_get_or_create(
        config_entry_id=owner.entry_id,
        identifiers={(PLATFORM, "kettle")},
        name="Smart kettle",
    )
    entity_reg.async_get_or_create(
        "water_heater",
        PLATFORM,
        "kettle-uid",
        suggested_object_id="kettle",
        config_entry=owner,
        device_id=kettle_device.id,
    )

    lamp_device = device_reg.async_get_or_create(
        config_entry_id=owner.entry_id,
        identifiers={(PLATFORM, "lamp")},
        name="Lamp relay",
    )
    entity_reg.async_get_or_create(
        "switch",
        PLATFORM,
        "lamp-uid",
        suggested_object_id="lamp",
        config_entry=owner,
        device_id=lamp_device.id,
    )

    hass.states.async_set(GATE, "off", {"friendly_name": "Gate"})
    hass.states.async_set(CONTACT, "off", {"device_class": "garage_door"})
    hass.states.async_set(
        KETTLE,
        OFF_MODE,
        {
            "friendly_name": "Kettle",
            "operation_list": list(KETTLE_MODES),
            "operation_mode": OFF_MODE,
            "current_temperature": 25,
            "temperature": 100,
            "min_temp": 40,
            "max_temp": 100,
        },
    )
    hass.states.async_set(LAMP, "off", {"friendly_name": "Lamp"})


def base_options(entity_options: dict | None = None) -> dict[str, Any]:
    """Опции config entry: три выставленных устройства и связь геркона.

    Args:
        entity_options: Содержимое ключа ``gate_options`` (хранилище
            per-entity опций), или ``None``, чтобы ключа не было вовсе —
            ровно как у пользователя, который ничего не настраивал.

    Returns:
        Готовый словарь опций config entry.
    """
    options: dict[str, Any] = {
        CONF_EXPOSED_ENTITIES: [GATE, KETTLE, LAMP],
        CONF_ENTITY_TYPE_OVERRIDES: {GATE: "gate", KETTLE: "kettle", LAMP: "relay"},
        CONF_ENTITY_LINKS: {GATE: {"open_state": CONTACT}},
    }
    if entity_options is not None:
        # Пишем ЛИТЕРАЛЬНЫЙ ключ v1.42: так выглядит запись у уже
        # установленного пользователя.
        options[LEGACY_OPTIONS_KEY] = entity_options
    return options


async def setup_entry(hass: HomeAssistant, entity_options: dict | None = None) -> MockConfigEntry:
    """Поднять интеграцию со стендом и заданными per-entity опциями."""
    assert await async_setup_component(hass, "frontend", {})
    register_hardware(hass)

    entry = MockConfigEntry(
        domain=DOMAIN,
        data=dict(SBER_CREDENTIALS),
        options=base_options(entity_options),
        version=3,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


@pytest.fixture
async def entry(hass: HomeAssistant) -> AsyncGenerator[MockConfigEntry]:
    """Интеграция без единой сохранённой опции (чистая установка)."""
    created = await setup_entry(hass)
    yield created
    if created.state is ConfigEntryState.LOADED:
        await hass.config_entries.async_unload(created.entry_id)
        await hass.async_block_till_done()


def live(entry_: MockConfigEntry, entity_id: str) -> BaseEntity:
    """Живая Sber-сущность внутри работающего моста."""
    return entry_.runtime_data.bridge.entities[entity_id]


def arm_publish_capture(entry_: MockConfigEntry) -> SberBridge:
    """Сделать мост «подключённым» с перехватом публикаций.

    Returns:
        Тот же мост — для чтения ``_mqtt_service.publish``.
    """
    bridge = entry_.runtime_data.bridge
    bridge._mqtt_client = AsyncMock()
    bridge._mqtt_service.publish = AsyncMock()
    bridge._connected = True
    bridge._ack_audit.cancel()
    return bridge


def payloads(bridge: SberBridge, marker: str) -> list[dict]:
    """Все опубликованные payload'ы, чей топик содержит ``marker``."""
    out: list[dict] = []
    for call in bridge._mqtt_service.publish.call_args_list:
        args = call.args if call.args else call[0]
        if marker in str(args[0]):
            out.append(json.loads(args[1]))
    return out


async def ws_call(client: Any, payload: dict) -> dict:
    """Отправить WS-команду и вернуть сырой ответ."""
    await client.send_json_auto_id(payload)
    return await client.receive_json()


def service_call(domain: str, service: str, entity_id: str, data: dict | None = None) -> dict:
    """Эталонный дескриптор HA-вызова, каким его строит ``BaseEntity``."""
    url: dict[str, Any] = {
        "type": "call_service",
        "domain": domain,
        "service": service,
        "target": {"entity_id": entity_id},
    }
    if data is not None:
        url["service_data"] = data
    return {"url": url}


def sber_cmd(*states: dict) -> dict:
    """Собрать Sber-команду из готовых элементов ``states``."""
    return {"states": list(states)}


def on_off(value: bool) -> dict:
    """Элемент команды Sber ``on_off``."""
    return {"key": "on_off", "value": {"type": "BOOL", "bool_value": value}}


def water_temp(value: int) -> dict:
    """Элемент команды Sber ``kitchen_water_temperature_set``."""
    return {"key": "kitchen_water_temperature_set", "value": {"type": "INTEGER", "integer_value": str(value)}}


def declared_open_state(entity: BaseEntity) -> set[str] | None:
    """``allowed_values.open_state`` сущности (``None``, если не объявлено)."""
    declared = entity.create_allowed_values_list().get("open_state")
    if declared is None:
        return None
    return set(declared["enum_values"]["values"])


# ---------------------------------------------------------------------------
# 1. Хранилище: старый ключ обязан читаться после апгрейда
# ---------------------------------------------------------------------------


class TestLegacyStorageKey:
    """Настройки, записанные v1.42-v1.46, обязаны пережить апгрейд."""

    def test_storage_key_is_still_the_v1_42_string(self) -> None:
        """Ключ хранилища по-прежнему буквально ``gate_options``.

        Миграции опций в интеграции нет.  Если обобщение переименовало
        ключ, у каждого, кто уже настроил ворота, настройки просто
        исчезнут при обновлении: инверсия геркона вернётся в исходное
        положение, и ворота начнут показывать «открыто» вместо
        «закрыто».
        """
        assert CONF_ENTITY_OPTIONS == LEGACY_OPTIONS_KEY
        assert CONF_GATE_OPTIONS == CONF_ENTITY_OPTIONS

    async def test_legacy_gate_options_are_applied_on_load(self, hass: HomeAssistant) -> None:
        """Ворота, настроенные до апгрейда, работают ровно как настроили.

        Загрузчик читает опции по ключу ``gate_options``.  Если после
        обобщения он смотрит в другой ключ, пользователь получит ворота
        с полярностью по умолчанию и выключенной эмуляцией хода — то
        есть тихий откат всех его настроек.
        """
        created = await setup_entry(
            hass,
            {GATE: {"invert_contact": True, "impulse_service": "turn_on", "travel_time": 20.0}},
        )
        try:
            gate = live(created, GATE)
            assert isinstance(gate, ImpulseGateEntity)
            assert gate.invert_contact is True
            assert gate.impulse_service_option == "turn_on"
            assert gate.travel_time == 20.0
        finally:
            await hass.config_entries.async_unload(created.entry_id)
            await hass.async_block_till_done()

    async def test_legacy_key_feeds_a_kettle_too(self, hass: HomeAssistant) -> None:
        """Тот же ключ обслуживает новую категорию — без второго хранилища.

        Если опции чайника поехали в отдельный ключ, их не увидит ни
        export, ни удаление сущности, ни этот загрузчик: пользователь
        настроит режимы, а после перезапуска HA чайник снова перестанет
        включаться.
        """
        created = await setup_entry(
            hass,
            {KETTLE: {"off_mode": OFF_MODE, "boil_mode": BOIL_MODE, "heat_mode": HEAT_MODE}},
        )
        try:
            kettle = live(created, KETTLE)
            assert isinstance(kettle, KettleEntity)
            assert kettle.process_cmd(sber_cmd(on_off(True))) == [
                service_call("water_heater", "set_operation_mode", KETTLE, {"operation_mode": BOIL_MODE})
            ]
        finally:
            await hass.config_entries.async_unload(created.entry_id)
            await hass.async_block_till_done()

    async def test_options_for_two_categories_coexist(self, hass: HomeAssistant) -> None:
        """Ворота и чайник настраиваются одновременно и не мешают друг другу.

        Общее хранилище — это словарь ``entity_id → опции``.  Если
        применение опций одной категории затирает или отбрасывает записи
        другой, настройка второго устройства молча снесёт первое.
        """
        created = await setup_entry(
            hass,
            {
                GATE: {"travel_time": 20.0, "auto_close_time": 45.0},
                KETTLE: {"boil_mode": BOIL_MODE},
            },
        )
        try:
            gate = live(created, GATE)
            assert (gate.travel_time, gate.auto_close_time) == (20.0, 45.0)
            assert live(created, KETTLE).entity_options_state()["boil_mode"] == BOIL_MODE
        finally:
            await hass.config_entries.async_unload(created.entry_id)
            await hass.async_block_till_done()

    async def test_options_stored_for_a_category_without_options_are_ignored(self, hass: HomeAssistant) -> None:
        """Мусор в опциях сущности без опций не роняет загрузку интеграции.

        Раньше загрузчик отфильтровывал чужие записи проверкой
        ``isinstance(..., ImpulseGateEntity)``.  После обобщения опции
        уходят в сущность безусловно, и запись, оставшаяся от смены
        категории (или правки конфига руками), не должна стоить
        пользователю всей интеграции.
        """
        created = await setup_entry(hass, {LAMP: {"invert_contact": True, "travel_time": 20.0}})
        try:
            assert created.state is ConfigEntryState.LOADED
            lamp = live(created, LAMP)
            assert isinstance(lamp, RelayEntity)
            assert lamp.supports_entity_options is False
        finally:
            await hass.config_entries.async_unload(created.entry_id)
            await hass.async_block_till_done()


# ---------------------------------------------------------------------------
# 2. Обратная совместимость WebSocket-команды v1.42
# ---------------------------------------------------------------------------


class TestLegacyGateOptionsCommand:
    """``update_gate_options`` зовёт панель, уже стоящая у пользователей."""

    async def test_legacy_command_still_saves_and_answers_in_the_old_shape(
        self,
        hass: HomeAssistant,
        hass_ws_client: Any,
        entry: MockConfigEntry,
    ) -> None:
        """Имя команды, форма ответа и место хранения не изменились.

        Панель в браузере кеширована и переживает обновление
        интеграции: она пошлёт старое имя и прочитает ответ по ключу
        ``gate_options``.  Любое расхождение — «сохранить» в панели без
        видимого эффекта.
        """
        client = await hass_ws_client(hass)

        response = await ws_call(
            client,
            {"type": "sber_mqtt_bridge/update_gate_options", "entity_id": GATE, "travel_time": 12.5},
        )
        await hass.async_block_till_done()

        assert response["success"], response.get("error")
        assert response["result"] == {"entity_id": GATE, "gate_options": {"travel_time": 12.5}}
        assert entry.options[LEGACY_OPTIONS_KEY] == {GATE: {"travel_time": 12.5}}
        assert live(entry, GATE).travel_time == 12.5

    async def test_legacy_command_accepts_the_new_auto_close_field(
        self,
        hass: HomeAssistant,
        hass_ws_client: Any,
        entry: MockConfigEntry,
    ) -> None:
        """Новая опция ворот доступна и через старую команду.

        Панель ворот отправляет форму целиком одним сообщением старой
        командой.  Если ``auto_close_time`` не входит в её схему, поле
        будет отвергнуто вместе со всей формой и ни одна настройка ворот
        больше не сохранится.
        """
        client = await hass_ws_client(hass)

        response = await ws_call(
            client,
            {
                "type": "sber_mqtt_bridge/update_gate_options",
                "entity_id": GATE,
                "invert_contact": True,
                "impulse_service": "turn_on",
                "travel_time": 20.0,
                "auto_close_time": 45.0,
            },
        )
        await hass.async_block_till_done()

        assert response["success"], response.get("error")
        assert response["result"]["gate_options"] == {
            "invert_contact": True,
            "impulse_service": "turn_on",
            "travel_time": 20.0,
            "auto_close_time": 45.0,
        }
        gate = live(entry, GATE)
        assert (gate.invert_contact, gate.impulse_service_option) == (True, "turn_on")
        assert (gate.travel_time, gate.auto_close_time) == (20.0, 45.0)

    async def test_legacy_command_refuses_a_payload_without_options(
        self,
        hass: HomeAssistant,
        hass_ws_client: Any,
        entry: MockConfigEntry,
    ) -> None:
        """Вызов без единого поля отвергнут и ничего не пишет.

        Пустое сохранение раньше клало в опции пустой словарь и
        перезагружало интеграцию впустую — то есть рвало MQTT-сессию
        просто так.
        """
        client = await hass_ws_client(hass)

        response = await ws_call(client, {"type": "sber_mqtt_bridge/update_gate_options", "entity_id": GATE})
        await hass.async_block_till_done()

        assert response["success"] is False
        assert response["error"]["code"] == "invalid_format"
        assert entry.options.get(CONF_ENTITY_OPTIONS, {}) == {}

    async def test_legacy_command_on_a_plain_relay_reports_not_a_gate(
        self,
        hass: HomeAssistant,
        hass_ws_client: Any,
        entry: MockConfigEntry,
    ) -> None:
        """Код ошибки ``not_a_gate`` — часть контракта v1.42.

        Панель различает «сущность не найдена» и «это не ворота»: по
        второму коду она прячет форму ворот.  Смена кода превратит
        понятное сообщение в неизвестную ошибку.
        """
        client = await hass_ws_client(hass)

        response = await ws_call(
            client,
            {"type": "sber_mqtt_bridge/update_gate_options", "entity_id": LAMP, "travel_time": 12.5},
        )
        await hass.async_block_till_done()

        assert response["success"] is False
        assert response["error"]["code"] == "not_a_gate"
        assert entry.options.get(CONF_ENTITY_OPTIONS, {}) == {}

    async def test_legacy_command_on_a_kettle_reports_not_a_gate(
        self,
        hass: HomeAssistant,
        hass_ws_client: Any,
        entry: MockConfigEntry,
    ) -> None:
        """Опции ворот, адресованные чайнику, — тоже ``not_a_gate``.

        До обобщения любая сущность, не являющаяся импульсными воротами,
        давала ровно этот код.  Появление у чайника СВОИХ опций не
        должно превращать тот же вызов в необработанное исключение:
        панель ждёт код ошибки, а получит ``unknown_error`` и покажет
        пользователю «внутренняя ошибка» вместо внятного отказа.
        """
        client = await hass_ws_client(hass)

        response = await ws_call(
            client,
            {"type": "sber_mqtt_bridge/update_gate_options", "entity_id": KETTLE, "travel_time": 12.5},
        )
        await hass.async_block_till_done()

        assert response["success"] is False
        assert response["error"]["code"] == "not_a_gate"
        assert entry.options.get(CONF_ENTITY_OPTIONS, {}) == {}

    async def test_legacy_command_on_an_unknown_entity_reports_not_found(
        self,
        hass: HomeAssistant,
        hass_ws_client: Any,
        entry: MockConfigEntry,
    ) -> None:
        """Несуществующая сущность — ``not_found``, а не запись в опции.

        Сохранение опций для сущности, которой нет в мосту, оставило бы
        в конфиге запись-призрак, которую пользователь уже никогда не
        увидит и не удалит через панель.
        """
        client = await hass_ws_client(hass)

        response = await ws_call(
            client,
            {"type": "sber_mqtt_bridge/update_gate_options", "entity_id": "switch.nope", "travel_time": 12.5},
        )
        await hass.async_block_till_done()

        assert response["success"] is False
        assert response["error"]["code"] == "not_found"
        assert entry.options.get(CONF_ENTITY_OPTIONS, {}) == {}


# ---------------------------------------------------------------------------
# 3. Обобщённая команда: сохранение без перезагрузки, для любой категории
# ---------------------------------------------------------------------------


class TestGenericCommandSavesWithoutReload:
    """Галочка в панели не должна стоить пользователю MQTT-сессии."""

    @pytest.mark.parametrize(
        ("entity_id", "fields"),
        [
            (GATE, {"travel_time": 12.5}),
            (KETTLE, {"boil_mode": BOIL_MODE}),
        ],
        ids=["gate", "kettle"],
    )
    async def test_saving_does_not_reload_the_entry(
        self,
        hass: HomeAssistant,
        hass_ws_client: Any,
        entry: MockConfigEntry,
        entity_id: str,
        fields: dict,
    ) -> None:
        """Сохранение опции не перезагружает запись и не пересоздаёт сущность.

        Перезагрузка рвёт MQTT-сессию с облаком: команды, отправленные в
        эти секунды, теряются, а Sber успевает пометить устройства
        офлайн.  Тот же объект сущности после сохранения — доказательство
        того, что мост не пересобирали.
        """
        client = await hass_ws_client(hass)
        before = live(entry, entity_id)

        with patch.object(hass.config_entries, "async_reload", new_callable=AsyncMock) as reload_mock:
            response = await ws_call(
                client,
                {"type": "sber_mqtt_bridge/update_entity_options", "entity_id": entity_id, "options": fields},
            )
            await hass.async_block_till_done()

        assert response["success"], response.get("error")
        assert response["result"] == {"entity_id": entity_id, "options": fields}
        reload_mock.assert_not_called()
        assert entry.state is ConfigEntryState.LOADED
        assert live(entry, entity_id) is before, "сущность пересоздана — значит запись всё-таки перезагрузили"
        assert entry.options[CONF_ENTITY_OPTIONS] == {entity_id: fields}

    async def test_gate_value_reaches_the_live_entity(
        self,
        hass: HomeAssistant,
        hass_ws_client: Any,
        entry: MockConfigEntry,
    ) -> None:
        """Время хода доезжает до живых ворот и меняет их модель.

        Без reload единственный способ применить опцию — протолкнуть её в
        живой объект.  Иначе пользователь настроит время хода и не
        увидит эффекта до перезапуска HA, а необъявленное ``opening``
        облако молча выбросит (issue #44).
        """
        client = await hass_ws_client(hass)

        response = await ws_call(
            client,
            {
                "type": "sber_mqtt_bridge/update_entity_options",
                "entity_id": GATE,
                "options": {"travel_time": 12.5},
            },
        )
        await hass.async_block_till_done()

        assert response["success"], response.get("error")
        gate = live(entry, GATE)
        assert gate.travel_time == 12.5
        assert declared_open_state(gate) == GATE_OPEN_STATE_FULL

    async def test_kettle_modes_reach_the_live_entity(
        self,
        hass: HomeAssistant,
        hass_ws_client: Any,
        entry: MockConfigEntry,
    ) -> None:
        """Режимы чайника доезжают до живой сущности и меняют команды.

        Имена режимов в стенде русские — автоопределение на них не
        срабатывает.  Значит правильный ``set_operation_mode`` может
        появиться ТОЛЬКО из сохранённой опции: если она не доехала,
        пользователь нажмёт «вкл» в приложении Сбера и чайник не
        закипятит воду.
        """
        client = await hass_ws_client(hass)

        response = await ws_call(
            client,
            {
                "type": "sber_mqtt_bridge/update_entity_options",
                "entity_id": KETTLE,
                "options": {"off_mode": OFF_MODE, "boil_mode": BOIL_MODE, "heat_mode": HEAT_MODE},
            },
        )
        await hass.async_block_till_done()

        assert response["success"], response.get("error")
        kettle = live(entry, KETTLE)
        assert kettle.process_cmd(sber_cmd(on_off(False))) == [
            service_call("water_heater", "set_operation_mode", KETTLE, {"operation_mode": OFF_MODE})
        ]
        assert kettle.process_cmd(sber_cmd(on_off(True), water_temp(80))) == [
            service_call("water_heater", "set_temperature", KETTLE, {"temperature": 80}),
            service_call("water_heater", "set_operation_mode", KETTLE, {"operation_mode": HEAT_MODE}),
        ]

    async def test_partial_save_merges_with_what_is_already_stored(
        self,
        hass: HomeAssistant,
        hass_ws_client: Any,
        entry: MockConfigEntry,
    ) -> None:
        """Отправка одного поля не стирает соседние.

        Форма чайника умеет сохранять по одному выпадающему списку.
        Если сохранение заменяет весь словарь, выбор режима «кипятить»
        обнулит уже настроенный «выключить» — и чайник перестанет
        выключаться из приложения.
        """
        client = await hass_ws_client(hass)

        first = await ws_call(
            client,
            {
                "type": "sber_mqtt_bridge/update_entity_options",
                "entity_id": KETTLE,
                "options": {"off_mode": OFF_MODE},
            },
        )
        second = await ws_call(
            client,
            {
                "type": "sber_mqtt_bridge/update_entity_options",
                "entity_id": KETTLE,
                "options": {"boil_mode": BOIL_MODE},
            },
        )
        await hass.async_block_till_done()

        assert first["success"], first.get("error")
        assert second["success"], second.get("error")
        assert second["result"]["options"] == {"off_mode": OFF_MODE, "boil_mode": BOIL_MODE}
        assert entry.options[CONF_ENTITY_OPTIONS] == {KETTLE: {"off_mode": OFF_MODE, "boil_mode": BOIL_MODE}}

    async def test_saving_republishes_whole_config_and_only_this_state(
        self,
        hass: HomeAssistant,
        hass_ws_client: Any,
        entry: MockConfigEntry,
    ) -> None:
        """После сохранения уезжают ПОЛНАЯ конфигурация и состояние одной сущности.

        Sber читает каждый ``config`` как исчерпывающий список устройств:
        payload с одними воротами заставит облако удалить и пересоздать
        всё остальное, потеряв имена и комнаты (issue #44).  Состояние,
        наоборот, публикуется только для изменённой сущности — лишние
        публикации бессмысленно нагружают сессию.
        """
        bridge = arm_publish_capture(entry)
        client = await hass_ws_client(hass)

        response = await ws_call(
            client,
            {
                "type": "sber_mqtt_bridge/update_entity_options",
                "entity_id": GATE,
                "options": {"travel_time": 12.5},
            },
        )
        await hass.async_block_till_done()

        assert response["success"], response.get("error")
        configs = payloads(bridge, "up/config")
        assert configs, "модель устройства обязана уехать в облако до первого 'opening'"
        assert {device["id"] for device in configs[-1]["devices"]} == {HUB_DEVICE_ID, GATE, KETTLE, LAMP}
        gate_model = next(d for d in configs[-1]["devices"] if d["id"] == GATE)["model"]
        assert set(gate_model["allowed_values"]["open_state"]["enum_values"]["values"]) == GATE_OPEN_STATE_FULL
        statuses = payloads(bridge, "up/status")
        assert statuses, "состояние изменённой сущности обязано быть переопубликовано"
        assert set(statuses[-1]["devices"]) == {GATE}


# ---------------------------------------------------------------------------
# 4. Валидация обобщённой команды
# ---------------------------------------------------------------------------


class TestGenericCommandValidation:
    """Отказ обязан быть внятным и не оставлять следов в конфиге."""

    async def test_empty_options_are_refused(
        self,
        hass: HomeAssistant,
        hass_ws_client: Any,
        entry: MockConfigEntry,
    ) -> None:
        """Вызов без полей отвергнут кодом ``invalid_format``.

        Пустое сохранение обошлось бы в переопубликацию всей
        конфигурации и состояния ни за что: у пользователя с полусотней
        устройств это заметная пауза в работе моста.
        """
        client = await hass_ws_client(hass)

        response = await ws_call(
            client,
            {"type": "sber_mqtt_bridge/update_entity_options", "entity_id": GATE, "options": {}},
        )
        await hass.async_block_till_done()

        assert response["success"] is False
        assert response["error"]["code"] == "invalid_format"
        assert entry.options.get(CONF_ENTITY_OPTIONS, {}) == {}

    async def test_option_of_another_category_is_refused(
        self,
        hass: HomeAssistant,
        hass_ws_client: Any,
        entry: MockConfigEntry,
    ) -> None:
        """Опция чайника, адресованная воротам, отвергнута с внятным кодом.

        Общая схема команды знает ключи всех категорий сразу, поэтому
        «чужой» ключ проходит схему и обязан быть пойман самой
        сущностью.  Молчаливое сохранение положило бы в конфиг
        настройку, которая никогда ни на что не влияет, и пользователь
        считал бы её работающей.
        """
        client = await hass_ws_client(hass)

        response = await ws_call(
            client,
            {
                "type": "sber_mqtt_bridge/update_entity_options",
                "entity_id": GATE,
                "options": {"boil_mode": BOIL_MODE},
            },
        )
        await hass.async_block_till_done()

        assert response["success"] is False
        assert response["error"]["code"] == "invalid_option"
        assert "boil_mode" in response["error"]["message"]
        assert entry.options.get(CONF_ENTITY_OPTIONS, {}) == {}

    async def test_mode_absent_from_operation_list_is_refused(
        self,
        hass: HomeAssistant,
        hass_ws_client: Any,
        entry: MockConfigEntry,
    ) -> None:
        """Режим, которого у чайника нет, отвергается в момент сохранения.

        HA молча проглатывает ``set_operation_mode`` с неизвестным
        режимом.  Без проверки пользователь получил бы чайник, который
        подтверждает команды из приложения Сбера и никогда не греет, —
        и никакого следа в логе.
        """
        client = await hass_ws_client(hass)

        response = await ws_call(
            client,
            {
                "type": "sber_mqtt_bridge/update_entity_options",
                "entity_id": KETTLE,
                "options": {"boil_mode": "Boil"},
            },
        )
        await hass.async_block_till_done()

        assert response["success"] is False
        assert response["error"]["code"] == "invalid_option"
        message = response["error"]["message"]
        assert "Boil" in message
        assert BOIL_MODE in message, "сообщение обязано перечислить режимы, которые чайник реально предлагает"
        assert entry.options.get(CONF_ENTITY_OPTIONS, {}) == {}

    async def test_category_without_options_is_refused(
        self,
        hass: HomeAssistant,
        hass_ws_client: Any,
        entry: MockConfigEntry,
    ) -> None:
        """Сущность без опций отвергает вызов отдельным кодом.

        Панель по этому коду поймёт, что форму рисовать не нужно.  Если
        вместо кода прилетит исключение, пользователь увидит «внутренняя
        ошибка» на совершенно исправной интеграции.
        """
        client = await hass_ws_client(hass)

        response = await ws_call(
            client,
            {
                "type": "sber_mqtt_bridge/update_entity_options",
                "entity_id": LAMP,
                "options": {"travel_time": 12.5},
            },
        )
        await hass.async_block_till_done()

        assert response["success"] is False
        assert response["error"]["code"] == "not_supported"
        assert entry.options.get(CONF_ENTITY_OPTIONS, {}) == {}

    async def test_unknown_entity_is_refused(
        self,
        hass: HomeAssistant,
        hass_ws_client: Any,
        entry: MockConfigEntry,
    ) -> None:
        """Сущность, которой нет в мосту, не создаёт запись в конфиге.

        Иначе в опциях останется мусор, невидимый в панели: удалить его
        можно будет только правкой ``.storage`` руками.
        """
        client = await hass_ws_client(hass)

        response = await ws_call(
            client,
            {
                "type": "sber_mqtt_bridge/update_entity_options",
                "entity_id": "water_heater.nope",
                "options": {"boil_mode": BOIL_MODE},
            },
        )
        await hass.async_block_till_done()

        assert response["success"] is False
        assert response["error"]["code"] == "not_found"
        assert entry.options.get(CONF_ENTITY_OPTIONS, {}) == {}

    @pytest.mark.parametrize(
        ("options", "case"),
        [
            ({"travel_time": True}, "bool вместо секунд"),
            ({"travel_time": -1}, "отрицательное время"),
            ({"travel_time": 601}, "больше 10 минут"),
            ({"auto_close_time": 3601}, "больше часа"),
            ({"impulse_service": "explode"}, "несуществующий сервис"),
            ({"nonsense": 1}, "ключ, неизвестный ни одной категории"),
        ],
    )
    async def test_structurally_invalid_values_never_reach_the_entity(
        self,
        hass: HomeAssistant,
        hass_ws_client: Any,
        entry: MockConfigEntry,
        options: dict,
        case: str,
    ) -> None:
        """Схема команды отсекает заведомо невозможные значения.

        ``apply_entity_options`` намеренно снисходителен (правка конфига
        руками не должна ронять загрузку), поэтому мусор, пропущенный
        схемой, будет сохранён и молча проигнорирован: пользователь
        увидит сохранённое значение в панели и решит, что оно работает.
        """
        client = await hass_ws_client(hass)

        response = await ws_call(
            client,
            {"type": "sber_mqtt_bridge/update_entity_options", "entity_id": GATE, "options": options},
        )
        await hass.async_block_till_done()

        assert response["success"] is False, case
        assert response["error"]["code"] == "invalid_format", case
        assert entry.options.get(CONF_ENTITY_OPTIONS, {}) == {}


# ---------------------------------------------------------------------------
# 4a. Жизненный цикл хранилища: удаление сущности уносит её опции
# ---------------------------------------------------------------------------


class TestOptionsStoreLifecycle:
    """Опции живут ровно столько же, сколько сама выставленная сущность."""

    async def test_removing_an_entity_drops_its_options(
        self,
        hass: HomeAssistant,
        hass_ws_client: Any,
        entry: MockConfigEntry,
    ) -> None:
        """Удаление сущности уносит её опции — и это работает для любой категории.

        Осиротевшая запись вернётся в тот день, когда пользователь снова
        добавит то же устройство мастером: чайник, добавленный заново,
        унаследует режимы от прошлой конфигурации, о которой пользователь
        уже забыл.  Соседние записи при этом обязаны уцелеть.
        """
        client = await hass_ws_client(hass)
        for entity_id, fields in (
            (GATE, {"travel_time": 20.0}),
            (KETTLE, {"boil_mode": BOIL_MODE}),
        ):
            saved = await ws_call(
                client,
                {"type": "sber_mqtt_bridge/update_entity_options", "entity_id": entity_id, "options": fields},
            )
            assert saved["success"], saved.get("error")
        await hass.async_block_till_done()

        response = await ws_call(client, {"type": "sber_mqtt_bridge/remove_entities", "entity_ids": [KETTLE]})
        await hass.async_block_till_done()

        assert response["success"], response.get("error")
        assert entry.options[CONF_ENTITY_OPTIONS] == {GATE: {"travel_time": 20.0}}

    async def test_clear_all_empties_the_options_store(
        self,
        hass: HomeAssistant,
        hass_ws_client: Any,
        entry: MockConfigEntry,
    ) -> None:
        """«Очистить всё» вычищает и опции — включая опции новых категорий.

        Пользователь зовёт эту команду, чтобы начать настройку с нуля.
        Пережившие её опции превратят «чистую» установку в установку с
        невидимыми настройками из прошлой жизни.
        """
        client = await hass_ws_client(hass)
        saved = await ws_call(
            client,
            {
                "type": "sber_mqtt_bridge/update_entity_options",
                "entity_id": KETTLE,
                "options": {"boil_mode": BOIL_MODE},
            },
        )
        assert saved["success"], saved.get("error")
        await hass.async_block_till_done()

        response = await ws_call(client, {"type": "sber_mqtt_bridge/clear_all"})
        await hass.async_block_till_done()

        assert response["success"], response.get("error")
        assert entry.options[CONF_ENTITY_OPTIONS] == {}
        assert entry.options[CONF_EXPOSED_ENTITIES] == []


# ---------------------------------------------------------------------------
# 5. Круговой рейс export → import
# ---------------------------------------------------------------------------


class TestExportImportRoundTrip:
    """Выгруженный конфиг обязан загружаться обратно без правки руками."""

    async def test_export_carries_options_of_every_category(
        self,
        hass: HomeAssistant,
        hass_ws_client: Any,
        entry: MockConfigEntry,
    ) -> None:
        """Выгрузка содержит опции и ворот, и чайника — в одном блоке.

        Экспорт — это то, что пользователь приложит к issue и чем
        восстановит настройки после переустановки HA.  Потерянный блок
        означает молча потерянные настройки при восстановлении.
        """
        client = await hass_ws_client(hass)
        stored = {
            GATE: {"invert_contact": True, "travel_time": 20.0, "auto_close_time": 45.0},
            KETTLE: {"off_mode": OFF_MODE, "boil_mode": BOIL_MODE, "heat_mode": HEAT_MODE},
        }
        for entity_id, fields in stored.items():
            response = await ws_call(
                client,
                {"type": "sber_mqtt_bridge/update_entity_options", "entity_id": entity_id, "options": fields},
            )
            assert response["success"], response.get("error")
        await hass.async_block_till_done()

        exported = await ws_call(client, {"type": "sber_mqtt_bridge/export"})

        assert exported["success"], exported.get("error")
        assert exported["result"][LEGACY_OPTIONS_KEY] == stored

    async def test_exported_config_imports_back_unchanged(
        self,
        hass: HomeAssistant,
        hass_ws_client: Any,
        entry: MockConfigEntry,
    ) -> None:
        """Круговой рейс не теряет и не искажает ни одной опции.

        Схема импорта строгая: ключ, забытый в ней, превращает
        собственную выгрузку интеграции в невалидный файл — пользователь
        узнает об этом ровно в тот момент, когда будет восстанавливать
        конфигурацию после сбоя.
        """
        client = await hass_ws_client(hass)
        stored = {
            GATE: {"invert_contact": True, "impulse_service": "turn_on", "travel_time": 20.0, "auto_close_time": 45.0},
            KETTLE: {"off_mode": OFF_MODE, "boil_mode": BOIL_MODE, "heat_mode": HEAT_MODE},
        }
        for entity_id, fields in stored.items():
            saved = await ws_call(
                client,
                {"type": "sber_mqtt_bridge/update_entity_options", "entity_id": entity_id, "options": fields},
            )
            assert saved["success"], saved.get("error")
        await hass.async_block_till_done()
        exported = await ws_call(client, {"type": "sber_mqtt_bridge/export"})
        assert exported["success"], exported.get("error")

        imported = await ws_call(
            client,
            {"type": "sber_mqtt_bridge/import", "config": exported["result"]},
        )
        await hass.async_block_till_done()

        assert imported["success"], imported.get("error")
        assert entry.options[CONF_ENTITY_OPTIONS] == stored

    async def test_imported_options_are_applied_to_the_reloaded_entities(
        self,
        hass: HomeAssistant,
        hass_ws_client: Any,
        entry: MockConfigEntry,
    ) -> None:
        """Импортированные опции действуют сразу после импорта.

        Импорт перезагружает запись, и именно на этой загрузке опции
        обязаны примениться.  Иначе восстановленная из файла установка
        будет вести себя как ненастроенная до следующего перезапуска HA:
        ворота с обратной полярностью, чайник без режимов.
        """
        client = await hass_ws_client(hass)
        config = {
            "version": 3,
            "exposed_entities": [GATE, KETTLE, LAMP],
            "type_overrides": {GATE: "gate", KETTLE: "kettle", LAMP: "relay"},
            "entity_links": {GATE: {"open_state": CONTACT}},
            LEGACY_OPTIONS_KEY: {
                GATE: {"invert_contact": True, "travel_time": 20.0},
                KETTLE: {"boil_mode": BOIL_MODE},
            },
        }

        response = await ws_call(client, {"type": "sber_mqtt_bridge/import", "config": config})
        await hass.async_block_till_done()

        assert response["success"], response.get("error")
        gate = live(entry, GATE)
        assert gate.invert_contact is True
        assert gate.travel_time == 20.0
        assert declared_open_state(gate) == GATE_OPEN_STATE_FULL
        assert live(entry, KETTLE).process_cmd(sber_cmd(on_off(True))) == [
            service_call("water_heater", "set_operation_mode", KETTLE, {"operation_mode": BOIL_MODE})
        ]

    async def test_import_of_an_impossible_value_is_refused_wholesale(
        self,
        hass: HomeAssistant,
        hass_ws_client: Any,
        entry: MockConfigEntry,
    ) -> None:
        """Битый файл не применяется по частям.

        Импорт — это «заменить всю конфигурацию».  Частично применённый
        файл оставил бы установку в состоянии, которого нет ни в одном
        сохранённом конфиге, и разобраться в нём было бы уже нельзя.
        """
        client = await hass_ws_client(hass)
        config = {
            "exposed_entities": [GATE],
            "type_overrides": {GATE: "gate"},
            LEGACY_OPTIONS_KEY: {GATE: {"travel_time": 9999}},
        }

        response = await ws_call(client, {"type": "sber_mqtt_bridge/import", "config": config})
        await hass.async_block_till_done()

        assert response["success"] is False
        assert response["error"]["code"] == "invalid_config"
        assert entry.options[CONF_EXPOSED_ENTITIES] == [GATE, KETTLE, LAMP]
        assert entry.options.get(CONF_ENTITY_OPTIONS, {}) == {}


# ---------------------------------------------------------------------------
# 6. device_detail: панель обязана увидеть текущие значения
# ---------------------------------------------------------------------------


class TestDeviceDetailOptionBlocks:
    """Карточка устройства отдаёт форму ровно той категории, что нужна."""

    async def test_gate_block_keeps_its_v1_42_name_and_full_field_set(
        self,
        hass: HomeAssistant,
        hass_ws_client: Any,
        entry: MockConfigEntry,
    ) -> None:
        """Блок ворот называется ``gate_options`` и содержит все поля формы.

        Форма отправляет все свои поля одним сообщением: поле, которому
        backend не прислал значение, уйдёт пустым и затрёт соседнюю
        сохранённую настройку при следующем сохранении.
        """
        client = await hass_ws_client(hass)

        response = await ws_call(client, {"type": "sber_mqtt_bridge/device_detail", "entity_id": GATE})

        assert response["success"], response.get("error")
        assert response["result"]["gate_options"] == {
            "invert_contact": False,
            "impulse_service": "auto",
            "contact_stale": False,
            "travel_time": 0.0,
            "auto_close_time": 0.0,
        }

    async def test_gate_block_shows_the_saved_values(
        self,
        hass: HomeAssistant,
        hass_ws_client: Any,
        entry: MockConfigEntry,
    ) -> None:
        """Сохранённые опции видны в карточке без перезагрузки записи.

        Панель перечитывает карточку сразу после сохранения.  Если она
        покажет прежние значения, пользователь решит, что сохранение не
        сработало, и нажмёт ещё раз.
        """
        client = await hass_ws_client(hass)
        saved = await ws_call(
            client,
            {
                "type": "sber_mqtt_bridge/update_entity_options",
                "entity_id": GATE,
                "options": {"invert_contact": True, "travel_time": 20.0, "auto_close_time": 45.0},
            },
        )
        assert saved["success"], saved.get("error")
        await hass.async_block_till_done()

        response = await ws_call(client, {"type": "sber_mqtt_bridge/device_detail", "entity_id": GATE})

        assert response["success"], response.get("error")
        assert response["result"]["gate_options"] == {
            "invert_contact": True,
            "impulse_service": "auto",
            "contact_stale": False,
            "travel_time": 20.0,
            "auto_close_time": 45.0,
        }

    async def test_kettle_block_offers_the_entity_own_modes(
        self,
        hass: HomeAssistant,
        hass_ws_client: Any,
        entry: MockConfigEntry,
    ) -> None:
        """Блок чайника отдаёт список режимов сущности и результат автоподбора.

        Выпадающие списки в панели заполняются из ``operation_list``:
        без него пользователю остался бы свободный ввод, а опечатка в
        имени режима даёт чайник, который подтверждает команды и не
        греет.  ``resolved_*`` показывает, что мост подобрал сам, — у
        чайника с русскими именами режимов не подбирается ничего, и это
        обязано быть видно ДО того, как пользователь понадеется на
        автоматику.
        """
        client = await hass_ws_client(hass)

        response = await ws_call(client, {"type": "sber_mqtt_bridge/device_detail", "entity_id": KETTLE})

        assert response["success"], response.get("error")
        assert response["result"]["kettle_options"] == {
            "off_mode": "",
            "boil_mode": "",
            "heat_mode": "",
            "operation_list": KETTLE_MODES,
            "resolved_off_mode": "",
            "resolved_boil_mode": "",
            "resolved_heat_mode": "",
        }

    async def test_kettle_block_shows_the_saved_modes(
        self,
        hass: HomeAssistant,
        hass_ws_client: Any,
        entry: MockConfigEntry,
    ) -> None:
        """Сохранённые режимы видны и как выбор, и как результат подбора.

        Пользователь настраивает режимы ровно один раз и проверяет
        результат глазами.  Пустой ``resolved_*`` при заполненном выборе
        означал бы, что мост опцию не принял, — и это должно быть видно
        в панели, а не в логе.
        """
        client = await hass_ws_client(hass)
        saved = await ws_call(
            client,
            {
                "type": "sber_mqtt_bridge/update_entity_options",
                "entity_id": KETTLE,
                "options": {"off_mode": OFF_MODE, "boil_mode": BOIL_MODE, "heat_mode": HEAT_MODE},
            },
        )
        assert saved["success"], saved.get("error")
        await hass.async_block_till_done()

        response = await ws_call(client, {"type": "sber_mqtt_bridge/device_detail", "entity_id": KETTLE})

        assert response["success"], response.get("error")
        assert response["result"]["kettle_options"] == {
            "off_mode": OFF_MODE,
            "boil_mode": BOIL_MODE,
            "heat_mode": HEAT_MODE,
            "operation_list": KETTLE_MODES,
            "resolved_off_mode": OFF_MODE,
            "resolved_boil_mode": BOIL_MODE,
            "resolved_heat_mode": HEAT_MODE,
        }

    async def test_relay_card_carries_no_option_block_at_all(
        self,
        hass: HomeAssistant,
        hass_ws_client: Any,
        entry: MockConfigEntry,
    ) -> None:
        """У категории без опций в карточке нет ни одного блока настроек.

        Панель рисует форму по факту наличия ключа.  Лишний (пусть и
        пустой) блок нарисует пользователю форму ворот на обычной
        розетке — с полями, которые ничего не делают.
        """
        client = await hass_ws_client(hass)

        response = await ws_call(client, {"type": "sber_mqtt_bridge/device_detail", "entity_id": LAMP})

        assert response["success"], response.get("error")
        result = response["result"]
        assert result["entity_id"] == LAMP
        assert {"gate_options", "kettle_options", "entity_options"} & set(result) == set()


# ---------------------------------------------------------------------------
# 7. Контракт BaseEntity: категория без опций не пострадала
# ---------------------------------------------------------------------------


class TestBaseEntityContract:
    """Механизм обязан быть частью контракта базового класса."""

    def test_base_entity_declares_the_whole_contract(self) -> None:
        """У ``BaseEntity`` есть все четыре элемента механизма.

        Если применение опций останется методом одного класса, каждая
        следующая категория снова потребует правок в загрузчике, мосту и
        WebSocket — то есть механизм не обобщён, а скопирован.
        """
        for member in (
            "ENTITY_OPTION_KEYS",
            "ENTITY_OPTIONS_BLOCK",
            "supports_entity_options",
            "apply_entity_options",
            "validate_entity_options",
            "entity_options_state",
        ):
            assert hasattr(BaseEntity, member), f"BaseEntity не объявляет {member}"

    def test_categories_declare_their_own_option_keys(self) -> None:
        """Каждая категория объявляет ПОЛНЫЙ и точный набор своих ключей.

        Ключ, забытый в ``ENTITY_OPTION_KEYS``, будет отвергнут
        валидацией как чужой, и опция станет недоступна из панели.
        Лишний ключ, наоборот, будет сохранён и молча проигнорирован.
        """
        assert set(ImpulseGateEntity.ENTITY_OPTION_KEYS) == {
            "invert_contact",
            "impulse_service",
            "travel_time",
            "auto_close_time",
        }
        assert set(KettleEntity.ENTITY_OPTION_KEYS) == {"off_mode", "boil_mode", "heat_mode"}
        assert RelayEntity.ENTITY_OPTION_KEYS == ()

    def test_option_blocks_do_not_collide(self) -> None:
        """Блоки категорий в ``device_detail`` называются по-разному.

        Совпадение имён заставило бы панель нарисовать форму ворот для
        чайника: ключ в ответе один, а поля в нём чужие.
        """
        assert ImpulseGateEntity.ENTITY_OPTIONS_BLOCK == "gate_options"
        assert KettleEntity.ENTITY_OPTIONS_BLOCK == "kettle_options"
        assert ImpulseGateEntity.ENTITY_OPTIONS_BLOCK != KettleEntity.ENTITY_OPTIONS_BLOCK

    def test_entity_without_options_ignores_everything(self) -> None:
        """Сущность без опций молча игнорирует любые опции.

        Загрузчик отдаёт опции всем сущностям подряд.  Исключение здесь
        означало бы, что запись, оставшаяся от смены категории, ломает
        загрузку всей интеграции.
        """
        relay = RelayEntity({"entity_id": LAMP, "name": "Lamp"})

        assert relay.supports_entity_options is False
        assert relay.entity_options_state() == {}
        relay.apply_entity_options({"invert_contact": True, "travel_time": 20.0})
        assert relay.entity_options_state() == {}

    def test_entity_without_options_rejects_user_input(self) -> None:
        """Пользовательский ввод для сущности без опций отвергается.

        ``apply_*`` снисходителен к конфигу, но ввод из панели обязан
        валидироваться строго: иначе сохранение «получится», а эффекта
        не будет.
        """
        relay = RelayEntity({"entity_id": LAMP, "name": "Lamp"})

        with pytest.raises(ValueError, match="travel_time"):
            relay.validate_entity_options({"travel_time": 20.0})
