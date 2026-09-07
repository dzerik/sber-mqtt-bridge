"""Строгие модели, привязанные к структурным страницам документации Sber.

Раньше три числа жили в ``sber_models.py`` руками: лимит ``partner_meta``
(1024), нижняя граница яркости цвета (100) и негласное правило «поле
значения должно соответствовать типу».  Первые два были переписаны из
документации однажды и с тех пор могли протухнуть незаметно, третье не
проверялось вообще.

Теперь все три опираются на ``_generated`` — то есть на снапшот
документации, который еженедельно пересобирается.  Эти тесты фиксируют и
саму привязку (значение берётся из спецификации, а не вписано в код), и
поведение валидаторов.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from custom_components.sber_mqtt_bridge._generated.protocol_limits import (
    PARTNER_META_MAX_CHARS as SPEC_PARTNER_META_MAX_CHARS,
)
from custom_components.sber_mqtt_bridge._generated.value_envelope import (
    COLOUR_COMPONENT_RANGES as SPEC_COLOUR_COMPONENT_RANGES,
)
from custom_components.sber_mqtt_bridge.sber_models import (
    COLOUR_COMPONENT_RANGES,
    PARTNER_META_MAX_CHARS,
    SberColourValue,
    SberDevice,
    SberValue,
    make_colour_value,
    make_integer_value,
)


def _device(**overrides) -> dict:
    """Собрать минимальный корректный дескриптор устройства.

    Args:
        **overrides: Поля, которые надо добавить или переопределить.

    Returns:
        Словарь, пригодный для :meth:`SberDevice.model_validate`.
    """
    body = {
        "id": "light.probe",
        "name": "Проба",
        "default_name": "Проба",
        "model": {
            "id": "Mdl_light_deadbeef",
            "category": "light",
            "features": ["online", "on_off"],
        },
    }
    body.update(overrides)
    return body


class TestConstantsComeFromTheSnapshot:
    """Числа берутся из спецификации, а не переписаны в код руками."""

    def test_partner_meta_limit_follows_the_documentation(self) -> None:
        """Лимит ``partner_meta`` совпадает с извлечённым из документации.

        Что сломается у пользователя, если тест упадёт: в коде останется
        число, которого документация больше не содержит.  Слишком
        маленькое — мост начнёт выбрасывать устройства, которые Sber
        принял бы; слишком большое — устройства будут отвергаться
        облаком без объяснений.
        """
        assert PARTNER_META_MAX_CHARS == SPEC_PARTNER_META_MAX_CHARS
        assert PARTNER_META_MAX_CHARS == 1024

    def test_colour_bounds_follow_the_documentation(self) -> None:
        """Границы HSV совпадают с извлечёнными из документации.

        Что сломается у пользователя, если тест упадёт: конвертер цвета
        (``devices/utils/color_converter.py``) считает по своим числам, и
        расхождение проявится как неправильный цвет ламп.
        """
        assert COLOUR_COMPONENT_RANGES == SPEC_COLOUR_COMPONENT_RANGES
        assert COLOUR_COMPONENT_RANGES["v"] == (100, 1000)


class TestColourValueBounds:
    """VR-004: у ``colour_value`` есть документированные границы."""

    @pytest.mark.parametrize(
        ("h", "s", "v"),
        [(0, 0, 100), (360, 1000, 1000), (120, 500, 550)],
    )
    def test_values_inside_the_range_are_accepted(self, h: int, s: int, v: int) -> None:
        """Цвет в допустимых границах проходит проверку.

        Что сломается у пользователя, если тест упадёт: цветные лампы
        перестанут проходить валидацию пакета состояния — в журнале
        появится предупреждение на каждой публикации цвета.
        """
        assert SberColourValue(h=h, s=s, v=v).v == v

    @pytest.mark.parametrize(
        ("h", "s", "v", "expected"),
        [
            (120, 500, 40, "colour_value.v"),
            (400, 500, 900, "colour_value.h"),
            (120, 1200, 900, "colour_value.s"),
        ],
    )
    def test_values_outside_the_range_are_rejected(self, h: int, s: int, v: int, expected: str) -> None:
        """Цвет за границами отклоняется с понятным текстом.

        Нижняя граница ``v`` у Sber именно 100: значение 40 выглядит
        безобидно, но в облаке даёт не тот цвет.

        Что сломается у пользователя, если тест упадёт: арифметика
        ``ColorConverter`` перестанет быть ничем прикрыта, и ошибка в
        пересчёте яркости уедет на провод молча.
        """
        with pytest.raises(ValidationError, match=expected):
            SberColourValue(h=h, s=s, v=v)

    def test_bridge_converter_output_is_accepted(self) -> None:
        """Значение, собранное штатным конструктором, проходит проверку.

        Что сломается у пользователя, если тест упадёт: собственный
        помощник моста начнёт производить значения, которые его же
        валидатор отвергает.
        """
        payload = make_colour_value(120, 500, 550)
        assert SberValue.model_validate(payload).colour_value is not None


class TestValuePayloadMatchesType:
    """Полезная нагрузка обязана лежать в поле, названном типом."""

    def test_payload_under_a_foreign_field_is_rejected(self) -> None:
        """Значение ENUM в поле ``integer_value`` отклоняется.

        ``extra="forbid"`` ловит только выдуманные поля; все ``*_value``
        объявлены в модели, поэтому такой пакет раньше проходил проверку
        и терялся уже в облаке.

        Что сломается у пользователя, если тест упадёт: устройство
        отправляет значение, которое облако не читает, а в журнале моста
        всё выглядит успешным.
        """
        with pytest.raises(ValidationError, match="must carry"):
            SberValue.model_validate({"type": "ENUM", "integer_value": "3"})

    def test_matching_payload_is_accepted(self) -> None:
        """Правильно оформленное значение проходит проверку.

        Что сломается у пользователя, если тест упадёт: валидация
        пакета состояния начнёт падать на каждом штатном значении.
        """
        assert SberValue.model_validate(make_integer_value(42)).integer_value == "42"

    def test_proto3_elided_payload_is_accepted(self) -> None:
        """Значение без полезной нагрузки принимается.

        Sber выбрасывает из пакета поля со значением по умолчанию, так
        что ``{"type": "BOOL"}`` — это законное ``false``; эхо-ответ на
        команду пересылает такие значения обратно как есть.

        Что сломается у пользователя, если тест упадёт: каждая команда
        «выключи» будет писать в журнал предупреждение о неправильном
        пакете.
        """
        assert SberValue.model_validate({"type": "BOOL"}).bool_value is None


class TestPartnerMetaLimit:
    """VR-003: единственное числовое ограничение во всей документации."""

    def test_oversized_partner_meta_is_rejected_with_the_size(self) -> None:
        """Слишком длинная служебная нагрузка отклоняется с указанием длины.

        Что сломается у пользователя, если тест упадёт: устройство с
        раздутым ``partner_meta`` уйдёт в облако и будет отвергнуто без
        объяснения причины.
        """
        assert PARTNER_META_MAX_CHARS is not None
        oversized = {"junk": "x" * (PARTNER_META_MAX_CHARS + 10)}
        with pytest.raises(ValidationError, match="limit is 1024"):
            SberDevice.model_validate(_device(partner_meta=oversized))

    def test_bridge_serial_marker_fits(self) -> None:
        """Штатная метка моста в лимит укладывается.

        Что сломается у пользователя, если тест упадёт: корневой хаб
        моста перестанет публиковаться, и все устройства потеряют
        родителя.
        """
        device = SberDevice.model_validate(_device(partner_meta={"ha_serial_number": "ha-1a2b3c4d"}))
        assert device.partner_meta == {"ha_serial_number": "ha-1a2b3c4d"}
