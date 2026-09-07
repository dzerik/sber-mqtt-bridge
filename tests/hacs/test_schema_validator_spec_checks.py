"""Проверки валидатора, построенные на структурных страницах документации Sber.

До этой партии валидатор читал только таблицы функций и категорий:
какие функции у категории есть, какого они типа, какие значения
перечислены.  Как устроен сам *конверт* — объект ``value``, описание
модели, ``allowed_values`` — не проверялось ничем, поэтому пакет вида
``{"type": "INTEGER", "integer_value": 42}`` (число вместо строки)
проходил все проверки и молча терялся в облаке.

Здесь закрыты три группы правил, и все три взяты со структурных страниц
``/value``, ``/model``, ``/device`` и ``/allowed_values``:

1. **Форма значения** — ``value_shape`` и ``colour_out_of_range``.
2. **Обязательность в модели** — ``not_declared`` (функцию, которую
   устройство поддерживает, Sber требует объявить в модели) и
   ``missing_required_field``.
3. **Нормативы протокола** — ``allowed_values_*`` и лимит
   ``partner_meta``.

Главный принцип этого файла: **ложное срабатывание хуже пропуска**.
Поэтому здесь два корпуса «тишины», и оба взяты не из головы:

* эталонные примеры самого Sber — 29 моделей категорий и 96 примеров
  состояний функций из снапшота документации;
* реальный выход моста — по одному максимально «богатому» устройству
  каждой из 29 категорий, прогнанному через настоящие классы устройств.

Если валидатор начнёт ругаться на любой из этих двух корпусов, значит он
будет ругаться и на исправный стенд пользователя.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from custom_components.sber_mqtt_bridge._generated.reference_values import FEATURE_RANGES
from custom_components.sber_mqtt_bridge._generated.usage_modes import STATE_BEARING_FEATURES
from custom_components.sber_mqtt_bridge.sber_entity_map import CATEGORY_DOMAIN_MAP
from custom_components.sber_mqtt_bridge.schema_validator import (
    _CATEGORY_RANGE_SANCTIONED,
    ALLOWED_VALUES_TYPES,
    COLOUR_COMPONENT_RANGES,
    PARTNER_META_MAX_CHARS,
    VALUE_FIELD_BY_TYPE,
    validate_device_descriptor,
    validate_publish,
)

SPEC_PATH = Path(__file__).parent / "__snapshots__" / "sber_full_spec.json"
"""Снапшот документации Sber — источник обоих эталонных корпусов."""

NEW_ISSUE_KINDS: frozenset[str] = frozenset(
    {
        "value_shape",
        "colour_out_of_range",
        "missing_required_field",
        "partner_meta_too_long",
        "allowed_values_widened",
        "allowed_values_shape",
        "allowed_values_inert",
    }
)
"""Замечания, добавленные этой партией.

Тесты «тишины» смотрят только на них: остальные проверки валидатора уже
покрыты своими файлами, и смешивать их сюда значило бы ловить чужие
регрессии в непонятном месте."""


FLOAT_QUOTED_IN_DOC_EXAMPLE: frozenset[str] = frozenset({"hcho_float", "tvoc_float"})
"""Функции, чей пример состояния противоречит структурной странице Sber.

Страница ``/value`` объявляет ``float_value`` числом ("number"), а
примеры на страницах ``hcho_float`` и ``tvoc_float`` показывают его
строкой (``"0.205"``).  Оба утверждения одновременно верными быть не
могут; нормативной считается структурная страница — она описывает сам
конверт, а не иллюстрирует одну функцию.  Наш ``devices/sensor_air.py``
шлёт настоящее число и, значит, прав.

Список зафиксирован явно, а не обойдён молча: если Sber починит примеры,
тест :meth:`TestSberOwnExamplesStaySilent.test_only_known_examples_contradict_the_docs`
об этом скажет, и запись надо будет удалить."""


def _spec() -> dict[str, Any]:
    """Прочитать снапшот документации.

    Returns:
        Разобранный снапшот.
    """
    return json.loads(SPEC_PATH.read_text(encoding="utf-8"))


SPEC = _spec()
CATEGORIES: dict[str, Any] = SPEC.get("categories", {})
FUNCTIONS: dict[str, Any] = SPEC.get("functions", {})


def _state(key: str, type_: str, **body: Any) -> dict[str, Any]:
    """Собрать одну запись ``states`` в формате Sber.

    Args:
        key: Имя функции.
        type_: Тип значения (``BOOL``, ``INTEGER``, …).
        **body: Поля полезной нагрузки (``bool_value`` и т. п.).

    Returns:
        Запись состояния.
    """
    return {"key": key, "value": {"type": type_, **body}}


def _device(
    *,
    device_id: str = "light.probe",
    category: str = "light",
    features: list[str] | None = None,
    allowed_values: dict[str, Any] | None = None,
    **overrides: Any,
) -> dict[str, Any]:
    """Собрать дескриптор устройства так, как его строит мост.

    Все поля, которые Sber помечает обязательными, заполнены — тест не
    должен спотыкаться о собственный стенд.

    Args:
        device_id: Идентификатор устройства.
        category: Категория Sber.
        features: Список объявленных функций.
        allowed_values: Карта ограничений модели.
        **overrides: Поля, которые надо переопределить или удалить
            (значение ``None`` удаляет поле — так проверяется
            обязательность).

    Returns:
        Дескриптор устройства для ``up/config``.
    """
    model: dict[str, Any] = {
        "id": f"Mdl_{category}_deadbeef",
        "manufacturer": "HA-SberBridge",
        "model": "Probe",
        "description": "Probe",
        "category": category,
        "features": features if features is not None else ["online", "on_off"],
    }
    if allowed_values is not None:
        model["allowed_values"] = allowed_values
    descriptor: dict[str, Any] = {
        "id": device_id,
        "name": "Проба",
        "default_name": "Проба",
        "room": "Комната",
        "model": model,
    }
    for key, value in overrides.items():
        if value is None:
            descriptor.pop(key, None)
        else:
            descriptor[key] = value
    return descriptor


def _new_kind_issues(issues: list[Any]) -> list[Any]:
    """Отфильтровать только замечания, добавленные этой партией.

    Args:
        issues: Полный список замечаний.

    Returns:
        Замечания новых типов.
    """
    return [i for i in issues if i.type in NEW_ISSUE_KINDS]


# ---------------------------------------------------------------------------
#  Корпус тишины №1 — эталонные примеры самого Sber
# ---------------------------------------------------------------------------


class TestSberOwnExamplesStaySilent:
    """Ни одна новая проверка не имеет права ругаться на пример из документации."""

    @pytest.mark.parametrize("category", sorted(CATEGORIES))
    def test_reference_model_of_every_category_is_clean(self, category: str) -> None:
        """Эталонная модель каждой из 29 категорий проходит проверки молча.

        Что сломается у пользователя, если тест упадёт: валидатор начнёт
        считать нарушением ровно то, что Sber публикует у себя как
        образец.  На стенде это выглядит как красные и жёлтые отметки на
        исправных устройствах — панель после такого перестают читать, и
        настоящая поломка теряется среди выдуманных.
        """
        body = CATEGORIES[category]
        descriptor = _device(
            device_id=f"probe.{category}",
            category=category,
            features=list(body.get("features", [])),
            allowed_values=body.get("allowed_values") or None,
        )
        found = _new_kind_issues(validate_device_descriptor(descriptor))
        assert found == [], [f"{i.type}/{i.key}: {i.description}" for i in found]

    @pytest.mark.parametrize("category", sorted(CATEGORIES))
    def test_reference_states_of_every_category_are_clean(self, category: str) -> None:
        """Состояния, собранные из примеров Sber, проходят проверки молча.

        Для каждой функции категории берётся «Пример описания состояния
        функции» с её собственной страницы — то есть пакет, который Sber
        сам называет правильным.

        Что сломается у пользователя, если тест упадёт: проверка формы
        значения начнёт отвергать корректные пакеты, и мост будет
        сообщать об ошибке при каждой публикации исправного устройства.
        """
        body = CATEGORIES[category]
        features = list(body.get("features", []))
        states = [
            example
            for name in features
            if name not in FLOAT_QUOTED_IN_DOC_EXAMPLE
            and isinstance(example := (FUNCTIONS.get(name) or {}).get("state_example"), dict)
        ]
        if not states:
            pytest.skip(f"в снапшоте нет ни одного примера состояния для категории {category}")
        issues = validate_publish(
            entity_id=f"probe.{category}",
            category=category,
            states=states,
            declared_features=features,
            check_completeness=True,
        )
        found = _new_kind_issues(issues)
        assert found == [], [f"{i.type}/{i.key}: {i.description}" for i in found]

    @pytest.mark.parametrize("function", sorted(FUNCTIONS))
    def test_every_function_state_example_is_well_formed(self, function: str) -> None:
        """Каждый из 96 примеров состояния проходит проверку формы значения.

        Что сломается у пользователя, если тест упадёт: значит наше
        представление о конверте ``value`` разошлось с документацией —
        либо проверка стала строже, чем Sber, либо Sber поменял форму, и
        тогда мост публикует значения, которых облако уже не понимает.
        """
        if function in FLOAT_QUOTED_IN_DOC_EXAMPLE:
            pytest.skip(f"{function}: пример противоречит структурной странице /value")
        example = (FUNCTIONS.get(function) or {}).get("state_example")
        if not isinstance(example, dict) or "value" not in example:
            pytest.skip(f"в снапшоте нет примера состояния для функции {function}")
        issues = validate_publish(
            entity_id="probe.function",
            category=None,
            states=[example],
        )
        found = _new_kind_issues(issues)
        assert found == [], [f"{i.type}: {i.description}" for i in found]

    def test_only_known_examples_contradict_the_docs(self) -> None:
        """Список расхождений документации с самой собой не должен расти молча.

        Проверяется, что противоречат структурной странице ``/value``
        ровно две функции — ``hcho_float`` и ``tvoc_float``, у которых
        число показано строкой.

        Что сломается у пользователя, если тест упадёт: либо Sber
        починил примеры (тогда поблажку надо убрать), либо появилось
        новое расхождение — и тогда надо решить, чью сторону мы
        занимаем, а не молча пропускать проверку.
        """
        contradicting: set[str] = set()
        for name, body in FUNCTIONS.items():
            example = body.get("state_example")
            if not isinstance(example, dict) or "value" not in example:
                continue
            issues = validate_publish(entity_id="probe", category=None, states=[example])
            if any(i.type == "value_shape" for i in issues):
                contradicting.add(name)
        assert contradicting == FLOAT_QUOTED_IN_DOC_EXAMPLE


SBER_CONTRADICTS_ITSELF: dict[str, set[tuple[str, str]]] = {
    "led_strip": {("unknown_for_category", "sleep_timer")},
    "scenario_button": {("unknown_for_category", "battery_percentag")},
    "sensor_air": {
        ("declared_not_published", "hcho_float"),
        ("declared_not_published", "tvoc_float"),
    },
    "tv": {("unknown_enum_value", "source")},
}
"""Замечания, которые эталонный корпус вызывает по вине самой документации.

Разбор, категория за категорией:

* ``led_strip`` — пример модели на странице категории объявляет
  ``sleep_timer``, которого нет ни в таблице функций той же страницы, ни
  в каталоге ``/functions``;
* ``scenario_button`` — в примере модели написано ``battery_percentag``,
  опечатка в ``battery_percentage``;
* ``sensor_air`` — ``hcho_float`` и ``tvoc_float`` исключены из корпуса
  как :data:`FLOAT_QUOTED_IN_DOC_EXAMPLE` (их примеры противоречат
  структурной странице ``/value``), поэтому объявленная функция остаётся
  без значения — артефакт исключения, а не находка;
* ``tv`` — пример состояния функции ``source`` шлёт ``HDMI1``, а словарь
  той же страницы знает только ``hdmi1``.

Список закрытый: он существует, чтобы «тишину» можно было проверять по
ВСЕМ типам замечаний, а не только по добавленным этой партией."""


class TestSberOwnExamplesStaySilentOnEveryCheck:
    """Тишина на эталонном корпусе — по всем проверкам, а не только по новым.

    Соседний :class:`TestSberOwnExamplesStaySilent` фильтрует находки
    через :data:`NEW_ISSUE_KINDS`, и старые типы замечаний он поэтому не
    видит вовсе. Именно так и разошлись две половины валидатора: модель
    бойлера со ссылкой на :data:`_CATEGORY_RANGE_SANCTIONED` считалась
    исправной, а каждая публикация её состояния получала
    ``out_of_range``.
    """

    @pytest.mark.parametrize("category", sorted(CATEGORIES))
    def test_reference_states_are_clean_including_the_older_checks(self, category: str) -> None:
        """Эталонные состояния категории молчат по всем типам замечаний.

        Что сломается у пользователя, если тест упадёт: устройство,
        собранное точно по примеру Sber, будет помечено в панели как
        неисправное — и владелец начнёт чинить то, что не сломано, а
        настоящая поломка утонет среди выдуманных.
        """
        body = CATEGORIES[category]
        features = list(body.get("features", []))
        states = [
            example
            for name in features
            if name not in FLOAT_QUOTED_IN_DOC_EXAMPLE
            and isinstance(example := (FUNCTIONS.get(name) or {}).get("state_example"), dict)
        ]
        if not states:
            pytest.skip(f"в снапшоте нет ни одного примера состояния для категории {category}")
        issues = validate_publish(
            entity_id=f"probe.{category}",
            category=category,
            states=states,
            declared_features=features,
            check_completeness=True,
        )
        known = SBER_CONTRADICTS_ITSELF.get(category, set())
        found = [i for i in issues if (i.type, i.key) not in known]
        assert found == [], [f"{i.type}/{i.key}: {i.description}" for i in found]

    def test_the_list_of_documentation_contradictions_does_not_shrink_silently(self) -> None:
        """Каждое исключение всё ещё воспроизводится на снапшоте.

        Что сломается у пользователя, если тест упадёт: Sber починил
        свою документацию, а у нас остался слепой глаз — ровно то же
        замечание на настоящем устройстве пройдёт мимо проверки.
        """
        still_seen: dict[str, set[tuple[str, str]]] = {}
        for category in SBER_CONTRADICTS_ITSELF:
            body = CATEGORIES[category]
            features = list(body.get("features", []))
            states = [
                example
                for name in features
                if name not in FLOAT_QUOTED_IN_DOC_EXAMPLE
                and isinstance(example := (FUNCTIONS.get(name) or {}).get("state_example"), dict)
            ]
            issues = validate_publish(
                entity_id=f"probe.{category}",
                category=category,
                states=states,
                declared_features=features,
                check_completeness=True,
            )
            still_seen[category] = {(i.type, str(i.key)) for i in issues}
        for category, expected in SBER_CONTRADICTS_ITSELF.items():
            assert expected <= still_seen[category], f"{category}: исключение больше не воспроизводится"


class TestBothScopesJudgeRangesByOneRule:
    """Конфиг и состояние обязаны судить о диапазоне одинаково.

    Иначе выходит абсурд, который панель и показывала: устройство,
    скопированное с эталонной модели самого Sber, признаётся исправным в
    ``up/config`` и бракуется в каждом ``up/status``.
    """

    @pytest.mark.parametrize(("category", "feature"), sorted(_CATEGORY_RANGE_SANCTIONED))
    def test_a_value_the_model_may_declare_is_not_flagged_in_the_publish(self, category: str, feature: str) -> None:
        """Значение внутри поблажки молчит и в модели, и в состоянии.

        Что сломается у пользователя, если тест упадёт: бойлер с
        уставкой 75 °C — то есть внутри диапазона 5…80, который Sber
        публикует в собственном примере модели, — снова начнёт выдавать
        жёлтое ``out_of_range`` на каждой публикации состояния.
        """
        low, high = _CATEGORY_RANGE_SANCTIONED[(category, feature)]
        documented = FEATURE_RANGES[feature]
        assert high > documented[1], "предусловие: поблажка вообще шире страницы функции"
        sanctioned_only = int(high)

        descriptor = _device(
            device_id=f"probe.{category}",
            category=category,
            features=["online", feature],
            allowed_values={
                feature: {"type": "INTEGER", "integer_values": {"min": f"{low:g}", "max": f"{high:g}", "step": "1"}}
            },
        )
        model_issues = [i for i in validate_device_descriptor(descriptor) if i.type == "allowed_values_widened"]
        assert model_issues == [], [i.description for i in model_issues]

        state_issues = validate_publish(
            entity_id=f"probe.{category}",
            category=category,
            states=[{"key": feature, "value": {"type": "INTEGER", "integer_value": str(sanctioned_only)}}],
            declared_features=["online", feature],
        )
        out_of_range = [i for i in state_issues if i.type == "out_of_range"]
        assert out_of_range == [], [i.description for i in out_of_range]

    @pytest.mark.parametrize(("category", "feature"), sorted(_CATEGORY_RANGE_SANCTIONED))
    def test_a_value_beyond_the_sanction_is_still_flagged(self, category: str, feature: str) -> None:
        """Поблажка не отключает проверку, а только сдвигает границу.

        Что сломается у пользователя, если тест упадёт: диапазон
        сгоревшего пересчёта (уставка 500 °C) перестанет замечаться
        вообще — а именно ради него проверка и написана.
        """
        _low, high = _CATEGORY_RANGE_SANCTIONED[(category, feature)]
        issues = validate_publish(
            entity_id=f"probe.{category}",
            category=category,
            states=[{"key": feature, "value": {"type": "INTEGER", "integer_value": str(int(high) + 1)}}],
            declared_features=["online", feature],
        )
        assert [i.type for i in issues if i.type == "out_of_range"] == ["out_of_range"]

    def test_a_category_without_a_sanction_keeps_the_function_page_bounds(self) -> None:
        """Без поблажки действует диапазон со страницы функции.

        Что сломается у пользователя, если тест упадёт: поблажка,
        заведённая для одной категории, расползётся на все — и радиатор с
        уставкой 80 °C уедет в облако без единого замечания.
        """
        assert ("hvac_radiator", "hvac_temp_set") not in _CATEGORY_RANGE_SANCTIONED
        issues = validate_publish(
            entity_id="probe.hvac_radiator",
            category="hvac_radiator",
            states=[{"key": "hvac_temp_set", "value": {"type": "INTEGER", "integer_value": "80"}}],
            declared_features=["online", "hvac_temp_set"],
        )
        flagged = [i for i in issues if i.type == "out_of_range"]
        assert [i.details["max"] for i in flagged] == [FEATURE_RANGES["hvac_temp_set"][1]]


class TestSanctionedRangesArePinnedToTheDocs:
    """Список «Sber сам себе противоречит» не должен превратиться в свалку."""

    def test_every_sanctioned_range_is_still_in_the_snapshot(self) -> None:
        """Каждое исключение подтверждается примером категории из снапшота.

        Что сломается у пользователя, если тест упадёт: в валидаторе
        останется поблажка, которой документация больше не оправдывает,
        — то есть настоящее расширение диапазона перестанет замечаться.
        Если Sber починит свой пример, исключение надо удалять, а не
        править тест.
        """
        for (category, feature), bounds in sorted(_CATEGORY_RANGE_SANCTIONED.items()):
            example = (CATEGORIES.get(category, {}).get("allowed_values") or {}).get(feature)
            assert example is not None, f"{category}/{feature}: примера в снапшоте больше нет"
            block = example.get("integer_values") or example.get("float_values") or {}
            documented = FEATURE_RANGES.get(feature)
            assert documented is not None, f"{feature}: у функции пропал документированный диапазон"
            assert bounds[0] <= documented[0], f"{category}/{feature}: поблажка ослабляет нижнюю границу"
            assert bounds[1] >= float(block["max"]), (
                f"{category}/{feature}: пример Sber выходит за поблажку — обновите её"
            )

    def test_no_sanction_is_needed_where_the_docs_agree(self) -> None:
        """Поблажка заведена только там, где пример шире страницы функции.

        Что сломается у пользователя, если тест упадёт: в списке
        исключений появится пара, для которой документация не
        противоречива, и мы просто перестанем проверять её диапазон.
        """
        for (category, feature), _bounds in sorted(_CATEGORY_RANGE_SANCTIONED.items()):
            example = (CATEGORIES.get(category, {}).get("allowed_values") or {}).get(feature, {})
            block = example.get("integer_values") or example.get("float_values") or {}
            documented = FEATURE_RANGES[feature]
            wider = float(block["min"]) < documented[0] or float(block["max"]) > documented[1]
            assert wider, f"{category}/{feature}: пример укладывается в документацию, поблажка не нужна"


# ---------------------------------------------------------------------------
#  Корпус тишины №2 — настоящий выход моста по всем 29 категориям
# ---------------------------------------------------------------------------


_PROBE_ATTRS: dict[str, Any] = {
    # свет
    "supported_color_modes": ["hs", "color_temp"],
    "color_mode": "hs",
    "brightness": 128,
    "hs_color": [120, 50],
    "color_temp_kelvin": 3000,
    # климат и водонагреватели
    "current_temperature": 21.5,
    "temperature": 23,
    "min_temp": 5,
    "max_temp": 35,
    "target_temp_step": 1,
    "hvac_modes": ["off", "cool", "heat", "auto"],
    "hvac_action": "cooling",
    "fan_mode": "auto",
    "fan_modes": ["auto", "low", "high"],
    "swing_mode": "off",
    "swing_modes": ["off", "vertical"],
    "preset_mode": "boost",
    "preset_modes": ["boost", "sleep"],
    "operation_list": ["eco", "performance"],
    # увлажнение и качество воздуха
    "humidity": 55,
    "current_humidity": 48,
    "min_humidity": 30,
    "max_humidity": 80,
    "available_modes": ["normal", "sleep"],
    "mode": "normal",
    # вентиляторы и пылесосы
    "percentage": 40,
    "percentage_step": 10,
    "oscillating": False,
    "fan_speed": "turbo",
    "fan_speed_list": ["quiet", "standard", "turbo"],
    # шторы и краны
    "current_position": 60,
    "current_tilt_position": 30,
    # медиаплеер
    "volume_level": 0.3,
    "is_volume_muted": False,
    "source": "HDMI 1",
    "source_list": ["HDMI 1", "TV"],
    # датчики
    "battery_level": 77,
    "signal_strength": -55,
    "sensitivity": "high",
    "carbon_dioxide": 600,
    "pm25": 12,
}
"""Богатый набор атрибутов HA: устройство объявляет максимум возможностей."""

_EXPECTED_INFO: dict[str, set[str]] = {}
"""Категории, у которых замечания уровня ``info`` ожидаются осознанно.

Пусто: последним жильцом была пара ``light`` / ``led_strip`` с записью
``allowed_values['light_colour'] = {"type": "COLOUR"}`` — документация
разрешает переопределять только FLOAT / INTEGER / ENUM, и запись убрана.
Словарь оставлен как точка расширения: любое новое ``info`` на исправной
конфигурации обязано быть либо починено, либо описано здесь."""


def _probe_entity(category: str) -> Any:
    """Собрать максимально «богатое» устройство указанной категории.

    Args:
        category: Ключ :data:`CATEGORY_DOMAIN_MAP`.

    Returns:
        Заполненный экземпляр класса устройства.
    """
    spec = CATEGORY_DOMAIN_MAP[category]
    device_class = (spec.device_classes or ("",))[0]
    entity = spec.cls(
        {
            "entity_id": f"{spec.domains[0]}.probe",
            "name": "Probe",
            "original_device_class": device_class,
            "device_class": device_class,
        }
    )
    entity.fill_by_ha_state({"state": "on", "attributes": dict(_PROBE_ATTRS)})
    return entity


class TestBridgeOutputStaysSilent:
    """Настоящие классы устройств не должны поднимать новых замечаний."""

    @pytest.mark.parametrize("category", sorted(CATEGORY_DOMAIN_MAP))
    def test_config_publish_of_every_category_is_clean(self, category: str) -> None:
        """Дескриптор устройства каждой категории проходит проверки молча.

        Прогоняется настоящий ``to_sber_state()``, то есть ровно то, что
        уходит в ``up/config``.

        Что сломается у пользователя, если тест упадёт: на стенде с 35+
        устройствами появятся замечания на исправной конфигурации, и
        панель валидации станет бесполезной — в ней невозможно будет
        отличить настоящую поломку от шума.
        """
        entity = _probe_entity(category)
        issues = _new_kind_issues(validate_device_descriptor(entity.to_sber_state()))
        loud = [i for i in issues if i.severity != "info"]
        assert loud == [], [f"{i.type}/{i.key}: {i.description}" for i in loud]
        assert {i.type for i in issues} == _EXPECTED_INFO.get(category, set())

    @pytest.mark.parametrize("category", sorted(CATEGORY_DOMAIN_MAP))
    def test_status_publish_of_every_category_is_clean(self, category: str) -> None:
        """Пакет состояния каждой категории проходит проверки молча.

        Что сломается у пользователя, если тест упадёт: каждая публикация
        состояния (а их десятки в минуту) начнёт порождать замечание —
        кольцевой буфер панели забьётся за секунды.
        """
        entity = _probe_entity(category)
        states = entity.to_sber_current_state()[entity.entity_id]["states"]
        issues = validate_publish(
            entity_id=entity.entity_id,
            category=entity.category,
            states=states,
            declared_features=entity.get_final_features_list(),
            check_completeness=True,
        )
        found = _new_kind_issues(issues)
        assert found == [], [f"{i.type}/{i.key}: {i.description}" for i in found]


# ---------------------------------------------------------------------------
#  Форма значения
# ---------------------------------------------------------------------------


class TestValueShape:
    """``value`` — конверт со своими правилами, и их до сих пор никто не проверял."""

    def test_integer_sent_as_number_is_an_error(self) -> None:
        """Целое число без кавычек — ошибка.

        Sber описывает ``integer_value`` как «целочисленное значение
        long, записанное в виде строки».

        Что сломается у пользователя, если тест упадёт: самый вероятный
        способ незаметно сломать устройство вернётся в слепую зону —
        пакет уходит в облако, выглядит правильным в журнале, и просто
        не доезжает.  В приложении это выглядит как «регулятор есть, а
        значение не меняется».
        """
        issues = validate_publish(
            entity_id="light.x",
            category="light",
            states=[_state("light_brightness", "INTEGER", integer_value=500)],
        )
        shape = [i for i in issues if i.type == "value_shape"]
        assert [i.key for i in shape] == ["light_brightness"]
        assert shape[0].severity == "error"
        assert shape[0].details["field"] == "integer_value"
        assert shape[0].details["expected"] == "string"

    def test_integer_sent_as_string_is_accepted(self) -> None:
        """Правильно оформленное целое замечаний не вызывает.

        Что сломается у пользователя, если тест упадёт: проверка станет
        ругаться на все без исключения числовые состояния моста.
        """
        issues = validate_publish(
            entity_id="light.x",
            category="light",
            states=[_state("light_brightness", "INTEGER", integer_value="500")],
        )
        assert [i for i in issues if i.type == "value_shape"] == []

    def test_payload_under_a_foreign_key_is_an_error(self) -> None:
        """Значение под чужим полем — ошибка.

        Что сломается у пользователя, если тест упадёт: облако читает
        поле, названное типом, и ничего другого; такое состояние
        теряется целиком.
        """
        issues = validate_publish(
            entity_id="light.x",
            category="light",
            states=[{"key": "on_off", "value": {"type": "BOOL", "enum_value": "on"}}],
        )
        shape = [i for i in issues if i.type == "value_shape"]
        assert [i.details["reason"] for i in shape] == ["foreign_fields"]
        assert shape[0].details["foreign"] == ["enum_value"]

    def test_unknown_value_type_is_an_error(self) -> None:
        """Тип, которого у Sber нет, — ошибка.

        Что сломается у пользователя, если тест упадёт: опечатка в типе
        (``"INT"`` вместо ``"INTEGER"``) пройдёт весь конвейер молча.
        """
        issues = validate_publish(
            entity_id="light.x",
            category="light",
            states=[{"key": "on_off", "value": {"type": "INT", "integer_value": "1"}}],
        )
        shape = [i for i in issues if i.type == "value_shape"]
        assert [i.details["reason"] for i in shape] == ["unknown_type"]

    def test_missing_type_is_an_error(self) -> None:
        """Значение без ``type`` — ошибка.

        Что сломается у пользователя, если тест упадёт: облако не знает,
        как прочитать такое значение, и отбрасывает состояние.
        """
        issues = validate_publish(
            entity_id="light.x",
            category="light",
            states=[{"key": "on_off", "value": {"bool_value": True}}],
        )
        assert [i.details["reason"] for i in issues if i.type == "value_shape"] == ["missing_type"]

    def test_proto3_elided_payload_is_not_reported(self) -> None:
        """Пропущенное поле значения замечанием НЕ считается.

        Sber сериализует protobuf по правилам proto3: поле со значением
        по умолчанию из пакета выбрасывается, поэтому ``{"type":
        "BOOL"}`` — это законное ``false``.  Эхо-ответ на команду
        пересылает значения Sber обратно ровно в том виде, в каком они
        пришли.

        Что сломается у пользователя, если тест упадёт: каждая команда
        «выключи» и каждая установка нуля будут порождать ошибку в
        панели — то самое ложное срабатывание, ради которого проверку и
        ограничили.
        """
        issues = validate_publish(
            entity_id="light.x",
            category="light",
            states=[{"key": "on_off", "value": {"type": "BOOL"}}, {"key": "online", "value": {"type": "BOOL"}}],
        )
        assert [i for i in issues if i.type == "value_shape"] == []

    def test_value_that_is_not_an_object_is_an_error(self) -> None:
        """Значение не объектом — ошибка.

        Что сломается у пользователя, если тест упадёт: строка вместо
        конверта дойдёт до облака и устройство перестанет отвечать.
        """
        issues = validate_publish(
            entity_id="light.x",
            category="light",
            states=[{"key": "on_off", "value": True}],
        )
        assert [i.details["reason"] for i in issues if i.type == "value_shape"] == ["not_an_object"]

    def test_every_documented_type_has_a_payload_field(self) -> None:
        """Таблица «тип → поле» покрывает все типы значений Sber.

        Что сломается у пользователя, если тест упадёт: для непокрытого
        типа проверка формы отключится целиком и перестанет ловить что
        бы то ни было.
        """
        assert set(VALUE_FIELD_BY_TYPE) >= {"BOOL", "INTEGER", "FLOAT", "STRING", "ENUM", "COLOUR"}


class TestColourValue:
    """``colour_value`` — единственная структура со своими границами."""

    def test_value_below_hundred_is_an_error(self) -> None:
        """Яркость цвета ниже 100 — ошибка.

        Нижняя граница ``v`` у Sber именно 100, а не 0.

        Что сломается у пользователя, если тест упадёт: лампа покажет
        не тот цвет либо погаснет в приложении, оставшись включённой в
        Home Assistant.
        """
        issues = validate_publish(
            entity_id="light.x",
            category="light",
            states=[_state("light_colour", "COLOUR", colour_value={"h": 120, "s": 500, "v": 40})],
        )
        colour = [i for i in issues if i.type == "colour_out_of_range"]
        assert [i.details["component"] for i in colour] == ["v"]
        assert colour[0].severity == "error"

    def test_hue_above_the_circle_is_an_error(self) -> None:
        """Оттенок больше 360 — ошибка.

        Что сломается у пользователя, если тест упадёт: конвертер цвета
        сможет незаметно выехать за круг, и цвет «перескочит».
        """
        issues = validate_publish(
            entity_id="light.x",
            category="light",
            states=[_state("light_colour", "COLOUR", colour_value={"h": 400, "s": 500, "v": 900})],
        )
        assert [i.details["component"] for i in issues if i.type == "colour_out_of_range"] == ["h"]

    def test_elided_components_are_not_reported(self) -> None:
        """Отсутствующие составляющие цвета замечанием не считаются.

        Ровно этот случай разбирался в issue #44: при крайнем положении
        ползунка Sber присылает ``colour_value`` без нулевых полей.

        Что сломается у пользователя, если тест упадёт: эхо на команду
        смены цвета начнёт порождать ошибку при каждом переводе ползунка
        в край.
        """
        issues = validate_publish(
            entity_id="light.x",
            category="light",
            states=[_state("light_colour", "COLOUR", colour_value={"h": 120})],
        )
        assert [i for i in issues if i.type == "colour_out_of_range"] == []

    def test_bounds_come_from_the_documentation(self) -> None:
        """Границы HSV взяты из снапшота, а не вписаны руками.

        Что сломается у пользователя, если тест упадёт: значит проверка
        цвета осталась без данных и молчит всегда.
        """
        assert COLOUR_COMPONENT_RANGES == {"h": (0, 360), "s": (0, 1000), "v": (100, 1000)}


# ---------------------------------------------------------------------------
#  Обязательность в модели и обязательные поля
# ---------------------------------------------------------------------------


class TestDeclarationInModel:
    """«Функция должна быть добавлена в описания моделей» — правило Sber."""

    def test_published_but_undeclared_feature_is_an_error(self) -> None:
        """Публикуем значение функции, которой нет в модели, — ошибка.

        Что сломается у пользователя, если тест упадёт: облаку некуда
        положить значение по необъявленному ключу, элемент управления в
        приложении не появится вовсе, а в журнале всё будет выглядеть
        успешным.
        """
        issues = validate_publish(
            entity_id="light.x",
            category="light",
            states=[_state("light_brightness", "INTEGER", integer_value="500")],
            declared_features=["online", "on_off"],
        )
        nots = [i for i in issues if i.type == "not_declared"]
        assert [i.key for i in nots] == ["light_brightness"]
        assert nots[0].severity == "error"

    def test_declared_feature_publishes_quietly(self) -> None:
        """Объявленная функция замечаний не вызывает.

        Что сломается у пользователя, если тест упадёт: каждая исправная
        публикация будет помечена ошибкой.
        """
        issues = validate_publish(
            entity_id="light.x",
            category="light",
            states=[_state("light_brightness", "INTEGER", integer_value="500")],
            declared_features=["online", "on_off", "light_brightness"],
        )
        assert [i for i in issues if i.type == "not_declared"] == []


class TestRequiredFields:
    """Поля, которые Sber помечает галочкой в структурах ``device`` и ``model``."""

    @pytest.mark.parametrize("field", ["id", "name", "default_name"])
    def test_missing_device_field_is_an_error(self, field: str) -> None:
        """Без обязательного поля устройства — ошибка.

        Что сломается у пользователя, если тест упадёт: Sber отбрасывает
        такое устройство целиком, и в приложении оно просто не
        появляется — без единого сообщения об ошибке.
        """
        issues = validate_device_descriptor(_device(**{field: None}))
        missing = [i for i in issues if i.type == "missing_required_field"]
        assert [i.details["field"] for i in missing] == [field]
        assert missing[0].severity == "error"

    def test_missing_model_field_is_an_error(self) -> None:
        """Без обязательного поля модели — ошибка.

        Что сломается у пользователя, если тест упадёт: Sber отбрасывает
        модель, а вместе с ней все устройства, которые на неё ссылаются.
        """
        descriptor = _device()
        del descriptor["model"]["manufacturer"]
        missing = [i for i in validate_device_descriptor(descriptor) if i.type == "missing_required_field"]
        assert [i.details for i in missing] == [{"scope": "model", "field": "manufacturer"}]

    def test_device_without_any_model_is_an_error(self) -> None:
        """Устройство без модели и без ``model_id`` — ошибка.

        Sber помечает обязательными оба поля сразу, оговариваясь, что
        ``model`` указывается, только если не задан ``model_id``.
        Выполнить обе галочки нельзя, поэтому проверяется «хотя бы
        одно».

        Что сломается у пользователя, если тест упадёт: устройство без
        модели не регистрируется ни при каких условиях.
        """
        descriptor = _device()
        del descriptor["model"]
        missing = [i for i in validate_device_descriptor(descriptor) if i.type == "missing_required_field"]
        assert any(i.details["field"] == "model" for i in missing)

    def test_model_id_instead_of_inline_model_is_accepted(self) -> None:
        """Ссылка на зарегистрированную модель — тоже законный вариант.

        Что сломается у пользователя, если тест упадёт: проверка начнёт
        требовать оба поля сразу, чего документация выполнить не
        позволяет.
        """
        descriptor = _device()
        del descriptor["model"]
        descriptor["model_id"] = "QWERTY123"
        missing = [i for i in validate_device_descriptor(descriptor) if i.type == "missing_required_field"]
        assert missing == []

    def test_partner_meta_over_the_limit_is_an_error(self) -> None:
        """``partner_meta`` длиннее лимита — ошибка.

        1024 символа — единственное числовое ограничение во всей
        документации C2C.

        Что сломается у пользователя, если тест упадёт: устройство с
        раздутой служебной нагрузкой перестанет приниматься облаком, а
        причина нигде не будет видна.
        """
        assert PARTNER_META_MAX_CHARS is not None
        descriptor = _device(partner_meta={"junk": "x" * (PARTNER_META_MAX_CHARS + 10)})
        over = [i for i in validate_device_descriptor(descriptor) if i.type == "partner_meta_too_long"]
        assert len(over) == 1
        assert over[0].severity == "error"
        assert over[0].details["max"] == PARTNER_META_MAX_CHARS

    def test_normal_partner_meta_is_quiet(self) -> None:
        """Обычная служебная нагрузка моста в лимит укладывается.

        Что сломается у пользователя, если тест упадёт: хаб моста, у
        которого в ``partner_meta`` лежит серийный номер HA, начнёт
        помечаться ошибкой на каждой публикации конфигурации.
        """
        descriptor = _device(partner_meta={"ha_serial_number": "ha-1a2b3c4d"})
        assert [i for i in validate_device_descriptor(descriptor) if i.type == "partner_meta_too_long"] == []


# ---------------------------------------------------------------------------
#  allowed_values
# ---------------------------------------------------------------------------


class TestAllowedValues:
    """«Диапазон можно только сократить, а шаг можно установить любой»."""

    def test_range_wider_than_documented_is_a_warning(self) -> None:
        """Диапазон шире документированного — предупреждение.

        Уровень именно «предупреждение», а не «ошибка»: правило Sber
        формулирует жёстко, но его же собственный эталон котла этот
        предел превышает, так что красить устройство в красный
        документация не позволяет.

        Что сломается у пользователя, если тест упадёт: увлажнитель,
        объявивший Сберу влажность до 100 % при документированных 90,
        рискует быть отвергнутым целиком, и понять причину будет
        невозможно.
        """
        descriptor = _device(
            device_id="humidifier.x",
            category="hvac_humidifier",
            features=["online", "on_off", "hvac_humidity_set"],
            allowed_values={
                "hvac_humidity_set": {
                    "type": "INTEGER",
                    "integer_values": {"min": "0", "max": "100", "step": "5"},
                }
            },
        )
        widened = [i for i in validate_device_descriptor(descriptor) if i.type == "allowed_values_widened"]
        assert [i.key for i in widened] == ["hvac_humidity_set"]
        assert widened[0].severity == "warning"
        assert widened[0].details["max"] == 90.0

    def test_narrowed_range_is_quiet(self) -> None:
        """Суженный диапазон — ровно то, ради чего структура существует.

        Что сломается у пользователя, если тест упадёт: правильно
        настроенное устройство получит предупреждение за то, что сделало
        всё по документации.
        """
        descriptor = _device(
            device_id="humidifier.x",
            category="hvac_humidifier",
            features=["online", "on_off", "hvac_humidity_set"],
            allowed_values={
                "hvac_humidity_set": {
                    "type": "INTEGER",
                    "integer_values": {"min": "40", "max": "70", "step": "5"},
                }
            },
        )
        assert [i for i in validate_device_descriptor(descriptor) if i.type == "allowed_values_widened"] == []

    def test_boiler_following_sbers_own_example_is_quiet(self) -> None:
        """Котёл до 80 °C молчит, хотя страница функции даёт только 50.

        Эталонная модель котла у самого Sber объявляет ``hvac_temp_set``
        как 25…80 — и именно из неё собран
        :class:`~.devices.hvac_boiler.HvacBoilerEntity`.

        Что сломается у пользователя, если тест упадёт: каждый бойлер на
        стенде получит предупреждение за то, что скопирован с образца
        Sber, — самый обидный вид ложного срабатывания.
        """
        descriptor = _device(
            device_id="water_heater.x",
            category="hvac_boiler",
            features=["online", "on_off", "hvac_temp_set"],
            allowed_values={
                "hvac_temp_set": {
                    "type": "INTEGER",
                    "integer_values": {"min": "25", "max": "80", "step": "5"},
                }
            },
        )
        assert [i for i in validate_device_descriptor(descriptor) if i.type == "allowed_values_widened"] == []

    def test_boiler_beyond_the_example_is_still_reported(self) -> None:
        """Выше эталона Sber поблажка не действует.

        Что сломается у пользователя, если тест упадёт: поблажка для
        котла превратится в дыру, через которую пройдёт любой диапазон.
        """
        descriptor = _device(
            device_id="water_heater.x",
            category="hvac_boiler",
            features=["online", "on_off", "hvac_temp_set"],
            allowed_values={
                "hvac_temp_set": {
                    "type": "INTEGER",
                    "integer_values": {"min": "25", "max": "95", "step": "5"},
                }
            },
        )
        widened = [i for i in validate_device_descriptor(descriptor) if i.type == "allowed_values_widened"]
        assert [i.key for i in widened] == ["hvac_temp_set"]

    def test_enum_value_outside_the_vocabulary_is_an_error(self) -> None:
        """Значение вне словаря Sber — ошибка, как и в состоянии.

        Что сломается у пользователя, если тест упадёт: приложение
        нарисует кнопку с придуманным значением, отправит его обратно
        как команду и получит отказ — ровно тот дефект, который вручную
        чинили в 1.49.0.
        """
        descriptor = _device(
            device_id="media_player.x",
            category="tv",
            features=["online", "on_off", "source"],
            allowed_values={"source": {"type": "ENUM", "enum_values": {"values": ["hdmi1", "HDMI 1"]}}},
        )
        unknown = [i for i in validate_device_descriptor(descriptor) if i.type == "unknown_enum_value"]
        assert [i.key for i in unknown] == ["source"]
        assert unknown[0].severity == "error"
        assert unknown[0].details["source"] == "allowed_values"

    def test_colour_entry_without_limits_is_only_info(self) -> None:
        """Пустая запись типа COLOUR — подсказка, а не ошибка.

        Такую запись мост шлёт для каждой цветной лампы; она ничего не
        ограничивает, и все лампы с ней работают.

        Что сломается у пользователя, если тест упадёт: каждая цветная
        лампа на стенде окрасится в жёлтый или красный, хотя ведёт себя
        правильно.
        """
        descriptor = _device(
            category="light",
            features=["online", "on_off", "light_colour"],
            allowed_values={"light_colour": {"type": "COLOUR"}},
        )
        found = [i for i in validate_device_descriptor(descriptor) if i.type.startswith("allowed_values")]
        assert [(i.type, i.severity) for i in found] == [("allowed_values_inert", "info")]

    def test_forbidden_type_carrying_limits_is_a_warning(self) -> None:
        """Запрещённый тип с ограничениями внутри — предупреждение.

        Что сломается у пользователя, если тест упадёт: объявленное
        ограничение не будет применено, а мы будем считать, что оно
        работает.
        """
        descriptor = _device(
            category="light",
            features=["online", "on_off", "light_colour"],
            allowed_values={"light_colour": {"type": "COLOUR", "integer_values": {"min": "0", "max": "1"}}},
        )
        found = [i for i in validate_device_descriptor(descriptor) if i.type == "allowed_values_shape"]
        assert [i.key for i in found] == ["light_colour"]
        assert found[0].severity == "warning"

    def test_block_that_does_not_match_the_type_is_a_warning(self) -> None:
        """Тип INTEGER с блоком ``enum_values`` — предупреждение.

        Что сломается у пользователя, если тест упадёт: Sber прочитает
        поле, названное типом, не найдёт его и просто проигнорирует все
        ограничения модели.
        """
        descriptor = _device(
            device_id="cover.x",
            category="curtain",
            features=["online", "open_percentage"],
            allowed_values={"open_percentage": {"type": "INTEGER", "enum_values": {"values": ["open"]}}},
        )
        found = [i for i in validate_device_descriptor(descriptor) if i.type == "allowed_values_shape"]
        assert [i.details["expected_block"] for i in found] == ["integer_values"]

    def test_full_vocabulary_restated_is_quiet(self) -> None:
        """Перечисление полного словаря ничего не сужает и молчит.

        ``devices/light.py`` объявляет для ``light_mode`` оба значения
        Sber — это не сужение, а копия документации.

        Что сломается у пользователя, если тест упадёт: каждая лампа
        получит предупреждение о «недопустимом сужении», которого не
        было.
        """
        descriptor = _device(
            category="light",
            features=["online", "on_off", "light_mode"],
            allowed_values={"light_mode": {"type": "ENUM", "enum_values": {"values": ["white", "colour"]}}},
        )
        assert [i for i in validate_device_descriptor(descriptor) if i.type.startswith("allowed_values")] == []

    def test_narrowing_a_feature_the_docs_do_not_mention_is_a_warning(self) -> None:
        """Сужение функции, о котором документация молчит, — предупреждение.

        Разрешение сокращать значения Sber пишет на 68 страницах функций
        из 96; запрета не пишет нигде. Поэтому замечание сформулировано
        как «документация не подтверждает», а не «Sber запрещает», и
        остаётся предупреждением.

        Что сломается у пользователя, если тест упадёт: либо исчезнет
        единственный сигнал о модели, чьё сужение ничем не подтверждено,
        либо (если замечание станет ошибкой или сменит формулировку на
        «запрещено») панель начнёт утверждать за Sber то, чего в
        документации нет.
        """
        descriptor = _device(
            category="light",
            features=["online", "on_off", "light_mode"],
            allowed_values={"light_mode": {"type": "ENUM", "enum_values": {"values": ["white"]}}},
        )
        found = [i for i in validate_device_descriptor(descriptor) if i.type == "allowed_values_shape"]
        assert [i.details["reason"] for i in found] == ["narrowing_not_documented"]
        assert [i.severity for i in found] == ["warning"]
        assert [i.message_key for i in found] == ["allowed_values_narrowing_unconfirmed"]

    def test_type_contradicting_the_function_is_a_warning(self) -> None:
        """Тип записи, не совпадающий с типом самой функции, — предупреждение.

        Что сломается у пользователя, если тест упадёт: Sber читает
        ограничения по типу функции, а не по тому, что написано в
        записи; несовпадение означает, что ограничения не применяются
        вовсе, а регулятор в приложении работает не в тех пределах.
        """
        descriptor = _device(
            category="light",
            features=["online", "on_off", "light_brightness"],
            allowed_values={"light_brightness": {"type": "ENUM", "enum_values": {"values": ["low"]}}},
        )
        found = [i for i in validate_device_descriptor(descriptor) if i.type == "allowed_values_shape"]
        assert [i.details["expected"] for i in found] == ["INTEGER"]

    def test_entry_that_is_not_an_object_is_skipped(self) -> None:
        """Мусор вместо записи ограничений не роняет валидатор.

        Что сломается у пользователя, если тест упадёт: испорченный
        пакет обрушит проверку, и вместе с ней пропадут все остальные
        замечания по этому устройству.
        """
        descriptor = _device(
            category="light",
            features=["online", "on_off"],
            allowed_values={"on_off": "какая-то строка"},
        )
        assert [i for i in validate_device_descriptor(descriptor) if i.type.startswith("allowed_values")] == []

    def test_state_scope_ignores_allowed_values(self) -> None:
        """В пакете состояния ``allowed_values`` не проверяются.

        Что сломается у пользователя, если тест упадёт: одно и то же
        замечание будет дублироваться на каждой публикации состояния,
        хотя относится оно к конфигурации.
        """
        issues = validate_publish(
            entity_id="light.x",
            category="light",
            states=[_state("on_off", "BOOL", bool_value=True)],
            declared_features=["online", "on_off"],
            allowed_values={"light_colour": {"type": "COLOUR"}},
        )
        assert [i for i in issues if i.type.startswith("allowed_values")] == []

    def test_permitted_types_come_from_the_documentation(self) -> None:
        """Список разрешённых типов ``allowed_values`` взят из снапшота.

        Что сломается у пользователя, если тест упадёт: проверка
        останется без данных и перестанет работать вовсе.
        """
        assert frozenset({"FLOAT", "INTEGER", "ENUM"}) == ALLOWED_VALUES_TYPES


class TestStateBearingCorpusIsUsable:
    """Служебная проверка: корпус эталонов не выродился в пустой список."""

    def test_snapshot_carries_state_examples(self) -> None:
        """В снапшоте есть примеры состояний, иначе корпус тишины пуст.

        Что сломается у пользователя, если тест упадёт: тесты выше
        начнут молча пропускаться, и проверка формы значения останется
        без единого эталона — мы узнаем о расхождении с Sber только от
        пользователя.
        """
        with_examples = [n for n, body in FUNCTIONS.items() if isinstance(body.get("state_example"), dict)]
        assert len(with_examples) >= 90
        assert set(with_examples) & set(STATE_BEARING_FEATURES)
