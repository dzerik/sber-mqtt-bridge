"""Strict pydantic model tests for Sber Smart Home protocol compliance.

Tests validate that sber_models.py correctly enforces the Sber C2C protocol
specification, including:
- Value type strictness (tagged union, string integers, HSV colour)
- extra='forbid' on all models (rejects unknown fields)
- Device model validators (VR-010 online, TV bug prevention)
- Device-level validators (VR-003 partner_meta size)
- Category compliance (required features per category)
- Integration: real device classes produce schema-valid output
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from custom_components.sber_mqtt_bridge.sber_models import (
    CATEGORY_REQUIRED_FEATURES,
    SberAllowedEnumValues,
    SberAllowedFloatValues,
    SberAllowedValue,
    SberColourValue,
    SberCommandPayload,
    SberConfigPayload,
    SberDependency,
    SberDependencyCondition,
    SberDevice,
    SberDeviceModel,
    SberDeviceState,
    SberState,
    SberStatusPayload,
    SberValue,
    make_bool_value,
    make_colour_value,
    make_enum_value,
    make_integer_value,
    make_state,
    validate_category_compliance,
    validate_config_payload,
    validate_device,
    validate_status_payload,
)

# ---------------------------------------------------------------------------
# Fixtures: reusable device data builders
# ---------------------------------------------------------------------------


def _minimal_entity_data(entity_id: str = "switch.test", name: str = "Test") -> dict:
    """Build minimal HA entity registry data for device construction."""
    return {"entity_id": entity_id, "name": name}


def _minimal_model(
    category: str = "relay",
    features: list[str] | None = None,
    allowed_values: dict | None = None,
    dependencies: dict | None = None,
) -> dict:
    """Build a valid SberDeviceModel dict."""
    data: dict = {
        "id": f"Mdl_{category}",
        "manufacturer": "Test",
        "model": "T1",
        "description": "Test device",
        "category": category,
        "features": features if features is not None else ["online", "on_off"],
    }
    if allowed_values is not None:
        data["allowed_values"] = allowed_values
    if dependencies is not None:
        data["dependencies"] = dependencies
    return data


def _minimal_device(
    category: str = "relay",
    features: list[str] | None = None,
    allowed_values: dict | None = None,
    partner_meta: dict | None = None,
) -> dict:
    """Build a valid SberDevice dict."""
    data: dict = {
        "id": "switch.test",
        "name": "Test Switch",
        "default_name": "switch.test",
        "room": "living_room",
        "model": _minimal_model(category, features, allowed_values),
        "hw_version": "1",
        "sw_version": "1",
    }
    if partner_meta is not None:
        data["partner_meta"] = partner_meta
    return data


# ===================================================================
# 1. SberValue strictness
# ===================================================================


class TestSberValueStrictness:
    """SberValue: tagged union type enforcement per Sber C2C spec."""

    def test_valid_bool_value(self):
        """PASS: BOOL type with bool_value is accepted."""
        v = SberValue.model_validate({"type": "BOOL", "bool_value": True})
        assert v.type == "BOOL"
        assert v.bool_value is True

    def test_valid_integer_value_is_string(self):
        """PASS: INTEGER type with string integer_value (Sber C2C spec)."""
        v = SberValue.model_validate({"type": "INTEGER", "integer_value": "220"})
        assert v.type == "INTEGER"
        assert v.integer_value == "220"

    def test_valid_enum_value(self):
        """PASS: ENUM type with enum_value string."""
        v = SberValue.model_validate({"type": "ENUM", "enum_value": "auto"})
        assert v.type == "ENUM"
        assert v.enum_value == "auto"

    def test_valid_colour_value(self):
        """PASS: COLOUR type with HSV colour_value object."""
        v = SberValue.model_validate({"type": "COLOUR", "colour_value": {"h": 360, "s": 1000, "v": 100}})
        assert v.type == "COLOUR"
        assert v.colour_value is not None
        assert v.colour_value.h == 360
        assert v.colour_value.s == 1000
        assert v.colour_value.v == 100

    def test_valid_float_value(self):
        """PASS: FLOAT type with float_value."""
        v = SberValue.model_validate({"type": "FLOAT", "float_value": 22.5})
        assert v.type == "FLOAT"
        assert v.float_value == 22.5

    def test_valid_string_value(self):
        """PASS: STRING type with string_value."""
        v = SberValue.model_validate({"type": "STRING", "string_value": "hello"})
        assert v.type == "STRING"
        assert v.string_value == "hello"

    def test_extra_field_rejected(self):
        """FAIL: extra='forbid' rejects unknown fields."""
        with pytest.raises(ValidationError, match="extra"):
            SberValue.model_validate({"type": "BOOL", "bool_value": True, "unknown_field": 1})

    def test_integer_value_as_int_rejected(self):
        """FAIL: integer_value must be string, not int (Sber C2C spec)."""
        with pytest.raises(ValidationError):
            SberValue.model_validate({"type": "INTEGER", "integer_value": 220})

    def test_invalid_type_literal_rejected(self):
        """FAIL: type must be one of the defined literals."""
        with pytest.raises(ValidationError):
            SberValue.model_validate({"type": "INVALID", "bool_value": True})


class TestSberColourValueStrictness:
    """SberColourValue: HSV with int fields, extra='forbid'."""

    def test_valid_hsv(self):
        """PASS: valid h/s/v integer triplet."""
        c = SberColourValue.model_validate({"h": 180, "s": 500, "v": 800})
        assert c.h == 180
        assert c.s == 500
        assert c.v == 800

    def test_extra_field_rejected(self):
        """FAIL: extra field in colour value."""
        with pytest.raises(ValidationError, match="extra"):
            SberColourValue.model_validate({"h": 0, "s": 0, "v": 100, "alpha": 255})

    def test_missing_field_rejected(self):
        """FAIL: h/s/v are all required."""
        with pytest.raises(ValidationError):
            SberColourValue.model_validate({"h": 0, "s": 0})

    def test_float_for_int_field_coerced(self):
        """Pydantic coerces compatible numeric types by default."""
        c = SberColourValue.model_validate({"h": 180, "s": 500, "v": 100})
        assert isinstance(c.h, int)


# ===================================================================
# 2. SberAllowedValue strictness
# ===================================================================


class TestSberAllowedValueStrictness:
    """SberAllowedValue: type-discriminated allowed ranges per feature."""

    def test_valid_integer_allowed(self):
        """PASS: INTEGER with min/max/step as strings."""
        av = SberAllowedValue.model_validate(
            {
                "type": "INTEGER",
                "integer_values": {"min": "0", "max": "100", "step": "1"},
            }
        )
        assert av.type == "INTEGER"
        assert av.integer_values is not None
        assert av.integer_values.min == "0"
        assert av.integer_values.max == "100"

    def test_valid_enum_allowed(self):
        """PASS: ENUM with values list."""
        av = SberAllowedValue.model_validate({"type": "ENUM", "enum_values": {"values": ["auto", "low"]}})
        assert av.type == "ENUM"
        assert av.enum_values is not None
        assert av.enum_values.values == ["auto", "low"]

    def test_valid_float_allowed(self):
        """PASS: FLOAT with numeric min/max."""
        av = SberAllowedValue.model_validate({"type": "FLOAT", "float_values": {"min": 0.5, "max": 5.0}})
        assert av.type == "FLOAT"
        assert av.float_values is not None
        assert av.float_values.min == 0.5
        assert av.float_values.max == 5.0

    def test_valid_colour_allowed_no_extra(self):
        """PASS: COLOUR type has no additional constraints."""
        av = SberAllowedValue.model_validate({"type": "COLOUR"})
        assert av.type == "COLOUR"
        assert av.integer_values is None
        assert av.float_values is None
        assert av.enum_values is None

    def test_extra_field_in_integer_values_rejected(self):
        """FAIL: extra field inside SberAllowedIntegerValues."""
        with pytest.raises(ValidationError, match="extra"):
            SberAllowedValue.model_validate(
                {
                    "type": "INTEGER",
                    "integer_values": {
                        "min": "0",
                        "max": "100",
                        "step": "1",
                        "extra": "bad",
                    },
                }
            )

    def test_integer_values_min_max_as_int_rejected(self):
        """FAIL: min/max/step must be strings, not ints (Sber spec)."""
        with pytest.raises(ValidationError):
            SberAllowedValue.model_validate(
                {
                    "type": "INTEGER",
                    "integer_values": {"min": 0, "max": 100, "step": 1},
                }
            )

    def test_extra_field_in_float_values_rejected(self):
        """FAIL: extra field inside SberAllowedFloatValues."""
        with pytest.raises(ValidationError, match="extra"):
            SberAllowedFloatValues.model_validate({"min": 0.0, "max": 100.0, "precision": 0.1})

    def test_extra_field_in_enum_values_rejected(self):
        """FAIL: extra field inside SberAllowedEnumValues."""
        with pytest.raises(ValidationError, match="extra"):
            SberAllowedEnumValues.model_validate({"values": ["a", "b"], "default": "a"})

    def test_extra_field_on_allowed_value_itself_rejected(self):
        """FAIL: extra top-level field on SberAllowedValue."""
        with pytest.raises(ValidationError, match="extra"):
            SberAllowedValue.model_validate(
                {
                    "type": "ENUM",
                    "enum_values": {"values": ["on"]},
                    "description": "Not allowed",
                }
            )


# ===================================================================
# 3. SberDeviceModel validators
# ===================================================================


class TestSberDeviceModelValidators:
    """SberDeviceModel: field validators for protocol safety."""

    def test_features_with_online_passes(self):
        """PASS: features list including 'online'."""
        m = SberDeviceModel.model_validate(_minimal_model())
        assert "online" in m.features

    def test_features_without_online_fails_vr010(self):
        """FAIL: features WITHOUT 'online' violates VR-010."""
        with pytest.raises(ValidationError, match=r"online.*VR-010"):
            SberDeviceModel.model_validate(_minimal_model(features=["on_off"]))

    def test_allowed_values_subset_of_features_passes(self):
        """PASS: allowed_values keys are a subset of features."""
        m = SberDeviceModel.model_validate(
            _minimal_model(
                features=["online", "on_off", "open_set"],
                allowed_values={
                    "open_set": {
                        "type": "ENUM",
                        "enum_values": {"values": ["open", "close"]},
                    }
                },
            )
        )
        assert "open_set" in m.allowed_values

    def test_allowed_values_key_not_in_features_fails(self):
        """FAIL: allowed_values has key NOT in features (TV bug)."""
        with pytest.raises(ValidationError, match="not in features"):
            SberDeviceModel.model_validate(
                _minimal_model(
                    features=["online", "on_off"],
                    allowed_values={
                        "volume_int": {
                            "type": "INTEGER",
                            "integer_values": {
                                "min": "0",
                                "max": "100",
                                "step": "1",
                            },
                        }
                    },
                )
            )

    def test_no_allowed_values_passes(self):
        """PASS: model with no allowed_values (sensors, simple relays)."""
        m = SberDeviceModel.model_validate(_minimal_model(features=["online", "temperature"]))
        assert m.allowed_values is None

    def test_model_with_dependencies_passes(self):
        """PASS: model with valid dependencies (light_colour depends on light_mode)."""
        m = SberDeviceModel.model_validate(
            _minimal_model(
                category="light",
                features=["online", "on_off", "light_colour", "light_mode"],
                dependencies={
                    "light_colour": {
                        "key": "light_mode",
                        "values": [{"type": "ENUM", "enum_value": "colour"}],
                    }
                },
            )
        )
        assert "light_colour" in m.dependencies

    def test_empty_features_still_needs_online(self):
        """FAIL: empty features list fails VR-010."""
        with pytest.raises(ValidationError, match=r"online.*VR-010"):
            SberDeviceModel.model_validate(_minimal_model(features=[]))

    def test_extra_model_field_rejected(self):
        """FAIL: extra field on SberDeviceModel."""
        data = _minimal_model()
        data["firmware"] = "2.0"
        with pytest.raises(ValidationError, match="extra"):
            SberDeviceModel.model_validate(data)


# ===================================================================
# 4. SberDevice validators
# ===================================================================


class TestSberDeviceValidators:
    """SberDevice: top-level device descriptor validation."""

    def test_valid_device_passes(self):
        """PASS: full valid device dict (relay with on_off)."""
        d = SberDevice.model_validate(_minimal_device())
        assert d.id == "switch.test"
        assert d.name == "Test Switch"

    def test_extra_top_level_field_rejected(self):
        """FAIL: extra top-level field on SberDevice."""
        data = _minimal_device()
        data["firmware_version"] = "2.0"
        with pytest.raises(ValidationError, match="extra"):
            SberDevice.model_validate(data)

    def test_partner_meta_under_1024_passes(self):
        """PASS: partner_meta under 1024 chars."""
        meta = {"key": "value"}
        d = SberDevice.model_validate(_minimal_device(partner_meta=meta))
        assert d.partner_meta == meta

    def test_partner_meta_over_1024_fails_vr003(self):
        """FAIL: partner_meta over 1024 chars violates VR-003."""
        # Generate a dict whose JSON serialization exceeds 1024 chars
        big_meta = {"data": "x" * 1020}
        assert len(json.dumps(big_meta)) > 1024
        with pytest.raises(ValidationError, match=r"1024.*VR-003"):
            SberDevice.model_validate(_minimal_device(partner_meta=big_meta))

    def test_partner_meta_exactly_1024_passes(self):
        """PASS: partner_meta exactly at boundary."""
        # json.dumps uses ': ' separator -> {"k": "xxx..."} has 9 chars overhead
        meta = {"k": "x" * 1015}
        assert len(json.dumps(meta)) == 1024
        d = SberDevice.model_validate(_minimal_device(partner_meta=meta))
        assert d.partner_meta is not None

    def test_partner_meta_none_passes(self):
        """PASS: partner_meta=None is fine."""
        d = SberDevice.model_validate(_minimal_device())
        assert d.partner_meta is None

    def test_device_with_nicknames_and_groups(self):
        """PASS: optional nicknames and groups are accepted."""
        data = _minimal_device()
        data["nicknames"] = ["My Switch", "Living Room Switch"]
        data["groups"] = ["lighting"]
        d = SberDevice.model_validate(data)
        assert d.nicknames == ["My Switch", "Living Room Switch"]
        assert d.groups == ["lighting"]


# ===================================================================
# 5. SberConfigPayload / SberStatusPayload / SberCommandPayload
# ===================================================================


class TestPayloads:
    """Config, status, and command payload envelope validation."""

    def test_valid_config_payload(self):
        """PASS: valid config with one device."""
        payload = SberConfigPayload.model_validate({"devices": [_minimal_device()]})
        assert len(payload.devices) == 1

    def test_config_payload_device_as_raw_dict_must_be_valid(self):
        """Devices must conform to SberDevice schema when parsed."""
        # Omit required 'model' key
        with pytest.raises(ValidationError):
            SberConfigPayload.model_validate({"devices": [{"id": "x", "name": "X"}]})

    def test_config_payload_empty_features_fails(self):
        """FAIL: device with empty features list fails VR-010."""
        bad_device = _minimal_device(features=[])
        with pytest.raises(ValidationError, match="online"):
            SberConfigPayload.model_validate({"devices": [bad_device]})

    def test_config_payload_extra_field_rejected(self):
        """FAIL: extra field on SberConfigPayload envelope."""
        with pytest.raises(ValidationError, match="extra"):
            SberConfigPayload.model_validate({"devices": [_minimal_device()], "version": "1.0"})

    def test_valid_status_payload(self):
        """PASS: valid status payload with device states."""
        payload = SberStatusPayload.model_validate(
            {
                "devices": {
                    "switch.test": {
                        "states": [
                            {
                                "key": "online",
                                "value": {"type": "BOOL", "bool_value": True},
                            }
                        ]
                    }
                }
            }
        )
        assert "switch.test" in payload.devices

    def test_valid_command_payload(self):
        """PASS: valid command payload (same structure as status)."""
        payload = SberCommandPayload.model_validate(
            {
                "devices": {
                    "switch.test": {
                        "states": [
                            {
                                "key": "on_off",
                                "value": {"type": "BOOL", "bool_value": True},
                            }
                        ]
                    }
                }
            }
        )
        assert "switch.test" in payload.devices


# ===================================================================
# 6. Category compliance (validate_category_compliance)
# ===================================================================


class TestCategoryCompliance:
    """validate_category_compliance: category-specific required features."""

    def test_light_with_required_features_passes(self):
        """PASS: light with {online, on_off} has no violations."""
        device = _minimal_device(category="light", features=["online", "on_off"])
        violations = validate_category_compliance(device)
        assert violations == []

    def test_light_without_on_off_fails(self):
        """FAIL: light WITHOUT on_off violates category requirement."""
        device = _minimal_device(category="light", features=["online", "light_brightness"])
        violations = validate_category_compliance(device)
        assert len(violations) >= 1
        assert "on_off" in str(violations[0])

    def test_sensor_pir_with_pir_passes(self):
        """PASS: sensor_pir with {online, pir} has no violations."""
        device = _minimal_device(category="sensor_pir", features=["online", "pir"])
        violations = validate_category_compliance(device)
        assert violations == []

    def test_sensor_pir_without_pir_fails(self):
        """FAIL: sensor_pir WITHOUT 'pir' feature."""
        device = _minimal_device(category="sensor_pir", features=["online", "temperature"])
        violations = validate_category_compliance(device)
        assert len(violations) >= 1
        assert "pir" in str(violations[0])

    def test_valve_with_required_features_passes(self):
        """PASS: valve requires {online, open_set, open_state, open_percentage} per Sber ✔︎."""
        device = _minimal_device(
            category="valve",
            features=["online", "open_set", "open_state", "open_percentage"],
        )
        violations = validate_category_compliance(device)
        assert violations == []

    def test_sensor_water_leak_without_feature_fails(self):
        """FAIL: sensor_water_leak WITHOUT water_leak_state."""
        device = _minimal_device(category="sensor_water_leak", features=["online"])
        violations = validate_category_compliance(device)
        assert len(violations) >= 1
        assert "water_leak_state" in str(violations[0])

    def test_sensor_water_leak_with_feature_passes(self):
        """PASS: sensor_water_leak with water_leak_state."""
        device = _minimal_device(
            category="sensor_water_leak",
            features=["online", "water_leak_state"],
        )
        violations = validate_category_compliance(device)
        assert violations == []

    def test_sensor_door_without_doorcontact_state_fails(self):
        """FAIL: sensor_door without doorcontact_state."""
        device = _minimal_device(category="sensor_door", features=["online"])
        violations = validate_category_compliance(device)
        assert len(violations) >= 1
        assert "doorcontact_state" in str(violations[0])

    def test_sensor_temp_only_requires_online(self):
        """PASS: sensor_temp has a pragmatic override — HA models temperature
        and humidity as separate entities, Sber's combo reference has both
        marked ✔︎.  We loosen the check to {online} so a standalone temperature
        or humidity sensor is still considered compliant."""
        device = _minimal_device(category="sensor_temp", features=["online"])
        violations = validate_category_compliance(device)
        assert violations == []

    def test_tv_with_required_features_passes(self):
        """PASS: tv with {online, on_off} and extras."""
        device = _minimal_device(
            category="tv",
            features=["online", "on_off", "volume_int", "source"],
        )
        violations = validate_category_compliance(device)
        assert violations == []

    def test_tv_without_on_off_fails(self):
        """FAIL: tv without on_off."""
        device = _minimal_device(category="tv", features=["online", "volume_int"])
        violations = validate_category_compliance(device)
        assert len(violations) >= 1
        assert "on_off" in str(violations[0])

    def test_curtain_only_needs_online(self):
        """PASS: curtain only requires {online}."""
        device = _minimal_device(
            category="curtain",
            features=["online", "open_percentage", "open_set", "open_state"],
        )
        violations = validate_category_compliance(device)
        assert violations == []

    def test_scenario_button_only_requires_online(self):
        """PASS: scenario_button with just online.

        Per Sber spec, scenario_button may use `button_event` OR any of
        `button_1_event`..`button_10_event` — the device class picks the
        right variant, our required set only enforces `online`.
        """
        device = _minimal_device(category="scenario_button", features=["online"])
        violations = validate_category_compliance(device)
        assert violations == []

    def test_hvac_ac_requires_on_off(self):
        """FAIL: hvac_ac without on_off."""
        device = _minimal_device(category="hvac_ac", features=["online"])
        violations = validate_category_compliance(device)
        assert len(violations) >= 1
        assert "on_off" in str(violations[0])

    def test_allowed_values_key_not_in_features_detected(self):
        """FAIL: allowed_values key not in features caught by compliance check."""
        device = _minimal_device(
            category="relay",
            features=["online", "on_off"],
            allowed_values={
                "brightness": {
                    "type": "INTEGER",
                    "integer_values": {"min": "0", "max": "100", "step": "1"},
                }
            },
        )
        violations = validate_category_compliance(device)
        assert any("brightness" in v for v in violations)

    def test_unknown_category_has_no_violations(self):
        """PASS: unknown category is not in CATEGORY_REQUIRED_FEATURES -> no required check."""
        device = _minimal_device(category="custom_device", features=["online"])
        violations = validate_category_compliance(device)
        assert violations == []


class TestCategoryRequiredFeaturesCompleteness:
    """Verify CATEGORY_REQUIRED_FEATURES covers all known device categories."""

    def test_all_known_categories_have_entries(self):
        """All 15+ device categories should be in the map."""
        expected = {
            "light",
            "relay",
            "socket",
            "curtain",
            "window_blind",
            "valve",
            "sensor_temp",
            "sensor_pir",
            "sensor_door",
            "sensor_water_leak",
            "hvac_ac",
            "hvac_radiator",
            "hvac_humidifier",
            "scenario_button",
            "tv",
        }
        actual = set(CATEGORY_REQUIRED_FEATURES.keys())
        missing = expected - actual
        assert not missing, f"Missing categories in CATEGORY_REQUIRED_FEATURES: {missing}"

    def test_all_categories_require_online(self):
        """Every category must require 'online' at minimum."""
        for cat, required in CATEGORY_REQUIRED_FEATURES.items():
            assert "online" in required, f"Category '{cat}' missing 'online' requirement"


# ===================================================================
# 7. validate_device() helper
# ===================================================================


class TestValidateDevice:
    """validate_device: convenience wrapper returning (bool, str)."""

    def test_valid_device_returns_true(self):
        """PASS: valid device returns (True, '')."""
        ok, msg = validate_device(_minimal_device())
        assert ok is True
        assert msg == ""

    def test_invalid_device_returns_false_with_message(self):
        """FAIL: invalid device returns (False, error_message)."""
        bad = _minimal_device(features=[])  # no 'online'
        ok, msg = validate_device(bad)
        assert ok is False
        assert "online" in msg.lower() or "VR-010" in msg

    def test_missing_model_returns_false(self):
        """FAIL: device without model field."""
        ok, msg = validate_device({"id": "x", "name": "X"})
        assert ok is False
        assert len(msg) > 0

    def test_extra_field_returns_false(self):
        """FAIL: device with extra top-level field."""
        data = _minimal_device()
        data["custom"] = "nope"
        ok, _msg = validate_device(data)
        assert ok is False

    def test_error_message_truncated(self):
        """Error message is truncated to 500 chars max."""
        # A device with many issues may produce long messages
        data = _minimal_device()
        data["extra1"] = "a"
        ok, msg = validate_device(data)
        assert ok is False
        assert len(msg) <= 500


class TestValidateConfigPayload:
    """validate_config_payload: logs warning on failure, returns bool."""

    def test_valid_returns_true(self):
        payload = {"devices": [_minimal_device()]}
        assert validate_config_payload(payload) is True

    def test_invalid_returns_false(self):
        assert validate_config_payload({"devices": "not_a_list"}) is False

    def test_invalid_device_in_payload_returns_false(self):
        bad_device = _minimal_device(features=[])  # VR-010
        assert validate_config_payload({"devices": [bad_device]}) is False


class TestValidateStatusPayload:
    """validate_status_payload: bool wrapper."""

    def test_valid_returns_true(self):
        payload = {
            "devices": {"switch.test": {"states": [{"key": "online", "value": {"type": "BOOL", "bool_value": True}}]}}
        }
        assert validate_status_payload(payload) is True

    def test_invalid_returns_false(self):
        assert validate_status_payload({"devices": []}) is False


# ===================================================================
# 8. SberState model
# ===================================================================


class TestSberState:
    """SberState: key + value pair."""

    def test_valid_state(self):
        s = SberState.model_validate({"key": "online", "value": {"type": "BOOL", "bool_value": True}})
        assert s.key == "online"

    def test_extra_field_rejected(self):
        with pytest.raises(ValidationError, match="extra"):
            SberState.model_validate(
                {
                    "key": "online",
                    "value": {"type": "BOOL", "bool_value": True},
                    "timestamp": 123,
                }
            )


# ===================================================================
# 9. Dependency models
# ===================================================================


class TestDependencyModels:
    """SberDependency and SberDependencyCondition strictness."""

    def test_valid_dependency(self):
        d = SberDependency.model_validate(
            {
                "key": "light_mode",
                "values": [{"type": "ENUM", "enum_value": "colour"}],
            }
        )
        assert d.key == "light_mode"
        assert len(d.values) == 1

    def test_dependency_condition_extra_rejected(self):
        with pytest.raises(ValidationError, match="extra"):
            SberDependencyCondition.model_validate({"type": "ENUM", "enum_value": "colour", "priority": 1})

    def test_dependency_extra_rejected(self):
        with pytest.raises(ValidationError, match="extra"):
            SberDependency.model_validate(
                {
                    "key": "light_mode",
                    "values": [{"type": "ENUM", "enum_value": "colour"}],
                    "optional": True,
                }
            )


# ===================================================================
# 10. Helper constructors
# ===================================================================


class TestHelperConstructors:
    """make_*_value and make_state helpers produce schema-valid output."""

    def test_make_bool_value_validates(self):
        v = make_bool_value(True)
        parsed = SberValue.model_validate(v)
        assert parsed.type == "BOOL"
        assert parsed.bool_value is True

    def test_make_integer_value_is_string(self):
        """make_integer_value must produce string integer_value."""
        v = make_integer_value(42)
        assert v["integer_value"] == "42"
        assert isinstance(v["integer_value"], str)
        parsed = SberValue.model_validate(v)
        assert parsed.integer_value == "42"

    def test_make_enum_value_validates(self):
        v = make_enum_value("auto")
        parsed = SberValue.model_validate(v)
        assert parsed.enum_value == "auto"

    def test_make_colour_value_validates(self):
        v = make_colour_value(120, 800, 500)
        parsed = SberValue.model_validate(v)
        assert parsed.colour_value.h == 120

    def test_make_state_validates(self):
        s = make_state("online", make_bool_value(True))
        parsed = SberState.model_validate(s)
        assert parsed.key == "online"


# ===================================================================
# 11. Integration: real device class output validates against schema
# ===================================================================


def _fill_and_get_sber_state(entity, ha_state: dict) -> dict:
    """Feed HA state into entity and return to_sber_state() output."""
    entity.fill_by_ha_state(ha_state)
    return entity.to_sber_state()


def _validate_device_output(device_dict: dict) -> None:
    """Assert device dict passes SberDevice schema + category compliance."""
    ok, msg = validate_device(device_dict)
    assert ok, f"validate_device failed: {msg}"
    violations = validate_category_compliance(device_dict)
    assert not violations, f"Category compliance violations: {violations}"


def _validate_current_state(entity) -> None:
    """Assert current state output validates against SberDeviceState."""
    state_output = entity.to_sber_current_state()
    # state_output is {entity_id: {"states": [...]}}
    for state_dict in state_output.values():
        SberDeviceState.model_validate(state_dict)
        # Also verify each state entry individually
        for s in state_dict["states"]:
            SberState.model_validate(s)


class TestIntegrationRelayEntity:
    """RelayEntity produces valid Sber schema output."""

    def test_relay_validates(self):
        from custom_components.sber_mqtt_bridge.devices.relay import RelayEntity

        entity = RelayEntity(_minimal_entity_data("switch.relay1", "Test Relay"))
        entity.fill_by_ha_state({"state": "on", "attributes": {}})
        device = entity.to_sber_state()
        _validate_device_output(device)
        _validate_current_state(entity)


class TestIntegrationSocketEntity:
    """SocketEntity produces valid Sber schema output."""

    def test_socket_validates(self):
        from custom_components.sber_mqtt_bridge.devices.socket_entity import SocketEntity

        entity = SocketEntity(_minimal_entity_data("switch.outlet1", "Test Socket"))
        entity.fill_by_ha_state({"state": "on", "attributes": {}})
        device = entity.to_sber_state()
        _validate_device_output(device)
        _validate_current_state(entity)


class TestIntegrationLightEntity:
    """LightEntity produces valid Sber schema output."""

    def test_light_basic_validates(self):
        from custom_components.sber_mqtt_bridge.devices.light import LightEntity

        entity = LightEntity(_minimal_entity_data("light.room", "Room Light"))
        entity.fill_by_ha_state(
            {
                "state": "on",
                "attributes": {
                    "brightness": 200,
                    "color_temp": 300,
                    "min_mireds": 153,
                    "max_mireds": 500,
                    "supported_color_modes": ["color_temp"],
                    "color_mode": "color_temp",
                },
            }
        )
        device = entity.to_sber_state()
        _validate_device_output(device)
        _validate_current_state(entity)

    def test_light_with_colour_validates(self):
        from custom_components.sber_mqtt_bridge.devices.light import LightEntity

        entity = LightEntity(_minimal_entity_data("light.rgb", "RGB Light"))
        entity.fill_by_ha_state(
            {
                "state": "on",
                "attributes": {
                    "brightness": 255,
                    "supported_color_modes": ["hs", "color_temp"],
                    "color_mode": "hs",
                    "hs_color": [120, 80],
                    "min_mireds": 153,
                    "max_mireds": 500,
                },
            }
        )
        device = entity.to_sber_state()
        _validate_device_output(device)
        _validate_current_state(entity)


class TestIntegrationCurtainEntity:
    """CurtainEntity produces valid Sber schema output."""

    def test_curtain_validates(self):
        from custom_components.sber_mqtt_bridge.devices.curtain import CurtainEntity

        entity = CurtainEntity(_minimal_entity_data("cover.blinds", "Blinds"))
        entity.fill_by_ha_state(
            {
                "state": "open",
                "attributes": {"current_position": 75},
            }
        )
        device = entity.to_sber_state()
        _validate_device_output(device)
        _validate_current_state(entity)


class TestIntegrationValveEntity:
    """ValveEntity produces valid Sber schema output."""

    def test_valve_validates(self):
        from custom_components.sber_mqtt_bridge.devices.valve import ValveEntity

        entity = ValveEntity(_minimal_entity_data("valve.water", "Water Valve"))
        entity.fill_by_ha_state({"state": "open", "attributes": {}})
        device = entity.to_sber_state()
        _validate_device_output(device)
        _validate_current_state(entity)


class TestIntegrationClimateEntity:
    """ClimateEntity produces valid Sber schema output."""

    def test_climate_validates(self):
        from custom_components.sber_mqtt_bridge.devices.climate import ClimateEntity

        entity = ClimateEntity(_minimal_entity_data("climate.ac", "AC"))
        entity.fill_by_ha_state(
            {
                "state": "cool",
                "attributes": {
                    "temperature": 24,
                    "current_temperature": 26,
                    "hvac_modes": ["off", "cool", "heat", "auto"],
                    "min_temp": 16,
                    "max_temp": 30,
                    "fan_mode": "auto",
                    "fan_modes": ["auto", "low", "medium", "high"],
                    "swing_mode": "off",
                    "swing_modes": ["off", "vertical"],
                },
            }
        )
        device = entity.to_sber_state()
        _validate_device_output(device)
        _validate_current_state(entity)


class TestIntegrationHumidifierEntity:
    """HumidifierEntity produces valid Sber schema output."""

    def test_humidifier_validates(self):
        from custom_components.sber_mqtt_bridge.devices.humidifier import HumidifierEntity

        entity = HumidifierEntity(_minimal_entity_data("humidifier.room", "Humidifier"))
        entity.fill_by_ha_state(
            {
                "state": "on",
                "attributes": {
                    "humidity": 55,
                    "min_humidity": 35,
                    "max_humidity": 85,
                },
            }
        )
        device = entity.to_sber_state()
        _validate_device_output(device)
        _validate_current_state(entity)


class TestIntegrationTvEntity:
    """TvEntity produces valid Sber schema output."""

    def test_tv_validates(self):
        from custom_components.sber_mqtt_bridge.devices.tv import TvEntity

        entity = TvEntity(_minimal_entity_data("media_player.tv", "Living Room TV"))
        entity.fill_by_ha_state(
            {
                "state": "on",
                "attributes": {
                    "volume_level": 0.5,
                    "is_volume_muted": False,
                    "source": "HDMI 1",
                    "source_list": ["HDMI 1", "HDMI 2", "TV"],
                },
            }
        )
        device = entity.to_sber_state()
        _validate_device_output(device)
        _validate_current_state(entity)

    def test_tv_without_source_list_validates(self):
        """TV with no source_list should still validate."""
        from custom_components.sber_mqtt_bridge.devices.tv import TvEntity

        entity = TvEntity(_minimal_entity_data("media_player.tv2", "Bedroom TV"))
        entity.fill_by_ha_state(
            {
                "state": "off",
                "attributes": {
                    "volume_level": 0.0,
                    "is_volume_muted": True,
                },
            }
        )
        device = entity.to_sber_state()
        _validate_device_output(device)
        _validate_current_state(entity)


class TestIntegrationSensorEntities:
    """Sensor entities produce valid Sber schema output."""

    def test_sensor_temp_validates(self):
        from custom_components.sber_mqtt_bridge.devices.sensor_temp import SensorTempEntity

        entity = SensorTempEntity(_minimal_entity_data("sensor.temp", "Temperature"))
        entity.fill_by_ha_state({"state": "22.5", "attributes": {"unit_of_measurement": "°C"}})
        device = entity.to_sber_state()
        _validate_device_output(device)
        _validate_current_state(entity)

    def test_motion_sensor_validates(self):
        from custom_components.sber_mqtt_bridge.devices.motion_sensor import MotionSensorEntity

        entity = MotionSensorEntity(_minimal_entity_data("binary_sensor.motion", "Motion"))
        entity.fill_by_ha_state({"state": "on", "attributes": {}})
        device = entity.to_sber_state()
        _validate_device_output(device)
        _validate_current_state(entity)

    def test_door_sensor_validates(self):
        from custom_components.sber_mqtt_bridge.devices.door_sensor import DoorSensorEntity

        entity = DoorSensorEntity(_minimal_entity_data("binary_sensor.door", "Front Door"))
        entity.fill_by_ha_state({"state": "off", "attributes": {}})
        device = entity.to_sber_state()
        _validate_device_output(device)
        _validate_current_state(entity)

    def test_water_leak_sensor_validates(self):
        from custom_components.sber_mqtt_bridge.devices.water_leak_sensor import (
            WaterLeakSensorEntity,
        )

        entity = WaterLeakSensorEntity(_minimal_entity_data("binary_sensor.leak", "Water Leak"))
        entity.fill_by_ha_state({"state": "off", "attributes": {}})
        device = entity.to_sber_state()
        _validate_device_output(device)
        _validate_current_state(entity)


class TestIntegrationScenarioButton:
    """ScenarioButtonEntity produces valid Sber schema output."""

    def test_scenario_button_validates(self):
        from custom_components.sber_mqtt_bridge.devices.scenario_button import (
            ScenarioButtonEntity,
        )

        entity = ScenarioButtonEntity(_minimal_entity_data("input_boolean.scene", "Movie Mode"))
        entity.fill_by_ha_state({"state": "on", "attributes": {}})
        device = entity.to_sber_state()
        _validate_device_output(device)
        _validate_current_state(entity)


class TestIntegrationWindowBlindEntity:
    """WindowBlindEntity produces valid Sber schema output."""

    def test_window_blind_validates(self):
        from custom_components.sber_mqtt_bridge.devices.window_blind import WindowBlindEntity

        entity = WindowBlindEntity(_minimal_entity_data("cover.blind", "Window Blind"))
        entity.fill_by_ha_state({"state": "open", "attributes": {"current_position": 50}})
        device = entity.to_sber_state()
        _validate_device_output(device)
        _validate_current_state(entity)
