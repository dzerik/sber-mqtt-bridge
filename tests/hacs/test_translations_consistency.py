"""Согласованность ``strings.json`` и ``translations/*.json``.

Строки интеграции живут в трёх файлах, и HA берёт из них разное:
``strings.json`` — источник правды (по нему HA собирает английский
интерфейс и по нему сверяется hassfest), ``translations/en.json`` —
язык по умолчанию, ``translations/ru.json`` — русская локаль.
Рассинхрон здесь не ломает ни один тест поведения и не виден в code
review: пользователь просто получает сырой ключ вместо текста —
``component.sber_mqtt_bridge.options.step.device_sync.title`` в
заголовке шага настройки.  Ровно это и случилось с шагом
``device_sync``: ключи добавили в ``strings.json`` и ``ru.json``, а в
``en.json`` — нет, и весь англоязычный интерфейс шага остался без
перевода.

Файл фиксирует три инварианта:

1. все три файла — валидный JSON;
2. набор ключей совпадает во всех трёх (лишний ключ так же плох, как
   недостающий: это мёртвая строка, которую никто не показывает, но
   которую переводчики продолжают переводить);
3. плейсхолдеры (``{count}``, ``{entities}``…) у одного ключа
   одинаковы во всех переводах — HA подставляет их по имени, и
   лишний ``{roles}`` в русском шаблоне уронит рендер плитки ремонта
   только у русских пользователей.

Дополнительно проверяется, что ``en.json`` — точная копия
``strings.json``: язык по умолчанию не имеет права расходиться с
источником правды по тексту, иначе одна и та же кнопка называется
по-разному в мастере и в панели.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

COMPONENT_ROOT = Path(__file__).resolve().parents[2] / "custom_components" / "sber_mqtt_bridge"
"""Корень интеграции — от него отсчитываются все файлы строк."""

STRINGS = "strings.json"
"""Источник правды: по нему HA собирает английский UI и сверяется hassfest."""

TRANSLATIONS = ("translations/en.json", "translations/ru.json")
"""Локали, которые обязаны повторять набор ключей ``strings.json``."""

ALL_STRING_FILES = (STRINGS, *TRANSLATIONS)
"""Все файлы строк интеграции."""

PLACEHOLDER_RE = re.compile(r"{(\w+)}")
"""Плейсхолдер HA-перевода: ``{count}``, ``{entities}``, ``{entity_id}``…"""

WWW = COMPONENT_ROOT / "www"
"""Корень SPA-панели (сборки нет — файлы отдаются как есть)."""

LOCALIZE_JS = WWW / "localize.js"
"""Модуль локализации панели: ``t()`` и английский запасной словарь."""

PANEL_SECTION = "config_panel"
"""Секция ``strings.json``, из которой панель берёт свои строки."""

T_CALL_RE = re.compile(r"\bt\(\s*(?:this\.)?hass\s*,\s*\"([a-z0-9_.-]+)\"")
"""Вызов ``t(this.hass, "block.key")`` в коде панели."""

NODE = shutil.which("node")
"""Путь к node — им из JS вынимается настоящий словарь запасных строк."""

requires_node = pytest.mark.skipif(NODE is None, reason="node is not installed")
"""Пропуск проверок, которым нужно исполнить JS."""


def load(name: str) -> dict[str, Any]:
    """Прочитать файл строк.

    Args:
        name: Путь относительно корня интеграции.

    Returns:
        Разобранный JSON.
    """
    return json.loads((COMPONENT_ROOT / name).read_text(encoding="utf-8"))


def flatten(data: Any, prefix: str = "") -> dict[str, Any]:
    """Свернуть вложенный словарь в карту «путь через точку → значение».

    Args:
        data: Узел JSON.
        prefix: Путь до узла.

    Returns:
        Карта листьев: ``"options.step.device_sync.title" → "Device sync timing"``.
    """
    if not isinstance(data, dict):
        return {prefix: data}
    out: dict[str, Any] = {}
    for key, value in data.items():
        out.update(flatten(value, f"{prefix}.{key}" if prefix else key))
    return out


def panel_strings(name: str) -> dict[str, Any]:
    """Свернуть секцию ``config_panel`` файла строк в плоскую карту.

    Args:
        name: Путь относительно корня интеграции.

    Returns:
        Карта ``"gate_options.title" → текст``.
    """
    return flatten(load(name).get(PANEL_SECTION, {}))


def keys_rendered_by_the_panel() -> dict[str, list[str]]:
    """Найти все ключи, которые панель отдаёт в ``t()``.

    Сам ``localize.js`` пропускается: в его документации есть пример
    ``t(this.hass, "block.key")``, который ключом не является.

    Returns:
        Карта ``ключ → файлы, где он рендерится``.
    """
    found: dict[str, list[str]] = {}
    for path in sorted(WWW.rglob("*.js")):
        if path == LOCALIZE_JS or "vendor" in path.parts:
            continue
        for key in T_CALL_RE.findall(path.read_text(encoding="utf-8")):
            found.setdefault(key, []).append(path.name)
    return found


def english_fallback(tmp_path: Path) -> dict[str, str]:
    """Вынуть настоящий ``EN_FALLBACK`` из ``localize.js`` через node.

    Регулярка по исходнику разобрала бы многострочные литералы и
    escape-последовательности неверно, поэтому словарь берётся
    исполнением модуля — он ни от чего не зависит и импортируется как
    есть.

    Args:
        tmp_path: Временный каталог для копии модуля и точки входа.

    Returns:
        Карта ``ключ → английский текст``.
    """
    shutil.copy(LOCALIZE_JS, tmp_path / "localize.js")
    entry = tmp_path / "dump.mjs"
    entry.write_text(
        'import { EN_FALLBACK } from "./localize.js";\nprocess.stdout.write(JSON.stringify(EN_FALLBACK));\n',
        encoding="utf-8",
    )
    result = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [str(NODE), "dump.mjs"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


class TestStringFilesAreValid:
    """Базовая пригодность файлов строк."""

    @pytest.mark.parametrize("name", ALL_STRING_FILES)
    def test_file_is_valid_json(self, name: str) -> None:
        """Файл разбирается и содержит непустой объект.

        Битый JSON здесь — не косметика: HA не загрузит переводы
        интеграции целиком, и весь интерфейс окажется в сырых ключах.
        """
        data = load(name)

        assert isinstance(data, dict)
        assert data, f"{name} пуст"

    @pytest.mark.parametrize("name", ALL_STRING_FILES)
    def test_every_leaf_is_a_non_empty_string(self, name: str) -> None:
        """Каждый лист — непустая строка.

        ``null`` или пустая строка выглядят как «перевод есть», а
        показывают пустое место: пользователь видит безымянную кнопку
        или шаг настройки без заголовка.
        """
        bad = {
            key: value for key, value in flatten(load(name)).items() if not isinstance(value, str) or not value.strip()
        }

        assert bad == {}


class TestKeysMatchAcrossLocales:
    """Наборы ключей обязаны совпадать во всех файлах строк."""

    @pytest.mark.parametrize("name", TRANSLATIONS)
    def test_locale_covers_exactly_the_source_keys(self, name: str) -> None:
        """В локали ровно те же ключи, что в ``strings.json``.

        Недостающий ключ — сырой идентификатор вместо текста в
        интерфейсе (так пропал весь шаг ``device_sync`` в английской
        локали).  Лишний — мёртвая строка: её никто не покажет, но её
        продолжат сопровождать и переводить.
        """
        source = set(flatten(load(STRINGS)))
        locale = set(flatten(load(name)))

        assert sorted(source - locale) == [], f"{name}: ключи есть в strings.json, но нет в локали"
        assert sorted(locale - source) == [], f"{name}: ключи есть в локали, но нет в strings.json"

    def test_default_locale_repeats_the_source_verbatim(self) -> None:
        """``en.json`` — точная копия ``strings.json``.

        Язык по умолчанию не имеет права расходиться с источником
        правды: иначе один и тот же шаг называется по-разному в
        зависимости от того, откуда HA взял строку, а правка в
        ``strings.json`` (единственном файле, который смотрит hassfest)
        молча не доезжает до пользователя.
        """
        assert load("translations/en.json") == load(STRINGS)


class TestPlaceholdersMatchAcrossLocales:
    """Плейсхолдеры подставляются по имени — набор обязан совпадать."""

    @pytest.mark.parametrize("name", TRANSLATIONS)
    def test_placeholders_are_identical_to_the_source(self, name: str) -> None:
        """У каждого ключа те же плейсхолдеры, что и в ``strings.json``.

        HA подставляет значения по имени: лишний ``{roles}`` в русском
        шаблоне уронит рендер плитки ремонта только у русских
        пользователей, а недостающий ``{entities}`` оставит их без
        имени сломанного устройства — то есть без единственной
        подсказки, что чинить.
        """
        source = flatten(load(STRINGS))
        locale = flatten(load(name))

        mismatched = {
            key: (sorted(PLACEHOLDER_RE.findall(str(source[key]))), sorted(PLACEHOLDER_RE.findall(str(value))))
            for key, value in locale.items()
            if key in source
            and set(PLACEHOLDER_RE.findall(str(source[key]))) != set(PLACEHOLDER_RE.findall(str(value)))
        }

        assert mismatched == {}


class TestPanelRendersOnlyTranslatedKeys:
    """Панель берёт строки из тех же файлов — ключи обязаны там быть.

    У SPA-панели нет ни сборки, ни JS-раннера: ``t(this.hass, "ключ")``
    с опечаткой или с ключом, который забыли добавить в JSON, не ломает
    ничего — панель просто нарисует сам ключ (``gate_options.save``
    вместо «Сохранить настройки ворот»).  Заметить это можно только
    глазами и только открыв нужный диалог, поэтому проверка статическая.
    """

    def test_panel_renders_at_least_the_gate_block(self) -> None:
        """Извлечение ключей вообще что-то находит.

        Страховка от «зелёного» самообмана: если разбор ``t()``
        сломается (переименуют хелпер, сменят кавычки), остальные тесты
        класса начнут проверять пустое множество и будут проходить
        всегда.
        """
        rendered = keys_rendered_by_the_panel()

        assert len(rendered) >= 20, f"разбор t() нашёл подозрительно мало ключей: {sorted(rendered)}"
        assert "gate_options.save" in rendered

    @pytest.mark.parametrize("name", ALL_STRING_FILES)
    def test_every_rendered_key_is_translated(self, name: str) -> None:
        """Каждый ключ из ``t()`` есть в секции ``config_panel`` файла строк.

        Недостающий ключ в ``ru.json`` — английский текст у русского
        пользователя (HA накладывает локаль поверх английской), а
        недостающий в ``en.json`` — сырой идентификатор у всех.
        """
        available = set(panel_strings(name))
        rendered = keys_rendered_by_the_panel()

        missing = {key: files for key, files in rendered.items() if key not in available}

        assert missing == {}

    @requires_node
    def test_every_rendered_key_has_an_english_fallback(self, tmp_path: Path) -> None:
        """У каждого ключа из ``t()`` есть запись в ``EN_FALLBACK``.

        Пока HA не подгрузил категорию ``config_panel`` (а для кастомной
        панели он не делает этого сам), ``t()`` показывает именно
        ``EN_FALLBACK``.  Ключ без записи выводится «как есть» на первом
        же кадре — то есть при каждом открытии диалога у всех
        пользователей.
        """
        fallback = english_fallback(tmp_path)
        rendered = keys_rendered_by_the_panel()

        missing = {key: files for key, files in rendered.items() if key not in fallback}

        assert missing == {}

    @requires_node
    def test_fallback_text_matches_the_default_locale(self, tmp_path: Path) -> None:
        """``EN_FALLBACK`` дословно повторяет английские строки из JSON.

        Требование записано в самом ``localize.js`` («must mirror
        translations/en.json»), и оно не косметическое: текст меняется
        прямо на глазах у пользователя, когда догружается категория
        переводов.  Заодно ловится запись про ключ, которого в JSON нет
        вовсе — такой «перевод» не увидит ни один переводчик.
        """
        fallback = english_fallback(tmp_path)
        english = panel_strings("translations/en.json")

        mismatched = {key: (text, english.get(key)) for key, text in fallback.items() if english.get(key) != text}

        assert mismatched == {}
