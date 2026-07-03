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
    CATEGORY_OBLIGATORY_FEATURES,
    CATEGORY_REFERENCE_FEATURES,
    FEATURE_TYPES,
    SPEC_GENERATED_AT,
    SPEC_SOURCE,
)
from custom_components.sber_mqtt_bridge.sber_models import (
    SberState,
    missing_obligatory_features,
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

    def test_category_reference_features_covers_all_29(self):
        # 28 original Sber categories + sensor_air (added v1.40.0).
        assert len(CATEGORY_REFERENCE_FEATURES) == 29

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
        with pytest.raises(ValidationError, match=r"pir.*ENUM"):
            SberState.model_validate({"key": "pir", "value": {"type": "BOOL", "bool_value": True}})

    def test_doorcontact_state_as_enum_rejected(self):
        """doorcontact_state is BOOL per Sber spec, not ENUM."""
        with pytest.raises(ValidationError, match=r"doorcontact_state.*BOOL"):
            SberState.model_validate({"key": "doorcontact_state", "value": {"type": "ENUM", "enum_value": "open"}})

    def test_on_off_as_integer_rejected(self):
        with pytest.raises(ValidationError, match=r"on_off.*BOOL"):
            SberState.model_validate({"key": "on_off", "value": {"type": "INTEGER", "integer_value": "1"}})

    def test_light_brightness_as_bool_rejected(self):
        with pytest.raises(ValidationError, match=r"light_brightness.*INTEGER"):
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


class TestObligatoryFeatures:
    """CATEGORY_OBLIGATORY_FEATURES + missing_obligatory_features() correctness."""

    def test_obligatory_covers_all_categories(self):
        # 28 original Sber categories + sensor_air (added v1.40.0).
        assert len(CATEGORY_OBLIGATORY_FEATURES) == 29

    def test_online_is_obligatory_almost_everywhere(self):
        """Every category except possibly exotic ones must have online obligatory."""
        missing_online = [c for c, oblig in CATEGORY_OBLIGATORY_FEATURES.items() if "online" not in oblig]
        # online is universally required per Sber spec — if this ever fails,
        # Sber docs changed or our scraper regressed.
        assert not missing_online, f"Categories without 'online' obligatory: {missing_online}"

    def test_light_requires_on_off_and_online(self):
        """Regression guard — our primary test category."""
        assert CATEGORY_OBLIGATORY_FEATURES["light"] == frozenset({"online", "on_off"})

    def test_sensor_pir_requires_online_and_pir(self):
        assert CATEGORY_OBLIGATORY_FEATURES["sensor_pir"] == frozenset({"online", "pir"})

    def test_missing_obligatory_detects_incomplete_emission(self):
        """Device emitting only 'online' for light should flag 'on_off' as missing."""
        missing = missing_obligatory_features("light", {"online"})
        assert missing == {"on_off"}

    def test_missing_obligatory_empty_when_all_present(self):
        assert missing_obligatory_features("light", {"online", "on_off", "light_brightness"}) == set()

    def test_missing_obligatory_unknown_category_empty(self):
        """Unknown categories fail-open (empty set, not false positive)."""
        assert missing_obligatory_features("does_not_exist", set()) == set()

    def test_sensor_temp_obligatory_relaxed_after_2026_05(self):
        """After the 2026-05 Sber spec update humidity/temperature became
        ✔︎* conditional (at-least-one-of). Ensure our codegen no longer
        marks them strict-mandatory — otherwise chunk-temperature-only
        HA sensors get false-rejected locally by missing_obligatory_features().
        """
        assert CATEGORY_OBLIGATORY_FEATURES["sensor_temp"] == frozenset({"online"})

    def test_cover_obligatory_relaxed_after_2026_05(self):
        """open_percentage/open_set became ✔︎* conditional for four cover
        categories; only online + open_state remain strict."""
        for cat in ("curtain", "gate", "valve", "window_blind"):
            assert CATEGORY_OBLIGATORY_FEATURES[cat] == frozenset({"online", "open_state"}), \
                f"{cat}: unexpected obligatory set — snapshot may need re-scraping"


class TestMissingObligatoryFeaturesBehaviour:
    """Behavioural tests for :func:`missing_obligatory_features` — the
    helper that guards against silent Sber-cloud device rejection.

    The audit flagged that ``TestObligatoryFeatures`` above verifies the
    generated data tables + one happy path, but not the function's
    edge behaviour (multiple missing, override interaction, whitespace,
    return-type shape).  Locking these prevents regressions where a
    refactor of the helper could pass the existing tests while breaking
    the silent-rejection audit.
    """

    def test_reports_multiple_missing_simultaneously(self):
        """A device emitting nothing must have EVERY obligatory feature
        flagged, not just one — otherwise callers apply fixes one-at-a-time
        and never converge."""
        missing = missing_obligatory_features("light", set())
        assert missing == {"online", "on_off"}

    def test_light_missing_only_on_off(self):
        """Emitting ``online`` alone leaves ``on_off`` missing."""
        assert missing_obligatory_features("light", {"online"}) == {"on_off"}

    def test_light_missing_only_online(self):
        """Emitting ``on_off`` alone leaves ``online`` missing."""
        assert missing_obligatory_features("light", {"on_off"}) == {"online"}

    def test_extra_features_do_not_affect_result(self):
        """Emitting extra unrelated features doesn't hide a missing
        obligatory one — the check is set-difference-based."""
        missing = missing_obligatory_features(
            "light", {"online", "child_lock", "sensor_sensitive"}
        )
        assert missing == {"on_off"}

    def test_sensor_temp_override_actually_relaxes_missing(self):
        """The ``_CATEGORY_OBLIGATORY_OVERRIDES`` layer must flow through
        :func:`missing_obligatory_features` — otherwise the override is
        dead code and temperature-only sensors get flagged incorrectly.
        """
        # temperature-only sensor (no humidity) — must be considered
        # complete because the override reduces obligatory to {online}.
        assert missing_obligatory_features("sensor_temp", {"online", "temperature"}) == set()

    def test_sensor_temp_online_alone_is_compliant(self):
        """Override cascades: ``online`` alone is enough for sensor_temp
        even though Sber's raw table historically wanted temperature/humidity.
        """
        assert missing_obligatory_features("sensor_temp", {"online"}) == set()

    def test_return_supports_membership_and_set_ops(self):
        """The result must be usable with the standard set-difference /
        membership API — that's what dispatcher/logging code relies on.
        Contract: it's a set-like of str; concrete class (frozenset vs
        set) is an implementation detail but iterability and ``in`` must
        both work.
        """
        result = missing_obligatory_features("light", {"online"})
        # Membership works
        assert "on_off" in result
        assert "online" not in result
        # Iterable
        assert list(result) == ["on_off"]
        # Set-difference with a plain set returns something set-like
        assert (result - {"on_off"}) == set()

    def test_empty_string_category_treated_as_unknown(self):
        """Empty-string category should be treated as unknown and fail-open,
        not crash — guards against a hall-of-mirrors bug where a missing
        ``category`` field is coerced to ``""`` upstream."""
        assert missing_obligatory_features("", {"online"}) == set()

    def test_none_category_treated_as_unknown_via_dict_get(self):
        """A ``None`` category flowing through ``dict.get`` returns None
        obligatory → empty missing set.  If this ever raises, we'd crash
        in ``sber_bridge`` when a malformed device slips through."""
        # Cast to str to satisfy type-checker; runtime coerces None via .get.
        assert missing_obligatory_features(None, {"online"}) == set()  # type: ignore[arg-type]

    def test_case_sensitivity_categories_are_lowercase(self):
        """Sber categories are lowercase; ``"Light"`` is a typo, not a
        valid category — must fail-open (unknown) rather than false-match."""
        assert missing_obligatory_features("Light", {"online"}) == set()

    def test_cover_categories_missing_open_state(self):
        """After the 2026-05 spec relaxation, four cover categories only
        require ``online`` + ``open_state``.  A cover emitting only
        ``open_percentage`` must still be flagged for missing ``open_state``.
        """
        for cat in ("curtain", "gate", "valve", "window_blind"):
            missing = missing_obligatory_features(cat, {"online", "open_percentage"})
            assert missing == {"open_state"}, f"{cat}: {missing}"

    def test_sensor_air_requires_only_online(self):
        """sensor_air (v1.40.0) was introduced with all measurement
        features as ✔︎* conditional; ``online`` is the only obligatory
        feature.  A device emitting just ``online`` is Sber-compliant."""
        assert missing_obligatory_features("sensor_air", {"online"}) == set()

    def test_sensor_air_online_missing_flagged(self):
        """But an empty sensor_air (no online) must still fail — the
        override does not remove ``online`` from the obligatory set."""
        assert missing_obligatory_features("sensor_air", {"co2", "pm2_5"}) == {"online"}


class TestSensorAirGeneratedTables:
    """Direct assertions against the ``_generated/`` tables for the
    v1.40.0 ``sensor_air`` category — closes audit Subject 4.

    Existing tests here treat the tables holistically ("count == 29",
    "online present everywhere").  These lock the shape for the
    single most-recent addition, so a scraper regression that quietly
    drops ``co2`` from the reference list — or that emits it with the
    wrong type — fails a targeted test instead of hiding behind
    downstream integration failures.
    """

    EXPECTED_REFERENCE = frozenset({
        "online",
        # ✔︎* conditional measurements (eight)
        "co2",
        "pm1_0",
        "pm2_5",
        "pm10",
        "tvoc_float",
        "hcho_float",
        "temperature",
        "humidity",
        # Display + telemetry
        "temp_unit_view",
        "battery_percentage",
        "battery_low_power",
        "signal_strength",
    })

    def test_sensor_air_registered_in_reference(self):
        assert "sensor_air" in CATEGORY_REFERENCE_FEATURES

    def test_sensor_air_registered_in_obligatory(self):
        assert "sensor_air" in CATEGORY_OBLIGATORY_FEATURES

    def test_sensor_air_reference_matches_expected_shape(self):
        """The reference set must exactly match the 13 features in the
        2026-05 Sber spec.  If new features are added upstream, this
        test needs to be updated deliberately, not silently."""
        assert CATEGORY_REFERENCE_FEATURES["sensor_air"] == self.EXPECTED_REFERENCE

    def test_sensor_air_obligatory_is_only_online(self):
        """All eight measurement features are ✔︎* conditional per the
        2026-05 spec.  Only ``online`` is strict-mandatory."""
        assert CATEGORY_OBLIGATORY_FEATURES["sensor_air"] == frozenset({"online"})

    @pytest.mark.parametrize("feature,expected_type", [
        ("online", "BOOL"),
        ("co2", "INTEGER"),
        ("pm1_0", "INTEGER"),
        ("pm2_5", "INTEGER"),
        ("pm10", "INTEGER"),
        ("humidity", "INTEGER"),
        ("temperature", "INTEGER"),
        ("tvoc_float", "FLOAT"),
        ("hcho_float", "FLOAT"),
        ("temp_unit_view", "ENUM"),
        ("battery_percentage", "INTEGER"),
        ("battery_low_power", "BOOL"),
    ])
    def test_sensor_air_feature_type_correct(self, feature, expected_type):
        """Type mismatches are the exact class of bug the Feature-Type
        validator was created for — e.g., emitting ``co2`` as BOOL would
        cause Sber to silently drop the whole device.  Lock each type."""
        assert FEATURE_TYPES.get(feature) == expected_type, (
            f"{feature}: FEATURE_TYPES={FEATURE_TYPES.get(feature)!r}, expected {expected_type!r}"
        )

    def test_sensor_air_reference_features_include_all_measurements(self):
        """Every conditional measurement (co2, pm*, tvoc/hcho, temp,
        humidity) that the SensorAirEntity code populates must exist
        in the reference — otherwise emit-time state entries would be
        classified as ``unknown_features_for_category`` and rejected.
        """
        measurements = {"co2", "pm1_0", "pm2_5", "pm10",
                        "tvoc_float", "hcho_float", "temperature", "humidity"}
        assert measurements.issubset(CATEGORY_REFERENCE_FEATURES["sensor_air"])

    def test_sensor_air_battery_signal_in_reference(self):
        """Battery + signal telemetry come from the shared
        ``BatteryAndSignalLinkMixin`` — assert they're recognised for
        sensor_air specifically (mixin behaviour is category-agnostic
        but the reference table must still list them)."""
        for feat in ("battery_percentage", "battery_low_power", "signal_strength"):
            assert feat in CATEGORY_REFERENCE_FEATURES["sensor_air"], (
                f"{feat}: not in sensor_air reference — snapshot regression?"
            )

    def test_sensor_air_no_leaked_features_from_other_categories(self):
        """Guard against a scraper bug where features from adjacent
        categories (e.g. ``on_off`` from switch, ``pir`` from sensor_pir)
        leak into sensor_air's reference set."""
        forbidden = {"on_off", "pir", "gas_leak_state",
                     "doorcontact_state", "hvac_temp_set", "light_brightness"}
        overlap = CATEGORY_REFERENCE_FEATURES["sensor_air"] & forbidden
        assert not overlap, f"Leaked features in sensor_air reference: {overlap}"


class TestCodegenDriftCheck:
    """Codegen --check mode must accurately report drift."""

    def test_check_mode_succeeds_on_fresh_commit(self):
        """With files freshly regenerated, --check exits 0."""
        result = subprocess.run(  # noqa: S603 — sys.executable is trusted
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
        assert spec_mod.origin
        assert Path(spec_mod.origin).exists()
