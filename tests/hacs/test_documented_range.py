"""Тесты общего хелпера ``devices/utils/documented_range.py``.

Хелпер существует ради одного правила Sber: числовой диапазон функции
задан на её странице, а ``allowed_values`` разрешено этот диапазон
только **сокращать**. Home Assistant про это правило не знает, поэтому
пересечение «возможности HA ∩ документированный диапазон» приходится
делать нам — и делать в одном месте, иначе следующая категория снова
уедет в облако с чужими границами.

Границы здесь никогда не набираются руками: сверка идёт с
``_generated/reference_values.FEATURE_RANGES`` и с
``schema_validator._documented_bounds`` — переписанная копия константы
была бы вторым источником истины, который молча протухает.
"""

from __future__ import annotations

import math

import pytest

from custom_components.sber_mqtt_bridge._generated.reference_values import FEATURE_RANGES
from custom_components.sber_mqtt_bridge.devices.utils.documented_range import (
    clamp_to_bounds,
    documented_bounds,
    documented_integer_bounds,
    narrowed_bounds,
)
from custom_components.sber_mqtt_bridge.schema_validator import (
    _CATEGORY_RANGE_SANCTIONED,
    _documented_bounds,
)


class TestDocumentedBounds:
    """``documented_bounds`` обязан отвечать ровно то же, что валидатор."""

    @pytest.mark.parametrize("key", sorted(FEATURE_RANGES))
    def test_every_documented_feature_matches_the_validator(self, key: str) -> None:
        """Хелпер и валидатор судят по одной таблице.

        Если тест упадёт: клампинг начнёт приводить значения к одному
        диапазону, а валидатор — ругаться на другой. Пользователь получит
        устройство, которое мост сам же помечает как неисправное, и
        предупреждение, по которому ничего нельзя сделать.
        """
        assert documented_bounds("hvac_ac", key) == _documented_bounds("hvac_ac", key)

    def test_feature_without_a_documented_range_returns_none(self) -> None:
        """Незнакомая функция — «диапазон неизвестен», а не «ничего нельзя».

        Если тест упадёт: функция, для которой Sber диапазон не
        публикует, начнёт клампиться к выдуманным границам — значение,
        которое устройство сообщает честно, окажется искажённым.
        """
        assert documented_bounds("hvac_ac", "on_off") is None

    def test_category_example_wider_than_the_function_page_wins(self) -> None:
        """Бойлеру разрешён потолок из его собственного примера у Sber.

        Если тест упадёт: горячие уставки бойлера (до 80 °C) начнут
        обрезаться до 50 °C, хотя эталонная модель самого Sber объявляет
        80 — пользователь недосчитается горячей воды.
        """
        assert ("hvac_boiler", "hvac_temp_set") in _CATEGORY_RANGE_SANCTIONED
        assert documented_bounds("hvac_boiler", "hvac_temp_set")[1] > documented_bounds("hvac_ac", "hvac_temp_set")[1]


class TestClampToBounds:
    """``clamp_to_bounds`` — одно число, притянутое к границам."""

    @pytest.mark.parametrize(
        ("value", "expected"),
        [(60.0, 50.0), (0.0, 5.0), (22.0, 22.0), (5.0, 5.0), (50.0, 50.0)],
    )
    def test_value_is_pulled_to_the_nearest_bound(self, value: float, expected: float) -> None:
        """Значение вне диапазона становится ближайшей границей.

        Если тест упадёт: в ``up/status`` уедет число, которое облако не
        обязано принимать, — устройство выглядит живым, а его значения в
        приложении «залипают».
        """
        assert clamp_to_bounds(value, (5.0, 50.0)) == expected

    def test_unknown_range_leaves_the_value_alone(self) -> None:
        """Без документированного диапазона число не трогают.

        Если тест упадёт: значения функций, диапазон которых Sber не
        публикует, начнут искажаться на ровном месте.
        """
        assert clamp_to_bounds(1234.0, None) == 1234.0

    def test_nan_is_passed_through_rather_than_invented(self) -> None:
        """``NaN`` не превращается в границу диапазона.

        Мусорное число из HA (шаблонный сенсор с делением на ноль) — не
        показание устройства. Если тест упадёт: мост начнёт публиковать
        выдуманные 5 °C там, где на самом деле нет никакого показания.
        """
        assert math.isnan(clamp_to_bounds(float("nan"), (5.0, 50.0)))


class TestNarrowedBounds:
    """``narrowed_bounds`` — пересечение «HA ∩ документация»."""

    def test_ha_range_is_intersected_with_the_documented_one(self) -> None:
        """Потолок 75 °C из HA сужается до документированных 50.

        Если тест упадёт: модель объявит Сберу диапазон шире
        документированного — облако вправе отвергнуть её целиком, и
        устройство не появится в приложении.
        """
        assert narrowed_bounds("hvac_ac", "hvac_temp_set", 30.0, 75.0) == (30.0, 50.0)

    def test_range_inside_the_documented_one_is_untouched(self) -> None:
        """Законные границы HA остаются как есть.

        Если тест упадёт: сужение начнёт отбирать у пользователя
        температуры, которые устройство поддерживает.
        """
        assert narrowed_bounds("hvac_ac", "hvac_temp_set", 16.0, 32.0) == (16.0, 32.0)

    def test_non_overlapping_range_falls_back_to_the_documented_one(self) -> None:
        """Бессмысленные 0…0 из HA дают полный документированный диапазон.

        Если тест упадёт: устройство объявит схлопнутый диапазон вроде
        ``5…5`` — ползунок температуры в приложении невозможно сдвинуть.
        """
        assert narrowed_bounds("hvac_ac", "hvac_temp_set", 0.0, 0.0) == (5.0, 50.0)

    def test_unknown_feature_passes_ha_bounds_through(self) -> None:
        """Без документированного диапазона границы HA не трогают.

        Если тест упадёт: функции без опубликованного диапазона начнут
        терять законные границы устройства.
        """
        assert narrowed_bounds("hvac_ac", "on_off", -5.0, 500.0) == (-5.0, 500.0)


class TestDocumentedIntegerBounds:
    """``documented_integer_bounds`` — то же, но целыми числами внутрь."""

    def test_rounding_goes_inwards(self) -> None:
        """Нижняя граница округляется вверх, верхняя — вниз.

        Если тест упадёт: округление расширит тот самый диапазон, ради
        сужения которого хелпер и написан.
        """
        assert documented_integer_bounds("hvac_ac", "hvac_temp_set", 16.4, 32.6) == (17, 32)

    def test_collapsed_range_falls_back_to_the_documented_one(self) -> None:
        """Диапазон уже одного градуса не схлопывается в пустоту.

        Если тест упадёт: ``allowed_values`` получит ``min`` больше
        ``max`` — описание модели станет бессмысленным, и облако вправе
        отвергнуть устройство целиком.
        """
        low, high = documented_integer_bounds("hvac_ac", "hvac_temp_set", 20.2, 20.4)
        assert low <= high

    def test_boiler_keeps_its_sanctioned_ceiling(self) -> None:
        """Бойлер сохраняет 80 °C, разрешённые примером Sber.

        Если тест упадёт: клампинг разойдётся с валидатором, и бойлер,
        собранный по эталону Sber, начнёт терять горячие уставки.
        """
        assert documented_integer_bounds("hvac_boiler", "hvac_temp_set", 0.0, 100.0) == (5, 80)
