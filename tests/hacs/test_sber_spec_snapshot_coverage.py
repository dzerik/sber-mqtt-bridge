"""Тесты полноты снапшота спецификации Sber и согласованности примеров.

Скрапер деградирует тихо: страница загрузилась, поле просто не нашлось,
покрытие упало с 96/96 до 40/96, а сгенерированные таблицы похудели — и
валидатор перестал проверять то, что проверял вчера. Отдельного сигнала
об этом нет, поэтому полнота зафиксирована здесь как контракт.

Второй пласт — сверка ФОРМЫ значения. Каждая страница функции содержит
канонический пакет состояния; из 96 таких пакетов и структурной страницы
``value`` складывается единственный нормативный ответ на вопрос «как
именно передаётся INTEGER, BOOL, COLOUR». Если эти проверки падают,
значит либо документация изменилась, либо разбор поехал — и в обоих
случаях облако начнёт молча отвергать устройства.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path

import pytest

from custom_components.sber_mqtt_bridge._generated import (
    ALLOWED_VALUES_TYPES,
    COLOUR_COMPONENT_RANGES,
    FEATURE_ENUM_LABELS,
    FEATURE_ENUM_VALUES,
    FEATURE_NARROWING,
    FEATURE_RANGES,
    FEATURE_TITLES_RU,
    FEATURE_TYPES,
    NARROWABLE_ENUM_FEATURES,
    NARROWABLE_RANGE_FEATURES,
    PARTNER_META_MAX_CHARS,
    SBER_ERROR_CODES,
    VALUE_FIELD_BY_TYPE,
    VALUE_FIELD_JSON_TYPES,
    VALUE_TYPES,
)

SPEC_FILE = Path(__file__).resolve().parents[2] / "tests" / "hacs" / "__snapshots__" / "sber_full_spec.json"

CODEGEN_PATH = Path(__file__).resolve().parents[2] / "tools" / "codegen.py"
"""Генератор ``_generated/`` — запускается из теста в режиме ``--check``."""

EXPECTED_CATEGORIES = 29
"""Категорий в документации Sber на момент фиксации снапшота."""

EXPECTED_FUNCTIONS = 96
"""Функций в каталоге Sber на момент фиксации снапшота."""


@pytest.fixture(scope="module")
def spec() -> dict:
    """Закоммиченный снапшот спецификации."""
    return json.loads(SPEC_FILE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def functions(spec) -> dict:
    """Каталог функций из снапшота."""
    return spec["functions"]


@pytest.fixture(scope="module")
def categories(spec) -> dict:
    """Категории устройств из снапшота."""
    return spec["categories"]


class TestFunctionFieldCoverage:
    """Каждое обязательное поле функции должно быть у всех 96 функций."""

    def test_catalog_size(self, functions):
        """Каталог не должен молча похудеть: пропавшая функция перестаёт проверяться."""
        assert len(functions) == EXPECTED_FUNCTIONS

    @pytest.mark.parametrize("field", ["title_ru", "doc_updated", "model_declaration", "state_example"])
    def test_field_present_for_every_function(self, functions, field):
        """Поле есть у всех функций — иначе разбор страницы сломался незаметно."""
        missing = sorted(name for name, entry in functions.items() if not entry.get(field))
        assert missing == [], f"{field} потерян у {len(missing)} функций: {missing[:10]}"

    def test_model_declaration_wording_is_uniform(self, functions):
        """Все 96 страниц говорят одно и то же; появление второго варианта — событие.

        Если у части функций значение станет другим, значит Сбер ввёл
        различие между «должна» и «может быть добавлена в модель», и наш
        набор объявляемых features надо пересматривать.
        """
        assert {entry["model_declaration"] for entry in functions.values()} == {"must_declare"}

    def test_narrowing_covers_the_documented_subset(self, functions):
        """Право сузить значения задокументировано не у всех — и это содержательно.

        Функция без такой фразы сужаться не может вообще: объявлять для неё
        ``allowed_values`` — заведомо неверная модель.
        """
        narrowable = {name for name, entry in functions.items() if entry.get("narrowing")}
        assert len(narrowable) == 68
        assert all(entry.get("narrowing") != "unrecognised" for entry in functions.values())

    def test_enum_vocabulary_carries_labels(self, functions):
        """У каждой ENUM-функции со словарём есть и русские подписи значений."""
        for name, entry in functions.items():
            if entry.get("enum_values"):
                assert sorted(entry.get("enum_descriptions", {})) == sorted(entry["enum_values"]), name


class TestStateExampleShape:
    """Форма значения — то, чего мы не проверяли вообще и что молча ломает публикацию."""

    def test_example_describes_its_own_function(self, functions):
        """Ключ примера совпадает с именем функции: иначе взят чужой блок <pre>."""
        for name, entry in functions.items():
            assert entry["state_example"]["key"] == name

    def test_example_type_matches_the_declared_type(self, functions):
        """Тип в примере совпадает с «Тип данных» из шапки страницы."""
        for name, entry in functions.items():
            assert entry["state_example"]["value"]["type"] == entry["type"], name

    def test_value_carries_exactly_one_payload_key(self, functions):
        """В value ровно два ключа: ``type`` и один носитель значения.

        Лишний ключ (или второй носитель) — это уже не тот пакет, который
        Сбер принимает.
        """
        for name, entry in functions.items():
            payload = [key for key in entry["state_example"]["value"] if key != "type"]
            assert len(payload) == 1, (name, payload)

    def test_payload_key_matches_the_type(self, functions):
        """INTEGER едет в ``integer_value``, ENUM — в ``enum_value`` и так далее."""
        for name, entry in functions.items():
            value = entry["state_example"]["value"]
            payload = next(key for key in value if key != "type")
            assert payload == VALUE_FIELD_BY_TYPE[value["type"]], name

    def test_integer_is_transmitted_as_a_string(self, functions):
        """INTEGER передаётся строкой — числом облако принимает и молча отбрасывает.

        Это ровно тот случай, который проходит все наши текущие проверки:
        ``{"type": "INTEGER", "integer_value": 42}`` формально корректен и
        не работает.
        """
        integers = [n for n, e in functions.items() if e["type"] == "INTEGER"]
        assert integers
        for name in integers:
            assert isinstance(functions[name]["state_example"]["value"]["integer_value"], str), name

    def test_bool_is_a_real_boolean(self, functions):
        """BOOL — настоящий ``true``/``false``, а не строка «true»."""
        for name, entry in functions.items():
            if entry["type"] == "BOOL":
                assert isinstance(entry["state_example"]["value"]["bool_value"], bool), name

    def test_enum_is_a_string(self, functions):
        """ENUM — строка; регистр значения важен (см. отдельный тест про source)."""
        for name, entry in functions.items():
            if entry["type"] == "ENUM":
                assert isinstance(entry["state_example"]["value"]["enum_value"], str), name

    def test_colour_is_an_hsv_object_within_bounds(self, functions):
        """COLOUR — объект {h, s, v}, и пример укладывается в документированные границы."""
        colours = [n for n, e in functions.items() if e["type"] == "COLOUR"]
        assert colours
        for name in colours:
            value = functions[name]["state_example"]["value"]["colour_value"]
            assert sorted(value) == ["h", "s", "v"], name
            for component, component_value in value.items():
                low, high = COLOUR_COMPONENT_RANGES[component]
                assert low <= component_value <= high, (name, component, component_value)

    def test_float_examples_contradict_the_value_page(self, functions):
        """Задокументированное противоречие: два FLOAT-примера показывают строку.

        Страница ``value`` объявляет ``float_value`` числом (``number``), и
        она авторитетнее примера. Тест фиксирует расхождение, чтобы никто не
        «починил» наш вывод FLOAT в строку по мотивам этих двух примеров, —
        и чтобы мы заметили, если Сбер исправит одну из сторон.
        """
        quoted = sorted(
            name
            for name, entry in functions.items()
            if entry["type"] == "FLOAT" and isinstance(entry["state_example"]["value"]["float_value"], str)
        )
        assert quoted == ["hcho_float", "tvoc_float"]
        assert VALUE_FIELD_JSON_TYPES["float_value"] == "number"

    def test_enum_example_values_belong_to_the_vocabulary(self, functions):
        """Значение примера входит в словарь функции — кроме известного бага доки.

        У ``source`` пример шлёт ``HDMI1``, а словарь на той же странице
        перечисляет ``hdmi1``. Расхождение внутри документации, поэтому оно
        зафиксировано поимённо, а не проигнорировано целиком.
        """
        mismatched = sorted(
            name
            for name, entry in functions.items()
            if entry.get("enum_values") and entry["state_example"]["value"]["enum_value"] not in entry["enum_values"]
        )
        assert mismatched == ["source"]

    def test_command_only_enums_have_no_vocabulary_but_do_have_an_example(self, functions):
        """У reject_call и unlock словаря нет — единственное значение живёт в примере.

        Без этого валидатор пропускает их молча: «словаря нет» читается как
        «проверять нечего», и опечатка в значении домофонной команды не
        ловится ничем.
        """
        without_vocabulary = sorted(
            name for name, entry in functions.items() if entry["type"] == "ENUM" and not entry.get("enum_values")
        )
        assert without_vocabulary == ["reject_call", "unlock"]
        assert functions["reject_call"]["state_example"]["value"]["enum_value"] == "reject"
        assert functions["unlock"]["state_example"]["value"]["enum_value"] == "unlock"


class TestCategoryFieldCoverage:
    """Новые поля категорий: подписи функций, эталон устройства, группы «хотя бы одна»."""

    def test_category_count(self, categories):
        """Категорий по-прежнему 29 — новая появляется только через дрейф-PR."""
        assert len(categories) == EXPECTED_CATEGORIES

    @pytest.mark.parametrize("field", ["doc_updated", "feature_descriptions", "device_example"])
    def test_field_present_for_every_category(self, categories, field):
        """Поле есть у всех категорий, включая hub с его единственной функцией."""
        missing = sorted(name for name, schema in categories.items() if not schema.get(field))
        assert missing == [], f"{field} потерян у категорий: {missing}"

    def test_every_listed_feature_has_a_russian_description(self, categories):
        """Подпись есть у каждой строки таблицы: панель не должна показывать слаг."""
        for name, schema in categories.items():
            missing = set(schema["all_features"]) - set(schema["feature_descriptions"])
            assert missing == set(), (name, sorted(missing))

    def test_device_example_carries_the_required_device_fields(self, categories):
        """Эталонный пакет устройства содержит обязательные поля структуры device."""
        for name, schema in categories.items():
            example = schema["device_example"]
            assert {"id", "name", "default_name"} <= set(example), name

    def test_sensor_categories_hang_off_a_parent(self, categories):
        """Сенсоры Сбер подвешивает под хаб через parent_id — это его собственный пример.

        У нас это поведение спрятано за настройкой ``hub_auto_parent``;
        тест фиксирует, что подход именно такой, каким его показывает Сбер.
        """
        assert "parent_id" in categories["sensor_temp"]["device_example"]
        assert "groups" in categories["light"]["device_example"]

    def test_any_of_groups_reference_real_features(self, categories):
        """Группы «хотя бы одна из» состоят только из функций той же категории."""
        for name, schema in categories.items():
            for group in schema["conditional_any_of"]:
                assert len(group) >= 2, (name, group)
                assert set(group) <= set(schema["all_features"]), (name, group)

    def test_open_method_rule_is_captured_for_all_four_cover_categories(self, categories):
        """Штора, ворота, жалюзи и клапан обязаны объявить способ открытия.

        Правило существует только в прозе; если оно перестанет извлекаться,
        устройство без ``open_set``/``open_percentage`` уедет в облако и
        просто не появится в приложении.
        """
        for name in ("curtain", "gate", "valve", "window_blind"):
            assert categories[name]["conditional_any_of"] == [["open_percentage", "open_set"]], name

    def test_air_and_temp_sensors_capture_their_measurement_group(self, categories):
        """Датчик обязан сообщать хотя бы одно измерение — список берётся из прозы."""
        assert set(categories["sensor_temp"]["conditional_any_of"][0]) == {"humidity", "temperature"}
        assert {"co2", "pm2_5", "hcho_float"} <= set(categories["sensor_air"]["conditional_any_of"][0])

    def test_scenario_button_rule_stays_visible_as_unresolved(self, categories):
        """Правило сценарной кнопки не перечисляет функции — и это должно быть видно.

        «Как минимум одна функция нажатия» машинно не раскрывается: в
        таблице у scenario_button нет ни одной галочки, поэтому проверка
        обязательности для неё не работает вовсе. Пока правило не перенесено
        в код руками, оно обязано лежать в снапшоте как нерешённое, а не
        исчезать.
        """
        unresolved = categories["scenario_button"]["conditional_unresolved"]
        assert len(unresolved) == 1
        assert "как минимум одна функция нажатия" in unresolved[0]
        assert categories["scenario_button"]["conditional_any_of"] == []


class TestStructuresAndProtocol:
    """Нормативные страницы структур: то, из чего собраны наши MQTT-пакеты."""

    def test_all_structure_pages_were_scraped(self, spec):
        """Все семь структурных страниц разобраны и содержат таблицу полей."""
        structures = spec["structures"]
        assert sorted(structures) == [
            "allowed_values",
            "common_error",
            "device",
            "error",
            "model",
            "state",
            "value",
        ]
        for name, structure in structures.items():
            assert structure["fields"], name
            assert structure["doc_updated"], name

    def test_value_types_are_the_closed_list(self, spec):
        """Список типов значения закрыт — тип вне него облако не понимает."""
        assert frozenset({"FLOAT", "INTEGER", "STRING", "BOOL", "ENUM", "COLOUR"}) == VALUE_TYPES
        assert set(VALUE_FIELD_BY_TYPE) == set(VALUE_TYPES)

    def test_allowed_values_may_not_declare_colour(self, spec):
        """allowed_values допустим только для FLOAT/INTEGER/ENUM.

        Мы отправляем ``allowed_values["light_colour"] = {"type": "COLOUR"}``;
        документация такого типа для этой структуры не разрешает, а значит
        модель лампы может быть отвергнута целиком.
        """
        assert frozenset({"FLOAT", "INTEGER", "ENUM"}) == ALLOWED_VALUES_TYPES
        assert "COLOUR" not in ALLOWED_VALUES_TYPES

    def test_partner_meta_limit_is_bound_to_the_docs(self):
        """1024 символа — единственный числовой лимит во всём разделе C2C.

        Раньше число жило в коде вручную; теперь его изменение наверху ломает
        тест, а не продакшен.
        """
        assert PARTNER_META_MAX_CHARS == 1024

    def test_colour_value_floor_is_one_hundred(self):
        """Нижняя граница v — 100, а не 0: на этом держится конвертер яркости цвета."""
        assert COLOUR_COMPONENT_RANGES == {"h": (0, 360), "s": (0, 1000), "v": (100, 1000)}

    def test_error_codes_are_known_with_wording(self):
        """Пять кодов ошибок с формулировками Сбера — основа внятной диагностики.

        401/403 означают «перевыпусти токен», 400 — «исправь модель»; сейчас
        пользователь видит один и тот же обрезанный текст в обоих случаях.
        """
        assert sorted(SBER_ERROR_CODES) == [400, 401, 403, 500, 503]
        assert SBER_ERROR_CODES[401] == "ошибка авторизации"


class TestGeneratedTablesAgreeWithTheSnapshot:
    """Сгенерированные таблицы должны быть согласованы между собой."""

    def test_narrowing_keys_are_known_features(self, functions):
        """В таблице сужения нет функций, которых нет в каталоге."""
        assert set(FEATURE_NARROWING) <= set(FEATURE_TYPES)
        assert set(FEATURE_NARROWING) <= set(functions)

    def test_range_narrowable_features_have_documented_bounds(self):
        """У числовой функции, которую можно сузить, должны быть известны границы.

        Без границ проверку «диапазон только сужается» делать не с чем, и
        бойлер с потолком 80 °C уедет в облако при документированных 50.
        """
        assert set(FEATURE_RANGES) >= NARROWABLE_RANGE_FEATURES

    def test_enum_narrowable_features_have_a_vocabulary(self):
        """У ENUM-функции, которую можно сузить, должен быть известен словарь."""
        assert set(FEATURE_ENUM_VALUES) >= NARROWABLE_ENUM_FEATURES

    def test_labels_cover_the_catalog(self, functions):
        """Русская подпись есть у каждой функции, а подписи значений — у каждого словаря."""
        assert set(FEATURE_TITLES_RU) == set(functions)
        assert set(FEATURE_ENUM_LABELS) == set(FEATURE_ENUM_VALUES)
        for name, labels in FEATURE_ENUM_LABELS.items():
            assert set(labels) == set(FEATURE_ENUM_VALUES[name]), name


class TestGeneratedModulesComeFromTheCommittedSnapshot:
    """``_generated/`` — функция снапшота, и это проверяется, а не подразумевается.

    Все проверки выше сверяют сгенерированные константы с числами,
    вписанными в сам тест. Это ловит изменение документации, но не
    ловит правку снапшота руками: подставленное в
    ``sber_full_spec.json`` значение, которое не перенесли в
    ``_generated``, до сих пор не роняло ни одного теста.
    """

    def test_codegen_check_reports_no_drift(self) -> None:
        """``python tools/codegen.py --check`` не находит расхождений.

        Ровно та же команда, которой пользуется еженедельный workflow
        ``sber-compliance.yml``: рендер из закоммиченного снапшота
        сравнивается с закоммиченными модулями. Строка «Spec generated
        at:» берётся из самого снапшота, поэтому сравнение
        детерминировано и игнорировать в нём нечего.

        Что сломается у пользователя, если тест упадёт: валидатор,
        pydantic-модели и панель будут судить об устройствах по
        таблицам, которых в источнике уже нет — например, разрешать
        значение, убранное Сбером из словаря, и молча терять устройство.
        """
        if shutil.which("ruff") is None:
            pytest.skip("codegen прогоняет вывод через ruff format — без ruff сравнение недостоверно")

        spec = importlib.util.spec_from_file_location("_codegen", CODEGEN_PATH)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)

        assert module.main(["--check"]) == 0, "см. вывод DRIFT выше: запустите python tools/codegen.py"
