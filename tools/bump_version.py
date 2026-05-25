#!/usr/bin/env python3
"""Bump project version atomically across every required location.

Project rule (see ``CLAUDE.md``): the version string lives in four places
and MUST stay in sync.

  1. ``pyproject.toml``                                          (``version = "X"``)
  2. ``custom_components/sber_mqtt_bridge/manifest.json``        (``"version": "X"``)
  3. ``custom_components/sber_mqtt_bridge/sber_protocol.py``     (``VERSION = "X"``)
  4. ``CHANGELOG.md``                                            (``## [X] - YYYY-MM-DD``)

Usage::

    tools/bump_version.py --current                     # print current version
    tools/bump_version.py patch                         # 1.39.7 → 1.39.8
    tools/bump_version.py minor                         # 1.39.7 → 1.40.0
    tools/bump_version.py major                         # 1.39.7 → 2.0.0
    tools/bump_version.py 1.40.0b1                      # explicit (pre-release ok)
    tools/bump_version.py patch --dry-run               # preview only
    tools/bump_version.py patch --no-changelog          # skip CHANGELOG edit
    tools/bump_version.py patch --date 2026-05-25       # override release date

The script refuses to run if the four files are out of sync at the start —
fix that by hand (or re-run the previous bump) before retrying.

CHANGELOG behaviour: renames the existing ``## [Unreleased]`` heading to
``## [NEW] - <date>`` and inserts a fresh empty ``## [Unreleased]`` above it.
If you pass ``--no-changelog`` the file is left untouched.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent.parent

PYPROJECT = ROOT / "pyproject.toml"
MANIFEST = ROOT / "custom_components" / "sber_mqtt_bridge" / "manifest.json"
PROTOCOL = ROOT / "custom_components" / "sber_mqtt_bridge" / "sber_protocol.py"
CHANGELOG = ROOT / "CHANGELOG.md"

# Matches PEP 440-ish: MAJOR.MINOR.PATCH with optional pre-release suffix
# (b1, a1, rc1, .dev1, etc.). We don't enforce strict PEP 440 — the existing
# project uses things like "1.39.6b3".
VERSION_RE = re.compile(
    r"\d+\.\d+\.\d+"          # MAJOR.MINOR.PATCH
    r"(?:[ab]\d+|rc\d+|\.dev\d+|-(?:alpha|beta|rc)\d*)?"  # optional pre-release
)


@dataclass
class FileSpec:
    """A single file that holds the version string."""

    path: Path
    pattern: re.Pattern[str]
    template: Callable[[str], str]

    def read_version(self) -> str:
        text = self.path.read_text(encoding="utf-8")
        match = self.pattern.search(text)
        if not match:
            raise SystemExit(
                f"could not locate version in {self.path.relative_to(ROOT)} "
                f"(pattern: {self.pattern.pattern!r})"
            )
        return match.group(1)

    def write_version(self, new_version: str) -> None:
        text = self.path.read_text(encoding="utf-8")
        new_text, n = self.pattern.subn(self.template(new_version), text, count=1)
        if n != 1:
            raise SystemExit(
                f"failed to replace version in {self.path.relative_to(ROOT)}"
            )
        self.path.write_text(new_text, encoding="utf-8")


# Note: each pattern has exactly one capture group around the version string.
SPECS: list[FileSpec] = [
    FileSpec(
        path=PYPROJECT,
        pattern=re.compile(r'^version = "([^"]+)"', re.MULTILINE),
        template=lambda v: f'version = "{v}"',
    ),
    FileSpec(
        path=MANIFEST,
        pattern=re.compile(r'"version"\s*:\s*"([^"]+)"'),
        template=lambda v: f'"version": "{v}"',
    ),
    FileSpec(
        path=PROTOCOL,
        pattern=re.compile(r'^VERSION = "([^"]+)"', re.MULTILINE),
        template=lambda v: f'VERSION = "{v}"',
    ),
]


def detect_current_version() -> str:
    """Read every spec; abort if they disagree."""
    versions = {spec.path: spec.read_version() for spec in SPECS}
    distinct = set(versions.values())
    if len(distinct) != 1:
        report = "\n".join(
            f"  {p.relative_to(ROOT)}: {v}" for p, v in versions.items()
        )
        raise SystemExit(
            "version files are out of sync — fix manually before bumping:\n"
            + report
        )
    return distinct.pop()


def parse_semver(v: str) -> tuple[int, int, int, str]:
    """Return (MAJOR, MINOR, PATCH, pre-release-suffix)."""
    m = re.match(
        r"^(\d+)\.(\d+)\.(\d+)"
        r"((?:[ab]\d+|rc\d+|\.dev\d+|-(?:alpha|beta|rc)\d*)?)$",
        v,
    )
    if not m:
        raise SystemExit(f"can't parse version {v!r} as semver")
    return int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(4) or ""


def compute_next_version(current: str, action: str) -> str:
    """Apply patch/minor/major/explicit to current."""
    if VERSION_RE.fullmatch(action):
        return action  # explicit version
    major, minor, patch, _suffix = parse_semver(current)
    if action == "patch":
        return f"{major}.{minor}.{patch + 1}"
    if action == "minor":
        return f"{major}.{minor + 1}.0"
    if action == "major":
        return f"{major + 1}.0.0"
    raise SystemExit(
        f"unknown action {action!r}: expected patch/minor/major or X.Y.Z"
    )


def update_changelog(new_version: str, release_date: str, *, dry_run: bool) -> bool:
    """Promote the [Unreleased] section to the new release.

    Returns True if the file was (or would be) modified.
    """
    if not CHANGELOG.exists():
        print(f"warn: {CHANGELOG.relative_to(ROOT)} not found — skipping")
        return False

    text = CHANGELOG.read_text(encoding="utf-8")
    # Match the [Unreleased] heading at start of line. Be tolerant of trailing
    # whitespace; require it to exist exactly once.
    pattern = re.compile(r"^## \[Unreleased\][^\n]*\n", re.MULTILINE)
    matches = list(pattern.finditer(text))
    if not matches:
        print(
            "warn: CHANGELOG has no '## [Unreleased]' section — skipping. "
            "Add it manually or rerun with --no-changelog.",
            file=sys.stderr,
        )
        return False
    if len(matches) > 1:
        raise SystemExit(
            "CHANGELOG has multiple '## [Unreleased]' sections — fix manually."
        )

    replacement = (
        f"## [Unreleased]\n\n"
        f"## [{new_version}] - {release_date}\n"
    )
    new_text = pattern.sub(replacement, text, count=1)

    if not dry_run:
        CHANGELOG.write_text(new_text, encoding="utf-8")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Bump the project version in pyproject.toml, manifest.json, "
        "sber_protocol.py, and CHANGELOG.md atomically.",
    )
    ap.add_argument(
        "action",
        nargs="?",
        help="patch | minor | major | explicit version (e.g. 1.40.0b1)",
    )
    ap.add_argument(
        "--current",
        action="store_true",
        help="just print the current version and exit",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="show what would change without writing",
    )
    ap.add_argument(
        "--no-changelog",
        action="store_true",
        help="don't touch CHANGELOG.md",
    )
    ap.add_argument(
        "--date",
        default=date.today().isoformat(),
        help="release date for CHANGELOG entry (default: today, YYYY-MM-DD)",
    )
    args = ap.parse_args()

    current = detect_current_version()

    if args.current:
        print(current)
        return 0

    if not args.action:
        ap.error("action is required (patch | minor | major | X.Y.Z)")

    new_version = compute_next_version(current, args.action)
    if new_version == current:
        raise SystemExit(f"version is already {current} — nothing to do")

    print(f"current: {current}")
    print(f"new:     {new_version}")
    if args.dry_run:
        print("(dry-run — no files written)")
    print()

    for spec in SPECS:
        rel = spec.path.relative_to(ROOT)
        print(f"  {rel}: {current} -> {new_version}")
        if not args.dry_run:
            spec.write_version(new_version)

    if not args.no_changelog:
        touched = update_changelog(new_version, args.date, dry_run=args.dry_run)
        if touched:
            print(f"  {CHANGELOG.relative_to(ROOT)}: [Unreleased] -> [{new_version}] - {args.date}")

    print()
    if args.dry_run:
        print("dry-run complete; rerun without --dry-run to apply.")
    else:
        print(f"bumped to {new_version}. Review changes, then:")
        print(f"  git add -p")
        print(f"  git commit -m 'chore: release v{new_version}'")
        print(f"  git tag v{new_version} && git push --follow-tags")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
