#!/usr/bin/env python3
# ruff: noqa: T201  # CLI tool — print() is the intended interface
"""Fetch canonical Sber device schemas from developers.sber.ru.

The Sber C2C docs pages are client-side rendered (Next.js), so a plain
HTTP GET returns an empty shell.  This script uses Playwright headless
chromium to render each category page, extract the JSON <pre> block
containing the canonical model schema, and write a single snapshot
file that drives compliance tests.

Usage:
    pip install playwright
    playwright install chromium
    python tools/fetch_sber_schemas.py

Output:
    tests/hacs/__snapshots__/sber_schemas.json

CI runs this weekly.  Diff detection in ``sber-compliance`` workflow
creates a PR when Sber documentation changes upstream.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

try:
    from playwright.sync_api import TimeoutError as PlaywrightTimeout
    from playwright.sync_api import sync_playwright
except ImportError:
    print("ERROR: playwright not installed. Run: pip install playwright && playwright install chromium")
    sys.exit(1)

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
OUTPUT_FILE = Path(__file__).parent.parent / "tests" / "hacs" / "__snapshots__" / "sber_schemas.json"


def extract_schema_from_page(page, category: str) -> dict | None:
    """Render the category page, find the <pre> block matching ``category``.

    The docs pages have multiple <pre> blocks (model example, user device
    example, individual field examples).  We pick the one that parses as
    JSON AND has ``category == <expected>``.
    """
    url = f"{BASE_URL}/{category}"
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=20_000)
        page.wait_for_selector("pre", timeout=10_000)
    except PlaywrightTimeout:
        return None

    pre_blocks: list[str] = page.eval_on_selector_all("pre", "els => els.map(e => e.innerText)")

    for block in pre_blocks:
        text = block.strip()
        if not text.startswith("{"):
            continue
        # Sber docs sometimes include trailing commas which are invalid
        # JSON. Strip them before parsing.
        cleaned = re.sub(r",(\s*[}\]])", r"\1", text)
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            continue
        if data.get("category") == category:
            return _normalize_schema(data)
    return None


def _normalize_schema(raw: dict) -> dict:
    """Strip instance-specific fields so only the schema shape remains.

    The Sber docs example models include fictional ``id``, ``manufacturer``,
    ``model``, version strings that are not part of the schema contract.
    We only care about: category, features, allowed_values, dependencies.
    """
    return {
        "category": raw.get("category"),
        "features": sorted(raw.get("features", [])),
        "allowed_values": raw.get("allowed_values") or {},
        "dependencies": raw.get("dependencies") or {},
    }


def main() -> int:
    """Fetch schemas for all categories and write the snapshot file."""
    schemas: dict[str, dict | None] = {}
    failed: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
        )
        page = context.new_page()

        for idx, category in enumerate(CATEGORIES, start=1):
            print(f"[{idx:2d}/{len(CATEGORIES)}] Fetching {category}...", end=" ", flush=True)
            schema = extract_schema_from_page(page, category)
            if schema is None:
                print("MISSING")
                failed.append(category)
            else:
                features_count = len(schema["features"])
                av_count = len(schema["allowed_values"])
                print(f"OK ({features_count} features, {av_count} allowed_values)")
                schemas[category] = schema

        browser.close()

    # Deterministic output — sorted keys, stable indentation
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(
        json.dumps(schemas, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"\nWrote {len(schemas)} schemas to {OUTPUT_FILE}")

    if failed:
        print(f"Failed to fetch: {', '.join(failed)}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
