"""Классы ошибок, которые валидатор раньше не замечал.

Три дыры, закрытые здесь, объединяет одно: дефект существовал, устройство
работало неправильно, а панель «Schema Validation» показывала чистый лист.

1. Пакет конфигурации (``devices`` — список) валидатор не умел даже
   разобрать: он понимал только пакет состояний (``devices`` — словарь)
   и на списке молча возвращал ``{}``.  Весь класс «неверная модель
   устройства» проверялся только офлайн-тестами.  Здесь закрыта разбор-
   ная половина; чтобы конфиг доходил до валидатора и на живом мосте,
   ``SberPublisher.publish_config`` должен ещё позвать
   ``_record_devtools`` — это соседний файл и отдельный шаг.
2. Объявленные функции не сверялись с категорией: выдуманное имя,
   которое ни разу не попало в состояние, не видел никто.
3. «Объявлено, но не публикуется» (issue #63) не ловилось вовсе — в
   приложении Сбера появлялась ручка, которая никогда не оживает.
"""

from __future__ import annotations

import json

from custom_components.sber_mqtt_bridge import schema_validator
from custom_components.sber_mqtt_bridge._generated import (
    COMMAND_ONLY_FEATURES,
    EVENT_ONLY_FEATURES,
    STATE_BEARING_FEATURES,
)
from custom_components.sber_mqtt_bridge.devices.light import LightEntity
from custom_components.sber_mqtt_bridge.schema_validator import (
    EVENT_SHAPED_STATE_FEATURES,
    ValidationCollector,
    validate_publish,
)


def _state(key: str, type_: str, **body) -> dict:
    """Собрать одну запись ``states`` в формате Sber."""
    return {"key": key, "value": {"type": type_, **body}}


def _config_device(device_id: str, category: str, features: list[str]) -> dict:
    """Собрать дескриптор устройства в том виде, в каком он идёт в ``up/config``.

    Все поля, которые Сбер помечает обязательными, здесь заполнены — иначе
    проверка ``missing_required_field`` справедливо ругалась бы на сам
    стенд теста, а не на то, ради чего тест написан.
    """
    return {
        "id": device_id,
        "name": device_id,
        "default_name": device_id,
        "room": "Комната",
        "model": {
            "id": f"Mdl_{category}",
            "manufacturer": "HA-SberBridge",
            "model": "Generic",
            "category": category,
            "features": features,
        },
    }


def _types(issues) -> list[str]:
    """Список типов найденных замечаний — компактнее, чем сравнивать объекты."""
    return [i.type for i in issues]


class TestConfigPayloadReachesTheValidator:
    """Дыра 1: пакет конфигурации проходил мимо валидатора."""

    def test_config_payload_is_parsed_and_recorded(self) -> None:
        """Список ``devices`` разбирается наравне со словарём.

        Если тест упадёт — на живом стенде снова не будет проверяться
        ни одна ошибка в модели устройства: пользователь увидит пустую
        панель валидации, пока Сбер молча отбрасывает его устройства.
        """
        collector = ValidationCollector()
        payload = json.dumps(
            {"devices": [_config_device("light.x", "light", ["online", "on_off", "kitchen_water_level"])]}
        )

        result = collector.record_publish_payload(payload)

        assert list(result) == ["light.x"]
        assert _types(result["light.x"]) == ["unknown_for_category"]
        assert result["light.x"][0].key == "kitchen_water_level"

    def test_correct_model_produces_nothing(self) -> None:
        """Правильная модель не должна ловить «функция отсутствует в публикации».

        В пакете конфигурации состояний нет вообще, поэтому проверки
        содержимого выключены.  Если тест упадёт — каждый публикуемый
        конфиг зальёт панель ошибками об «отсутствующих» значениях,
        которых там и не должно быть.
        """
        collector = ValidationCollector()
        payload = {"devices": [_config_device("light.x", "light", ["online", "on_off"])]}

        assert collector.record_publish_payload(payload) == {"light.x": []}

    def test_hub_descriptor_stays_clean(self) -> None:
        """Служебный хаб ``root`` идёт в том же пакете и не должен шуметь."""
        collector = ValidationCollector()
        payload = {"devices": [_config_device("root", "hub", ["online"])]}

        assert collector.record_publish_payload(payload) == {"root": []}

    def test_entries_without_an_id_are_skipped(self) -> None:
        """Запись, которую не к чему привязать, пропускается молча.

        Замечание адресуется устройством: без ``id`` его некуда положить
        ни в таблицу «здоровье устройств», ни в ленту. Жаловаться
        пользователю на мусор, которого он не писал, — чистый шум.

        Что сломается у пользователя, если тест упадёт: панель получит
        строки без устройства и либо не отрисует их, либо свалится на
        отсутствующем ключе.
        """
        collector = ValidationCollector()
        payload = {"devices": ["строка", {"model": {"category": "light"}}, {"id": ""}]}

        assert collector.record_publish_payload(payload) == {}

    def test_descriptor_without_a_model_is_reported_not_skipped(self) -> None:
        """Устройство с одним лишь ``id`` разбирается, а не выбрасывается.

        Сбер разрешает описать устройство либо вложенной ``model``, либо
        ``model_id`` уже зарегистрированной. Дескриптор без обеих —
        настоящая поломка, и проверки на неё в
        :func:`validate_device_descriptor` есть.

        Что сломается у пользователя, если тест упадёт: коллектор снова
        начнёт отфильтровывать такой дескриптор до проверок, и половина
        ``validate_device_descriptor`` останется достижимой только из
        тестов — устройство молча не появится в приложении, а панель
        покажет его здоровым.
        """
        collector = ValidationCollector()
        result = collector.record_publish_payload({"devices": [{"id": "no-model"}]})

        assert list(result) == ["no-model"]
        keys = {i.message_key for i in result["no-model"]}
        assert "device_missing_model" in keys
        assert keys >= {"device_missing_field"}

    def test_config_and_status_findings_live_side_by_side(self) -> None:
        """Публикация конфига не стирает то, что нашла публикация состояний.

        Конфиг и статус на живом мосте чередуются.  Если тест упадёт —
        устройство с испорченной моделью будет выглядеть здоровым ровно
        до следующего конфига и обратно, и пользователь не поймёт,
        почему замечание «мигает».
        """
        collector = ValidationCollector()
        collector.record_publish_payload(
            {"devices": {"climate.a": {"states": [_state("on_off", "BOOL", bool_value=True)]}}},
            categories={"climate.a": "hvac_ac"},
        )
        before = len(collector.snapshot()["by_entity"]["climate.a"])
        assert before, "предусловие: у climate.a есть замечания по состоянию"

        collector.record_publish_payload(
            {"devices": [_config_device("climate.a", "hvac_ac", ["online", "hvac_temp_set", "kitchen_water_level"])]}
        )

        merged = collector.snapshot()["by_entity"]["climate.a"]
        assert len(merged) > before
        assert "unknown_for_category" in [i["type"] for i in merged]

    def test_the_same_problem_is_not_reported_twice(self) -> None:
        """Одна ошибка — одна строка в панели, даже если её видят обе публикации.

        Выдуманная функция и объявлена, и публикуется, поэтому её находят
        и модельная, и состоянческая проверка.  Если тест упадёт —
        пользователь увидит две записи об одной опечатке и решит, что
        сломаны две вещи.
        """
        collector = ValidationCollector()
        collector.record_publish_payload(
            {
                "devices": {
                    "light.x": {
                        "states": [
                            _state("online", "BOOL", bool_value=True),
                            _state("kitchen_water_level", "INTEGER", integer_value="5"),
                        ]
                    }
                }
            },
            categories={"light.x": "light"},
            declared_features={"light.x": ["online", "kitchen_water_level"]},
        )
        collector.record_publish_payload(
            {"devices": [_config_device("light.x", "light", ["online", "kitchen_water_level"])]}
        )

        merged = collector.snapshot()["by_entity"]["light.x"]
        unknown = [i for i in merged if i["type"] == "unknown_for_category"]
        assert len(unknown) == 1, merged


class TestDeclaredFeaturesCheckedAgainstCategory:
    """Дыра 2: объявленные функции не сверялись со справочником категории."""

    def test_feature_alien_to_the_category_is_flagged(self) -> None:
        """Функция из другой категории в списке ``features`` — замечание.

        Раньше проверялись только ключи, попавшие в состояние, поэтому
        ``kitchen_water_level`` у лампы не видел никто.  Если тест
        упадёт — опечатка в ручном ``sber_features_add`` снова станет
        невидимой, а в приложении появится нерабочая ручка.
        """
        issues = validate_publish(
            entity_id="light.x",
            category="light",
            states=[
                _state("online", "BOOL", bool_value=True),
                _state("on_off", "BOOL", bool_value=True),
            ],
            declared_features=["online", "on_off", "kitchen_water_level"],
        )

        assert _types(issues) == ["unknown_for_category"]
        assert issues[0].key == "kitchen_water_level"
        assert issues[0].details == {"source": "model"}

    def test_published_alien_feature_is_reported_once(self) -> None:
        """Ключ, который и объявлен, и опубликован, — всё равно одно замечание."""
        issues = validate_publish(
            entity_id="light.x",
            category="light",
            states=[
                _state("online", "BOOL", bool_value=True),
                _state("kitchen_water_level", "INTEGER", integer_value="5"),
            ],
            declared_features=["online", "kitchen_water_level"],
        )

        unknown = [i for i in issues if i.type == "unknown_for_category"]
        assert len(unknown) == 1
        assert unknown[0].details == {"source": "state"}

    def test_unknown_category_stays_silent(self) -> None:
        """Незнакомую категорию сверять не с чем — молчим, а не ругаемся."""
        issues = validate_publish(
            entity_id="x.y",
            category="future_category",
            states=[],
            declared_features=["online", "whatever"],
        )

        assert issues == []


class TestDeclaredButNotPublished:
    """Дыра 3 (issue #63): объявлено в модели, но в состоянии не приходит."""

    def test_state_bearing_feature_missing_from_publish_is_warning(self) -> None:
        """Лампа объявила яркость, но её не публикует — ползунок мёртв.

        Если тест упадёт — вернётся ровно тот класс дефектов, ради
        которого заведён issue #63: в приложении Сбера есть ручка,
        которая никогда не меняет значение, и понять почему нельзя.
        """
        issues = validate_publish(
            entity_id="light.x",
            category="light",
            states=[
                _state("online", "BOOL", bool_value=True),
                _state("on_off", "BOOL", bool_value=True),
            ],
            declared_features=["online", "on_off", "light_brightness"],
            check_completeness=True,
        )

        assert _types(issues) == ["declared_not_published"]
        assert issues[0].key == "light_brightness"
        # Полнота нормативно обязательна только для ответа на запрос
        # состояния, спонтанный push может быть частичным — поэтому
        # предупреждение, а не ошибка.
        assert issues[0].severity == "warning"

    def test_check_is_opt_in(self) -> None:
        """Без явного запроса проверка не работает — частичный push легален.

        Если тест упадёт, каждый вызывающий, который спрашивает «законен
        ли этот payload», начнёт получать ответ на другой вопрос —
        «полностью ли собрано устройство».
        """
        issues = validate_publish(
            entity_id="light.x",
            category="light",
            states=[_state("online", "BOOL", bool_value=True), _state("on_off", "BOOL", bool_value=True)],
            declared_features=["online", "on_off", "light_brightness"],
        )

        assert issues == []

    def test_command_only_feature_is_exempt(self) -> None:
        """``open_set`` нечего публиковать: он не хранит состояние.

        Если тест упадёт — каждая штора и каждые ворота получат вечное
        замечание о функции, которой по определению нет значения.
        """
        issues = validate_publish(
            entity_id="cover.c",
            category="curtain",
            states=[
                _state("online", "BOOL", bool_value=True),
                _state("open_state", "ENUM", enum_value="open"),
            ],
            declared_features=["online", "open_set", "open_state"],
            check_completeness=True,
        )

        assert issues == []

    def test_event_only_feature_is_exempt(self) -> None:
        """Молчание ``pir`` — это и есть «движения нет» (issue #61)."""
        issues = validate_publish(
            entity_id="binary_sensor.pir",
            category="sensor_pir",
            states=[_state("online", "BOOL", bool_value=True)],
            declared_features=["online", "pir"],
            check_completeness=True,
        )

        assert issues == []

    def test_button_events_are_exempt(self) -> None:
        """Многокнопочный пульт сообщает про нажатую кнопку, а не про все сразу.

        Сбер помечает все ``button_*_event`` как «хранит состояние
        устройства и может менять его», хотя ведут они себя как события.
        Если бы мы верили пометке буквально, шестикнопочная панель на
        каждой публикации давала бы пять замечаний из воздуха.
        """
        declared = ["online", *(f"button_{n}_event" for n in range(1, 7))]
        issues = validate_publish(
            entity_id="input_boolean.remote",
            category="scenario_button",
            states=[
                _state("online", "BOOL", bool_value=True),
                _state("button_3_event", "ENUM", enum_value="click"),
            ],
            declared_features=declared,
            check_completeness=True,
        )

        assert issues == []

    def test_alien_feature_is_not_reported_twice(self) -> None:
        """Выдуманное имя — одна ошибка, а не «чужое» плюс «не публикуется».

        Совет пользователю в обоих случаях один: убрать функцию.  Две
        строки об одном и том же читаются как две поломки.
        """
        issues = validate_publish(
            entity_id="light.x",
            category="light",
            states=[
                _state("online", "BOOL", bool_value=True),
                _state("on_off", "BOOL", bool_value=True),
            ],
            declared_features=["online", "on_off", "kitchen_water_level"],
            check_completeness=True,
        )

        assert _types(issues) == ["unknown_for_category"]

    def test_full_snapshot_caller_can_turn_the_check_on(self) -> None:
        """Полный снимок состояний просит проверку явным флагом.

        Если тест упадёт — issue #63 перестанет быть виден на стенде,
        а именно там его и надо ловить.
        """
        collector = ValidationCollector()

        result = collector.record_publish_payload(
            {
                "devices": {
                    "light.x": {
                        "states": [
                            _state("online", "BOOL", bool_value=True),
                            _state("on_off", "BOOL", bool_value=True),
                        ]
                    }
                }
            },
            categories={"light.x": "light"},
            declared_features={"light.x": ["online", "on_off", "light_brightness"]},
            check_completeness=True,
        )

        assert _types(result["light.x"]) == ["declared_not_published"]

    def test_check_is_off_unless_the_caller_asks(self) -> None:
        """Без флага коллектор о полноте не судит.

        Через коллектор проходит не только полный снимок, но и командное
        эхо, которое часть ключей выбрасывает намеренно.  Если тест
        упадёт — включённая по умолчанию проверка снова начнёт обвинять
        частичные публикации в том, чего они и не обещали.
        """
        collector = ValidationCollector()

        result = collector.record_publish_payload(
            {
                "devices": {
                    "light.x": {
                        "states": [
                            _state("online", "BOOL", bool_value=True),
                            _state("on_off", "BOOL", bool_value=True),
                        ]
                    }
                }
            },
            categories={"light.x": "light"},
            declared_features={"light.x": ["online", "on_off", "light_brightness"]},
        )

        assert result["light.x"] == []

    def test_command_echo_of_a_healthy_lamp_stays_clean(self) -> None:
        """Переключение цвет→белый на исправной лампе не рисует замечание.

        Эхо строится теми же средствами, что и на живом мосте:
        ``sanitize_echo_states`` намеренно снимает ``light_colour``, раз
        лампа перешла в режим ``white``.  Если тест упадёт — каждая
        обычная команда пользователя будет оставлять в панели
        «Schema Validation» жёлтую строку про исправную лампу, а
        ``current_validation_issues`` в диагностике перестанет означать
        «есть настоящая проблема».
        """
        lamp = LightEntity({"entity_id": "light.rgb", "name": "RGB"})
        lamp.fill_by_ha_state(
            {
                "entity_id": "light.rgb",
                "state": "on",
                "attributes": {
                    "brightness": 200,
                    "hs_color": (240, 100),
                    "color_mode": "hs",
                    "supported_color_modes": ["hs", "color_temp"],
                    "color_temp_kelvin": 4000,
                    "min_color_temp_kelvin": 2000,
                    "max_color_temp_kelvin": 6500,
                },
            }
        )
        declared = lamp.get_final_features_list()
        assert "light_colour" in declared, "предусловие: лампа объявляет цвет"

        # Эхо = текущее состояние с наложенной командой, прогнанное через
        # тот же санитайзер, что и в SberPublisher.publish_command_echo.
        commanded = _state("light_mode", "ENUM", enum_value="white")
        baseline = lamp.to_sber_current_state()["light.rgb"]["states"]
        merged = [commanded if s["key"] == "light_mode" else s for s in baseline]
        echo_states = lamp.sanitize_echo_states(merged, {"light_mode"})
        assert "light_colour" not in [s["key"] for s in echo_states], "предусловие: эхо снимает цвет"

        collector = ValidationCollector()
        result = collector.record_publish_payload(
            {"devices": {"light.rgb": {"states": echo_states}}},
            categories={"light.rgb": lamp.category},
            declared_features={"light.rgb": declared},
        )

        assert result["light.rgb"] == []
        assert collector.snapshot()["recent"] == []


class TestUsageModeConstants:
    """Классификация функций, на которой держатся проверки выше."""

    def test_the_three_sets_do_not_overlap(self) -> None:
        """Функция бывает либо командной, либо событийной, либо со состоянием.

        Пересечение означало бы, что проверка «объявлено, но не
        публикуется» одновременно и требует значение, и освобождает от
        него — поведение стало бы зависеть от порядка проверок.
        """
        assert not STATE_BEARING_FEATURES & COMMAND_ONLY_FEATURES
        assert not STATE_BEARING_FEATURES & EVENT_ONLY_FEATURES
        assert not COMMAND_ONLY_FEATURES & EVENT_ONLY_FEATURES

    def test_button_events_are_carved_out_of_state_bearing(self) -> None:
        """Оговорка про ``button_*_event`` берётся из самого справочника.

        Если Сбер переклассифицирует их, набор станет пустым и оговорка
        исчезнет сама — руками её поддерживать не надо.
        """
        assert EVENT_SHAPED_STATE_FEATURES <= STATE_BEARING_FEATURES
        assert "button_1_event" in EVENT_SHAPED_STATE_FEATURES
        assert "on_off" not in EVENT_SHAPED_STATE_FEATURES

    def test_validator_uses_the_generated_sets_verbatim(self) -> None:
        """Валидатор берёт классификацию из ``_generated``, а не свою копию.

        Проверяется тождество объектов: рукописный дубликат прошёл бы по
        значению, но молча протух бы на следующем скрейпе спеки.  Если
        тест упадёт — часть проверок будет судить по устаревшей
        классификации, и «объявлено, но не публикуется» начнёт то
        промахиваться, то ругаться на исправные устройства.
        """
        assert schema_validator.STATE_BEARING_FEATURES is STATE_BEARING_FEATURES
        assert schema_validator.EVENT_ONLY_FEATURES is EVENT_ONLY_FEATURES
