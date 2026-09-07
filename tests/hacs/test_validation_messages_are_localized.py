"""Замечания валидатора переводятся, а не жёстко зашиты в код.

Панель локализована целиком (v1.36.0, 294 строки, ru/en), и колонка
«Описание» на вкладке проверки схемы — не исключение: бэкенд отдаёт
``message_key`` + ``message_args``, панель ищет их в
``config_panel.validation_issue`` и рисует текст на языке пользователя.
Английский ``description`` из :data:`VALIDATION_MESSAGES` остаётся
запасным вариантом для логов, диагностики и падающих тестов.

Схема требует, чтобы четыре списка совпадали ключ в ключ:

1. :data:`VALIDATION_MESSAGES` — то, что валидатор умеет сказать;
2. ``strings.json`` — источник правды для hassfest;
3. ``translations/en.json`` и ``translations/ru.json`` — локали;
4. ``EN_FALLBACK`` в ``www/localize.js`` — то, что видно до загрузки
   переводов.

Соседний ``test_translations_consistency.py`` этого не ловит: он ищет в
JS литеральные вызовы ``t(this.hass, "…")``, а ключ замечания
собирается на лету из ``message_key``.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from test_translations_consistency import english_fallback, panel_strings, requires_node

from custom_components.sber_mqtt_bridge.schema_validator import VALIDATION_MESSAGES

SECTION = "validation_issue"
"""Блок ``config_panel``, в котором живут тексты замечаний."""

PLACEHOLDER_RE = re.compile(r"{(\w+)}")
"""Плейсхолдер перевода: ``{key}``, ``{category}``, ``{min}``…"""

LOCALES = ("strings.json", "translations/en.json", "translations/ru.json")
"""Файлы строк, обязанные содержать весь блок целиком."""


def _section(name: str) -> dict[str, str]:
    """Вернуть блок ``validation_issue`` файла строк.

    Args:
        name: Путь относительно корня интеграции.

    Returns:
        Карта «ключ замечания → текст».
    """
    prefix = f"{SECTION}."
    return {key.removeprefix(prefix): value for key, value in panel_strings(name).items() if key.startswith(prefix)}


def _placeholders(text: str) -> set[str]:
    """Собрать имена плейсхолдеров строки.

    Args:
        text: Текст с ``{name}``.

    Returns:
        Множество имён.
    """
    return set(PLACEHOLDER_RE.findall(text))


class TestEveryMessageIsTranslatable:
    """У каждой формулировки валидатора есть ключ во всех файлах строк."""

    @pytest.mark.parametrize("locale", LOCALES)
    def test_locale_has_exactly_the_validator_keys(self, locale: str) -> None:
        """Набор ключей локали совпадает с набором валидатора.

        Что сломается у пользователя, если тест упадёт: недостающий ключ
        — это замечание, которое панель покажет по-английски (или сырым
        идентификатором) посреди русской вкладки; лишний ключ —
        перевод, который никто никогда не увидит, и переводчик тратит на
        него время.
        """
        catalogue = _section(locale)

        assert sorted(set(VALIDATION_MESSAGES) - set(catalogue)) == []
        assert sorted(set(catalogue) - set(VALIDATION_MESSAGES)) == []

    def test_english_locale_repeats_the_validator_text_verbatim(self) -> None:
        """``en.json`` дословно повторяет английский текст валидатора.

        Что сломается у пользователя, если тест упадёт: одно и то же
        замечание будет читаться по-разному в панели и в логе, и по
        тексту из отчёта пользователя нельзя будет найти место в коде.
        """
        english = _section("translations/en.json")

        mismatched = {
            key: (text, english.get(key)) for key, text in VALIDATION_MESSAGES.items() if english.get(key) != text
        }

        assert mismatched == {}

    @pytest.mark.parametrize("locale", LOCALES)
    def test_placeholders_match_the_validator(self, locale: str) -> None:
        """Плейсхолдеры перевода — ровно те, что подставляет валидатор.

        Что сломается у пользователя, если тест упадёт: лишний
        плейсхолдер останется в тексте фигурными скобками
        (``{expected}``), а потерянный унесёт с собой единственное
        число, ради которого замечание и читают.
        """
        catalogue = _section(locale)

        mismatched = {
            key: (_placeholders(text), _placeholders(catalogue[key]))
            for key, text in VALIDATION_MESSAGES.items()
            if key in catalogue and _placeholders(catalogue[key]) != _placeholders(text)
        }

        assert mismatched == {}

    @requires_node
    def test_panel_fallback_covers_every_message(self, tmp_path: Path) -> None:
        """``EN_FALLBACK`` знает каждое замечание — и теми же словами.

        До того как HA догрузит категорию ``config_panel`` (а для
        кастомной панели он не делает этого сам), ``t()`` отдаёт именно
        ``EN_FALLBACK``.

        Что сломается у пользователя, если тест упадёт: на первом кадре
        вкладки вместо описания появится сырой ключ
        ``validation_issue.value_out_of_range``.
        """
        fallback = english_fallback(tmp_path)

        wrong = {
            key: (text, fallback.get(f"{SECTION}.{key}"))
            for key, text in VALIDATION_MESSAGES.items()
            if fallback.get(f"{SECTION}.{key}") != text
        }

        assert wrong == {}


class TestEveryEmittedIssueCarriesItsKey:
    """Ключ и аргументы доезжают до панели, а не теряются по дороге."""

    def test_message_key_is_declared_in_the_catalogue(self) -> None:
        """Каждый ``message_key=`` в коде валидатора есть в каталоге.

        Проверяется по исходнику: подобрать payload, поднимающий все 28
        замечаний, нельзя, а опечатка в ключе роняет публикацию
        ``KeyError`` уже на живом мосте.

        Что сломается у пользователя, если тест упадёт: мост перестанет
        публиковать состояние того устройства, на котором сработала
        проверка с опечаткой.
        """
        source = (
            Path(__file__).resolve().parents[2] / "custom_components" / "sber_mqtt_bridge" / "schema_validator.py"
        ).read_text(encoding="utf-8")
        used = set(re.findall(r'message_key="([a-z0-9_]+)"', source))

        assert used, "предусловие: в валидаторе есть хотя бы один message_key"
        assert sorted(used - set(VALIDATION_MESSAGES)) == []

    def test_rendered_description_matches_the_translated_pair(self) -> None:
        """``description`` — это тот же шаблон, подставленный теми же аргументами.

        Что сломается у пользователя, если тест упадёт: русский текст в
        панели и английский в логе начнут говорить о разных вещах —
        например, о разных границах диапазона.
        """
        from custom_components.sber_mqtt_bridge.schema_validator import validate_publish

        issues = validate_publish(
            entity_id="light.probe",
            category="light",
            states=[{"key": "light_brightness", "value": {"type": "INTEGER", "integer_value": "5000"}}],
        )
        out_of_range = [i for i in issues if i.type == "out_of_range"]

        assert [i.message_key for i in out_of_range] == ["value_out_of_range"]
        assert out_of_range[0].message_args["sent"] == "5000"
        assert out_of_range[0].description == VALIDATION_MESSAGES["value_out_of_range"].format(
            **out_of_range[0].message_args
        )
