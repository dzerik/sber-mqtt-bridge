"""Соответствие наших устройств документации Sber C2C — по всем 29 категориям.

Проверяется то, что раньше не проверялось ни валидатором, ни точечными
тестами устройств: **форма** публикуемого значения, обязательные функции
в объявлении, попадание чисел в документированные диапазоны и законность
``allowed_values``.

Источник истины — только сгенерированные таблицы ``_generated/`` (они
собраны скрапером из https://developers.sber.ru/docs/ru/smarthome/c2c и
перегенерируются вместе со снапшотом). Ни одна константа документации
здесь не набирается руками: перепечатанная копия — второй источник
истины, который молча протухает.

Что здесь **не** проверяется, чтобы не дублировать соседей:

* словари ENUM-значений на выходе устройств — ``test_enum_vocabularies.py``;
* сам снапшот против документации — ``test_sber_spec_snapshot_coverage.py``;
* поведение ``schema_validator`` на синтетических payload'ах —
  ``test_schema_validator_gaps.py`` и ``test_reference_values.py``.

Здесь проверяются **наши реальные сущности**: то, что уедет в
``up/config`` и ``up/status``.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from custom_components.sber_mqtt_bridge._generated.category_features import CATEGORY_REFERENCE_FEATURES
from custom_components.sber_mqtt_bridge._generated.feature_types import FEATURE_TYPES
from custom_components.sber_mqtt_bridge._generated.narrowing import FEATURE_NARROWING
from custom_components.sber_mqtt_bridge._generated.obligatory_features import CATEGORY_OBLIGATORY_FEATURES
from custom_components.sber_mqtt_bridge._generated.reference_values import FEATURE_ENUM_VALUES
from custom_components.sber_mqtt_bridge._generated.usage_modes import (
    COMMAND_ONLY_FEATURES,
    EVENT_ONLY_FEATURES,
)
from custom_components.sber_mqtt_bridge._generated.value_envelope import (
    ALLOWED_VALUES_TYPES,
    COLOUR_COMPONENT_RANGES,
    VALUE_FIELD_BY_TYPE,
    VALUE_FIELD_JSON_TYPES,
    VALUE_TYPES,
)
from custom_components.sber_mqtt_bridge.devices.base_entity import BaseEntity
from custom_components.sber_mqtt_bridge.sber_entity_map import CATEGORY_DOMAIN_MAP
from custom_components.sber_mqtt_bridge.schema_validator import _documented_bounds

# ---------------------------------------------------------------------------
# Профили HA-состояний, которыми обстреливается каждая категория
# ---------------------------------------------------------------------------

_BASE_ATTRS: dict[str, Any] = {
    "supported_color_modes": ["hs", "color_temp"],
    "color_mode": "hs",
    "hs_color": (12.0, 55.0),
    "min_color_temp_kelvin": 2000,
    "max_color_temp_kelvin": 6535,
    "hvac_modes": ["off", "cool", "heat", "dry", "fan_only", "auto"],
    "fan_modes": ["auto", "low", "medium", "high"],
    "fan_mode": "auto",
    "swing_modes": ["off", "vertical"],
    "swing_mode": "off",
    "preset_modes": ["eco", "boost"],
    "preset_mode": "eco",
    "available_modes": ["normal", "boost"],
    "mode": "normal",
    "operation_list": ["eco", "performance"],
    "operation_mode": "eco",
    "source_list": ["hdmi1", "hdmi2"],
    "source": "hdmi1",
    "fan_speed_list": ["spot", "smart"],
    "fan_speed": "spot",
    "cleaning_type": "wet",
    "sensitivity": "high",
}
"""Списки возможностей, общие для всех профилей.

Заданы «на языке» Sber намеренно: словари значений — забота
``test_enum_vocabularies.py``, а здесь нужны сущности, у которых
объявлено как можно больше функций."""


_NUMERIC_ATTRS: tuple[str, ...] = (
    "brightness",
    "color_temp_kelvin",
    "current_position",
    "current_tilt_position",
    "temperature",
    "current_temperature",
    "target_temp_low",
    "target_temp_high",
    "min_temp",
    "max_temp",
    "humidity",
    "current_humidity",
    "min_humidity",
    "max_humidity",
    "battery_level",
    "percentage",
    "volume_level",
    "carbon_dioxide",
    "pm25",
    "voltage",
    "current",
    "power",
    "water_level",
)
"""Числовые атрибуты HA, которые устройства превращают в значения Sber."""


_PROFILES: dict[str, dict[str, Any]] = {
    "bare": {},
    "typical": {
        **_BASE_ATTRS,
        "brightness": 128,
        "color_temp_kelvin": 4000,
        "current_position": 55,
        "current_tilt_position": 30,
        "temperature": 22,
        "current_temperature": 21.5,
        "target_temp_low": 20,
        "target_temp_high": 24,
        "min_temp": 7,
        "max_temp": 35,
        "humidity": 50,
        "current_humidity": 45,
        "min_humidity": 30,
        "max_humidity": 80,
        "battery_level": 80,
        "percentage": 50,
        "volume_level": 0.5,
        "carbon_dioxide": 700,
        "pm25": 12,
        "voltage": 230,
        "current": 4500,
        "power": 1200,
        "water_level": 20.0,
    },
    "floor": {
        **_BASE_ATTRS,
        "brightness": 1,
        "color_temp_kelvin": 2000,
        "current_position": 0,
        "current_tilt_position": 0,
        "temperature": 7,
        "current_temperature": 0.0,
        "target_temp_low": 7,
        "target_temp_high": 8,
        "min_temp": 7,
        "max_temp": 35,
        "humidity": 30,
        "current_humidity": 0,
        "min_humidity": 30,
        "max_humidity": 80,
        "battery_level": 0,
        "percentage": 0,
        "volume_level": 0.0,
        "carbon_dioxide": 0,
        "pm25": 0,
        "voltage": 0,
        "current": 0,
        "power": 0,
        "water_level": 0.0,
    },
    "zero": {
        **_BASE_ATTRS,
        **dict.fromkeys(_NUMERIC_ATTRS, 0),
        "volume_level": 0.0,
        "water_level": 0.0,
        "current_temperature": 0.0,
    },
    "ceiling": {
        **_BASE_ATTRS,
        "brightness": 255,
        "color_temp_kelvin": 6535,
        "current_position": 100,
        "current_tilt_position": 100,
        "temperature": 35,
        "current_temperature": 45.0,
        "target_temp_low": 34,
        "target_temp_high": 35,
        "min_temp": 7,
        "max_temp": 35,
        "humidity": 80,
        "current_humidity": 100,
        "min_humidity": 30,
        "max_humidity": 80,
        "battery_level": 100,
        "percentage": 100,
        "volume_level": 1.0,
        "carbon_dioxide": 5000,
        "pm25": 500,
        "voltage": 250,
        "current": 16000,
        "power": 3500,
        "water_level": 50.0,
    },
    "blank": {**_BASE_ATTRS, **dict.fromkeys(_NUMERIC_ATTRS), "hs_color": None},
    "hot_water": {
        **_BASE_ATTRS,
        "temperature": 60,
        "current_temperature": 58.0,
        "min_temp": 30,
        "max_temp": 75,
        "humidity": 60,
        "current_humidity": 55,
        "min_humidity": 0,
        "max_humidity": 100,
        "water_level": 30.0,
    },
}
"""Пять профилей атрибутов HA плюс сущность вообще без атрибутов.

``floor`` / ``ceiling`` — законные края шкал самой HA (яркость 0…255,
позиция 0…100, громкость 0.0…1.0), ``blank`` — атрибуты присутствуют,
но равны ``None`` (обычное дело у только что заведённой интеграции),
``hot_water`` — бойлер: HA сообщает ``max_temp`` 75 °C и влажность
0…100 %, то есть шире, чем документирует Sber."""


_STATES: tuple[str, ...] = (
    "on",
    "off",
    "open",
    "closed",
    "opening",
    "closing",
    "heat",
    "cool",
    "cleaning",
    "docked",
    "playing",
    "idle",
    "locked",
    "unlocked",
    "unavailable",
    "unknown",
)
"""Состояния HA, которыми обстреливается каждая категория."""

_ONLINE_STATES: tuple[str, ...] = tuple(s for s in _STATES if s not in ("unavailable", "unknown"))
"""Те же состояния без двух, означающих «связи с устройством нет»."""


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------


def _probe(category: str, attrs: dict[str, Any], state: str) -> BaseEntity:
    """Собрать сущность указанной категории Sber и накормить её состоянием HA.

    Args:
        category: Ключ :data:`CATEGORY_DOMAIN_MAP`.
        attrs: Атрибуты HA-состояния.
        state: Значение ``state`` HA-сущности.

    Returns:
        Заполненная сущность, готовая к публикации.
    """
    spec = CATEGORY_DOMAIN_MAP[category]
    device_class = (spec.device_classes or ("",))[0]
    entity = spec.cls(
        {
            "entity_id": f"{spec.domains[0]}.probe",
            "name": "Проба",
            "original_device_class": device_class,
            "device_class": device_class,
        }
    )
    entity.fill_by_ha_state({"state": state, "attributes": dict(attrs)})
    return entity


def _wire_category(entity: BaseEntity) -> str:
    """Вернуть категорию Sber, под которой сущность реально уедет в облако.

    Ключ :data:`CATEGORY_DOMAIN_MAP` и категория на проводе — не одно и
    то же: ``sensor_humidity`` — наш внутренний псевдоним, Сберу такая
    категория неизвестна, датчик влажности публикуется как ``sensor_temp``.
    Сверять справочник надо именно с тем, что уедет.

    Args:
        entity: Собранная сущность.

    Returns:
        Имя категории Sber.
    """
    return str(entity.category)


def _states(entity: BaseEntity) -> list[dict[str, Any]]:
    """Вернуть список публикуемых состояний сущности.

    Args:
        entity: Заполненная сущность.

    Returns:
        Список элементов ``{"key": …, "value": …}`` из ``up/status``.
    """
    return list(entity.to_sber_current_state()[entity.entity_id]["states"])


def _published_numbers(value: dict[str, Any]) -> float | None:
    """Достать число из ``value``-словаря INTEGER/FLOAT.

    Args:
        value: Sber-словарь значения.

    Returns:
        Число либо ``None``, если значение не числовое.
    """
    for field in ("integer_value", "float_value"):
        if field in value:
            try:
                return float(value[field])
            except (TypeError, ValueError):
                return None
    return None


def _categories(xfail: dict[str, str] | None = None) -> list[Any]:
    """Собрать параметры «все категории Sber», пометив известные дефекты.

    Args:
        xfail: Категория → причина, по которой тест для неё обязан падать.
            Пометка строгая (``strict=True``): как только владелец починит
            устройство, тест станет XPASS и упадёт, напомнив убрать пометку.

    Returns:
        Список параметров для :func:`pytest.mark.parametrize`.
    """
    known = xfail or {}
    return [
        pytest.param(
            category,
            marks=[pytest.mark.xfail(strict=True, reason=known[category])] if category in known else [],
            id=category,
        )
        for category in sorted(CATEGORY_DOMAIN_MAP)
    ]


# ---------------------------------------------------------------------------
# 1. Форма значения: ровно `type` + одно поле полезной нагрузки
# ---------------------------------------------------------------------------


_ENVELOPE_DEBT: dict[str, str] = {}
"""Категории, чья форма значения расходится с документацией (долг владельца).

Пусто: последний долг — ``kitchen_water_level`` у чайника, уезжавший
INTEGER вместо документированного FLOAT, — закрыт переводом
``devices/kettle.py`` на ``make_state_for()``, который берёт тип из
``_generated/feature_types.py``."""


_HOSTILE_PROFILES: dict[str, dict[str, Any]] = {
    "negative": {
        **_BASE_ATTRS,
        **dict.fromkeys(_NUMERIC_ATTRS, -7),
        "volume_level": -0.5,
        "hs_color": (-7.0, -7.0),
    },
    "nan": {
        **_BASE_ATTRS,
        **dict.fromkeys(_NUMERIC_ATTRS, float("nan")),
        "hs_color": (float("nan"), float("nan")),
    },
}
"""Заведомо испорченные числа из HA — проверка живучести, а не соответствия.

Держатся отдельно от :data:`_PROFILES` намеренно: попадание такого
значения в документированный диапазон здесь **не** требуется. Батарея
−7 % — мусор со стороны интеграции, а не ошибка нашей арифметики, и
``schema_validator`` отмечает такое предупреждением, а не ошибкой.
Требуется другое: публикация не должна падать и не должна порождать
JSON, который брокер не примет."""


class TestValueEnvelope:
    """Обёртка ``value``: тип и единственное поле полезной нагрузки.

    Документация (``c2c/value``) описывает ``value`` как объект ровно из
    двух ключей: ``type`` и поле, названное типом. Сегодня эту форму не
    проверяет ничто — ``schema_validator`` сверяет только ``type``, — так
    что подменённое поле уходит в облако и молча отбрасывается.
    """

    @pytest.mark.parametrize("category", _categories(_ENVELOPE_DEBT))
    def test_value_carries_exactly_type_and_its_own_payload_key(self, category: str) -> None:
        """Каждое значение — это ``type`` плюс ровно одно поле по типу.

        Прод: устройство регистрируется и выглядит живым, но функция,
        отправленная не в своём поле (или с лишним ключом), для облака
        не существует — пользователь видит ползунок, который никогда не
        меняется, и никакой ошибки нигде.
        """
        offenders: list[str] = []
        for profile, attrs in _PROFILES.items():
            for state in _STATES:
                for item in _states(_probe(category, attrs, state)):
                    key, value = str(item["key"]), item["value"]
                    if not isinstance(value, dict):
                        offenders.append(f"{profile}/{state}/{key}: value не словарь ({value!r})")
                        continue
                    declared = value.get("type")
                    if declared not in VALUE_TYPES:
                        offenders.append(f"{profile}/{state}/{key}: тип {declared!r} вне списка Sber")
                        continue
                    expected = FEATURE_TYPES.get(key)
                    if expected is not None and declared != expected:
                        offenders.append(f"{profile}/{state}/{key}: отправлен {declared}, документирован {expected}")
                        continue
                    field = VALUE_FIELD_BY_TYPE[declared]
                    if set(value) != {"type", field}:
                        offenders.append(f"{profile}/{state}/{key}: ключи {sorted(value)}, ожидались type+{field}")
        assert offenders == [], f"{category}: {offenders}"

    @pytest.mark.parametrize("category", _categories())
    def test_payload_key_carries_the_json_type_sber_documents(self, category: str) -> None:
        """INTEGER — строкой, FLOAT — числом, BOOL — булевым, ENUM — строкой.

        Прод: ``{"integer_value": 42}`` числом вместо ``"42"`` проходит все
        наши сегодняшние проверки и молча отвергается Сбером — устройство
        есть в приложении, но его значения «залипают».
        """
        offenders: list[str] = []
        for profile, attrs in _PROFILES.items():
            for state in _STATES:
                for item in _states(_probe(category, attrs, state)):
                    key, value = str(item["key"]), item["value"]
                    field = VALUE_FIELD_BY_TYPE.get(value.get("type", ""))
                    if field is None or field not in value:
                        continue  # форму сторожит соседний тест
                    payload = value[field]
                    json_type = VALUE_FIELD_JSON_TYPES[field]
                    where = f"{profile}/{state}/{key}"
                    if json_type == "string" and not isinstance(payload, str):
                        offenders.append(f"{where}: {field}={payload!r} не строка")
                    elif json_type == "boolean" and not isinstance(payload, bool):
                        offenders.append(f"{where}: {field}={payload!r} не булево")
                    elif json_type == "number" and (isinstance(payload, bool) or not isinstance(payload, int | float)):
                        offenders.append(f"{where}: {field}={payload!r} не число")
                    if field == "integer_value" and isinstance(payload, str):
                        try:
                            int(payload)
                        except ValueError:
                            offenders.append(f"{where}: integer_value={payload!r} не целое, записанное строкой")
        assert offenders == [], f"{category}: {offenders}"

    @pytest.mark.parametrize("category", _categories())
    def test_colour_value_is_hsv_inside_documented_bounds(self, category: str) -> None:
        """``colour_value`` — объект ``h``/``s``/``v`` в границах Sber.

        Прод: ``v`` ниже 100 (у Sber нижняя граница именно 100, не 0) или
        ``h`` больше 360 — лампа меняет цвет в HA и не меняет в приложении
        Сбера. Границы взяты из документации, а не из нашего конвертера,
        поэтому тест ловит и «починку» конвертера в неверную сторону.
        """
        offenders: list[str] = []
        for profile, attrs in _PROFILES.items():
            for state in _STATES:
                for item in _states(_probe(category, attrs, state)):
                    value = item["value"]
                    if value.get("type") != "COLOUR":
                        continue
                    colour = value.get("colour_value")
                    where = f"{profile}/{state}/{item['key']!s}"
                    if not isinstance(colour, dict) or set(colour) != set(COLOUR_COMPONENT_RANGES):
                        offenders.append(f"{where}: colour_value={colour!r}, ожидались h/s/v")
                        continue
                    for component, (low, high) in COLOUR_COMPONENT_RANGES.items():
                        got = colour[component]
                        if isinstance(got, bool) or not isinstance(got, int) or not low <= got <= high:
                            offenders.append(f"{where}: {component}={got!r} вне {low}…{high}")
        assert offenders == [], f"{category}: {offenders}"

    @pytest.mark.parametrize("category", _categories())
    def test_publish_payload_is_plain_serializable_json(self, category: str) -> None:
        """Публикуемый пакет сериализуется в JSON без подпорок.

        ``allow_nan=False`` здесь принципиален: ``NaN`` и ``Infinity`` —
        расширение Python, а не JSON, и брокер такое сообщение отвергает.

        Прод: ``Decimal`` из интеграции или нечисловой ``float`` в значении
        роняет публикацию целиком — не «одно устройство показывает не то»,
        а весь ``up/status`` не уходит, и в приложении Сбера замирают все
        устройства сразу.
        """
        for profile, attrs in _PROFILES.items():
            for state in _STATES:
                payload = _probe(category, attrs, state).to_sber_current_state()
                try:
                    encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False)
                except (TypeError, ValueError) as err:  # pragma: no cover — путь дефекта
                    pytest.fail(f"{category} ({profile}/{state}): пакет не сериализуется — {err}")
                assert json.loads(encoded), f"{category} ({profile}/{state}): пустой пакет"

    @pytest.mark.parametrize("category", _categories())
    def test_broken_number_from_home_assistant_does_not_break_publishing(self, category: str) -> None:
        """Отрицательное число и ``NaN`` в атрибуте HA не роняют публикацию.

        ``float('nan')`` приезжает из HA буднично: шаблонный сенсор с
        делением на ноль, modbus-регистр с мусором, MQTT-полезная нагрузка
        ``"nan"``. Парсеры ``_safe_float_parser`` его пропускают (это
        честный ``float``), а ``int()`` дальше по пути падает.

        Прод: ``build_states_list_json`` ловит ``ValueError`` и молча
        выбрасывает сущность из пакета. Сбер ждёт в ответе все объявленные
        функции — устройство, которого в ответе нет, для него неисправно.
        Пользователь видит «климат пропал», в журнале — одна строка
        exception, связи с испорченным атрибутом никакой.
        """
        for profile, attrs in _HOSTILE_PROFILES.items():
            for state in _ONLINE_STATES:
                entity = _probe(category, attrs, state)
                try:
                    payload = entity.to_sber_current_state()
                except (ValueError, OverflowError, TypeError) as err:  # pragma: no cover — путь дефекта
                    pytest.fail(f"{category} ({profile}/{state}): публикация упала — {type(err).__name__}: {err}")
                try:
                    json.dumps(payload, ensure_ascii=False, allow_nan=False)
                except (TypeError, ValueError) as err:  # pragma: no cover — путь дефекта
                    pytest.fail(f"{category} ({profile}/{state}): в пакет уехало не-JSON число — {err}")


# ---------------------------------------------------------------------------
# 2. Обязательные функции категории
# ---------------------------------------------------------------------------


class TestObligatoryFeatures:
    """Обязательные (``✔︎``) функции категории — в объявлении и в публикации.

    Модель без обязательной функции Сбер отбрасывает целиком, а ответ на
    опрос состояния «должен содержать все заявленные функции устройства»
    (``c2c/webhook-post-query``).
    """

    @pytest.mark.parametrize("category", _categories())
    def test_model_declares_every_obligatory_feature(self, category: str) -> None:
        """Список функций модели содержит все обязательные для категории.

        Прод: устройства без обязательной функции просто не появляются в
        приложении Сбера — ни ошибки, ни записи в журнале, только пустое
        место там, где пользователь ждёт лампу.
        """
        offenders: list[str] = []
        for profile, attrs in _PROFILES.items():
            for state in _STATES:
                entity = _probe(category, attrs, state)
                obligatory = CATEGORY_OBLIGATORY_FEATURES.get(_wire_category(entity), frozenset())
                declared = {str(name) for name in entity.get_final_features_list()}
                missing = obligatory - declared
                if missing:
                    offenders.append(f"{profile}/{state}: нет {sorted(missing)}")
        assert offenders == [], f"{category}: {offenders}"

    @pytest.mark.parametrize("category", _categories())
    def test_online_publish_carries_every_obligatory_feature(self, category: str) -> None:
        """Живое устройство публикует все обязательные функции.

        Командные и событийные функции исключены: у них нет значения покоя
        (``pir`` умеет сказать только «движение»), Sber их в ответе не ждёт.

        Прод: обязательная функция без значения — это «устройство есть,
        но не отвечает»; Салют перестаёт им управлять голосом.
        """
        offenders: list[str] = []
        for profile, attrs in _PROFILES.items():
            for state in _ONLINE_STATES:
                entity = _probe(category, attrs, state)
                must_publish = CATEGORY_OBLIGATORY_FEATURES.get(_wire_category(entity), frozenset())
                must_publish -= COMMAND_ONLY_FEATURES | EVENT_ONLY_FEATURES
                published = {str(item["key"]) for item in _states(entity)}
                missing = must_publish - published
                if missing:
                    offenders.append(f"{profile}/{state}: не опубликованы {sorted(missing)}")
        assert offenders == [], f"{category}: {offenders}"

    @pytest.mark.parametrize("category", _categories())
    def test_offline_publish_still_carries_obligatory_features(self, category: str) -> None:
        """Потеря связи не отменяет обязательные функции.

        Измерение недоступного датчика публиковать нельзя (это выдуманный
        ноль), а вот обязательный по спеку ключ — обязано: без него Сбер
        выбрасывает устройство из конфигурации при первом же отвале, и оно
        не вернётся до переопубликации.
        """
        offenders: list[str] = []
        for profile, attrs in _PROFILES.items():
            for state in ("unavailable", "unknown"):
                entity = _probe(category, attrs, state)
                must_publish = CATEGORY_OBLIGATORY_FEATURES.get(_wire_category(entity), frozenset())
                must_publish -= COMMAND_ONLY_FEATURES | EVENT_ONLY_FEATURES
                published = {str(item["key"]) for item in _states(entity)}
                missing = must_publish - published
                if missing:
                    offenders.append(f"{profile}/{state}: не опубликованы {sorted(missing)}")
        assert offenders == [], f"{category}: {offenders}"


# ---------------------------------------------------------------------------
# 3. Объявленные функции принадлежат категории
# ---------------------------------------------------------------------------


class TestDeclaredFeaturesBelongToTheCategory:
    """Ни одна категория не имеет права объявить чужую функцию.

    Список функций категории — закрытый (таблица «Доступные функции
    устройства» на её странице). Функция вне списка для облака — мусор в
    модели.

    Проверяется **объявление классов устройств**
    (``BaseEntity.declared_features``), а не публикуемый список.
    Публикуемый проходит через ``_drop_features_foreign_to_category``,
    который фильтрует по тому же справочнику: сверять его выход со
    справочником — значит сверять фильтр с самим собой, и такой тест не
    покраснеет никогда, что бы классы ни объявили. Рантайм-фильтр —
    страховка, эти тесты — сторож, и они обязаны быть независимы.
    """

    @pytest.mark.parametrize("category", _categories())
    def test_declared_features_are_inside_the_reference_set(self, category: str) -> None:
        """Всё объявленное классом есть в справочнике категории.

        Прод: лишняя функция в модели — это либо молчаливый отказ облака
        принять устройство, либо элемент управления, который ничего не
        делает. И то и другое пользователь видит как «мост не работает».
        Фильтр в ``BaseEntity`` такую функцию снимет и до Сбера не
        пропустит — но починить её обязан класс, иначе следующая
        категория провалится туда же молча.
        """
        offenders: list[str] = []
        for profile, attrs in _PROFILES.items():
            for state in _STATES:
                entity = _probe(category, attrs, state)
                wire = _wire_category(entity)
                reference = CATEGORY_REFERENCE_FEATURES.get(wire)
                assert reference is not None, f"{category}: категория {wire!r} неизвестна документации Sber"
                declared = {str(name) for name in entity.declared_features}
                alien = declared - set(reference)
                if alien:
                    offenders.append(f"{profile}/{state}: чужие {sorted(alien)}")
        assert offenders == [], f"{category}: {offenders}"

    @pytest.mark.parametrize("category", _categories())
    def test_sensor_side_attributes_do_not_add_foreign_features(self, category: str) -> None:
        """Атрибуты вскрытия / отключённой сирены / чувствительности — тоже.

        Отдельный профиль: ``tamper``, ``alarm_mute`` и ``sensitivity``
        приезжают от Zigbee-датчиков сплошь и рядом, а Sber документирует
        ``tamper_alarm`` только для ``sensor_door``, ``alarm_mute`` — для
        ``sensor_smoke`` и ``sensor_gas``, ``sensor_sensitive`` — для
        четырёх категорий из двадцати девяти. Именно на этих трёх
        атрибутах чужие функции и заводились.

        Прод: датчик протечки, сообщивший в HA о вскрытии, уезжал в Сбер
        моделью с функцией, которой у его категории нет, — и облако
        вправе отбросить такую модель целиком, вместе с датчиком.
        """
        offenders: list[str] = []
        for profile, attrs in _PROFILES.items():
            probe_attrs = {**attrs, "tamper": True, "alarm_mute": False, "sensitivity": "high"}
            for state in _STATES:
                entity = _probe(category, probe_attrs, state)
                reference = set(CATEGORY_REFERENCE_FEATURES[_wire_category(entity)])
                alien = {str(name) for name in entity.declared_features} - reference
                if alien:
                    offenders.append(f"{profile}/{state}: чужие {sorted(alien)}")
        assert offenders == [], f"{category}: {offenders}"

    @pytest.mark.parametrize("category", _categories())
    def test_published_keys_are_inside_the_reference_set(self, category: str) -> None:
        """Всё публикуемое тоже есть в справочнике категории.

        Прод: ключ, которого у категории быть не может, облако игнорирует
        целиком — вместе с остальным содержимым пакета в худшем случае.
        """
        offenders: list[str] = []
        for profile, attrs in _PROFILES.items():
            for state in _STATES:
                entity = _probe(category, attrs, state)
                reference = set(CATEGORY_REFERENCE_FEATURES[_wire_category(entity)])
                published = {str(item["key"]) for item in _states(entity)}
                alien = published - reference
                if alien:
                    offenders.append(f"{profile}/{state}: чужие {sorted(alien)}")
        assert offenders == [], f"{category}: {offenders}"


# ---------------------------------------------------------------------------
# 4. Числа в документированных диапазонах
# ---------------------------------------------------------------------------


class TestPublishedNumbersStayInsideDocumentedRanges:
    """Опубликованное число обязано попадать в диапазон из документации.

    Границы Sber указывает на странице функции («Тип данных: INTEGER(5,
    50)»). Профили подаются законные для самой HA — 0…255 яркости, 0…100
    процентов, 0.0…1.0 громкости, — так что выход за диапазон означает
    ошибку пересчёта у нас, а не мусор на входе.
    """

    @pytest.mark.parametrize("category", _categories())
    def test_boundary_ha_input_produces_in_range_values(self, category: str) -> None:
        """Края шкал HA не выталкивают значения за границы Sber.

        Прод: яркость 0 обязана стать документированным минимумом 50, а не
        нулём; позиция 100 — сотней, а не 1000. Значение вне диапазона
        облако вправе обрезать или выбросить — пользователь видит лампу,
        которая «не гаснет до конца», или штору, застрявшую на 100 %.
        """
        offenders: list[str] = []
        for profile, attrs in _PROFILES.items():
            for state in _STATES:
                entity = _probe(category, attrs, state)
                wire = _wire_category(entity)
                for item in _states(entity):
                    key = str(item["key"])
                    bounds = _documented_bounds(wire, key)
                    if bounds is None:
                        continue
                    number = _published_numbers(item["value"])
                    if number is None:
                        continue
                    if not bounds[0] <= number <= bounds[1]:
                        offenders.append(f"{profile}/{state}/{key}={number:g} вне {bounds[0]:g}…{bounds[1]:g}")
        assert offenders == [], f"{category}: {sorted(set(offenders))}"


# ---------------------------------------------------------------------------
# 5. allowed_values умеет только сужать
# ---------------------------------------------------------------------------


class TestAllowedValuesNarrowOnly:
    """``allowed_values`` существует только чтобы **сузить** документированное.

    Страница ``c2c/allowed_values`` формулирует это дважды: структура
    применима только к FLOAT/INTEGER/ENUM, и «диапазон можно только
    сократить, а шаг можно установить любой». ``schema_validator`` те же
    правила проверяет на живых публикациях; здесь они проверяются на
    выходе наших классов устройств, по всем профилям и состояниям сразу,
    — то есть без ожидания, когда конкретное сочетание встретится на
    стенде.
    """

    @staticmethod
    def _declared(category: str) -> list[tuple[str, str, str, dict[str, Any]]]:
        """Собрать ``allowed_values`` категории по всем профилям.

        Args:
            category: Ключ :data:`CATEGORY_DOMAIN_MAP`.

        Returns:
            Четвёрки «где, категория на проводе, функция, дескриптор».
            Категория нужна проверке диапазонов: у пары
            «категория + функция» документация Sber бывает шире, чем у
            одной функции (см. ``_documented_bounds``).
        """
        found: list[tuple[str, str, str, dict[str, Any]]] = []
        for profile, attrs in _PROFILES.items():
            for state in _STATES:
                entity = _probe(category, attrs, state)
                wire = _wire_category(entity)
                found.extend(
                    (f"{profile}/{state}", wire, key, descriptor)
                    for key, descriptor in entity.create_allowed_values_list().items()
                )
        return found

    @pytest.mark.parametrize("category", _categories())
    def test_type_is_one_of_the_three_sber_allows(self, category: str) -> None:
        """Тип записи — только FLOAT, INTEGER или ENUM.

        Прод: тип вне этой тройки делает описание модели невалидным, а
        Сбер отклоняет модель целиком и молча — устройство не появляется,
        и в журнале ничего нет.
        """
        offenders = [
            f"{where}/{key}: тип {descriptor.get('type')!r}"
            for where, _wire, key, descriptor in self._declared(category)
            if descriptor.get("type") not in ALLOWED_VALUES_TYPES
        ]
        assert offenders == [], f"{category}: {sorted(set(offenders))}"

    @pytest.mark.parametrize("category", _categories())
    def test_descriptor_carries_the_box_matching_its_type(self, category: str) -> None:
        """У записи ровно один вложенный контейнер, и он соответствует типу.

        Прод: ``{"type": "INTEGER"}`` без ``integer_values`` ничего не
        переопределяет — пользователь двигает ползунок в приложении в
        диапазоне по умолчанию, а устройство его не принимает.
        """
        box_by_type = {"INTEGER": "integer_values", "FLOAT": "float_values", "ENUM": "enum_values"}
        offenders: list[str] = []
        for where, _wire, key, descriptor in self._declared(category):
            declared_type = descriptor.get("type")
            expected_box = box_by_type.get(str(declared_type))
            if expected_box is None:
                continue  # тип сторожит соседний тест
            if set(descriptor) != {"type", expected_box}:
                offenders.append(f"{where}/{key}: ключи {sorted(descriptor)}, ожидались type+{expected_box}")
        assert offenders == [], f"{category}: {sorted(set(offenders))}"

    @pytest.mark.parametrize("category", _categories())
    def test_integer_bounds_are_transmitted_as_strings(self, category: str) -> None:
        """``min``/``max``/``step`` у INTEGER — строки, как в примерах Sber.

        Прод: во всех 26 примерах моделей на страницах категорий границы
        записаны строками; числом они для облака выглядят как чужой тип, и
        переопределение диапазона просто не применяется.
        """
        offenders: list[str] = []
        for where, _wire, key, descriptor in self._declared(category):
            if descriptor.get("type") != "INTEGER":
                continue
            box = descriptor.get("integer_values", {})
            offenders.extend(
                f"{where}/{key}.{field}={box[field]!r} не строка"
                for field in ("min", "max", "step")
                if field in box and not isinstance(box[field], str)
            )
        assert offenders == [], f"{category}: {sorted(set(offenders))}"

    @pytest.mark.parametrize("category", _categories())
    def test_numeric_bounds_never_widen_the_documented_range(self, category: str) -> None:
        """Объявленные границы лежат внутри документированных.

        Прод: объявив Сберу потолок 75 °C при документированных 50, мы
        отдаём модель, которую облако вправе отвергнуть целиком — бойлер
        просто не появляется в приложении, и пользователю нечего чинить.
        """
        offenders: list[str] = []
        for where, wire, key, descriptor in self._declared(category):
            documented = _documented_bounds(wire, key)
            box = descriptor.get("integer_values") or descriptor.get("float_values")
            if documented is None or not isinstance(box, dict):
                continue
            try:
                low = float(box.get("min", documented[0]))
                high = float(box.get("max", documented[1]))
            except (TypeError, ValueError):
                continue  # нечисловые границы сторожит соседний тест
            if low < documented[0] or high > documented[1]:
                offenders.append(
                    f"{where}/{key}: объявлено {low:g}…{high:g}, документировано {documented[0]:g}…{documented[1]:g}"
                )
        assert offenders == [], f"{category}: {sorted(set(offenders))}"

    @pytest.mark.parametrize("category", _categories())
    def test_enum_subset_is_documented_and_narrowing_is_permitted(self, category: str) -> None:
        """ENUM-перечень — подмножество словаря, и сокращать его разрешено.

        Документация разрешает сокращать перечень не у каждой функции:
        у ``light_mode`` такой оговорки нет, поэтому объявлять для него
        можно только полный словарь (это ничего не переопределяет и
        безвредно), а урезанный — нельзя.

        Прод: значение вне словаря даёт кнопку, которую облако не умеет
        нажать; незаконно урезанный перечень отбирает у пользователя
        режим, который устройство поддерживает.
        """
        offenders: list[str] = []
        for where, _wire, key, descriptor in self._declared(category):
            if descriptor.get("type") != "ENUM":
                continue
            vocabulary = FEATURE_ENUM_VALUES.get(key)
            if vocabulary is None:
                continue  # словарь неизвестен — судить не о чем
            declared = set(descriptor.get("enum_values", {}).get("values", []))
            unknown = declared - vocabulary
            if unknown:
                offenders.append(f"{where}/{key}: значения вне словаря {sorted(unknown)}")
            if FEATURE_NARROWING.get(key) is None and declared != set(vocabulary):
                offenders.append(
                    f"{where}/{key}: перечень урезан до {sorted(declared)}, "
                    "хотя документация не разрешает сокращать эту функцию"
                )
        assert offenders == [], f"{category}: {sorted(set(offenders))}"
