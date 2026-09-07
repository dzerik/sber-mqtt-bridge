"""Миграция ``model.id``: что видит пользователь при обновлении и при установке.

С версии 1.51 мост иначе называет **модели** устройств: в дайджест
``model.id`` вошли производитель и название железа, а из объявления
пропали функции, которых нет в справочнике категории Sber.  Обе правки
двигают идентификатор, а облако держит одну модель на идентификатор —
значит при первой публикации оно заведёт модели заново.

Отменить это, оставив старый идентификатор, нельзя: содержимое модели
под неизменным ``model.id`` облако не подхватывает (1.39.6b3 — облако
сохранило устаревшую зависимость, и все команды цвета отклонялись), то
есть пин сохранил бы ровно те сломанные описания, ради которых правка и
делалась.  Поэтому миграция — это предупреждение, а не совместимость.

Здесь проверяется именно та часть, которую видит пользователь:

* **обновление с 1.50.0** — у записи конфигурации уже есть устройства,
  зарегистрированные в облаке, и человек обязан получить объяснение,
  почему в приложении Сбера что-то поменялось;
* **чистая установка** — регистрировать заново нечего, и пугать
  человека уведомлением не за что;
* уведомление приходит **один раз**: следующий перезапуск не должен
  показывать его снова, иначе оно превратится в шум и его перестанут
  читать;
* пометка о выполненной миграции пишется, **не затирая** соседние ключи
  ``entry.options`` — реестр устройств облака живёт там же, и потеря его
  ключа стоила бы пользователю комнат (issue #44, #57);
* **обновление с версии старше самого реестра облака** (до 1.45): реестра
  в опциях нет вовсе, и решение откладывается, а не принимается по
  пустому месту;
* у каждой записи конфигурации своё уведомление — два аккаунта Сбера не
  затирают уведомления друг друга.

Если эти тесты упадут: человек либо не узнает, что Сбер перерегистрирует
его устройства (и решит, что мост сломался), либо получит это
уведомление на каждый перезапуск, либо потеряет реестр «известно Сберу».
"""

from __future__ import annotations

from typing import Any

import pytest
from homeassistant.components import persistent_notification
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sber_mqtt_bridge.cloud_device_registry import (
    MODEL_IDENTITY_REVISION,
    OPTIONS_KEY,
    OPTIONS_MODEL_REVISION_KEY,
    CloudDeviceRegistry,
    ModelIdentityMigration,
    migration_notification_id,
)
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

KNOWN_DEVICES = ["light.lamp", "switch.pump"]
"""Устройства, которые облако уже держит, — признак обновления, а не установки."""


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: Any) -> None:
    """Разрешить HA грузить ``custom_components/sber_mqtt_bridge``."""
    return


def _entry(hass: HomeAssistant, **options: Any) -> MockConfigEntry:
    """Создать запись конфигурации с заданными опциями.

    Args:
        hass: Экземпляр Home Assistant.
        **options: Содержимое ``entry.options``.

    Returns:
        Добавленная в HA запись конфигурации.
    """
    entry = MockConfigEntry(domain=DOMAIN, data={}, options=dict(options), version=3)
    entry.add_to_hass(hass)
    return entry


def _run(hass: HomeAssistant, entry: MockConfigEntry) -> bool:
    """Выполнить миграцию для записи и вернуть, было ли уведомление."""
    return ModelIdentityMigration(hass, entry, CloudDeviceRegistry(hass, entry)).async_run()


def _notifications(hass: HomeAssistant) -> dict[str, Any]:
    """Вернуть текущие постоянные уведомления HA."""
    return persistent_notification._async_get_or_create_notifications(hass)


class TestUpgradeFrom1500:
    """Запись, у которой облако уже держит устройства."""

    async def test_user_is_told_what_happened(self, hass: HomeAssistant) -> None:
        """Пользователь получает уведомление с числом задетых устройств.

        Если упадёт: человек увидит в приложении Сбера новые модели (а
        возможно, и сброшенные комнаты) без единого слова о причине и
        решит, что мост сломался.
        """
        entry = _entry(hass, **{OPTIONS_KEY: KNOWN_DEVICES, CONF_EXPOSED_ENTITIES: KNOWN_DEVICES})

        assert _run(hass, entry) is True

        notice = _notifications(hass)[migration_notification_id(entry)]
        assert "модел" in str(notice["title"]), "заголовок не говорит, о чём речь"
        assert f"{len(KNOWN_DEVICES)} шт." in str(notice["message"]), "не сказано, сколько устройств задето"
        assert "комнат" in str(notice["message"]), "нет объяснения, что делать с комнатой"

    async def test_every_dropped_feature_is_named(self, hass: HomeAssistant) -> None:
        """В объяснении перечислено всё, что реально снимается.

        Список составлен по фактическому замеру, а не по памяти: кроме
        ``on_off`` у домофона и ``tamper_alarm``/``alarm_mute`` у датчиков
        снимаются ещё ``sensor_sensitive`` (дым, протечка) и
        ``hvac_humidity_set`` (бойлер, обогреватель, радиатор, тёплый
        пол).

        Если тест упадёт, у человека с датчиком дыма пропадёт регулировка
        чувствительности, а в объяснении об этом не будет ни слова — он
        решит, что сломалось что-то ещё.
        """
        entry = _entry(hass, **{OPTIONS_KEY: KNOWN_DEVICES})

        _run(hass, entry)

        message = str(_notifications(hass)[migration_notification_id(entry)]["message"])
        for feature in ("on_off", "tamper_alarm", "alarm_mute", "sensor_sensitive", "hvac_humidity_set"):
            assert feature in message, f"в уведомлении не назван {feature}"

    async def test_entry_is_stamped_with_the_current_revision(self, hass: HomeAssistant) -> None:
        """После миграции запись помечена текущей ревизией."""
        entry = _entry(hass, **{OPTIONS_KEY: KNOWN_DEVICES})

        _run(hass, entry)

        assert entry.options[OPTIONS_MODEL_REVISION_KEY] == MODEL_IDENTITY_REVISION

    async def test_notice_is_shown_once(self, hass: HomeAssistant) -> None:
        """Второй запуск молчит — уведомление не повторяется.

        Если упадёт: уведомление будет всплывать на каждый перезапуск HA
        и на каждую правку в панели (она перезагружает запись), после
        чего его перестанут читать вовсе.
        """
        entry = _entry(hass, **{OPTIONS_KEY: KNOWN_DEVICES})
        assert _run(hass, entry) is True

        persistent_notification.async_dismiss(hass, migration_notification_id(entry))
        assert _run(hass, entry) is False
        assert migration_notification_id(entry) not in _notifications(hass)

    async def test_neighbouring_options_survive(self, hass: HomeAssistant) -> None:
        """Пометка не затирает соседние ключи опций.

        В тех же опциях лежит реестр «что держит облако». Потеря его
        ключа означает публикацию укороченного списка устройств, а это
        ровно та потеря комнат, ради которой реестр и заведён (#44).
        """
        entry = _entry(
            hass,
            **{OPTIONS_KEY: KNOWN_DEVICES, CONF_EXPOSED_ENTITIES: KNOWN_DEVICES, "foreign_key": "keep me"},
        )

        _run(hass, entry)

        assert entry.options[OPTIONS_KEY] == KNOWN_DEVICES
        assert entry.options[CONF_EXPOSED_ENTITIES] == KNOWN_DEVICES
        assert entry.options["foreign_key"] == "keep me"


class TestCleanInstall:
    """Запись, у которой облако не держит ничего."""

    async def test_no_notification(self, hass: HomeAssistant) -> None:
        """Свежей установке не о чем сообщать.

        Перерегистрировать нечего: в облаке нет ни одной нашей модели.
        Если упадёт, каждый новый пользователь получит на первом же
        запуске уведомление про «изменились описания моделей», которых
        он ещё ни разу не отправлял.
        """
        entry = _entry(hass)

        assert _run(hass, entry) is False
        assert migration_notification_id(entry) not in _notifications(hass)

    async def test_entry_is_stamped_anyway(self, hass: HomeAssistant) -> None:
        """Пометка всё равно ставится — иначе первая же публикация
        превратит чистую установку в «обновление» и покажет уведомление
        задним числом.
        """
        entry = _entry(hass)

        _run(hass, entry)

        assert entry.options[OPTIONS_MODEL_REVISION_KEY] == MODEL_IDENTITY_REVISION

    async def test_exposed_entities_alone_are_not_evidence(self, hass: HomeAssistant) -> None:
        """Выставленные сущности без подтверждения от облака — не повод.

        Мост, который ни разу не смог опубликовать конфигурацию, ничего
        в облаке не регистрировал, и говорить ему о перерегистрации
        нечего.
        """
        entry = _entry(hass, **{OPTIONS_KEY: [], CONF_EXPOSED_ENTITIES: KNOWN_DEVICES})

        assert _run(hass, entry) is False


class TestUpgradeFromBeforeTheRegistry:
    """Обновление с версии старше самого реестра «известно Сберу» (до 1.45).

    У такой записи ключа реестра в опциях нет вовсе — не пустой список, а
    отсутствие ключа. Пустой реестр тут не значит «в облаке ничего нет»,
    он значит «мы ещё не спрашивали»: устройства у человека в облаке
    есть, и модели им перерегистрируют.

    Если эти тесты упадут, запись пометится ревизией на пустом месте, и к
    моменту, когда первая же публикация наполнит реестр, уведомлять будет
    уже некому — пользователь увидит в приложении Сбера новые модели без
    единого слова о причине.
    """

    async def test_verdict_is_postponed(self, hass: HomeAssistant) -> None:
        """Решение откладывается: ни уведомления, ни пометки."""
        entry = _entry(hass, **{CONF_EXPOSED_ENTITIES: KNOWN_DEVICES})

        assert _run(hass, entry) is False
        assert OPTIONS_MODEL_REVISION_KEY not in entry.options

    async def test_notice_arrives_once_the_registry_answers(self, hass: HomeAssistant) -> None:
        """Как только реестр наполнился публикацией, уведомление приходит."""
        entry = _entry(hass, **{CONF_EXPOSED_ENTITIES: KNOWN_DEVICES})
        _run(hass, entry)

        hass.config_entries.async_update_entry(
            entry,
            options={**entry.options, OPTIONS_KEY: KNOWN_DEVICES},
        )

        assert _run(hass, entry) is True
        assert entry.options[OPTIONS_MODEL_REVISION_KEY] == MODEL_IDENTITY_REVISION

    async def test_empty_registry_key_is_an_answer(self, hass: HomeAssistant) -> None:
        """Пустой список в ключе реестра — это ответ «в облаке ничего нет».

        Отличие от отсутствия ключа принципиальное: список записан нами,
        значит реестр работал и сказал, что устройств у Сбера нет.
        Откладывать тут нечего.
        """
        entry = _entry(hass, **{OPTIONS_KEY: [], CONF_EXPOSED_ENTITIES: KNOWN_DEVICES})

        assert _run(hass, entry) is False
        assert entry.options[OPTIONS_MODEL_REVISION_KEY] == MODEL_IDENTITY_REVISION


class TestNotificationIsPerEntry:
    """Два аккаунта Сбера — два уведомления, а не одно на двоих.

    Если тест упадёт, вторая запись затрёт уведомление первой, и человек
    увидит число устройств только одной из своих установок.
    """

    async def test_each_entry_gets_its_own_notification(self, hass: HomeAssistant) -> None:
        """Уведомления обеих записей живут одновременно."""
        first = _entry(hass, **{OPTIONS_KEY: KNOWN_DEVICES})
        second = _entry(hass, **{OPTIONS_KEY: ["light.other"]})

        assert _run(hass, first) is True
        assert _run(hass, second) is True

        notices = _notifications(hass)
        assert migration_notification_id(first) in notices
        assert migration_notification_id(second) in notices
        assert "2 шт." in str(notices[migration_notification_id(first)]["message"])
        assert "1 шт." in str(notices[migration_notification_id(second)]["message"])


class TestStoredRevision:
    """Чтение пометки о ревизии."""

    async def test_missing_revision_reads_as_none(self, hass: HomeAssistant) -> None:
        """Отсутствие ключа — это «ещё не мигрировали»."""
        migration = ModelIdentityMigration(hass, entry := _entry(hass), CloudDeviceRegistry(hass, entry))
        assert migration.stored_revision is None
        assert migration.is_up_to_date is False

    async def test_garbage_revision_reads_as_none(self, hass: HomeAssistant) -> None:
        """Мусор в ключе не выдаётся за ревизию.

        Опции переживают откаты версий и ручные правки ``.storage``:
        строка или ``True`` на месте числа не должны выглядеть как
        «уже мигрировали» и глотать уведомление.
        """
        for garbage in ("2", True, None, [2]):
            entry = _entry(hass, **{OPTIONS_MODEL_REVISION_KEY: garbage})
            migration = ModelIdentityMigration(hass, entry, CloudDeviceRegistry(hass, entry))
            assert migration.stored_revision is None, garbage

    async def test_current_revision_is_up_to_date(self, hass: HomeAssistant) -> None:
        """Актуальная пометка распознаётся и останавливает миграцию."""
        entry = _entry(hass, **{OPTIONS_MODEL_REVISION_KEY: MODEL_IDENTITY_REVISION, OPTIONS_KEY: KNOWN_DEVICES})
        migration = ModelIdentityMigration(hass, entry, CloudDeviceRegistry(hass, entry))
        assert migration.is_up_to_date is True
        assert migration.async_run() is False


@pytest.fixture
def _no_mqtt_reconnect_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    """Отключить бесконечную задачу переподключения MQTT.

    Всё до границы с сетью — загрузка сущностей, запись опций, сама
    миграция — работает по-настоящему.
    """

    async def _noop(self: SberBridge) -> None:
        return

    monkeypatch.setattr(SberBridge, "_mqtt_connection_loop", _noop)


class TestRunsDuringSetup:
    """Миграция выполняется на реальном подъёме записи конфигурации.

    Отдельно от юнит-тестов выше: они проверяют решение, а этот —
    что решение вообще принимается, и до того, как мост начнёт
    публиковать. Если тест упадёт, миграция окажется мёртвым кодом.
    """

    @staticmethod
    def _credentials() -> dict[str, Any]:
        """Минимальные данные записи, достаточные для подъёма моста."""
        return {
            CONF_SBER_LOGIN: "test",
            CONF_SBER_PASSWORD: "pass",
            CONF_SBER_BROKER: "broker.test",
            CONF_SBER_PORT: 8883,
            CONF_SBER_VERIFY_SSL: False,
        }

    async def _setup(self, hass: HomeAssistant, options: dict[str, Any]) -> MockConfigEntry:
        """Поднять интеграцию с заданными опциями и вернуть запись."""
        entry = MockConfigEntry(domain=DOMAIN, data=self._credentials(), options=options, version=3)
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        return entry

    @pytest.mark.usefixtures("_no_mqtt_reconnect_loop")
    async def test_upgrade_notifies_on_setup(self, hass: HomeAssistant) -> None:
        """Обновление с 1.50.0: подъём записи показывает уведомление."""
        entry = await self._setup(
            hass,
            {OPTIONS_KEY: KNOWN_DEVICES, CONF_EXPOSED_ENTITIES: KNOWN_DEVICES},
        )

        assert migration_notification_id(entry) in _notifications(hass)
        assert entry.options[OPTIONS_MODEL_REVISION_KEY] == MODEL_IDENTITY_REVISION
        assert entry.options[OPTIONS_KEY] == KNOWN_DEVICES

        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()

    @pytest.mark.usefixtures("_no_mqtt_reconnect_loop")
    async def test_clean_install_is_silent_on_setup(self, hass: HomeAssistant) -> None:
        """Чистая установка: подъём записи проходит молча."""
        entry = await self._setup(hass, {CONF_EXPOSED_ENTITIES: []})

        assert migration_notification_id(entry) not in _notifications(hass)
        assert entry.options[OPTIONS_MODEL_REVISION_KEY] == MODEL_IDENTITY_REVISION

        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
