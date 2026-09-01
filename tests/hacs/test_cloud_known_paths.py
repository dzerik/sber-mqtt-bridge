"""Все пути, которыми мост узнаёт, какие устройства держит облако.

Панель показывает пользователю строку «Известно Сберу: N». Число берётся
из :class:`~cloud_device_registry.CloudDeviceRegistry`, а он переживает
перезапуск только потому, что дублируется в ``ConfigEntry.options``.

В issue #57 пользователь с рабочим мостом (36 выставленных устройств,
команды проходят, статусы отдаются) видел «Известно Сберу: 0». Значит
реестр не пополнился ни одним из способов, которыми облако сообщает о
себе, и ни одна из этих записей не дошла до опций.

Способов ровно четыре, и каждый из них здесь проверяется до конца — не
до внутреннего множества, а до значения в ``entry.options``, потому что
именно оттуда читает следующий запуск:

1. **публикация конфигурации** — всё, что ушло в ``up/config``, облако
   зарегистрировало;
2. **``down/status_request`` со списком id** — облако спрашивает только
   про то, что держит; это прямое свидетельство;
3. **``down/status_request`` без списка** («состояние всех устройств») —
   свидетельство слабее, но облако не опрашивает хаб, для которого у
   него ничего нет. Именно этот случай наблюдался у пользователя;
4. **``down/commands``** — команда приходит только на устройство,
   которое облако держит.

Плюс свойства, без которых первые четыре бесполезны: запись переживает
чужие перезаписи опций (настройки, добавление и удаление сущности) и
перезапуск записи конфигурации; реестр не выдумывает устройств, о
которых облако не говорило; и публикация состояний не пишет в опции —
иначе каждое движение датчика приводило бы к записи на диск.

Стенд — полный: настоящий HA, настоящая запись конфигурации, настоящий
:class:`SberBridge`, настоящая загрузка сущностей. Подменён только
транспорт (in-memory recorder) и бесконечный цикл переподключения, так
что весь путь от MQTT-сообщения до ``entry.options`` реален.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import patch

import aiomqtt
import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_mock_service

from custom_components.sber_mqtt_bridge.cloud_device_registry import HUB_DEVICE_ID, OPTIONS_KEY
from custom_components.sber_mqtt_bridge.const import (
    CONF_EXPOSED_ENTITIES,
    CONF_SBER_BROKER,
    CONF_SBER_LOGIN,
    CONF_SBER_PASSWORD,
    CONF_SBER_PORT,
    CONF_SBER_VERIFY_SSL,
    DOMAIN,
)
from custom_components.sber_mqtt_bridge.sber_bridge import SberBridge

_LOGGER = logging.getLogger(__name__)

LAMP = "light.lamp"
PUMP = "switch.pump"
EXPOSED = [LAMP, PUMP]
"""Полный набор выставленных сущностей стенда — обе со состоянием."""

EXPOSED_SORTED = sorted(EXPOSED)
"""Ровно то, что обязано лежать в ``entry.options`` после публикации."""


# ---------------------------------------------------------------------------
# Стенд (перенесён из test_websocket_full_stack.py — фикстуры модульные)
# ---------------------------------------------------------------------------


class RecordingTransport:
    """In-memory замена подключённого ``aiomqtt.Client``.

    Используется только ``publish``: цикл переподключения выключен, так
    что мост через этот объект ничего не читает.
    """

    def __init__(self) -> None:
        """Начать с пустого журнала публикаций."""
        self.published: list[tuple[str, str | bytes]] = []

    async def publish(self, topic: str, payload: str | bytes) -> None:
        """Записать исходящую публикацию вместо обращения к сети."""
        self.published.append((topic, payload))


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: Any) -> None:
    """Разрешить HA грузить ``custom_components/sber_mqtt_bridge``."""
    return


@pytest.fixture(autouse=True)
def _no_mqtt_reconnect_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    """Отключить бесконечную задачу переподключения MQTT.

    Всё выше транспорта (загрузка сущностей, запись опций, диспетчер)
    работает по-настоящему; убрана только граница с сетью.
    """

    async def _noop(self: SberBridge) -> None:
        return

    monkeypatch.setattr(SberBridge, "_mqtt_connection_loop", _noop)


def _register_devices(hass: HomeAssistant) -> None:
    """Создать два HA-устройства с сущностями стенда."""
    owner = MockConfigEntry(domain="test_devices")
    owner.add_to_hass(hass)
    device_reg = dr.async_get(hass)
    entity_reg = er.async_get(hass)

    lamp_device = device_reg.async_get_or_create(
        config_entry_id=owner.entry_id,
        identifiers={("test_devices", "lamp")},
        name="Lamp device",
    )
    pump_device = device_reg.async_get_or_create(
        config_entry_id=owner.entry_id,
        identifiers={("test_devices", "pump")},
        name="Pump device",
    )

    entity_reg.async_get_or_create(
        "light",
        "test_devices",
        "lamp-uid",
        suggested_object_id="lamp",
        config_entry=owner,
        device_id=lamp_device.id,
    )
    entity_reg.async_get_or_create(
        "switch",
        "test_devices",
        "pump-uid",
        suggested_object_id="pump",
        config_entry=owner,
        device_id=pump_device.id,
    )

    hass.states.async_set(LAMP, "on", {"friendly_name": "Lamp", "supported_color_modes": ["brightness"]})
    hass.states.async_set(PUMP, "off", {"friendly_name": "Pump"})


@pytest.fixture
async def entry(hass: HomeAssistant) -> AsyncGenerator[MockConfigEntry]:
    """Поднять интеграцию по-настоящему и отдать её запись конфигурации."""
    assert await async_setup_component(hass, "frontend", {})
    _register_devices(hass)

    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_SBER_LOGIN: "test",
            CONF_SBER_PASSWORD: "pass",
            CONF_SBER_BROKER: "broker.test",
            CONF_SBER_PORT: 8883,
            CONF_SBER_VERIFY_SSL: False,
        },
        options={CONF_EXPOSED_ENTITIES: list(EXPOSED)},
        version=3,
    )
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    yield config_entry

    if config_entry.state is ConfigEntryState.LOADED:
        await hass.config_entries.async_unload(config_entry.entry_id)
        await hass.async_block_till_done()


def attach_transport(config_entry: MockConfigEntry) -> RecordingTransport:
    """Подключить записывающий транспорт к текущему мосту записи.

    Вызывается заново после каждой перезагрузки записи: перезагрузка
    строит новый :class:`SberBridge` с новым MQTT-сервисом, и старый
    транспорт к нему уже не привязан.

    Args:
        config_entry: Запись конфигурации интеграции.

    Returns:
        Присоединённый рекордер публикаций.
    """
    recorder = RecordingTransport()
    service = config_entry.runtime_data.bridge._mqtt_service
    service._client = recorder
    service._connected = True
    return recorder


@pytest.fixture
def transport(entry: MockConfigEntry) -> RecordingTransport:
    """Подключить записывающий транспорт и пометить мост подключённым."""
    return attach_transport(entry)


@pytest.fixture
def ha_services(hass: HomeAssistant) -> dict[str, list[Any]]:
    """Замокать HA-сервисы, которые дёргают команды Сбера."""
    return {
        "light.turn_on": async_mock_service(hass, "light", "turn_on"),
        "light.turn_off": async_mock_service(hass, "light", "turn_off"),
        "switch.turn_on": async_mock_service(hass, "switch", "turn_on"),
        "switch.turn_off": async_mock_service(hass, "switch", "turn_off"),
    }


# ---------------------------------------------------------------------------
# Помощники
# ---------------------------------------------------------------------------


def persisted(config_entry: MockConfigEntry) -> Any:
    """Вернуть значение реестра ровно так, как оно лежит в опциях."""
    return config_entry.options.get(OPTIONS_KEY)


def live(config_entry: MockConfigEntry) -> frozenset[str]:
    """Вернуть множество, которым мост оперирует прямо сейчас."""
    return config_entry.runtime_data.bridge._cloud_devices.known


def status_request(*entity_ids: str) -> str:
    """Собрать полезную нагрузку ``down/status_request``.

    Args:
        entity_ids: Идентификаторы, которые называет облако; пустой
            вызов даёт запрос «состояние всех устройств».

    Returns:
        JSON-строку в том виде, в каком её присылает Сбер.
    """
    return json.dumps({"devices": list(entity_ids)})


def command(entity_id: str, *, turn_on: bool = True) -> str:
    """Собрать полезную нагрузку ``down/commands`` на одно устройство."""
    return json.dumps(
        {
            "devices": {
                entity_id: {
                    "states": [{"key": "on_off", "value": {"type": "BOOL", "bool_value": turn_on}}],
                }
            }
        }
    )


async def inject(hass: HomeAssistant, config_entry: MockConfigEntry, suffix: str, payload: str) -> None:
    """Прогнать сообщение через настоящий входящий конвейер моста."""
    result = await config_entry.runtime_data.bridge.async_inject_sber_message(suffix, payload)
    assert result["handled"] is True, f"мост не разобрал топик {suffix}"
    await hass.async_block_till_done()


# ---------------------------------------------------------------------------
# 1. Публикация конфигурации
# ---------------------------------------------------------------------------


class TestConfigPublishPath:
    """Публикация ``up/config`` — основной способ узнать, что держит облако."""

    async def test_config_publish_fills_registry_and_options(
        self, hass: HomeAssistant, entry: MockConfigEntry, transport: RecordingTransport
    ) -> None:
        """Успешная публикация обязана дойти до опций записи.

        Если этого не происходит, панель показывает «Известно Сберу: 0»
        на исправно работающем мосте (issue #57), а следующий запуск
        считает, что у облака нет ничего, — и публикует список, который
        облако воспримет как «остальные удалены» (issue #44).
        """
        bridge = entry.runtime_data.bridge
        assert live(entry) == frozenset(), "до публикации реестр обязан быть пуст"
        assert persisted(entry) is None, "до публикации ключа в опциях быть не должно"

        assert await bridge._publisher.publish_config(force=True) is True
        await hass.async_block_till_done()

        assert live(entry) == frozenset(EXPOSED)
        assert persisted(entry) == EXPOSED_SORTED
        assert bridge.cloud_known_entities == EXPOSED

    async def test_config_request_from_cloud_fills_registry_and_options(
        self, hass: HomeAssistant, entry: MockConfigEntry, transport: RecordingTransport
    ) -> None:
        """``down/config_request`` обязан заполнить реестр, а не промолчать.

        Облако спрашивает конфигурацию именно тогда, когда сомневается в
        своей копии. Если мост отвечает пропуском по дедупликации, Сбер
        не получает ничего и реестр остаётся пустым на всю сессию — ровно
        картина issue #57.
        """
        assert live(entry) == frozenset()

        await inject(hass, entry, "config_request", "{}")

        assert live(entry) == frozenset(EXPOSED)
        assert persisted(entry) == EXPOSED_SORTED

    async def test_config_request_refills_a_registry_emptied_by_removal(
        self, hass: HomeAssistant, entry: MockConfigEntry, transport: RecordingTransport
    ) -> None:
        """Повторный ``config_request`` обязан работать после первого.

        Мост не отправляет побайтово тот же payload. Пока публикация
        отвечала на прямой вопрос облака молчанием, второй шанс заполнить
        реестр не наступал никогда. Здесь реестр опустошают руками — как
        это делает снятие сущности с публикации, — и облако переспрашивает.
        """
        bridge = entry.runtime_data.bridge
        await inject(hass, entry, "config_request", "{}")
        assert live(entry) == frozenset(EXPOSED)

        bridge.forget_cloud_devices(EXPOSED)
        await hass.async_block_till_done()
        assert live(entry) == frozenset(), "подготовка: реестр обязан быть очищен"

        await inject(hass, entry, "config_request", "{}")

        assert live(entry) == frozenset(EXPOSED)
        assert persisted(entry) == EXPOSED_SORTED

    async def test_publish_without_transport_records_nothing(self, hass: HomeAssistant, entry: MockConfigEntry) -> None:
        """Неотправленная конфигурация не смеет считаться доставленной.

        Транспорт не подключён (фикстура ``transport`` не запрошена).
        Если бы мост записал такие устройства как известные облаку,
        панель показывала бы «Известно Сберу: 2» при пустом облаке, а
        калитка публикации ждала бы подтверждения от устройств, которых
        у Сбера нет.
        """
        bridge = entry.runtime_data.bridge

        assert await bridge._publisher.publish_config(force=True) is False
        await hass.async_block_till_done()

        assert live(entry) == frozenset()
        assert persisted(entry) is None

    async def test_publish_that_raises_records_nothing(
        self, hass: HomeAssistant, entry: MockConfigEntry, transport: RecordingTransport
    ) -> None:
        """Упавшая публикация не смеет считаться доставленной.

        Брокер может отвергнуть пакет (например, по размеру). Мост при
        этом продолжает жить и обслуживать команды — именно поэтому
        отказ обязан быть виден в реестре, а не замаскирован.
        """
        bridge = entry.runtime_data.bridge

        async def _boom(topic: str, payload: str | bytes) -> None:
            raise RuntimeError("broker refused the packet")

        transport.publish = _boom  # type: ignore[method-assign]

        assert await bridge._publisher.publish_config(force=True) is False
        await hass.async_block_till_done()

        assert live(entry) == frozenset()
        assert persisted(entry) is None


# ---------------------------------------------------------------------------
# 2. status_request со списком id
# ---------------------------------------------------------------------------


class TestStatusRequestWithIds:
    """Облако спрашивает только про то, что держит, — это прямое свидетельство."""

    async def test_named_ids_reach_registry_and_options(
        self, hass: HomeAssistant, entry: MockConfigEntry, transport: RecordingTransport
    ) -> None:
        """Названные облаком id обязаны попасть и в реестр, и в опции.

        Это единственный источник, работающий после перезапуска, когда
        публикация ещё не прошла. Потеря этих данных возвращает issue #44:
        следующая публикация не будет знать, что облако держит.
        """
        await inject(hass, entry, "status_request", status_request(LAMP, PUMP))

        assert live(entry) == frozenset(EXPOSED)
        assert persisted(entry) == EXPOSED_SORTED

    async def test_only_the_named_device_is_recorded(
        self, hass: HomeAssistant, entry: MockConfigEntry, transport: RecordingTransport
    ) -> None:
        """Реестр не смеет дописывать устройства, о которых облако молчало.

        Столбец «Известно Сберу» — единственный признак молчаливого
        отказа Сбера. Если бы запрос про одну лампу помечал известным и
        насос, молчаливо отвергнутое устройство навсегда выглядело бы
        принятым и предупреждение никогда бы не сработало.
        """
        await inject(hass, entry, "status_request", status_request(LAMP))

        assert live(entry) == frozenset({LAMP})
        assert persisted(entry) == [LAMP]
        assert entry.runtime_data.bridge.never_confirmed_entities == [PUMP]

    async def test_hub_root_is_never_recorded(
        self, hass: HomeAssistant, entry: MockConfigEntry, transport: RecordingTransport
    ) -> None:
        """Хаб — не устройство пользователя и в реестр попадать не должен.

        ``root`` присутствует всегда и ни одной сущности HA не
        соответствует. Записанный в реестр, он навсегда сделал бы
        «Известно Сберу» на единицу больше действительного и удержал бы
        калитку публикации на несуществующей сущности.
        """
        await inject(hass, entry, "status_request", status_request(HUB_DEVICE_ID))

        assert live(entry) == frozenset()
        assert persisted(entry) is None

    async def test_ids_merge_across_requests(
        self, hass: HomeAssistant, entry: MockConfigEntry, transport: RecordingTransport
    ) -> None:
        """Второй запрос дополняет реестр, а не подменяет его.

        Сбер опрашивает устройства по одному. Если бы каждый запрос
        перетирал реестр, «Известно Сберу» вечно показывало бы единицу.
        """
        await inject(hass, entry, "status_request", status_request(LAMP))
        assert live(entry) == frozenset({LAMP})

        await inject(hass, entry, "status_request", status_request(PUMP))

        assert live(entry) == frozenset(EXPOSED)
        assert persisted(entry) == EXPOSED_SORTED

    async def test_unknown_id_from_cloud_is_remembered(
        self, hass: HomeAssistant, entry: MockConfigEntry, transport: RecordingTransport
    ) -> None:
        """Устройство, которое облако держит, а мост уже нет, обязано учитываться.

        Именно ради этого случая реестр вообще существует: облако помнит
        сущность, которую HA больше не выставляет, и следующая публикация
        должна знать об этом, чтобы Сбер не пересоздал устройство и не
        потерял назначенную комнату (issue #44).
        """
        bridge = entry.runtime_data.bridge
        ghost = "light.gone_from_ha"
        await bridge._publisher.publish_config(force=True)
        await hass.async_block_till_done()

        await inject(hass, entry, "status_request", status_request(LAMP, ghost))

        assert live(entry) == frozenset({LAMP, PUMP, ghost})
        assert persisted(entry) == sorted([LAMP, PUMP, ghost])
        assert bridge.cloud_known_entities == EXPOSED, (
            "панель показывает только выставленные — но помнить мост обязан все три"
        )


# ---------------------------------------------------------------------------
# 3. status_request без списка — случай пользователя из issue #57
# ---------------------------------------------------------------------------


class TestStatusRequestWithoutIds:
    """«Состояние всех устройств» — то, что видел пользователь issue #57."""

    async def test_bare_request_seeds_registry_and_options(
        self, hass: HomeAssistant, entry: MockConfigEntry, transport: RecordingTransport
    ) -> None:
        """Запрос без списка обязан заполнить реестр выставленными сущностями.

        Ровно этот случай наблюдался в issue #57: все 36 устройств
        помечались подтверждёнными в сессии, а постоянный реестр не
        узнавал ничего — «Известно Сберу: 0» до конца жизни процесса и
        нулевой пол защиты для следующей публикации.
        """
        assert live(entry) == frozenset()

        await inject(hass, entry, "status_request", status_request())

        assert live(entry) == frozenset(EXPOSED)
        assert persisted(entry) == EXPOSED_SORTED

    async def test_empty_devices_key_is_treated_as_bare_request(
        self, hass: HomeAssistant, entry: MockConfigEntry, transport: RecordingTransport
    ) -> None:
        """Полезная нагрузка вообще без ключа ``devices`` — тот же случай.

        Сбер шлёт «состояние всех» и так, и так. Разбор, чувствительный
        к форме, оставил бы реестр пустым у половины пользователей.
        """
        await inject(hass, entry, "status_request", "{}")

        assert live(entry) == frozenset(EXPOSED)
        assert persisted(entry) == EXPOSED_SORTED

    async def test_bare_request_does_not_overwrite_per_device_knowledge(
        self, hass: HomeAssistant, entry: MockConfigEntry, transport: RecordingTransport
    ) -> None:
        """Общий запрос — только затравка, поверх точных данных он не пишет.

        Точный список, полученный из публикации или поимённого запроса,
        строго лучше догадки «всё, что выставлено». Затерев его, мост
        пометил бы принятыми устройства, которые Сбер молча отверг, и
        предупреждение «ни разу не подтверждено» замолчало бы навсегда.
        """
        await inject(hass, entry, "status_request", status_request(LAMP))
        assert live(entry) == frozenset({LAMP})

        await inject(hass, entry, "status_request", status_request())

        assert live(entry) == frozenset({LAMP}), "общий запрос перетёр поимённое знание"
        assert persisted(entry) == [LAMP]

    async def test_bare_request_does_not_silence_the_rejection_warning(
        self, hass: HomeAssistant, entry: MockConfigEntry, transport: RecordingTransport
    ) -> None:
        """Общий запрос не смеет объявлять подтверждённым каждое устройство.

        «Ни разу не подтверждено» — единственный сигнал о молчаливом
        отказе Сбера. Запрос без списка не говорит ни про одно устройство
        поимённо, поэтому насос, про который облако не спрашивало ни разу,
        обязан остаться в этом списке.

        Ровно этим объясняется картина пользователя из issue #57:
        «Подтверждено в этой сессии: 36, Ни разу не подтверждено: 0» при
        пустом постоянном реестре. Реестр от такой подмены защищён
        (см. ``note_cloud_active``), а счётчик сессии — нет, и защита
        реестра в итоге обесценивается: тревога не срабатывает никогда.
        """
        await inject(hass, entry, "status_request", status_request(LAMP))
        assert live(entry) == frozenset({LAMP})
        assert entry.runtime_data.bridge.never_confirmed_entities == [PUMP]

        await inject(hass, entry, "status_request", status_request())

        assert entry.runtime_data.bridge.never_confirmed_entities == [PUMP]

    async def test_unloadable_entity_is_not_seeded(
        self, hass: HomeAssistant, entry: MockConfigEntry, transport: RecordingTransport, hass_ws_client: Any
    ) -> None:
        """Сущность, которую мост не смог загрузить, в реестр не попадает.

        Затравка обязана браться из загруженных устройств, а не из
        списка выставленных в опциях. Выставленная, но не загруженная
        сущность никогда не сериализовалась в конфигурацию — значит Сбер
        её не держит. Записанная как известная, она навсегда удержала бы
        калитку публикации (устройство известно облаку, но готовым не
        станет) и завысила бы счётчик «Известно Сберу».
        """
        client = await hass_ws_client(hass)
        await client.send_json_auto_id(
            {"type": "sber_mqtt_bridge/add_entities", "entity_ids": ["switch.never_had_state"]}
        )
        response = await client.receive_json()
        assert response["success"], response.get("error")
        await hass.async_block_till_done()
        attach_transport(entry)
        assert entry.runtime_data.bridge.enabled_entity_ids == EXPOSED, (
            "подготовка: сущность без состояния не должна была загрузиться"
        )

        await inject(hass, entry, "status_request", status_request())

        assert live(entry) == frozenset(EXPOSED)
        assert persisted(entry) == EXPOSED_SORTED


# ---------------------------------------------------------------------------
# 4. Команда на устройство
# ---------------------------------------------------------------------------


class TestCommandPath:
    """Команда приходит только на устройство, которое облако держит."""

    async def test_command_records_the_commanded_device(
        self,
        hass: HomeAssistant,
        entry: MockConfigEntry,
        transport: RecordingTransport,
        ha_services: dict[str, list[Any]],
    ) -> None:
        """Полученная команда обязана попасть в реестр и в опции.

        Это самое прямое свидетельство из всех: Сбер не шлёт команду на
        устройство, которого у него нет. У пользователя из issue #57
        команды проходили («устройства реально работают»), а «Известно
        Сберу» стояло в нуле — то есть этот путь ничего не записывал.
        """
        assert live(entry) == frozenset()

        await inject(hass, entry, "commands", command(LAMP))

        assert ha_services["light.turn_on"], "подготовка: команда обязана дойти до HA"
        assert live(entry) == frozenset({LAMP})
        assert persisted(entry) == [LAMP]

    async def test_command_does_not_vouch_for_other_devices(
        self,
        hass: HomeAssistant,
        entry: MockConfigEntry,
        transport: RecordingTransport,
        ha_services: dict[str, list[Any]],
    ) -> None:
        """Команда на лампу ничего не говорит о насосе.

        Свидетельство поимённое. Расширив его на весь выставленный
        набор, мост пометил бы принятыми устройства, которые Сбер молча
        отверг, — и предупреждение о них исчезло бы.
        """
        await inject(hass, entry, "commands", command(LAMP))

        assert live(entry) == frozenset({LAMP})
        assert persisted(entry) == [LAMP]

    async def test_command_for_unknown_entity_records_nothing(
        self,
        hass: HomeAssistant,
        entry: MockConfigEntry,
        transport: RecordingTransport,
        ha_services: dict[str, list[Any]],
    ) -> None:
        """Команда на неизвестную мосту сущность реестр не пополняет.

        Такую команду мост выполнить не может; записав её отправителя в
        реестр, он навсегда удержал бы калитку публикации на сущности,
        которой в HA нет.
        """
        await inject(hass, entry, "commands", command("light.never_existed"))

        assert live(entry) == frozenset()
        assert persisted(entry) is None


# ---------------------------------------------------------------------------
# 5. Реестр переживает чужие записи в опции и перезапуск
# ---------------------------------------------------------------------------


class TestRegistrySurvivesForeignWrites:
    """Реестр живёт в общих опциях — любой чужой писатель может его снести."""

    async def test_update_settings_keeps_the_registry(
        self, hass: HomeAssistant, entry: MockConfigEntry, transport: RecordingTransport, hass_ws_client: Any
    ) -> None:
        """Смена настроек в панели не смеет стирать «Известно Сберу».

        Обработчик настроек собирает новые опции копией существующих.
        Если копия сделана до записи реестра (или реестр в неё не
        попал), одно нажатие «Сохранить» обнуляет столбец — и следующий
        запуск публикует список, теряющий комнаты (issue #44).
        """
        bridge = entry.runtime_data.bridge
        await bridge._publisher.publish_config(force=True)
        await hass.async_block_till_done()
        assert persisted(entry) == EXPOSED_SORTED

        client = await hass_ws_client(hass)
        await client.send_json_auto_id(
            {"type": "sber_mqtt_bridge/update_settings", "settings": {"debounce_delay": 1.5}}
        )
        response = await client.receive_json()
        assert response["success"], response.get("error")
        await hass.async_block_till_done()

        assert entry.options["debounce_delay"] == 1.5, "подготовка: настройка обязана сохраниться"
        assert persisted(entry) == EXPOSED_SORTED, "запись настроек снесла реестр"

    async def test_adding_an_entity_keeps_the_registry(
        self, hass: HomeAssistant, entry: MockConfigEntry, transport: RecordingTransport, hass_ws_client: Any
    ) -> None:
        """Добавление сущности не смеет забывать то, что уже держит облако.

        Добавление перезагружает запись. Если реестр не переживает
        перезагрузку, каждое расширение набора обнуляет защиту, и
        следующая публикация может отобрать у уже принятых устройств
        назначенные комнаты.
        """
        bridge = entry.runtime_data.bridge
        await bridge._publisher.publish_config(force=True)
        await hass.async_block_till_done()
        assert persisted(entry) == EXPOSED_SORTED

        client = await hass_ws_client(hass)
        await client.send_json_auto_id({"type": "sber_mqtt_bridge/add_entities", "entity_ids": ["sensor.extra"]})
        response = await client.receive_json()
        assert response["success"], response.get("error")
        await hass.async_block_till_done()

        assert persisted(entry) == EXPOSED_SORTED, "добавление сущности снесло реестр"
        assert live(entry) == frozenset(EXPOSED), "перезагруженный мост не прочитал реестр из опций"

    async def test_removing_an_entity_prunes_exactly_that_entity(
        self, hass: HomeAssistant, entry: MockConfigEntry, transport: RecordingTransport, hass_ws_client: Any
    ) -> None:
        """Снятие насоса убирает из реестра насос — и только его.

        Оставленная запись сделала бы снятое устройство вечным
        должником калитки публикации: облако его держит, а готовым оно
        уже не станет никогда. Убранная лишняя — вернула бы issue #44.
        """
        bridge = entry.runtime_data.bridge
        await bridge._publisher.publish_config(force=True)
        await hass.async_block_till_done()
        assert persisted(entry) == EXPOSED_SORTED

        client = await hass_ws_client(hass)
        await client.send_json_auto_id({"type": "sber_mqtt_bridge/remove_entities", "entity_ids": [PUMP]})
        response = await client.receive_json()
        assert response["success"], response.get("error")
        await hass.async_block_till_done()

        assert persisted(entry) == [LAMP]
        assert live(entry) == frozenset({LAMP})

    async def test_clear_all_empties_the_registry(
        self, hass: HomeAssistant, entry: MockConfigEntry, transport: RecordingTransport, hass_ws_client: Any
    ) -> None:
        """«Удалить все» обязано опустошить и реестр.

        Публикация с пустым списком намеренно не принимается за
        свидетельство, так что сам по себе реестр не опустеет никогда.
        Оставшись полным, он навсегда заблокировал бы калитку публикации
        устройствами, которых больше никто не выставляет.
        """
        bridge = entry.runtime_data.bridge
        await bridge._publisher.publish_config(force=True)
        await hass.async_block_till_done()
        assert persisted(entry) == EXPOSED_SORTED

        client = await hass_ws_client(hass)
        await client.send_json_auto_id({"type": "sber_mqtt_bridge/clear_all"})
        response = await client.receive_json()
        assert response["success"], response.get("error")
        await hass.async_block_till_done()

        assert persisted(entry) == []
        assert live(entry) == frozenset()

    async def test_registry_survives_a_reload(
        self, hass: HomeAssistant, entry: MockConfigEntry, transport: RecordingTransport
    ) -> None:
        """Перезапись конфигурации — момент, ради которого реестр и пишется.

        Перезагрузка строит новый мост; если он не прочитает реестр из
        опций, то опубликует список, ничего не знающий про облако, и
        Сбер пересоздаст устройства, потеряв комнаты (issue #44).
        """
        bridge = entry.runtime_data.bridge
        await bridge._publisher.publish_config(force=True)
        await hass.async_block_till_done()
        assert persisted(entry) == EXPOSED_SORTED

        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()

        assert entry.runtime_data.bridge is not bridge, "подготовка: перезагрузка обязана создать новый мост"
        assert live(entry) == frozenset(EXPOSED)
        assert persisted(entry) == EXPOSED_SORTED
        assert entry.runtime_data.bridge.cloud_known_entities == EXPOSED

    async def test_unload_does_not_erase_a_late_publish(
        self, hass: HomeAssistant, entry: MockConfigEntry, transport: RecordingTransport
    ) -> None:
        """Публикация, завершившаяся после выгрузки, обязана сохраниться.

        Каждая правка в панели перезагружает запись, так что окно между
        началом публикации и выгрузкой открывается регулярно. Пока её
        результат выбрасывали, следующий старт считал, что облако не
        держит ничего (issue #57).
        """
        bridge = entry.runtime_data.bridge
        bridge._cloud_devices.shutdown()

        bridge._cloud_devices.note_cloud_reported([LAMP])
        await hass.async_block_till_done()

        assert persisted(entry) == [LAMP]


# ---------------------------------------------------------------------------
# 6. Реестр не пишет в опции по любому поводу
# ---------------------------------------------------------------------------


class TestRegistryDoesNotThrash:
    """Опции — файл на диске; писать в них на каждый чих нельзя."""

    async def test_state_publishes_never_write_options(
        self, hass: HomeAssistant, entry: MockConfigEntry, transport: RecordingTransport
    ) -> None:
        """Публикация состояний не смеет трогать опции.

        Состояния уходят на каждое изменение в HA — десятки раз в
        минуту у активного датчика. Запись опций на каждой публикации
        означала бы постоянную перезапись ``.storage`` и перезагрузки
        записи конфигурации.
        """
        bridge = entry.runtime_data.bridge
        await bridge._publisher.publish_config(force=True)
        await hass.async_block_till_done()
        before = persisted(entry)

        with patch.object(
            hass.config_entries,
            "async_update_entry",
            wraps=hass.config_entries.async_update_entry,
        ) as writes:
            for value in ("off", "on", "off"):
                hass.states.async_set(LAMP, value, {"supported_color_modes": ["brightness"]})
                await hass.async_block_till_done()
            await bridge._publish_states(force=True)
            await hass.async_block_till_done()

        assert writes.call_count == 0, "публикация состояний записала опции"
        assert persisted(entry) == before

    async def test_repeated_identical_evidence_writes_options_once(
        self, hass: HomeAssistant, entry: MockConfigEntry, transport: RecordingTransport
    ) -> None:
        """Повторное свидетельство о том же наборе — не повод писать снова.

        Сбер опрашивает состояние регулярно. Если бы каждый запрос
        приводил к записи опций, интеграция бы перезагружалась по кругу.
        """
        await inject(hass, entry, "status_request", status_request(LAMP, PUMP))
        assert persisted(entry) == EXPOSED_SORTED

        with patch.object(
            hass.config_entries,
            "async_update_entry",
            wraps=hass.config_entries.async_update_entry,
        ) as writes:
            await inject(hass, entry, "status_request", status_request(LAMP, PUMP))
            await inject(hass, entry, "status_request", status_request(LAMP))
            await inject(hass, entry, "status_request", status_request())

        assert writes.call_count == 0, "повторное свидетельство переписало опции"
        assert persisted(entry) == EXPOSED_SORTED

    async def test_empty_config_publish_keeps_the_registry(
        self, hass: HomeAssistant, entry: MockConfigEntry, transport: RecordingTransport
    ) -> None:
        """Публикация без единого устройства не смеет обнулять реестр.

        Пустой список со стороны моста означает не «Сбер всё удалил», а
        «сущности не загрузились» — та самая деградация, ради которой
        реестр и заведён. Поверив ей, мост обнулил бы «Известно Сберу»
        на работающей системе (issue #57) и снял бы пол защиты (#44).
        """
        bridge = entry.runtime_data.bridge
        await bridge._publisher.publish_config(force=True)
        await hass.async_block_till_done()
        assert persisted(entry) == EXPOSED_SORTED

        bridge._cloud_devices.note_published([])
        await hass.async_block_till_done()

        assert live(entry) == frozenset(EXPOSED)
        assert persisted(entry) == EXPOSED_SORTED


# ---------------------------------------------------------------------------
# 7. Диагностика показывает то же, что и опции
# ---------------------------------------------------------------------------


class TestRegistryIsVisibleInDiagnostics:
    """Без выгрузки диагностики issue #57 диагностировали догадками."""

    async def test_diagnostics_state_matches_the_options(
        self, hass: HomeAssistant, entry: MockConfigEntry, transport: RecordingTransport
    ) -> None:
        """Живое множество и записанное в опции обязаны совпадать.

        Расхождение — это и есть issue #57 в чистом виде: панель читает
        одно, следующий запуск — другое. Выгрузка диагностики должна
        показывать оба, чтобы вопрос «какое из двух пустое» имел ответ.
        """
        bridge = entry.runtime_data.bridge
        await bridge._publisher.publish_config(force=True)
        await hass.async_block_till_done()

        state = bridge.cloud_device_registry_state

        assert state["known"] == EXPOSED_SORTED
        assert state["persisted"] == EXPOSED_SORTED
        assert state["known_exposed"] == EXPOSED
        assert state["never_confirmed"] == []
        assert state["config_published_this_session"] is True


class TestALateWriteCannotResurrectARemovedDevice:
    """Умирающий мост не смеет вернуть в опции устройство, которое сняли."""

    async def test_late_publish_does_not_undo_a_removal(
        self, hass: HomeAssistant, entry: MockConfigEntry, transport: RecordingTransport, hass_ws_client: Any
    ) -> None:
        """Публикация, стартовавшая до снятия сущности, не возвращает её.

        Каждая правка в панели перезагружает запись, поэтому окно между
        началом публикации и выгрузкой открывается регулярно. Реестр
        умирающего моста хранит набор, снятый ДО правки: записав его как
        есть, он вернул бы в опции устройство, которое пользователь
        только что убрал. Оно осталось бы там навсегда — невидимым, пока
        сущность не выставят снова, и тогда показалось бы «известным
        Сберу» без единого свидетельства, попутно став полом, которого
        калитка публикации ждёт до истечения таймаута.
        """
        old_registry = entry.runtime_data.bridge._cloud_devices
        old_registry.note_cloud_reported(EXPOSED)
        assert persisted(entry) == EXPOSED_SORTED

        client = await hass_ws_client(hass)
        await client.send_json_auto_id({"type": "sber_mqtt_bridge/remove_entities", "entity_ids": [PUMP]})
        response = await client.receive_json()
        assert response["success"], response.get("error")
        await hass.async_block_till_done()
        assert persisted(entry) == [LAMP], "подготовка: снятие обязано вычистить реестр"

        # Публикация старого моста завершается уже после выгрузки и
        # отчитывается о наборе, снятом до правки.
        old_registry.shutdown()
        old_registry.note_published(EXPOSED)
        await hass.async_block_till_done()

        assert persisted(entry) == [LAMP], "снятое устройство вернулось в опции"


# ---------------------------------------------------------------------------
# 8. Сорвавшаяся первая публикация
# ---------------------------------------------------------------------------


class FlakyTransport(RecordingTransport):
    """Транспорт, роняющий первые ``failures`` публикаций конфигурации.

    Воспроизводит единственный потерянный пакет: соединение живо,
    состояния уходят нормально, но ``up/config`` не долетел.
    """

    def __init__(self, failures: int = 1) -> None:
        """Начать с пустого журнала и заданным числом срывов.

        Args:
            failures: Сколько первых публикаций конфигурации провалить.
        """
        super().__init__()
        self.failures = failures
        self.config_attempts = 0
        """Сколько раз мост пытался отправить конфигурацию."""

    async def publish(self, topic: str, payload: str | bytes) -> None:
        """Записать публикацию, уронив первые ``failures`` конфигураций."""
        if topic.endswith("/config"):
            self.config_attempts += 1
            if self.config_attempts <= self.failures:
                raise aiomqtt.MqttError("packet dropped")
        await super().publish(topic, payload)


class TestFailedInitialPublishIsRetried:
    """Сорвавшаяся публикация при подключении не должна стоить сессии.

    Рукопожатие раньше шло дальше молча: мост подписывался, исполнял
    команды и выглядел здоровым, а Сбер не получал список устройств.
    Реестр заполняется только успешной публикацией, поэтому «Известно
    Сберу» оставалось нулевым до конца жизни процесса — ровно то, что
    видел пользователь issue #57.
    """

    async def test_dropped_config_packet_is_republished(self, hass: HomeAssistant, entry: MockConfigEntry) -> None:
        """После неудачной публикации мост обязан попробовать снова.

        Без повторной попытки один потерянный пакет оставляет облако без
        конфигурации на всю сессию, а реестр — пустым, и вернуться к
        нормальной работе можно только перезапуском Home Assistant.
        """
        bridge = entry.runtime_data.bridge
        flaky = FlakyTransport()
        service = bridge._mqtt_service
        service._client = flaky
        service._connected = True

        await bridge._perform_initial_publish()
        await hass.async_block_till_done()

        assert flaky.config_attempts >= 2, "мост не повторил сорвавшуюся публикацию конфигурации"
        assert live(entry) == frozenset(EXPOSED), "реестр остался пустым при работающем мосте"
        assert persisted(entry) == EXPOSED_SORTED

    async def test_failed_publish_is_reported_to_the_operator(
        self, hass: HomeAssistant, entry: MockConfigEntry, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Провал обязан быть громким: молчание тут и породило issue #57.

        Пользователь видел исправно выглядящий мост и нулевой счётчик,
        и в журнале не было ничего, что связало бы одно с другим.
        """
        bridge = entry.runtime_data.bridge
        flaky = FlakyTransport(failures=99)
        service = bridge._mqtt_service
        service._client = flaky
        service._connected = True

        with caplog.at_level(logging.ERROR, logger="custom_components.sber_mqtt_bridge.sber_bridge"):
            await bridge._perform_initial_publish()
            await hass.async_block_till_done()

        assert "did NOT reach Sber" in caplog.text, "сорвавшаяся публикация конфигурации прошла молча"
