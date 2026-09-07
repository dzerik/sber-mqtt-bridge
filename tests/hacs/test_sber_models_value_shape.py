"""Форма значения выводится из документированного типа функции.

До этих тестов каждый класс устройства сам решал, каким конструктором
собрать ``value``: ``make_bool_value`` / ``make_integer_value`` /
``make_enum_value`` / ``make_colour_value``.  Конструктора для FLOAT в
``sber_models`` вообще не было, поэтому автор чайника взял ближайший —
INTEGER, — и ``kitchen_water_level`` два года уезжал в облако в чужом
конверте.  Ошибка такого рода не видна ни в ревью, ни в журнале: облако
читает поле, названное типом, и просто не находит значения.

Здесь проверяется другой порядок: тип берётся из
``_generated/feature_types.py`` (снапшот документации), а
:func:`make_state` сверяет с ним всё, что собрали руками.
"""

from __future__ import annotations

import logging
import math
from typing import Any

import pytest

from custom_components.sber_mqtt_bridge._generated.feature_types import FEATURE_TYPES
from custom_components.sber_mqtt_bridge._generated.value_envelope import (
    VALUE_FIELD_BY_TYPE,
    VALUE_FIELD_JSON_TYPES,
)
from custom_components.sber_mqtt_bridge.sber_models import (
    _VALUE_BUILDERS,
    SberState,
    make_bool_value,
    make_float_value,
    make_integer_value,
    make_state,
    make_state_for,
    make_string_value,
    make_typed_value,
    make_value_for,
)

_RAW_BY_TYPE: dict[str, Any] = {
    "BOOL": True,
    "INTEGER": 42,
    "FLOAT": 1.7,
    "STRING": "текст",
    "ENUM": "auto",
    "COLOUR": {"h": 12, "s": 500, "v": 700},
}
"""Обычное питоновское значение для каждого типа Sber.

Именно такие значения и держат классы устройств у себя в полях: ``bool``,
число, строка, тройка HSV."""


class TestBuildersCoverTheDocumentedTypes:
    """Конструктор есть для каждого типа, который знает документация."""

    def test_every_documented_type_has_a_builder(self) -> None:
        """У каждого типа из ``VALUE_FIELD_BY_TYPE`` есть свой конструктор.

        Прод: пропущенный конструктор — это ровно та дыра, из-за которой
        появился дефект уровня воды.  Автор нового класса устройства не
        найдёт нужного ``make_*_value``, возьмёт похожий, и значение
        молча исчезнет в облаке.  Если тест упадёт — в документации
        появился тип, который мост собрать не умеет.
        """
        assert set(_VALUE_BUILDERS) == set(VALUE_FIELD_BY_TYPE)

    @pytest.mark.parametrize("value_type", sorted(_RAW_BY_TYPE))
    def test_builder_emits_type_plus_its_own_payload_key(self, value_type: str) -> None:
        """Собранное значение — это ``type`` плюс ровно одно поле по типу.

        Прод: лишний или чужой ключ в ``value`` облако не читает, а может
        и отбросить устройство целиком.
        """
        value = make_typed_value(value_type, _RAW_BY_TYPE[value_type])
        assert set(value) == {"type", VALUE_FIELD_BY_TYPE[value_type]}
        assert value["type"] == value_type

    def test_unknown_type_is_refused(self) -> None:
        """Неизвестный тип — ошибка, а не пакет с выдуманным ключом.

        Прод: опечатка в имени типа не должна превращаться в тихо
        отброшенное облаком значение.
        """
        with pytest.raises(ValueError, match="unknown Sber value type"):
            make_typed_value("DOUBLE", 1)


class TestPayloadJsonTypes:
    """Поле полезной нагрузки несёт тот тип JSON, который описан у Sber."""

    def test_integer_goes_on_the_wire_as_a_quoted_string(self) -> None:
        """``integer_value`` — строка, а не число.

        Прод: ``{"integer_value": 42}`` числом проходит все наши проверки
        и молча отвергается облаком — значение «залипает».
        """
        assert make_integer_value(42) == {"type": "INTEGER", "integer_value": "42"}
        assert make_value_for("hvac_temp_set", 22.9) == {"type": "INTEGER", "integer_value": "22"}

    def test_float_goes_on_the_wire_as_a_number(self) -> None:
        """``float_value`` — число, а не строка.

        Прод: закавыченный FLOAT облако не читает — уровень воды в
        приложении остаётся пустым.
        """
        assert make_float_value(1.7) == {"type": "FLOAT", "float_value": 1.7}

    @pytest.mark.parametrize("broken", [float("nan"), float("inf"), -float("inf")])
    def test_non_finite_float_is_refused(self, broken: float) -> None:
        """``NaN`` и ``Infinity`` в FLOAT — ошибка на месте сборки.

        Прод: это расширения Python, а не JSON.  Одно такое число ценой
        не в одно устройство, а во весь пакет ``up/status`` — брокер
        отвергает сообщение целиком, и в приложении замирают все
        устройства сразу.
        """
        with pytest.raises(ValueError, match="finite"):
            make_float_value(broken)

    @pytest.mark.parametrize("value_type", sorted(_RAW_BY_TYPE))
    def test_payload_matches_the_documented_json_type(self, value_type: str) -> None:
        """Тип JSON поля совпадает с ``VALUE_FIELD_JSON_TYPES``.

        Прод: строка вместо числа (и наоборот) — самая дешёвая на вид и
        самая незаметная ошибка: устройство в приложении есть, значения
        не меняются.
        """
        field = VALUE_FIELD_BY_TYPE[value_type]
        payload = make_typed_value(value_type, _RAW_BY_TYPE[value_type])[field]
        expected = VALUE_FIELD_JSON_TYPES[field]
        if expected == "string":
            assert isinstance(payload, str)
        elif expected == "boolean":
            assert isinstance(payload, bool)
        elif expected == "number":
            assert isinstance(payload, int | float)
            assert not isinstance(payload, bool)
        else:
            assert isinstance(payload, dict)


class TestValueForFollowsTheDocumentation:
    """``make_value_for`` берёт тип из справочника, а не у автора класса."""

    @pytest.mark.parametrize("feature", sorted(FEATURE_TYPES))
    def test_every_documented_feature_gets_its_documented_type(self, feature: str) -> None:
        """Для каждой функции справочника конверт собирается по типу оттуда.

        Прод: это и есть страховка от повторения дефекта уровня воды —
        класс устройства больше не выбирает тип сам.
        """
        documented = FEATURE_TYPES[feature]
        value = make_value_for(feature, _RAW_BY_TYPE[documented])
        assert value["type"] == documented
        assert set(value) == {"type", VALUE_FIELD_BY_TYPE[documented]}
        SberState.model_validate({"key": feature, "value": value})

    def test_water_level_is_float(self) -> None:
        """``kitchen_water_level`` собирается FLOAT, как в документации.

        Прод: именно здесь чайник и ошибался.  INTEGER-конверт облако не
        читает, и уровень воды в приложении Сбера пуст.
        """
        assert make_value_for("kitchen_water_level", 1.7) == {"type": "FLOAT", "float_value": 1.7}

    def test_undocumented_feature_is_refused(self) -> None:
        """Незнакомая функция — ошибка, а не угаданный тип.

        Прод: у недокументированной функции документированного типа нет;
        угадать его — значит снова тихо разойтись с облаком.  Такой
        случай обязан быть виден автору сразу.
        """
        with pytest.raises(ValueError, match="not in the documented catalogue"):
            make_value_for("kitchen_water_pressure", 1)

    def test_state_shorthand_matches_the_long_form(self) -> None:
        """``make_state_for`` — это ``make_state`` + ``make_value_for``.

        Прод: короткая форма нужна, чтобы имя функции не повторялось
        дважды — повтор рано или поздно расходится.
        """
        assert make_state_for("kitchen_water_level", 1.7) == make_state(
            "kitchen_water_level", make_value_for("kitchen_water_level", 1.7)
        )


class TestMakeStateGuardsTheDocumentedType:
    """``make_state`` — узкое место, через которое проходят все состояния."""

    def test_matching_value_passes_through_untouched(self) -> None:
        """Правильно собранное значение не трогается.

        Прод: сторож не должен «чинить» то, что и так верно, — иначе он
        сам станет источником расхождений.
        """
        value = make_bool_value(True)
        assert make_state("on_off", value)["value"] is value

    def test_wrong_but_convertible_type_is_repaired_and_logged(self, caplog: pytest.LogCaptureFixture) -> None:
        """INTEGER, отданный под FLOAT-функцию, переупаковывается и попадает в журнал.

        Прод: это буквально дефект чайника.  Теперь такая ошибка не
        доезжает до облака — в эфир уходит документированный конверт, — а
        разработчик видит в журнале строку с именем функции вместо
        безмолвно пустого значения в приложении.
        """
        with caplog.at_level(logging.ERROR):
            state = make_state("kitchen_water_level", make_integer_value(20))
        assert state["value"] == {"type": "FLOAT", "float_value": 20.0}
        assert "kitchen_water_level" in caplog.text

    def test_text_and_enum_are_interchangeable(self) -> None:
        """STRING под ENUM-функцию переупаковывается: несут одни и те же символы.

        Прод: словарь значений сторожит другой тест; здесь важно, что
        конверт доедет правильным.
        """
        state = make_state("hvac_work_mode", make_string_value("auto"))
        assert state["value"] == {"type": "ENUM", "enum_value": "auto"}

    def test_incompatible_type_is_left_alone_and_logged(self, caplog: pytest.LogCaptureFixture) -> None:
        """BOOL под ENUM-функцию не переделывается — только жалоба в журнал.

        Прод: у булева значения нет осмысленного ENUM-написания.
        Придумать его — значит отправить правдоподобное, но неверное
        значение; лучше оставить как есть и написать об этом громко,
        чтобы дефект чинили в классе устройства.
        """
        with caplog.at_level(logging.ERROR):
            state = make_state("hvac_work_mode", make_bool_value(True))
        assert state["value"] == {"type": "BOOL", "bool_value": True}
        assert "hvac_work_mode" in caplog.text

    def test_unknown_feature_is_passed_through(self) -> None:
        """Незнакомая функция проходит как есть, без выдумок.

        Прод: справочник документации неполон, и мост обязан уметь
        публиковать функцию, которой в нём нет, — «неизвестно» никогда не
        значит «запрещено».
        """
        value = make_integer_value(5)
        assert make_state("kitchen_water_pressure", value)["value"] is value

    def test_non_dict_value_is_passed_through(self) -> None:
        """Значение не-словарь не роняет сборку состояния.

        Прод: сторож стоит на пути публикации всех устройств; падение
        здесь стоило бы всего пакета ``up/status``, а не одного значения.
        """
        assert make_state("on_off", None)["value"] is None  # type: ignore[arg-type]


class TestColourValues:
    """COLOUR принимает и словарь, и тройку HSV."""

    def test_triple_and_mapping_agree(self) -> None:
        """Тройка ``(h, s, v)`` и словарь дают один и тот же конверт.

        Прод: конвертер цвета отдаёт то одно, то другое; расхождение
        здесь означало бы лампу, которая меняет цвет в HA и не меняет в
        приложении Сбера.
        """
        assert make_value_for("light_colour", (12, 500, 700)) == make_value_for(
            "light_colour", {"h": 12, "s": 500, "v": 700}
        )

    def test_incomplete_colour_is_refused(self) -> None:
        """Цвет без одной компоненты — ошибка, а не нулевая подстановка.

        Прод: подставленный ноль в ``v`` — это выключенная лампа при
        документированном минимуме 100.
        """
        with pytest.raises(ValueError, match="missing"):
            make_value_for("light_colour", {"h": 12, "s": 500})


def test_integer_conversion_matches_the_parser_used_by_devices() -> None:
    """Дробное число в INTEGER усекается так же, как в ``_safe_int_parser``.

    Прод: разное округление в двух местах даёт значение, которое в
    журнале одно, а в облаке другое, — и разбирательство на пустом месте.
    """
    assert make_value_for("hvac_temp_set", 22.9)["integer_value"] == "22"
    assert make_value_for("hvac_temp_set", "22.9")["integer_value"] == "22"


@pytest.mark.parametrize("broken", [float("nan"), float("inf")])
def test_non_finite_number_never_reaches_an_integer_value(broken: float) -> None:
    """Нечисловой ``float`` не превращается в INTEGER, а даёт ошибку.

    Прод: ``int(float('nan'))`` роняет сборку состояния с ValueError, а
    ``sber_protocol`` ловит его и выбрасывает устройство из пакета —
    пользователь видит «устройство пропало» без единой внятной строки в
    журнале.  Ошибка на месте сборки называет функцию.
    """
    assert not math.isfinite(broken)
    with pytest.raises(ValueError, match="finite"):
        make_value_for("hvac_temp_set", broken)
