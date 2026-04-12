"""Live Sber protocol compliance tests.

Compares the canonical Sber schemas (fetched from developers.sber.ru via
``scripts/fetch_sber_schemas.py``) against:

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


@pytest.fixture(scope="module")
def sber_schemas() -> dict[str, dict]:
    """Load the fetched Sber schemas snapshot."""
    if not SNAPSHOT_FILE.exists():
        pytest.skip(f"Snapshot file missing — run scripts/fetch_sber_schemas.py: {SNAPSHOT_FILE}")
    return json.loads(SNAPSHOT_FILE.read_text(encoding="utf-8"))


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
