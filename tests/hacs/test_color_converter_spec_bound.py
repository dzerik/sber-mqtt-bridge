"""Конвертер цвета считает по границам из документации, а не по своим.

Границы ``colour_value`` (h/s/v) живут в
``_generated/value_envelope.COLOUR_COMPONENT_RANGES`` — их вынимает из
страницы https://developers.sber.ru/docs/ru/smarthome/c2c/value тот же
скрапер, что и остальную спецификацию. Здесь проверяется, что
``ColorConverter`` пользуется именно ими и что ни один край шкал Home
Assistant не выталкивает результат за эти границы.

Соседи: арифметику пересчёта как таковую проверяет ``test_utils.py``,
валидацию готового значения — ``test_sber_models_spec_bound.py``.
"""

from __future__ import annotations

import pytest

from custom_components.sber_mqtt_bridge._generated.value_envelope import COLOUR_COMPONENT_RANGES
from custom_components.sber_mqtt_bridge.devices.utils import color_converter
from custom_components.sber_mqtt_bridge.devices.utils.color_converter import ColorConverter
from custom_components.sber_mqtt_bridge.sber_models import SberColourValue


class TestBoundsComeFromTheSpecification:
    """Числа границ не переписаны в конвертер руками."""

    def test_converter_reads_the_generated_table(self) -> None:
        """Границы конвертера — те же объекты, что в спецификации.

        Что сломается у пользователя, если тест упадёт: в конвертере
        появится собственная копия чисел, и после изменения документации
        мост начнёт молча слать цвет за пределами протокола — лампы
        загорятся не тем цветом, а в журнале не будет ничего.
        """
        assert COLOUR_COMPONENT_RANGES["h"] == color_converter.SBER_HUE_RANGE
        assert COLOUR_COMPONENT_RANGES["s"] == color_converter.SBER_SATURATION_RANGE
        assert COLOUR_COMPONENT_RANGES["v"] == color_converter.SBER_VALUE_RANGE

    def test_value_floor_is_not_zero(self) -> None:
        """Нижняя граница ``v`` — 100, а не 0.

        Что сломается у пользователя, если тест упадёт: полностью
        притушенная лампа уедет в облако с ``v = 0`` — значением, которого
        документация не допускает; Сбер такой пакет вправе выбросить, и
        яркость в приложении замрёт.
        """
        assert COLOUR_COMPONENT_RANGES["v"][0] == 100


class TestHomeAssistantToSberStaysInsideTheDocumentedBox:
    """Ни одно состояние HA не выносит значение за границы Sber."""

    @pytest.mark.parametrize("brightness", [0, 1, 2, 127, 128, 254, 255])
    def test_every_brightness_edge_lands_inside_the_range(self, brightness: int) -> None:
        """Края шкалы яркости HA дают ``v`` внутри 100…1000.

        Что сломается у пользователя, если тест упадёт: округление вынесет
        яркость за документированную границу — облако обрежет или
        отбросит значение, и лампа «не гаснет до конца» либо не набирает
        полную яркость.
        """
        low, high = COLOUR_COMPONENT_RANGES["v"]
        _, _, value = ColorConverter.ha_to_sber_hsv(180, 50, brightness)
        assert low <= value <= high

    def test_full_brightness_sweep_never_escapes(self) -> None:
        """Вся шкала 0…255 укладывается в документированный диапазон.

        Что сломается у пользователя, если тест упадёт: дефект пересчёта
        проявится не на краях, а где-то в середине — то есть на обычной,
        каждодневной яркости.
        """
        low, high = COLOUR_COMPONENT_RANGES["v"]
        offenders = [
            brightness
            for brightness in range(256)
            if not low <= ColorConverter.ha_to_sber_hsv(0, 0, brightness)[2] <= high
        ]
        assert offenders == []

    def test_zero_brightness_becomes_the_documented_minimum(self) -> None:
        """Яркость 0 превращается в документированный минимум.

        Что сломается у пользователя, если тест упадёт: вместо минимума
        уедет 0 — значение вне протокола (см. VR-004 в ``sber_models``).
        """
        assert ColorConverter.ha_to_sber_hsv(0, 0, 0)[2] == COLOUR_COMPONENT_RANGES["v"][0]

    def test_maximum_brightness_becomes_the_documented_maximum(self) -> None:
        """Яркость 255 превращается в документированный максимум.

        Что сломается у пользователя, если тест упадёт: лампа на полной
        яркости в приложении Сбера будет показана недокрученной.
        """
        assert ColorConverter.ha_to_sber_hsv(0, 0, 255)[2] == COLOUR_COMPONENT_RANGES["v"][1]

    @pytest.mark.parametrize("hue", [0, 1, 179, 180, 359, 360])
    @pytest.mark.parametrize("saturation", [0, 1, 50, 99, 100])
    def test_hue_and_saturation_edges_land_inside_the_range(self, hue: int, saturation: int) -> None:
        """Края оттенка и насыщенности HA не выходят за границы Sber.

        Что сломается у пользователя, если тест упадёт: чистый красный
        (0°) или полностью насыщенный цвет уедет за границу — облако
        покажет другой оттенок либо выбросит пакет целиком.
        """
        sber_hue, sber_saturation, _ = ColorConverter.ha_to_sber_hsv(hue, saturation, 128)
        assert COLOUR_COMPONENT_RANGES["h"][0] <= sber_hue <= COLOUR_COMPONENT_RANGES["h"][1]
        assert COLOUR_COMPONENT_RANGES["s"][0] <= sber_saturation <= COLOUR_COMPONENT_RANGES["s"][1]

    @pytest.mark.parametrize(
        ("hue", "saturation", "brightness"),
        [(None, None, None), (-10, -10, -10), (400, 200, 300), (float("inf"), 1e9, 1e9)],
    )
    def test_hostile_input_is_still_publishable(
        self, hue: float | None, saturation: float | None, brightness: float | None
    ) -> None:
        """Мусор из HA не даёт значения, которое отвергнет наш же валидатор.

        Отрицательные и бесконечные атрибуты приезжают из HA буднично:
        шаблонный сенсор с делением на ноль, битый регистр modbus.

        Что сломается у пользователя, если тест упадёт: пакет со всеми
        устройствами не пройдёт проверку и не уедет — в приложении Сбера
        замрёт сразу всё, а не одна лампа.
        """
        h, s, v = ColorConverter.ha_to_sber_hsv(hue, saturation, brightness)
        assert SberColourValue(h=h, s=s, v=v).v == v


class TestSberToHomeAssistantStaysInsideTheHaScales:
    """Обратный пересчёт не выходит за шкалы Home Assistant."""

    def test_documented_minimum_means_fully_dimmed(self) -> None:
        """``v`` на нижней границе даёт яркость 0.

        Что сломается у пользователя, если тест упадёт: команда «убавить
        до минимума» из приложения Сбера приедет в HA как ненулевая
        яркость, и лампу нельзя будет притушить до конца.
        """
        assert ColorConverter.sber_to_ha_hsv(0, 0, COLOUR_COMPONENT_RANGES["v"][0])[2] == 0

    def test_documented_maximum_means_full_brightness(self) -> None:
        """``v`` на верхней границе даёт яркость 255.

        Что сломается у пользователя, если тест упадёт: команда «на полную»
        не доведёт лампу до максимума.
        """
        assert ColorConverter.sber_to_ha_hsv(0, 0, COLOUR_COMPONENT_RANGES["v"][1])[2] == 255

    def test_value_below_the_documented_floor_is_read_as_off(self) -> None:
        """``v`` ниже документированного минимума читается как 0, а не как ошибка.

        Что сломается у пользователя, если тест упадёт: облако, приславшее
        значение за пределами собственной документации, уронит обработку
        команды — лампа перестанет отзываться.
        """
        assert ColorConverter.sber_to_ha_hsv(0, 0, 0)[2] == 0
        assert ColorConverter.sber_to_ha_hsv(0, 0, 40)[2] == 0

    @pytest.mark.parametrize("value", [100, 101, 550, 999, 1000, 5000])
    def test_brightness_never_leaves_the_ha_scale(self, value: int) -> None:
        """Яркость на выходе всегда лежит в 0…255.

        Что сломается у пользователя, если тест упадёт: HA отклонит вызов
        ``light.turn_on`` с недопустимой яркостью, и команда из Сбера
        пропадёт без следа.
        """
        assert 0 <= ColorConverter.sber_to_ha_hsv(0, 0, value)[2] <= 255

    @pytest.mark.parametrize("hue", [0, 360, 400])
    @pytest.mark.parametrize("saturation", [0, 1000, 1200])
    def test_hue_and_saturation_never_leave_the_ha_scales(self, hue: int, saturation: int) -> None:
        """Оттенок и насыщенность на выходе лежат в 0…360 и 0…100.

        Что сломается у пользователя, если тест упадёт: ``hs_color`` вне
        шкалы HA — это ``vol.Invalid`` на вызове сервиса, то есть
        проглоченная команда смены цвета.
        """
        ha_hue, ha_saturation, _ = ColorConverter.sber_to_ha_hsv(hue, saturation, 550)
        assert 0 <= ha_hue <= 360
        assert 0 <= ha_saturation <= 100


class TestRoundTrip:
    """Туда-обратно значение не уползает."""

    @pytest.mark.parametrize("brightness", [0, 1, 128, 254, 255])
    def test_brightness_survives_the_round_trip(self, brightness: int) -> None:
        """Яркость возвращается с точностью до шага округления.

        Что сломается у пользователя, если тест упадёт: каждая публикация
        состояния будет чуть смещать яркость — лампа «сама» поедет вверх
        или вниз при повторяющихся обновлениях.
        """
        sber = ColorConverter.ha_to_sber_hsv(180, 50, brightness)
        assert abs(ColorConverter.sber_to_ha_hsv(*sber)[2] - brightness) <= 1
