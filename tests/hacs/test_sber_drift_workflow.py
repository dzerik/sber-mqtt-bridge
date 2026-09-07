"""Тесты еженедельной сверки дрейфа документации Сбера.

Что здесь защищается.

Раз в неделю workflow ``sber-compliance`` заново скачивает документацию
Сбера и открывает PR, если она изменилась. Шаг «Detect drift» долгое
время диффил только ``sber_schemas.json``. А словари допустимых значений
ENUM и числовые диапазоны живут в ``sber_full_spec.json`` — именно из
него кодогенератор делает ``FEATURE_ENUM_VALUES`` и ``FEATURE_RANGES``.
Этот файл в диффе не участвовал, потому что в нём при каждом прогоне
меняется ``generated_at``, и наивный дифф всегда показывал бы «дрейф».

Цена ошибки для пользователя: Сбер добавляет значение в словарь функции
(или сдвигает диапазон), сверка молчит, наш валидатор продолжает жить со
старым словарём — и либо ругается на корректное значение, либо пропускает
некорректное, а устройство молча отваливается в облаке.

Тесты читают сам workflow-файл и проверяют поведение той команды
``git diff``, которая в нём записана, на настоящем временном репозитории.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_FILE = REPO_ROOT / ".github" / "workflows" / "sber-compliance.yml"

SCHEMAS_PATH = "tests/hacs/__snapshots__/sber_schemas.json"
FULL_SPEC_PATH = "tests/hacs/__snapshots__/sber_full_spec.json"
GENERATED_DIR = "custom_components/sber_mqtt_bridge/_generated"

_PATH_RE = re.compile(r"(?:tests/hacs/__snapshots__/\S+\.json|custom_components/sber_mqtt_bridge/_generated)")
_IGNORE_RE = re.compile(r"-I\s+'([^']+)'")


def _drift_step() -> dict:
    """Найти шаг «Detect drift» в workflow."""
    workflow = yaml.safe_load(WORKFLOW_FILE.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["fetch-and-check"]["steps"]
    for step in steps:
        if step.get("id") == "drift":
            return step
    pytest.fail("в sber-compliance.yml нет шага с id: drift")


def _drift_paths() -> list[str]:
    """Пути, которые шаг «Detect drift» реально сравнивает."""
    return sorted(set(_PATH_RE.findall(_drift_step()["run"])))


def _ignore_patterns() -> list[str]:
    """Регулярки ``git diff -I``, которыми шаг гасит шум."""
    return _IGNORE_RE.findall(_drift_step()["run"])


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    """Запустить git в указанном каталоге."""
    # git — доверенный инструмент разработки, argv собирается тестом.
    return subprocess.run(  # noqa: S603
        ["git", *args],  # noqa: S607
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )


def _has_drift(repo: Path) -> bool:
    """Повторить условие шага «Detect drift» на подготовленном репозитории."""
    ignore: list[str] = []
    for pattern in _ignore_patterns():
        ignore += ["-I", pattern]
    result = _git(repo, "diff", "--exit-code", "--quiet", *ignore, "--", *_drift_paths())
    return result.returncode != 0


SPEC_TEMPLATE = """{{
  "generated_at": "{stamp}",
  "functions": {{
    "hvac_air_flow_power": {{
      "enum_values": [{values}],
      "type": "ENUM"
    }}
  }}
}}
"""

GENERATED_TEMPLATE = '''"""AUTO-GENERATED.

Spec generated at: {stamp}
"""

FEATURE_ENUM_VALUES = {{"hvac_air_flow_power": frozenset({{{values}}})}}
'''


def _write_snapshot(repo: Path, stamp: str, values: str) -> None:
    """Разложить в репозитории оба снапшота и сгенерированный модуль."""
    for rel in (SCHEMAS_PATH, FULL_SPEC_PATH, f"{GENERATED_DIR}/reference_values.py"):
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
    (repo / SCHEMAS_PATH).write_text('{\n  "light": {"features": ["on_off"]}\n}\n', encoding="utf-8")
    (repo / FULL_SPEC_PATH).write_text(SPEC_TEMPLATE.format(stamp=stamp, values=values), encoding="utf-8")
    (repo / f"{GENERATED_DIR}/reference_values.py").write_text(
        GENERATED_TEMPLATE.format(stamp=stamp, values=values), encoding="utf-8"
    )


@pytest.fixture
def drift_repo(tmp_path: Path) -> Path:
    """Временный git-репозиторий с закоммиченными снапшотами."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", ".")
    _git(repo, "config", "user.email", "drift@test.local")
    _git(repo, "config", "user.name", "drift")
    _write_snapshot(repo, stamp="2026-08-26T11:22:53+00:00", values='"auto", "low"')
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "baseline")
    return repo


class TestDriftStepConfiguration:
    """Шаг сверки обязан смотреть на все три артефакта."""

    def test_schemas_snapshot_is_checked(self):
        """Исторический артефакт — модели категорий."""
        assert SCHEMAS_PATH in _drift_paths()

    def test_full_spec_snapshot_is_checked(self):
        """Из него берутся словари ENUM и диапазоны — без него сверка слепа."""
        assert FULL_SPEC_PATH in _drift_paths()

    def test_generated_package_is_checked(self):
        """Сгенерированные модули — то, что реально читает рантайм."""
        assert GENERATED_DIR in _drift_paths()

    def test_generated_at_is_ignored(self):
        """Метка времени меняется каждый прогон и не является дрейфом."""
        assert any("generated_at" in pattern for pattern in _ignore_patterns())


class TestDriftDetectionBehaviour:
    """Поведение записанной в workflow команды на настоящем репозитории."""

    def test_timestamp_only_change_is_not_drift(self, drift_repo: Path):
        """Пересчёт снапшота без изменений в документации не должен плодить PR."""
        _write_snapshot(drift_repo, stamp="2026-09-07T12:06:54+00:00", values='"auto", "low"')
        assert _has_drift(drift_repo) is False

    def test_changed_enum_vocabulary_is_drift(self, drift_repo: Path):
        """Новое значение в словаре функции обязано поднимать PR.

        Это и есть дефект, из-за которого ``sber_full_spec.json`` не
        диффился: добавленный Сбером ``quiet`` проходил мимо сверки, и
        наш ``FEATURE_ENUM_VALUES`` оставался старым.
        """
        _write_snapshot(drift_repo, stamp="2026-09-07T12:06:54+00:00", values='"auto", "low", "quiet"')
        assert _has_drift(drift_repo) is True

    def test_changed_schemas_snapshot_is_still_drift(self, drift_repo: Path):
        """Старая логика по ``sber_schemas.json`` не должна сломаться."""
        (drift_repo / SCHEMAS_PATH).write_text(
            '{\n  "light": {"features": ["on_off", "light_brightness"]}\n}\n', encoding="utf-8"
        )
        assert _has_drift(drift_repo) is True


class TestPullRequestStepIntact:
    """Логика создания PR должна остаться прежней."""

    def test_pr_step_still_gated_on_drift_output(self):
        """PR создаётся только когда шаг сверки сказал drift=true."""
        workflow = yaml.safe_load(WORKFLOW_FILE.read_text(encoding="utf-8"))
        steps = workflow["jobs"]["fetch-and-check"]["steps"]
        pr_steps = [s for s in steps if str(s.get("uses", "")).startswith("peter-evans/create-pull-request")]
        assert len(pr_steps) == 1
        assert pr_steps[0]["if"] == "steps.drift.outputs.drift == 'true'"
