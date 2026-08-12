"""Жёсткие юнит-тесты ``ImpulseGateEntity`` и фабрики ``make_gate_entity`` (issue #53).

Категория Sber ``gate``, собранная из пары «импульсное реле (switch/button/
script) + геркон (binary_sensor)».  Физически это ОДНА кнопка, а Sber шлёт
направленную команду ``open_set=open|close`` — поэтому здесь проверяются не
«счастливые пути», а ровно те инварианты, нарушение которых в проде означает
либо молчаливый отказ облака Sber принять устройство, либо закрытие ворот на
стоящую под ними машину:

* точный (а не «содержит») состав ``features`` и ``allowed_values``;
* ``open_state`` присутствует в публикации ВСЕГДА (обязательная фича категории);
* положение створки берётся ТОЛЬКО из геркона, состояние реле не читается;
* направленная команда, совпадающая с текущим положением, не даёт НИ ОДНОГО
  сервисного вызова;
* антидребезг на инъектируемых часах (без ``asyncio.sleep`` и без ``freezegun``).

Ожидания выведены из спеки Sber (``_generated/obligatory_features.py``,
``_generated/category_features.py``, ``_generated/feature_types.py``) и из
дизайна issue #53, а не из текущего вывода кода.
"""

from __future__ import annotations

import logging
import time

import pytest

from custom_components.sber_mqtt_bridge.devices.base_entity import (
    ALL_LINKABLE_ROLES,
    ROLE_OPEN_STATE,
    ROLE_SIGNAL,
    BaseEntity,
    resolve_link_role_for,
)
from custom_components.sber_mqtt_bridge.devices.gate import (
    GateEntity,
    ImpulseGateEntity,
    make_gate_entity,
)
from custom_components.sber_mqtt_bridge.sber_models import missing_obligatory_features
from custom_components.sber_mqtt_bridge.schema_validator import validate_publish

GATE_LOGGER = "custom_components.sber_mqtt_bridge.devices.gate"
"""Логгер модуля ворот — по нему ловятся WARNING про отсутствующий геркон."""

CONTACT_ID = "binary_sensor.gate_contact"
"""Связанный геркон в роли ``open_state``."""

EXPECTED_FEATURES = ["online", "open_set", "open_state"]
"""Полный набор фич импульсных ворот без связанных датчиков.

``open_percentage`` отсутствует намеренно: у импульсного привода нет
позиции, а спека Sber помечает эту фичу условной.  ``stop``/battery в
модели ворот нет вовсе."""

EXPECTED_ALLOWED_VALUES = {
    "open_set": {"type": "ENUM", "enum_values": {"values": ["open", "close"]}},
}
"""Единственный allowed_values ворот. ``stop`` не объявляем — одна кнопка
не умеет останавливать створку, а объявленное значение породит голосовую
команду «останови ворота», которая молча ничего не сделает."""

COMMAND_ONLY_FEATURES = frozenset({"open_set"})
"""Фичи, которые устройство принимает командой, но не публикует в состоянии.

Единственная такая фича ворот — ``open_set``: створка не имеет позиции,
поэтому подтверждением команды служит ``open_state``, а не эхо самой
команды.  Белый список намеренно закрытый: любая другая объявленная,
но не публикуемая фича — это регулятор в приложении Sber, который
никогда не покажет значение."""

IMPULSE_BY_DOMAIN = {
    "switch": ("switch", "toggle"),
    "button": ("button", "press"),
    "input_button": ("input_button", "press"),
    "script": ("script", "turn_on"),
}
"""Домен первичной сущности → (домен, сервис) импульса."""


class FakeClock:
    """Детерминированные монотонные часы для антидребезга.

    Заменяет ``ImpulseGateEntity._now``; тесты двигают время вручную,
    поэтому ни один тест не спит и не зависит от реального таймера.
    """

    def __init__(self, start: float = 0.0) -> None:
        """Запомнить стартовое «время» и обнулить счётчик обращений."""
        self.now = start
        self.calls = 0

    def __call__(self) -> float:
        """Вернуть текущее «время» и посчитать обращение."""
        self.calls += 1
        return self.now

    def advance(self, delta: float) -> None:
        """Сдвинуть часы вперёд на ``delta`` секунд."""
        self.now += delta


def make_impulse_gate(
    entity_id: str = "switch.gate",
    *,
    state: str | None = "off",
    attributes: dict | None = None,
    options: dict | None = None,
    link: bool = True,
    contact: str | None = None,
    clock: FakeClock | None = None,
) -> ImpulseGateEntity:
    """Собрать импульсные ворота в нужном состоянии.

    Args:
        entity_id: entity_id импульсного реле (первичная сущность).
        state: HA-состояние реле; ``None`` — сущность ещё не заполнена.
        attributes: HA-атрибуты реле.
        options: Опции ``gate_options`` (``invert_contact`` / ``impulse_service``).
        link: Регистрировать ли связь с герконом в роли ``open_state``.
        contact: HA-состояние геркона (``None`` — данных ещё не было).
        clock: Фейковые часы для антидребезга.

    Returns:
        Готовая к проверкам сущность.
    """
    entity = ImpulseGateEntity({"entity_id": entity_id, "name": "Gate"})
    if clock is not None:
        entity._now = clock
    if options is not None:
        entity.apply_gate_options(options)
    if link:
        entity.register_link("open_state", CONTACT_ID)
    if state is not None:
        entity.fill_by_ha_state({"entity_id": entity_id, "state": state, "attributes": attributes or {}})
    if contact is not None:
        entity.update_linked_data("open_state", {"entity_id": CONTACT_ID, "state": contact})
    return entity


def states_map(entity: BaseEntity) -> dict[str, dict]:
    """Вернуть публикуемое состояние как ``{feature_key: value_dict}``.

    Заодно фиксирует, что публикация адресована ровно одному Sber-устройству
    (геркон не должен превращаться во второе устройство) и что ключи не
    дублируются.
    """
    payload = entity.to_sber_current_state()
    assert set(payload) == {entity.entity_id}
    states = payload[entity.entity_id]["states"]
    keys = [s["key"] for s in states]
    assert len(keys) == len(set(keys)), f"дублирующиеся ключи в публикации: {keys}"
    return {s["key"]: s["value"] for s in states}


def open_set_cmd(enum_value: str) -> dict:
    """Собрать Sber-команду ``open_set`` с ENUM-значением."""
    return {"states": [{"key": "open_set", "value": {"type": "ENUM", "enum_value": enum_value}}]}


def service_calls(results: list[dict]) -> list[dict]:
    """Оставить из результата ``process_cmd`` только сервисные вызовы."""
    return [r for r in results if "url" in r]


# ---------------------------------------------------------------------------
#  Модель устройства: features / allowed_values
# ---------------------------------------------------------------------------


class TestModel:
    """Состав модели, публикуемой в конфиге Sber."""

    def test_features_exact_without_links(self):
        """Набор фич обязан быть РОВНО online+open_set+open_state.

        Любая лишняя фича (например возвращённый ``open_percentage``)
        создаёт в приложении Sber неработающий регулятор позиции, а
        любая недостающая — обязательную фичу теряет и облако молча
        выбрасывает устройство.
        """
        entity = make_impulse_gate(contact="off")
        features = entity.get_final_features_list()
        assert sorted(features) == EXPECTED_FEATURES
        assert len(features) == len(EXPECTED_FEATURES), f"дубликаты в features: {features}"

    def test_open_percentage_and_battery_never_advertised(self):
        """Ни позиции, ни батарейки в модели ворот быть не может.

        В спеке ``gate`` батарейных фич нет вовсе, а позиция у импульсного
        привода недостижима: объявив её, мы получим команды
        ``open_percentage``, которые нечем исполнить.
        """
        entity = make_impulse_gate(contact="on", attributes={"battery": 42, "battery_level": 42})
        entity.update_linked_data("battery", {"state": "42"})
        entity.update_linked_data("battery_low", {"state": "on"})
        features = set(entity.get_final_features_list())
        forbidden = {
            "open_percentage",
            "open_rate",
            "open_left_percentage",
            "open_right_percentage",
            "battery_percentage",
            "battery_low_power",
            "on_off",
        }
        assert features & forbidden == set()

    def test_battery_data_never_leaks_into_states(self):
        """Батарейные значения не должны попадать в публикацию состояния.

        Даже если пользователь связал батарейный сенсор, публикация
        ``battery_percentage`` при необъявленной фиче — это ``not_declared``
        в валидаторе и повод для Sber проигнорировать пакет.
        """
        entity = make_impulse_gate(contact="on")
        entity.update_linked_data("battery", {"state": "7"})
        entity.update_linked_data("battery_low", {"state": "on"})
        assert set(states_map(entity)) == {"online", "open_state"}
        # Проверка и до фильтра необъявленных ключей: полагаться на то, что
        # фильтр вырежет батарейку, нельзя — стоит пользователю добавить
        # battery_percentage через extra_features, и в облако уйдёт
        # выдуманное значение вместе с рассинхроном модели.
        raw = entity._build_current_state()
        assert {s["key"] for s in raw[entity.entity_id]["states"]} == {"online", "open_state"}

    def test_features_gain_signal_strength_when_linked(self):
        """Связанный датчик сигнала добавляет ровно одну фичу.

        Если ``signal_strength`` не появится — пользователь не увидит
        качество связи; если появится что-то ещё — модель разъедется с
        публикуемым состоянием.
        """
        entity = make_impulse_gate(contact="off")
        entity.update_linked_data("signal_strength", {"state": "-60"})
        assert sorted(entity.get_final_features_list()) == [*EXPECTED_FEATURES, "signal_strength"]

    def test_signal_strength_state_value_is_exact_enum(self):
        """RSSI −60 обязан публиковаться как ENUM ``medium``.

        Ошибка конвертации даст Sber неизвестное enum-значение — это
        отклонение всего пакета состояния.
        """
        entity = make_impulse_gate(contact="off")
        entity.update_linked_data("signal_strength", {"state": "-60"})
        assert states_map(entity)["signal_strength"] == {"type": "ENUM", "enum_value": "medium"}

    def test_allowed_values_exact(self):
        """allowed_values обязан быть РОВНО open/close.

        Появление ``stop`` включит в приложении и в голосовом ассистенте
        команду остановки, которую железо выполнить не может.
        """
        entity = make_impulse_gate(contact="off")
        assert entity.create_allowed_values_list() == EXPECTED_ALLOWED_VALUES

    def test_allowed_values_dropped_when_open_set_removed(self):
        """Удалив ``open_set`` через override, нельзя оставить осиротевший allowed_values.

        Пара «фичи без allowed_values» / «allowed_values без фичи»
        отбраковывается pydantic-валидатором, и устройство исчезает из
        конфигурационного пакета целиком.
        """
        entity = make_impulse_gate(contact="off")
        entity.removed_features = ["open_set"]
        assert entity.create_allowed_values_list() == {}
        assert sorted(entity.get_final_features_list()) == ["online", "open_state"]

    def test_model_descriptor_matches_features_and_allowed_values(self):
        """Конфиг устройства обязан объявлять категорию gate и тот же набор.

        Расхождение ``model.features`` с публикуемым состоянием — прямой
        путь к молчаливому отказу облака.
        """
        entity = make_impulse_gate(contact="off")
        descriptor = entity.to_sber_state()["model"]
        assert descriptor["category"] == "gate"
        assert sorted(descriptor["features"]) == EXPECTED_FEATURES
        assert descriptor["allowed_values"] == EXPECTED_ALLOWED_VALUES

    def test_no_obligatory_feature_missing(self):
        """Обязательные фичи категории gate (online, open_state) обязаны быть объявлены.

        Их отсутствие — самая частая причина «устройство добавилось и
        сразу пропало» в облаке Sber.
        """
        entity = make_impulse_gate(contact="off")
        assert missing_obligatory_features("gate", set(entity.get_final_features_list())) == set()

    @pytest.mark.parametrize("with_signal", [False, True])
    def test_validate_publish_is_clean(self, with_signal):
        """Валидатор публикации не должен находить НИ ОДНОЙ проблемы.

        Ловит сразу четыре класса дефектов: недостающие обязательные
        фичи, неизвестные категории ключи, неверный тип значения и
        публикацию необъявленного ключа.
        """
        entity = make_impulse_gate(contact="on")
        if with_signal:
            entity.update_linked_data("signal_strength", {"state": "-80"})
        payload = entity.to_sber_current_state()
        issues = validate_publish(
            entity_id=entity.entity_id,
            category="gate",
            states=payload[entity.entity_id]["states"],
            declared_features=entity.get_final_features_list(),
        )
        assert [f"{i.type}:{i.key}" for i in issues] == []

    @pytest.mark.parametrize("with_signal", [False, True])
    def test_every_declared_feature_is_actually_published(self, with_signal):
        """Каждая объявленная фича обязана иметь значение в публикации.

        Обратное направление к
        :meth:`TestPublishedState.test_published_keys_are_subset_of_declared_features`
        — и как раз его ``validate_publish`` не проверяет: валидатор
        ловит «опубликовано, но не объявлено», а не «объявлено, но
        никогда не публикуется».  Между тем для ворот опасен именно
        второй вариант: объявив, например, ``open_percentage``, мы
        получим в приложении Sber вечно пустой регулятор позиции и
        команды, которые нечем исполнить.  Проверка идёт по смыслу
        («у импульсного привода нет позиции»), а не по списку-хардкоду.
        """
        entity = make_impulse_gate(contact="on")
        if with_signal:
            entity.update_linked_data("signal_strength", {"state": "-80"})
        declared = set(entity.get_final_features_list())
        published = set(states_map(entity))
        assert declared - published - COMMAND_ONLY_FEATURES == set()


# ---------------------------------------------------------------------------
#  Публикуемое состояние
# ---------------------------------------------------------------------------


class TestPublishedState:
    """``open_state`` и ``online`` в публикации состояния."""

    @pytest.mark.parametrize(
        ("descr", "kwargs"),
        [
            ("нет связи с герконом", {"link": False}),
            ("связь есть, данных ещё не было", {"link": True}),
            ("реле недоступно", {"link": True, "state": "unavailable", "contact": "on"}),
            ("реле не заполнено состоянием", {"link": True, "state": None}),
        ],
    )
    def test_open_state_published_always(self, descr, kwargs):
        """``open_state`` обязателен и публикуется в любой ситуации.

        ``_filter_undeclared_states`` молча вырезает недекларированные
        ключи, а условная публикация обязательной фичи = устройство
        периодически «пропадает» из облака.  Матрица покрывает и
        offline-случаи (нет связи, нет данных, реле недоступно).
        """
        entity = make_impulse_gate(**kwargs)
        assert "open_state" in states_map(entity), descr

    def test_published_keys_are_subset_of_declared_features(self):
        """Публикация не должна содержать ключей вне объявленных фич.

        Иначе Sber отказывается маршрутизировать значение (issue #44),
        а фильтр в базовом классе выбросит его молча.
        """
        entity = make_impulse_gate(contact="on")
        entity.update_linked_data("signal_strength", {"state": "-30"})
        assert set(states_map(entity)) <= set(entity.get_final_features_list())
        assert set(states_map(entity)) == {"online", "open_state", "signal_strength"}

    def test_no_link_publishes_close_and_warns_once(self, caplog):
        """Без геркона положение неизвестно — публикуем ``close`` и предупреждаем.

        Соврать «открыто» опаснее, чем «закрыто»: пользователь уедет,
        считая ворота закрытыми.  Предупреждение обязано быть ровно
        одно на сущность, иначе оно зальёт лог на каждой публикации.
        """
        entity = make_impulse_gate(link=False)
        with caplog.at_level(logging.WARNING, logger=GATE_LOGGER):
            assert states_map(entity)["open_state"] == {"type": "ENUM", "enum_value": "close"}
            first = [r for r in caplog.records if r.levelno >= logging.WARNING]
            assert len(first) == 1
            assert "switch.gate" in first[0].getMessage()
            caplog.clear()
            states_map(entity)
            assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []

    def test_linked_but_silent_contact_reports_offline(self, caplog):
        """Геркон связан, но ни разу не отчитался → устройство offline.

        Показать «online + закрыто» для неизвестного положения — прямая
        ложь; лучше честный offline до первого события контакта.
        Предупреждения при этом быть не должно: связь ведь настроена.
        """
        entity = make_impulse_gate(link=True)
        with caplog.at_level(logging.WARNING, logger=GATE_LOGGER):
            state = states_map(entity)
        assert state["online"] == {"type": "BOOL", "bool_value": False}
        assert state["open_state"] == {"type": "ENUM", "enum_value": "close"}
        assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []

    def test_online_true_after_first_contact_reading(self):
        """После первого показания геркона ворота выходят в online."""
        entity = make_impulse_gate(contact="on")
        assert states_map(entity)["online"] == {"type": "BOOL", "bool_value": True}

    def test_relay_unavailable_forces_offline(self):
        """Недоступное реле = offline, даже если геркон исправно отвечает.

        Управлять воротами нечем, и Sber должен об этом знать.
        """
        entity = make_impulse_gate(state="unavailable", contact="on")
        assert states_map(entity)["online"] == {"type": "BOOL", "bool_value": False}

    def test_switch_in_unknown_state_is_offline(self):
        """``switch`` в состоянии ``unknown`` — это недоступное реле."""
        entity = make_impulse_gate(state="unknown", contact="on")
        assert states_map(entity)["online"] == {"type": "BOOL", "bool_value": False}

    def test_button_in_unknown_state_stays_online(self):
        """``button`` всегда ``unknown`` до первого нажатия — это не offline.

        Иначе ворота на кнопке навсегда останутся недоступными в Sber.
        """
        entity = make_impulse_gate("button.gate", state="unknown", contact="on")
        assert states_map(entity)["online"] == {"type": "BOOL", "bool_value": True}

    def test_no_link_stays_online(self):
        """Без геркона реле всё ещё управляемо, поэтому online=true."""
        entity = make_impulse_gate(link=False)
        assert states_map(entity)["online"] == {"type": "BOOL", "bool_value": True}


# ---------------------------------------------------------------------------
#  Полярность геркона
# ---------------------------------------------------------------------------


class TestContactPolarity:
    """Единственный источник положения створки — связанный геркон."""

    @pytest.mark.parametrize(
        ("invert", "raw", "expected"),
        [
            (False, "on", "open"),
            (False, "off", "close"),
            (False, "closed", "close"),
            (False, "ON", "close"),
            (True, "on", "close"),
            (True, "off", "open"),
            (True, "closed", "open"),
        ],
    )
    def test_polarity_matrix(self, invert, raw, expected):
        """Определённое показание геркона однозначно задаёт ``open_state``.

        По умолчанию ``on`` = открыто (так отдают Z2M-discovery и
        ZHA-квирк для TS0601/TS0603); флаг ``invert_contact`` разворачивает
        трактовку для самодельных шаблонных сенсоров.  Любое значение,
        отличное от ``on``, считается «контакт не сработал» — регистр и
        синонимы не угадываются.
        """
        entity = make_impulse_gate(options={"invert_contact": invert}, contact=raw)
        assert states_map(entity)["open_state"] == {"type": "ENUM", "enum_value": expected}
        assert entity.is_online is True

    @pytest.mark.parametrize("invert", [False, True])
    @pytest.mark.parametrize("bad", ["unknown", "unavailable", None])
    def test_undefined_reading_holds_last_known_position(self, invert, bad):
        """``unknown``/``unavailable``/отсутствие значения не меняют положение.

        Потерять управление воротами хуже, чем показать чуть устаревшее
        положение, поэтому последнее известное значение удерживается, а
        факт протухания виден в диагностике через ``contact_stale``.
        """
        first = "off" if invert else "on"
        entity = make_impulse_gate(options={"invert_contact": invert}, contact=first)
        assert states_map(entity)["open_state"]["enum_value"] == "open"
        assert entity.contact_stale is False

        entity.update_linked_data("open_state", {"state": bad})
        assert states_map(entity)["open_state"]["enum_value"] == "open"
        assert entity.contact_stale is True
        assert states_map(entity)["online"]["bool_value"] is True

    @pytest.mark.parametrize("bad", ["unknown", "unavailable", None])
    def test_undefined_reading_before_first_value_keeps_offline(self, bad):
        """Протухшее показание не считается «контакт виден».

        Иначе после единственного ``unavailable`` ворота отрапортуют
        online + «закрыто», хотя положение никто не измерял.
        """
        entity = make_impulse_gate(link=True)
        entity.update_linked_data("open_state", {"state": bad})
        state = states_map(entity)
        assert state["online"] == {"type": "BOOL", "bool_value": False}
        assert state["open_state"] == {"type": "ENUM", "enum_value": "close"}
        assert entity.contact_stale is True

    def test_fresh_reading_clears_stale_flag(self):
        """Новое валидное показание снимает признак протухания."""
        entity = make_impulse_gate(contact="on")
        entity.update_linked_data("open_state", {"state": "unavailable"})
        assert entity.contact_stale is True
        entity.update_linked_data("open_state", {"state": "off"})
        assert entity.contact_stale is False
        assert states_map(entity)["open_state"]["enum_value"] == "close"

    def test_relay_own_state_is_never_a_position(self):
        """Состояние самого реле не должно влиять на ``open_state``.

        Реле «залипает» в ``on`` после импульса — если читать его как
        положение, ворота навсегда останутся «открытыми» и защитный гард
        перестанет их открывать.
        """
        entity = make_impulse_gate(state="on", contact="off")
        assert states_map(entity)["open_state"]["enum_value"] == "close"
        entity.fill_by_ha_state({"entity_id": "switch.gate", "state": "on", "attributes": {}})
        assert states_map(entity)["open_state"]["enum_value"] == "close"

    def test_impulse_does_not_optimistically_flip_position(self):
        """Отправленный импульс сам по себе не меняет публикуемое положение.

        Единственный источник истины — геркон; оптимистичное «уже открыто»
        снимет гард и позволит второй команде закрыть ворота на машину.
        """
        entity = make_impulse_gate(contact="off", clock=FakeClock())
        assert service_calls(entity.process_cmd(open_set_cmd("open")))
        assert states_map(entity)["open_state"]["enum_value"] == "close"

    def test_signal_role_is_delegated_to_mixin(self):
        """Роли, кроме ``open_state``, обязаны уходить в базовый миксин.

        Регресс на ``super().update_linked_data`` — потеряв делегирование,
        мы потеряем и качество связи, и все будущие роли.
        """
        entity = make_impulse_gate(contact="off")
        entity.update_linked_data("signal_strength", {"state": "-45"})
        assert states_map(entity)["signal_strength"] == {"type": "ENUM", "enum_value": "high"}
        assert states_map(entity)["open_state"]["enum_value"] == "close"

    def test_signal_strength_from_primary_attributes(self):
        """Заявленные ``ATTR_SPECS`` обязаны реально применяться к атрибутам реле.

        Класс декларирует ``ATTR_SPECS`` с ``preserve_on_missing`` ради
        разбора ``linkquality``/``rssi`` первичной сущности; если специи
        не применяются, декларация — мёртвый код, и Zigbee-реле, несущее
        ``linkquality`` в атрибутах, никогда не покажет качество связи.
        """
        entity = make_impulse_gate(contact="off", attributes={"linkquality": -60})
        assert "signal_strength" in entity.get_final_features_list()
        assert states_map(entity)["signal_strength"] == {"type": "ENUM", "enum_value": "medium"}


# ---------------------------------------------------------------------------
#  Команды: домен × команда × текущее положение
# ---------------------------------------------------------------------------


class TestCommandMatrix:
    """Диспетчеризация ``open_set`` по домену первички и по положению створки."""

    @pytest.mark.parametrize("domain", sorted(IMPULSE_BY_DOMAIN))
    @pytest.mark.parametrize(
        ("contact", "action", "expect_impulse"),
        [
            (None, "open", True),
            (None, "close", True),
            ("off", "open", True),
            ("off", "close", False),
            ("on", "open", False),
            ("on", "close", True),
        ],
    )
    def test_domain_command_position_matrix(self, domain, contact, action, expect_impulse):
        """Импульс шлётся только когда запрошенное направление ещё не достигнуто.

        У железа одна кнопка: команда «открыть» на уже открытых воротах
        физически означает «закрыть».  Пока положение неизвестно (геркон
        молчит), реле обязано оставаться управляемым.
        """
        entity = make_impulse_gate(f"{domain}.gate", state="off", contact=contact, clock=FakeClock())
        results = entity.process_cmd(open_set_cmd(action))
        calls = service_calls(results)
        if not expect_impulse:
            assert calls == []
            assert results == [{"update_state": True}]
            return
        expected_domain, expected_service = IMPULSE_BY_DOMAIN[domain]
        assert results == [
            {
                "url": {
                    "type": "call_service",
                    "domain": expected_domain,
                    "service": expected_service,
                    "target": {"entity_id": f"{domain}.gate"},
                }
            }
        ]

    def test_open_when_already_open_makes_no_service_call(self):
        """КЛЮЧЕВОЙ ТЕСТ БЕЗОПАСНОСТИ: «открой» на открытых воротах — ноль вызовов.

        Без этого гарда «Салют, открой ворота» при открытых воротах
        отправит импульс, и створка поедет ВНИЗ — возможно, на стоящую
        под ней машину.
        """
        entity = make_impulse_gate(contact="on", clock=FakeClock())
        results = entity.process_cmd(open_set_cmd("open"))
        assert service_calls(results) == []
        assert results == [{"update_state": True}]

    def test_close_when_already_closed_makes_no_service_call(self):
        """Симметрично: «закрой» на закрытых воротах не даёт импульса.

        Иначе повторная команда откроет ворота, о чём пользователь не
        узнает.
        """
        entity = make_impulse_gate(contact="off", clock=FakeClock())
        results = entity.process_cmd(open_set_cmd("close"))
        assert service_calls(results) == []
        assert results == [{"update_state": True}]

    def test_guard_with_inverted_contact(self):
        """Гард обязан учитывать инверсию геркона.

        При ``invert_contact=True`` ``on`` означает «закрыто», и команда
        «закрой» не должна давать импульс — иначе инверсия превращает
        защиту в свою противоположность.
        """
        entity = make_impulse_gate(options={"invert_contact": True}, contact="on", clock=FakeClock())
        assert entity.process_cmd(open_set_cmd("close")) == [{"update_state": True}]
        assert service_calls(entity.process_cmd(open_set_cmd("open"))) != []

    def test_guard_does_not_arm_cooldown(self):
        """Подтверждение без импульса не должно запускать антидребезг.

        Иначе «открой» на открытых воротах (ноль вызовов) заблокирует
        следующую за ней настоящую команду «закрой».
        """
        clock = FakeClock()
        entity = make_impulse_gate(contact="on", clock=clock)
        assert entity.process_cmd(open_set_cmd("open")) == [{"update_state": True}]
        clock.advance(0.05)
        assert len(service_calls(entity.process_cmd(open_set_cmd("close")))) == 1

    def test_missing_link_keeps_gate_controllable(self, caplog):
        """Без геркона гарда нет — реле обязано слушаться обеих команд.

        Иначе удаление связи превращает ворота в кирпич.
        """
        clock = FakeClock()
        entity = make_impulse_gate(link=False, clock=clock)
        with caplog.at_level(logging.WARNING, logger=GATE_LOGGER):
            assert len(service_calls(entity.process_cmd(open_set_cmd("open")))) == 1
            clock.advance(5.0)
            assert len(service_calls(entity.process_cmd(open_set_cmd("close")))) == 1

    @pytest.mark.parametrize("action", ["open", "close"])
    @pytest.mark.parametrize("lost", ["unknown", "unavailable", None])
    def test_stale_contact_does_not_block_any_direction(self, action, lost):
        """Протухшее показание снимает гард, а не блокирует направление.

        Сценарий: створка поехала по команде, а геркон отвалился, не успев
        отчитаться о новом положении.  Последнее известное значение мы
        продолжаем публиковать (управление важнее свежести), но считать
        его достоверным для гарда нельзя: иначе одно из направлений
        окажется заблокировано навсегда, и закрыть реально открытые
        ворота из Sber станет невозможно — каждая команда «закрой» будет
        подтверждаться ack'ом и не делать ничего.
        """
        entity = make_impulse_gate(contact="off", clock=FakeClock())
        entity.update_linked_data("open_state", {"state": lost})

        results = entity.process_cmd(open_set_cmd(action))

        assert len(service_calls(results)) == 1
        assert states_map(entity)["open_state"]["enum_value"] == "close", (
            "положение обязано остаться последним известным"
        )

    def test_fresh_reading_restores_the_guard(self):
        """Вернувшийся геркон снова включает защиту от реверса.

        Контроль к предыдущему тесту: снятие гарда обязано быть ровно на
        время протухания, а не насовсем.
        """
        clock = FakeClock()
        entity = make_impulse_gate(contact="off", clock=clock)
        entity.update_linked_data("open_state", {"state": "unavailable"})
        clock.advance(10.0)
        entity.update_linked_data("open_state", {"state": "off"})

        assert entity.process_cmd(open_set_cmd("close")) == [{"update_state": True}]

    def test_service_call_carries_no_service_data(self):
        """Импульс — это ровно один вызов без ``service_data``.

        Любой лишний параметр (например position) окажется в ``hass.
        services.async_call`` и упадёт валидацией схемы сервиса.
        """
        entity = make_impulse_gate(contact="off", clock=FakeClock())
        (call,) = service_calls(entity.process_cmd(open_set_cmd("open")))
        assert call["url"] == {
            "type": "call_service",
            "domain": "switch",
            "service": "toggle",
            "target": {"entity_id": "switch.gate"},
        }


class TestImpulseServiceOption:
    """Опция ``impulse_service`` и выбор сервиса импульса."""

    @pytest.mark.parametrize(
        ("option", "expected_service"),
        [(None, "toggle"), ("auto", "toggle"), ("toggle", "toggle"), ("turn_on", "turn_on")],
    )
    def test_switch_service_selection(self, option, expected_service):
        """Для ``switch`` дефолт — ``toggle``, ``turn_on`` доступен опцией.

        ``toggle`` всегда пишет ЗНАЧЕНИЕ, ОТЛИЧНОЕ от текущего, а импульс
        у TS0603-подобного железа возникает именно на смене значения;
        подмена дефолта на ``turn_on`` сделает вторую подряд команду
        физически безрезультатной.
        """
        options = None if option is None else {"impulse_service": option}
        entity = make_impulse_gate(options=options, contact="off", clock=FakeClock())
        (call,) = service_calls(entity.process_cmd(open_set_cmd("open")))
        assert call["url"]["service"] == expected_service
        assert call["url"]["domain"] == "switch"

    @pytest.mark.parametrize("domain", ["button", "input_button"])
    @pytest.mark.parametrize("option", ["auto", "toggle", "turn_on"])
    def test_button_always_pressed(self, domain, option):
        """У кнопки есть только ``press`` — опция switch-сервиса её не касается.

        ``button.toggle``/``button.turn_on`` не существуют: вызов упадёт
        с ServiceNotFound и ворота не откроются.
        """
        entity = make_impulse_gate(
            f"{domain}.gate", options={"impulse_service": option}, contact="off", clock=FakeClock()
        )
        (call,) = service_calls(entity.process_cmd(open_set_cmd("open")))
        assert (call["url"]["domain"], call["url"]["service"]) == (domain, "press")

    @pytest.mark.parametrize("option", ["auto", "toggle", "turn_on"])
    def test_script_always_turned_on(self, option):
        """У скрипта нет toggle-семантики — только ``script.turn_on``."""
        entity = make_impulse_gate("script.gate", options={"impulse_service": option}, contact="off", clock=FakeClock())
        (call,) = service_calls(entity.process_cmd(open_set_cmd("open")))
        assert (call["url"]["domain"], call["url"]["service"]) == ("script", "turn_on")

    def test_unknown_domain_produces_no_service_call(self):
        """Для домена, которым импульс не описан, вызова быть не должно.

        Категорию ``gate`` можно назначить вручную (``set_override``) любой
        сущности, в том числе ``lock``/``light``.  Выдумывать для неё
        ``<domain>.toggle`` нельзя: такого сервиса может не существовать,
        и каждая команда Sber превратится в ServiceNotFound в логе.
        """
        entity = make_impulse_gate("lock.gate", contact="off", clock=FakeClock())
        assert service_calls(entity.process_cmd(open_set_cmd("open"))) == []

    def test_unknown_domain_is_warned_about_once(self, caplog):
        """Про неисполнимый домен предупреждаем один раз, а не на каждую команду.

        Sber переспрашивает состояние и повторяет команды — WARNING без
        дедупликации зальёт лог HA.
        """
        clock = FakeClock()
        entity = make_impulse_gate("lock.gate", contact="off", clock=clock)
        with caplog.at_level(logging.WARNING, logger=GATE_LOGGER):
            for _ in range(3):
                clock.advance(10.0)
                assert entity.process_cmd(open_set_cmd("open")) == []
        assert caplog.text.count("has no impulse service") == 1


class TestCommandRejection:
    """Значения и ключи, на которые ворота реагировать не должны."""

    def test_stop_is_ignored(self):
        """``stop`` не объявлен в allowed_values и обязан игнорироваться.

        Импульс в ответ на «останови» на самом деле сдвинет створку в
        противоположную сторону — худший из возможных исходов.
        """
        entity = make_impulse_gate(contact="off", clock=FakeClock())
        assert entity.process_cmd(open_set_cmd("stop")) == []

    @pytest.mark.parametrize("value", ["opening", "closing", "OPEN", "", "toggle"])
    def test_unknown_enum_values_ignored(self, value):
        """Неизвестное enum-значение не должно двигать ворота."""
        entity = make_impulse_gate(contact="off", clock=FakeClock())
        assert entity.process_cmd(open_set_cmd(value)) == []

    @pytest.mark.parametrize(
        "value",
        [
            {"type": "BOOL", "bool_value": True},
            {"type": "INTEGER", "integer_value": "100"},
            {"enum_value": "open"},
            {},
        ],
    )
    def test_non_enum_payloads_ignored(self, value):
        """Значение не-ENUM (или без объявленного типа) не двигает ворота.

        Ворота — необратимое физическое действие: действовать по
        неоднозначному payload нельзя.
        """
        entity = make_impulse_gate(contact="off", clock=FakeClock())
        assert entity.process_cmd({"states": [{"key": "open_set", "value": value}]}) == []

    @pytest.mark.parametrize("key", ["open_percentage", "on_off", "open_rate", ""])
    def test_undeclared_command_keys_ignored(self, key):
        """Необъявленные фичи не должны иметь обработчиков.

        ``open_percentage`` мы не объявляли: если облако всё же его
        пришлёт, попытка исполнить приведёт к ``cover.set_cover_position``
        на switch-сущности.
        """
        entity = make_impulse_gate(contact="off", clock=FakeClock())
        cmd = {"states": [{"key": key, "value": {"type": "INTEGER", "integer_value": "50"}}]}
        assert entity.process_cmd(cmd) == []

    def test_empty_states_list(self):
        """Пустой список состояний — пустой результат, без исключений."""
        entity = make_impulse_gate(contact="off", clock=FakeClock())
        assert entity.process_cmd({"states": []}) == []


# ---------------------------------------------------------------------------
#  Антидребезг на фейковых часах
# ---------------------------------------------------------------------------


class TestImpulseCooldown:
    """Окно антидребезга: повторная команда внутри него не даёт импульса."""

    def test_default_cooldown_is_two_seconds(self):
        """Дефолтное окно — 2 секунды.

        Обнулённое окно возвращает «залипание» команд, из-за которого
        створка реверсирует на середине хода.
        """
        assert make_impulse_gate(contact="off").impulse_cooldown == pytest.approx(2.0)

    def test_second_impulse_inside_window_suppressed(self):
        """Вторая команда через 0.5 с подтверждается, но импульса не даёт."""
        clock = FakeClock()
        entity = make_impulse_gate(contact="off", clock=clock)
        assert len(service_calls(entity.process_cmd(open_set_cmd("open")))) == 1
        clock.advance(0.5)
        second = entity.process_cmd(open_set_cmd("open"))
        assert service_calls(second) == []
        assert second == [{"update_state": True}]

    def test_impulse_allowed_after_window(self):
        """Через 2.5 с команда снова проходит.

        Проверка «после порога» обязательна: без неё тест не отличает
        работающий антидребезг от навсегда заблокированных ворот.
        """
        clock = FakeClock()
        entity = make_impulse_gate(contact="off", clock=clock)
        assert len(service_calls(entity.process_cmd(open_set_cmd("open")))) == 1
        clock.advance(2.5)
        assert len(service_calls(entity.process_cmd(open_set_cmd("open")))) == 1

    @pytest.mark.parametrize(
        ("delta", "expect_impulse"),
        [(0.0, False), (1.999, False), (2.0, True), (2.001, True)],
    )
    def test_cooldown_boundary(self, delta, expect_impulse):
        """Граница окна — ровно ``impulse_cooldown``, включительно наружу.

        Смещение границы на одну итерацию превращает антидребезг либо в
        «пропускаю всё», либо в «блокирую навсегда».
        """
        clock = FakeClock()
        entity = make_impulse_gate(contact="off", clock=clock)
        entity.process_cmd(open_set_cmd("open"))
        clock.advance(delta)
        calls = service_calls(entity.process_cmd(open_set_cmd("open")))
        assert bool(calls) is expect_impulse

    def test_cooldown_blocks_opposite_direction_too(self):
        """Внутри окна блокируется и команда в другую сторону.

        Быстрая пара «открой»/«закрой» — тот самый сценарий, при котором
        створка реверсирует над машиной.
        """
        clock = FakeClock()
        entity = make_impulse_gate(contact="off", clock=clock)
        entity.process_cmd(open_set_cmd("open"))
        clock.advance(0.2)
        entity.update_linked_data("open_state", {"state": "on"})
        assert entity.process_cmd(open_set_cmd("close")) == [{"update_state": True}]

    def test_custom_cooldown_is_respected(self):
        """Настроенное окно применяется вместо дефолтного."""
        clock = FakeClock()
        entity = make_impulse_gate(contact="off", clock=clock)
        entity.impulse_cooldown = 10.0
        entity.process_cmd(open_set_cmd("open"))
        clock.advance(5.0)
        assert service_calls(entity.process_cmd(open_set_cmd("open"))) == []
        clock.advance(5.0)
        assert len(service_calls(entity.process_cmd(open_set_cmd("open")))) == 1

    def test_clock_is_injectable_and_used(self):
        """Логика обязана ходить за временем ТОЛЬКО через ``_now``.

        Прямой вызов ``time.monotonic()`` внутри команды сделал бы
        антидребезг непроверяемым без сна в тестах.
        """
        assert ImpulseGateEntity({"entity_id": "switch.gate"})._now is time.monotonic
        clock = FakeClock(start=1_000_000.0)
        entity = make_impulse_gate(contact="off", clock=clock)
        entity.process_cmd(open_set_cmd("open"))
        assert clock.calls >= 1


# ---------------------------------------------------------------------------
#  Опции gate_options
# ---------------------------------------------------------------------------


class TestGateOptions:
    """``entry.options['gate_options']`` → поведение сущности."""

    def test_defaults(self):
        """Без опций: прямая полярность и авто-выбор сервиса."""
        entity = make_impulse_gate()
        assert entity.invert_contact is False
        assert entity.impulse_service_option == "auto"

    @pytest.mark.parametrize("value", [True, False])
    def test_invert_contact_applied(self, value):
        """Булев ``invert_contact`` применяется как есть."""
        entity = make_impulse_gate(options={"invert_contact": value})
        assert entity.invert_contact is value

    @pytest.mark.parametrize("bad", ["yes", "true", 1, 0, None, [], "False"])
    def test_non_boolean_invert_ignored(self, bad):
        """Небулево значение инверсии игнорируется.

        Правка конфига руками не должна незаметно перевернуть трактовку
        геркона: «закрыто» стало бы «открыто», и гард начал бы работать
        наоборот.
        """
        entity = make_impulse_gate(options={"invert_contact": bad})
        assert entity.invert_contact is False

    @pytest.mark.parametrize("bad", ["press", "TOGGLE", "", None, 5])
    def test_invalid_impulse_service_ignored(self, bad):
        """Неизвестное значение ``impulse_service`` откатывается к ``auto``."""
        entity = make_impulse_gate(options={"impulse_service": bad}, contact="off", clock=FakeClock())
        assert entity.impulse_service_option == "auto"
        (call,) = service_calls(entity.process_cmd(open_set_cmd("open")))
        assert call["url"]["service"] == "toggle"

    def test_unknown_keys_and_empty_options_are_noop(self):
        """Лишние ключи и пустой словарь опций не ломают загрузку сущности."""
        entity = make_impulse_gate(options={})
        entity.apply_gate_options({"travel_time": 25, "declare_stop": True})
        assert entity.invert_contact is False
        assert entity.impulse_service_option == "auto"

    def test_invert_applies_to_subsequent_readings(self):
        """Инверсия влияет на трактовку последующих показаний геркона."""
        entity = make_impulse_gate(link=True)
        entity.apply_gate_options({"invert_contact": True})
        entity.update_linked_data("open_state", {"state": "on"})
        assert states_map(entity)["open_state"]["enum_value"] == "close"


# ---------------------------------------------------------------------------
#  Роли связывания
# ---------------------------------------------------------------------------


class TestLinkRoles:
    """Контракт ролей: что ворота принимают и без чего не работают."""

    def test_linkable_roles_exact(self):
        """Ворота принимают ровно две роли: геркон и уровень сигнала.

        Батарейных фич в спеке ``gate`` нет — приняв батарейную роль, мы
        начнём публиковать необъявленные ключи.
        """
        assert ImpulseGateEntity.LINKABLE_ROLES == (ROLE_OPEN_STATE, ROLE_SIGNAL)
        assert [r.role for r in ImpulseGateEntity.LINKABLE_ROLES] == ["open_state", "signal_strength"]

    def test_required_link_roles(self):
        """``open_state`` — обязательная роль, и она обязана быть среди принимаемых.

        Мастер отказывается добавить ворота без геркона именно по этому
        списку; роль, отсутствующая в ``LINKABLE_ROLES``, сделала бы
        добавление принципиально невозможным.
        """
        assert ImpulseGateEntity.REQUIRED_LINK_ROLES == ("open_state",)
        accepted = {r.role for r in ImpulseGateEntity.LINKABLE_ROLES}
        assert set(ImpulseGateEntity.REQUIRED_LINK_ROLES) <= accepted

    def test_other_classes_have_no_required_roles(self):
        """Обязательных ролей нет ни у базового класса, ни у cover-ворот.

        Иначе новая проверка мастера заблокирует добавление уже
        работающих у пользователей устройств.
        """
        assert BaseEntity.REQUIRED_LINK_ROLES == ()
        assert GateEntity.REQUIRED_LINK_ROLES == ()

    def test_role_open_state_definition(self):
        """Роль ``open_state`` описывает только герконы дверей/ворот.

        ``window`` намеренно не входит: иначе каждый оконный датчик станет
        кандидатом в датчики положения ворот в мастере.
        """
        assert ROLE_OPEN_STATE.role == "open_state"
        assert ROLE_OPEN_STATE.domains == frozenset({"binary_sensor"})
        assert ROLE_OPEN_STATE.device_classes == frozenset({"garage_door", "door", "opening"})
        assert ROLE_OPEN_STATE.matches("binary_sensor", "window") is False
        assert ROLE_OPEN_STATE.matches("sensor", "garage_door") is False

    def test_role_registered_globally(self):
        """Роль обязана попасть в глобальный реестр ролей.

        Реестр собирается из констант, объявленных ВЫШЕ
        ``ALL_LINKABLE_ROLES``; объявленная ниже роль молча выпадет из
        мастера и из ``auto_link_all``.
        """
        assert ROLE_OPEN_STATE in ALL_LINKABLE_ROLES

    @pytest.mark.parametrize(
        ("domain", "device_class", "expected"),
        [
            ("binary_sensor", "garage_door", "open_state"),
            ("binary_sensor", "door", "open_state"),
            ("binary_sensor", "opening", "open_state"),
            ("binary_sensor", "window", ""),
            ("binary_sensor", "battery", ""),
            ("sensor", "signal_strength", "signal_strength"),
            ("sensor", "battery", ""),
        ],
    )
    def test_resolution_against_class_roles(self, domain, device_class, expected):
        """Сопоставление сущности ролям ворот даёт однозначный результат."""
        assert resolve_link_role_for(ImpulseGateEntity.LINKABLE_ROLES, domain, device_class) == expected


# ---------------------------------------------------------------------------
#  Фабрика make_gate_entity
# ---------------------------------------------------------------------------


class TestFactory:
    """Маршрутизация категории ``gate`` между двумя реализациями."""

    def test_cover_stays_legacy_gate_entity(self):
        """HA ``cover`` обязан остаться на прежнем ``GateEntity``.

        Иначе у существующих пользователей сменится набор фич, а с ним и
        ``model.id`` — в облаке появится новая модель, а карточка ворот
        переедет/сломается.
        """
        entity = make_gate_entity({"entity_id": "cover.gate", "name": "Gate"})
        assert type(entity) is GateEntity
        assert entity.category == "gate"

    @pytest.mark.parametrize(
        "entity_id",
        ["switch.gate", "button.gate", "input_button.gate", "script.gate", "lock.gate"],
    )
    def test_non_cover_becomes_impulse_gate(self, entity_id):
        """Любой не-``cover`` домен получает импульсную реализацию."""
        entity = make_gate_entity({"entity_id": entity_id, "name": "Gate"})
        assert type(entity) is ImpulseGateEntity
        assert entity.category == "gate"
        assert entity.entity_id == entity_id

    def test_cover_gate_behaviour_unchanged(self):
        """Поведенческий регресс cover-ворот: позиция и ``stop`` на месте.

        Это признак того, что фабрика не увела ``cover`` на импульсную
        ветку: у cover-ворот обязаны остаться ``open_percentage`` и
        полный ENUM с ``stop``.
        """
        entity = make_gate_entity({"entity_id": "cover.gate", "name": "Gate"})
        entity.fill_by_ha_state({"entity_id": "cover.gate", "state": "open", "attributes": {"current_position": 50}})
        features = entity.get_final_features_list()
        assert "open_percentage" in features
        allowed = entity.create_allowed_values_list()
        assert allowed["open_set"]["enum_values"]["values"] == ["open", "close", "stop"]
        states = states_map(entity)
        assert states["open_percentage"] == {"type": "INTEGER", "integer_value": "50"}

    def test_cover_gate_commands_still_target_cover_domain(self):
        """Переход curtain на ``get_entity_domain()`` не должен задеть cover.

        Для ``cover.*`` вызовы обязаны остаться байт-в-байт прежними:
        ``cover.open_cover`` / ``cover.set_cover_position``.
        """
        entity = make_gate_entity({"entity_id": "cover.gate", "name": "Gate"})
        entity.fill_by_ha_state({"entity_id": "cover.gate", "state": "open", "attributes": {"current_position": 50}})
        (opened,) = entity.process_cmd(open_set_cmd("open"))
        assert opened["url"] == {
            "type": "call_service",
            "domain": "cover",
            "service": "open_cover",
            "target": {"entity_id": "cover.gate"},
        }
        (positioned,) = entity.process_cmd(
            {"states": [{"key": "open_percentage", "value": {"type": "INTEGER", "integer_value": 75}}]}
        )
        assert positioned["url"] == {
            "type": "call_service",
            "domain": "cover",
            "service": "set_cover_position",
            "target": {"entity_id": "cover.gate"},
            "service_data": {"position": 75},
        }

    def test_factory_declares_produced_classes(self):
        """Фабрика обязана объявлять, какие классы она создаёт.

        ``CategorySpec.cls`` перестал быть классом; интроспекция (тесты
        структуры, диагностика) читает ``produces`` — без него категория
        ``gate`` выпадет из всех обходов классов устройств.
        """
        assert make_gate_entity.produces == (GateEntity, ImpulseGateEntity)
