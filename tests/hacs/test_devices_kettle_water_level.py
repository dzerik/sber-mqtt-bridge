"""Уровень воды чайника: тип, дробная часть и мусорные числа из HA.

Sber документирует ``kitchen_water_level`` как FLOAT в литрах (0…50):
https://developers.sber.ru/docs/ru/smarthome/c2c/kitchen_water_level.
Чайник же публиковал его через ``make_integer_value`` — облако читает
поле, названное типом, ``float_value`` не находит и уровень воды не
показывает.  Ни одной ошибки при этом нигде не возникает, поэтому дефект
и прожил так долго.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from custom_components.sber_mqtt_bridge._generated.feature_types import FEATURE_TYPES
from custom_components.sber_mqtt_bridge.devices.kettle import KettleEntity

ENTITY_DATA: dict[str, Any] = {"entity_id": "water_heater.kettle", "name": "Чайник"}


def _states(**attrs: Any) -> dict[str, dict[str, Any]]:
    """Собрать чайник, накормить его атрибутами HA и вернуть карту состояний.

    Args:
        **attrs: Атрибуты HA-состояния (``water_level`` и прочие).

    Returns:
        Отображение «ключ функции Sber → словарь ``value``».
    """
    entity = KettleEntity(ENTITY_DATA)
    entity.fill_by_ha_state({"state": "heating", "attributes": dict(attrs)})
    published = entity.to_sber_current_state()[entity.entity_id]["states"]
    return {str(item["key"]): item["value"] for item in published}


def test_water_level_is_published_as_float() -> None:
    """Уровень воды уезжает FLOAT-ом, как написано в документации.

    Прод: в INTEGER-конверте облако значения не видит — в приложении
    Сбера уровень воды пуст, и никакой ошибки нигде нет.
    """
    assert FEATURE_TYPES["kitchen_water_level"] == "FLOAT"
    assert _states(water_level=20.0)["kitchen_water_level"] == {"type": "FLOAT", "float_value": 20.0}


def test_fractional_water_level_survives() -> None:
    """1.7 литра остаются 1.7, а не превращаются в 1.

    Прод: у чайника шкала в литрах (0…50), и усечение до целого — это
    минус пол-литра на индикаторе.  Раньше значение проходило через
    целочисленный парсер именно потому, что дальше его всё равно
    заворачивали в INTEGER.
    """
    assert _states(water_level=1.7)["kitchen_water_level"] == {"type": "FLOAT", "float_value": 1.7}


def test_missing_water_level_is_not_published() -> None:
    """Чайник, который про воду ничего не сообщает, ничего и не публикует.

    Прод: ноль вместо «неизвестно» — это «воды нет», и приложение
    показывает пустой чайник вместо полного.
    """
    assert "kitchen_water_level" not in _states()


@pytest.mark.parametrize("broken", ["nan", "inf", "не число"])
def test_broken_water_level_does_not_reach_the_payload(broken: str) -> None:
    """``NaN`` / ``Infinity`` из HA не попадают в пакет.

    ``float('nan')`` приезжает из HA буднично: шаблонный сенсор с
    делением на ноль, MQTT-полезная нагрузка ``"nan"``.

    Прод: ``NaN`` — расширение Python, а не JSON, и брокер отвергает всё
    сообщение ``up/status`` целиком.  Цена одного мусорного атрибута —
    замершие в приложении устройства, все сразу.
    """
    states = _states(water_level=float(broken) if broken != "не число" else broken)
    assert "kitchen_water_level" not in states
    json.dumps(states, allow_nan=False)


def test_whole_kettle_payload_matches_the_documented_types() -> None:
    """Каждое состояние чайника собрано в типе из справочника документации.

    Прод: чайник переведён на ``make_state_for``, который берёт тип из
    ``_generated/feature_types.py``.  Если тест упадёт — кто-то снова
    выбрал конверт руками, и соответствующая функция станет для облака
    невидимой.
    """
    states = _states(current_temperature=55, temperature=80, water_level=1.7, water_low_level=False, child_lock=True)
    assert states
    for key, value in states.items():
        assert value["type"] == FEATURE_TYPES[key], key
