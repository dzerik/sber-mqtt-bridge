"""Тесты извлечения новых полей спецификации Sber из страниц документации.

Скрапер ``tools/fetch_sber_schemas.py`` ходит в сеть и требует playwright,
поэтому здесь проверяются только чистые функции разбора — на сохранённых
кусках текста реальных страниц. Ломается такой разбор молча: страница
по-прежнему загружается, поле просто становится пустым, а вниз по течению
``_generated/`` теряет константу, и валидатор перестаёт проверять то, что
проверял вчера. Эти тесты и нужны, чтобы такая деградация падала здесь, а
не через неделю в проде.

Все фрагменты ниже скопированы дословно со страниц
developers.sber.ru/docs/ru/smarthome/c2c — включая неразрывные пробелы и
``\\ufeff``, из-за которых наивные регулярки перестают совпадать.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRAPER_PATH = REPO_ROOT / "tools" / "fetch_sber_schemas.py"


def _load_scraper_module():
    """Загрузить скрапер, подменив playwright заглушкой.

    Модуль импортирует ``playwright.sync_api`` на верхнем уровне и вызывает
    ``sys.exit(1)``, если пакета нет. В тестовом окружении браузер не нужен:
    проверяются только функции разбора.
    """
    if "playwright" not in sys.modules:
        stub = type(sys)("playwright")
        sync_stub = type(sys)("playwright.sync_api")
        sync_stub.TimeoutError = TimeoutError
        sync_stub.sync_playwright = lambda: None
        sys.modules["playwright"] = stub
        sys.modules["playwright.sync_api"] = sync_stub

    spec = importlib.util.spec_from_file_location("_scraper_extraction", SCRAPER_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def scraper():
    """Модуль скрапера, загруженный один раз на файл тестов."""
    return _load_scraper_module()


# --- фрагменты реальных страниц -------------------------------------------

HVAC_TEMP_SET_PAGE = (
    "hvac_temp_set\nhvac_temp_set (целевая температура)\nОбновлено 4 апреля 2025\n\n"
    "Тип данных: INTEGER(5, 50).\n\n"
    "Способ использования: хранит состояние устройства и может менять его.\n\n"
    "Назначение: управляет настройкой целевой температуры. Принимает значения "
    "от 5 до 50 °C с шагом в 1 °C. При описании модели устройства можно "
    "уменьшить диапазон принимаемых функцией значений либо изменить их шаг. "
    "Подробнее см. в разделе Допустимые значения функций.\n\n"
    "Устройства с этой функцией﻿\nhvac_ac — кондиционеры.\n"
    "hvac_boiler — котлы, контроллеры отопления.\n\n"
    "Описание функции в модели устройства﻿\n\n"
    # Неразрывный пробел здесь настоящий — именно на нём ломался первый вариант разбора.
    "Функция должна быть добавлена в\xa0описания моделей всех поддерживающих ее устройств.\n"
)

HVAC_TEMP_SET_PRE_BLOCKS = [
    '"features": [\n    "hvac_temp_set",\n    // ...\n]\n',
    '{\n    "states": [\n        {\n            "key": "hvac_temp_set",\n'
    '            "value": {\n                "type": "INTEGER",\n'
    '                "integer_value": "25"\n            }\n        }\n    ]\n}\n',
]

LIGHT_COLOUR_PRE_BLOCKS = [
    '{\n    "states": [\n        {\n            "key": "light_colour",\n'
    '            "value": {\n                "type": "COLOUR",\n'
    '                "colour_value": { "h": 360, "s": 1000, "v": 1000 }\n'
    "            }\n        }\n    ]\n}\n",
]

HVAC_HEATING_RATE_PAGE = (
    "Тип данных: ENUM.\n\n"
    "Способ использования: хранит состояние устройства и может менять его.\n\n"
    "Назначение: управляет скоростью нагрева:\n\n"
    "auto — автоматическая скорость нагрева.\n"
    "high — высокая скорость нагрева.\n"
    "low — низкая скорость нагрева.\n"
    "medium — средняя скорость нагрева.\n"
    "Число в диапазоне от 1 до 10, где 1 — минимальная скорость нагрева.\n\n"
    "При описании модели устройства перечень доступных режимов работы функции можно сократить.\n\n"
    "Устройства с этой функцией﻿\n"
    "hvac_boiler — котлы, контроллеры отопления.\n"
    "hvac_underfloor_heating — теплые полы.\n"
)

CURTAIN_PAGE = (
    "У устройства есть обязательные функции: online, open_state. Кроме того, "
    "обязательно должен быть описан способ открытия: либо open_set, либо "
    "open_percentage, либо они оба.\n\n"
    "При одновременном использовании open_set и open_percentage необходимо соблюдать правило:\n\n"
    "Если open_percentage не равен нулю, то open_set должен принять значение open.\n\n"
    "Функция\tОбязательная?\tОписание\n"
    # Тот же текст повторяется внутри таблицы — но уже без точки на конце.
    "Для устройства обязательно должен быть описан способ открытия: либо "
    "open_percentage, либо open_set, либо они оба\n\n\n"
    "open_rate\t\t\n\nСкорость открывания устройства\n\n\n"
    "open_state\t✔︎\t\n\nСтатус открывания устройства\n"
)

CURTAIN_FEATURES = {
    "online",
    "open_percentage",
    "open_rate",
    "open_set",
    "open_state",
    "signal_strength",
}

SCENARIO_BUTTON_PAGE = (
    "Для сценарной кнопки обязательно должна быть описана функция online, "
    "а также как минимум одна функция нажатия на кнопку.\n"
)

VALUE_PAGE_TABLE = [
    ["Поле", "Тип", "Обязательное?", "Описание"],
    [
        "type",
        "string",
        "✔︎",
        "Тип данных, в котором передается значение. Может принимать значение:\n\nFLOAT\nINTEGER\nSTRING\nBOOL\nENUM\nCOLOUR",
    ],
    ["float_value", "number", "", "Вещественное значение"],
    ["integer_value", "string", "", "Целочисленное значение long, записанное в виде строки"],
    ["bool_value", "boolean", "", "Логическое значение"],
    ["enum_value", "string", "", "Перечисляемое значение"],
    [
        "colour_value",
        "colour",
        "",
        'Цвет в формате HSV: {"h":int,"s":int,"v":int}.\n\nДопустимые значения:\n\nh: 0–360\ns: 0–1000\nv: 100–1000',
    ],
]

DEVICE_PAGE_TABLE = [
    ["Поле", "Тип", "Обязательное?", "Описание"],
    ["id", "string", "✔︎", "Идентификатор устройства в системе вендора"],
    ["parent_id", "string", "", "ID родительского устройства (например, хаба)"],
    [
        "partner_meta",
        "<object>",
        "",
        "Произвольная информация об устройстве. Максимально допустимое количество "
        "символов в JSON-представлении объекта partner_meta — 1024.",
    ],
]

ALLOWED_VALUES_PAGE_TABLE = [
    ["Поле", "Тип", "Обязательное?", "Описание"],
    ["type", "string", "✔︎", "Тип данных, которое принимает функция. Возможные значения:\n\nFLOAT\nINTEGER\nENUM"],
    ["integer_values", "object", "✔︎*", "Допустимые значения для функции, принимающей значение INTEGER."],
    ["enum_values", "object", "✔︎*", "Допустимые значения для функции, принимающей значение ENUM."],
]

ERROR_PAGE_TABLE = [
    ["Поле", "Тип", "Обязательное?", "Описание"],
    ["id", "string", "✔︎", "Идентификатор устройства"],
    [
        "code",
        "integer",
        "✔︎",
        "Код ошибки. Могут использоваться коды:\n\n400 — ошибка валидации запроса\n"
        "401 — ошибка авторизации\n403 — ошибка проверки токена\n"
        "500 — внутренняя ошибка системы\n503 — сервер недоступен",
    ],
]


class TestDocUpdated:
    """Дата «Обновлено …» — самый чувствительный сигнал дрейфа документации."""

    def test_reads_the_date_as_printed(self, scraper):
        """Дата берётся дословно: без неё правки в прозе Сбера остаются незамеченными."""
        assert scraper.extract_doc_updated("Обновлено 4 апреля 2025") == "4 апреля 2025"

    def test_accepts_zero_padded_day(self, scraper):
        """День с ведущим нулём тоже дата — иначе intercom и reject_call «теряют» её."""
        assert scraper.extract_doc_updated("Обновлено 06 ноября 2025") == "06 ноября 2025"

    def test_missing_node_is_none(self, scraper):
        """Отсутствие узла даёт None, а не пустую строку: неизвестно ≠ «дата пустая»."""
        assert scraper.extract_doc_updated("") is None
        assert scraper.extract_doc_updated(None) is None


class TestTitleRu:
    """Русская подпись функции — то, чем панель может заменить протокольный слаг."""

    def test_extracts_label_from_function_heading(self, scraper):
        """light_colour (цвет) → «цвет»: иначе в мастере остаются английские слаги."""
        assert scraper.extract_title_ru("light_colour (цвет)") == "цвет"

    def test_category_heading_has_no_label(self, scraper):
        """Заголовок страницы категории — голый слаг, подписи там нет и выдумывать её нельзя."""
        assert scraper.extract_title_ru("light") is None


class TestModelDeclaration:
    """Норматив «функция должна быть объявлена в модели» — 96 страниц из 96."""

    def test_recognises_the_canonical_sentence(self, scraper):
        """Фраза распознаётся вместе с неразрывным пробелом внутри неё.

        Именно на \\xa0 разбор и падал: страница загружалась, поле молча
        оставалось пустым, покрытие рушилось с 96/96 до 0/96.
        """
        assert scraper.classify_model_declaration(HVAC_TEMP_SET_PAGE) == scraper.MODEL_DECLARATION_REQUIRED

    def test_absent_sentence_is_none(self, scraper):
        """None означает «формулировка изменилась», а не «объявлять не обязательно»."""
        assert scraper.classify_model_declaration("Тип данных: BOOL.") is None


class TestNarrowing:
    """Право сузить допустимые значения — основа проверки allowed_values."""

    def test_numeric_range_and_step(self, scraper):
        """«уменьшить диапазон … либо изменить их шаг» → range_and_step."""
        assert scraper.extract_narrowing(HVAC_TEMP_SET_PAGE) == scraper.NARROWING_RANGE_AND_STEP

    def test_enum_subset(self, scraper):
        """«перечень … можно сократить» → enum_subset (можно публиковать подмножество)."""
        assert scraper.extract_narrowing(HVAC_HEATING_RATE_PAGE) == scraper.NARROWING_ENUM_SUBSET

    def test_range_without_step(self, scraper):
        """Формулировка без слова «шаг» не даёт права менять шаг."""
        text = "При описании модели устройства диапазон принимаемых функцией значений можно уменьшить."
        assert scraper.extract_narrowing(text) == scraper.NARROWING_RANGE_ONLY

    def test_absent_rule_yields_none(self, scraper):
        """Нет фразы — None, то есть «документация молчит», а не «нельзя».

        Разрешение сокращать значения Sber пишет на 68 страницах из 96;
        запрета не пишет нигде, поэтому None читается потребителем как
        «не подтверждено», а не как прямой запрет.
        """
        assert scraper.extract_narrowing("Тип данных: BOOL.\n\nНазначение: управляет состоянием.") is None

    def test_unknown_wording_is_flagged(self, scraper):
        """Новая формулировка помечается, а не сводится к «документация молчит».

        Молчаливый None потерял бы единственный факт, который страница
        всё-таки сообщает: сужать эту функцию можно. Потребитель после
        этого не отличит «разрешено, но формулировка новая» от «в
        документации ничего нет».
        """
        text = "При описании модели устройства действуют особые правила."
        assert scraper.extract_narrowing(text) == scraper.NARROWING_UNRECOGNISED


class TestStateExample:
    """Эталонный пакет состояния — единственный источник ФОРМЫ значения."""

    def test_integer_value_is_a_string(self, scraper):
        """INTEGER передаётся строкой; отправка числом молча отвергается облаком."""
        example = scraper.extract_state_example(HVAC_TEMP_SET_PRE_BLOCKS)
        assert example == {"key": "hvac_temp_set", "value": {"type": "INTEGER", "integer_value": "25"}}

    def test_colour_value_is_an_hsv_object(self, scraper):
        """COLOUR — объект {h, s, v}, а не строка и не список."""
        example = scraper.extract_state_example(LIGHT_COLOUR_PRE_BLOCKS)
        assert example["value"]["colour_value"] == {"h": 360, "s": 1000, "v": 1000}

    def test_ignores_the_features_block(self, scraper):
        """Блок "features" не является объектом JSON и не должен приниматься за пример."""
        assert scraper.extract_state_example([HVAC_TEMP_SET_PRE_BLOCKS[0]]) is None

    def test_tolerates_comments_and_trailing_commas(self, scraper):
        """Примеры Сбера содержат ``// ...`` и висячие запятые — это не повод их терять."""
        block = '{\n "states": [\n  {\n   "key": "on_off",\n   "value": {\n    "type": "BOOL",\n    "bool_value": false,\n   },\n   // ...\n  },\n ],\n}\n'
        assert scraper.extract_state_example([block]) == {
            "key": "on_off",
            "value": {"type": "BOOL", "bool_value": False},
        }

    def test_schema_pseudo_json_is_rejected(self, scraper):
        """Схема с псевдотипами (``"type": string``) — не пример и парситься не должна."""
        block = (
            '{\n    "states": [\n        {\n            "key": string,\n            "value": {}\n        }\n    ]\n}'
        )
        assert scraper.extract_state_example([block]) is None

    def test_strict_parser_stays_strict(self, scraper):
        """Мягкий парсер отдельный: строгий по-прежнему не принимает комментарии.

        От строгого зависит выбор эталонной модели категории — послабление в
        нём поменяло бы уже зафиксированные в снапшоте данные.
        """
        assert scraper._parse_json_block('{"a": 1, // c\n "b": 2}') is None


class TestEnumDescriptions:
    """Русские подписи значений ENUM — материал для панели вместо голых слагов."""

    def test_collects_value_glosses(self, scraper):
        """Каждое значение получает формулировку Сбера, без точки на конце."""
        descriptions = scraper.extract_enum_descriptions(HVAC_HEATING_RATE_PAGE)
        assert descriptions["auto"] == "автоматическая скорость нагрева"
        assert descriptions["medium"] == "средняя скорость нагрева"

    def test_stops_before_the_category_list(self, scraper):
        """Список категорий выглядит так же и не должен попадать в словарь значений.

        Без этой отсечки в подписях значений оказались бы «hvac_boiler» и
        «hvac_underfloor_heating», и панель показала бы их как режимы работы.
        """
        descriptions = scraper.extract_enum_descriptions(HVAC_HEATING_RATE_PAGE)
        assert "hvac_boiler" not in descriptions
        assert "hvac_underfloor_heating" not in descriptions

    def test_matches_the_extracted_vocabulary(self, scraper):
        """Ключи подписей совпадают со списком значений: расхождение — баг разбора."""
        values = scraper.extract_enum_values(HVAC_HEATING_RATE_PAGE)
        assert sorted(scraper.extract_enum_descriptions(HVAC_HEATING_RATE_PAGE)) == sorted(values)


class TestAnyOfGroups:
    """Правило «хотя бы одна из функций» живёт только в прозе страницы категории."""

    def test_reads_the_open_method_rule(self, scraper):
        """Штора обязана объявить open_set или open_percentage — иначе Сбер её не примет."""
        groups, unresolved = scraper.extract_any_of_groups(CURTAIN_PAGE, CURTAIN_FEATURES)
        assert groups == [["open_percentage", "open_set"]]
        assert unresolved == []

    def test_ignores_the_same_sentence_repeated_inside_the_table(self, scraper):
        """Тот же текст повторён в таблице без точки — оттуда группы брать нельзя.

        Разбор, которому разрешено пересекать перевод строки, утаскивает
        половину таблицы и выдумывает группу из соседних строк вроде
        ``open_rate`` и ``open_state``.
        """
        groups, _ = scraper.extract_any_of_groups(CURTAIN_PAGE, CURTAIN_FEATURES)
        assert all("open_rate" not in group for group in groups)
        assert all("open_state" not in group for group in groups)

    def test_unenumerable_rule_is_reported_not_dropped(self, scraper):
        """Сценарная кнопка: «как минимум одна функция нажатия» — правило без списка.

        Если такую фразу молча выбросить, единственное обязательное правило
        сценарной кнопки исчезает из спецификации и не проверяется никем.
        """
        groups, unresolved = scraper.extract_any_of_groups(SCENARIO_BUTTON_PAGE, {"online", "button_1_event"})
        assert groups == []
        assert len(unresolved) == 1
        assert "как минимум одна" in unresolved[0]

    def test_table_cells_on_one_rendered_line_are_not_prose(self, scraper):
        """Ячейки таблицы, склеившиеся в одну строку, не должны давать группу.

        ``innerText`` разделяет ячейки табуляцией, а сколько их поместится в
        одну отрисованную строку — зависит от ширины окна. Именно так у
        ``curtain`` однажды родилась группа из ``open_rate`` и
        ``open_right_*``: правило «объявите способ открытия» подменилось
        случайным набором соседних строк таблицы.
        """
        rendered_row = (
            "Для устройства обязательно должен быть описан способ открытия: либо "
            "open_percentage, либо open_set, либо они оба\topen_rate\t\tСкорость "
            "открывания устройства."
        )
        groups, unresolved = scraper.extract_any_of_groups(rendered_row, CURTAIN_FEATURES)
        assert groups == []
        assert unresolved == []

    def test_never_invents_a_feature_name(self, scraper):
        """Токены сверяются с таблицей категории: выдуманных функций быть не может."""
        groups, _ = scraper.extract_any_of_groups(CURTAIN_PAGE, {"open_set"})
        assert groups == []


class TestFieldTable:
    """Таблицы структур (value / model / device / …) разбираются по заголовкам."""

    def test_maps_columns_by_header_not_position(self, scraper):
        """Колонки ищутся по названию — порядок столбцов не является контрактом."""
        fields = scraper.parse_field_table(VALUE_PAGE_TABLE)
        assert fields["integer_value"]["type"] == "string"
        assert fields["type"]["obligatory"] is True
        assert fields["integer_value"]["obligatory"] is False

    def test_separates_strict_and_conditional_markers(self, scraper):
        """✔︎ и ✔︎* — разные требования; смешать их значит требовать лишнего."""
        fields = scraper.parse_field_table(ALLOWED_VALUES_PAGE_TABLE)
        assert fields["type"]["obligatory"] is True
        assert fields["enum_values"]["conditional"] is True
        assert fields["enum_values"]["obligatory"] is False

    def test_unknown_header_yields_nothing(self, scraper):
        """Перевёрстанная таблица даёт пустоту, а не мусор с перепутанными колонками."""
        assert scraper.parse_field_table([["A", "B"], ["x", "y"]]) == {}


class TestProtocolFacts:
    """Нормативные константы протокола: цитата вместо устного предания."""

    @pytest.fixture
    def structures(self, scraper):
        """Структуры, собранные из сохранённых таблиц четырёх страниц."""
        return {
            "value": {"fields": scraper.parse_field_table(VALUE_PAGE_TABLE)},
            "device": {"fields": scraper.parse_field_table(DEVICE_PAGE_TABLE)},
            "allowed_values": {"fields": scraper.parse_field_table(ALLOWED_VALUES_PAGE_TABLE)},
            "error": {"fields": scraper.parse_field_table(ERROR_PAGE_TABLE)},
        }

    def test_value_types_are_read_from_the_page(self, scraper, structures):
        """Закрытый список типов значения — основа проверки формы value."""
        facts = scraper.derive_protocol_facts(structures)
        assert facts["value_types"] == ["FLOAT", "INTEGER", "STRING", "BOOL", "ENUM", "COLOUR"]

    def test_integer_value_is_declared_as_string(self, scraper, structures):
        """``integer_value`` объявлен строкой — на этом держится вся сериализация INTEGER."""
        facts = scraper.derive_protocol_facts(structures)
        assert facts["value_field_types"]["integer_value"] == "string"
        assert facts["value_field_types"]["float_value"] == "number"

    def test_colour_bounds_include_the_v_floor(self, scraper, structures):
        """v начинается со 100, а не с 0 — ошибка здесь ломает цвет на живых лампах."""
        facts = scraper.derive_protocol_facts(structures)
        assert facts["colour_ranges"] == {"h": [0, 360], "s": [0, 1000], "v": [100, 1000]}

    def test_allowed_values_types_exclude_colour(self, scraper, structures):
        """allowed_values разрешён только для FLOAT/INTEGER/ENUM; COLOUR в списке нет."""
        facts = scraper.derive_protocol_facts(structures)
        assert facts["allowed_values_types"] == ["FLOAT", "INTEGER", "ENUM"]
        assert "COLOUR" not in facts["allowed_values_types"]

    def test_partner_meta_limit(self, scraper, structures):
        """Единственный числовой лимит во всём разделе — 1024 символа."""
        assert scraper.derive_protocol_facts(structures)["partner_meta_max_chars"] == 1024

    def test_error_codes_with_wording(self, scraper, structures):
        """Коды ошибок с формулировками: 401/403 лечатся не тем же, чем 400."""
        codes = scraper.derive_protocol_facts(structures)["error_codes"]
        assert codes["401"] == "ошибка авторизации"
        assert sorted(codes) == ["400", "401", "403", "500", "503"]

    def test_missing_page_leaves_constants_unknown(self, scraper):
        """Недоступная страница даёт None/пустоту — но никогда «ограничений нет»."""
        facts = scraper.derive_protocol_facts({})
        assert facts["partner_meta_max_chars"] is None
        assert facts["colour_ranges"] == {}
        assert facts["value_types"] == []


class TestPreviousStructuresFallback:
    """Сбой одной структурной страницы не должен стирать константы из кодогенерации."""

    def test_failed_page_is_carried_over(self, scraper, capsys):
        """Значения переносятся из закоммиченного снапшота, а не исчезают.

        Иначе минутная недоступность портала превращается в «лимита
        partner_meta не существует» в сгенерированном модуле.
        """
        structures: dict[str, dict] = {}
        previous = {"structures": {"device": {"fields": {"id": {"obligatory": True}}}}}
        scraper.merge_previous_structures(structures, previous, ["device"])
        assert structures["device"]["fields"]["id"]["obligatory"] is True
        assert "reusing committed extraction" in capsys.readouterr().out

    def test_nothing_to_carry_over_stays_empty(self, scraper):
        """Если предыдущего снапшота нет, поле остаётся пустым и видно в отчёте."""
        structures: dict[str, dict] = {}
        scraper.merge_previous_structures(structures, {}, ["device"])
        assert structures == {}
