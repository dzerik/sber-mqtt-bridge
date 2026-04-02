"""Sber C2C protocol compliance tests for LightEntity, ClimateEntity, HumidifierEntity.

Validates JSON output against Sber C2C documentation specification.
Focuses on catching common bugs: tuple vs list, string integers,
deprecated HA APIs, missing required fields, incorrect enum values.
"""

from __future__ import annotations

import pytest

from custom_components.sber_mqtt_bridge.devices.light import LightEntity
from custom_components.sber_mqtt_bridge.devices.climate import ClimateEntity
from custom_components.sber_mqtt_bridge.devices.humidifier import HumidifierEntity


# ---------------------------------------------------------------------------
# Helpers: entity data dicts
# ---------------------------------------------------------------------------

LIGHT_ENTITY_DATA = {"entity_id": "light.living_room", "name": "Living Room"}
CLIMATE_ENTITY_DATA = {"entity_id": "climate.ac", "name": "AC"}
HUMIDIFIER_ENTITY_DATA = {"entity_id": "humidifier.bedroom", "name": "Bedroom Humidifier"}

DEVICE_DATA = {
    "id": "device_123",
    "name": "Test Device",
    "area_id": "living_room",
    "manufacturer": "TestManufacturer",
    "model": "TestModel",
    "model_id": "test_model_id",
    "hw_version": "2.0",
    "sw_version": "3.1",
}


# ---------------------------------------------------------------------------
# Helpers: HA state builders
# ---------------------------------------------------------------------------


def _light_ha_state(
    *,
    state: str = "on",
    brightness: int = 200,
    color_temp: int = 300,
    min_mireds: int = 153,
    max_mireds: int = 500,
    supported_color_modes: list[str] | None = None,
    color_mode: str = "color_temp",
    hs_color: list[float] | tuple[float, ...] | None = None,
    rgb_color: list[int] | None = None,
    xy_color: list[float] | None = None,
    supported_features: int = 0,
) -> dict:
    """Build a HA state dict for a light entity."""
    if supported_color_modes is None:
        supported_color_modes = ["color_temp", "hs"]
    return {
        "entity_id": "light.living_room",
        "state": state,
        "attributes": {
            "brightness": brightness,
            "color_temp": color_temp,
            "min_mireds": min_mireds,
            "max_mireds": max_mireds,
            "supported_color_modes": supported_color_modes,
            "color_mode": color_mode,
            "supported_features": supported_features,
            "hs_color": hs_color if hs_color is not None else [30.0, 80.0],
            "rgb_color": rgb_color if rgb_color is not None else [255, 200, 50],
            "xy_color": xy_color if xy_color is not None else [0.5, 0.3],
        },
    }


def _climate_ha_state(
    *,
    state: str = "cool",
    current_temperature: float = 24.5,
    temperature: float = 22.0,
    fan_modes: list[str] | None = None,
    swing_modes: list[str] | None = None,
    hvac_modes: list[str] | None = None,
    fan_mode: str = "auto",
    swing_mode: str = "off",
    min_temp: float = 16.0,
    max_temp: float = 32.0,
    target_humidity: int | None = None,
    preset_mode: str | None = None,
    preset_modes: list[str] | None = None,
    child_lock: bool | None = None,
) -> dict:
    """Build a HA state dict for a climate entity."""
    if fan_modes is None:
        fan_modes = ["auto", "low", "medium", "high"]
    if swing_modes is None:
        swing_modes = ["off", "vertical", "horizontal"]
    if hvac_modes is None:
        hvac_modes = ["off", "cool", "heat", "fan_only", "dry"]
    attrs: dict = {
        "current_temperature": current_temperature,
        "temperature": temperature,
        "fan_modes": fan_modes,
        "swing_modes": swing_modes,
        "hvac_modes": hvac_modes,
        "fan_mode": fan_mode,
        "swing_mode": swing_mode,
        "min_temp": min_temp,
        "max_temp": max_temp,
    }
    if target_humidity is not None:
        attrs["target_humidity"] = target_humidity
    if preset_mode is not None:
        attrs["preset_mode"] = preset_mode
    if preset_modes is not None:
        attrs["preset_modes"] = preset_modes
    if child_lock is not None:
        attrs["child_lock"] = child_lock
    return {
        "entity_id": "climate.ac",
        "state": state,
        "attributes": attrs,
    }


def _humidifier_ha_state(
    *,
    state: str = "on",
    humidity: int = 50,
    current_humidity: float = 45.0,
    available_modes: list[str] | None = None,
    mode: str = "normal",
    min_humidity: int = 35,
    max_humidity: int = 85,
    water_level: int | None = None,
    water_low_level: bool | None = None,
    child_lock: bool | None = None,
) -> dict:
    """Build a HA state dict for a humidifier entity."""
    if available_modes is None:
        available_modes = ["normal", "sleep", "auto", "high"]
    attrs: dict = {
        "humidity": humidity,
        "current_humidity": current_humidity,
        "available_modes": available_modes,
        "mode": mode,
        "min_humidity": min_humidity,
        "max_humidity": max_humidity,
    }
    if water_level is not None:
        attrs["water_level"] = water_level
    if water_low_level is not None:
        attrs["water_low_level"] = water_low_level
    if child_lock is not None:
        attrs["child_lock"] = child_lock
    return {
        "entity_id": "humidifier.bedroom",
        "state": state,
        "attributes": attrs,
    }


# ---------------------------------------------------------------------------
# Helpers: state payload inspection
# ---------------------------------------------------------------------------


def _find_state_by_key(states: list[dict], key: str) -> dict | None:
    """Find a state entry by its 'key' field in a Sber states list."""
    for s in states:
        if s.get("key") == key:
            return s
    return None


def _get_states_list(entity) -> list[dict]:
    """Extract the states list from a to_sber_current_state() call."""
    result = entity.to_sber_current_state()
    entity_id = entity.entity_id
    return result[entity_id]["states"]


# ---------------------------------------------------------------------------
# Helpers: Sber command builders
# ---------------------------------------------------------------------------


def _sber_cmd(states: list[dict]) -> dict:
    """Wrap a list of state dicts into a Sber command payload."""
    return {"states": states}


def _bool_cmd(key: str, value: bool) -> dict:
    return {"key": key, "value": {"type": "BOOL", "bool_value": value}}


def _int_cmd(key: str, value: str) -> dict:
    return {"key": key, "value": {"type": "INTEGER", "integer_value": value}}


def _enum_cmd(key: str, value: str) -> dict:
    return {"key": key, "value": {"type": "ENUM", "enum_value": value}}


def _colour_cmd(h: int, s: int, v: int) -> dict:
    return {
        "key": "light_colour",
        "value": {"type": "COLOUR", "colour_value": {"h": h, "s": s, "v": v}},
    }


# ===========================================================================
# 1. LightEntity — Config JSON (to_sber_state)
# ===========================================================================


class TestLightConfigJson:
    """Validate LightEntity.to_sber_state() output against Sber C2C spec."""

    def _make_light(self, *, with_device: bool = False, **state_kw) -> LightEntity:
        entity = LightEntity(LIGHT_ENTITY_DATA)
        entity.fill_by_ha_state(_light_ha_state(**state_kw))
        if with_device:
            entity.device_id = DEVICE_DATA["id"]
            entity.link_device(DEVICE_DATA)
        return entity

    def test_required_top_level_fields_present(self):
        """to_sber_state must include id, name, default_name, room, model."""
        config = self._make_light().to_sber_state()
        for field in ("id", "name", "default_name", "room", "model"):
            assert field in config, f"Missing required field: {field}"

    def test_model_required_fields(self):
        """model must have id, manufacturer, model, description, category, features."""
        model = self._make_light().to_sber_state()["model"]
        for field in ("id", "manufacturer", "model", "description", "category", "features"):
            assert field in model, f"Missing model field: {field}"

    def test_category_is_light(self):
        """Category must be 'light' per Sber C2C spec."""
        config = self._make_light().to_sber_state()
        assert config["model"]["category"] == "light"

    def test_hw_sw_version_present_and_not_unknown_with_device(self):
        """hw_version/sw_version must be present and NOT 'Unknown' when device is linked."""
        config = self._make_light(with_device=True).to_sber_state()
        assert config["hw_version"] != "Unknown"
        assert config["sw_version"] != "Unknown"
        assert config["hw_version"] == "2.0"
        assert config["sw_version"] == "3.1"

    def test_hw_sw_version_present_without_device(self):
        """hw_version/sw_version must still be present even without a linked device."""
        config = self._make_light().to_sber_state()
        assert "hw_version" in config
        assert "sw_version" in config
        # Default values should not be literally "Unknown"
        assert config["hw_version"] != "Unknown"
        assert config["sw_version"] != "Unknown"

    def test_features_include_online_and_on_off(self):
        """All lights must have 'online' and 'on_off' features."""
        features = self._make_light().to_sber_state()["model"]["features"]
        assert "online" in features
        assert "on_off" in features

    def test_features_brightness_mode(self):
        """Brightness-only lights include light_brightness but not light_colour."""
        entity = self._make_light(
            supported_color_modes=["brightness"],
            color_mode="brightness",
        )
        features = entity.to_sber_state()["model"]["features"]
        assert "light_brightness" in features
        assert "light_colour" not in features
        assert "light_mode" not in features

    def test_features_color_mode(self):
        """Color lights include light_colour, light_mode, and light_brightness."""
        entity = self._make_light(
            supported_color_modes=["hs", "color_temp"],
            color_mode="hs",
        )
        features = entity.to_sber_state()["model"]["features"]
        assert "light_colour" in features
        assert "light_mode" in features
        assert "light_brightness" in features

    def test_features_color_temp_mode(self):
        """Color-temp lights include light_colour_temp feature."""
        entity = self._make_light(
            supported_color_modes=["color_temp"],
            color_mode="color_temp",
        )
        features = entity.to_sber_state()["model"]["features"]
        assert "light_colour_temp" in features

    def test_allowed_values_integer_structure(self):
        """INTEGER allowed_values must have min/max/step as STRINGS."""
        entity = self._make_light(
            supported_color_modes=["hs", "color_temp"],
            color_mode="hs",
        )
        config = entity.to_sber_state()
        av = config["model"]["allowed_values"]

        brightness_av = av["light_brightness"]
        assert brightness_av["type"] == "INTEGER"
        iv = brightness_av["integer_values"]
        assert isinstance(iv["min"], str), "min must be a string"
        assert isinstance(iv["max"], str), "max must be a string"
        assert isinstance(iv["step"], str), "step must be a string"

    def test_allowed_values_enum_structure(self):
        """ENUM allowed_values must use enum_values.values (list), not 'value'."""
        entity = self._make_light(
            supported_color_modes=["hs", "color_temp"],
            color_mode="hs",
        )
        config = entity.to_sber_state()
        av = config["model"]["allowed_values"]

        light_mode_av = av["light_mode"]
        assert light_mode_av["type"] == "ENUM"
        assert "enum_values" in light_mode_av
        assert "values" in light_mode_av["enum_values"], "Must use 'values' key, not 'value'"
        assert isinstance(light_mode_av["enum_values"]["values"], list)
        assert "white" in light_mode_av["enum_values"]["values"]
        assert "colour" in light_mode_av["enum_values"]["values"]

    def test_dependencies_uses_values_not_value(self):
        """CRITICAL: dependencies must use 'values' key, NOT 'value'."""
        entity = self._make_light(
            supported_color_modes=["hs", "color_temp"],
            color_mode="hs",
        )
        config = entity.to_sber_state()
        deps = config["model"].get("dependencies", {})
        if "light_colour" in deps:
            dep = deps["light_colour"]
            assert "values" in dep, "Dependencies must use 'values', not 'value'"
            assert "value" not in dep, "Dependencies must NOT use 'value' key"


# ===========================================================================
# 2. LightEntity — State JSON (to_sber_current_state)
# ===========================================================================


class TestLightStateJson:
    """Validate LightEntity.to_sber_current_state() against Sber C2C spec."""

    def _make_light(self, **state_kw) -> LightEntity:
        entity = LightEntity(LIGHT_ENTITY_DATA)
        entity.fill_by_ha_state(_light_ha_state(**state_kw))
        return entity

    def test_online_always_present(self):
        """'online' BOOL must always be present in state."""
        states = _get_states_list(self._make_light())
        online = _find_state_by_key(states, "online")
        assert online is not None, "online state missing"
        assert online["value"]["type"] == "BOOL"

    def test_on_off_always_present(self):
        """'on_off' BOOL must always be present."""
        states = _get_states_list(self._make_light())
        on_off = _find_state_by_key(states, "on_off")
        assert on_off is not None
        assert on_off["value"]["type"] == "BOOL"
        assert on_off["value"]["bool_value"] is True

    def test_integer_value_serialized_as_string(self):
        """CRITICAL: integer_value must be a string, not an int."""
        entity = self._make_light(brightness=200)
        states = _get_states_list(entity)
        brightness = _find_state_by_key(states, "light_brightness")
        assert brightness is not None
        iv = brightness["value"]["integer_value"]
        assert isinstance(iv, str), f"integer_value must be str, got {type(iv).__name__}: {iv!r}"

    def test_color_temp_integer_value_is_string(self):
        """Color temp integer_value must be string."""
        entity = self._make_light(
            color_mode="color_temp",
            color_temp=300,
            supported_color_modes=["color_temp", "hs"],
        )
        states = _get_states_list(entity)
        ct = _find_state_by_key(states, "light_colour_temp")
        assert ct is not None
        assert isinstance(ct["value"]["integer_value"], str)

    def test_light_mode_enum_values(self):
        """light_mode ENUM must be exactly 'white' or 'colour' per Sber spec."""
        # White mode
        entity_white = self._make_light(
            color_mode="color_temp",
            supported_color_modes=["color_temp", "hs"],
        )
        states = _get_states_list(entity_white)
        mode = _find_state_by_key(states, "light_mode")
        assert mode is not None
        assert mode["value"]["enum_value"] in ("white", "colour")

    def test_colour_mode_emits_colour_value(self):
        """In colour mode, light_colour must have colour_value with h/s/v integers."""
        entity = self._make_light(
            color_mode="hs",
            hs_color=[120.0, 80.0],
            brightness=200,
            supported_color_modes=["hs", "color_temp"],
        )
        states = _get_states_list(entity)
        colour = _find_state_by_key(states, "light_colour")
        assert colour is not None, "light_colour state missing in colour mode"
        cv = colour["value"]["colour_value"]
        assert isinstance(cv["h"], int), f"h must be int, got {type(cv['h']).__name__}"
        assert isinstance(cv["s"], int), f"s must be int, got {type(cv['s']).__name__}"
        assert isinstance(cv["v"], int), f"v must be int, got {type(cv['v']).__name__}"

    def test_hs_color_as_tuple_works(self):
        """CRITICAL: hs_color can be a tuple (from HA) - must not crash."""
        entity = LightEntity(LIGHT_ENTITY_DATA)
        ha_state = _light_ha_state(
            color_mode="hs",
            hs_color=(120.0, 80.0),
            supported_color_modes=["hs", "color_temp"],
            brightness=200,
        )
        entity.fill_by_ha_state(ha_state)
        # Must not raise TypeError
        states = _get_states_list(entity)
        colour = _find_state_by_key(states, "light_colour")
        assert colour is not None, "light_colour must work with tuple hs_color"

    def test_hs_color_as_list_works(self):
        """hs_color as a list must also produce valid colour state."""
        entity = self._make_light(
            color_mode="hs",
            hs_color=[120.0, 80.0],
            supported_color_modes=["hs", "color_temp"],
            brightness=200,
        )
        states = _get_states_list(entity)
        colour = _find_state_by_key(states, "light_colour")
        assert colour is not None

    def test_offline_state(self):
        """Unavailable entity must report online=False."""
        entity = self._make_light(state="unavailable")
        states = _get_states_list(entity)
        online = _find_state_by_key(states, "online")
        assert online["value"]["bool_value"] is False

    def test_light_mode_white_when_color_temp(self):
        """When color_mode is color_temp, light_mode must be 'white'."""
        entity = self._make_light(
            color_mode="color_temp",
            supported_color_modes=["color_temp", "hs"],
        )
        states = _get_states_list(entity)
        mode = _find_state_by_key(states, "light_mode")
        assert mode is not None
        assert mode["value"]["enum_value"] == "white"

    def test_light_mode_colour_when_hs(self):
        """When color_mode is hs, light_mode must be 'colour'."""
        entity = self._make_light(
            color_mode="hs",
            hs_color=[120.0, 50.0],
            supported_color_modes=["color_temp", "hs"],
            brightness=200,
        )
        states = _get_states_list(entity)
        mode = _find_state_by_key(states, "light_mode")
        assert mode is not None
        assert mode["value"]["enum_value"] == "colour"


# ===========================================================================
# 3. LightEntity — Command Processing (process_cmd)
# ===========================================================================


class TestLightProcessCmd:
    """Validate LightEntity.process_cmd() produces correct HA service calls."""

    def _make_light(self, **state_kw) -> LightEntity:
        entity = LightEntity(LIGHT_ENTITY_DATA)
        entity.fill_by_ha_state(_light_ha_state(**state_kw))
        return entity

    def test_on_off_turn_on(self):
        """on_off=True produces light.turn_on call."""
        entity = self._make_light()
        result = entity.process_cmd(_sber_cmd([_bool_cmd("on_off", True)]))
        assert len(result) == 1
        url = result[0]["url"]
        assert url["domain"] == "light"
        assert url["service"] == "turn_on"
        assert url["target"]["entity_id"] == "light.living_room"

    def test_on_off_turn_off(self):
        """on_off=False produces light.turn_off call."""
        entity = self._make_light()
        result = entity.process_cmd(_sber_cmd([_bool_cmd("on_off", False)]))
        assert len(result) == 1
        assert result[0]["url"]["service"] == "turn_off"

    def test_brightness_command(self):
        """light_brightness INTEGER produces turn_on with brightness."""
        entity = self._make_light()
        result = entity.process_cmd(_sber_cmd([_int_cmd("light_brightness", "500")]))
        assert len(result) == 1
        url = result[0]["url"]
        assert url["service"] == "turn_on"
        assert "brightness" in url["service_data"]
        br = url["service_data"]["brightness"]
        assert isinstance(br, int)
        assert 0 <= br <= 255

    def test_colour_command_produces_hs_color(self):
        """light_colour COLOUR produces turn_on with hs_color and brightness."""
        entity = self._make_light()
        result = entity.process_cmd(_sber_cmd([_colour_cmd(120, 500, 800)]))
        assert len(result) == 1
        url = result[0]["url"]
        assert url["service"] == "turn_on"
        assert "hs_color" in url["service_data"]
        assert "brightness" in url["service_data"]

    def test_colour_command_brightness_at_least_one(self):
        """CRITICAL: brightness must be >= 1 on colour command to avoid turning off."""
        entity = self._make_light()
        result = entity.process_cmd(_sber_cmd([_colour_cmd(0, 0, 0)]))
        assert len(result) == 1
        url = result[0]["url"]
        assert url["service_data"]["brightness"] >= 1

    def test_color_temp_uses_kelvin_not_mireds(self):
        """CRITICAL: light_colour_temp must use color_temp_kelvin, NOT deprecated color_temp."""
        entity = self._make_light()
        result = entity.process_cmd(_sber_cmd([_int_cmd("light_colour_temp", "500")]))
        assert len(result) == 1
        sd = result[0]["url"]["service_data"]
        assert "color_temp_kelvin" in sd, "Must use color_temp_kelvin for HA 2025+"
        assert "color_temp" not in sd, "Must NOT use deprecated color_temp"

    def test_light_mode_white_uses_kelvin(self):
        """Switching to white mode via light_mode must use color_temp_kelvin."""
        entity = self._make_light(
            color_mode="hs",
            supported_color_modes=["hs", "color_temp"],
        )
        result = entity.process_cmd(_sber_cmd([_enum_cmd("light_mode", "white")]))
        assert len(result) >= 1
        # Find the service call (not update_state)
        calls = [r for r in result if "url" in r]
        if calls:
            sd = calls[0]["url"]["service_data"]
            assert "color_temp_kelvin" in sd, "white mode switch must use color_temp_kelvin"
            assert "color_temp" not in sd

    def test_light_mode_colour_uses_hs_color(self):
        """Switching to colour mode must send hs_color to HA."""
        entity = self._make_light(
            color_mode="color_temp",
            hs_color=[120.0, 80.0],
            supported_color_modes=["hs", "color_temp"],
        )
        result = entity.process_cmd(_sber_cmd([_enum_cmd("light_mode", "colour")]))
        calls = [r for r in result if "url" in r]
        assert len(calls) >= 1
        sd = calls[0]["url"]["service_data"]
        assert "hs_color" in sd

    def test_unknown_command_does_not_crash(self):
        """Unknown Sber commands must not raise exceptions."""
        entity = self._make_light()
        result = entity.process_cmd(_sber_cmd([_enum_cmd("unknown_feature", "value")]))
        assert isinstance(result, list)

    def test_none_cmd_data_returns_empty(self):
        """process_cmd(None) must return empty list, not crash."""
        entity = self._make_light()
        result = entity.process_cmd(None)
        assert result == []

    def test_empty_states_returns_empty(self):
        """process_cmd with empty states must return empty list."""
        entity = self._make_light()
        result = entity.process_cmd({"states": []})
        assert result == []


# ===========================================================================
# 4. ClimateEntity — Config JSON (to_sber_state)
# ===========================================================================


class TestClimateConfigJson:
    """Validate ClimateEntity.to_sber_state() against Sber C2C spec."""

    def _make_climate(self, *, with_device: bool = False, **state_kw) -> ClimateEntity:
        entity = ClimateEntity(CLIMATE_ENTITY_DATA)
        entity.fill_by_ha_state(_climate_ha_state(**state_kw))
        if with_device:
            entity.device_id = DEVICE_DATA["id"]
            entity.link_device(DEVICE_DATA)
        return entity

    def test_category_is_hvac_ac(self):
        """Category must be 'hvac_ac' per Sber C2C spec."""
        config = self._make_climate().to_sber_state()
        assert config["model"]["category"] == "hvac_ac"

    def test_required_top_level_fields(self):
        """All required top-level fields must be present."""
        config = self._make_climate().to_sber_state()
        for field in ("id", "name", "default_name", "room", "model", "hw_version", "sw_version"):
            assert field in config, f"Missing required field: {field}"

    def test_model_required_fields(self):
        """Model must have all required Sber fields."""
        model = self._make_climate().to_sber_state()["model"]
        for field in ("id", "manufacturer", "model", "description", "category", "features"):
            assert field in model, f"Missing model field: {field}"

    def test_features_include_core(self):
        """Climate must always have online, on_off, temperature, hvac_temp_set."""
        features = self._make_climate().to_sber_state()["model"]["features"]
        for f in ("online", "on_off", "temperature", "hvac_temp_set"):
            assert f in features, f"Missing core feature: {f}"

    def test_features_fan_modes(self):
        """hvac_air_flow_power included when fan_modes available."""
        features = self._make_climate(fan_modes=["auto", "low"]).to_sber_state()["model"]["features"]
        assert "hvac_air_flow_power" in features

    def test_features_hvac_modes(self):
        """hvac_work_mode included when hvac_modes available."""
        features = self._make_climate(
            hvac_modes=["off", "cool", "heat"],
        ).to_sber_state()["model"]["features"]
        assert "hvac_work_mode" in features

    def test_features_swing_modes(self):
        """hvac_air_flow_direction included when swing_modes available."""
        features = self._make_climate(
            swing_modes=["off", "vertical"],
        ).to_sber_state()["model"]["features"]
        assert "hvac_air_flow_direction" in features

    def test_features_night_mode(self):
        """hvac_night_mode included when sleep/night preset available."""
        features = self._make_climate(
            preset_modes=["sleep", "none"],
        ).to_sber_state()["model"]["features"]
        assert "hvac_night_mode" in features

    def test_features_child_lock(self):
        """child_lock included when available."""
        features = self._make_climate(child_lock=True).to_sber_state()["model"]["features"]
        assert "child_lock" in features

    def test_features_humidity_set(self):
        """hvac_humidity_set included when target_humidity available."""
        features = self._make_climate(target_humidity=50).to_sber_state()["model"]["features"]
        assert "hvac_humidity_set" in features

    def test_allowed_values_hvac_temp_set_integer_strings(self):
        """hvac_temp_set INTEGER allowed_values must have min/max/step as strings."""
        config = self._make_climate(min_temp=16.0, max_temp=32.0).to_sber_state()
        av = config["model"]["allowed_values"]["hvac_temp_set"]
        assert av["type"] == "INTEGER"
        iv = av["integer_values"]
        assert iv["min"] == "16"
        assert iv["max"] == "32"
        assert isinstance(iv["step"], str)

    def test_allowed_values_enum_uses_values_key(self):
        """ENUM allowed_values must use 'values' key (not 'value')."""
        config = self._make_climate(
            fan_modes=["auto", "low", "high"],
        ).to_sber_state()
        av = config["model"]["allowed_values"]["hvac_air_flow_power"]
        assert av["type"] == "ENUM"
        assert "values" in av["enum_values"], "Must use 'values' key"
        assert isinstance(av["enum_values"]["values"], list)

    @pytest.mark.parametrize(
        "ha_mode,sber_mode",
        [
            ("cool", "cooling"),
            ("heat", "heating"),
            ("fan_only", "ventilation"),
            ("dry", "dehumidification"),
            ("auto", "auto"),
            ("heat_cool", "auto"),
        ],
    )
    def test_hvac_work_mode_enum_values(self, ha_mode: str, sber_mode: str):
        """Sber work mode enum values must match Sber documentation exactly."""
        config = self._make_climate(
            hvac_modes=["off", ha_mode],
        ).to_sber_state()
        av = config["model"]["allowed_values"]
        if "hvac_work_mode" in av:
            values = av["hvac_work_mode"]["enum_values"]["values"]
            assert sber_mode in values, f"Sber mode '{sber_mode}' missing for HA '{ha_mode}'"

    def test_hw_sw_version_with_device(self):
        """Linked device must provide real hw/sw version, not 'Unknown'."""
        config = self._make_climate(with_device=True).to_sber_state()
        assert config["hw_version"] != "Unknown"
        assert config["sw_version"] != "Unknown"


# ===========================================================================
# 5. ClimateEntity — State JSON (to_sber_current_state)
# ===========================================================================


class TestClimateStateJson:
    """Validate ClimateEntity.to_sber_current_state() against Sber C2C spec."""

    def _make_climate(self, **state_kw) -> ClimateEntity:
        entity = ClimateEntity(CLIMATE_ENTITY_DATA)
        entity.fill_by_ha_state(_climate_ha_state(**state_kw))
        return entity

    def test_online_always_present(self):
        """online BOOL must always be present."""
        states = _get_states_list(self._make_climate())
        online = _find_state_by_key(states, "online")
        assert online is not None
        assert online["value"]["type"] == "BOOL"

    def test_temperature_x10_encoding(self):
        """temperature uses x10 encoding: 24.5C -> '245' as string."""
        entity = self._make_climate(current_temperature=24.5)
        states = _get_states_list(entity)
        temp = _find_state_by_key(states, "temperature")
        assert temp is not None
        assert temp["value"]["type"] == "INTEGER"
        assert temp["value"]["integer_value"] == "245"

    def test_temperature_integer_value_is_string(self):
        """temperature integer_value must be string per Sber spec."""
        entity = self._make_climate(current_temperature=22.0)
        states = _get_states_list(entity)
        temp = _find_state_by_key(states, "temperature")
        iv = temp["value"]["integer_value"]
        assert isinstance(iv, str), f"temperature integer_value must be str, got {type(iv).__name__}"

    def test_hvac_temp_set_integer_string(self):
        """hvac_temp_set integer_value must be string."""
        entity = self._make_climate(temperature=22.0)
        states = _get_states_list(entity)
        ts = _find_state_by_key(states, "hvac_temp_set")
        assert ts is not None
        iv = ts["value"]["integer_value"]
        assert isinstance(iv, str), f"hvac_temp_set must be str, got {type(iv).__name__}"
        assert iv == "22"

    @pytest.mark.parametrize(
        "ha_mode,expected_sber",
        [
            ("cool", "cooling"),
            ("heat", "heating"),
            ("fan_only", "ventilation"),
            ("dry", "dehumidification"),
        ],
    )
    def test_hvac_work_mode_enum_values_match_sber_docs(self, ha_mode: str, expected_sber: str):
        """ENUM values in state must match Sber-documented values exactly."""
        entity = self._make_climate(
            state=ha_mode,
            hvac_modes=["off", ha_mode],
        )
        states = _get_states_list(entity)
        wm = _find_state_by_key(states, "hvac_work_mode")
        assert wm is not None, f"hvac_work_mode missing for HA mode '{ha_mode}'"
        assert wm["value"]["enum_value"] == expected_sber

    def test_hvac_work_mode_not_present_when_off(self):
        """hvac_work_mode should not be emitted when state is 'off'."""
        entity = self._make_climate(state="off")
        states = _get_states_list(entity)
        wm = _find_state_by_key(states, "hvac_work_mode")
        assert wm is None, "hvac_work_mode must not be emitted when off"

    @pytest.mark.parametrize("ha_fan,expected_sber", [
        ("auto", "auto"),
        ("low", "low"),
        ("medium", "medium"),
        ("high", "high"),
    ])
    def test_fan_mode_enum_values(self, ha_fan: str, expected_sber: str):
        """Fan mode ENUM must use Sber naming convention."""
        entity = self._make_climate(
            fan_mode=ha_fan,
            fan_modes=["auto", "low", "medium", "high"],
        )
        states = _get_states_list(entity)
        fp = _find_state_by_key(states, "hvac_air_flow_power")
        assert fp is not None
        assert fp["value"]["enum_value"] == expected_sber

    def test_child_lock_bool_type(self):
        """child_lock must be a BOOL value."""
        entity = self._make_climate(child_lock=True)
        states = _get_states_list(entity)
        cl = _find_state_by_key(states, "child_lock")
        assert cl is not None
        assert cl["value"]["type"] == "BOOL"
        assert cl["value"]["bool_value"] is True

    def test_offline_when_unavailable(self):
        """online must be False when entity is unavailable."""
        entity = self._make_climate(state="unavailable")
        states = _get_states_list(entity)
        online = _find_state_by_key(states, "online")
        assert online["value"]["bool_value"] is False


# ===========================================================================
# 6. ClimateEntity — Command Processing (process_cmd)
# ===========================================================================


class TestClimateProcessCmd:
    """Validate ClimateEntity.process_cmd() produces correct HA calls."""

    def _make_climate(self, **state_kw) -> ClimateEntity:
        entity = ClimateEntity(CLIMATE_ENTITY_DATA)
        entity.fill_by_ha_state(_climate_ha_state(**state_kw))
        return entity

    def test_on_off_turn_on(self):
        """on_off=True produces climate.turn_on."""
        entity = self._make_climate()
        result = entity.process_cmd(_sber_cmd([_bool_cmd("on_off", True)]))
        assert len(result) == 1
        url = result[0]["url"]
        assert url["domain"] == "climate"
        assert url["service"] == "turn_on"

    def test_on_off_turn_off(self):
        """on_off=False produces climate.turn_off."""
        entity = self._make_climate()
        result = entity.process_cmd(_sber_cmd([_bool_cmd("on_off", False)]))
        assert result[0]["url"]["service"] == "turn_off"

    def test_hvac_temp_set_command(self):
        """hvac_temp_set INTEGER produces climate.set_temperature."""
        entity = self._make_climate()
        result = entity.process_cmd(_sber_cmd([_int_cmd("hvac_temp_set", "24")]))
        assert len(result) == 1
        url = result[0]["url"]
        assert url["service"] == "set_temperature"
        assert url["service_data"]["temperature"] == 24.0

    def test_hvac_work_mode_command(self):
        """hvac_work_mode ENUM produces climate.set_hvac_mode."""
        entity = self._make_climate(hvac_modes=["off", "cool", "heat"])
        result = entity.process_cmd(_sber_cmd([_enum_cmd("hvac_work_mode", "cooling")]))
        assert len(result) == 1
        url = result[0]["url"]
        assert url["service"] == "set_hvac_mode"
        assert url["service_data"]["hvac_mode"] == "cool"

    def test_hvac_air_flow_power_command(self):
        """hvac_air_flow_power ENUM produces climate.set_fan_mode."""
        entity = self._make_climate(fan_modes=["auto", "low", "high"])
        result = entity.process_cmd(_sber_cmd([_enum_cmd("hvac_air_flow_power", "low")]))
        assert len(result) == 1
        url = result[0]["url"]
        assert url["service"] == "set_fan_mode"
        assert url["service_data"]["fan_mode"] == "low"

    def test_unknown_command_does_not_crash(self):
        """Unknown Sber commands must not raise exceptions."""
        entity = self._make_climate()
        result = entity.process_cmd(_sber_cmd([_enum_cmd("unknown_key", "value")]))
        assert isinstance(result, list)

    def test_night_mode_on(self):
        """hvac_night_mode=True sets preset_mode to sleep/night."""
        entity = self._make_climate(preset_modes=["sleep", "none"])
        result = entity.process_cmd(_sber_cmd([_bool_cmd("hvac_night_mode", True)]))
        assert len(result) == 1
        url = result[0]["url"]
        assert url["service"] == "set_preset_mode"
        assert url["service_data"]["preset_mode"] in ("sleep", "night")

    def test_night_mode_off(self):
        """hvac_night_mode=False sets preset_mode to none."""
        entity = self._make_climate(preset_modes=["sleep", "none"])
        result = entity.process_cmd(_sber_cmd([_bool_cmd("hvac_night_mode", False)]))
        assert len(result) == 1
        url = result[0]["url"]
        assert url["service"] == "set_preset_mode"
        assert url["service_data"]["preset_mode"] == "none"

    def test_empty_states_returns_empty(self):
        """Empty states must return empty list."""
        entity = self._make_climate()
        result = entity.process_cmd({"states": []})
        assert result == []


# ===========================================================================
# 7. HumidifierEntity — Config JSON (to_sber_state)
# ===========================================================================


class TestHumidifierConfigJson:
    """Validate HumidifierEntity.to_sber_state() against Sber C2C spec."""

    def _make_humidifier(self, *, with_device: bool = False, **state_kw) -> HumidifierEntity:
        entity = HumidifierEntity(HUMIDIFIER_ENTITY_DATA)
        entity.fill_by_ha_state(_humidifier_ha_state(**state_kw))
        if with_device:
            entity.device_id = DEVICE_DATA["id"]
            entity.link_device(DEVICE_DATA)
        return entity

    def test_category_is_hvac_humidifier(self):
        """Category must be 'hvac_humidifier' per Sber C2C spec."""
        config = self._make_humidifier().to_sber_state()
        assert config["model"]["category"] == "hvac_humidifier"

    def test_required_top_level_fields(self):
        """All required top-level fields must be present."""
        config = self._make_humidifier().to_sber_state()
        for field in ("id", "name", "default_name", "room", "model", "hw_version", "sw_version"):
            assert field in config, f"Missing required field: {field}"

    def test_features_include_core(self):
        """Humidifier must always have online, on_off, humidity, hvac_humidity_set."""
        features = self._make_humidifier().to_sber_state()["model"]["features"]
        for f in ("online", "on_off", "humidity", "hvac_humidity_set"):
            assert f in features, f"Missing core feature: {f}"

    def test_features_air_flow_power_when_modes(self):
        """hvac_air_flow_power included when available_modes is non-empty."""
        features = self._make_humidifier(
            available_modes=["normal", "auto"],
        ).to_sber_state()["model"]["features"]
        assert "hvac_air_flow_power" in features

    def test_features_no_air_flow_power_without_modes(self):
        """hvac_air_flow_power excluded when no available_modes."""
        features = self._make_humidifier(
            available_modes=[],
        ).to_sber_state()["model"]["features"]
        assert "hvac_air_flow_power" not in features

    def test_features_night_mode(self):
        """hvac_night_mode included when sleep/night is available."""
        features = self._make_humidifier(
            available_modes=["normal", "sleep"],
        ).to_sber_state()["model"]["features"]
        assert "hvac_night_mode" in features

    def test_features_child_lock(self):
        """child_lock included when available."""
        features = self._make_humidifier(child_lock=False).to_sber_state()["model"]["features"]
        assert "child_lock" in features

    def test_features_water_percentage(self):
        """hvac_water_percentage included when water_level available."""
        features = self._make_humidifier(water_level=60).to_sber_state()["model"]["features"]
        assert "hvac_water_percentage" in features

    def test_features_water_low_level(self):
        """hvac_water_low_level included when water_low_level available."""
        features = self._make_humidifier(water_low_level=False).to_sber_state()["model"]["features"]
        assert "hvac_water_low_level" in features

    def test_allowed_values_humidity_set_integer_strings(self):
        """hvac_humidity_set must have min/max/step as strings."""
        config = self._make_humidifier(
            min_humidity=30, max_humidity=80,
        ).to_sber_state()
        av = config["model"]["allowed_values"]["hvac_humidity_set"]
        assert av["type"] == "INTEGER"
        iv = av["integer_values"]
        assert iv["min"] == "30"
        assert iv["max"] == "80"
        assert isinstance(iv["step"], str)

    def test_allowed_values_air_flow_power_enum(self):
        """hvac_air_flow_power ENUM uses Sber naming, 'values' key."""
        config = self._make_humidifier(
            available_modes=["auto", "low", "high"],
        ).to_sber_state()
        av = config["model"]["allowed_values"]["hvac_air_flow_power"]
        assert av["type"] == "ENUM"
        assert "values" in av["enum_values"], "Must use 'values', not 'value'"
        values = av["enum_values"]["values"]
        assert isinstance(values, list)
        # Verify Sber naming
        assert "auto" in values
        assert "low" in values
        assert "high" in values

    @pytest.mark.parametrize("ha_mode,expected_sber", [
        ("auto", "auto"),
        ("low", "low"),
        ("high", "high"),
        ("silent", "quiet"),
        ("sleep", "quiet"),
        ("strong", "turbo"),
        ("boost", "turbo"),
    ])
    def test_humidifier_mode_mapping(self, ha_mode: str, expected_sber: str):
        """HA humidifier modes must map to Sber enum values correctly."""
        config = self._make_humidifier(
            available_modes=[ha_mode],
        ).to_sber_state()
        av = config["model"]["allowed_values"]["hvac_air_flow_power"]
        assert expected_sber in av["enum_values"]["values"]

    def test_hw_sw_version_with_device(self):
        """Linked device must provide real hw/sw version, not 'Unknown'."""
        config = self._make_humidifier(with_device=True).to_sber_state()
        assert config["hw_version"] != "Unknown"
        assert config["sw_version"] != "Unknown"


# ===========================================================================
# 8. HumidifierEntity — State JSON (to_sber_current_state)
# ===========================================================================


class TestHumidifierStateJson:
    """Validate HumidifierEntity.to_sber_current_state() against Sber C2C spec."""

    def _make_humidifier(self, **state_kw) -> HumidifierEntity:
        entity = HumidifierEntity(HUMIDIFIER_ENTITY_DATA)
        entity.fill_by_ha_state(_humidifier_ha_state(**state_kw))
        return entity

    def test_online_always_present(self):
        """online BOOL must always be present."""
        states = _get_states_list(self._make_humidifier())
        online = _find_state_by_key(states, "online")
        assert online is not None
        assert online["value"]["type"] == "BOOL"

    def test_on_off_reflects_state(self):
        """on_off must reflect the HA state."""
        entity_on = self._make_humidifier(state="on")
        states_on = _get_states_list(entity_on)
        assert _find_state_by_key(states_on, "on_off")["value"]["bool_value"] is True

        entity_off = self._make_humidifier(state="off")
        states_off = _get_states_list(entity_off)
        assert _find_state_by_key(states_off, "on_off")["value"]["bool_value"] is False

    def test_humidity_integer_value_is_string(self):
        """humidity integer_value must be string per Sber spec."""
        entity = self._make_humidifier(current_humidity=45.0)
        states = _get_states_list(entity)
        hum = _find_state_by_key(states, "humidity")
        assert hum is not None
        iv = hum["value"]["integer_value"]
        assert isinstance(iv, str), f"humidity integer_value must be str, got {type(iv).__name__}"

    def test_hvac_humidity_set_integer_string(self):
        """hvac_humidity_set integer_value must be string."""
        entity = self._make_humidifier(humidity=50)
        states = _get_states_list(entity)
        hs = _find_state_by_key(states, "hvac_humidity_set")
        assert hs is not None
        iv = hs["value"]["integer_value"]
        assert isinstance(iv, str), f"hvac_humidity_set must be str, got {type(iv).__name__}"

    def test_air_flow_power_enum_sber_value(self):
        """hvac_air_flow_power must emit mapped Sber enum value, not HA value."""
        entity = self._make_humidifier(
            available_modes=["normal", "sleep", "auto"],
            mode="auto",
        )
        states = _get_states_list(entity)
        fp = _find_state_by_key(states, "hvac_air_flow_power")
        assert fp is not None
        assert fp["value"]["type"] == "ENUM"
        assert fp["value"]["enum_value"] == "auto"

    def test_night_mode_bool(self):
        """hvac_night_mode must be BOOL reflecting sleep/night mode."""
        entity_sleep = self._make_humidifier(
            available_modes=["normal", "sleep"],
            mode="sleep",
        )
        states = _get_states_list(entity_sleep)
        nm = _find_state_by_key(states, "hvac_night_mode")
        assert nm is not None
        assert nm["value"]["type"] == "BOOL"
        assert nm["value"]["bool_value"] is True

        entity_normal = self._make_humidifier(
            available_modes=["normal", "sleep"],
            mode="normal",
        )
        states_n = _get_states_list(entity_normal)
        nm_n = _find_state_by_key(states_n, "hvac_night_mode")
        assert nm_n["value"]["bool_value"] is False

    def test_water_percentage_integer_string(self):
        """hvac_water_percentage must be INTEGER with string value."""
        entity = self._make_humidifier(water_level=75)
        states = _get_states_list(entity)
        wp = _find_state_by_key(states, "hvac_water_percentage")
        assert wp is not None
        assert wp["value"]["type"] == "INTEGER"
        assert isinstance(wp["value"]["integer_value"], str)
        assert wp["value"]["integer_value"] == "75"

    def test_water_low_level_bool(self):
        """hvac_water_low_level must be BOOL."""
        entity = self._make_humidifier(water_low_level=True)
        states = _get_states_list(entity)
        wl = _find_state_by_key(states, "hvac_water_low_level")
        assert wl is not None
        assert wl["value"]["type"] == "BOOL"
        assert wl["value"]["bool_value"] is True

    def test_child_lock_bool(self):
        """child_lock must be BOOL."""
        entity = self._make_humidifier(child_lock=True)
        states = _get_states_list(entity)
        cl = _find_state_by_key(states, "child_lock")
        assert cl is not None
        assert cl["value"]["type"] == "BOOL"
        assert cl["value"]["bool_value"] is True

    def test_offline_when_unavailable(self):
        """online must be False when entity is unavailable."""
        entity = self._make_humidifier(state="unavailable")
        states = _get_states_list(entity)
        online = _find_state_by_key(states, "online")
        assert online["value"]["bool_value"] is False


# ===========================================================================
# 9. HumidifierEntity — Command Processing (process_cmd)
# ===========================================================================


class TestHumidifierProcessCmd:
    """Validate HumidifierEntity.process_cmd() produces correct HA calls."""

    def _make_humidifier(self, **state_kw) -> HumidifierEntity:
        entity = HumidifierEntity(HUMIDIFIER_ENTITY_DATA)
        entity.fill_by_ha_state(_humidifier_ha_state(**state_kw))
        return entity

    def test_on_off_turn_on(self):
        """on_off=True produces humidifier.turn_on."""
        entity = self._make_humidifier()
        result = entity.process_cmd(_sber_cmd([_bool_cmd("on_off", True)]))
        assert len(result) == 1
        url = result[0]["url"]
        assert url["domain"] == "humidifier"
        assert url["service"] == "turn_on"

    def test_on_off_turn_off(self):
        """on_off=False produces humidifier.turn_off."""
        entity = self._make_humidifier()
        result = entity.process_cmd(_sber_cmd([_bool_cmd("on_off", False)]))
        assert result[0]["url"]["service"] == "turn_off"

    def test_hvac_humidity_set_command(self):
        """hvac_humidity_set produces humidifier.set_humidity."""
        entity = self._make_humidifier()
        result = entity.process_cmd(_sber_cmd([_int_cmd("hvac_humidity_set", "60")]))
        assert len(result) == 1
        url = result[0]["url"]
        assert url["domain"] == "humidifier"
        assert url["service"] == "set_humidity"
        assert url["service_data"]["humidity"] == 60

    def test_humidity_command_also_accepted(self):
        """'humidity' key (in addition to hvac_humidity_set) produces set_humidity."""
        entity = self._make_humidifier()
        result = entity.process_cmd(_sber_cmd([_int_cmd("humidity", "55")]))
        assert len(result) == 1
        url = result[0]["url"]
        assert url["service"] == "set_humidity"
        assert url["service_data"]["humidity"] == 55

    def test_hvac_air_flow_power_command(self):
        """hvac_air_flow_power ENUM produces humidifier.set_mode."""
        entity = self._make_humidifier(
            available_modes=["normal", "auto", "high"],
        )
        result = entity.process_cmd(_sber_cmd([_enum_cmd("hvac_air_flow_power", "auto")]))
        assert len(result) == 1
        url = result[0]["url"]
        assert url["domain"] == "humidifier"
        assert url["service"] == "set_mode"

    def test_hvac_night_mode_on(self):
        """hvac_night_mode=True sets mode to sleep/night."""
        entity = self._make_humidifier(
            available_modes=["normal", "sleep", "auto"],
        )
        result = entity.process_cmd(_sber_cmd([_bool_cmd("hvac_night_mode", True)]))
        assert len(result) == 1
        url = result[0]["url"]
        assert url["service"] == "set_mode"
        assert url["service_data"]["mode"] in ("sleep", "night")

    def test_hvac_night_mode_off(self):
        """hvac_night_mode=False reverts to a non-night mode."""
        entity = self._make_humidifier(
            available_modes=["normal", "sleep", "auto"],
        )
        result = entity.process_cmd(_sber_cmd([_bool_cmd("hvac_night_mode", False)]))
        assert len(result) == 1
        url = result[0]["url"]
        assert url["service"] == "set_mode"
        # Must revert to a non-sleep/night mode
        assert url["service_data"]["mode"] not in ("sleep", "night")

    def test_unknown_command_does_not_crash(self):
        """Unknown Sber commands must not raise exceptions."""
        entity = self._make_humidifier()
        result = entity.process_cmd(_sber_cmd([_enum_cmd("unknown_key", "value")]))
        assert isinstance(result, list)

    def test_empty_states_returns_empty(self):
        """Empty states must return empty list."""
        entity = self._make_humidifier()
        result = entity.process_cmd({"states": []})
        assert result == []


# ===========================================================================
# 10. Cross-cutting: all integer_value fields are strings everywhere
# ===========================================================================


class TestIntegerValueAlwaysString:
    """Ensure ALL integer_value fields across all entities are strings, never int.

    This is the single most common Sber C2C compliance bug.
    """

    @staticmethod
    def _check_all_integer_values_are_strings(states: list[dict]) -> None:
        """Assert that every INTEGER state has integer_value as str."""
        for s in states:
            v = s.get("value", {})
            if v.get("type") == "INTEGER":
                iv = v.get("integer_value")
                assert isinstance(iv, str), (
                    f"State '{s.get('key')}': integer_value must be str, "
                    f"got {type(iv).__name__}: {iv!r}"
                )

    def test_light_all_integers_are_strings(self):
        """All integer_values in light state must be strings."""
        entity = LightEntity(LIGHT_ENTITY_DATA)
        entity.fill_by_ha_state(_light_ha_state(
            brightness=200,
            color_temp=300,
            color_mode="color_temp",
            supported_color_modes=["color_temp", "hs"],
        ))
        states = _get_states_list(entity)
        self._check_all_integer_values_are_strings(states)

    def test_climate_all_integers_are_strings(self):
        """All integer_values in climate state must be strings."""
        entity = ClimateEntity(CLIMATE_ENTITY_DATA)
        entity.fill_by_ha_state(_climate_ha_state(
            current_temperature=24.5,
            temperature=22.0,
            target_humidity=50,
        ))
        states = _get_states_list(entity)
        self._check_all_integer_values_are_strings(states)

    def test_humidifier_all_integers_are_strings(self):
        """All integer_values in humidifier state must be strings."""
        entity = HumidifierEntity(HUMIDIFIER_ENTITY_DATA)
        entity.fill_by_ha_state(_humidifier_ha_state(
            humidity=50,
            current_humidity=45.0,
            water_level=70,
        ))
        states = _get_states_list(entity)
        self._check_all_integer_values_are_strings(states)


# ===========================================================================
# 11. Cross-cutting: all allowed_values INTEGER fields are strings
# ===========================================================================


class TestAllowedValuesIntegerFieldsAreStrings:
    """Ensure INTEGER allowed_values have min/max/step as strings in all entities."""

    @staticmethod
    def _check_allowed_values(config: dict) -> None:
        av = config["model"].get("allowed_values", {})
        for key, val in av.items():
            if val.get("type") == "INTEGER":
                iv = val.get("integer_values", {})
                for field in ("min", "max", "step"):
                    if field in iv:
                        assert isinstance(iv[field], str), (
                            f"allowed_values[{key}].integer_values.{field} must be str, "
                            f"got {type(iv[field]).__name__}: {iv[field]!r}"
                        )

    def test_light_allowed_values(self):
        """Light allowed_values INTEGER fields must be strings."""
        entity = LightEntity(LIGHT_ENTITY_DATA)
        entity.fill_by_ha_state(_light_ha_state(
            supported_color_modes=["hs", "color_temp"],
        ))
        self._check_allowed_values(entity.to_sber_state())

    def test_climate_allowed_values(self):
        """Climate allowed_values INTEGER fields must be strings."""
        entity = ClimateEntity(CLIMATE_ENTITY_DATA)
        entity.fill_by_ha_state(_climate_ha_state())
        self._check_allowed_values(entity.to_sber_state())

    def test_humidifier_allowed_values(self):
        """Humidifier allowed_values INTEGER fields must be strings."""
        entity = HumidifierEntity(HUMIDIFIER_ENTITY_DATA)
        entity.fill_by_ha_state(_humidifier_ha_state())
        self._check_allowed_values(entity.to_sber_state())


# ===========================================================================
# 12. Cross-cutting: ENUM allowed_values use "values" key, never "value"
# ===========================================================================


class TestEnumAllowedValuesUseValuesKey:
    """Ensure all ENUM allowed_values use 'values' key, not 'value'."""

    @staticmethod
    def _check_enum_keys(config: dict) -> None:
        av = config["model"].get("allowed_values", {})
        for key, val in av.items():
            if val.get("type") == "ENUM":
                ev = val.get("enum_values", {})
                assert "values" in ev, (
                    f"allowed_values[{key}].enum_values must have 'values' key"
                )
                assert "value" not in ev, (
                    f"allowed_values[{key}].enum_values must NOT have 'value' key"
                )

    def test_light_enum_values_key(self):
        """Light ENUM allowed_values use 'values' key."""
        entity = LightEntity(LIGHT_ENTITY_DATA)
        entity.fill_by_ha_state(_light_ha_state(supported_color_modes=["hs", "color_temp"]))
        self._check_enum_keys(entity.to_sber_state())

    def test_climate_enum_values_key(self):
        """Climate ENUM allowed_values use 'values' key."""
        entity = ClimateEntity(CLIMATE_ENTITY_DATA)
        entity.fill_by_ha_state(_climate_ha_state(
            fan_modes=["auto", "low"],
            hvac_modes=["off", "cool", "heat"],
        ))
        self._check_enum_keys(entity.to_sber_state())

    def test_humidifier_enum_values_key(self):
        """Humidifier ENUM allowed_values use 'values' key."""
        entity = HumidifierEntity(HUMIDIFIER_ENTITY_DATA)
        entity.fill_by_ha_state(_humidifier_ha_state(available_modes=["auto", "low"]))
        self._check_enum_keys(entity.to_sber_state())
