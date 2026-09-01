"""Documented ENUM vocabularies and numeric ranges: tables + validator.

Two more relations were being scraped and thrown away.  ``tools/codegen.py``
now renders both into :mod:`_generated.reference_values`, and
``schema_validator`` uses them:

* ``unknown_enum_value`` — the device sent an ENUM value Sber never
  documented, so the cloud has nothing to route it to;
* ``out_of_range`` — a number outside the function's documented bounds.

**Where the vocabulary comes from matters.**  It is read off each
*function* page, not off the ``allowed_values`` block of a category page.
The category block is an illustrative example and is routinely shorter:
the ``hvac_air_flow_power`` examples omit ``quiet``, which the function
page lists and real air purifiers use.  Validating against the example
would reject correct devices — :meth:`TestVocabularyComesFromFunctionPages
.test_quiet_is_accepted` is the standing proof.
"""

from __future__ import annotations

from typing import ClassVar

import pytest

from custom_components.sber_mqtt_bridge._generated.feature_types import FEATURE_TYPES
from custom_components.sber_mqtt_bridge._generated.reference_values import FEATURE_ENUM_VALUES, FEATURE_RANGES
from custom_components.sber_mqtt_bridge.schema_validator import validate_publish


def _issue_types(category: str, key: str, value: dict) -> list[str]:
    """Return issue types raised for a single state, ignoring unrelated ones.

    Args:
        category: Sber category.
        key: Feature name.
        value: Sber value dict.

    Returns:
        Types of the two value-level issues this module is about.
    """
    issues = validate_publish(entity_id="probe", category=category, states=[{"key": key, "value": value}])
    return [i.type for i in issues if i.type in ("unknown_enum_value", "out_of_range")]


class TestGeneratedTables:
    """The tables must be usable, and honest about what they don't know."""

    def test_enum_vocabularies_are_populated(self) -> None:
        """Словари извлеклись почти для всех ENUM-функций.

        Если извлечение сломается (Sber переверстает страницы), таблица
        молча опустеет, правило перестанет срабатывать, и мы снова начнём
        отправлять в облако значения, которых оно не знает, — без единой
        жалобы. Порог намеренно ниже фактических 44, чтобы тест не падал
        от одной новой функции, но ловил обвал.
        """
        enum_features = {name for name, kind in FEATURE_TYPES.items() if kind == "ENUM"}
        with_vocabulary = enum_features & set(FEATURE_ENUM_VALUES)
        assert len(with_vocabulary) >= 40, (
            f"словарей всего {len(with_vocabulary)} на {len(enum_features)} ENUM-функций — "
            "похоже, извлечение со страниц функций сломалось"
        )

    def test_no_vocabulary_for_non_enum_features(self) -> None:
        """Словарь у не-ENUM функции означал бы ошибку разбора страницы."""
        wrong = sorted(name for name in FEATURE_ENUM_VALUES if FEATURE_TYPES.get(name) != "ENUM")
        assert wrong == [], f"словарь у не-ENUM функций: {wrong}"

    def test_category_names_did_not_leak_into_vocabularies(self) -> None:
        """Список «Устройства с этой функцией» не должен попасть в словарь.

        Он свёрстан теми же строками «слово — описание», что и значения,
        и стоит сразу под ними. Если ограничитель разбора съедет, в
        словарь попадут имена категорий, правило станет слишком
        снисходительным и перестанет ловить настоящие расхождения.

        Проверяется на ``hvac_air_flow_power``: под его словарём стоит
        список из пяти категорий (``hvac_ac``, ``hvac_fan`` и прочие),
        ни одна из которых значением быть не может. Сверять весь словарь
        со всеми именами категорий нельзя — ``tv`` законное значение
        функции ``source`` и одновременно имя категории.
        """
        vocabulary = FEATURE_ENUM_VALUES["hvac_air_flow_power"]
        assert vocabulary == frozenset({"auto", "high", "low", "medium", "quiet", "turbo"})
        leaked = sorted(vocabulary & {"hvac_ac", "hvac_air_purifier", "hvac_fan", "hvac_heater", "hvac_humidifier"})
        assert leaked == [], f"имена категорий просочились в словарь: {leaked}"

    def test_ranges_are_ordered_pairs(self) -> None:
        """Диапазон обязан быть парой «нижняя ≤ верхняя»."""
        broken = sorted(name for name, (low, high) in FEATURE_RANGES.items() if low > high)
        assert broken == [], f"перевёрнутые диапазоны: {broken}"

    def test_known_ranges(self) -> None:
        """Точечная сверка нескольких диапазонов с документацией."""
        assert FEATURE_RANGES["humidity"] == (0.0, 100.0)
        assert FEATURE_RANGES["air_pressure"] == (200.0, 800.0)
        assert FEATURE_RANGES["hvac_temp_set"] == (5.0, 50.0)


class TestVocabularyComesFromFunctionPages:
    """Эталон — страница функции, а не пример на странице категории."""

    def test_quiet_is_accepted(self) -> None:
        """``quiet`` законен, хотя примера с ним на страницах категорий нет.

        Правила проекта (CLAUDE.md) прямо перечисляют ``quiet`` среди
        значений ``hvac_air_flow_power``, и страница функции его
        подтверждает. Если тест упадёт, значит эталон снова берётся из
        неполного примера категории — и мост начнёт браковать исправные
        очистители и вентиляторы.
        """
        assert "quiet" in FEATURE_ENUM_VALUES["hvac_air_flow_power"]
        assert _issue_types("hvac_fan", "hvac_air_flow_power", {"type": "ENUM", "enum_value": "quiet"}) == []

    def test_screencast_is_accepted(self) -> None:
        """У ``source`` в примере категории 8 значений, на странице функции 9."""
        assert "screencast" in FEATURE_ENUM_VALUES["source"]


class TestUnknownEnumValue:
    """Значение вне словаря — ошибка."""

    def test_ha_source_name_is_rejected(self) -> None:
        """Имя источника из Home Assistant Sber не понимает.

        ``HDMI 1`` — это подпись из интерфейса HA; протокол знает только
        ``hdmi1``. Облако не может смаршрутизировать значение, которого
        не знает, и переключение источника у телевизора не работает.
        """
        assert _issue_types("tv", "source", {"type": "ENUM", "enum_value": "HDMI 1"}) == ["unknown_enum_value"]

    def test_documented_value_is_clean(self) -> None:
        """Задокументированное значение проходит без замечаний."""
        assert _issue_types("tv", "source", {"type": "ENUM", "enum_value": "hdmi1"}) == []

    def test_feature_without_vocabulary_is_never_flagged(self) -> None:
        """Нет словаря — нет и проверки: «неизвестно» не значит «запрещено».

        Две командные ENUM-функции документированы иначе, и словарь у них
        не извлекается. Ругаться на них — значит сыпать ложными ошибками
        в журнал.
        """
        assert "unlock" not in FEATURE_ENUM_VALUES
        assert _issue_types("intercom", "unlock", {"type": "ENUM", "enum_value": "unlock"}) == []

    def test_non_enum_payload_is_ignored(self) -> None:
        """Проверка словаря не трогает значения других типов."""
        assert _issue_types("tv", "source", {"type": "STRING", "string_value": "HDMI 1"}) == []


class TestOutOfRange:
    """Число вне документированных границ — предупреждение."""

    @pytest.mark.parametrize("sent", ["101", "-1", "1000"])
    def test_outside_is_flagged(self, sent: str) -> None:
        """Влажность вне 0…100 будет отброшена или обрезана облаком."""
        assert _issue_types("sensor_temp", "humidity", {"type": "INTEGER", "integer_value": sent}) == ["out_of_range"]

    @pytest.mark.parametrize("sent", ["0", "50", "100"])
    def test_boundaries_are_inclusive(self, sent: str) -> None:
        """Границы включительны — 0 и 100 законная влажность.

        Исключительная граница забраковала бы полностью сухой и
        полностью влажный датчик, то есть штатные показания.
        """
        assert _issue_types("sensor_temp", "humidity", {"type": "INTEGER", "integer_value": sent}) == []

    def test_severity_is_a_warning(self) -> None:
        """Выход за диапазон — предупреждение, а не ошибка.

        Граница описывает функцию, а не устройство: розетка на холостом
        ходу честно сообщает 0 Вт при задокументированном минимуме 10.
        Ошибкой это сделало бы журнал бесполезным.
        """
        issues = validate_publish(
            entity_id="probe",
            category="sensor_temp",
            states=[{"key": "humidity", "value": {"type": "INTEGER", "integer_value": "150"}}],
        )
        out = [i for i in issues if i.type == "out_of_range"]
        assert len(out) == 1
        assert out[0].severity == "warning"
        assert out[0].details == {"sent": 150.0, "min": 0.0, "max": 100.0}

    def test_unparsable_number_is_left_to_the_type_check(self) -> None:
        """Мусор вместо числа — не наша забота, а проверки типов."""
        assert _issue_types("sensor_temp", "humidity", {"type": "INTEGER", "integer_value": "не число"}) == []

    def test_feature_without_range_is_never_flagged(self) -> None:
        """Функция без задокументированного диапазона не проверяется.

        Диапазоны есть далеко не у всех: их 29 на 96 функций. Для
        остальных проверка обязана молчать, а не считать отсутствие
        границ нулевыми границами — иначе любое значение стало бы
        «выходящим за диапазон».
        """
        assert "on_off" not in FEATURE_RANGES
        assert _issue_types("light", "on_off", {"type": "INTEGER", "integer_value": "999999"}) == []


class TestKnownOffenders:
    """Долг, который правило вскрыло: он зафиксирован и не должен расти."""

    KNOWN: ClassVar[dict[str, list[str]]] = {}
    """Категории и функции, чьи значения расходятся со словарём Sber.

    Список пуст — долг закрыт. Было два должника:

    * ``tv``/``source`` — отдавались подписи источников из HA ("HDMI 1")
      вместо словаря протокола (hdmi1, tv, av, …);
    * ``vacuum_cleaner`` — ``vacuum_cleaner_program`` собирался из имён
      скоростей вентилятора HA ("Silent", "Turbo") вместо
      perimeter/spot/smart/random_route, а ``vacuum_cleaner_status`` — из
      standby/go_home/error, которых в документации Sber нет вовсе.

    Обе категории теперь сопоставляют значения через
    ``devices/utils/enum_matcher.py`` и не объявляют функцию, если ни одно
    значение сопоставить не удалось. Пустой словарь — не разрешение
    добавлять сюда новых нарушителей: каждая запись означает устройство,
    чьи значения облако не понимает."""

    def test_offender_list_is_exhaustive(self) -> None:
        """Новых нарушителей появиться не должно.

        Тест не «разрешает» текущие расхождения — он делает их видимыми и
        не даёт списку молча вырасти. Каждая новая категория здесь
        означает устройство, чьи значения облако не понимает.
        """
        from custom_components.sber_mqtt_bridge.sber_entity_map import CATEGORY_DOMAIN_MAP

        probe_attrs = {
            "source_list": ["HDMI 1", "TV"],
            "source": "HDMI 1",
            "fan_speed_list": ["Silent", "Turbo"],
            "fan_speed": "Silent",
            "current_position": 60,
            "current_temperature": 21,
            "temperature": 21,
            "humidity": 45,
            "brightness": 128,
            "battery_level": 77,
        }
        offenders: dict[str, list[str]] = {}
        for category, spec in CATEGORY_DOMAIN_MAP.items():
            device_class = (spec.device_classes or ("",))[0]
            entity = spec.cls(
                {
                    "entity_id": f"{spec.domains[0]}.probe",
                    "name": "Probe",
                    "original_device_class": device_class,
                    "device_class": device_class,
                }
            )
            entity.fill_by_ha_state({"state": "on", "attributes": {**probe_attrs, "device_class": device_class}})
            payload = entity.to_sber_current_state()
            states = next(iter(payload.values())).get("states", [])
            # ``issue.key`` may be a ``SberFeature`` enum member — compare
            # as plain strings so the expectation reads as protocol names.
            keys = sorted(
                {
                    str(issue.key)
                    for issue in validate_publish(entity_id="probe", category=category, states=states)
                    if issue.type == "unknown_enum_value"
                }
            )
            if keys:
                offenders[category] = keys

        assert offenders == self.KNOWN, (
            f"список категорий, отправляющих незнакомые Sber значения, изменился — стало {offenders}, было {self.KNOWN}"
        )
