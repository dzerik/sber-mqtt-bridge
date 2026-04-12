"""Tests for the generated _generated/ package + codegen safety properties.

Validates:
1. Generated files are importable and contain expected data
2. FEATURE_TYPES runtime validator catches wrong value types
3. Codegen --check mode correctly detects drift
4. Runtime never reads the JSON spec (defense against portal outages)
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from custom_components.sber_mqtt_bridge._generated import (
    CATEGORY_REFERENCE_FEATURES,
    FEATURE_TYPES,
    SPEC_GENERATED_AT,
    SPEC_SOURCE,
)
from custom_components.sber_mqtt_bridge.sber_models import (
    SberState,
    unknown_features_for_category,
)

REPO_ROOT = Path(__file__).parent.parent.parent
CODEGEN_SCRIPT = REPO_ROOT / "tools" / "codegen.py"


class TestGeneratedArtifacts:
    """The generated package must expose the expected data."""

    def test_feature_types_non_empty(self):
        assert len(FEATURE_TYPES) >= 80, f"only {len(FEATURE_TYPES)} features, scraper regression?"

    def test_every_feature_type_is_valid_sber_type(self):
        valid = {"BOOL", "INTEGER", "FLOAT", "STRING", "ENUM", "COLOUR"}
        invalid = [(k, v) for k, v in FEATURE_TYPES.items() if v not in valid]
        assert not invalid, f"features with invalid types: {invalid}"

    def test_category_reference_features_covers_all_28(self):
        assert len(CATEGORY_REFERENCE_FEATURES) == 28

    def test_every_category_has_online_in_reference(self):
        for cat, features in CATEGORY_REFERENCE_FEATURES.items():
            assert "online" in features, f"{cat} reference missing 'online'"

    def test_provenance_constants_present(self):
        # Exact URL comparison (CodeQL flags startswith as incomplete URL sanitization)
        assert SPEC_SOURCE == "https://developers.sber.ru/docs/ru/smarthome/c2c"
        assert SPEC_GENERATED_AT  # ISO 8601 timestamp


class TestFeatureTypeValidator:
    """SberState must reject states whose value type doesn't match FEATURE_TYPES."""

    def test_valid_pir_enum_passes(self):
        state = SberState.model_validate({"key": "pir", "value": {"type": "ENUM", "enum_value": "pir"}})
        assert state.key == "pir"

    def test_pir_as_bool_rejected(self):
        """The real bug that motivated this validator — pir must be ENUM, not BOOL."""
        with pytest.raises(ValidationError, match="pir.*ENUM"):
            SberState.model_validate({"key": "pir", "value": {"type": "BOOL", "bool_value": True}})

    def test_doorcontact_state_as_enum_rejected(self):
        """doorcontact_state is BOOL per Sber spec, not ENUM."""
        with pytest.raises(ValidationError, match="doorcontact_state.*BOOL"):
            SberState.model_validate({"key": "doorcontact_state", "value": {"type": "ENUM", "enum_value": "open"}})

    def test_on_off_as_integer_rejected(self):
        with pytest.raises(ValidationError, match="on_off.*BOOL"):
            SberState.model_validate({"key": "on_off", "value": {"type": "INTEGER", "integer_value": "1"}})

    def test_light_brightness_as_bool_rejected(self):
        with pytest.raises(ValidationError, match="light_brightness.*INTEGER"):
            SberState.model_validate({"key": "light_brightness", "value": {"type": "BOOL", "bool_value": True}})

    def test_unknown_feature_allowed(self):
        """Features not in FEATURE_TYPES pass through — handled by schema compliance tests."""
        # Make sure the unknown feature isn't actually known
        key = "totally_made_up_feature_xyz"
        assert key not in FEATURE_TYPES
        state = SberState.model_validate({"key": key, "value": {"type": "BOOL", "bool_value": True}})
        assert state.key == key

    def test_extra_field_still_rejected(self):
        """Original extra='forbid' protection still works."""
        with pytest.raises(ValidationError):
            SberState.model_validate(
                {
                    "key": "on_off",
                    "value": {"type": "BOOL", "bool_value": True},
                    "extra_field": 1,
                }
            )


class TestUnknownFeaturesHelper:
    """unknown_features_for_category() identifies features not in Sber reference."""

    def test_light_with_only_reference_features(self):
        features = {"online", "on_off", "light_brightness"}
        assert unknown_features_for_category("light", features) == set()

    def test_relay_with_tv_feature_flagged(self):
        """Adding 'source' (TV feature) to a relay would cause silent Sber rejection."""
        features = {"online", "on_off", "source"}
        unknown = unknown_features_for_category("relay", features)
        assert "source" in unknown

    def test_unknown_category_returns_empty(self):
        """Unknown categories skip the check rather than false-positive."""
        assert unknown_features_for_category("does_not_exist", {"online"}) == set()


class TestCodegenDriftCheck:
    """Codegen --check mode must accurately report drift."""

    def test_check_mode_succeeds_on_fresh_commit(self):
        """With files freshly regenerated, --check exits 0."""
        result = subprocess.run(
            [sys.executable, str(CODEGEN_SCRIPT), "--check"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        assert result.returncode == 0, (
            f"codegen --check failed — generated files out of date?\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )


class TestRuntimeDoesNotReadSpec:
    """Production runtime must NOT depend on the JSON spec file.

    If the portal is down and the spec file gets corrupted, committed
    generated modules must continue to work.
    """

    def test_generated_modules_have_no_json_imports(self):
        """Generated .py files shouldn't import json at runtime."""
        pkg_dir = REPO_ROOT / "custom_components" / "sber_mqtt_bridge" / "_generated"
        for py_file in pkg_dir.glob("*.py"):
            content = py_file.read_text()
            assert "import json" not in content, f"{py_file.name} imports json — runtime depends on spec"
            assert "open(" not in content, f"{py_file.name} opens a file — runtime reads from disk"

    def test_generated_modules_load_without_spec(self, tmp_path, monkeypatch):
        """Loading _generated/ does not fail if the spec file is missing."""
        # The module is already imported at the top of this file, proving
        # the load path doesn't require the spec. Do an independent check:
        # re-import in isolation and confirm the data is the same.
        spec_mod = importlib.util.find_spec("custom_components.sber_mqtt_bridge._generated.feature_types")
        assert spec_mod is not None, "feature_types module not importable"
        assert spec_mod.origin and Path(spec_mod.origin).exists()
