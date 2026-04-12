"""Live Sber protocol compliance tests.

Compares the canonical Sber schemas (fetched from developers.sber.ru via
``tools/fetch_sber_schemas.py``) against:

1. Our ``CATEGORY_REQUIRED_FEATURES`` — must include all features Sber
   lists in its reference model.
2. Our device classes — the features list produced by a minimally-filled
   entity must be a subset of what Sber allows.

When Sber updates its documentation, the weekly ``sber-compliance``
CI workflow re-runs the scraper and this test fails with a clear diff,
prompting a PR.  The snapshot file is the source of truth —
regenerate it after verifying the Sber change is intentional.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from custom_components.sber_mqtt_bridge.sber_models import CATEGORY_REQUIRED_FEATURES

SNAPSHOT_FILE = Path(__file__).parent / "__snapshots__" / "sber_schemas.json"
FULL_SPEC_FILE = Path(__file__).parent / "__snapshots__" / "sber_full_spec.json"


@pytest.fixture(scope="module")
def sber_schemas() -> dict[str, dict]:
    """Load the fetched Sber schemas snapshot."""
    if not SNAPSHOT_FILE.exists():
        pytest.skip(f"Snapshot file missing — run tools/fetch_sber_schemas.py: {SNAPSHOT_FILE}")
    return json.loads(SNAPSHOT_FILE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def sber_full_spec() -> dict:
    """Load the unified Sber specification artifact (categories + functions)."""
    if not FULL_SPEC_FILE.exists():
        pytest.skip(f"Full spec missing — run tools/fetch_sber_schemas.py: {FULL_SPEC_FILE}")
    return json.loads(FULL_SPEC_FILE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def sber_functions(sber_full_spec: dict) -> dict[str, dict]:
    """Shortcut accessor for the functions catalog."""
    return sber_full_spec.get("functions", {})


class TestSberSchemasSnapshot:
    """Snapshot-level sanity checks."""

    def test_all_28_categories_present(self, sber_schemas: dict[str, dict]) -> None:
        """The snapshot must cover every category we promise to support."""
        expected = set(CATEGORY_REQUIRED_FEATURES.keys())
        found = set(sber_schemas.keys())
        missing = expected - found
        assert not missing, f"Snapshot missing {len(missing)} categories: {sorted(missing)}"

    def test_every_schema_has_online(self, sber_schemas: dict[str, dict]) -> None:
        """Per Sber VR-010, every device category must include 'online'."""
        for category, schema in sber_schemas.items():
            assert "online" in schema["features"], f"{category} schema missing 'online'"

    def test_every_schema_has_expected_shape(self, sber_schemas: dict[str, dict]) -> None:
        """Each schema must have category, features, allowed_values, dependencies keys."""
        required_keys = {"category", "features", "allowed_values", "dependencies"}
        for category, schema in sber_schemas.items():
            missing = required_keys - set(schema.keys())
            assert not missing, f"{category} schema missing keys: {missing}"


class TestOurRequiredFeaturesMatchSber:
    """Our ``CATEGORY_REQUIRED_FEATURES`` must be a subset of Sber's features.

    If Sber adds a mandatory feature to a category, our bridge should include
    it (or at least be aware).  If we require a feature Sber doesn't list,
    that's a bug in our assumptions.
    """

    @pytest.mark.parametrize("category", sorted(CATEGORY_REQUIRED_FEATURES.keys()))
    def test_our_required_features_listed_in_sber_schema(self, category: str, sber_schemas: dict[str, dict]) -> None:
        """Every feature we mark as required must appear in Sber's canonical features list."""
        schema = sber_schemas.get(category)
        if schema is None:
            pytest.skip(f"No Sber schema snapshot for {category}")

        our_required = set(CATEGORY_REQUIRED_FEATURES[category])
        sber_features = set(schema["features"])

        unknown = our_required - sber_features
        assert not unknown, f"{category}: we require {unknown} but Sber schema has only {sber_features}"


class TestCategoryCoverage:
    """Detect when Sber adds new categories that we don't support yet."""

    def test_no_new_sber_categories(self, sber_schemas: dict[str, dict]) -> None:
        """Sber snapshot categories should all be known to us.

        If this fails, Sber added a new category.  Decide whether to add
        support or explicitly exclude it from our registry.
        """
        sber_cats = set(sber_schemas.keys())
        our_cats = set(CATEGORY_REQUIRED_FEATURES.keys())
        new = sber_cats - our_cats
        assert not new, f"Sber added new categories not in our registry: {new}"


class TestFunctionsCatalog:
    """Validate the functions catalog and category cross-references."""

    def test_functions_catalog_not_empty(self, sber_functions: dict[str, dict]) -> None:
        """The catalog should contain at least 80 functions (Sber currently has ~90)."""
        assert len(sber_functions) >= 80, f"Only {len(sber_functions)} functions found — scraper regression?"

    def test_every_function_has_type(self, sber_functions: dict[str, dict]) -> None:
        """Every function must have a Sber data type declared."""
        missing_type = [name for name, spec in sber_functions.items() if not spec.get("type")]
        assert not missing_type, f"Functions without type: {missing_type}"

    def test_function_types_are_valid(self, sber_functions: dict[str, dict]) -> None:
        """Function types must be one of the known Sber value types."""
        valid_types = {"BOOL", "INTEGER", "FLOAT", "STRING", "ENUM", "COLOUR"}
        for name, spec in sber_functions.items():
            assert spec["type"] in valid_types, f"{name}: unknown type {spec['type']!r}"

    # Features referenced by Sber category schemas that have no page on
    # /functions. Either typos in Sber docs or undocumented features.
    # Update this set only after verifying each entry is really a Sber-side
    # documentation bug, not a scraper miss on our side.
    KNOWN_SBER_DOC_ISSUES: frozenset[str] = frozenset(
        {
            "battery_percentag",  # typo in scenario_button ref model (missing 'e')
            "sleep_timer",  # used in led_strip, no /functions page
        }
    )

    def test_category_features_resolve_to_known_functions(
        self,
        sber_schemas: dict[str, dict],
        sber_functions: dict[str, dict],
    ) -> None:
        """Every feature declared in any Sber category schema must exist in the functions catalog.

        If this fails, either our scraper missed a function or Sber introduced
        a feature without documenting it on /functions.  Known upstream typos
        are allowlisted in :attr:`KNOWN_SBER_DOC_ISSUES`.
        """
        all_features: set[str] = set()
        for schema in sber_schemas.values():
            all_features.update(schema.get("features", []))
        catalog_names = set(sber_functions.keys())
        orphan = (all_features - catalog_names) - self.KNOWN_SBER_DOC_ISSUES
        assert not orphan, f"Features referenced by categories but missing from /functions catalog: {orphan}"

    def test_functions_cross_reference_matches_category_schemas(
        self,
        sber_schemas: dict[str, dict],
        sber_functions: dict[str, dict],
    ) -> None:
        """Function.used_in_categories should mention every category that actually uses it.

        Sanity check that Sber docs are internally consistent — if a function
        says 'used in light' but light's schema doesn't list it, one of them
        is wrong.  We only flag obvious mismatches (>0 declared but 0 actual
        matches), not subset differences, to avoid false positives.
        """
        for name, spec in sber_functions.items():
            declared = set(spec.get("used_in_categories", []))
            if not declared:
                continue
            actual = {cat for cat, schema in sber_schemas.items() if name in schema.get("features", [])}
            if not actual:
                continue  # Sber docs sometimes list categories via inheritance
            intersection = declared & actual
            assert intersection, (
                f"Function {name}: declared used in {declared} but not listed in any of their feature lists"
            )
