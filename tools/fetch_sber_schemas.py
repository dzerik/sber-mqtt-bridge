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

import contextlib
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

# One accepted value of an ENUM function, as the page words it:
#   "auto — скорость меняется автоматически."
# The value itself is a protocol slug; "+" and "-" are real ones (tv.source).
_ENUM_VALUE_RE = re.compile(r"^([a-z0-9_]+|\+|-)\s+—\s+\S", flags=re.MULTILINE)

# The heading that ends the vocabulary and starts the category list.  Its
# entries look exactly like enum values ("hvac_ac — кондиционеры."), so the
# scan MUST stop here or every category name becomes a fake enum value.
_ENUM_STOP_MARKER = "Устройства с этой функцией"

# Where the vocabulary starts.  Everything above it is prose about the type
# and the usage mode, which never carries the "value — description" shape.
_ENUM_START_MARKER = "Назначение:"

# "Способ использования: хранит состояние устройства и может менять его."
# Always the first line of a function page, above "Назначение:".
_USAGE_DECL_RE = re.compile(r"Способ использования:\s*([^\n]+)")

USAGE_STATE_READ_WRITE = "state_read_write"
"""Feature holds device state and Sber may change it (the common case)."""

USAGE_STATE_READ_ONLY = "state_read_only"
"""Feature holds device state but is reported only — no command accepted."""

USAGE_COMMAND_ONLY = "command_only"
"""Feature carries no state at all: it exists purely to accept a command.

Such a feature must be *declared* by the device yet never appears in a
state publish, which is exactly why the obligatory/conditional checks
have to run against declared features rather than the payload.
"""

USAGE_EVENT_ONLY = "event_only"
"""Feature notifies that something happened; it cannot be commanded.

Only ``pir`` is worded this way today — it is sent when motion is
detected and stays silent otherwise, so requiring it in every publish
reports every idle motion sensor as broken (issue #61).
"""

# Sber words the usage line in exactly four ways across all 96 functions.
# Keys are normalized (nbsp collapsed, trailing period dropped, lowercased)
# by :func:`classify_usage` before lookup.
_USAGE_MODES: dict[str, str] = {
    "хранит состояние устройства и может менять его": USAGE_STATE_READ_WRITE,
    "хранит состояние устройства, менять его не может": USAGE_STATE_READ_ONLY,
    "не хранит состояние устройства, может менять его": USAGE_COMMAND_ONLY,
    "уведомляет о состоянии устройства, менять его не может": USAGE_EVENT_ONLY,
}


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
    #
    # На части страниц (напр. sensor_air) таблица обёрнута в <div> и не является
    # прямым sibling'ом заголовка — старый экстрактор её не находил и уходил в
    # silent-fallback (obligatory/conditional=[]), что давало ЛОЖНЫЙ дрифт при
    # живой таблице. Структурный фикс — в _TABLE_EXTRACTOR_JS (поиск вложенной
    # таблицы). Здесь дополнительно ждём заголовок и ретраим на случай, когда
    # JS-рендер таблицы не готов к первому проходу; hub-страницы без таблицы
    # легитимно отработают пустым fallback ниже.
    with contextlib.suppress(PlaywrightTimeout):
        page.wait_for_selector("h2:has-text('Доступные функции')", timeout=8_000)
    table_rows = _extract_features_table(page)
    for _ in range(3):
        if table_rows:
            break
        page.wait_for_timeout(600)
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
  const HEAD = /^H[1-4]$/;
  const headings = Array.from(document.querySelectorAll('h1,h2,h3,h4'));
  const target = headings.find(h => h.innerText.includes('Доступные функции'));
  if (!target) return [];
  // The table is not always a direct sibling of the heading — on some
  // category pages (e.g. sensor_air) it is wrapped in a <div>. Scan the
  // following siblings until the next section heading and pick the first
  // <table>, whether it is the sibling itself or nested inside it.
  let table = null;
  let el = target.nextElementSibling;
  while (el && !HEAD.test(el.tagName)) {
    if (el.tagName === 'TABLE') { table = el; break; }
    const inner = el.querySelector ? el.querySelector('table') : null;
    if (inner) { table = inner; break; }
    el = el.nextElementSibling;
  }
  if (!table) return [];
  const rows = Array.from(table.querySelectorAll('tr'));
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


_MAIN_JS_URL_RE = re.compile(r'https://media\.sberdevices\.ru/bsm-docs/[^"\s]+/main\.[a-f0-9]+\.js')
_MDX_SLUG_RE = re.compile(r'"@site/docs/ru/smarthome/c2c/([a-z0-9_-]+)\.mdx"')


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


def slug_candidates(name: str) -> list[str]:
    """URL slugs a function *might* live at, most likely first.

    The canonical function name always uses underscores, while the docs
    site is inconsistent about the slug: ``open_set`` is served at
    ``/open_set`` but ``light_colour_temp`` at ``/light-colour-temp``.
    With no index entry to read the real href from, both spellings have
    to be tried.

    Args:
        name: Canonical function name (underscore form).

    Returns:
        One or two slugs; the kebab variant is omitted when the name has
        no underscore to convert.
    """
    kebab = name.replace("_", "-")
    return [name] if kebab == name else [name, kebab]


def plan_recovery_names(discovered_slugs: list[str], known_functions: set[str]) -> list[str]:
    """Functions the index stopped listing and that must be fetched directly.

    The ``/functions`` index is the only discovery source, so a page that
    silently drops out of it disappears from the snapshot — and with it
    from ``FEATURE_ENUM_VALUES`` / ``FEATURE_RANGES``.  Nothing downstream
    notices: the validator simply stops checking that feature.  Comparing
    the discovered slugs with the previously committed catalog turns that
    silent shrinkage into a direct re-fetch.

    Args:
        discovered_slugs: Slugs the index yielded this run.
        known_functions: Function names from the previous snapshot.

    Returns:
        Sorted names present in the previous snapshot but not covered by
        any discovered slug (slug dashes count as underscores).
    """
    covered = {slug.replace("-", "_") for slug in discovered_slugs}
    return sorted(known_functions - covered)


def extract_enum_values(article_text: str) -> list[str]:
    """Pull an ENUM function's accepted values out of its page text.

    The vocabulary is prose, not a table::

        Назначение: управляет скоростью вентилятора:

        auto — скорость меняется автоматически.
        quiet — тихий режим работы. ...

        Устройства с этой функцией
        hvac_ac — кондиционеры.

    Note the last two lines: the category list that follows has the very
    same shape, so the scan is bounded by
    :data:`_ENUM_STOP_MARKER` — without that bound every category name
    would be collected as an accepted value.

    This vocabulary is the *authoritative* one.  The ``allowed_values``
    block on a category page is only an illustrative example and is
    routinely shorter: the ``hvac_air_flow_power`` example omits
    ``quiet`` even though the function accepts it, so validating our own
    values against the category example would reject correct devices.

    Args:
        article_text: ``innerText`` of the function page's article.

    Returns:
        Accepted values in page order, de-duplicated.  Empty when the
        page has no vocabulary (every non-ENUM function, and the odd
        ENUM whose page words things differently — callers must treat
        "empty" as "unknown", never as "nothing is allowed").
    """
    start = article_text.find(_ENUM_START_MARKER)
    if start == -1:
        return []
    end = article_text.find(_ENUM_STOP_MARKER, start)
    section = article_text[start : end if end != -1 else len(article_text)]
    seen: list[str] = []
    for match in _ENUM_VALUE_RE.finditer(section):
        value = match.group(1)
        if value not in seen:
            seen.append(value)
    return seen


def normalize_spaces(text: str) -> str:
    """Collapse Sber's typographic whitespace into plain single spaces.

    The docs are typeset with non-breaking spaces (``\\xa0``) and the odd
    zero-width BOM (``\\ufeff``) sprinkled mid-sentence: ``alarm_mute``
    reads "менять его не\\xa0может" while ``battery_low_power`` uses a
    plain space in the very same phrase.  Comparing the raw strings would
    split one wording into two, so every phrase is normalized first.

    Args:
        text: Raw ``innerText`` fragment as rendered by the docs site.

    Returns:
        The same text with all whitespace runs turned into single spaces
        and the leading/trailing whitespace stripped.
    """
    return re.sub(r"\s+", " ", text.replace("\xa0", " ").replace("\ufeff", "")).strip()


def classify_usage(usage: str) -> str | None:
    """Map a "Способ использования" sentence onto one of the four modes.

    Args:
        usage: The sentence as the page words it (raw or normalized).

    Returns:
        One of :data:`USAGE_STATE_READ_WRITE`, :data:`USAGE_STATE_READ_ONLY`,
        :data:`USAGE_COMMAND_ONLY`, :data:`USAGE_EVENT_ONLY` — or ``None``
        when Sber reworded the sentence.  ``None`` means *unknown*, never
        "no restriction": callers surface it as drift instead of guessing,
        because guessing here silently mislabels a command-only feature as
        state-bearing and the validator starts demanding a state that can
        never arrive.
    """
    return _USAGE_MODES.get(normalize_spaces(usage).rstrip(" .").lower())


def extract_usage(article_text: str) -> tuple[str | None, str | None]:
    """Pull the usage sentence + its classification off a function page.

    Args:
        article_text: ``innerText`` of the function page's article.

    Returns:
        ``(usage, usage_mode)``.  ``usage`` is the normalized sentence,
        ``usage_mode`` its :data:`_USAGE_MODES` classification.  Both are
        ``None`` when the page carries no usage line at all.
    """
    match = _USAGE_DECL_RE.search(article_text)
    if not match:
        return None, None
    usage = normalize_spaces(match.group(1))
    return usage, classify_usage(usage)


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

    usage, usage_mode = extract_usage(article_text)

    spec: dict = {
        "name": name,
        "type": type_name,
        "range": range_str,
        "usage": usage,
        "usage_mode": usage_mode,
        "examples": [b.strip() for b in pre_blocks if b.strip()],
    }
    if type_name == "ENUM":
        values = extract_enum_values(article_text)
        if values:
            spec["enum_values"] = values
    return spec


def report_usage_coverage(functions: dict[str, dict]) -> bool:
    """Print how many functions carry a recognised usage mode.

    Deliberately a warning and not a failure: a reworded usage sentence
    must still let the run finish and write the snapshot, so the drift
    check downstream can open a PR showing exactly which function lost
    its classification.  Failing here would abort before the PR exists.

    Args:
        functions: The function catalog, after extraction.

    Returns:
        ``True`` when every function is classified, ``False`` otherwise.
    """
    unknown = sorted(name for name, spec in functions.items() if not spec.get("usage_mode"))
    if not unknown:
        print(f"OK: all {len(functions)} functions carry a recognised usage mode")
        return True
    print(f"WARNING: {len(unknown)} function(s) with unrecognised 'Способ использования' wording:")
    for name in unknown:
        print(f"  ? {name:30s} usage={functions[name].get('usage')!r}")
    print("  Action: add the new wording to _USAGE_MODES in this file")
    return False


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

        # Phase 2b: the index is the only discovery source, so anything it
        # drops would silently vanish from the catalog.  Re-fetch such pages
        # by their slug directly (see plan_recovery_names).
        recovery = [n for n in plan_recovery_names(function_slugs, known_functions) if n not in functions]
        if recovery:
            print(f"\n=== Phase 2b: {len(recovery)} known function(s) missing from the index ===")
            for name in recovery:
                print(f"Re-fetching {name} by slug...", end=" ", flush=True)
                for candidate in slug_candidates(name):
                    spec = extract_function_spec(page, candidate)
                    if spec is not None and spec.get("type") is not None:
                        spec = {k: v for k, v in spec.items() if k != "examples"}
                        functions[spec["name"]] = spec
                        print(f"OK ({spec['type']}, /{candidate})")
                        break
                else:
                    print("MISSING")
                    function_failures.append(name)

        browser.close()

    # Phase 2c: usage-mode coverage (warning only — see report_usage_coverage).
    print("\n=== Phase 2c: usage mode coverage ===")
    report_usage_coverage(functions)

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
