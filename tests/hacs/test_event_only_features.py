"""Тесты правила событийных функций Sber (``EVENT_ONLY_FEATURES``, issue #61).

Что здесь защищается.

Сбер помечает часть функций галочкой «обязательная». Галочка означает
«функция обязана быть описана в МОДЕЛИ устройства», а не «функция обязана
присутствовать в каждой публикации состояния». Для функции ``pir``
документация Сбера говорит дословно: «pir — отправляется, когда обнаружено
движение». То есть у неё ровно одно допустимое значение (``pir``) и нет
значения «покой»: молчание и есть состояние покоя.

До правки валидатор требовал обязательные функции в каждой публикации и
поэтому красил в ошибку КАЖДЫЙ датчик движения в покое, хотя облако Сбера
эти устройства прекрасно принимало. Обратный риск не менее дорогой: если
исключение расползётся с ``pir`` на обычные функции (``on_off`` у света,
``open_state`` у ворот), валидатор перестанет ловить реальные молчаливые
отказы Сбера — устройство пропадёт из приложения, а DevTools покажет
«всё чисто».

Поэтому тесты ниже фиксируют не «примерно так», а точные множества:
исключение обязано касаться ровно ``pir``, ровно половины «публикация» и
никогда — половины «модель».
"""

from __future__ import annotations

from typing import Any

import pytest

from custom_components.sber_mqtt_bridge._generated.feature_types import FEATURE_TYPES
from custom_components.sber_mqtt_bridge._generated.obligatory_features import (
    CATEGORY_OBLIGATORY_FEATURES,
)
from custom_components.sber_mqtt_bridge._generated.reference_values import (
    FEATURE_ENUM_VALUES,
    FEATURE_RANGES,
)
from custom_components.sber_mqtt_bridge.devices.motion_sensor import MotionSensorEntity
from custom_components.sber_mqtt_bridge.schema_validator import (
    EVENT_ONLY_FEATURES,
    ValidationIssue,
    validate_publish,
)

DOCUMENTED_EVENT_ONLY = frozenset({"pir"})
"""Событийные функции по документации Sber на момент написания тестов.

Единственная функция, у которой словарь допустимых значений состоит ровно
из одного значения, — ``pir`` (страница «Датчик движения»). Ожидание взято
из документации, а не из текущего вывода кода: если генерация справочника
добавит новую такую функцию, тест обязан упасть и потребовать осознанного
решения, а не молча расширить исключение.
"""

FEATURES_WITH_QUIET_VALUE = frozenset(
    {
        "on_off",
        "online",
        "open_state",
        "doorcontact_state",
        "water_leak_state",
        "smoke_state",
        "gas_leak_state",
        "hvac_temp_set",
    }
)
"""Обязательные функции, у которых «покой» выражается значением.

У каждой из них есть чем сказать «ничего не происходит» (``false``,
``close``, ``0``), поэтому их отсутствие в публикации — настоящий дефект:
Сбер молча выбросит устройство. Ни одна из них не имеет права попасть в
``EVENT_ONLY_FEATURES``.
"""

MOTION_ENTITY_ID = "binary_sensor.hall_motion"
MOTION_DATA = {"entity_id": MOTION_ENTITY_ID, "name": "Hall motion"}


def _value_for(key: str) -> dict[str, Any]:
    """Собрать корректное по спецификации значение для функции ``key``.

    Значения строятся из сгенерированного справочника, чтобы вспомогательный
    код не порождал посторонних замечаний валидатора (тип, словарь, диапазон)
    и тесты падали только по существу проверяемого правила.

    Args:
        key: Имя функции Sber.

    Returns:
        Словарь ``value`` в формате протокола Sber.
    """
    type_ = FEATURE_TYPES.get(key, "BOOL")
    if type_ == "BOOL":
        return {"type": "BOOL", "bool_value": True}
    if type_ == "ENUM":
        vocabulary = FEATURE_ENUM_VALUES.get(key)
        enum_value = sorted(vocabulary)[0] if vocabulary else key
        return {"type": "ENUM", "enum_value": enum_value}
    if type_ == "INTEGER":
        low = FEATURE_RANGES.get(key, (0, 1))[0]
        return {"type": "INTEGER", "integer_value": str(int(low))}
    if type_ == "FLOAT":
        low = FEATURE_RANGES.get(key, (0.0, 1.0))[0]
        return {"type": "FLOAT", "float_value": float(low)}
    return {"type": type_, "string_value": "x"}


def _states(*keys: str) -> list[dict[str, Any]]:
    """Собрать список состояний Sber для перечисленных функций."""
    return [{"key": key, "value": _value_for(key)} for key in keys]


def _missing_obligatory(issues: list[ValidationIssue]) -> list[ValidationIssue]:
    """Отфильтровать замечания типа ``missing_obligatory``."""
    return [i for i in issues if i.type == "missing_obligatory"]


def _motion_entity(*, motion: bool) -> MotionSensorEntity:
    """Создать реальную сущность датчика движения в заданном состоянии.

    Args:
        motion: ``True`` — движение обнаружено, ``False`` — покой.

    Returns:
        Заполненный ``MotionSensorEntity``.
    """
    entity = MotionSensorEntity(dict(MOTION_DATA))
    entity.fill_by_ha_state(
        {
            "entity_id": MOTION_ENTITY_ID,
            "state": "on" if motion else "off",
            "attributes": {"device_class": "motion", "battery_level": 77},
        }
    )
    return entity


OBLIGATORY_PAIRS = [
    (category, feature)
    for category, features in sorted(CATEGORY_OBLIGATORY_FEATURES.items())
    for feature in sorted(features)
]
"""Все пары «категория Sber → её обязательная функция» из справочника."""


class TestEventOnlyFeatureSet:
    """Состав множества событийных функций."""

    def test_set_equals_documented_event_only_features(self) -> None:
        """Исключение обязано касаться ровно ``pir``.

        Прод: любая лишняя функция в этом множестве перестаёт требоваться в
        публикации — валидатор молчит, а Сбер выбрасывает устройство, и
        пользователь ищет причину вручную часами.
        """
        assert EVENT_ONLY_FEATURES == DOCUMENTED_EVENT_ONLY

    def test_set_is_derived_from_single_value_vocabulary(self) -> None:
        """Множество выводится из справочника, а не задано руками.

        Правило «ровно одно допустимое значение ⇒ нет значения покоя» —
        единственное обоснование исключения. Прод: список, набранный руками,
        разъедется с документацией при следующей генерации справочника.
        """
        single_valued = {name for name, values in FEATURE_ENUM_VALUES.items() if len(values) == 1}
        assert single_valued == set(EVENT_ONLY_FEATURES)

    def test_pir_vocabulary_has_exactly_one_value(self) -> None:
        """У ``pir`` в справочнике ровно одно значение — само ``pir``.

        Прод: если у Сбера появится второе значение (например «покой»),
        исключение станет неверным и датчики начнут врать о состоянии.
        """
        assert set(FEATURE_ENUM_VALUES["pir"]) == {"pir"}

    def test_features_with_quiet_value_are_never_event_only(self) -> None:
        """Функции, умеющие сказать «покой», обязаны остаться обязательными.

        Прод: попадание ``on_off`` или ``open_state`` в исключение отключает
        главную проверку валидатора — молчаливый отказ Сбера станет невидим.
        """
        assert EVENT_ONLY_FEATURES.isdisjoint(FEATURES_WITH_QUIET_VALUE)


class TestMotionSensorPublishIsClean:
    """Реальный датчик движения проходит валидацию (issue #61)."""

    def test_idle_motion_sensor_has_no_issues_at_all(self) -> None:
        """Датчик движения в покое даёт пустой список замечаний.

        Прод: именно эта картина у пользователя — 100% датчиков движения
        помечены красным «missing_obligatory: pir», хотя Салют показывает их
        в правильной категории и получает события.
        """
        entity = _motion_entity(motion=False)
        states = entity.to_sber_current_state()[MOTION_ENTITY_ID]["states"]
        assert "pir" not in {s["key"] for s in states}

        issues = validate_publish(
            entity_id=MOTION_ENTITY_ID,
            category="sensor_pir",
            states=states,
            declared_features=entity.get_final_features_list(),
        )
        assert issues == []

    def test_motion_detected_publish_has_no_issues_at_all(self) -> None:
        """При обнаружении движения публикация тоже полностью чиста.

        Прод: событие движения — единственное, ради чего датчик существует;
        замечание на нём означало бы, что валидатор не понимает протокол.
        """
        entity = _motion_entity(motion=True)
        states = entity.to_sber_current_state()[MOTION_ENTITY_ID]["states"]
        pir = next(s for s in states if s["key"] == "pir")
        assert pir["value"] == {"type": "ENUM", "enum_value": "pir"}

        issues = validate_publish(
            entity_id=MOTION_ENTITY_ID,
            category="sensor_pir",
            states=states,
            declared_features=entity.get_final_features_list(),
        )
        assert issues == []


class TestModelHalfIsStillEnforced:
    """Половина «модель» проверяется и для событийных функций."""

    def test_sensor_without_pir_in_model_is_an_error_about_the_model(self) -> None:
        """Не объявивший ``pir`` датчик — ошибка с текстом про модель.

        Прод: Сбер требует описать функцию в модели устройства. Без неё
        устройство не регистрируется вовсе, и текст замечания обязан вести
        разработчика к списку features, а не к содержимому публикации.
        """
        issues = validate_publish(
            entity_id=MOTION_ENTITY_ID,
            category="sensor_pir",
            states=_states("online"),
            declared_features=["online", "battery_percentage"],
        )
        missing = _missing_obligatory(issues)
        assert [i.key for i in missing] == ["pir"]
        assert missing[0].severity == "error"
        assert "missing from the device model" in missing[0].description
        assert "absent from the publish" not in missing[0].description

    def test_undeclared_and_unpublished_feature_reported_once(self) -> None:
        """Одна причина — одно замечание, без дублей.

        Прод: дубли по одному ключу раздувают панель DevTools и мешают
        отличить «одна поломка» от «две разных».
        """
        issues = validate_publish(
            entity_id="light.kitchen",
            category="light",
            states=_states("online"),
            declared_features=["online"],
        )
        missing = _missing_obligatory(issues)
        assert [i.key for i in missing] == ["on_off"]
        assert "missing from the device model" in missing[0].description


class TestOrdinaryObligatoryFeaturesStillRequiredInPublish:
    """Обычные обязательные функции по-прежнему нужны в каждой публикации."""

    @pytest.mark.parametrize(
        ("category", "entity_id", "feature", "declared"),
        [
            ("light", "light.kitchen", "on_off", ["online", "on_off"]),
            ("gate", "cover.gate", "open_state", ["online", "open_state", "open_set"]),
        ],
    )
    def test_declared_but_unpublished_feature_is_an_error_about_the_publish(
        self,
        category: str,
        entity_id: str,
        feature: str,
        declared: list[str],
    ) -> None:
        """Объявленная, но не опубликованная функция — ошибка про публикацию.

        Прод: свет без ``on_off`` и ворота без ``open_state`` Сбер молча
        выбрасывает; если исключение зацепит их, поломка станет невидимой.
        """
        issues = validate_publish(
            entity_id=entity_id,
            category=category,
            states=_states("online"),
            declared_features=declared,
        )
        missing = _missing_obligatory(issues)
        assert [i.key for i in missing] == [feature]
        assert missing[0].severity == "error"
        assert "absent from the publish" in missing[0].description
        assert "missing from the device model" not in missing[0].description


class TestDeclaredFeaturesNoneKeepsPublishCheck:
    """``declared_features=None`` отключает только проверку модели."""

    def test_publish_check_still_runs_without_declared_features(self) -> None:
        """Без списка features проверка публикации обязана работать.

        Прод: синтетические payload'ы и часть вызовов DevTools не знают
        features; если бы ``None`` глушил проверку, самый частый путь
        валидации стал бы декоративным.
        """
        issues = validate_publish(
            entity_id="light.kitchen",
            category="light",
            states=_states("online"),
            declared_features=None,
        )
        missing = _missing_obligatory(issues)
        assert [i.key for i in missing] == ["on_off"]
        assert "absent from the publish" in missing[0].description

    def test_event_only_exemption_survives_missing_declared_features(self) -> None:
        """Без списка features покой датчика движения по-прежнему чист.

        Прод: DevTools валидирует и «сырые» публикации без модели — датчики
        движения не должны краснеть и там.
        """
        issues = validate_publish(
            entity_id=MOTION_ENTITY_ID,
            category="sensor_pir",
            states=_states("online"),
            declared_features=None,
        )
        assert _missing_obligatory(issues) == []


class TestExemptionIsNarrow:
    """Исключение не превращает ``pir`` в непроверяемую функцию."""

    def test_published_pir_with_foreign_value_is_still_rejected(self) -> None:
        """Опубликованное чужое значение ``pir`` по-прежнему ошибка.

        Прод: исключение касается только отсутствия ключа. Значение вне
        словаря Сбера облако маршрутизировать не умеет, и такое замечание
        обязано остаться.
        """
        issues = validate_publish(
            entity_id=MOTION_ENTITY_ID,
            category="sensor_pir",
            states=[
                {"key": "online", "value": {"type": "BOOL", "bool_value": True}},
                {"key": "pir", "value": {"type": "ENUM", "enum_value": "motion"}},
            ],
            declared_features=["online", "pir"],
        )
        unknown = [i for i in issues if i.type == "unknown_enum_value"]
        assert [i.key for i in unknown] == ["pir"]
        assert unknown[0].severity == "error"

    def test_event_only_feature_is_not_exempt_in_a_foreign_category(self) -> None:
        """В чужой категории ``pir`` остаётся незаявленной функцией.

        Прод: исключение не должно превращать ``pir`` в «разрешено везде» —
        публикация ``pir`` от лампы обязана быть замечена.
        """
        issues = validate_publish(
            entity_id="light.kitchen",
            category="light",
            states=[
                {"key": "online", "value": {"type": "BOOL", "bool_value": True}},
                {"key": "on_off", "value": {"type": "BOOL", "bool_value": True}},
                {"key": "pir", "value": {"type": "ENUM", "enum_value": "pir"}},
            ],
            declared_features=["online", "on_off"],
        )
        assert {i.type for i in issues if i.key == "pir"} == {
            "unknown_for_category",
            "not_declared",
        }


class TestPublishExemptionScopeAcrossAllCategories:
    """Полный обход справочника: пропуск публикации ровно для событийных."""

    @pytest.mark.parametrize(("category", "feature"), OBLIGATORY_PAIRS)
    def test_publish_check_skipped_only_for_event_only_features(self, category: str, feature: str) -> None:
        """Для каждой пары «категория → обязательная функция»: пропуск ⇔ событийная.

        Ожидание берётся из документации (:data:`DOCUMENTED_EVENT_ONLY`), а не
        из константы кода, — иначе расширенное правило «объяснило» бы само себя.

        Прод: тихое расширение правила (ещё одна функция в исключении, ошибка
        в условии) снимает проверку с реальных устройств — Сбер выбрасывает их
        молча, а панель показывает «всё чисто».
        """
        obligatory = sorted(CATEGORY_OBLIGATORY_FEATURES[category])
        published = [f for f in obligatory if f != feature]
        issues = validate_publish(
            entity_id=f"test.{category}",
            category=category,
            states=_states(*published),
            declared_features=obligatory,
        )
        reported = {i.key for i in _missing_obligatory(issues)}
        should_be_skipped = feature in DOCUMENTED_EVENT_ONLY
        assert (feature not in reported) is should_be_skipped

    def test_skipped_set_equals_event_only_features_exactly(self) -> None:
        """Множество «пропущено в публикации» в точности равно ``EVENT_ONLY_FEATURES``.

        Прод: агрегирующая проверка — ни одна лишняя функция не выпала из-под
        контроля и ни одна событийная не осталась требуемой (иначе датчики
        движения снова покраснеют).
        """
        skipped: set[str] = set()
        for category, feature in OBLIGATORY_PAIRS:
            obligatory = sorted(CATEGORY_OBLIGATORY_FEATURES[category])
            published = [f for f in obligatory if f != feature]
            issues = validate_publish(
                entity_id=f"test.{category}",
                category=category,
                states=_states(*published),
                declared_features=obligatory,
            )
            if feature not in {i.key for i in _missing_obligatory(issues)}:
                skipped.add(feature)
        assert skipped == set(EVENT_ONLY_FEATURES)
