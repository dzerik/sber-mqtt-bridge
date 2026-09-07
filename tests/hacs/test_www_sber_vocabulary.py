"""Панель говорит словами документации Sber, а не только идентификаторами.

Снапшот документации несёт два словаря, которых пользователь до сих пор
не видел:

* ``_generated/feature_labels.py`` — человеческое имя каждой из 96
  функций («температура цвета» для ``light_colour_temp``) и каждого
  ENUM-значения. Это ровно те слова, которыми та же функция подписана в
  приложении Салют, то есть единственный способ связать строку в нашей
  панели с кнопкой на телефоне;
* ``_generated/protocol_limits.SBER_ERROR_CODES`` — что означают пять
  кодов ошибок, которые облако присылает в ``down/errors``. Разница
  между 403 («ошибка проверки токена» — не тот пароль) и 503 («сервер
  недоступен» — подожди) видна только через них.

Файл держит три границы:

1. **Транспорт** — команда ``sber_mqtt_bridge/feature_labels`` отдаёт
   сгенерированные таблицы дословно и не требует моста;
2. **Панель** — ``www/feature-labels.js`` действительно исполняется
   (проверки гоняют настоящий модуль через node), а компоненты
   действительно его зовут;
3. **Локализация** — блок ``config_panel.sber_error`` совпадает с
   документацией по набору кодов, а русский текст повторяет
   формулировку Sber дословно.

Соседний ``test_translations_consistency.py`` эти ключи не покрывает:
он ищет литеральные ``t(this.hass, "…")``, а код ошибки подставляется
в ключ на лету.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from _ws_dispatch import dispatch
from test_translations_consistency import english_fallback, panel_strings, requires_node

from custom_components.sber_mqtt_bridge._generated.feature_labels import (
    FEATURE_ENUM_LABELS,
    FEATURE_TITLES_RU,
)
from custom_components.sber_mqtt_bridge._generated.protocol_limits import SBER_ERROR_CODES
from custom_components.sber_mqtt_bridge.message_logger import MessageLogger, last_error_moment, parse_sber_error
from custom_components.sber_mqtt_bridge.websocket_api.reference import LABEL_LANGUAGE, ws_feature_labels
from custom_components.sber_mqtt_bridge.websocket_api.status import ws_get_status

COMPONENT_ROOT = Path(__file__).resolve().parents[2] / "custom_components" / "sber_mqtt_bridge"
"""Корень интеграции."""

WWW = COMPONENT_ROOT / "www"
"""Корень панели (сборки нет — файлы отдаются браузеру как есть)."""

ERROR_SECTION = "sber_error"
"""Блок ``config_panel``, в котором живут расшифровки кодов ошибок."""

LOCALES = ("strings.json", "translations/en.json", "translations/ru.json")
"""Файлы строк, обязанные содержать блок целиком."""

_STATUS_MODULE = "custom_components.sber_mqtt_bridge.websocket_api.status"
"""Модуль, в котором патчатся ``get_bridge`` / ``get_config_entry``."""

NODE = shutil.which("node")
"""Путь к node — им исполняются настоящие модули панели."""


def _error_catalogue(locale: str) -> dict[str, str]:
    """Вернуть блок ``sber_error`` файла строк.

    Args:
        locale: Путь относительно корня интеграции.

    Returns:
        Карта «код (или ``unknown``) → текст».
    """
    prefix = f"{ERROR_SECTION}."
    return {key.removeprefix(prefix): value for key, value in panel_strings(locale).items() if key.startswith(prefix)}


def _run_node(tmp_path: Path, driver: str, *, modules: tuple[str, ...]) -> Any:
    """Исполнить драйвер рядом с копиями модулей панели.

    Args:
        tmp_path: Временный каталог.
        driver: Исходник ``driver.mjs``.
        modules: Имена модулей ``www`` (без пути), которые он импортирует.

    Returns:
        JSON, напечатанный драйвером в stdout.
    """
    for name in modules:
        shutil.copy(WWW / name, tmp_path / name)
    (tmp_path / "driver.mjs").write_text(driver, encoding="utf-8")
    result = subprocess.run(  # noqa: S603 - фиксированный argv, без shell
        [str(NODE), "driver.mjs"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    return json.loads(result.stdout)


_JS_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
"""Блочный комментарий JS — включая JSDoc."""

_JS_LINE_COMMENT = re.compile(r"^\s*//.*$", re.MULTILINE)
"""Строка, целиком занятая комментарием ``//``."""


def _without_comments(source: str) -> str:
    """Убрать из исходника JS комментарии.

    Документация модуля вправе цитировать заголовок как пример
    («температура цвета» в docstring ``feature-labels.js``); запрет
    касается кода, который этот заголовок печатает.

    Args:
        source: Исходник модуля панели.

    Returns:
        Тот же исходник без комментариев.
    """
    return _JS_LINE_COMMENT.sub("", _JS_BLOCK_COMMENT.sub("", source))


def _labels_driver(body: str) -> str:
    """Собрать драйвер, который загрузил словарь и что-то из него спросил.

    Args:
        body: JS-выражение, печатающее результат.

    Returns:
        Исходник модуля ``driver.mjs``.
    """
    return (
        "import { ensureFeatureLabels, enumValueLabel, featureLabel, featureTitle, resetFeatureLabels } "
        'from "./feature-labels.js";\n' + body
    )


# ---------------------------------------------------------------------------
# 1. Транспорт: одна команда, одна выгрузка на страницу
# ---------------------------------------------------------------------------


class TestVocabularyCommand:
    """``sber_mqtt_bridge/feature_labels`` — источник имён для панели."""

    @pytest.mark.asyncio
    async def test_command_returns_the_generated_tables_verbatim(self) -> None:
        """Отдаются ровно сгенерированные таблицы, без пересборки по дороге.

        Что сломается у пользователя, если тест упадёт: панель подпишет
        функцию словами, которых нет в документации Sber, — а значит и в
        приложении Салют; сверить одно с другим станет невозможно.
        """
        hass = MagicMock()
        connection = MagicMock()

        await dispatch(ws_feature_labels, hass, connection, {"id": 1})

        payload = connection.send_result.call_args[0][1]
        assert payload["titles"] == FEATURE_TITLES_RU
        assert payload["enum_labels"] == FEATURE_ENUM_LABELS
        assert payload["language"] == LABEL_LANGUAGE

    @pytest.mark.asyncio
    async def test_command_works_without_a_bridge(self) -> None:
        """Словарь отдаётся и когда моста нет.

        Что сломается у пользователя, если тест упадёт: вкладка проверки
        схемы читается именно тогда, когда связь с облаком не работает.
        Если словарь придёт только вместе с живым мостом, замечания в
        этот момент останутся подписаны идентификаторами.
        """
        hass = MagicMock()
        hass.config_entries.async_loaded_entries = MagicMock(return_value=[])
        connection = MagicMock()

        await dispatch(ws_feature_labels, hass, connection, {"id": 1})

        assert not connection.send_error.called
        assert connection.send_result.call_args[0][1]["titles"]

    def test_titles_are_not_copied_into_the_panel_sources(self) -> None:
        """Ни один русский заголовок не вшит в JS.

        Что сломается у пользователя, если тест упадёт: копия словаря в
        панели молча разойдётся с документацией при следующей
        перегенерации снапшота, и подпись в панели перестанет совпадать
        с подписью в приложении.
        """
        titles = {title for title in FEATURE_TITLES_RU.values() if title.strip()}
        assert len(titles) > 50, "предусловие: словарь заголовков не пуст"
        offenders = {
            f"{path.name}: {title}": title
            for path in sorted(WWW.rglob("*.js"))
            if "vendor" not in path.parts
            for source in [_without_comments(path.read_text(encoding="utf-8"))]
            for title in titles
            if title in source
        }

        assert offenders == {}


# ---------------------------------------------------------------------------
# 2. Панель: настоящий модуль, исполненный node
# ---------------------------------------------------------------------------


class TestPanelLabelModule:
    """``www/feature-labels.js`` — поведение, а не пересказ."""

    @requires_node
    def test_documented_title_replaces_the_identifier_in_russian(self, tmp_path: Path) -> None:
        """В русской локали ведёт документированное имя, идентификатор — в подсказке.

        Что сломается у пользователя, если тест упадёт: русский
        пользователь снова увидит ``light_colour_temp`` там, где Sber
        сам пишет «температура цвета».
        """
        driver = _labels_driver(
            'const labels = { language: "ru", titles: { light_colour_temp: "температура цвета" },'
            " enum_labels: {} };\n"
            'const hass = { language: "ru", callWS: async () => labels };\n'
            "await ensureFeatureLabels(hass);\n"
            'console.log(JSON.stringify(featureLabel(hass, "light_colour_temp")));\n'
        )

        assert _run_node(tmp_path, driver, modules=("feature-labels.js",)) == {
            "text": "температура цвета",
            "hint": "light_colour_temp",
        }

    @requires_node
    def test_other_languages_keep_the_identifier_and_hint_the_title(self, tmp_path: Path) -> None:
        """В остальных локалях ведёт идентификатор, документированное имя — в подсказке.

        Документация Sber существует только по-русски, и выдумывать
        английские названия функций нельзя: они разойдутся и с
        документацией, и с приложением.

        Что сломается у пользователя, если тест упадёт: англоязычная
        панель начнёт показывать русский текст как основную подпись —
        или потеряет подсказку, которая связывает строку с приложением
        Салют на телефоне.
        """
        driver = _labels_driver(
            'const labels = { language: "ru", titles: { light_colour_temp: "температура цвета" },'
            " enum_labels: {} };\n"
            'const hass = { language: "en", callWS: async () => labels };\n'
            "await ensureFeatureLabels(hass);\n"
            'console.log(JSON.stringify(featureLabel(hass, "light_colour_temp")));\n'
        )

        assert _run_node(tmp_path, driver, modules=("feature-labels.js",)) == {
            "text": "light_colour_temp",
            "hint": "температура цвета",
        }

    @requires_node
    def test_regional_language_tag_still_counts_as_the_label_language(self, tmp_path: Path) -> None:
        """``ru-RU`` — это тот же русский.

        Что сломается у пользователя, если тест упадёт: у части русских
        установок (HA хранит и региональные теги) панель молча
        переключится на идентификаторы.
        """
        driver = _labels_driver(
            'const labels = { language: "ru", titles: { humidity: "текущая влажность" }, enum_labels: {} };\n'
            'const hass = { language: "ru-RU", callWS: async () => labels };\n'
            "await ensureFeatureLabels(hass);\n"
            'console.log(JSON.stringify(featureLabel(hass, "humidity").text));\n'
        )

        assert _run_node(tmp_path, driver, modules=("feature-labels.js",)) == "текущая влажность"

    @requires_node
    def test_unknown_feature_falls_back_to_its_identifier(self, tmp_path: Path) -> None:
        """Функция без документированного имени показывается как есть.

        Что сломается у пользователя, если тест упадёт: функция, которую
        Sber добавил после последней перегенерации снапшота, исчезнет из
        списка или нарисуется пустым местом.
        """
        driver = _labels_driver(
            'const labels = { language: "ru", titles: {}, enum_labels: {} };\n'
            'const hass = { language: "ru", callWS: async () => labels };\n'
            "await ensureFeatureLabels(hass);\n"
            'console.log(JSON.stringify([featureLabel(hass, "brand_new"), featureTitle("brand_new")]));\n'
        )

        assert _run_node(tmp_path, driver, modules=("feature-labels.js",)) == [
            {"text": "brand_new", "hint": ""},
            "",
        ]

    @requires_node
    def test_a_failed_fetch_degrades_to_identifiers(self, tmp_path: Path) -> None:
        """Отказ команды не роняет отрисовку.

        Что сломается у пользователя, если тест упадёт: старый бэкенд
        (или отозванный доступ) выбросит исключение прямо в
        ``connectedCallback``, и компонент не отрисуется вообще — вместо
        таблицы устройств пустое место.
        """
        driver = _labels_driver(
            'const hass = { language: "ru", callWS: async () => { throw new Error("unknown command"); } };\n'
            "await ensureFeatureLabels(hass);\n"
            'console.log(JSON.stringify(featureLabel(hass, "humidity")));\n'
        )

        assert _run_node(tmp_path, driver, modules=("feature-labels.js",)) == {"text": "humidity", "hint": ""}

    @requires_node
    def test_a_failed_fetch_is_tried_again_by_the_next_component(self, tmp_path: Path) -> None:
        """Отказ не защёлкивается: следующий компонент запрашивает словарь заново.

        Панель — SPA: уход на другую страницу и возврат не создают
        страницу заново, так что «выключено до F5» означает «выключено на
        весь сеанс». А оба способа получить отказ временные: панель
        открыта, пока запись конфигурации ещё грузится (команда не
        зарегистрирована), или связь моргнула.

        Что сломается у пользователя, если тест упадёт: одна неудачная
        попытка в первую секунду после открытия панели навсегда оставит
        пользователя с идентификаторами вместо человеческих имён — и
        никакая перезагрузка вкладки настроек этого не исправит.
        """
        driver = _labels_driver(
            "let calls = 0;\n"
            "let broken = true;\n"
            'const hass = { language: "ru", callWS: async () => { calls += 1;\n'
            '  if (broken) { broken = false; throw new Error("unknown command"); }\n'
            '  return { language: "ru", titles: { humidity: "текущая влажность" }, enum_labels: {} }; } };\n'
            "await ensureFeatureLabels(hass);\n"
            "await ensureFeatureLabels(hass);\n"
            'console.log(JSON.stringify([calls, featureTitle("humidity")]));\n'
        )

        assert _run_node(tmp_path, driver, modules=("feature-labels.js",)) == [2, "текущая влажность"]

    @requires_node
    def test_an_unusable_hass_is_not_remembered_as_an_answer(self, tmp_path: Path) -> None:
        """``hass`` без ``callWS`` не считается ответом «словаря нет».

        Компоненты подключаются в разном порядке, и первый вполне может
        подключиться раньше, чем панель получила рабочий ``hass``.

        Что сломается у пользователя, если тест упадёт: словарь не будет
        запрошен ни разу — не потому что бэкенд отказал, а потому что
        первым спросил тот, кому нечем было спрашивать.
        """
        driver = _labels_driver(
            "let calls = 0;\n"
            'const hass = { language: "ru", callWS: async () => { calls += 1;\n'
            '  return { language: "ru", titles: { humidity: "текущая влажность" }, enum_labels: {} }; } };\n'
            "await ensureFeatureLabels(undefined);\n"
            "await ensureFeatureLabels({});\n"
            "await ensureFeatureLabels(hass);\n"
            'console.log(JSON.stringify([calls, featureTitle("humidity")]));\n'
        )

        assert _run_node(tmp_path, driver, modules=("feature-labels.js",)) == [1, "текущая влажность"]

    @requires_node
    def test_the_vocabulary_is_fetched_once_per_page(self, tmp_path: Path) -> None:
        """Сколько бы компонентов ни спросило — запрос один.

        Таблица статична и весит около 12 КБ; повторять её на каждый
        компонент (и тем более на каждый опрос статуса) не за что.

        Что сломается у пользователя, если тест упадёт: на большой
        установке открытие панели превратится в десятки одинаковых
        запросов подряд.
        """
        driver = _labels_driver(
            "let calls = 0;\n"
            'const hass = { language: "ru", callWS: async () => { calls += 1; '
            'return { language: "ru", titles: {}, enum_labels: {} }; } };\n'
            "await Promise.all([ensureFeatureLabels(hass), ensureFeatureLabels(hass), ensureFeatureLabels(hass)]);\n"
            "await ensureFeatureLabels(hass);\n"
            "console.log(JSON.stringify(calls));\n"
        )

        assert _run_node(tmp_path, driver, modules=("feature-labels.js",)) == 1

    @requires_node
    def test_enum_values_get_the_same_treatment(self, tmp_path: Path) -> None:
        """ENUM-значение подписывается так же, как функция.

        Что сломается у пользователя, если тест упадёт: в карточке
        устройства останется ``dehumidification`` — слово, которое Sber
        на своей же странице переводит на человеческий язык.
        """
        driver = _labels_driver(
            'const labels = { language: "ru", titles: {},'
            ' enum_labels: { hvac_work_mode: { dehumidification: "режим осушения" } } };\n'
            'const hass = { language: "ru", callWS: async () => labels };\n'
            "await ensureFeatureLabels(hass);\n"
            'console.log(JSON.stringify([enumValueLabel(hass, "hvac_work_mode", "dehumidification"),'
            ' enumValueLabel(hass, "hvac_work_mode", "nonsense")]));\n'
        )

        assert _run_node(tmp_path, driver, modules=("feature-labels.js",)) == [
            {"text": "режим осушения", "hint": "dehumidification"},
            {"text": "nonsense", "hint": ""},
        ]

    @requires_node
    def test_reset_clears_the_cache(self, tmp_path: Path) -> None:
        """``resetFeatureLabels`` действительно сбрасывает состояние.

        Что сломается, если тест упадёт: тесты этого файла начнут
        зависеть от порядка исполнения и перестанут ловить регрессии.
        """
        driver = _labels_driver(
            'const hass = { language: "ru", callWS: async () => '
            '({ language: "ru", titles: { humidity: "текущая влажность" }, enum_labels: {} }) };\n'
            "await ensureFeatureLabels(hass);\n"
            "resetFeatureLabels();\n"
            'console.log(JSON.stringify(featureTitle("humidity")));\n'
        )

        assert _run_node(tmp_path, driver, modules=("feature-labels.js",)) == ""


class TestPanelActuallyUsesTheVocabulary:
    """Модуль подключён к разметке, а не лежит мёртвым грузом."""

    @pytest.mark.parametrize(
        ("component", "helper"),
        [
            ("components/sber-entity-row.js", "featureTitle"),
            ("components/sber-detail-dialog.js", "featureLabel"),
            ("components/sber-detail-dialog.js", "enumValueLabel"),
            ("components/sber-validation.js", "featureLabel"),
        ],
    )
    def test_component_imports_and_renders_the_helper(self, component: str, helper: str) -> None:
        """Компонент импортирует хелпер и зовёт его.

        Что сломается у пользователя, если тест упадёт: имена функций
        снова исчезнут из списка устройств, карточки устройства или
        замечаний валидатора — молча, потому что панель не собирается и
        неиспользованный импорт ничего не ломает.
        """
        source = (WWW / component).read_text(encoding="utf-8")

        assert "feature-labels.js" in source, f"{component}: словарь не импортирован"
        assert f"{helper}(" in source, f"{component}: {helper} импортирован, но не вызывается"

    @pytest.mark.parametrize(
        "component",
        [
            "components/sber-entity-row.js",
            "components/sber-detail-dialog.js",
            "components/sber-validation.js",
        ],
    )
    def test_component_requests_the_vocabulary(self, component: str) -> None:
        """Компонент заказывает словарь при подключении.

        Что сломается у пользователя, если тест упадёт: словарь никто не
        загрузит, и хелперы будут честно возвращать идентификаторы —
        внешне так же, как если бы фичи не было вовсе.
        """
        source = (WWW / component).read_text(encoding="utf-8")

        assert "ensureFeatureLabels(this.hass, this)" in source


# ---------------------------------------------------------------------------
# 3. Коды ошибок Sber
# ---------------------------------------------------------------------------


class TestErrorCodeCatalogue:
    """Расшифровки кодов совпадают с документацией и есть во всех локалях."""

    @pytest.mark.parametrize("locale", LOCALES)
    def test_locale_covers_every_documented_code(self, locale: str) -> None:
        """В блоке ровно документированные коды плюс ``unknown``.

        Что сломается у пользователя, если тест упадёт: недостающий код
        покажется как «код не описан в документации» — хотя описан;
        лишний — переводится и сопровождается зря.
        """
        catalogue = _error_catalogue(locale)
        expected = {str(code) for code in SBER_ERROR_CODES} | {"unknown"}

        assert set(catalogue) == expected

    def test_russian_repeats_the_documentation_verbatim(self) -> None:
        """Русский текст — дословная формулировка Sber.

        Переписывать её своими словами нельзя: пользователь сверяет
        сообщение панели с документацией и с ответом поддержки Сбера, и
        расхождение обесценивает обе сверки.

        Что сломается у пользователя, если тест упадёт: расшифровка кода
        в панели перестанет совпадать с текстом на странице
        developers.sber.ru.
        """
        russian = _error_catalogue("translations/ru.json")

        mismatched = {code: (text, russian.get(str(code))) for code, text in SBER_ERROR_CODES.items()}
        mismatched = {code: pair for code, pair in mismatched.items() if pair[0] != pair[1]}

        assert mismatched == {}

    @requires_node
    def test_panel_fallback_covers_every_code(self, tmp_path: Path) -> None:
        """``EN_FALLBACK`` знает каждый код теми же словами, что ``en.json``.

        Что сломается у пользователя, если тест упадёт: до подгрузки
        категории ``config_panel`` (а для кастомной панели HA не делает
        этого сам) вместо расшифровки покажется сырой ключ
        ``sber_error.403``.
        """
        fallback = english_fallback(tmp_path)
        english = _error_catalogue("translations/en.json")

        assert english, "предусловие: блок sber_error в en.json не пуст"
        wrong = {
            key: (text, fallback.get(f"{ERROR_SECTION}.{key}"))
            for key, text in english.items()
            if fallback.get(f"{ERROR_SECTION}.{key}") != text
        }

        assert wrong == {}

    @requires_node
    def test_documented_code_is_spelled_out_and_unknown_one_is_not_guessed(self, tmp_path: Path) -> None:
        """``sberErrorText`` расшифровывает пятёрку и честно молчит про остальное.

        Что сломается у пользователя, если тест упадёт: либо код снова
        останется голым числом, либо панель припишет незнакомому коду
        чужое значение — и пользователь пойдёт чинить не то.
        """
        driver = (
            'import { sberErrorText } from "./localize.js";\n'
            "const hass = {};\n"
            "console.log(JSON.stringify([sberErrorText(hass, 403), sberErrorText(hass, 599), "
            "sberErrorText(hass, null)]));\n"
        )

        documented, unknown, absent = _run_node(tmp_path, driver, modules=("localize.js",))
        assert documented == "token verification error"
        assert unknown != documented
        assert absent == ""


class TestErrorPacketIsDecoded:
    """Бэкенд достаёт код из пакета, панель его показывает."""

    def test_error_packet_yields_code_message_and_device(self) -> None:
        """Из документированного пакета берутся все три поля.

        Что сломается у пользователя, если тест упадёт: рядом с числом
        не окажется ни текста ошибки, ни устройства, из-за которого она
        пришла.
        """
        parsed = parse_sber_error('{"code": 400, "message": "bad value", "id": "light.kitchen"}')

        assert parsed == {"code": 400, "message": "bad value", "device_id": "light.kitchen"}

    def test_truncated_payload_still_yields_the_code(self) -> None:
        """Обрезанный JSON отдаёт хотя бы код.

        ``SberBridge`` хранит последнюю ошибку обрезанной до 500
        символов, так что длинный ``details`` оставляет от пакета
        огрызок.

        Что сломается у пользователя, если тест упадёт: самая полезная
        часть длинной ошибки — её код — потеряется именно на длинных
        ошибках.
        """
        parsed = parse_sber_error('{"code": 503, "message": "service unavai')

        assert parsed is not None
        assert parsed["code"] == 503

    @pytest.mark.parametrize(
        "payload",
        ["", "   not json at all", "[1, 2, 3]", '"just a string"'],
    )
    def test_a_non_error_payload_is_reported_as_such(self, payload: str) -> None:
        """Мусор не превращается в ошибку с выдуманным кодом.

        Что сломается у пользователя, если тест упадёт: в журнале
        появится красная строка про несуществующий код.
        """
        assert parse_sber_error(payload) is None

    def test_a_boolean_is_not_mistaken_for_a_code(self) -> None:
        """``true`` — не код 1.

        В Python ``bool`` наследует ``int``, и наивная проверка
        пропустила бы ``{"code": true}`` как код ``1``.

        Что сломается у пользователя, если тест упадёт: панель покажет
        расшифровку кода, которого в пакете не было.
        """
        parsed = parse_sber_error('{"code": true, "message": "x"}')

        assert parsed is not None
        assert parsed["code"] is None

    def test_only_the_errors_topic_is_decoded(self) -> None:
        """Разбирается пакет с ``down/errors``, остальные — нет.

        Что сломается у пользователя, если тест упадёт: каждое
        опубликованное состояние будет зря разбираться как JSON, а
        полезная нагрузка команды со словом ``code`` внутри нарисуется
        в журнале красной строкой про ошибку.
        """
        logger = MessageLogger(maxlen=10)

        logger.log("in", "sbdev/user/down/errors", '{"code": 403, "message": "no"}')
        logger.log("in", "sbdev/user/down/commands", '{"code": 403}')

        error_entry, command_entry = logger.entries
        assert error_entry["sber_error"]["code"] == 403
        assert "sber_error" not in command_entry

    def test_log_entry_survives_an_unparseable_error(self) -> None:
        """Нечитаемая ошибка всё равно попадает в журнал.

        Что сломается у пользователя, если тест упадёт: пакет, который
        не удалось разобрать, исчезнет из журнала целиком — а это ровно
        тот пакет, ради которого журнал и открывают.
        """
        logger = MessageLogger(maxlen=10)

        logger.log("in", "sbdev/user/down/errors", "<binary garbage>")

        (entry,) = logger.entries
        assert entry["payload"] == "<binary garbage>"
        assert "sber_error" not in entry


class TestStatusCarriesTheLastError:
    """Статус несёт разобранную последнюю ошибку, а не только счётчик."""

    async def _status(self, stats: dict[str, Any], messages: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """Вызвать ``ws_get_status`` с подставленной статистикой.

        Args:
            stats: Значение ``bridge.stats``.
            messages: Значение ``bridge.message_log`` — журнал пакетов,
                по которому датируется последняя ошибка.

        Returns:
            Тело ответа команды.
        """
        hass = MagicMock()
        hass.config.location_name = "Home"
        connection = MagicMock()
        bridge = MagicMock()
        bridge.stats = stats
        bridge.message_log = [] if messages is None else messages
        bridge.unacknowledged_entities = []
        bridge.is_connected = True
        bridge.connection_phase = "connected"
        bridge.entities_count = 0
        bridge.enabled_entity_ids = []
        entry = MagicMock()
        entry.options = {}

        with (
            patch(f"{_STATUS_MODULE}.get_config_entry", return_value=entry),
            patch(f"{_STATUS_MODULE}.get_bridge", return_value=bridge),
        ):
            await dispatch(ws_get_status, hass, connection, {"id": 1})
        return connection.send_result.call_args[0][1]

    @pytest.mark.asyncio
    async def test_last_error_is_decoded_for_the_panel(self) -> None:
        """Код последней ошибки доезжает до панели разобранным.

        Что сломается у пользователя, если тест упадёт: панель снова
        покажет только «Ошибок от Сбера: 3», и неверный пароль (403)
        будет неотличим от недоступного облака (503).
        """
        result = await self._status({"errors_from_sber": 3, "last_error_detail": '{"code": 403, "message": "denied"}'})

        assert result["last_error"]["code"] == 403
        assert result["last_error"]["message"] == "denied"
        assert result["last_error"]["device_id"] == ""

    @pytest.mark.asyncio
    async def test_no_error_means_no_block(self) -> None:
        """Пока ошибок не было, показывать нечего.

        Что сломается у пользователя, если тест упадёт: на здоровом
        мосту появится пустая красная плитка.
        """
        result = await self._status({"errors_from_sber": 0, "last_error_detail": ""})

        assert result["last_error"] is None

    @pytest.mark.asyncio
    async def test_the_error_arrives_dated(self) -> None:
        """Вместе с кодом уезжает момент, когда ошибка пришла.

        Что сломается у пользователя, если тест упадёт: плитка снова
        станет вневременной, и «сейчас сломано» будет не отличить от
        «сломалось один раз при старте».
        """
        result = await self._status(
            {"errors_from_sber": 1, "last_error_detail": '{"code": 403, "message": "denied"}'},
            [{"time": 1000.0, "direction": "in", "topic": "sbdev/u/down/errors", "payload": "{}"}],
        )

        assert result["last_error"]["at"] == 1000.0
        assert result["last_error"]["superseded"] is False

    @pytest.mark.asyncio
    async def test_a_later_answer_from_sber_marks_the_error_as_history(self) -> None:
        """Ответ Сбера после ошибки помечает её как пережитую.

        ``last_error_detail`` не очищается ни при переподключении, ни при
        удачной публикации: пользователь исправил пароль, мост работает —
        а красная плитка «403, ошибка проверки токена» висит до
        перезапуска Home Assistant.

        Что сломается у пользователя, если тест упадёт: панель снова
        будет пугать давно исправленной ошибкой.
        """
        result = await self._status(
            {"errors_from_sber": 1, "last_error_detail": '{"code": 403, "message": "denied"}'},
            [
                {"time": 1000.0, "direction": "in", "topic": "sbdev/u/down/errors", "payload": "{}"},
                {"time": 1001.0, "direction": "out", "topic": "sbdev/u/up/status", "payload": "{}"},
                {"time": 1002.0, "direction": "in", "topic": "sbdev/u/down/status_request", "payload": "{}"},
            ],
        )

        assert result["last_error"]["superseded"] is True

    @pytest.mark.asyncio
    async def test_an_error_older_than_the_log_is_not_dated_by_guesswork(self) -> None:
        """Ошибку, которой нет в журнале, не датируют наугад.

        Кольцевой буфер ограничен, и пользователь может очистить его
        кнопкой.

        Что сломается у пользователя, если тест упадёт: рядом со старой
        ошибкой встанет сегодняшнее время, и человек пойдёт искать
        поломку, которой сейчас нет.
        """
        result = await self._status({"errors_from_sber": 1, "last_error_detail": '{"code": 503, "message": "later"}'})

        assert result["last_error"]["at"] is None
        assert result["last_error"]["superseded"] is False


class TestLastErrorMoment:
    """``last_error_moment`` читает журнал так же, как его пишет мост."""

    def test_the_latest_error_wins(self) -> None:
        """Датируется последняя ошибка, а не первая.

        Что сломается у пользователя, если тест упадёт: панель подпишет
        свежую ошибку временем давней.
        """
        moment = last_error_moment(
            [
                {"time": 1.0, "direction": "in", "topic": "sbdev/u/down/errors"},
                {"time": 2.0, "direction": "in", "topic": "sbdev/u/down/errors"},
            ]
        )

        assert moment == {"at": 2.0, "superseded": False}

    def test_an_unparseable_error_packet_is_still_dated(self) -> None:
        """Нечитаемый пакет ошибки тоже датируется.

        Он одинаково увеличивает счётчик и переписывает
        ``last_error_detail``, поэтому определять ошибку по разобранному
        полю нельзя — только по топику.

        Что сломается у пользователя, если тест упадёт: самая непонятная
        ошибка останется единственной без времени.
        """
        moment = last_error_moment([{"time": 5.0, "direction": "in", "topic": "sbdev/u/down/errors"}])

        assert moment["at"] == 5.0

    def test_our_own_publishes_do_not_count_as_an_answer(self) -> None:
        """Наши публикации после ошибки — не признак выздоровления.

        Мост публикует состояния независимо от того, принимает их облако
        или молча отбрасывает.

        Что сломается у пользователя, если тест упадёт: плитка потускнеет
        сразу после первой же публикации, то есть всегда.
        """
        moment = last_error_moment(
            [
                {"time": 1.0, "direction": "in", "topic": "sbdev/u/down/errors"},
                {"time": 2.0, "direction": "out", "topic": "sbdev/u/up/config"},
            ]
        )

        assert moment["superseded"] is False

    def test_a_later_error_does_not_supersede_itself(self) -> None:
        """Следующая ошибка не считается ответом облака.

        Что сломается у пользователя, если тест упадёт: непрерывный поток
        ошибок будет выглядеть как выздоровление.
        """
        moment = last_error_moment(
            [
                {"time": 1.0, "direction": "in", "topic": "sbdev/u/down/errors"},
                {"time": 2.0, "direction": "in", "topic": "sbdev/u/down/errors"},
            ]
        )

        assert moment["superseded"] is False

    def test_an_empty_log_dates_nothing(self) -> None:
        """Пустой журнал не рождает ни времени, ни выводов.

        Что сломается у пользователя, если тест упадёт: сразу после
        перезапуска панель припишет ошибке время «прямо сейчас».
        """
        assert last_error_moment([]) == {"at": None, "superseded": False}

    def test_the_logger_and_the_reader_agree_on_the_topic(self) -> None:
        """Читатель узнаёт ровно те записи, которые пишет ``MessageLogger``.

        Проверяется через настоящий логгер, а не через выдуманные словари:
        разойдись имя топика — и функция молча перестанет находить ошибки.

        Что сломается у пользователя, если тест упадёт: время у ошибки
        исчезнет, и плитка вернётся к вечно красному состоянию.
        """
        logger = MessageLogger(maxlen=10)
        logger.log("in", "sbdev/user/down/errors", '{"code": 403, "message": "no"}')
        logger.log("in", "sbdev/user/down/status_request", "{}")

        moment = last_error_moment(logger.entries)

        assert moment["at"] == logger.entries[0]["time"]
        assert moment["superseded"] is True


class TestStatsGridRendersTheLastError:
    """Плитка последней ошибки действительно есть в разметке."""

    def test_grid_renders_the_decoded_last_error(self) -> None:
        """Компонент читает ``status.last_error`` и расшифровывает код.

        Что сломается у пользователя, если тест упадёт: бэкенд будет
        отдавать разобранную ошибку, а панель — молчать о ней.
        """
        source = (WWW / "components" / "sber-stats-grid.js").read_text(encoding="utf-8")

        assert "sberErrorText" in source
        assert re.search(r"_renderLastError\(\s*s\.last_error\s*\)", source)

    def test_grid_dates_the_error_and_steps_back_when_it_is_history(self) -> None:
        """Плитка показывает время ошибки и тускнеет, когда Сбер уже ответил.

        Что сломается у пользователя, если тест упадёт: бэкенд будет
        отдавать ``at`` и ``superseded``, а панель — по-прежнему держать
        красную плитку до перезапуска Home Assistant.
        """
        source = (WWW / "components" / "sber-stats-grid.js").read_text(encoding="utf-8")

        assert "error.at" in source, "время ошибки не отрисовано"
        assert "error.superseded" in source, "пережитая ошибка не отличается от свежей"
        assert "stats.last_error_superseded" in source, "нет подписи, объясняющей блёклую плитку"
        assert ".last-error.superseded" in source, "нет стиля для пережитой ошибки"

    def test_message_log_spells_out_the_error_code(self) -> None:
        """Журнал DevTools подписывает код рядом с сырым пакетом.

        Что сломается у пользователя, если тест упадёт: в журнале
        снова останется голое ``"code": 403`` — единственное место, где
        код вообще был виден.
        """
        source = (WWW / "components" / "sber-devtools.js").read_text(encoding="utf-8")

        assert "sberErrorText" in source
        assert "_renderSberError(m.sber_error)" in source


# ---------------------------------------------------------------------------
# 4. Строки панели проходят через ICU-разбор Home Assistant
# ---------------------------------------------------------------------------


ICU_QUOTE_HAZARD = re.compile(r"'[{}<']")
"""Апостроф, открывающий в ICU-сообщении литеральную вставку.

Home Assistant отдаёт переводы фронтенду, а тот форматирует их через
``intl-messageformat``. В ICU MessageFormat апостроф перед ``{``, ``}``
или ``<`` открывает «кавычку»: всё до следующего апострофа выводится как
есть, без подстановки. Пара апострофов подряд — тоже спецпоследовательность
(``''`` печатается как один апостроф).

Проверено исполнением настоящего ``intl-messageformat``:
``"Feature '{key}': type '{declared}'"`` печатается как
``Feature {key}: type {declared}``, а соседние плейсхолдеры без
апострофов подставляются — получается каша, в которой половина строки
превратилась в фигурные скобки.
"""


class TestPanelStringsSurviveIcuFormatting:
    """Ни одна строка панели не ломается о правила ICU."""

    @pytest.mark.parametrize("locale", LOCALES)
    def test_no_apostrophe_opens_an_icu_quote(self, locale: str) -> None:
        """В строках нет ``'{``, ``'}``, ``'<`` и ``''``.

        Кавычить идентификаторы и плейсхолдеры нужно типографскими
        кавычками: «…» по-русски, “…” по-английски. Обратный слэш ICU не
        понимает, а удвоенный апостроф хоть и правилен для ICU, но
        запасной путь панели (``EN_FALLBACK`` подставляется своим
        regex-ом, а не через ICU) выведет его как есть — то есть до
        загрузки переводов пользователь увидит ``''key''``.

        Что сломается у пользователя, если тест упадёт: в замечании
        валидатора вместо имени функции, типа и границ диапазона
        останутся голые ``{key}``, ``{declared}``, ``{expected_block}``
        — причём вперемешку с подставленными соседями, потому что
        подстановка ломается только у тех плейсхолдеров, вокруг которых
        стоят апострофы.
        """
        offenders = {key: value for key, value in panel_strings(locale).items() if ICU_QUOTE_HAZARD.search(str(value))}

        assert offenders == {}

    @requires_node
    def test_the_english_fallback_is_free_of_the_same_hazard(self, tmp_path: Path) -> None:
        """``EN_FALLBACK`` тоже чист.

        Он обязан дословно повторять ``en.json`` (это проверяет
        ``test_translations_consistency``), так что опасная кавычка,
        попавшая сюда, доедет и до ICU.

        Что сломается у пользователя, если тест упадёт: правку сделают в
        одном файле из двух, и строка снова разъедется — тихо, потому
        что запасной путь подставляет плейсхолдеры своим regex-ом и
        апострофов не замечает.
        """
        offenders = {key: value for key, value in english_fallback(tmp_path).items() if ICU_QUOTE_HAZARD.search(value)}

        assert offenders == {}
