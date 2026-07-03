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
import urllib.error
import urllib.request
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

# All 29 Sber device categories (must match CATEGORY_REQUIRED_FEATURES
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
    "sensor_air",  # 2026-07: датчик качества воздуха (co2/pm/tvoc/hcho)
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
    "common-error",
    "logging",
    "testing",
    "webhook",
    "authorization",
    "bridge",
    "ca",
    "error",
)

# Function name regex in title: "Функция {name} | ..."
_FUNC_TITLE_RE = re.compile(r"Функция\s+([a-z_0-9]+)")

# Type declarations in function page text: "Тип данных: INTEGER(50,1000)" etc.
_TYPE_DECL_RE = re.compile(
    r"Тип данных:\s*([A-Z]+)(?:\s*\(([^)]+)\))?",
    flags=re.IGNORECASE,
)

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
    """Render a category page, pick the <pre> whose JSON category matches.

    Also extracts the "Доступные функции устройства" table, which marks
    each feature as obligatory (``✔︎`` in column 2) or optional.  The
    obligatory set is the strictest feature contract per Sber's own docs.
    """
    if not _load_page(page, f"{BASE_URL}/{category}"):
        return None

    pre_blocks: list[str] = page.eval_on_selector_all("pre", "els => els.map(e => e.innerText)")
    schema: dict | None = None
    for block in pre_blocks:
        data = _parse_json_block(block)
        if data and data.get("category") == category:
            schema = _normalize_category_schema(data)
            break
    if schema is None:
        return None

    # Extract obligatory + conditional features from the "Доступные функции" table.
    # obligatory  = ✔︎  (strict mandatory)
    # conditional = ✔︎* (at least one of the starred set must be present)
    table_rows = _extract_features_table(page)
    if table_rows:
        schema["all_features"] = sorted({row["feature"] for row in table_rows if row["feature"]})
        schema["obligatory"] = sorted({row["feature"] for row in table_rows if row.get("obligatory")})
        schema["conditional"] = sorted({row["feature"] for row in table_rows if row.get("conditional")})
    else:
        # Fallback: no table found (rare — e.g. hub page).  Treat the
        # reference features as all-features and leave obligatory empty.
        schema["all_features"] = schema["features"]
        schema["obligatory"] = []
        schema["conditional"] = []
    return schema


_TABLE_EXTRACTOR_JS = """
() => {
  const headings = Array.from(document.querySelectorAll('h2'));
  const target = headings.find(h => h.innerText.includes('Доступные функции'));
  if (!target) return [];
  let el = target.nextElementSibling;
  while (el && el.tagName !== 'TABLE') el = el.nextElementSibling;
  if (!el) return [];
  const rows = Array.from(el.querySelectorAll('tr'));
  return rows.slice(1).map(tr => {
    const cells = Array.from(tr.querySelectorAll('td')).map(td => td.innerText.trim());
    const marker = cells[1] || '';
    // Sber uses ✔︎ for strict mandatory and ✔︎* for "at least one of the
    // starred features must be present" (conditional mandatory).
    // Split the two so validators can enforce the strict set without
    // over-rejecting devices that expose only the conditional subset.
    const hasCheck = /[✔✓]/.test(marker);
    const isStrict = hasCheck && !marker.includes('*');
    const isConditional = hasCheck && marker.includes('*');
    return {
      feature: cells[0] || '',
      obligatory: isStrict,
      conditional: isConditional,
    };
  });
}
"""


def _extract_features_table(page) -> list[dict]:
    """Return rows from the 'Доступные функции устройства' table (may be empty)."""
    try:
        return page.evaluate(_TABLE_EXTRACTOR_JS)
    except Exception:  # noqa: BLE001 — best-effort extraction
        return []


# ---------------------------------------------------------------------------
# Category index drift check
# ---------------------------------------------------------------------------


def discover_advertised_categories(page) -> set[str] | None:
    """Pull the set of category slugs advertised on the `/devices` index page.

    Returns the set, or ``None`` if the page failed to load (treated as
    soft-fail by the caller — drift check is skipped, main extraction
    continues). Used to detect when Sber adds or removes a category
    upstream so the hardcoded :data:`CATEGORIES` tuple can be updated.
    """
    if not _load_page(page, f"{BASE_URL}/devices"):
        return None
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
        if not slug or slug == "devices" or slug in _STRUCTURAL_LINKS:
            continue
        # Categories are flat slugs; nested paths point to functions/sub-docs.
        if "/" in slug:
            continue
        slugs.add(slug)
    return slugs


_MAIN_JS_URL_RE = re.compile(
    r'https://media\.sberdevices\.ru/bsm-docs/[^"\s]+/main\.[a-f0-9]+\.js'
)
_MDX_SLUG_RE = re.compile(
    r'"@site/docs/ru/smarthome/c2c/([a-z0-9_-]+)\.mdx"'
)


def discover_slugs_via_main_js(user_agent: str, timeout: int = 30) -> set[str] | None:
    """Extract every ``c2c/*.mdx`` slug embedded in the Docusaurus webpack bundle.

    The docs site is Docusaurus v3 — every route is registered inside
    ``main.<hash>.js`` as a chunk-map entry pointing at ``@site/docs/…mdx``.
    Reading that map is one HTTP round-trip (5–6 MB, plain ``urllib``)
    versus a full Playwright browser render. It surfaces categories AND
    function pages AND structural pages in one go.

    Returns None on any fetch failure (missing HTML, unresolvable main.js
    URL, network error) so callers can treat this as an optional signal.

    MVP scope: kebab-case slugs (all structural pages like ``api-brief``,
    ``account-linking``) are filtered out. Distinguishing category vs
    function among the remaining snake_case + single-word slugs is left
    to the caller, which knows the current CATEGORIES set + the previous
    snapshot's function list.
    """

    def _get(url: str) -> str | None:
        req = urllib.request.Request(url, headers={"User-Agent": user_agent})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except (urllib.error.URLError, TimeoutError, OSError):
            return None

    # Any real docs page will link the current main.js — /devices is fine
    # and matches Phase 0's own probe.
    html = _get(f"{BASE_URL}/devices")
    if not html:
        return None
    m = _MAIN_JS_URL_RE.search(html)
    if not m:
        return None
    main_js = _get(m.group(0))
    if not main_js:
        return None

    slugs = set(_MDX_SLUG_RE.findall(main_js))
    # Kebab-case slugs on this site are structural pages (api-*, account-*,
    # error-*, …) — drop them so only category/function candidates remain.
    return {s for s in slugs if "-" not in s}


def report_mainjs_drift(slugs: set[str] | None, known_functions: set[str]) -> None:
    """Print candidates for new categories/functions surfaced by main.js.

    Compares the main.js slug set against the hardcoded :data:`CATEGORIES`
    and the ``known_functions`` set (typically read from the previous
    snapshot). Slugs that aren't recognised as any of these — and aren't
    on a small list of well-known structural pages — get printed as
    ``? <slug>`` so the maintainer can decide if it's a new category,
    new function, or just another docs page.

    MVP: no auto-classification into category-vs-function. That would
    need scraping the /devices index anyway, which is exactly what the
    Playwright-based Phase 0 already does.
    """
    if slugs is None:
        print("WARNING: main.js unreachable — MVP slug discovery skipped")
        return
    # Structural pages (login guides, error refs, api reference, …) are
    # already enumerated in _STRUCTURAL_LINKS at module-scope. Reuse it so
    # updates land in one place instead of drifting between two lists.
    structural = frozenset(_STRUCTURAL_LINKS)
    unknown = slugs - set(CATEGORIES) - known_functions - structural
    print(f"main.js manifest carries {len(slugs)} non-kebab c2c slugs (all discovery, no Playwright)")
    if not unknown:
        print("OK: every slug already accounted for by CATEGORIES + snapshot functions")
        return
    print(f"MAYBE-NEW: {len(unknown)} slug(s) not yet known to this tool:")
    for slug in sorted(unknown):
        # Distinguishing category vs function without extra fetches is
        # imperfect, but presence of an underscore + a common prefix is a
        # strong hint of category (sensor_air, hvac_*, etc.).
        hint = "category?" if slug.startswith(("sensor_", "hvac_", "light_", "scenario_")) else "function?"
        print(f"  ? {slug:35s} ({hint})")


def report_category_drift(advertised: set[str] | None) -> bool:
    """Compare advertised categories with hardcoded :data:`CATEGORIES`.

    Prints OK / WARNING. Returns ``True`` if no drift (or check skipped),
    ``False`` if additions or removals detected.
    """
    if advertised is None:
        print("WARNING: /devices index unreachable — category drift check skipped")
        return True
    known = set(CATEGORIES)
    new = advertised - known
    removed = known - advertised
    if not new and not removed:
        print(f"OK: all {len(known)} advertised categories match CATEGORIES")
        return True
    if new:
        suffix = "y" if len(new) == 1 else "ies"
        print(f"WARNING: {len(new)} new categor{suffix} on Sber docs:")
        for slug in sorted(new):
            print(f"  + {slug}")
        print("  Action: add to CATEGORIES in this file AND to CATEGORY_REQUIRED_FEATURES in sber_models.py")
    if removed:
        suffix = "y" if len(removed) == 1 else "ies"
        print(f"WARNING: {len(removed)} categor{suffix} no longer advertised:")
        for slug in sorted(removed):
            print(f"  - {slug}")
    return False


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
    """Parse a single function page — name, type, range.

    ``used_in_categories`` is deliberately NOT extracted from the function
    page (see :func:`build_used_in_categories`).  The function's
    "Устройства с этой функцией" section is inconsistent — some pages omit
    it, others word the surrounding section differently — so we invert the
    graph from the per-category "Доступные функции" tables, which are the
    canonical source of truth.
    """
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

    pre_blocks: list[str] = page.eval_on_selector_all("pre", "els => els.map(e => e.innerText)")

    return {
        "name": name,
        "type": type_name,
        "range": range_str,
        "examples": [b.strip() for b in pre_blocks if b.strip()],
    }


def build_used_in_categories(categories: dict[str, dict]) -> dict[str, list[str]]:
    """Invert ``categories[X].all_features`` into ``feature → [category, …]``.

    This is the authoritative source of the feature↔category link. Reading
    it off the function page (previously via ``_parse_categories_from_text``)
    was unreliable — several Sber pages either omitted the section or moved
    it under a different heading, causing common features like
    ``temperature`` / ``humidity`` / ``signal_strength`` to appear as
    orphaned in the snapshot.

    Args:
        categories: The per-category schemas as returned by
            :func:`extract_category_schema`.

    Returns:
        Mapping ``feature_name → sorted list of category slugs`` covering
        every feature seen in any category's ``all_features``.
    """
    used: dict[str, set[str]] = {}
    for cat_name, cat_schema in categories.items():
        for feature in cat_schema.get("all_features", ()):
            used.setdefault(feature, set()).add(cat_name)
    return {feat: sorted(cats) for feat, cats in used.items()}


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

        # Phase 0: detect drift between hardcoded CATEGORIES and upstream
        # /devices index. Soft-warning only — extraction continues either way.
        print("=== Phase 0: category index drift check ===")
        advertised = discover_advertised_categories(page)
        report_category_drift(advertised)
        print()

        # Phase 0b: MVP browserless discovery via main.js webpack manifest.
        # See discover_slugs_via_main_js() for rationale — this surfaces
        # BOTH new categories and new function pages in a single HTTP hop.
        print("=== Phase 0b: main.js manifest sweep (no browser) ===")
        # Seed "known functions" from the previously-committed snapshot so
        # we don't re-flag every existing function on a fresh checkout.
        known_functions: set[str] = set()
        if FULL_SPEC_FILE.exists():
            try:
                prev = json.loads(FULL_SPEC_FILE.read_text(encoding="utf-8"))
                known_functions = set((prev.get("functions") or {}).keys())
            except (json.JSONDecodeError, OSError):
                pass
        slugs_from_bundle = discover_slugs_via_main_js(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) fetch_sber_schemas",
        )
        report_mainjs_drift(slugs_from_bundle, known_functions)
        print()

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

    # Phase 3: invert per-category tables into the feature → categories index
    # (see build_used_in_categories() for why this is authoritative).
    print("\n=== Phase 3: build feature → category inverse index ===")
    used_in = build_used_in_categories(categories)
    orphans_in_catalog: list[str] = []
    for feat_name, feat_spec in functions.items():
        feat_spec["used_in_categories"] = used_in.get(feat_name, [])
    # Features that appear in category tables but have no catalog page are
    # surfaced as a warning — usually harmless (Sber adds the row before
    # publishing the per-function page) but worth flagging so it doesn't
    # go unnoticed.
    for feat_name in sorted(used_in):
        if feat_name not in functions:
            orphans_in_catalog.append(feat_name)
    if orphans_in_catalog:
        print(f"WARNING: {len(orphans_in_catalog)} feature(s) used by categories but missing from /functions catalog:")
        for feat in orphans_in_catalog:
            print(f"  ? {feat}  used_in={used_in[feat]}")
    else:
        print(f"OK: every feature used by categories has a catalog entry ({len(used_in)} features linked)")

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
