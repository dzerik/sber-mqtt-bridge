"""Приводы (``curtain`` / ``window_blind`` / ``gate``) при потере связи.

``open_state`` — обязательная (``✔︎``) функция всех трёх категорий
(:data:`CATEGORY_OBLIGATORY_FEATURES`).  Сбер требует, чтобы ответ на
опрос состояния содержал все объявленные функции устройства, поэтому
пакет ``online=false`` **без** ``open_state`` для облака означает
неисправное устройство: штора пропадает из приложения при первом же
отвале Zigbee и не возвращается до переопубликации конфигурации.

Проект уже принял это правило для датчиков
(``test_devices_simple_sensor.py::
test_obligatory_alarm_state_still_published_when_offline``), здесь оно
распространяется на приводы.

Второй инвариант этого файла — какое именно значение уезжает офлайн:

* последнее известное **состояние покоя** (``open`` / ``close``);
* НИКОГДА ``opening`` / ``closing``: переходное состояние гасит кнопку
  управления в приложении Сбера (проверено на живых воротах), а
  недоступное устройство не порождает событий HA, которыми этот
  «замерший ход» можно было бы сменить;
* ``close``, если положение не сообщалось ни разу — сторона ошибки,
  которая не роняет створку на стоящую под ней машину.

Не проверяется здесь: онлайн-публикация и команды — они в
``test_devices_curtain.py`` / ``test_devices_window_blind.py`` /
``test_devices_impulse_gate.py``.
"""

from __future__ import annotations

from typing import Any

import pytest

from custom_components.sber_mqtt_bridge._generated.obligatory_features import CATEGORY_OBLIGATORY_FEATURES
from custom_components.sber_mqtt_bridge._generated.reference_values import FEATURE_ENUM_VALUES
from custom_components.sber_mqtt_bridge.devices.base_entity import BaseEntity
from custom_components.sber_mqtt_bridge.devices.curtain import CurtainEntity
from custom_components.sber_mqtt_bridge.devices.gate import (
    GateEntity,
    ImpulseGateEntity,
    make_gate_entity,
)
from custom_components.sber_mqtt_bridge.devices.window_blind import WindowBlindEntity

RELAY = "switch.gate_relay"
"""entity_id импульсного реле для :class:`ImpulseGateEntity`."""

CONTACT = "binary_sensor.gate_contact"
"""entity_id геркона, связанного ролью ``open_state``."""

TRANSITIONAL = ("opening", "closing")
"""Значения ``open_state``, гасящие кнопку управления в приложении Сбера."""

OFFLINE_STATES = ("unavailable", "unknown")
"""HA-состояния, которые мост обязан трактовать как «связи нет»."""

COVER_CLASSES: tuple[tuple[str, type[CurtainEntity], str], ...] = (
    ("curtain", CurtainEntity, "cover.curtain"),
    ("window_blind", WindowBlindEntity, "cover.blind"),
    ("gate", GateEntity, "cover.gate"),
)
"""Классы приводов на базе ``cover``: (категория Sber, класс, entity_id)."""


def cover_state(entity: BaseEntity, key: str) -> Any:
    """Достать значение опубликованной функции.

    Args:
        entity: Заполненная сущность.
        key: Имя функции Sber.

    Returns:
        Словарь ``value`` функции либо ``None``, если её нет в пакете.
    """
    states = entity.to_sber_current_state()[entity.entity_id]["states"]
    for item in states:
        if str(item["key"]) == key:
            return item["value"]
    return None


def cover_keys(entity: BaseEntity) -> list[str]:
    """Вернуть имена всех опубликованных функций.

    Args:
        entity: Заполненная сущность.

    Returns:
        Список ключей в порядке публикации.
    """
    return [str(item["key"]) for item in entity.to_sber_current_state()[entity.entity_id]["states"]]


def make_cover(cls: type[CurtainEntity], entity_id: str) -> CurtainEntity:
    """Собрать привод на базе HA ``cover``.

    Args:
        cls: Класс привода.
        entity_id: entity_id HA-сущности.

    Returns:
        Пустая (ещё не заполненная состоянием) сущность.
    """
    return cls({"entity_id": entity_id, "name": "Привод"})


def feed(entity: CurtainEntity, state: str, position: int | None = None) -> None:
    """Скормить приводу HA-состояние.

    Args:
        entity: Сущность привода.
        state: Значение ``state`` HA-сущности.
        position: ``current_position``; ``None`` — атрибут не передаётся.
    """
    attrs: dict[str, Any] = {}
    if position is not None:
        attrs["current_position"] = position
    entity.fill_by_ha_state({"entity_id": entity.entity_id, "state": state, "attributes": attrs})


def make_impulse_gate(contact: str | None = "off") -> ImpulseGateEntity:
    """Собрать импульсные ворота с герконом и включённой эмуляцией хода.

    Args:
        contact: Состояние геркона; ``None`` — показаний ещё не было.

    Returns:
        Готовая к публикации сущность.
    """
    entity = make_gate_entity({"entity_id": RELAY, "name": "Ворота"})
    assert isinstance(entity, ImpulseGateEntity)
    entity.apply_gate_options({"travel_time": 20})
    entity.fill_by_ha_state({"entity_id": RELAY, "state": "off", "attributes": {}})
    entity.register_link("open_state", CONTACT)
    if contact is not None:
        entity.update_linked_data("open_state", {"entity_id": CONTACT, "state": contact, "attributes": {}})
    return entity


class TestObligatoryOpenStateSurvivesDropout:
    """``open_state`` не исчезает из пакета вместе со связью."""

    @pytest.mark.parametrize(("category", "cls", "entity_id"), COVER_CLASSES, ids=[c[0] for c in COVER_CLASSES])
    @pytest.mark.parametrize("offline", OFFLINE_STATES)
    def test_offline_publish_carries_open_state(
        self, category: str, cls: type[CurtainEntity], entity_id: str, offline: str
    ) -> None:
        """Недоступный привод публикует ``online=false`` И ``open_state``.

        Если тест упадёт, пользователь при первом же отвале Zigbee
        увидит, как штора/ворота пропадают из приложения Сбера: облако
        отбрасывает устройство, чей ответ не содержит обязательной
        функции категории, и обратно оно само не вернётся.
        """
        assert "open_state" in CATEGORY_OBLIGATORY_FEATURES[category]

        entity = make_cover(cls, entity_id)
        feed(entity, "open", 80)
        feed(entity, offline)

        assert cover_state(entity, "online") == {"type": "BOOL", "bool_value": False}
        assert cover_state(entity, "open_state") is not None

    @pytest.mark.parametrize(("category", "cls", "entity_id"), COVER_CLASSES, ids=[c[0] for c in COVER_CLASSES])
    def test_offline_publish_keeps_last_known_position(
        self, category: str, cls: type[CurtainEntity], entity_id: str
    ) -> None:
        """Офлайн уезжает последнее известное положение, а не выдуманное.

        Иначе открытая штора, потерявшая связь, отрапортует «закрыта»:
        в приложении она нарисуется закрытой, а голосовой сценарий
        «закрой шторы» решит, что делать нечего.
        """
        entity = make_cover(cls, entity_id)
        feed(entity, "open", 80)
        feed(entity, "unavailable")

        assert cover_state(entity, "open_state") == {"type": "ENUM", "enum_value": "open"}

    @pytest.mark.parametrize(("category", "cls", "entity_id"), COVER_CLASSES, ids=[c[0] for c in COVER_CLASSES])
    def test_offline_publish_without_any_history_reports_close(
        self, category: str, cls: type[CurtainEntity], entity_id: str
    ) -> None:
        """Привод, не сообщавший положения ни разу, публикует ``close``.

        Молчать нельзя (функция обязательная), а из двух состояний покоя
        безопасно только ``close``: пользователь, поверивший ложному
        ``close``, отправит «открыть» — в худшем случае откроются уже
        открытые ворота.  Поверивший ложному ``open`` отправит
        «закрыть» — на стоящую под воротами машину.
        """
        entity = make_cover(cls, entity_id)
        feed(entity, "unavailable")

        assert cover_state(entity, "open_state") == {"type": "ENUM", "enum_value": "close"}

    @pytest.mark.parametrize(("category", "cls", "entity_id"), COVER_CLASSES, ids=[c[0] for c in COVER_CLASSES])
    def test_offline_publish_never_reports_movement(
        self, category: str, cls: type[CurtainEntity], entity_id: str
    ) -> None:
        """Привод, пропавший на ходу, публикует покой, а не ``opening``/``closing``.

        Переходное состояние гасит кнопку управления в приложении Сбера
        (проверено на живом оборудовании), а недоступное устройство не
        порождает событий HA — «замерший ход» некому сменить, и
        управление шторой/воротами из приложения пропадает до
        восстановления связи.
        """
        for moving, resting in (("opening", 30), ("closing", 30)):
            entity = make_cover(cls, entity_id)
            feed(entity, "closed", 0)
            feed(entity, moving, resting)
            assert cover_state(entity, "open_state")["enum_value"] in TRANSITIONAL

            feed(entity, "unavailable")
            assert cover_state(entity, "open_state")["enum_value"] not in TRANSITIONAL

    @pytest.mark.parametrize(("category", "cls", "entity_id"), COVER_CLASSES, ids=[c[0] for c in COVER_CLASSES])
    def test_offline_publish_omits_the_position_reading(
        self, category: str, cls: type[CurtainEntity], entity_id: str
    ) -> None:
        """Процент открытия офлайн не публикуется вовсе.

        ``open_percentage`` — не обязательная функция, а измерение; у
        недоступного привода его нет.  Публиковать вместо него ноль —
        то же самое, что писать 0 °C в историю отвалившегося
        термометра (issue #63); молчание оставляет в облаке последнее
        настоящее значение.
        """
        entity = make_cover(cls, entity_id)
        feed(entity, "open", 80)
        feed(entity, "unavailable")

        assert "open_percentage" not in cover_keys(entity)

    @pytest.mark.parametrize(("category", "cls", "entity_id"), COVER_CLASSES, ids=[c[0] for c in COVER_CLASSES])
    def test_published_open_state_is_a_documented_value(
        self, category: str, cls: type[CurtainEntity], entity_id: str
    ) -> None:
        """Любое опубликованное ``open_state`` есть в справочнике Sber.

        Недокументированное значение облако не маршрутизирует: команда
        от Салюта до устройства не доходит.
        """
        for state, position in (("open", 80), ("closed", 0), ("opening", 40), ("closing", 40), ("unavailable", None)):
            entity = make_cover(cls, entity_id)
            feed(entity, "open", 80)
            feed(entity, state, position)
            assert cover_state(entity, "open_state")["enum_value"] in FEATURE_ENUM_VALUES["open_state"]


class TestImpulseGateOfflineOpenState:
    """Импульсные ворота: офлайн-публикация не показывает движение."""

    def test_offline_mid_travel_publishes_resting_position(self) -> None:
        """Реле пропало во время эмулируемого хода — уезжает покой.

        Эмуляция хода живёт по таймеру и продолжает считать себя
        актуальной, но публиковать её недоступному устройству нельзя:
        в приложении Сбера ``opening`` гасит кнопку, а событий HA,
        которыми это состояние можно было бы сменить, у пропавшего реле
        не будет — пользователь останется без управления воротами.
        """
        entity = make_impulse_gate(contact="off")
        entity._start_travel()
        assert cover_state(entity, "open_state")["enum_value"] == "opening"

        entity.fill_by_ha_state({"entity_id": RELAY, "state": "unavailable", "attributes": {}})

        assert cover_state(entity, "online") == {"type": "BOOL", "bool_value": False}
        assert cover_state(entity, "open_state") == {"type": "ENUM", "enum_value": "close"}

    def test_offline_keeps_last_known_open_position(self) -> None:
        """Открытые ворота, потерявшие реле, остаются открытыми.

        Иначе после отвала реле приложение покажет закрытые ворота, а
        команда «закрой» станет для пользователя недоступной ровно
        тогда, когда створка действительно открыта.
        """
        entity = make_impulse_gate(contact="on")
        assert cover_state(entity, "open_state")["enum_value"] == "open"

        entity.fill_by_ha_state({"entity_id": RELAY, "state": "unavailable", "attributes": {}})

        assert cover_state(entity, "open_state") == {"type": "ENUM", "enum_value": "open"}

    def test_travel_resumes_when_the_relay_comes_back(self) -> None:
        """Возврат связи внутри окна хода снова показывает движение.

        Офлайн-подмена значения — только про публикацию: сама эмуляция
        не отменяется, иначе вернувшиеся ворота отрапортовали бы покой
        посреди реально едущей створки.
        """
        entity = make_impulse_gate(contact="off")
        entity._start_travel()
        entity.fill_by_ha_state({"entity_id": RELAY, "state": "unavailable", "attributes": {}})
        assert cover_state(entity, "open_state")["enum_value"] == "close"

        entity.fill_by_ha_state({"entity_id": RELAY, "state": "off", "attributes": {}})

        assert cover_state(entity, "open_state") == {"type": "ENUM", "enum_value": "opening"}

    def test_offline_publish_still_carries_open_state(self) -> None:
        """Геркон не сообщал ничего — ``open_state`` всё равно в пакете.

        Ворота без показаний геркона считаются офлайн; если в этот
        момент выпадет обязательная функция, облако отбросит устройство
        целиком, и пользователь не увидит ворот вообще.
        """
        entity = make_impulse_gate(contact=None)

        assert cover_state(entity, "online") == {"type": "BOOL", "bool_value": False}
        assert cover_state(entity, "open_state") == {"type": "ENUM", "enum_value": "close"}
