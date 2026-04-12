#!/usr/bin/env python3
# ruff: noqa: T201  # CLI tool — print() is the intended interface
"""Fetch canonical Sber device schemas + function catalog.

Renders every device category page and every function page on
developers.sber.ru (client-side rendered via Next.js — plain HTTP
returns an empty shell).  Builds two artifacts:

1. ``tests/hacs/__snapshots__/sber_schemas.json`` — per-category
   reference models (features, allowed_values, dependencies).
2. ``tests/hacs/__snapshots__/sber_full_spec.json`` — unified
   artifact containing every category + every function with type,
   range, usage and cross-references between them.

Usage:
    pip install playwright
    playwright install chromium
    python tools/fetch_sber_schemas.py

CI runs this weekly.  Diff detection in the ``sber-compliance``
workflow creates a PR when the documentation changes upstream.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

try:
    from playwright.sync_api import TimeoutError as PlaywrightTimeout
    from playwright.sync_api import sync_playwright
except ImportError:
    print("ERROR: playwright not installed. Run: pip install playwright && playwright install chromium")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# All 28 Sber device categories (must match CATEGORY_REQUIRED_FEATURES
# in custom_components/sber_mqtt_bridge/sber_models.py).
CATEGORIES: tuple[str, ...] = (
    "light",
    "led_strip",
    "relay",
    "socket",
    "tv",
    "intercom",
    "hvac_ac",
    "hvac_radiator",
    "hvac_heater",
    "hvac_boiler",
    "hvac_underfloor_heating",
    "hvac_fan",
    "hvac_air_purifier",
    "hvac_humidifier",
    "kettle",
    "curtain",
    "window_blind",
    "gate",
    "valve",
    "sensor_temp",
    "sensor_pir",
    "sensor_door",
    "sensor_water_leak",
    "sensor_smoke",
    "sensor_gas",
    "scenario_button",
    "vacuum_cleaner",
    "hub",
)

BASE_URL = "https://developers.sber.ru/docs/ru/smarthome/c2c"
SCHEMAS_FILE = Path(__file__).parent.parent / "tests" / "hacs" / "__snapshots__" / "sber_schemas.json"
FULL_SPEC_FILE = Path(__file__).parent.parent / "tests" / "hacs" / "__snapshots__" / "sber_full_spec.json"

# Links on /functions to exclude (structural pages, not functions)
_STRUCTURAL_LINKS = (
    "types",
    "structure",
    "structures",
    "cloud-to-cloud",
    "api",
    "allowed_values",
    "dependencies",
    "device",
    "devices",
    "model",
    "state",
    "value",
    "overview",
    "intro",
    "functions",
    "discovery",
    "migration",
    "auth",
    "mqtt",
    "rest",
    "examples",
    "faq",
)

# Function name regex in title: "Функция {name} | ..."
_FUNC_TITLE_RE = re.compile(r"Функция\s+([a-z_0-9]+)")

# Type declarations in function page text: "Тип данных: INTEGER(50,1000)" etc.
_TYPE_DECL_RE = re.compile(
    r"Тип данных:\s*([A-Z]+)(?:\s*\(([^)]+)\))?",
    flags=re.IGNORECASE,
)

# Category listing marker on function page
_CATEGORY_MARKER = "Устройства с этой функцией"

# Trailing commas in Sber JSON examples (not valid JSON) — strip before parsing
_TRAILING_COMMA_RE = re.compile(r",(\s*[}\]])")


# ---------------------------------------------------------------------------
# Category schema extraction
# ---------------------------------------------------------------------------


def _load_page(page, url: str) -> bool:
    """Navigate + wait for content.  Return True on success."""
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=20_000)
        page.wait_for_selector("pre, article", timeout=10_000)
    except PlaywrightTimeout:
        return False
    return True


def _parse_json_block(text: str) -> dict | None:
    """Parse a <pre> block that should be a JSON object (lenient)."""
    text = text.strip()
    if not text.startswith("{"):
        return None
    cleaned = _TRAILING_COMMA_RE.sub(r"\1", text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return None


def _normalize_category_schema(raw: dict) -> dict:
    """Strip instance-specific fields — keep only schema contract."""
    return {
        "category": raw.get("category"),
        "features": sorted(raw.get("features", [])),
        "allowed_values": raw.get("allowed_values") or {},
        "dependencies": raw.get("dependencies") or {},
    }


def extract_category_schema(page, category: str) -> dict | None:
    """Render a category page, pick the <pre> whose JSON category matches."""
    if not _load_page(page, f"{BASE_URL}/{category}"):
        return None
    pre_blocks: list[str] = page.eval_on_selector_all("pre", "els => els.map(e => e.innerText)")
    for block in pre_blocks:
        data = _parse_json_block(block)
        if data and data.get("category") == category:
            return _normalize_category_schema(data)
    return None


# ---------------------------------------------------------------------------
# Function catalog extraction
# ---------------------------------------------------------------------------


def list_function_slugs(page) -> list[str]:
    """Get the list of function page slugs from /functions index."""
    if not _load_page(page, f"{BASE_URL}/functions"):
        return []
    hrefs: list[str] = page.eval_on_selector_all(
        'a[href*="/smarthome/c2c/"]',
        "els => els.map(a => a.getAttribute('href'))",
    )
    slugs: set[str] = set()
    prefix = "/docs/ru/smarthome/c2c/"
    for href in hrefs:
        if not href or not href.startswith(prefix):
            continue
        slug = href[len(prefix) :].strip("/")
        if not slug or slug in _STRUCTURAL_LINKS:
            continue
        if slug in CATEGORIES:
            continue  # Category pages, not function pages
        slugs.add(slug)
    return sorted(slugs)


def extract_function_spec(page, slug: str) -> dict | None:
    """Parse a single function page — type, range, usage, categories."""
    if not _load_page(page, f"{BASE_URL}/{slug}"):
        return None

    title = page.title()
    name_match = _FUNC_TITLE_RE.search(title)
    # URL slugs sometimes use dashes; the canonical function name uses underscores.
    name = name_match.group(1) if name_match else slug.replace("-", "_")

    article_text: str = page.eval_on_selector(
        "article, main",
        "el => el ? el.innerText : ''",
    )

    type_match = _TYPE_DECL_RE.search(article_text)
    type_name: str | None = None
    range_str: str | None = None
    if type_match:
        type_name = type_match.group(1).upper()
        range_str = (type_match.group(2) or "").strip() or None

    categories_used = _parse_categories_from_text(article_text)

    pre_blocks: list[str] = page.eval_on_selector_all("pre", "els => els.map(e => e.innerText)")

    return {
        "name": name,
        "type": type_name,
        "range": range_str,
        "used_in_categories": sorted(categories_used),
        "examples": [b.strip() for b in pre_blocks if b.strip()],
    }


def _parse_categories_from_text(text: str) -> set[str]:
    """Extract category names from the 'Устройства с этой функцией' section."""
    idx = text.find(_CATEGORY_MARKER)
    if idx == -1:
        return set()
    tail = text[idx + len(_CATEGORY_MARKER) :]
    # Next section is usually "Примеры голосовых команд"
    end = tail.find("Примеры")
    if end != -1:
        tail = tail[:end]
    mentioned: set[str] = set()
    for cat in CATEGORIES:
        pattern = rf"\b{re.escape(cat)}\b"
        if re.search(pattern, tail):
            mentioned.add(cat)
    return mentioned


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def _write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    """Fetch all categories + functions, write two snapshots."""
    categories: dict[str, dict] = {}
    category_failures: list[str] = []

    functions: dict[str, dict] = {}
    function_failures: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
        )
        page = context.new_page()

        # Phase 1: category schemas
        print(f"=== Phase 1: {len(CATEGORIES)} category schemas ===")
        for idx, category in enumerate(CATEGORIES, start=1):
            print(f"[{idx:2d}/{len(CATEGORIES)}] Fetching category {category}...", end=" ", flush=True)
            schema = extract_category_schema(page, category)
            if schema is None:
                print("MISSING")
                category_failures.append(category)
            else:
                print(f"OK ({len(schema['features'])} features)")
                categories[category] = schema

        # Phase 2: function catalog
        print("\n=== Phase 2: function catalog ===")
        function_slugs = list_function_slugs(page)
        print(f"Discovered {len(function_slugs)} function pages")
        for idx, slug in enumerate(function_slugs, start=1):
            print(f"[{idx:3d}/{len(function_slugs)}] Fetching function {slug}...", end=" ", flush=True)
            spec = extract_function_spec(page, slug)
            if spec is None or spec.get("type") is None:
                print("MISSING")
                function_failures.append(slug)
                continue
            name = spec["name"]
            # Drop oversized example list from functions snapshot
            spec = {k: v for k, v in spec.items() if k != "examples"}
            functions[name] = spec
            print(f"OK ({spec['type']})")

        browser.close()

    # Write per-category snapshot (backward-compatible with existing tests)
    _write_json(SCHEMAS_FILE, categories)
    print(f"\nWrote {len(categories)} category schemas to {SCHEMAS_FILE}")

    # Write unified full spec
    full_spec = {
        "generated_at": datetime.now(UTC).isoformat(),
        "source": BASE_URL,
        "categories": categories,
        "functions": functions,
    }
    _write_json(FULL_SPEC_FILE, full_spec)
    print(f"Wrote unified spec ({len(categories)} categories, {len(functions)} functions) to {FULL_SPEC_FILE}")

    if category_failures or function_failures:
        print()
        if category_failures:
            print(f"Failed categories ({len(category_failures)}): {', '.join(category_failures)}")
        if function_failures:
            print(f"Failed functions ({len(function_failures)}): {', '.join(function_failures[:10])}...")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
