"""Энергомониторинг умных розеток: связанные сенсоры power / voltage / current.

Что проверяет этот файл (и что сломается у пользователя, если он упадёт):

* Zigbee2MQTT / Tuya / Shelly / ESPHome отдают мощность, напряжение и ток
  ОТДЕЛЬНЫМИ сущностями (``sensor.plug_power`` и т.д.), а не атрибутами
  выключателя.  Если роли ``power`` / ``voltage`` / ``current`` перестанут
  резолвиться, мастер снова покажет эти сенсоры в разделе «Не подходят», и
  розетка приедет в Сбер без энергомониторинга — ровно та причина, по
  которой пользователи держали рядом вторую интеграцию.
* Единицы Sber зафиксированы документацией: ``power`` — ватты (0…50000),
  ``voltage`` — вольты (0…5000), ``current`` — **миллиамперы** (0…30000).
  HA отдаёт амперы: без пересчёта 0,65 A превращается в 0 мА, и в
  приложении Сбера ток всегда «0».
* Функция объявляется только когда значение реально есть: объявленная, но
  не публикуемая функция ловится валидатором и может привести к тихому
  отклонению устройства облаком.
"""

from __future__ import annotations

import logging

import pytest

from custom_components.sber_mqtt_bridge.devices.base_entity import (
    ALL_LINKABLE_ROLES,
    ENERGY_LINK_ROLES,
    resolve_link_role,
)
from custom_components.sber_mqtt_bridge.devices.intercom import IntercomEntity
from custom_components.sber_mqtt_bridge.devices.relay import RelayEntity
from custom_components.sber_mqtt_bridge.devices.socket_entity import SocketEntity
from custom_components.sber_mqtt_bridge.devices.utils.electrical import (
    ENERGY_FEATURES,
    to_sber_energy_attribute,
    to_sber_energy_value,
)


def _states_of(entity) -> dict[str, dict]:
    """Вернуть {feature_key: value_dict} из ``to_sber_current_state``."""
    payload = entity.to_sber_current_state()[entity.entity_id]["states"]
    return {s["key"]: s["value"] for s in payload}


def _socket(**attrs) -> SocketEntity:
    """Розетка в состоянии ``on`` с заданными атрибутами HA."""
    entity = SocketEntity({"entity_id": "switch.plug", "name": "Plug"})
    entity.fill_by_ha_state({"state": "on", "attributes": dict(attrs)})
    return entity


def _sensor_state(state: str, unit: str | None = None) -> dict:
    """Состояние связанного HA-сенсора с единицей измерения."""
    attributes: dict[str, object] = {}
    if unit is not None:
        attributes["unit_of_measurement"] = unit
    return {"entity_id": "sensor.plug_x", "state": state, "attributes": attributes}


# ---------------------------------------------------------------------------
#  Роли связывания
# ---------------------------------------------------------------------------


class TestEnergyLinkRoles:
    """Три роли энергомониторинга должны быть в глобальном реестре."""

    @pytest.mark.parametrize(
        ("device_class", "expected"),
        [("power", "power"), ("voltage", "voltage"), ("current", "current")],
    )
    def test_sensor_device_class_resolves_to_role(self, device_class, expected):
        """Без этого мастер кладёт сенсор в «Не подходят» и связать его нельзя."""
        assert resolve_link_role("sensor", device_class) == expected

    def test_roles_are_registered_globally(self):
        """Роль, неизвестная ``ALL_LINKABLE_ROLES``, не доедет до мастера."""
        assert {"power", "voltage", "current"} <= {r.role for r in ALL_LINKABLE_ROLES}

    @pytest.mark.parametrize("cls", [SocketEntity, RelayEntity])
    def test_socket_and_relay_accept_energy_roles(self, cls):
        """Категории ``socket`` / ``relay`` документируют power/voltage/current."""
        assert {"power", "voltage", "current"} <= {r.role for r in cls.LINKABLE_ROLES}

    def test_intercom_does_not_accept_energy_roles(self):
        """У ``intercom`` этих функций в справочнике нет — Сбер отклонит модель."""
        assert not {"power", "voltage", "current"} & {r.role for r in IntercomEntity.LINKABLE_ROLES}

    def test_binary_sensor_power_is_not_a_link(self):
        """``binary_sensor`` с device_class ``power`` — это «есть питание», не ватты."""
        assert resolve_link_role("binary_sensor", "power") == ""


# ---------------------------------------------------------------------------
#  Пересчёт единиц HA → Sber
# ---------------------------------------------------------------------------


class TestLinkedEnergyUnits:
    """Значения связанных сенсоров приводятся к единицам Sber."""

    @pytest.mark.parametrize(
        ("state", "unit", "expected"),
        [
            ("1200", "W", "1200"),
            ("1200.4", "W", "1200"),
            ("1.2", "kW", "1200"),
            ("2500", None, "2500"),  # без единицы считаем ватты (базовая единица HA)
            ("1500", "mW", "2"),
        ],
    )
    def test_power_is_watts(self, state, unit, expected):
        """Мощность Sber — ватты; киловатты HA без пересчёта дали бы 1 Вт вместо 1200."""
        entity = _socket()
        entity.update_linked_data("power", _sensor_state(state, unit))
        assert _states_of(entity)["power"] == {"type": "INTEGER", "integer_value": expected}

    @pytest.mark.parametrize(
        ("state", "unit", "expected"),
        [
            ("230", "V", "230"),
            ("231.4", "V", "231"),
            ("230000", "mV", "230"),
        ],
    )
    def test_voltage_is_volts(self, state, unit, expected):
        """Напряжение Sber — вольты."""
        entity = _socket()
        entity.update_linked_data("voltage", _sensor_state(state, unit))
        assert _states_of(entity)["voltage"] == {"type": "INTEGER", "integer_value": expected}

    @pytest.mark.parametrize(
        ("state", "unit", "expected"),
        [
            ("0.65", "A", "650"),  # ГЛАВНАЯ ЛОВУШКА: int(0.65) дал бы 0
            ("9", "A", "9000"),
            ("650", "mA", "650"),
            ("0.65", None, "650"),  # без единицы считаем амперы (базовая единица HA)
        ],
    )
    def test_current_is_milliamperes(self, state, unit, expected):
        """Ток Sber — миллиамперы: 0,65 A = 650 мА, а не 0."""
        entity = _socket()
        entity.update_linked_data("current", _sensor_state(state, unit))
        assert _states_of(entity)["current"] == {"type": "INTEGER", "integer_value": expected}

    def test_foreign_unit_is_refused(self):
        """Единица чужой величины — повод не публиковать показание вовсе.

        Панель («set_entity_links») позволяет положить в роль любой
        сенсор, поэтому в роль ``power`` вполне может попасть счётчик
        накопленной энергии в кВт·ч.  ``kWh`` не является единицей
        мощности, и трактовать это число как ватты нельзя: пользователь
        увидел бы в приложении Сбера правдоподобную, но выдуманную
        мощность в тысячи ватт.  Функция просто не объявляется — это
        видимое «нет данных» вместо незаметно неверного значения.
        """
        entity = _socket()
        entity.update_linked_data("power", _sensor_state("12.5", "kWh"))
        assert "power" not in entity.get_final_features_list()
        assert "power" not in _states_of(entity)

    def test_missing_unit_falls_back_to_ha_base_unit(self):
        """Единицы нет вовсе — читаем базовую единицу HA, а не отказываемся.

        Отсутствие ``unit_of_measurement`` встречается у самодельных
        template-сенсоров; отказ здесь лишил бы энергомониторинга тех,
        у кого он раньше работал.
        """
        entity = _socket()
        entity.update_linked_data("current", _sensor_state("0.65", None))
        assert _states_of(entity)["current"] == {"type": "INTEGER", "integer_value": "650"}


class TestDocumentedRangeClamp:
    """Значения зажимаются в документированные диапазоны Sber."""

    @pytest.mark.parametrize(
        ("role", "state", "unit", "expected"),
        [
            ("power", "999999", "W", "50000"),
            ("power", "-5", "W", "0"),
            ("voltage", "99999", "V", "5000"),
            ("current", "99", "A", "30000"),
        ],
    )
    def test_out_of_range_is_clamped(self, role, state, unit, expected):
        """Значение вне INTEGER(min, max) — повод для облака отклонить устройство."""
        entity = _socket()
        entity.update_linked_data(role, _sensor_state(state, unit))
        assert _states_of(entity)[role]["integer_value"] == expected

    def test_attribute_path_is_clamped_too(self):
        """Битый атрибут самой сущности тоже не должен уехать за диапазон."""
        entity = _socket(power=999999)
        assert _states_of(entity)["power"]["integer_value"] == "50000"


# ---------------------------------------------------------------------------
#  Объявление функций и взаимодействие с атрибутами
# ---------------------------------------------------------------------------


class TestFeatureDeclaration:
    """Функция объявляется ровно тогда, когда значение доступно."""

    def test_no_energy_without_data(self):
        """«Объявлено, но не публикуется» ловит валидатор — так быть не должно."""
        entity = _socket()
        features = entity.get_final_features_list()
        assert not {"power", "voltage", "current"} & set(features)
        assert not {"power", "voltage", "current"} & set(_states_of(entity))

    def test_linked_value_declares_the_feature(self):
        """Появление связанного сенсора обязано менять список функций.

        На это опирается ``HaStateForwarder._handle_linked_state_change``:
        сравнение списков до/после решает, переиздавать ли конфигурацию.
        """
        entity = _socket()
        before = entity.get_final_features_list()
        entity.update_linked_data("power", _sensor_state("100", "W"))
        after = entity.get_final_features_list()
        assert "power" not in before
        assert "power" in after

    def test_unavailable_linked_sensor_drops_the_feature(self):
        """Сенсор ушёл в unavailable — публиковать старое значение нельзя."""
        entity = _socket()
        entity.update_linked_data("power", _sensor_state("100", "W"))
        entity.update_linked_data("power", _sensor_state("unavailable"))
        assert "power" not in entity.get_final_features_list()
        assert "power" not in _states_of(entity)

    def test_attribute_path_publishes_the_value_as_is(self):
        """Атрибуты самого выключателя публикуются БЕЗ пересчёта единиц.

        У атрибута нет ``unit_of_measurement``, поэтому пересчитывать
        не от чего.  Единственная известная интеграция, которая вообще
        кладёт эти величины в атрибуты выключателя — ``localtuya``, —
        уже приводит их к единицам Sber: в её ``switch.py`` ``voltage``
        и ``current_consumption`` делятся на 10 (вольты и ватты), а
        ``current`` отдаётся сырым датапоинтом Tuya, то есть в
        миллиамперах.

        Если тест упадёт (например, кто-то решит трактовать атрибут как
        амперы), у владельцев Tuya-розеток ток уедет в тысячу раз вверх
        и упрётся в потолок 30 000 мА — в приложении Сбера они увидят
        вечные 30 A.
        """
        entity = _socket(power=150, voltage=220, current=650)
        states = _states_of(entity)
        assert states["power"]["integer_value"] == "150"
        assert states["voltage"]["integer_value"] == "220"
        assert states["current"]["integer_value"] == "650"

    def test_fractional_attribute_is_rounded_not_truncated(self):
        """Дробный атрибут округляется, а не обнуляется.

        ``_safe_int_parser`` резал 0,65 в ноль ещё при разборе — теперь
        округление одно и происходит перед публикацией.  Пользователь с
        розеткой, отдающей дробные показания, перестаёт видеть в
        приложении Сбера вечный ноль.
        """
        entity = _socket(current=0.65)
        assert _states_of(entity)["current"]["integer_value"] == "1"

    def test_linked_value_wins_over_attribute(self):
        """Явно связанный сенсор точнее случайного атрибута с неизвестной единицей."""
        entity = _socket(power=150)
        entity.update_linked_data("power", _sensor_state("1200", "W"))
        assert _states_of(entity)["power"]["integer_value"] == "1200"

    def test_primary_refresh_does_not_wipe_linked_value(self):
        """Обновление состояния розетки не должно стирать связанные показания.

        Иначе энергомониторинг мигал бы: значение появлялось при событии
        сенсора и исчезало при следующем переключении розетки.
        """
        entity = _socket()
        entity.update_linked_data("current", _sensor_state("0.65", "A"))
        entity.fill_by_ha_state({"state": "off", "attributes": {}})
        assert _states_of(entity)["current"]["integer_value"] == "650"

    def test_intercom_ignores_energy_links(self):
        """У категории вне справочника функции не должны просочиться на провод."""
        entity = IntercomEntity({"entity_id": "switch.door", "name": "Door"})
        entity.fill_by_ha_state({"state": "on", "attributes": {}})
        entity.update_linked_data("power", _sensor_state("100", "W"))
        assert "power" not in entity.get_final_features_list()
        assert "power" not in _states_of(entity)


# ---------------------------------------------------------------------------
#  Конвертер как отдельная единица
# ---------------------------------------------------------------------------


class TestEnergyConverterUnit:
    """Крайние случаи ``devices/utils/electrical.py``."""

    def test_roles_and_features_share_one_vocabulary(self):
        """Имена ролей и имён функций Sber обязаны совпадать.

        На этом держится маршрутизация ``update_linked_data``: разъезд
        словарей означает молча проигнорированный связанный сенсор.
        """
        assert set(ENERGY_FEATURES) == {r.role for r in ENERGY_LINK_ROLES}

    @pytest.mark.parametrize("raw", [None, "unknown", "unavailable", "", "не число", float("nan"), float("inf")])
    def test_unusable_readings_return_none(self, raw):
        """NaN из шаблонного сенсора не должен уехать в облако нулём."""
        assert to_sber_energy_value("power", raw, "W", "socket") is None

    def test_unknown_feature_returns_none(self):
        """Чужая роль не должна давать «значение» ниоткуда."""
        assert to_sber_energy_value("battery", "50", "%", "socket") is None

    def test_range_comes_from_the_function_page_without_a_category(self):
        """Диапазон известен и без категории — берётся со страницы функции.

        Значение вне ``INTEGER(0, 50000)`` — законный повод облаку молча
        отклонить всё устройство целиком.
        """
        assert to_sber_energy_value("power", "999999", "W", None) == 50000

    def test_attribute_and_sensor_paths_treat_the_number_differently(self):
        """Два входа — две трактовки, и это осознанно.

        650 в атрибуте — это уже миллиамперы (``localtuya`` кладёт туда
        сырой датапоинт Tuya), а 650 у сенсора с единицей ``A`` — это
        650 ампер, то есть заведомо битые данные, которые зажимаются в
        документированный потолок.  Если функции перестанут отличаться,
        одна из двух групп пользователей увидит ток, ошибочный в тысячу
        раз.
        """
        assert to_sber_energy_attribute("current", 650, "socket") == 650
        assert to_sber_energy_value("current", "650", "A", "socket") == 30000

    @pytest.mark.parametrize("raw", [None, "unknown", "unavailable", "", "не число", float("nan")])
    def test_attribute_unusable_readings_return_none(self, raw):
        """Нечитаемый атрибут не должен объявлять функцию с нулевым значением."""
        assert to_sber_energy_attribute("power", raw, "socket") is None

    def test_attribute_unknown_feature_returns_none(self):
        """Атрибутный путь тоже не выдумывает значения для чужих ролей."""
        assert to_sber_energy_attribute("battery", 50, "socket") is None

    def test_clamping_is_logged(self, caplog):
        """Зажатое значение обязано оставлять след в логе.

        Иначе ошибка в единицах выглядит как правдоподобное показание:
        розетка, вечно показывающая ровно 30 A, неотличима от исправной.
        Без этой записи диагностировать такое по логам невозможно.
        """
        with caplog.at_level(logging.WARNING):
            assert to_sber_energy_value("current", "99", "A", "socket") == 30000
        assert "current" in caplog.text
        assert "clamped" in caplog.text

    def test_value_inside_the_range_is_not_logged(self, caplog):
        """Нормальные показания не должны засорять лог предупреждениями."""
        with caplog.at_level(logging.WARNING):
            to_sber_energy_value("current", "0.65", "A", "socket")
            to_sber_energy_attribute("power", 150, "socket")
        assert caplog.text == ""
