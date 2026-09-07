"""Тесты выгрузки и кодогенерации поля «Способ использования» Сбера.

Что здесь защищается.

На странице каждой функции Сбер первой же строкой пишет, ЧЕМ функция
является: хранит ли она состояние устройства и можно ли его менять.
Формулировок ровно четыре, и они делят каталог на три практически
важные группы:

* ``command_only`` — «не хранит состояние устройства, может менять его».
  Такая функция обязана быть ОБЪЯВЛЕНА в модели устройства, но никогда
  не появляется в публикации состояния: состояния у неё нет. Пример —
  ``open_set`` у штор и ворот.
* ``event_only`` — «уведомляет о состоянии устройства». Единственная
  такая функция ``pir``: приходит в момент обнаружения движения и молчит
  всё остальное время.
* ``state_read_write`` / ``state_read_only`` — функции, которые реально
  несут состояние и только их законно искать в публикации.

Если выгрузка этого поля сломается (например, скрапер перестанет
нормализовать неразрывный пробел ``\\xa0``, которым Сбер типографит часть
страниц), классификация молча «поедет»: командные функции попадут в
несущие состояние, валидатор начнёт требовать значение, которого не
бывает, и пользователь получит поток ложных жалоб на исправные шторы и
датчики движения — ровно как в issue #61 с ``pir``.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from custom_components.sber_mqtt_bridge._generated import (
    COMMAND_ONLY_FEATURES,
    EVENT_ONLY_FEATURES,
    FEATURE_USAGE_MODES,
    STATE_BEARING_FEATURES,
)
from custom_components.sber_mqtt_bridge.schema_validator import (
    EVENT_ONLY_FEATURES as HANDWRITTEN_EVENT_ONLY,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRAPER_PATH = REPO_ROOT / "tools" / "fetch_sber_schemas.py"
FULL_SPEC_FILE = REPO_ROOT / "tests" / "hacs" / "__snapshots__" / "sber_full_spec.json"

DOCUMENTED_COMMAND_ONLY = frozenset(
    {
        "channel",
        "custom_key",
        "direction",
        "hvac_direction_set",
        "mute",
        "number",
        "open_left_set",
        "open_right_set",
        "open_set",
        "reject_call",
        "unlock",
        "volume",
    }
)
"""Функции с формулировкой «не хранит состояние устройства, может менять его».

Сверено со страницами developers.sber.ru на 2026-09-07: 12 функций из 96.
Список зафиксирован здесь литералом намеренно — если скрапер начнёт
классифицировать иначе, тест покажет это как расхождение с документацией,
а не подстроится под новую выгрузку.
"""

DOCUMENTED_EVENT_ONLY = frozenset({"pir"})
"""Единственная функция с формулировкой «уведомляет о состоянии устройства»."""

DOCUMENTED_USAGE_COUNTS = {
    "state_read_write": 47,
    "state_read_only": 36,
    "command_only": 12,
    "event_only": 1,
}
"""Сколько функций приходится на каждую формулировку (96 всего)."""


def _load_scraper_module():
    """Загрузить ``tools/fetch_sber_schemas.py`` без установленного playwright.

    Модуль импортирует ``playwright.sync_api`` на верхнем уровне и при
    его отсутствии делает ``sys.exit(1)``, поэтому подменяем заглушкой.
    """
    if "playwright" not in sys.modules:
        stub = type(sys)("playwright")
        sync_stub = type(sys)("playwright.sync_api")
        sync_stub.TimeoutError = TimeoutError
        sync_stub.sync_playwright = lambda: None
        sys.modules["playwright"] = stub
        sys.modules["playwright.sync_api"] = sync_stub

    spec = importlib.util.spec_from_file_location("_scraper_usage", SCRAPER_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def scraper():
    """Модуль скрапера, загружаемый один раз на файл."""
    return _load_scraper_module()


@pytest.fixture(scope="module")
def snapshot() -> dict:
    """Актуальный снапшот ``sber_full_spec.json``."""
    return json.loads(FULL_SPEC_FILE.read_text(encoding="utf-8"))


class TestUsageExtraction:
    """Скрапер обязан доставать строку «Способ использования» со страницы."""

    def test_usage_line_is_extracted(self, scraper):
        """Без этого поля снапшот вообще не знает о делении функций на группы."""
        article = (
            "Функция open_set\n"
            "Способ использования: не хранит состояние устройства, может менять его.\n"
            "\nНазначение: управляет открыванием устройства:\n"
        )
        usage, mode = scraper.extract_usage(article)
        assert usage == "не хранит состояние устройства, может менять его."
        assert mode == scraper.USAGE_COMMAND_ONLY

    def test_nbsp_wording_is_still_classified(self, scraper):
        """Сбер типографит часть страниц неразрывным пробелом.

        ``alarm_mute`` написан как «менять его не\\xa0может», а
        ``battery_low_power`` — с обычным пробелом. Без нормализации одна и
        та же формулировка распадается на две, часть функций уезжает в
        «неизвестно» и выпадает из ``STATE_BEARING_FEATURES``.
        """
        article = "Способ использования: хранит состояние устройства, менять его не\xa0может.\n"
        usage, mode = scraper.extract_usage(article)
        assert "\xa0" not in usage, "неразрывный пробел должен быть нормализован"
        assert mode == scraper.USAGE_STATE_READ_ONLY

    def test_usage_without_trailing_period_is_classified(self, scraper):
        """Одна страница обходится без точки в конце — это та же формулировка."""
        article = "Способ использования: хранит состояние устройства, менять его не может\n"
        _, mode = scraper.extract_usage(article)
        assert mode == scraper.USAGE_STATE_READ_ONLY

    @pytest.mark.parametrize(
        ("phrase", "expected_mode"),
        [
            ("хранит состояние устройства и может менять его.", "state_read_write"),
            ("хранит состояние устройства, менять его не может.", "state_read_only"),
            ("не хранит состояние устройства, может менять его.", "command_only"),
            ("уведомляет о состоянии устройства, менять его не может.", "event_only"),
            ("ХРАНИТ СОСТОЯНИЕ УСТРОЙСТВА И МОЖЕТ МЕНЯТЬ ЕГО.", "state_read_write"),
        ],
    )
    def test_all_four_wordings_are_recognised(self, scraper, phrase, expected_mode):
        """Все четыре формулировки Сбера покрывают 96 функций из 96."""
        assert scraper.classify_usage(phrase) == expected_mode

    def test_reworded_usage_is_unknown_not_guessed(self, scraper):
        """Переписанная Сбером формулировка — это дрейф, а не повод угадывать.

        Угадывание здесь опаснее пустого значения: неверно записав
        командную функцию как несущую состояние, мы заставим валидатор
        требовать значение, которого не существует.
        """
        assert scraper.classify_usage("иногда хранит состояние, а иногда нет") is None

    def test_page_without_usage_line_yields_none(self, scraper):
        """Страница без строки «Способ использования» не должна ронять выгрузку."""
        assert scraper.extract_usage("Функция foo\nТип данных: BOOL\n") == (None, None)

    def test_usage_coverage_report_flags_unclassified(self, scraper):
        """Нераспознанная формулировка должна попадать в отчёт, а не теряться."""
        assert scraper.report_usage_coverage({"a": {"usage_mode": "command_only"}}) is True
        assert scraper.report_usage_coverage({"a": {"usage": "нечто новое", "usage_mode": None}}) is False


class TestSnapshotUsageCoverage:
    """Снапшот обязан нести поле usage для каждой из 96 функций."""

    def test_every_function_has_usage_and_mode(self, snapshot):
        """Пустое поле у функции = она выпадает из классификации целиком."""
        missing = sorted(name for name, spec in snapshot["functions"].items() if not spec.get("usage_mode"))
        assert not missing, f"функции без usage_mode: {missing}"

    def test_usage_mode_distribution_matches_docs(self, snapshot):
        """Раскладка по формулировкам сверена со страницами Сбера вручную."""
        counts: dict[str, int] = {}
        for spec in snapshot["functions"].values():
            counts[spec["usage_mode"]] = counts.get(spec["usage_mode"], 0) + 1
        assert counts == DOCUMENTED_USAGE_COUNTS

    def test_snapshot_command_only_matches_documented_set(self, snapshot):
        """Поимённая сверка командных функций с документацией."""
        scraped = frozenset(
            name for name, spec in snapshot["functions"].items() if spec["usage_mode"] == "command_only"
        )
        assert scraped == DOCUMENTED_COMMAND_ONLY

    def test_usage_text_carries_no_nbsp(self, snapshot):
        """В снапшоте не должно остаться неразрывных пробелов и BOM.

        Иначе одна и та же формулировка хранится в двух видах и любое
        сравнение по тексту (в т.ч. поиск дрейфа) начинает врать.
        """
        dirty = sorted(
            name for name, spec in snapshot["functions"].items() if "\xa0" in spec["usage"] or "﻿" in spec["usage"]
        )
        assert not dirty, f"ненормализованный usage у: {dirty}"


class TestGeneratedUsageModes:
    """Сгенерированный ``_generated/usage_modes.py`` — то, что читает рантайм."""

    def test_command_only_features_match_documented_set(self):
        """``open_set`` и компания не имеют состояния и не могут быть в публикации."""
        assert COMMAND_ONLY_FEATURES == DOCUMENTED_COMMAND_ONLY

    def test_event_only_features_match_documented_set(self):
        """Событийная функция ровно одна — ``pir``."""
        assert EVENT_ONLY_FEATURES == DOCUMENTED_EVENT_ONLY

    def test_generated_event_only_agrees_with_handwritten(self):
        """Сгенерированный набор обязан совпадать с рукописным в schema_validator.

        Рукописный выведен косвенно (ENUM ровно с одним значением),
        сгенерированный — прямо из формулировки Сбера. Расхождение
        означало бы, что один из двух источников устарел, и валидатор
        начал бы либо требовать событие, которого не бывает, либо
        перестал бы проверять функцию, которая состояние всё-таки несёт.
        """
        assert EVENT_ONLY_FEATURES == HANDWRITTEN_EVENT_ONLY

    def test_open_set_is_command_only_not_state_bearing(self):
        """Шторы обязаны объявлять ``open_set``, но публиковать его нечем."""
        assert "open_set" in COMMAND_ONLY_FEATURES
        assert "open_set" not in STATE_BEARING_FEATURES

    def test_open_state_is_state_bearing(self):
        """А вот ``open_state`` состояние несёт — иначе шторы «пропадут»."""
        assert "open_state" in STATE_BEARING_FEATURES
        assert "open_state" not in COMMAND_ONLY_FEATURES

    def test_three_sets_partition_the_catalog(self):
        """Три набора обязаны не пересекаться и покрывать весь каталог."""
        assert not COMMAND_ONLY_FEATURES & EVENT_ONLY_FEATURES
        assert not COMMAND_ONLY_FEATURES & STATE_BEARING_FEATURES
        assert not EVENT_ONLY_FEATURES & STATE_BEARING_FEATURES
        union = COMMAND_ONLY_FEATURES | EVENT_ONLY_FEATURES | STATE_BEARING_FEATURES
        assert union == frozenset(FEATURE_USAGE_MODES)

    def test_usage_modes_cover_all_96_functions(self):
        """Неполнота каталога тихо отключает проверки — ловим её явно."""
        assert len(FEATURE_USAGE_MODES) == 96


class TestIndexRecovery:
    """Выпадение функции из индекса ``/functions`` не должно резать каталог."""

    def test_function_dropped_from_index_is_planned_for_direct_fetch(self, scraper):
        """Если индекс перестал показывать страницу, её тянут по прямому слагу.

        Без этого функция просто исчезает из снапшота, вместе с ней —
        из ``FEATURE_ENUM_VALUES`` и ``FEATURE_RANGES``, и валидатор
        молча перестаёт проверять её значения.
        """
        recovery = scraper.plan_recovery_names(["on-off", "open_state"], {"on_off", "open_state", "pir"})
        assert recovery == ["pir"]

    def test_kebab_slug_covers_underscore_name(self, scraper):
        """``light-colour-temp`` — это страница функции ``light_colour_temp``."""
        assert scraper.plan_recovery_names(["light-colour-temp"], {"light_colour_temp"}) == []

    def test_slug_candidates_try_both_spellings(self, scraper):
        """Сбер отдаёт ``/open_set``, но ``/light-colour-temp`` — нужны оба варианта."""
        assert scraper.slug_candidates("open_set") == ["open_set", "open-set"]
        assert scraper.slug_candidates("pir") == ["pir"]

    def test_full_index_needs_no_recovery(self, scraper):
        """Сегодня индекс отдаёт все 96 страниц — восстановление не срабатывает."""
        assert scraper.plan_recovery_names(["a", "b"], {"a", "b"}) == []
