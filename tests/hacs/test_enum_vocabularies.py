"""Жёсткие тесты словарей ENUM-значений Sber для ``tv`` и ``vacuum_cleaner``.

Облако Sber маршрутизирует ТОЛЬКО те значения ENUM, которые описаны на
странице самой функции. Значение вне словаря выглядит принятым: устройство
регистрируется, приложение рисует кнопку — и кнопка не работает, потому что
облаку нечего послать в ответ, а наш публикуемый статус оно молча выбрасывает.

Именно это и происходило на живой системе (аудит issue #61):

* ``media_player`` Яндекс-станции отдавал ``source: "Станция"`` — подпись из
  Home Assistant. Sber знает только ``hdmi1…hdmi3, tv, av, content,
  screencast, +, -``.
* ``vacuum_cleaner`` отдавал ``vacuum_cleaner_status`` значениями
  ``standby`` / ``go_home`` / ``error``, которых в документации Sber нет
  вовсе, ``vacuum_cleaner_program`` — именами скоростей вентилятора HA
  (``turbo``), а в ``allowed_values`` объявлял команду ``stop``, отсутствующую
  в словаре.

Тесты сверяются с документацией Sber (https://developers.sber.ru/docs/ru/
smarthome/c2c/), а не с текущим поведением кода: ожидаемые множества
выписаны здесь литералами, и расхождение генерируемой спецификации с ними
тоже является провалом.

Последний класс — «сторож»: он проходит по ВСЕМ категориям
``CATEGORY_DOMAIN_MAP`` и требует, чтобы ни одна из них не публиковала и не
объявляла ENUM-значение вне словаря. Новый нарушитель не должен появиться
незаметно.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest
from homeassistant.components.vacuum import VacuumActivity

from custom_components.sber_mqtt_bridge._generated.reference_values import FEATURE_ENUM_VALUES
from custom_components.sber_mqtt_bridge.devices.base_entity import BaseEntity
from custom_components.sber_mqtt_bridge.devices.climate import ClimateEntity
from custom_components.sber_mqtt_bridge.devices.tv import TvEntity
from custom_components.sber_mqtt_bridge.devices.utils.enum_matcher import (
    invert_value_map,
    map_ha_values,
    match_enum_value,
    normalize_enum_token,
)
from custom_components.sber_mqtt_bridge.devices.vacuum_cleaner import (
    _HA_STATE_TO_SBER_STATUS,
    VacuumCleanerEntity,
)
from custom_components.sber_mqtt_bridge.sber_entity_map import CATEGORY_DOMAIN_MAP
from custom_components.sber_mqtt_bridge.schema_validator import validate_publish

_LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Словари из документации Sber — выписаны вручную, а не взяты из кода
# ---------------------------------------------------------------------------

DOC_SOURCE: frozenset[str] = frozenset({"+", "-", "av", "content", "hdmi1", "hdmi2", "hdmi3", "screencast", "tv"})
"""Значения функции ``source`` (категория ``tv``) по документации Sber."""

DOC_VACUUM_STATUS: frozenset[str] = frozenset({"cleaning", "docked", "pause", "returning_to_dock"})
"""Значения функции ``vacuum_cleaner_status`` по документации Sber."""

DOC_VACUUM_PROGRAM: frozenset[str] = frozenset({"perimeter", "random_route", "smart", "spot"})
"""Значения функции ``vacuum_cleaner_program`` по документации Sber."""

DOC_VACUUM_COMMAND: frozenset[str] = frozenset({"pause", "resume", "return_to_dock", "start"})
"""Значения функции ``vacuum_cleaner_command`` по документации Sber.

``stop`` в этом множестве НЕТ — он был выдуман нами и приводил к кнопке,
которую облако никогда не нажмёт."""

DOC_VACUUM_CLEANING_TYPE: frozenset[str] = frozenset({"dry", "mixed", "wet"})
"""Значения функции ``vacuum_cleaner_cleaning_type`` по документации Sber."""

_VOCABULARY_LESS_ENUM_FEATURES: frozenset[str] = frozenset({"reject_call", "unlock"})
"""ENUM-функции, у которых документация не приводит закрытого списка значений.

Единственное законное исключение для сторожа ниже: объявлять
``allowed_values`` для любой другой ENUM-функции, не имея её словаря, значит
угадывать."""

TV_ENTITY_DATA = {"entity_id": "media_player.tv", "name": "Гостиная ТВ"}
VACUUM_ENTITY_DATA = {"entity_id": "vacuum.robot", "name": "Робот"}


# ---------------------------------------------------------------------------
# Хелперы
# ---------------------------------------------------------------------------


def _tv(state: str = "playing", **attrs: Any) -> TvEntity:
    """Собрать заполненный ``TvEntity``.

    Args:
        state: Состояние HA-сущности.
        **attrs: Атрибуты HA-состояния.

    Returns:
        Сущность после ``fill_by_ha_state``.
    """
    entity = TvEntity(dict(TV_ENTITY_DATA))
    entity.fill_by_ha_state({"state": state, "attributes": dict(attrs)})
    return entity


def _vacuum(state: str = "cleaning", **attrs: Any) -> VacuumCleanerEntity:
    """Собрать заполненный ``VacuumCleanerEntity``.

    Args:
        state: Состояние HA-сущности.
        **attrs: Атрибуты HA-состояния.

    Returns:
        Сущность после ``fill_by_ha_state``.
    """
    entity = VacuumCleanerEntity(dict(VACUUM_ENTITY_DATA))
    entity.fill_by_ha_state({"state": state, "attributes": dict(attrs)})
    return entity


def _published(entity: BaseEntity) -> dict[str, dict[str, Any]]:
    """Вернуть публикуемое состояние как ``ключ функции → value-словарь``.

    Args:
        entity: Заполненная сущность.

    Returns:
        Отображение строкового ключа Sber на его ``value``-словарь.
    """
    states = entity.to_sber_current_state()[entity.entity_id]["states"]
    return {str(state["key"]): state["value"] for state in states}


def _enum_allowed(entity: BaseEntity, feature: str) -> list[str] | None:
    """Вернуть объявленные ``allowed_values`` ENUM-значения функции.

    Args:
        entity: Заполненная сущность.
        feature: Ключ функции Sber.

    Returns:
        Список значений в объявленном порядке либо ``None``, если функция
        в ``allowed_values`` не объявлена.
    """
    descriptor = entity.create_allowed_values_list().get(feature)
    if descriptor is None:
        return None
    return list(descriptor["enum_values"]["values"])


def _issues(entity: BaseEntity, *, issue_type: str | None = None) -> list[Any]:
    """Прогнать публикацию сущности через реальный валидатор схемы.

    Args:
        entity: Заполненная сущность.
        issue_type: Если задан — оставить только проблемы этого типа.

    Returns:
        Список :class:`ValidationIssue`.
    """
    found = validate_publish(
        entity_id=entity.entity_id,
        category=entity.category,
        states=entity.to_sber_current_state()[entity.entity_id]["states"],
        declared_features=entity.get_final_features_list(),
    )
    if issue_type is None:
        return found
    return [issue for issue in found if issue.type == issue_type]


# ---------------------------------------------------------------------------
# 1. Сгенерированная спецификация обязана совпадать с документацией
# ---------------------------------------------------------------------------


class TestGeneratedSpecMatchesDocumentation:
    """Словари в ``_generated`` — источник истины для кода, документация — для них."""

    @pytest.mark.parametrize(
        ("feature", "documented"),
        [
            ("source", DOC_SOURCE),
            ("vacuum_cleaner_status", DOC_VACUUM_STATUS),
            ("vacuum_cleaner_program", DOC_VACUUM_PROGRAM),
            ("vacuum_cleaner_command", DOC_VACUUM_COMMAND),
            ("vacuum_cleaner_cleaning_type", DOC_VACUUM_CLEANING_TYPE),
        ],
    )
    def test_vocabulary_is_exactly_the_documented_set(self, feature: str, documented: frozenset[str]) -> None:
        """Если словарь разъедется с документацией, весь остальной файл проверяет фикцию.

        В проде это выглядит как «тесты зелёные, устройство мёртвое»: код
        сверяется с генерируемым множеством, а облако — со своим.
        """
        assert set(FEATURE_ENUM_VALUES[feature]) == set(documented)

    def test_stop_is_not_a_documented_vacuum_command(self) -> None:
        """``stop`` жил в наших ``allowed_values`` и рисовал кнопку, которой нет у Sber.

        Приложение показывало «Стоп», облако такую команду не отправляет —
        пользователь жмёт в пустоту.
        """
        assert "stop" not in FEATURE_ENUM_VALUES["vacuum_cleaner_command"]

    def test_resume_is_a_documented_vacuum_command(self) -> None:
        """Без ``resume`` приостановленный робот нечем продолжить из приложения."""
        assert "resume" in FEATURE_ENUM_VALUES["vacuum_cleaner_command"]

    @pytest.mark.parametrize("invented", ["standby", "go_home", "error", "charging", "returning"])
    def test_invented_vacuum_statuses_are_not_documented(self, invented: str) -> None:
        """Ровно эти значения мы слали в облако до issue #61 — их у Sber нет.

        Каждое такое значение — статус, который приложение не может показать:
        карточка робота застывает на последнем понятном состоянии.
        """
        assert invented not in FEATURE_ENUM_VALUES["vacuum_cleaner_status"]

    @pytest.mark.parametrize("ha_label", ["turbo", "quiet", "standard", "max", "silent"])
    def test_ha_fan_speed_names_are_not_documented_programs(self, ha_label: str) -> None:
        """Имена скоростей вентилятора HA — не маршруты уборки Sber.

        Публикация ``vacuum_cleaner_program: turbo`` даёт в приложении режим,
        который облако не умеет ни показать, ни выбрать.
        """
        assert ha_label not in FEATURE_ENUM_VALUES["vacuum_cleaner_program"]


# ---------------------------------------------------------------------------
# 2. Сопоставление имён HA со словарём Sber
# ---------------------------------------------------------------------------


class TestEnumMatcherNormalization:
    """Регистр, пробелы, дефисы и подчёркивания — шум, всё остальное — значимо."""

    @pytest.mark.parametrize(
        ("ha_label", "expected"),
        [
            ("hdmi1", "hdmi1"),
            ("HDMI1", "hdmi1"),
            ("HDMI 1", "hdmi1"),
            ("hdmi 1", "hdmi1"),
            ("HDMI-1", "hdmi1"),
            ("hdmi_1", "hdmi1"),
            ("  HDMI  1  ", "hdmi1"),
            ("HDMI 2", "hdmi2"),
            ("HDMI-3", "hdmi3"),
            ("TV", "tv"),
            ("Tv", "tv"),
            ("AV", "av"),
            ("Content", "content"),
            ("CONTENT", "content"),
            ("Screencast", "screencast"),
            ("Screen Cast", "screencast"),
            ("screen-cast", "screencast"),
            ("SCREEN_CAST", "screencast"),
        ],
    )
    def test_ha_label_resolves_to_documented_source(self, ha_label: str, expected: str) -> None:
        """HA пишет входы прозой, Sber — токенами; несведённый вход = мёртвый пункт меню.

        Если сопоставление сломается, у телевизора исчезнет переключение
        источников: функция ``source`` просто не будет объявлена.
        """
        assert match_enum_value(ha_label, DOC_SOURCE) == expected

    @pytest.mark.parametrize(
        "ha_label",
        [
            "Станция",
            "Яндекс Музыка",
            "HDMI",
            "HDMI 4",
            "HDMI 10",
            "AV Receiver",
            "TV Box",
            "Content Provider",
            "",
            "   ",
            "---",
            "___",
        ],
    )
    def test_unrelated_label_resolves_to_nothing(self, ha_label: str) -> None:
        """Несопоставимое имя обязано быть отброшено, а не «доведено» до похожего.

        Угаданный источник страшнее отсутствующего: приложение покажет
        «HDMI 1» там, где на самом деле колонка, и переключение уедет не туда.
        """
        assert match_enum_value(ha_label, DOC_SOURCE) is None

    @pytest.mark.parametrize("documented", sorted(DOC_SOURCE))
    def test_documented_value_passes_through_unchanged(self, documented: str) -> None:
        """Интеграция, уже отдающая токен Sber, не должна пострадать от нормализации.

        Отдельно важно для ``+`` и ``-``: дефис входит в список шумовых
        символов, и без прямой проверки членства он бы схлопнулся в пустую
        строку и потерялся.
        """
        assert match_enum_value(documented, DOC_SOURCE) == documented

    def test_normalization_strips_exactly_the_noise_characters(self) -> None:
        """Нормализация не имеет права трогать буквы и цифры.

        Если она начнёт удалять что-то ещё, разные источники схлопнутся в
        один токен и телевизор будет переключаться не туда.
        """
        assert normalize_enum_token("HDMI 1") == "hdmi1"
        assert normalize_enum_token("Random_Route") == "randomroute"
        assert normalize_enum_token("Станция") == "станция"
        assert normalize_enum_token("-") == ""
        assert normalize_enum_token("A-B_C D") == "abcd"

    def test_synonym_cannot_smuggle_undocumented_value(self) -> None:
        """Таблица синонимов — не лазейка в обход словаря.

        Устаревший синоним иначе протащил бы в облако значение, которого
        Sber не знает, и режим уборки перестал бы переключаться.
        """
        assert match_enum_value("edge", DOC_VACUUM_PROGRAM, synonyms={"edge": "go_home"}) is None
        assert match_enum_value("edge", DOC_VACUUM_PROGRAM, synonyms={"edge": "perimeter"}) == "perimeter"

    def test_map_preserves_ha_order(self) -> None:
        """Порядок значений входит в цифровой отпечаток ``model.id``.

        Перетасовка списка меняет ``model.id``, облако перерегистрирует
        устройство, и пользователь теряет назначенную комнату (issue #44).
        """
        mapped = map_ha_values(["TV", "HDMI 2", "HDMI 1", "Content"], DOC_SOURCE)
        assert list(mapped.values()) == ["tv", "hdmi2", "hdmi1", "content"]

    def test_first_ha_label_claims_the_sber_value(self) -> None:
        """Два имени HA на одно значение Sber — слот достаётся первому.

        Иначе публикуемое состояние и принимаемая команда указывали бы на
        разные входы телевизора.
        """
        mapped = map_ha_values(["HDMI 1", "hdmi-1", "HDMI_1"], DOC_SOURCE)
        assert mapped == {"HDMI 1": "hdmi1"}

    def test_unmatched_labels_are_dropped_not_kept(self) -> None:
        """Именно так «Станция» не должна попадать в объявление устройства."""
        assert map_ha_values(["Станция", "HDMI 1", "Яндекс Музыка"], DOC_SOURCE) == {"HDMI 1": "hdmi1"}

    def test_map_of_nothing_matching_is_empty(self) -> None:
        """Пустой результат — сигнал «функцию объявлять нельзя»."""
        assert map_ha_values(["Станция", "Яндекс Музыка"], DOC_SOURCE) == {}

    def test_bare_string_is_not_iterated_character_by_character(self) -> None:
        """Кривая интеграция отдаёт строку вместо списка — это не 9 источников.

        Посимвольный перебор нашёл бы в строке ``-`` и объявил документированный
        относительный источник, которого у устройства нет.
        """
        assert map_ha_values("HDMI 1 - TV", DOC_SOURCE) == {}

    def test_inversion_is_the_exact_reverse(self) -> None:
        """Обратная таблица — единственный путь команды Sber назад в HA."""
        forward = map_ha_values(["HDMI 1", "TV"], DOC_SOURCE)
        assert invert_value_map(forward) == {"hdmi1": "HDMI 1", "tv": "TV"}


# ---------------------------------------------------------------------------
# 3. Телевизор: объявление и публикация источника
# ---------------------------------------------------------------------------


class TestTvSourceDeclaration:
    """Что телевизор объявляет облаку в ``features`` и ``allowed_values``."""

    def test_declared_sources_are_sber_values_in_ha_order(self) -> None:
        """Объявляем токены Sber, а не подписи HA — приложение шлёт назад именно их.

        Объявив «HDMI 1», мы получили бы обратно «HDMI 1» и не смогли бы
        отличить его от любого другого произвольного текста.
        """
        tv = _tv(source_list=["HDMI 1", "TV", "HDMI 2", "Screen Cast"])
        assert _enum_allowed(tv, "source") == ["hdmi1", "tv", "hdmi2", "screencast"]

    def test_unmatched_source_is_not_declared(self) -> None:
        """«Станция» Яндекса не должна оказаться в объявленных значениях.

        Иначе Sber молча отвергает устройство целиком — ровно тот отказ,
        который выглядит как «всё работает, но ничего не появилось».
        """
        tv = _tv(source_list=["HDMI 1", "Станция"])
        assert _enum_allowed(tv, "source") == ["hdmi1"]

    def test_every_declared_value_is_documented(self) -> None:
        """Сторож для конкретной сущности: ни одного самодельного значения."""
        tv = _tv(source_list=["HDMI 1", "HDMI 2", "HDMI 3", "TV", "AV", "Content", "Screencast", "Станция"])
        assert set(_enum_allowed(tv, "source") or []) <= DOC_SOURCE

    def test_source_feature_declared_when_something_matches(self) -> None:
        """Функция ``source`` объявляется ровно тогда, когда есть что переключать."""
        tv = _tv(source_list=["Станция", "HDMI 1"])
        assert "source" in tv.get_final_features_list()

    def test_tv_without_matching_sources_declares_no_source(self) -> None:
        """Колонка с единственным источником «Станция» не получает переключателя.

        Пустой или самодельный список источников — это либо отвергнутое
        устройство, либо неработающий элемент управления в приложении.
        """
        station = _tv(source="Станция", source_list=["Станция", "Яндекс Музыка"])
        assert "source" not in station.get_final_features_list()
        assert station.create_allowed_values_list() == {}

    def test_source_is_the_only_difference_between_the_two_cases(self) -> None:
        """Отказ от ``source`` не должен задеть остальные функции телевизора.

        Громкость, mute и каналы обязаны остаться — иначе колонка потеряет
        управление вместе с ненайденным источником.
        """
        with_source = set(_tv(source_list=["HDMI 1"]).get_final_features_list())
        without_source = set(_tv(source_list=["Станция"]).get_final_features_list())
        assert with_source - without_source == {"source"}
        assert without_source - with_source == set()

    def test_station_stays_a_valid_sber_device(self) -> None:
        """Устройство без источников остаётся полноценным устройством Sber.

        Обязательные для категории ``tv`` функции — ``online`` и ``on_off`` —
        на месте, и валидатор не находит ни одной проблемы: колонка должна
        включаться и регулировать громкость из приложения.
        """
        station = _tv(source="Станция", source_list=["Станция"], volume_level=0.4)
        features = station.get_final_features_list()
        assert {"online", "on_off"} <= set(features)
        assert _issues(station) == []


class TestTvSourcePublish:
    """Что телевизор публикует в состоянии."""

    @pytest.mark.parametrize(
        ("ha_source", "expected"),
        [
            ("HDMI 1", "hdmi1"),
            ("HDMI 2", "hdmi2"),
            ("HDMI 3", "hdmi3"),
            ("TV", "tv"),
            ("AV", "av"),
            ("Content", "content"),
            ("Screen Cast", "screencast"),
        ],
    )
    def test_current_source_is_published_as_sber_value(self, ha_source: str, expected: str) -> None:
        """Публикуемый источник — токен Sber; иначе приложение показывает не тот вход."""
        sources = ["HDMI 1", "HDMI 2", "HDMI 3", "TV", "AV", "Content", "Screen Cast"]
        tv = _tv(source=ha_source, source_list=sources)
        assert _published(tv)["source"] == {"type": "ENUM", "enum_value": expected}

    def test_unmatched_current_source_is_not_published(self) -> None:
        """Пока выбран несопоставимый вход, состояние ``source`` не публикуется.

        Публикация «Станция» — это ``unknown_enum_value``: облако не может
        сопоставить значение и перестаёт доверять статусу устройства.
        """
        tv = _tv(source="Станция", source_list=["HDMI 1", "Станция"])
        assert "source" not in _published(tv)

    def test_station_publishes_no_source_at_all(self) -> None:
        """У колонки в публикации остаются только реально управляемые функции."""
        station = _tv(source="Станция", source_list=["Станция"], volume_level=0.4)
        assert set(_published(station)) == {"online", "on_off", "volume_int", "mute"}

    @pytest.mark.parametrize(
        "source_list",
        [
            ["HDMI 1", "HDMI 2", "TV"],
            ["Станция"],
            ["Станция", "Яндекс Музыка", "HDMI 1"],
            ["hdmi1", "hdmi2", "hdmi3", "tv", "av", "content", "screencast", "+", "-"],
            ["HDMI-1", "SCREEN_CAST", "Content"],
            [],
        ],
    )
    @pytest.mark.parametrize("state", ["playing", "on", "off", "standby", "idle", "unavailable", "unknown"])
    def test_validator_reports_no_unknown_enum_value(self, source_list: list[str], state: str) -> None:
        """Ни один вариант списка источников не должен давать ``unknown_enum_value``.

        Это тот самый диагноз, который на живой системе выдавался на каждую
        Яндекс-станцию: значение вне словаря — сломанное управление.
        """
        for current in [None, *source_list, "Станция"]:
            attrs: dict[str, Any] = {"source_list": list(source_list), "volume_level": 0.5}
            if current is not None:
                attrs["source"] = current
            tv = _tv(state, **attrs)
            offenders = _issues(tv, issue_type="unknown_enum_value")
            assert offenders == [], f"source={current!r} list={source_list!r}: {[i.details for i in offenders]}"


class TestTvSourceCommand:
    """Обратное преобразование: команда Sber → вызов сервиса HA."""

    def test_sber_value_becomes_the_ha_input_name(self) -> None:
        """``media_player.select_source`` принимает только имя из ``source_list``.

        Проброс ``hdmi1`` напрямую HA отвергает — переключение источника из
        приложения Сбера молча перестаёт работать.
        """
        tv = _tv(source="TV", source_list=["HDMI 1", "HDMI 2", "TV"])
        calls = tv.process_cmd({"states": [{"key": "source", "value": {"type": "ENUM", "enum_value": "hdmi1"}}]})
        assert calls == [
            {
                "url": {
                    "type": "call_service",
                    "domain": "media_player",
                    "service": "select_source",
                    "target": {"entity_id": "media_player.tv"},
                    "service_data": {"source": "HDMI 1"},
                }
            }
        ]

    @pytest.mark.parametrize(
        ("sber_value", "ha_source"),
        [("hdmi1", "HDMI 1"), ("hdmi2", "HDMI-2"), ("screencast", "Screen Cast"), ("tv", "TV")],
    )
    def test_round_trip_returns_the_original_ha_label(self, sber_value: str, ha_source: str) -> None:
        """Что опубликовали как значение Sber, то и должно вернуться именем HA."""
        tv = _tv(source_list=["HDMI 1", "HDMI-2", "Screen Cast", "TV"])
        calls = tv.process_cmd({"states": [{"key": "source", "value": {"type": "ENUM", "enum_value": sber_value}}]})
        assert [call["url"]["service_data"] for call in calls] == [{"source": ha_source}]

    @pytest.mark.parametrize("sber_value", ["hdmi3", "av", "content", "+", "-", "unknown_input"])
    def test_command_for_never_advertised_source_is_dropped(self, sber_value: str) -> None:
        """Значение, которого телевизор не объявлял, нельзя отдавать в HA.

        Пробросив его, мы получаем исключение внутри HA на каждое нажатие —
        и заодно теряем полезные записи в журнале за спамом.
        """
        tv = _tv(source="HDMI 1", source_list=["HDMI 1", "TV"])
        assert (
            tv.process_cmd({"states": [{"key": "source", "value": {"type": "ENUM", "enum_value": sber_value}}]}) == []
        )

    def test_station_accepts_no_source_command_at_all(self) -> None:
        """Колонка не объявляла источников — значит, и переключать нечего."""
        station = _tv(source="Станция", source_list=["Станция"])
        for sber_value in sorted(DOC_SOURCE):
            assert (
                station.process_cmd(
                    {"states": [{"key": "source", "value": {"type": "ENUM", "enum_value": sber_value}}]}
                )
                == []
            )


# ---------------------------------------------------------------------------
# 4. Пылесос: статус, команда, программа
# ---------------------------------------------------------------------------


EXPECTED_VACUUM_STATUS: dict[str, str] = {
    "cleaning": "cleaning",
    "docked": "docked",
    "returning": "returning_to_dock",
    "paused": "pause",
    # У Sber нет значений для «стоит вне базы» и «авария»; из четырёх
    # документированных ``pause`` — единственное, что не врёт: не убирает
    # и не на базе.
    "idle": "pause",
    "error": "pause",
}
"""Ожидаемое отображение состояний HA, выведенное из словаря Sber, а не из кода."""


class TestVacuumStatusMatrix:
    """Полная матрица состояний HA → словарь ``vacuum_cleaner_status``."""

    def test_map_covers_exactly_home_assistant_activities(self) -> None:
        """Ключи таблицы — ровно состояния HA ``VacuumActivity``.

        Пропущенное состояние молча уедет в значение по умолчанию: робот,
        застрявший посреди комнаты, покажется стоящим на базе.
        """
        assert set(_HA_STATE_TO_SBER_STATUS) == {activity.value for activity in VacuumActivity}

    def test_full_matrix_is_exactly_as_documented(self) -> None:
        """Матрица целиком, без «in» и частичных сравнений."""
        assert _HA_STATE_TO_SBER_STATUS == EXPECTED_VACUUM_STATUS

    @pytest.mark.parametrize("activity", sorted(activity.value for activity in VacuumActivity))
    def test_published_status_matches_the_matrix(self, activity: str) -> None:
        """Каждое состояние HA публикуется документированным значением Sber.

        Значение вне словаря — это карточка робота в приложении, застывшая
        на последнем понятном статусе.
        """
        assert _published(_vacuum(activity))["vacuum_cleaner_status"] == {
            "type": "ENUM",
            "enum_value": EXPECTED_VACUUM_STATUS[activity],
        }

    @pytest.mark.parametrize("activity", sorted(activity.value for activity in VacuumActivity))
    def test_every_published_status_is_documented(self, activity: str) -> None:
        """Дублирующая проверка по словарю: ни одного самодельного статуса."""
        assert _published(_vacuum(activity))["vacuum_cleaner_status"]["enum_value"] in DOC_VACUUM_STATUS

    @pytest.mark.parametrize("weird", ["mopping", "unknown", "unavailable", "", "returning_to_dock", "STANDBY"])
    def test_unrecognized_ha_state_falls_back_to_a_documented_value(self, weird: str) -> None:
        """Незнакомое состояние стороннего интеграционного компонента — не повод врать.

        Запасное значение обязано быть из словаря: иначе достаточно одного
        экзотического пылесоса, чтобы облако перестало понимать публикации.
        """
        assert _published(_vacuum(weird))["vacuum_cleaner_status"]["enum_value"] in DOC_VACUUM_STATUS

    @pytest.mark.parametrize("weird", ["mopping", "unknown", "unavailable", "", "STANDBY"])
    def test_unrecognized_ha_state_reports_the_resting_value(self, weird: str) -> None:
        """Неизвестное состояние отображается в ``docked`` — «ничего не делаю».

        Любое другое значение утверждало бы активность, которой может не быть:
        приложение показало бы уборку у выключенного робота.
        """
        assert _published(_vacuum(weird))["vacuum_cleaner_status"]["enum_value"] == "docked"


class TestVacuumCommandVocabulary:
    """``vacuum_cleaner_command``: объявление и исполнение."""

    def test_allowed_values_are_exactly_the_documented_set(self) -> None:
        """Объявляем ровно словарь Sber — ни больше, ни меньше.

        Лишнее значение даёт кнопку, которую облако не нажмёт; недостающее
        отнимает у пользователя реальное действие.
        """
        assert set(_enum_allowed(_vacuum(), "vacuum_cleaner_command") or []) == DOC_VACUUM_COMMAND

    def test_stop_is_not_declared(self) -> None:
        """``stop`` был выдуман нами и должен исчезнуть из объявления (issue #61)."""
        assert "stop" not in (_enum_allowed(_vacuum(), "vacuum_cleaner_command") or [])

    def test_resume_is_declared(self) -> None:
        """Без ``resume`` приостановленную уборку не продолжить из приложения."""
        assert "resume" in (_enum_allowed(_vacuum(), "vacuum_cleaner_command") or [])

    def test_declared_commands_have_no_duplicates(self) -> None:
        """Повтор значения меняет ``model.id`` и путает приложение."""
        declared = _enum_allowed(_vacuum(), "vacuum_cleaner_command") or []
        assert len(declared) == len(set(declared))

    @pytest.mark.parametrize(
        ("sber_command", "ha_service"),
        [
            ("start", "start"),
            ("resume", "start"),
            ("pause", "pause"),
            ("return_to_dock", "return_to_base"),
        ],
    )
    def test_each_documented_command_becomes_an_exact_service_call(self, sber_command: str, ha_service: str) -> None:
        """Каждая документированная команда обязана доезжать до сервиса HA.

        Необработанная команда — это кнопка в приложении, после которой
        робот не двигается.
        """
        vacuum = _vacuum()
        calls = vacuum.process_cmd(
            {"states": [{"key": "vacuum_cleaner_command", "value": {"type": "ENUM", "enum_value": sber_command}}]}
        )
        assert calls == [
            {
                "url": {
                    "type": "call_service",
                    "domain": "vacuum",
                    "service": ha_service,
                    "target": {"entity_id": "vacuum.robot"},
                }
            }
        ]

    def test_every_documented_command_is_handled(self) -> None:
        """Полное покрытие словаря: непокрытых значений быть не может."""
        vacuum = _vacuum()
        unhandled = [
            command
            for command in sorted(DOC_VACUUM_COMMAND)
            if not vacuum.process_cmd(
                {"states": [{"key": "vacuum_cleaner_command", "value": {"type": "ENUM", "enum_value": command}}]}
            )
        ]
        assert unhandled == []

    @pytest.mark.parametrize("undocumented", ["stop", "go_home", "charge", "clean_spot", ""])
    def test_undocumented_command_executes_nothing(self, undocumented: str) -> None:
        """Значение вне словаря не должно порождать вызов сервиса HA."""
        vacuum = _vacuum()
        assert (
            vacuum.process_cmd(
                {"states": [{"key": "vacuum_cleaner_command", "value": {"type": "ENUM", "enum_value": undocumented}}]}
            )
            == []
        )


class TestVacuumProgramVocabulary:
    """``vacuum_cleaner_program``: маршруты уборки, а не скорости вентилятора."""

    @pytest.mark.parametrize(
        ("ha_mode", "expected"),
        [
            ("spot", "spot"),
            ("Spot", "spot"),
            ("Spot Clean", None),
            ("smart", "smart"),
            ("Smart", "smart"),
            ("perimeter", "perimeter"),
            ("Perimeter", "perimeter"),
            ("Edge", "perimeter"),
            ("edge clean", "perimeter"),
            ("random_route", "random_route"),
            ("Random Route", "random_route"),
            ("RANDOM-ROUTE", "random_route"),
            ("Random", "random_route"),
            ("Turbo", None),
            ("Max", None),
            ("Тихий", None),
            ("Balanced", None),
        ],
    )
    def test_ha_mode_maps_only_onto_documented_routes(self, ha_mode: str, expected: str | None) -> None:
        """Имя режима HA превращается в маршрут Sber либо отбрасывается.

        Опубликованный ``turbo`` — режим, которого облако не знает: выбор
        программы в приложении перестаёт работать.
        """
        vacuum = _vacuum(fan_speed_list=[ha_mode])
        declared = _enum_allowed(vacuum, "vacuum_cleaner_program")
        assert declared == ([expected] if expected else None)

    def test_declared_programs_keep_ha_order_and_are_documented(self) -> None:
        """Порядок стабилен (``model.id``), значения — только из словаря."""
        vacuum = _vacuum(fan_speed_list=["Turbo", "Spot", "Edge", "Smart", "Random Route"])
        declared = _enum_allowed(vacuum, "vacuum_cleaner_program")
        assert declared == ["spot", "perimeter", "smart", "random_route"]
        assert set(declared) <= DOC_VACUUM_PROGRAM

    def test_no_matching_mode_means_no_program_feature(self) -> None:
        """Робот, у которого есть только скорости вентилятора, не получает программ.

        Объявлять функцию с самодельными значениями хуже, чем не объявлять:
        пользователь видит переключатель, который ничего не переключает.
        """
        vacuum = _vacuum(fan_speed="Turbo", fan_speed_list=["Turbo", "Max", "Тихий"])
        assert "vacuum_cleaner_program" not in vacuum.get_final_features_list()
        assert _enum_allowed(vacuum, "vacuum_cleaner_program") is None
        assert "vacuum_cleaner_program" not in _published(vacuum)

    def test_robot_without_programs_stays_valid(self) -> None:
        """Отсутствие программ не должно делать устройство невалидным.

        Обязательна для категории только ``online``; всё остальное —
        по возможностям устройства.
        """
        vacuum = _vacuum(fan_speed="Turbo", fan_speed_list=["Turbo"])
        assert "online" in vacuum.get_final_features_list()
        assert _issues(vacuum) == []

    def test_current_mode_outside_vocabulary_publishes_no_program(self) -> None:
        """Функция объявлена, но текущий режим не сопоставился — значит, молчим.

        Публикация «Turbo» дала бы ``unknown_enum_value`` и подорвала бы
        доверие облака ко всей публикации устройства.
        """
        vacuum = _vacuum(fan_speed="Turbo", fan_speed_list=["Spot", "Turbo"])
        assert "vacuum_cleaner_program" in vacuum.get_final_features_list()
        assert "vacuum_cleaner_program" not in _published(vacuum)

    def test_current_mode_inside_vocabulary_is_published(self) -> None:
        """Сопоставленный режим публикуется документированным значением."""
        vacuum = _vacuum(fan_speed="Edge", fan_speed_list=["Spot", "Edge"])
        assert _published(vacuum)["vacuum_cleaner_program"] == {"type": "ENUM", "enum_value": "perimeter"}

    def test_program_command_is_translated_back_to_the_ha_mode(self) -> None:
        """``vacuum.set_fan_speed`` принимает только имя из ``fan_speed_list``.

        Проброс ``perimeter`` напрямую HA отвергает — выбор программы из
        приложения не срабатывает.
        """
        vacuum = _vacuum(fan_speed="Spot", fan_speed_list=["Spot", "Edge"])
        calls = vacuum.process_cmd(
            {"states": [{"key": "vacuum_cleaner_program", "value": {"type": "ENUM", "enum_value": "perimeter"}}]}
        )
        assert calls == [
            {
                "url": {
                    "type": "call_service",
                    "domain": "vacuum",
                    "service": "set_fan_speed",
                    "target": {"entity_id": "vacuum.robot"},
                    "service_data": {"fan_speed": "Edge"},
                }
            }
        ]

    @pytest.mark.parametrize("route", ["smart", "random_route", "spot", "turbo", ""])
    def test_program_command_for_unadvertised_route_is_dropped(self, route: str) -> None:
        """Маршрут, которого робот не объявлял, не должен уезжать в HA."""
        vacuum = _vacuum(fan_speed="Edge", fan_speed_list=["Edge"])
        assert (
            vacuum.process_cmd(
                {"states": [{"key": "vacuum_cleaner_program", "value": {"type": "ENUM", "enum_value": route}}]}
            )
            == []
        )


class TestVacuumCleaningTypeVocabulary:
    """``vacuum_cleaner_cleaning_type``: сухая / влажная / смешанная."""

    @pytest.mark.parametrize(("ha_value", "expected"), [("dry", "dry"), ("Wet", "wet"), ("MIXED", "mixed")])
    def test_documented_cleaning_type_is_published(self, ha_value: str, expected: str) -> None:
        """Тип уборки публикуется значением Sber независимо от регистра HA."""
        vacuum = _vacuum(cleaning_type=ha_value)
        assert _published(vacuum)["vacuum_cleaner_cleaning_type"] == {"type": "ENUM", "enum_value": expected}

    @pytest.mark.parametrize("ha_value", ["Влажная", "vacuum", "auto", "", "mop"])
    def test_unknown_cleaning_type_is_neither_declared_nor_published(self, ha_value: str) -> None:
        """Незнакомый тип уборки отбрасывается вместе с объявлением функции."""
        vacuum = _vacuum(cleaning_type=ha_value)
        assert "vacuum_cleaner_cleaning_type" not in vacuum.get_final_features_list()
        assert "vacuum_cleaner_cleaning_type" not in _published(vacuum)


class TestVacuumValidatorIsClean:
    """Валидатор не должен находить ``unknown_enum_value`` ни в одном варианте."""

    @pytest.mark.parametrize(
        "fan_speed_list",
        [
            [],
            ["Turbo", "Max", "Тихий"],
            ["Spot", "Edge", "Smart", "Random Route"],
            ["spot", "perimeter", "smart", "random_route"],
            ["Spot", "Turbo"],
        ],
    )
    @pytest.mark.parametrize(
        "state",
        ["cleaning", "docked", "idle", "paused", "returning", "error", "unknown", "unavailable", "mopping"],
    )
    def test_no_unknown_enum_value_for_any_combination(self, fan_speed_list: list[str], state: str) -> None:
        """Живая система выдавала здесь настоящие расхождения — их быть не должно.

        Каждое такое расхождение — управление роботом, которое выглядит
        исправным в приложении и не работает на деле.
        """
        for current in [None, *fan_speed_list, "Turbo"]:
            attrs: dict[str, Any] = {"fan_speed_list": list(fan_speed_list), "battery_level": 55}
            if current is not None:
                attrs["fan_speed"] = current
            for cleaning_type in (None, "wet", "Влажная"):
                if cleaning_type is not None:
                    attrs["cleaning_type"] = cleaning_type
                vacuum = _vacuum(state, **attrs)
                offenders = _issues(vacuum, issue_type="unknown_enum_value")
                assert offenders == [], f"state={state} speed={current!r} type={cleaning_type!r}: {offenders}"


# ---------------------------------------------------------------------------
# 5. Найденное сторожем: hvac_work_mode принимает значение чужой функции
# ---------------------------------------------------------------------------


class TestClimateWorkModeVocabulary:
    """``hvac_work_mode`` обязан оставаться внутри своего словаря.

    Сторож из следующего раздела нашёл здесь настоящее расхождение того же
    рода, что и у телевизора с пылесосом: HA-пресет подставляется в ENUM
    чужой функции.
    """

    @staticmethod
    def _climate(preset: str) -> ClimateEntity:
        """Собрать кондиционер с заданным HA-пресетом.

        Args:
            preset: Значение атрибута ``preset_mode``.

        Returns:
            Заполненная сущность ``hvac_ac``.
        """
        entity = ClimateEntity({"entity_id": "climate.ac", "name": "Кондиционер"})
        entity.fill_by_ha_state(
            {
                "state": "cool",
                "attributes": {
                    "hvac_modes": ["off", "cool", "heat"],
                    "preset_modes": ["none", "eco", "boost", "sleep"],
                    "preset_mode": preset,
                    "current_temperature": 21,
                    "temperature": 22,
                    "min_temp": 16,
                    "max_temp": 30,
                },
            }
        )
        return entity

    @pytest.mark.parametrize("preset", ["none", "eco", "boost", "sleep", "comfort", "away"])
    def test_published_work_mode_is_documented(self, preset: str) -> None:
        """Любой HA-пресет обязан дать значение из словаря ``hvac_work_mode``.

        ``quiet`` в этом словаре нет — он принадлежит ``hvac_air_flow_power``.
        Отправляя его в ``hvac_work_mode``, мы даём облаку значение, которое
        оно не маршрутизирует: режим работы кондиционера в приложении
        перестаёт переключаться.
        """
        published = _published(self._climate(preset)).get("hvac_work_mode")
        if published is None:
            return
        assert published["enum_value"] in FEATURE_ENUM_VALUES["hvac_work_mode"]

    def test_eco_preset_publishes_the_documented_eco_mode(self) -> None:
        """У Sber есть собственный ``eco`` — подменять его на ``quiet`` незачем.

        Пользователь включает эко-режим в HA, а приложение Сбера показывает
        режим, которого не понимает.
        """
        assert _published(self._climate("eco"))["hvac_work_mode"] == {"type": "ENUM", "enum_value": "eco"}

    def test_boost_preset_publishes_the_documented_turbo_mode(self) -> None:
        """``turbo`` документирован, и именно он должен уходить для ``boost``."""
        assert _published(self._climate("boost"))["hvac_work_mode"] == {"type": "ENUM", "enum_value": "turbo"}

    def test_sleep_preset_does_not_publish_a_fan_power_value(self) -> None:
        """Ночному пресету соответствует документированный ``comfortable_sleep``.

        ``quiet`` — значение функции мощности обдува; в режиме работы оно
        для облака бессмысленно.
        """
        published = _published(self._climate("sleep")).get("hvac_work_mode")
        assert published is not None
        assert published["enum_value"] != "quiet"
        assert published["enum_value"] in FEATURE_ENUM_VALUES["hvac_work_mode"]


# ---------------------------------------------------------------------------
# 6. Сторож: ни одна категория не имеет права выдумывать значения
# ---------------------------------------------------------------------------

_SBER_FLAVOURED_ATTRS: dict[str, Any] = {
    "source": "hdmi1",
    "source_list": ["hdmi1", "hdmi2", "hdmi3", "tv", "av", "content", "screencast"],
    "fan_speed": "spot",
    "fan_speed_list": ["spot", "perimeter", "smart", "random_route"],
    "cleaning_type": "wet",
    "hvac_modes": ["off", "cool", "heat", "dry", "fan_only", "auto"],
    "fan_modes": ["auto", "low", "medium", "high"],
    "fan_mode": "auto",
    "swing_modes": ["off", "vertical", "horizontal", "both"],
    "swing_mode": "off",
    "preset_modes": ["eco", "boost", "comfort"],
    "preset_mode": "eco",
    "available_modes": ["normal", "boost", "eco"],
    "mode": "normal",
    "operation_list": ["eco", "performance", "high_demand"],
    "operation_mode": "eco",
    "supported_color_modes": ["hs", "color_temp"],
    "color_mode": "hs",
    "hs_color": (30, 40),
    "brightness": 180,
    "color_temp_kelvin": 4000,
    "temperature": 22,
    "current_temperature": 21,
    "min_temp": 5,
    "max_temp": 35,
    "humidity": 50,
    "current_humidity": 45,
    "percentage": 40,
    "percentage_step": 10,
    "current_position": 60,
    "current_tilt_position": 30,
    "volume_level": 0.4,
    "is_volume_muted": False,
    "battery_level": 66,
    "signal_strength": -55,
    "sensitivity": "high",
    "carbon_dioxide": 600,
    "pm25": 12,
}
"""Атрибуты HA, уже написанные «на языке» Sber — благоприятный случай."""

_HA_FLAVOURED_ATTRS: dict[str, Any] = {
    **_SBER_FLAVOURED_ATTRS,
    "source": "Станция",
    "source_list": ["Станция", "Яндекс Музыка", "HDMI 1"],
    "fan_speed": "Турбо",
    "fan_speed_list": ["Турбо", "Тихий режим", "Max+"],
    "cleaning_type": "Влажная",
    "preset_modes": ["Дома", "В отъезде", "Ночь"],
    "preset_mode": "Ночь",
    "available_modes": ["Ночь", "Турбо"],
    "mode": "Ночь",
    "operation_list": ["Электро", "Газ"],
    "operation_mode": "Электро",
    "fan_modes": ["Сильный", "Слабый"],
    "fan_mode": "Сильный",
    "swing_modes": ["Качание"],
    "swing_mode": "Качание",
    "sensitivity": "Высокая",
}
"""Те же атрибуты в том виде, в каком их реально отдают интеграции HA."""

_SENTINEL_STATES: tuple[str, ...] = (
    "on",
    "off",
    "cleaning",
    "docked",
    "idle",
    "paused",
    "returning",
    "error",
    "open",
    "closed",
    "opening",
    "closing",
    "playing",
    "standby",
    "heat",
    "cool",
    "unknown",
    "unavailable",
)
"""Состояния HA, которыми обстреливается каждая категория."""


def _probe(category: str, attrs: dict[str, Any], state: str) -> BaseEntity:
    """Собрать максимально «богатую» сущность указанной категории.

    Args:
        category: Ключ :data:`CATEGORY_DOMAIN_MAP`.
        attrs: Атрибуты HA-состояния.
        state: Состояние HA-сущности.

    Returns:
        Заполненная сущность категории.
    """
    spec = CATEGORY_DOMAIN_MAP[category]
    device_class = (spec.device_classes or ("",))[0]
    entity = spec.cls(
        {
            "entity_id": f"{spec.domains[0]}.probe",
            "name": "Проба",
            "original_device_class": device_class,
            "device_class": device_class,
        }
    )
    entity.fill_by_ha_state({"state": state, "attributes": dict(attrs)})
    return entity


class TestNoCategoryInventsEnumValues:
    """Сторож по всем категориям Sber — новый нарушитель не пройдёт незаметно."""

    @pytest.mark.parametrize("category", sorted(CATEGORY_DOMAIN_MAP))
    @pytest.mark.parametrize(
        ("profile", "attrs"),
        [("sber", _SBER_FLAVOURED_ATTRS), ("ha", _HA_FLAVOURED_ATTRS)],
    )
    def test_publish_has_no_unknown_enum_value(self, category: str, profile: str, attrs: dict[str, Any]) -> None:
        """Ни одна категория не имеет права опубликовать значение вне словаря Sber.

        Ровно так ломались телевизор и пылесос: устройство регистрируется,
        элементы управления рисуются, ничего не работает. Профиль ``ha``
        подаёт человеческие подписи, которые интеграции отдают на самом деле.
        """
        offenders: list[str] = []
        for state in _SENTINEL_STATES:
            entity = _probe(category, attrs, state)
            offenders.extend(
                f"{state}/{issue.key}={issue.details.get('sent')!r}"
                for issue in _issues(entity, issue_type="unknown_enum_value")
            )
        assert offenders == [], f"{category} ({profile}) публикует недокументированные значения: {offenders}"

    @pytest.mark.parametrize("category", sorted(CATEGORY_DOMAIN_MAP))
    @pytest.mark.parametrize(
        ("profile", "attrs"),
        [("sber", _SBER_FLAVOURED_ATTRS), ("ha", _HA_FLAVOURED_ATTRS)],
    )
    def test_allowed_values_stay_inside_the_documented_vocabulary(
        self, category: str, profile: str, attrs: dict[str, Any]
    ) -> None:
        """``allowed_values`` — то, что приложение рисует и присылает обратно.

        Объявленное значение вне словаря (как ``stop`` у пылесоса) даёт
        кнопку, которую облако никогда не нажмёт; вдобавок оно входит в
        ``model.id``, так что ошибка ещё и переселяет устройство из комнаты.
        """
        offenders: list[str] = []
        for state in _SENTINEL_STATES:
            entity = _probe(category, attrs, state)
            for key, descriptor in entity.create_allowed_values_list().items():
                if descriptor.get("type") != "ENUM":
                    continue
                declared = list(descriptor.get("enum_values", {}).get("values", []))
                vocabulary = FEATURE_ENUM_VALUES.get(key)
                if vocabulary is None:
                    if key not in _VOCABULARY_LESS_ENUM_FEATURES:
                        offenders.append(f"{state}/{key}: у функции нет словаря, объявлять нечего")
                    continue
                offenders.extend(f"{state}/{key}={value!r}" for value in declared if value not in vocabulary)
        assert offenders == [], f"{category} ({profile}) объявляет недокументированные значения: {offenders}"

    @pytest.mark.parametrize("category", sorted(CATEGORY_DOMAIN_MAP))
    def test_declared_enum_values_have_no_duplicates(self, category: str) -> None:
        """Повтор значения в ``allowed_values`` меняет ``model.id`` без причины.

        Облако перерегистрирует устройство и пользователь теряет назначенную
        комнату (история issue #44).
        """
        entity = _probe(category, _HA_FLAVOURED_ATTRS, "on")
        duplicated = [
            key
            for key, descriptor in entity.create_allowed_values_list().items()
            if descriptor.get("type") == "ENUM"
            and len(descriptor["enum_values"]["values"]) != len(set(descriptor["enum_values"]["values"]))
        ]
        assert duplicated == [], f"{category}: повторяющиеся значения в {duplicated}"
