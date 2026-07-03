"""Unit tests for the scraper's schema-processing helpers.

The scraper itself (``tools/fetch_sber_schemas.py``) needs playwright +
chromium and is run weekly on CI (``sber-compliance.yml``). These tests
exercise the pure-Python helpers used to *shape* the scraped data so
regressions in that shaping don't have to wait for the next weekly
crawl to be discovered.

Focus areas:
1. :func:`build_used_in_categories` — the inverse index that replaced
   the fragile ``_parse_categories_from_text`` (which produced empty
   ``used_in_categories`` lists for features like ``temperature``,
   ``humidity`` and ``volume``).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRAPER_PATH = REPO_ROOT / "tools" / "fetch_sber_schemas.py"


def _load_scraper_module():
    """Load ``tools/fetch_sber_schemas.py`` without importing playwright.

    The module imports ``playwright.sync_api`` at top level; if the
    package isn't installed it prints and calls ``sys.exit(1)``. We
    can't rely on playwright being available in every test env, so we
    stub it before loading.
    """
    if "playwright" not in sys.modules:
        stub = type(sys)("playwright")
        sync_stub = type(sys)("playwright.sync_api")
        sync_stub.TimeoutError = TimeoutError
        sync_stub.sync_playwright = lambda: None
        sys.modules["playwright"] = stub
        sys.modules["playwright.sync_api"] = sync_stub

    spec = importlib.util.spec_from_file_location("_scraper", SCRAPER_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def scraper():
    """Import the scraper module once per test module."""
    return _load_scraper_module()


class TestBuildUsedInCategories:
    """`build_used_in_categories` inverts per-category tables into feature→[cat]."""

    def test_single_category_single_feature(self, scraper):
        """One category with one feature → feature maps to that category."""
        result = scraper.build_used_in_categories(
            {"light": {"all_features": ["on_off"]}}
        )
        assert result == {"on_off": ["light"]}

    def test_feature_shared_by_multiple_categories(self, scraper):
        """A feature used by N categories lists all N, sorted."""
        result = scraper.build_used_in_categories(
            {
                "hvac_ac": {"all_features": ["temperature", "humidity"]},
                "hvac_boiler": {"all_features": ["temperature"]},
                "sensor_temp": {"all_features": ["temperature", "humidity"]},
                "hvac_humidifier": {"all_features": ["humidity"]},
            }
        )
        assert result["temperature"] == ["hvac_ac", "hvac_boiler", "sensor_temp"]
        assert result["humidity"] == ["hvac_ac", "hvac_humidifier", "sensor_temp"]

    def test_result_is_sorted_deterministically(self, scraper):
        """Category order in the result is alphabetical regardless of input order."""
        result = scraper.build_used_in_categories(
            {
                "zeta": {"all_features": ["shared"]},
                "alpha": {"all_features": ["shared"]},
                "middle": {"all_features": ["shared"]},
            }
        )
        assert result["shared"] == ["alpha", "middle", "zeta"]

    def test_empty_all_features_produces_no_entry(self, scraper):
        """Categories with no features don't create ghost feature entries."""
        result = scraper.build_used_in_categories(
            {
                "phantom": {"all_features": []},
                "light": {"all_features": ["on_off"]},
            }
        )
        assert "" not in result
        assert result == {"on_off": ["light"]}

    def test_missing_all_features_key_is_tolerated(self, scraper):
        """A category schema without the ``all_features`` key is skipped, not crashed."""
        result = scraper.build_used_in_categories(
            {
                "broken": {},  # no all_features
                "light": {"all_features": ["on_off"]},
            }
        )
        assert result == {"on_off": ["light"]}

    def test_empty_input_returns_empty_dict(self, scraper):
        """No categories → no features."""
        assert scraper.build_used_in_categories({}) == {}

    def test_feature_appears_once_even_if_listed_twice(self, scraper):
        """If the same category ends up in a feature's set twice, it's deduped."""
        # This shouldn't happen in real data (each all_features list is a set),
        # but the underlying set semantics guarantee dedup regardless of input.
        result = scraper.build_used_in_categories(
            {
                "sensor_temp": {"all_features": ["temperature", "temperature"]},
            }
        )
        assert result["temperature"] == ["sensor_temp"]


class TestScraperExports:
    """Guards against silent removal of helpers other code paths rely on."""

    def test_build_used_in_categories_is_exported(self, scraper):
        assert callable(getattr(scraper, "build_used_in_categories", None))

    def test_dead_helpers_are_gone(self, scraper):
        """The old text-based parser was replaced — must not resurrect silently."""
        assert not hasattr(scraper, "_parse_categories_from_text"), (
            "The fragile text-based parser was replaced by build_used_in_categories; "
            "keep the invariant that it stays gone."
        )
        assert not hasattr(scraper, "_CATEGORY_MARKER"), (
            "_CATEGORY_MARKER only made sense with _parse_categories_from_text; "
            "must not come back as dead code."
        )
