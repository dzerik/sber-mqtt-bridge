#!/usr/bin/env python3
# ruff: noqa: T201
"""Generate Sber-derived Python modules from the unified spec artifact.

Reads ``tests/hacs/__snapshots__/sber_full_spec.json`` and writes three
modules under ``custom_components/sber_mqtt_bridge/_generated/``:

- ``feature_types.py``  — ``FEATURE_TYPES: dict[str, str]``
  (feature name → Sber value type)
- ``category_features.py`` — ``CATEGORY_REFERENCE_FEATURES:
  dict[str, frozenset[str]]`` (all features Sber lists per category)
- ``__init__.py`` — re-exports + spec provenance constants

Safety guarantees:

1. **Generated files are committed** — runtime never reads the JSON
   spec, only the committed ``.py`` modules.  Portal outages, spec
   corruption, or scraper bugs cannot break the production bridge.
2. **Atomic writes** — we write to a temp file in the same directory
   and ``os.replace`` into place, so interrupted codegen can never
   leave half-written files.
3. **Strict spec validation** — before any write, we validate the
   input structure.  On malformed spec, we abort with a clear error
   and leave committed files untouched.
4. **``--check`` mode** — CI runs codegen into a temp dir and diffs
   against committed files.  A mismatch fails the build without
   touching anything.
5. **No surprising deletions** — we only generate the modules listed
   above, never clean up unrelated files under ``_generated/``.

Usage:
    python tools/codegen.py          # regenerate, overwrite committed files
    python tools/codegen.py --check  # CI mode: exit 1 if out of date
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from textwrap import dedent
from typing import Any

SPEC_FILE = Path(__file__).parent.parent / "tests" / "hacs" / "__snapshots__" / "sber_full_spec.json"
OUTPUT_DIR = Path(__file__).parent.parent / "custom_components" / "sber_mqtt_bridge" / "_generated"

VALID_TYPES = frozenset({"BOOL", "INTEGER", "FLOAT", "STRING", "ENUM", "COLOUR"})

HEADER = '''"""AUTO-GENERATED from tests/hacs/__snapshots__/sber_full_spec.json.

DO NOT EDIT BY HAND.  Regenerate with:

    python tools/codegen.py

Source: {source}
Spec generated at: {generated_at}
"""

from __future__ import annotations
'''


# ---------------------------------------------------------------------------
# Spec loading + validation
# ---------------------------------------------------------------------------


class SpecValidationError(RuntimeError):
    """Spec structure is malformed — refuse to generate."""


def load_spec(path: Path) -> dict[str, Any]:
    """Load and validate the unified Sber spec."""
    if not path.exists():
        raise SpecValidationError(f"Spec file missing: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SpecValidationError(f"Spec is not valid JSON: {exc}") from exc

    for key in ("source", "generated_at", "categories", "functions"):
        if key not in data:
            raise SpecValidationError(f"Spec missing required top-level key: {key!r}")

    if not isinstance(data["functions"], dict) or not data["functions"]:
        raise SpecValidationError("Spec 'functions' must be a non-empty dict")
    if not isinstance(data["categories"], dict) or not data["categories"]:
        raise SpecValidationError("Spec 'categories' must be a non-empty dict")

    for name, spec in data["functions"].items():
        ftype = spec.get("type")
        if ftype not in VALID_TYPES:
            raise SpecValidationError(
                f"Function {name!r} has invalid type {ftype!r} (expected one of {sorted(VALID_TYPES)})"
            )

    for category, schema in data["categories"].items():
        features = schema.get("features")
        if not isinstance(features, list):
            raise SpecValidationError(f"Category {category!r} features must be a list, got {type(features)}")

    return data


# ---------------------------------------------------------------------------
# Module generators (pure functions — return file content, don't write)
# ---------------------------------------------------------------------------


def render_feature_types(spec: dict) -> str:
    """Render feature_types.py content."""
    header = HEADER.format(source=spec["source"], generated_at=spec["generated_at"]).rstrip()
    functions = spec["functions"]
    lines = [header, "", "FEATURE_TYPES: dict[str, str] = {"]
    for name in sorted(functions):
        ftype = functions[name]["type"]
        lines.append(f'    "{name}": "{ftype}",')
    lines.append("}")
    lines.append('"""Feature name → Sber value type. Source: developers.sber.ru/docs/ru/smarthome/c2c/functions."""')
    lines.append("")
    return "\n".join(lines)


def render_category_features(spec: dict) -> str:
    """Render category_features.py content."""
    header = HEADER.format(source=spec["source"], generated_at=spec["generated_at"]).rstrip()
    categories = spec["categories"]
    lines = [header, "", "CATEGORY_REFERENCE_FEATURES: dict[str, frozenset[str]] = {"]
    for category in sorted(categories):
        features = sorted(categories[category].get("features", []))
        if features:
            formatted = ", ".join(f'"{f}"' for f in features)
            lines.append(f'    "{category}": frozenset({{{formatted}}}),')
        else:
            lines.append(f'    "{category}": frozenset(),')
    lines.append("}")
    lines.append(
        dedent(
            '''"""All features listed in the Sber reference model for each category.

This is the *widest* known-valid feature set per category.  Use for
compliance checks: features we emit outside this set are unknown to
Sber cloud and likely cause silent rejection (see the TV allowed_values
bug that motivated this module)."""
            ''',
        ).strip()
    )
    lines.append("")
    return "\n".join(lines)


def render_init(spec: dict) -> str:
    """Render __init__.py content."""
    header = HEADER.format(source=spec["source"], generated_at=spec["generated_at"]).rstrip()
    body = dedent(
        '''

        from .category_features import CATEGORY_REFERENCE_FEATURES
        from .feature_types import FEATURE_TYPES

        __all__ = [
            "CATEGORY_REFERENCE_FEATURES",
            "FEATURE_TYPES",
            "SPEC_GENERATED_AT",
            "SPEC_SOURCE",
        ]

        SPEC_SOURCE: str = "{source}"
        """Upstream documentation URL used to generate this package."""

        SPEC_GENERATED_AT: str = "{generated_at}"
        """ISO 8601 timestamp when the spec snapshot was fetched."""
        '''
    ).format(source=spec["source"], generated_at=spec["generated_at"])
    return header + body


# ---------------------------------------------------------------------------
# Atomic I/O + check mode
# ---------------------------------------------------------------------------


def atomic_write(path: Path, content: str) -> None:
    """Write content to path via temp file + os.replace (no partial writes)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path_str = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent), text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.replace(tmp_path_str, path)
    except BaseException:
        Path(tmp_path_str).unlink(missing_ok=True)
        raise


def ruff_format_content(content: str, path: Path) -> str:
    """Run content through ``ruff format`` via stdin, keeping input on failure."""
    try:
        result = subprocess.run(
            ["ruff", "format", "-", "--stdin-filename", str(path)],
            input=content,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        # ruff not available or failed — keep input unchanged.
        return content


def diff_against_committed(path: Path, expected: str) -> str:
    """Return unified diff between committed file and expected content (empty if match)."""
    actual = path.read_text(encoding="utf-8") if path.exists() else ""
    if actual == expected:
        return ""
    return "\n".join(
        difflib.unified_diff(
            actual.splitlines(),
            expected.splitlines(),
            fromfile=f"committed:{path.name}",
            tofile=f"generated:{path.name}",
            lineterm="",
        )
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

TARGETS: tuple[tuple[str, str], ...] = (
    ("feature_types.py", "render_feature_types"),
    ("category_features.py", "render_category_features"),
    ("__init__.py", "render_init"),
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="CI mode: diff against committed files, exit 1 on mismatch, write nothing",
    )
    args = parser.parse_args(argv)

    try:
        spec = load_spec(SPEC_FILE)
    except SpecValidationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    renderers = {
        "render_feature_types": render_feature_types,
        "render_category_features": render_category_features,
        "render_init": render_init,
    }

    drift_found = False
    for filename, renderer_name in TARGETS:
        target_path = OUTPUT_DIR / filename
        raw_content = renderers[renderer_name](spec)
        # Run through ruff for canonical formatting so drift-check is stable.
        expected = ruff_format_content(raw_content, target_path)
        if args.check:
            diff = diff_against_committed(target_path, expected)
            if diff:
                drift_found = True
                print(f"DRIFT: {target_path}")
                print(diff)
            else:
                print(f"OK:    {target_path}")
        else:
            atomic_write(target_path, expected)
            print(f"WROTE: {target_path}")

    if args.check and drift_found:
        print(
            "\nGenerated files are out of date.  Run: python tools/codegen.py",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
