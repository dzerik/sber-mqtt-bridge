"""Тесты контура проверок репозитория: hacs.json, coverage-порог, релиз, .gitignore.

Здесь проверяются не строки кода, а обещания, которые репозиторий даёт
наружу: какая минимальная версия Home Assistant заявлена в HACS, какой
порог покрытия защищает CI, может ли тег уехать в релиз мимо тестов и не
утекут ли в историю локальные артефакты. Всё это ломается молча и
обнаруживается уже у пользователя, поэтому закрыто тестами.
"""

from __future__ import annotations

import json
import pathlib
import re
import tomllib

import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
"""Корень репозитория (tests/hacs/<file> → на два уровня вверх)."""

WORKFLOWS = REPO_ROOT / ".github" / "workflows"
"""Каталог GitHub Actions workflow-файлов."""

# Самые новые API Home Assistant, которые интеграция импортирует на уровне
# модуля: если пользователь поставит HA старее — будет ImportError прямо
# при загрузке, а не деградация функциональности.  Версии проверены по
# исходникам HA (тег, в котором символ появился впервые).
REQUIRED_HA_APIS: dict[str, tuple[str, str]] = {
    # символ: (версия HA, файл интеграции, который его импортирует)
    "OptionsFlowWithReload": ("2025.8.0", "config_flow.py"),
}


def _ha_version_tuple(version: str) -> tuple[int, ...]:
    """Разобрать calver-версию HA (``2026.2.3``) в кортеж для сравнения.

    Args:
        version: Строка версии Home Assistant.

    Returns:
        Кортеж целых чисел, пригодный для сравнения ``<``/``>=``.
    """
    match = re.fullmatch(r"(\d+)\.(\d+)(?:\.(\d+))?", version)
    assert match, f"не calver-версия HA: {version!r}"
    return tuple(int(part) for part in match.groups(default="0"))


def test_hacs_min_ha_covers_every_required_api() -> None:
    """Заявленный в hacs.json минимум HA не ниже самого нового используемого API.

    Если тест упадёт — HACS разрешит установку на версии HA, где нужного
    класса ещё нет, и интеграция свалится с ImportError при загрузке
    config_flow: пользователь увидит «Ошибка настройки» без внятной причины.
    """
    hacs = json.loads((REPO_ROOT / "hacs.json").read_text(encoding="utf-8"))
    declared = hacs["homeassistant"]

    for symbol, (introduced_in, module) in REQUIRED_HA_APIS.items():
        source = (REPO_ROOT / "custom_components" / "sber_mqtt_bridge" / module).read_text(encoding="utf-8")
        # Таблица не должна протухнуть: символ обязан реально импортироваться.
        assert symbol in source, f"{symbol} больше не используется в {module} — обнови REQUIRED_HA_APIS"
        assert _ha_version_tuple(declared) >= _ha_version_tuple(introduced_in), (
            f"hacs.json обещает HA {declared}, но {symbol} появился только в {introduced_in}"
        )


def test_coverage_gate_matches_documented_minimum() -> None:
    """Порог ``fail_under`` не опускается ниже документированного минимума.

    Если тест упадёт — CI начнёт пропускать регрессии покрытия: удаление
    сотен покрытых строк останется зелёным, и незамеченный мёртвый код
    доедет до релиза.
    """
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    fail_under = pyproject["tool"]["coverage"]["report"]["fail_under"]

    assert fail_under >= 95, "порог покрытия не должен опускаться ниже 95%"


def test_release_workflow_is_gated_on_ci() -> None:
    """Публикация релиза по тегу возможна только после зелёного CI.

    Если тест упадёт — тег снова сможет уехать в релиз с красными тестами
    (так вышел битый HACS-релиз v1.47.0), и пользователи получат обновление,
    которое не собирается.
    """
    release = yaml.safe_load((WORKFLOWS / "release.yaml").read_text(encoding="utf-8"))
    jobs = release["jobs"]

    gate_jobs = {name for name, job in jobs.items() if str(job.get("uses", "")).endswith("ci.yaml")}
    assert gate_jobs, "release.yaml должен вызывать CI как reusable workflow"

    needs = jobs["release"].get("needs") or []
    needs = [needs] if isinstance(needs, str) else list(needs)
    assert gate_jobs & set(needs), "job 'release' должен зависеть от CI-гейта через needs"


def test_ci_workflow_is_callable_from_release() -> None:
    """CI объявлен как reusable workflow, иначе гейт релиза не запустится.

    Если тест упадёт — release.yaml не сможет вызвать CI, и каждый тег будет
    падать на этапе запуска workflow, блокируя выпуск.
    """
    ci = yaml.safe_load((WORKFLOWS / "ci.yaml").read_text(encoding="utf-8"))
    # PyYAML разбирает голое `on:` как булев True — YAML 1.1, не опечатка.
    triggers = ci[True] if True in ci else ci["on"]

    assert "workflow_call" in triggers, "ci.yaml должен объявлять trigger workflow_call"


def test_local_only_artifacts_are_gitignored() -> None:
    """Локальные артефакты не попадают в индекс по невнимательности.

    Если тест упадёт — в репозиторий рискуют уехать 36-мегабайтный тарболл
    исходников HA и дамп устройств реального дома (имена комнат и техники),
    а из истории git это уже не вычистить.
    """
    patterns = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()

    assert "/tools/config.json" in patterns, "дамп устройств реального дома должен быть в .gitignore"
    assert "/homeassistant-*.tar.gz" in patterns, "тарболлы исходников HA должны быть в .gitignore"
