"""Тесты SensorTempEntity — issue #63 (карточка датчика температуры в приложении Сбера).

Закрывают три самостоятельных дефекта, найденных при разборе #63, и
фиксируют четвёртый (коллизия ``model.id``) как известное ограничение.
"""

from __future__ import annotations

import pytest
import voluptuous as vol

from custom_components.sber_mqtt_bridge._generated.reference_values import FEATURE_RANGES
from custom_components.sber_mqtt_bridge.devices.sensor_temp import (
    SENSOR_TEMP_OPTION_TEMP_UNIT_VIEW,
    SensorTempEntity,
)

TEMP_DATA = {"entity_id": "sensor.temp", "name": "Temperature"}


def _entity(**options) -> SensorTempEntity:
    """Создать датчик температуры с применёнными пользовательскими опциями."""
    entity = SensorTempEntity(dict(TEMP_DATA))
    if options:
        entity.apply_entity_options(options)
    return entity


def _fill(entity: SensorTempEntity, state: str = "22.5", **attrs) -> SensorTempEntity:
    """Прогнать HA-состояние через датчик."""
    entity.fill_by_ha_state({"entity_id": "sensor.temp", "state": state, "attributes": attrs})
    return entity


def _states(entity: SensorTempEntity) -> dict[str, dict]:
    """Вернуть публикуемые состояния в виде ``{key: value}``."""
    payload = entity.to_sber_current_state()["sensor.temp"]["states"]
    return {s["key"]: s["value"] for s in payload}


class TestTempUnitViewOption:
    """``temp_unit_view`` — опциональная функция, а не обязательная для всех.

    Sber документирует её "только для датчиков с экраном". Отключить её
    нужно уметь поштучно: это единственное, что мост шлёт сверх минимума,
    и репортёру #63 нужен способ проверить голый дескриптор. По умолчанию
    функция остаётся включённой — её снятие меняет digest в ``model.id``,
    после чего облако перерегистрирует устройство и теряет комнату (#44).
    """

    def test_declared_by_default(self):
        """По умолчанию поведение не меняется — иначе все существующие
        датчики температуры разом сменят ``model.id`` и потеряют комнату."""
        entity = _fill(_entity(), unit_of_measurement="°C")
        assert "temp_unit_view" in entity.get_final_features_list()
        assert "temp_unit_view" in _states(entity)

    def test_option_off_removes_feature(self):
        """С ``temp_unit_view: false`` функция исчезает из объявления.

        Если сломается — пользователь не сможет получить минимальный
        дескриптор ``online`` + ``temperature``, которым проверяют гипотезу
        о падении карточки.
        """
        entity = _fill(_entity(**{SENSOR_TEMP_OPTION_TEMP_UNIT_VIEW: False}), unit_of_measurement="°C")
        assert "temp_unit_view" not in entity.get_final_features_list()

    def test_option_off_removes_state(self):
        """Выключенная функция не должна публиковаться и в состоянии.

        Публикация необъявленного ключа — это ровно тот класс ошибок,
        из-за которого приложение рисует неработающий контрол (#44).
        """
        entity = _fill(_entity(**{SENSOR_TEMP_OPTION_TEMP_UNIT_VIEW: False}), unit_of_measurement="°C")
        assert "temp_unit_view" not in _states(entity)
        # Само показание при этом никуда не девается.
        assert _states(entity)["temperature"]["integer_value"] == "225"

    def test_options_state_reports_flag(self):
        """Панель должна видеть текущее значение опции, иначе форма
        сбросит его при следующем сохранении."""
        entity = _entity(**{SENSOR_TEMP_OPTION_TEMP_UNIT_VIEW: False})
        assert entity.supports_entity_options is True
        assert entity.entity_options_state() == {SENSOR_TEMP_OPTION_TEMP_UNIT_VIEW: False}

    def test_non_bool_option_rejected(self):
        """Строка вместо флага должна отбиваться с внятным сообщением,
        а не молча включать функцию.

        Ожидание привязано к тексту именно проверки типа: пока ключ не был
        объявлен в ``ENTITY_OPTION_KEYS``, базовый класс отбивал его как
        чужой ("unknown option(s)"), и тест был бы зелёным по чужой
        причине — не стерёг бы новую ветку.
        """
        entity = _entity()
        with pytest.raises(ValueError, match="must be true or false"):
            entity.validate_entity_options({SENSOR_TEMP_OPTION_TEMP_UNIT_VIEW: "no"})

    def test_garbage_option_ignored_on_load(self):
        """На пути загрузки сущностей мусор в конфиге игнорируется —
        иначе правленный руками config_entry уронит всю интеграцию."""
        entity = _fill(_entity(**{SENSOR_TEMP_OPTION_TEMP_UNIT_VIEW: "no"}), unit_of_measurement="°C")
        assert "temp_unit_view" in entity.get_final_features_list()


class TestAirPressureUnits:
    """``air_pressure`` шлётся в миллиметрах ртутного столба.

    Sber: ``INTEGER(200, 800)``, "в миллиметрах ртутного столба". Любой
    BME280 из zigbee2mqtt/ESPHome отдаёт гектопаскали, и без конвертации
    в облако уходило ``1013`` — заведомо невалидное значение.
    """

    def test_hpa_attribute_converted(self):
        """1013 hPa → 760 мм рт. ст.

        Если сломается — в карточку датчика поедет число за пределами
        диапазона Sber.
        """
        entity = _fill(_entity(), unit_of_measurement="°C", pressure=1013, pressure_unit="hPa")
        assert _states(entity)["air_pressure"]["integer_value"] == "760"

    def test_mbar_converted(self):
        """Миллибар численно равен гектопаскалю — тот же результат."""
        entity = _fill(_entity(), pressure=1013, pressure_unit="mbar")
        assert _states(entity)["air_pressure"]["integer_value"] == "760"

    def test_kpa_converted(self):
        """101.3 kPa — та же атмосфера в другой единице."""
        entity = _fill(_entity(), pressure=101.3, pressure_unit="kPa")
        assert _states(entity)["air_pressure"]["integer_value"] == "760"

    def test_mmhg_passes_through(self):
        """Единица уже правильная — конвертировать нельзя, иначе 760
        превратится в 570."""
        entity = _fill(_entity(), pressure=760, pressure_unit="mmHg")
        assert _states(entity)["air_pressure"]["integer_value"] == "760"

    def test_temperature_unit_is_not_mistaken_for_pressure(self):
        """``unit_of_measurement`` датчика температуры — это ``°C``.

        Он не должен участвовать в выборе множителя: иначе давление
        осталось бы непреобразованным (или, хуже, преобразованным по
        случайному коэффициенту).
        """
        entity = _fill(_entity(), unit_of_measurement="°C", pressure=1013)
        assert _states(entity)["air_pressure"]["integer_value"] == "760"

    def test_unlabelled_mmhg_left_alone(self):
        """Без единицы значение из диапазона мм рт. ст. трогать нельзя.

        740 — нормальное давление в мм рт. ст.; умножение на 0.75 дало бы
        555, то есть выдуманное показание.
        """
        entity = _fill(_entity(), pressure=740)
        assert _states(entity)["air_pressure"]["integer_value"] == "740"

    def test_pressure_clamped_to_sber_range(self):
        """Значение вне ``INTEGER(200, 800)`` подрезается по границе.

        Sber молча отбрасывает устройство целиком, если хоть одно
        значение выходит за объявленный диапазон.
        """
        low, high = FEATURE_RANGES["air_pressure"]
        entity = _fill(_entity(), pressure=5, pressure_unit="mmHg")
        assert _states(entity)["air_pressure"]["integer_value"] == str(int(low))
        entity = _fill(_entity(), pressure=2, pressure_unit="bar")
        assert _states(entity)["air_pressure"]["integer_value"] == str(int(high))

    def test_unparseable_pressure_dropped(self):
        """Нечисловое давление не объявляется и не публикуется."""
        entity = _fill(_entity(), pressure="n/a")
        assert "air_pressure" not in entity.get_final_features_list()
        assert "air_pressure" not in _states(entity)


class TestOfflineDoesNotFabricateReading:
    """Недоступный датчик не должен публиковать 0 °C как настоящее показание.

    ``_get_sber_value`` возвращает 0, если HA отдал ``unavailable`` /
    ``unknown``. Раньше этот ноль уезжал в облако вместе с
    ``online=false``, и в истории Сбера при каждом отвале Zigbee
    появлялись нулевые показания.
    """

    @pytest.mark.parametrize("ha_state", ["unavailable", "unknown"])
    def test_no_temperature_when_offline(self, ha_state):
        """Ключ ``temperature`` не публикуется, пока датчик недоступен."""
        entity = _fill(_entity(), unit_of_measurement="°C")
        entity.fill_by_ha_state({"entity_id": "sensor.temp", "state": ha_state, "attributes": {}})
        states = _states(entity)
        assert states["online"]["bool_value"] is False
        assert "temperature" not in states

    def test_temperature_returns_after_recovery(self):
        """После восстановления связи показание снова публикуется —
        иначе датчик замолчал бы навсегда."""
        entity = _fill(_entity(), unit_of_measurement="°C")
        entity.fill_by_ha_state({"entity_id": "sensor.temp", "state": "unavailable", "attributes": {}})
        _fill(entity, "23.1", unit_of_measurement="°C")
        states = _states(entity)
        assert states["online"]["bool_value"] is True
        assert states["temperature"]["integer_value"] == "231"


@pytest.mark.xfail(
    # TODO(#63): нестрогий намеренно — дефект живёт в base_entity, вне этого
    # направления. Со strict=True тест покраснел бы (XPASS) в чужом релизе, как
    # только model.id починят, и упал бы в файле, который к правке отношения не
    # имеет. Когда _build_model_descriptor научится различать железо, xfail
    # снимается вместе с этим TODO.
    strict=False,
    reason=(
        "Известное ограничение base_entity._build_model_descriptor (#63): без HA "
        "model_id префикс модели вырождается в Mdl_{category}, а manufacturer / "
        "model / description в capability digest не входят — два разных датчика "
        "с одинаковым набором функций получают один model.id и разные метаданные "
        "в одном пакете. Чинится в base_entity, вне этого направления."
    ),
)
def test_different_hardware_gets_different_model_id():
    """Два физически разных датчика не должны делить один ``model.id``.

    Облако Sber хранит одну модель на ``model.id`` и сливает интерфейсы
    всех устройств, которые её заявляют. Здесь в одном config-пакете
    уезжают два устройства с одинаковым ``model.id``, но разными
    ``manufacturer`` / ``model`` / ``description`` — какое из описаний
    останется в облаке, не определено.
    """
    ids = []
    for entity_id, device in (
        ("sensor.aqara", {"id": "d1", "manufacturer": "Aqara", "model": "WSDCGQ11LM"}),
        ("sensor.sonoff", {"id": "d2", "manufacturer": "SONOFF", "model": "SNZB-02"}),
    ):
        entity = SensorTempEntity({"entity_id": entity_id, "original_name": entity_id, "device_id": device["id"]})
        entity.linked_device = device
        entity.fill_by_ha_state({"entity_id": entity_id, "state": "21.0", "attributes": {"unit_of_measurement": "°C"}})
        ids.append(entity.to_sber_state()["model"]["id"])
    assert ids[0] != ids[1]


class TestEntityOptionsContract:
    """Опции категорий должны быть достижимы снаружи и не путаться между собой.

    Механизм опций собран из двух половин: класс устройства объявляет свои
    ключи, а WebSocket-слой пропускает их в ``entry.options``. Половины
    живут в разных файлах и никем не сверялись, поэтому ``temp_unit_view``
    приехал в класс, но не в схему — опцию нельзя было ни выставить из
    панели, ни импортировать вместе с конфигом.
    """

    @staticmethod
    def _option_classes() -> list[type]:
        """Собрать все классы устройств, объявляющие свои опции."""
        # sber_entity_map импортирует все модули devices/ — иначе часть
        # подклассов просто не была бы загружена к моменту обхода.
        import custom_components.sber_mqtt_bridge.sber_entity_map  # noqa: F401
        from custom_components.sber_mqtt_bridge.devices.base_entity import BaseEntity

        seen: list[type] = []

        def walk(cls: type) -> None:
            for sub in cls.__subclasses__():
                if sub not in seen:
                    seen.append(sub)
                    walk(sub)

        walk(BaseEntity)
        return [cls for cls in seen if cls.ENTITY_OPTION_KEYS]

    def test_every_option_key_is_registered_in_ws_validators(self):
        """Каждый ключ опции обязан иметь валидатор в WebSocket-слое.

        Незарегистрированный ключ отбивается схемой с PREVENT_EXTRA: и
        ``update_entity_options`` из панели, и импорт конфига целиком
        (``extra keys not allowed``). Опция при этом выглядит рабочей в
        коде устройства, но выставить её пользователь не может ничем.
        """
        from custom_components.sber_mqtt_bridge.websocket_api._common import ENTITY_OPTION_VALIDATORS

        known = set(ENTITY_OPTION_VALIDATORS)
        for cls in self._option_classes():
            missing = sorted(set(cls.ENTITY_OPTION_KEYS) - known)
            assert not missing, f"{cls.__name__}: ключи {missing} не зарегистрированы в ENTITY_OPTION_VALIDATORS"

    def test_option_blocks_do_not_collide(self):
        """У каждой категории с опциями своё имя блока в ``device_detail``.

        Совпадение имён (в том числе родовое ``entity_options`` из
        ``BaseEntity``) заставит панель нарисовать форму одной категории
        для другой: ключ в ответе один, а поля в нём чужие.
        """
        from custom_components.sber_mqtt_bridge.devices.base_entity import BaseEntity

        blocks = [(cls.__name__, cls.ENTITY_OPTIONS_BLOCK) for cls in self._option_classes()]
        assert [name for name, block in blocks if block == BaseEntity.ENTITY_OPTIONS_BLOCK] == []
        names = [block for _, block in blocks]
        assert len(set(names)) == len(names), f"имена блоков повторяются: {blocks}"

    def test_temp_unit_view_survives_ws_and_import(self):
        """Опцию можно и выставить командой панели, и вернуть импортом.

        Экспорт конфига кладёт опции в ту же схему, что и
        ``update_entity_options``: ключ, который принимает один путь и
        отвергает другой, означал бы, что выгруженный конфиг не
        загружается обратно.
        """
        from custom_components.sber_mqtt_bridge.websocket_api._common import ENTITY_OPTIONS_SCHEMA
        from custom_components.sber_mqtt_bridge.websocket_api.io_export import IMPORT_CONFIG_SCHEMA

        options = {SENSOR_TEMP_OPTION_TEMP_UNIT_VIEW: False}
        assert ENTITY_OPTIONS_SCHEMA(options) == options
        payload = {"version": 3, "gate_options": {"sensor.temp": options}}
        assert IMPORT_CONFIG_SCHEMA(payload)["gate_options"]["sensor.temp"] == options
        with pytest.raises(vol.Invalid):
            ENTITY_OPTIONS_SCHEMA({SENSOR_TEMP_OPTION_TEMP_UNIT_VIEW: "no"})
