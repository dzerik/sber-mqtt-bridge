"""Tests for ClimateEntity — Sber HVAC/AC device mapping."""

import unittest

from custom_components.sber_mqtt_bridge.devices.climate import ClimateEntity
from custom_components.sber_mqtt_bridge.devices.hvac_boiler import HvacBoilerEntity
from custom_components.sber_mqtt_bridge.schema_validator import validate_publish

ENTITY_DATA = {"entity_id": "climate.ac", "name": "AC"}
BOILER_DATA = {"entity_id": "water_heater.boiler", "name": "Boiler"}


def _make_ha_state(
    state="cool",
    current_temperature=24.5,
    temperature=22.0,
    fan_modes=None,
    swing_modes=None,
    hvac_modes=None,
    fan_mode="auto",
    swing_mode="off",
    min_temp=16.0,
    max_temp=32.0,
):
    if fan_modes is None:
        fan_modes = ["auto", "low", "medium", "high"]
    if swing_modes is None:
        swing_modes = ["off", "vertical", "horizontal"]
    if hvac_modes is None:
        hvac_modes = ["off", "cool", "heat", "fan_only", "dry"]
    return {
        "entity_id": "climate.ac",
        "state": state,
        "attributes": {
            "current_temperature": current_temperature,
            "temperature": temperature,
            "fan_modes": fan_modes,
            "swing_modes": swing_modes,
            "hvac_modes": hvac_modes,
            "fan_mode": fan_mode,
            "swing_mode": swing_mode,
            "min_temp": min_temp,
            "max_temp": max_temp,
        },
    }


class TestClimateInit(unittest.TestCase):
    """Test ClimateEntity initialization."""

    def test_init_defaults(self):
        entity = ClimateEntity(ENTITY_DATA)
        self.assertEqual(entity.category, "hvac_ac")
        self.assertEqual(entity.entity_id, "climate.ac")
        self.assertFalse(entity.current_state)
        self.assertIsNone(entity.temperature)
        self.assertIsNone(entity.target_temperature)
        self.assertEqual(entity.fan_modes, [])
        self.assertEqual(entity.swing_modes, [])
        self.assertEqual(entity.hvac_modes, [])


class TestClimateFillByHaState(unittest.TestCase):
    """Test fill_by_ha_state parses HA climate attributes."""

    def test_fill_basic(self):
        entity = ClimateEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state())
        self.assertTrue(entity.current_state)  # "cool" != "off"
        self.assertEqual(entity.temperature, 24.5)
        self.assertEqual(entity.target_temperature, 22.0)
        self.assertEqual(entity.fan_mode, "auto")
        self.assertEqual(entity.swing_mode, "off")
        self.assertEqual(entity.hvac_mode, "cool")
        self.assertEqual(entity.min_temp, 16.0)
        self.assertEqual(entity.max_temp, 32.0)

    def test_fill_off_state(self):
        entity = ClimateEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(state="off"))
        self.assertFalse(entity.current_state)

    def test_fill_heat_state(self):
        entity = ClimateEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(state="heat"))
        self.assertTrue(entity.current_state)
        self.assertEqual(entity.hvac_mode, "heat")

    def test_fill_fan_modes(self):
        entity = ClimateEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(fan_modes=["low", "high"]))
        self.assertEqual(entity.fan_modes, ["low", "high"])

    def test_fill_no_optional_attributes(self):
        """Missing attributes use defaults."""
        entity = ClimateEntity(ENTITY_DATA)
        entity.fill_by_ha_state(
            {
                "entity_id": "climate.ac",
                "state": "off",
                "attributes": {},
            }
        )
        self.assertFalse(entity.current_state)
        self.assertIsNone(entity.temperature)
        self.assertIsNone(entity.target_temperature)
        self.assertEqual(entity.fan_modes, [])


class TestClimateCreateFeaturesList(unittest.TestCase):
    """Test create_features_list with various capabilities."""

    def test_all_modes_present(self):
        entity = ClimateEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state())
        features = entity.get_final_features_list()
        self.assertIn("on_off", features)
        self.assertIn("temperature", features)
        self.assertIn("hvac_temp_set", features)
        self.assertIn("hvac_air_flow_direction", features)
        self.assertIn("hvac_air_flow_power", features)
        self.assertIn("hvac_work_mode", features)
        self.assertIn("online", features)

    def test_no_fan_modes(self):
        entity = ClimateEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(fan_modes=[]))
        features = entity.get_final_features_list()
        self.assertNotIn("hvac_air_flow_power", features)

    def test_no_swing_modes(self):
        entity = ClimateEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(swing_modes=[]))
        features = entity.get_final_features_list()
        self.assertNotIn("hvac_air_flow_direction", features)

    def test_no_hvac_modes(self):
        entity = ClimateEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(hvac_modes=[]))
        features = entity.get_final_features_list()
        self.assertNotIn("hvac_work_mode", features)


class TestClimateCreateAllowedValues(unittest.TestCase):
    """Test create_allowed_values_list."""

    def test_all_modes(self):
        entity = ClimateEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state())
        av = entity.create_allowed_values_list()
        self.assertIn("hvac_air_flow_power", av)
        self.assertIn("hvac_air_flow_direction", av)
        self.assertIn("hvac_work_mode", av)
        self.assertEqual(av["hvac_air_flow_power"]["type"], "ENUM")
        self.assertEqual(
            av["hvac_air_flow_power"]["enum_values"]["values"],
            ["auto", "low", "medium", "high"],
        )

    def test_empty_modes(self):
        entity = ClimateEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(fan_modes=[], swing_modes=[], hvac_modes=[]))
        av = entity.create_allowed_values_list()
        # Only hvac_temp_set remains when no enum modes
        self.assertNotIn("hvac_air_flow_power", av)
        self.assertNotIn("hvac_air_flow_direction", av)
        self.assertNotIn("hvac_work_mode", av)
        self.assertIn("hvac_temp_set", av)


class TestClimateToSberCurrentState(unittest.TestCase):
    """Test to_sber_current_state builds correct Sber payload."""

    def test_full_state(self):
        entity = ClimateEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state())
        result = entity.to_sber_current_state()
        self.assertIn("climate.ac", result)
        states = result["climate.ac"]["states"]
        keys = [s["key"] for s in states]

        self.assertIn("online", keys)
        self.assertIn("on_off", keys)
        self.assertIn("temperature", keys)
        self.assertIn("hvac_temp_set", keys)
        self.assertIn("hvac_air_flow_power", keys)
        self.assertIn("hvac_air_flow_direction", keys)
        self.assertIn("hvac_work_mode", keys)

        online = next(s for s in states if s["key"] == "online")
        self.assertTrue(online["value"]["bool_value"])

        temp = next(s for s in states if s["key"] == "temperature")
        self.assertEqual(temp["value"]["integer_value"], "245")  # 24.5 * 10, as string per spec

        temp_set = next(s for s in states if s["key"] == "hvac_temp_set")
        self.assertEqual(temp_set["value"]["integer_value"], "22")  # whole degrees, as string per spec

    def test_unavailable_state(self):
        entity = ClimateEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(state="unavailable"))
        result = entity.to_sber_current_state()
        states = result["climate.ac"]["states"]
        online = next(s for s in states if s["key"] == "online")
        self.assertFalse(online["value"]["bool_value"])

    def test_no_temperature(self):
        """Без current_temperature датчик комнаты не публикуем, а уставку — обязаны.

        Если ``hvac_temp_set`` пропадёт из публикации, Сбер молча выбросит
        кондиционер целиком (обязательная функция категории hvac_ac).
        """
        entity = ClimateEntity(ENTITY_DATA)
        entity.fill_by_ha_state(
            {
                "entity_id": "climate.ac",
                "state": "cool",
                "attributes": {"fan_mode": "auto"},
            }
        )
        result = entity.to_sber_current_state()
        states = result["climate.ac"]["states"]
        keys = [s["key"] for s in states]
        self.assertNotIn("temperature", keys)
        self.assertIn("hvac_temp_set", keys)
        temp_set = next(s for s in states if s["key"] == "hvac_temp_set")
        # Комнатная температура неизвестна → нижняя граница диапазона.
        self.assertEqual(temp_set["value"]["integer_value"], "16")

    def test_off_state_on_off_false(self):
        entity = ClimateEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(state="off"))
        result = entity.to_sber_current_state()
        states = result["climate.ac"]["states"]
        on_off = next(s for s in states if s["key"] == "on_off")
        self.assertFalse(on_off["value"]["bool_value"])


class TestClimateProcessCmd(unittest.TestCase):
    """Test process_cmd dispatches HA service calls."""

    def _make_entity(self):
        entity = ClimateEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state())
        return entity

    def test_cmd_on_off_turn_on(self):
        entity = self._make_entity()
        result = entity.process_cmd({"states": [{"key": "on_off", "value": {"type": "BOOL", "bool_value": True}}]})
        self.assertEqual(len(result), 1)
        url = result[0]["url"]
        self.assertEqual(url["domain"], "climate")
        self.assertEqual(url["service"], "turn_on")

    def test_cmd_on_off_turn_off(self):
        entity = self._make_entity()
        result = entity.process_cmd({"states": [{"key": "on_off", "value": {"type": "BOOL", "bool_value": False}}]})
        url = result[0]["url"]
        self.assertEqual(url["service"], "turn_off")

    def test_cmd_on_off_wrong_type_rejected(self):
        """on_off with non-BOOL type must be silently rejected."""
        entity = self._make_entity()
        result = entity.process_cmd({"states": [{"key": "on_off", "value": {"type": "INTEGER", "integer_value": "1"}}]})
        self.assertEqual(result, [])

    def test_cmd_hvac_temp_set(self):
        entity = self._make_entity()
        result = entity.process_cmd({"states": [{"key": "hvac_temp_set", "value": {"integer_value": 25}}]})
        url = result[0]["url"]
        self.assertEqual(url["service"], "set_temperature")
        self.assertEqual(url["service_data"]["temperature"], 25.0)

    def test_cmd_fan_mode_valid(self):
        entity = self._make_entity()
        result = entity.process_cmd({"states": [{"key": "hvac_air_flow_power", "value": {"enum_value": "low"}}]})
        url = result[0]["url"]
        self.assertEqual(url["service"], "set_fan_mode")
        self.assertEqual(url["service_data"]["fan_mode"], "low")

    def test_cmd_fan_mode_invalid_rejected(self):
        """Invalid fan mode not in allowed list is rejected."""
        entity = self._make_entity()
        result = entity.process_cmd({"states": [{"key": "hvac_air_flow_power", "value": {"enum_value": "turbo"}}]})
        self.assertEqual(len(result), 0)

    def test_cmd_swing_mode_valid(self):
        entity = self._make_entity()
        result = entity.process_cmd(
            {"states": [{"key": "hvac_air_flow_direction", "value": {"enum_value": "vertical"}}]}
        )
        url = result[0]["url"]
        self.assertEqual(url["service"], "set_swing_mode")
        self.assertEqual(url["service_data"]["swing_mode"], "vertical")

    def test_cmd_swing_mode_invalid_rejected(self):
        entity = self._make_entity()
        result = entity.process_cmd({"states": [{"key": "hvac_air_flow_direction", "value": {"enum_value": "3d"}}]})
        self.assertEqual(len(result), 0)

    def test_cmd_hvac_mode_valid(self):
        entity = self._make_entity()
        result = entity.process_cmd({"states": [{"key": "hvac_work_mode", "value": {"enum_value": "heating"}}]})
        url = result[0]["url"]
        self.assertEqual(url["service"], "set_hvac_mode")
        self.assertEqual(url["service_data"]["hvac_mode"], "heat")

    def test_cmd_hvac_mode_invalid_rejected(self):
        entity = self._make_entity()
        result = entity.process_cmd({"states": [{"key": "hvac_work_mode", "value": {"enum_value": "turbo_cool"}}]})
        self.assertEqual(len(result), 0)

    def test_cmd_empty_states(self):
        entity = self._make_entity()
        result = entity.process_cmd({"states": []})
        self.assertEqual(result, [])

    def test_cmd_multiple(self):
        entity = self._make_entity()
        result = entity.process_cmd(
            {
                "states": [
                    {"key": "on_off", "value": {"type": "BOOL", "bool_value": True}},
                    {"key": "hvac_temp_set", "value": {"integer_value": 20}},
                    {"key": "hvac_air_flow_power", "value": {"enum_value": "high"}},
                ]
            }
        )
        self.assertEqual(len(result), 3)

    def test_cmd_fan_mode_empty_list_accepts_any(self):
        """When fan_modes is empty, any mode is accepted."""
        entity = ClimateEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(fan_modes=[]))
        result = entity.process_cmd({"states": [{"key": "hvac_air_flow_power", "value": {"enum_value": "turbo"}}]})
        self.assertEqual(len(result), 1)


class TestClimateChildLock(unittest.TestCase):
    """child_lock is off-spec for every hvac_* Sber category (issue #44 audit)."""

    def test_child_lock_never_advertised(self):
        """Even with the HA attribute present, child_lock is not a climate feature."""
        entity = ClimateEntity(ENTITY_DATA)
        ha = _make_ha_state()
        ha["attributes"]["child_lock"] = True
        entity.fill_by_ha_state(ha)
        self.assertNotIn("child_lock", entity.get_final_features_list())

    def test_child_lock_never_in_state(self):
        """child_lock must not appear in the published Sber state."""
        entity = ClimateEntity(ENTITY_DATA)
        ha = _make_ha_state()
        ha["attributes"]["child_lock"] = True
        entity.fill_by_ha_state(ha)
        states = entity.to_sber_current_state()["climate.ac"]["states"]
        self.assertNotIn("child_lock", [s["key"] for s in states])


class TestClimateHeatCoolRange(unittest.TestCase):
    """Test heat_cool thermostats publishing target_temp_high/low instead of temperature."""

    def _range_state(self, low=20.0, high=24.0, temperature=None):
        ha = _make_ha_state(state="heat_cool", temperature=temperature)
        ha["attributes"]["target_temp_low"] = low
        ha["attributes"]["target_temp_high"] = high
        return ha

    def test_target_temperature_from_range_midpoint(self):
        """temperature=None with target_temp_high/low yields their midpoint."""
        entity = ClimateEntity(ENTITY_DATA)
        entity.fill_by_ha_state(self._range_state(low=20.0, high=24.0))
        self.assertEqual(entity.target_temperature, 22.0)

    def test_state_hvac_temp_set_from_range(self):
        """Sber hvac_temp_set state is built from the range midpoint."""
        entity = ClimateEntity(ENTITY_DATA)
        entity.fill_by_ha_state(self._range_state(low=20.0, high=24.0))
        states = entity.to_sber_current_state()["climate.ac"]["states"]
        temp_set = next(s for s in states if s["key"] == "hvac_temp_set")
        self.assertEqual(temp_set["value"]["integer_value"], "22")

    def test_explicit_temperature_takes_precedence(self):
        """When both temperature and range are present, temperature wins."""
        entity = ClimateEntity(ENTITY_DATA)
        entity.fill_by_ha_state(self._range_state(low=20.0, high=24.0, temperature=23.0))
        self.assertEqual(entity.target_temperature, 23.0)

    def test_cmd_temp_set_shifts_range(self):
        """temp_set command in range mode shifts the range keeping its width."""
        entity = ClimateEntity(ENTITY_DATA)
        entity.fill_by_ha_state(self._range_state(low=20.0, high=24.0))
        result = entity.process_cmd({"states": [{"key": "hvac_temp_set", "value": {"integer_value": 25}}]})
        self.assertEqual(len(result), 1)
        url = result[0]["url"]
        self.assertEqual(url["service"], "set_temperature")
        # midpoint 22 -> 25 => delta +3, width preserved (4 degrees)
        self.assertEqual(url["service_data"]["target_temp_low"], 23.0)
        self.assertEqual(url["service_data"]["target_temp_high"], 27.0)
        self.assertNotIn("temperature", url["service_data"])

    def test_cmd_temp_set_plain_when_temperature_present(self):
        """With an explicit temperature attribute the plain command is used."""
        entity = ClimateEntity(ENTITY_DATA)
        entity.fill_by_ha_state(self._range_state(low=20.0, high=24.0, temperature=23.0))
        result = entity.process_cmd({"states": [{"key": "hvac_temp_set", "value": {"integer_value": 25}}]})
        url = result[0]["url"]
        self.assertEqual(url["service_data"], {"temperature": 25.0})

    def test_cmd_temp_set_plain_without_range(self):
        """Without target_temp_high/low the plain set_temperature is kept."""
        entity = ClimateEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state())
        result = entity.process_cmd({"states": [{"key": "hvac_temp_set", "value": {"integer_value": 25}}]})
        url = result[0]["url"]
        self.assertEqual(url["service_data"], {"temperature": 25.0})


class TestClimateHumiditySet(unittest.TestCase):
    """Test hvac_humidity_set reads the real HA target humidity attribute."""

    def test_target_humidity_from_humidity_attr(self):
        """HA climate publishes target humidity as 'humidity' (ATTR_HUMIDITY)."""
        entity = ClimateEntity(ENTITY_DATA)
        ha = _make_ha_state()
        ha["attributes"]["humidity"] = 45
        entity.fill_by_ha_state(ha)
        features = entity.get_final_features_list()
        self.assertIn("hvac_humidity_set", features)
        states = entity.to_sber_current_state()["climate.ac"]["states"]
        hum = next(s for s in states if s["key"] == "hvac_humidity_set")
        self.assertEqual(hum["value"]["integer_value"], "45")

    def test_target_humidity_fallback_key(self):
        """Legacy 'target_humidity' key is kept as a fallback."""
        entity = ClimateEntity(ENTITY_DATA)
        ha = _make_ha_state()
        ha["attributes"]["target_humidity"] = 50
        entity.fill_by_ha_state(ha)
        states = entity.to_sber_current_state()["climate.ac"]["states"]
        hum = next(s for s in states if s["key"] == "hvac_humidity_set")
        self.assertEqual(hum["value"]["integer_value"], "50")

    def test_no_humidity_feature_without_attrs(self):
        """No humidity attributes -> no hvac_humidity_set feature."""
        entity = ClimateEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state())
        self.assertNotIn("hvac_humidity_set", entity.get_final_features_list())


class TestClimateHorizontalSwing(unittest.TestCase):
    """Test swing_horizontal_modes fallback (HA 2024.12+) for hvac_air_flow_direction."""

    def _horizontal_state(self, modes=None, mode="horizontal"):
        if modes is None:
            modes = ["off", "horizontal", "swing"]
        ha = _make_ha_state(swing_modes=[], swing_mode=None)
        ha["attributes"]["swing_horizontal_modes"] = modes
        ha["attributes"]["swing_horizontal_mode"] = mode
        return ha

    def test_feature_present_with_horizontal_only(self):
        """Device with only horizontal swing gets hvac_air_flow_direction."""
        entity = ClimateEntity(ENTITY_DATA)
        entity.fill_by_ha_state(self._horizontal_state())
        self.assertIn("hvac_air_flow_direction", entity.get_final_features_list())

    def test_allowed_values_only_mapped_modes(self):
        """Allowed values include only modes with a known Sber mapping."""
        entity = ClimateEntity(ENTITY_DATA)
        entity.fill_by_ha_state(self._horizontal_state(modes=["off", "on", "horizontal", "swing"]))
        av = entity.create_allowed_values_list()
        self.assertIn("hvac_air_flow_direction", av)
        # "on" has no Sber mapping and must be filtered out
        self.assertEqual(av["hvac_air_flow_direction"]["enum_values"]["values"], ["no", "horizontal", "swing"])

    def test_state_from_horizontal_mode(self):
        """Current horizontal mode maps into hvac_air_flow_direction state."""
        entity = ClimateEntity(ENTITY_DATA)
        entity.fill_by_ha_state(self._horizontal_state(mode="horizontal"))
        states = entity.to_sber_current_state()["climate.ac"]["states"]
        direction = next(s for s in states if s["key"] == "hvac_air_flow_direction")
        self.assertEqual(direction["value"]["enum_value"], "horizontal")

    def test_state_skips_unmapped_horizontal_mode(self):
        """Unmapped current horizontal mode produces no direction state."""
        entity = ClimateEntity(ENTITY_DATA)
        entity.fill_by_ha_state(self._horizontal_state(mode="on"))
        states = entity.to_sber_current_state()["climate.ac"]["states"]
        keys = [s["key"] for s in states]
        self.assertNotIn("hvac_air_flow_direction", keys)

    def test_cmd_goes_to_set_swing_horizontal_mode(self):
        """Direction command routes to climate.set_swing_horizontal_mode."""
        entity = ClimateEntity(ENTITY_DATA)
        entity.fill_by_ha_state(self._horizontal_state())
        result = entity.process_cmd({"states": [{"key": "hvac_air_flow_direction", "value": {"enum_value": "swing"}}]})
        self.assertEqual(len(result), 1)
        url = result[0]["url"]
        self.assertEqual(url["service"], "set_swing_horizontal_mode")
        self.assertEqual(url["service_data"]["swing_horizontal_mode"], "swing")

    def test_cmd_rejects_mode_not_in_horizontal_list(self):
        """Command for a mode absent from swing_horizontal_modes is rejected."""
        entity = ClimateEntity(ENTITY_DATA)
        entity.fill_by_ha_state(self._horizontal_state(modes=["off", "horizontal"]))
        result = entity.process_cmd({"states": [{"key": "hvac_air_flow_direction", "value": {"enum_value": "swing"}}]})
        self.assertEqual(result, [])

    def test_no_feature_when_nothing_mappable(self):
        """Only unmappable horizontal modes -> feature is not added."""
        entity = ClimateEntity(ENTITY_DATA)
        entity.fill_by_ha_state(self._horizontal_state(modes=["on", "wide"]))
        self.assertNotIn("hvac_air_flow_direction", entity.get_final_features_list())
        self.assertNotIn("hvac_air_flow_direction", entity.create_allowed_values_list())

    def test_vertical_swing_takes_precedence(self):
        """When swing_modes are present, the vertical path is used for commands."""
        entity = ClimateEntity(ENTITY_DATA)
        ha = _make_ha_state()
        ha["attributes"]["swing_horizontal_modes"] = ["off", "horizontal"]
        ha["attributes"]["swing_horizontal_mode"] = "off"
        entity.fill_by_ha_state(ha)
        result = entity.process_cmd(
            {"states": [{"key": "hvac_air_flow_direction", "value": {"enum_value": "vertical"}}]}
        )
        url = result[0]["url"]
        self.assertEqual(url["service"], "set_swing_mode")
        self.assertEqual(url["service_data"]["swing_mode"], "vertical")


class TestClimateProcessStateChange(unittest.TestCase):
    """Test process_state_change delegates to fill_by_ha_state."""

    def test_state_change(self):
        entity = ClimateEntity(ENTITY_DATA)
        old = _make_ha_state(state="off")
        new = _make_ha_state(state="heat", temperature=26.0)
        entity.fill_by_ha_state(old)
        self.assertFalse(entity.current_state)
        entity.process_state_change(old, new)
        self.assertTrue(entity.current_state)
        self.assertEqual(entity.hvac_mode, "heat")


class TestClimateObligatoryTempSet(unittest.TestCase):
    """hvac_temp_set обязателен для hvac_ac — он должен быть в каждой публикации.

    Если эти тесты падают, Сбер молча выбрасывает кондиционер: устройство
    исчезает из приложения, хотя мост исправно шлёт состояния.
    """

    def _publish(self, entity):
        """Вернуть (список ключей состояния, ошибки валидатора схемы)."""
        features = entity.get_final_features_list()
        states = entity.to_sber_current_state()[entity.entity_id]["states"]
        issues = validate_publish(
            entity_id=entity.entity_id,
            category=entity.category,
            states=states,
            declared_features=features,
        )
        keys = [str(s["key"]) for s in states]
        return keys, [i for i in issues if i.severity == "error"]

    def test_off_climate_without_target_still_publishes_temp_set(self):
        """Выключенный термостат отдаёт temperature=None — уставку берём из комнаты."""
        entity = ClimateEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(state="off", temperature=None, current_temperature=21.0))
        keys, errors = self._publish(entity)
        self.assertIn("hvac_temp_set", keys)
        self.assertEqual(errors, [])

    def test_fan_only_without_target_temperature_is_not_dropped(self):
        """Режим вентиляции без TARGET_TEMPERATURE тоже обязан публиковать уставку."""
        entity = ClimateEntity(ENTITY_DATA)
        entity.fill_by_ha_state(
            {
                "entity_id": "climate.ac",
                "state": "fan_only",
                "attributes": {"current_temperature": 26.0, "hvac_modes": ["off", "fan_only"]},
            }
        )
        keys, errors = self._publish(entity)
        self.assertIn("hvac_temp_set", keys)
        self.assertEqual(errors, [])

    def test_fallback_is_clamped_into_declared_range(self):
        """Фолбэк не должен вылезать за min/max из allowed_values."""
        entity = ClimateEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(temperature=None, current_temperature=40.0, max_temp=32.0))
        states = entity.to_sber_current_state()["climate.ac"]["states"]
        temp_set = next(s for s in states if s["key"] == "hvac_temp_set")
        self.assertEqual(temp_set["value"]["integer_value"], "32")

    def test_transient_none_keeps_known_target(self):
        """Транзиентный state без атрибута temperature не стирает известную уставку."""
        entity = ClimateEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(temperature=23.0))
        entity.fill_by_ha_state(
            {
                "entity_id": "climate.ac",
                "state": "cool",
                "attributes": {"current_temperature": 24.5},
            }
        )
        self.assertEqual(entity.target_temperature, 23.0)
        states = entity.to_sber_current_state()["climate.ac"]["states"]
        temp_set = next(s for s in states if s["key"] == "hvac_temp_set")
        self.assertEqual(temp_set["value"]["integer_value"], "23")

    def test_switch_to_range_replaces_preserved_target(self):
        """Переход heat → heat_cool: показываем середину диапазона, а не старую уставку."""
        entity = ClimateEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(state="heat", temperature=23.0))
        entity.fill_by_ha_state(
            {
                "entity_id": "climate.ac",
                "state": "heat_cool",
                "attributes": {"target_temp_low": 18.0, "target_temp_high": 24.0},
            }
        )
        self.assertEqual(entity.target_temperature, 21.0)
        self.assertTrue(entity._target_is_range)


class TestClimateModeLookupIsCaseInsensitive(unittest.TestCase):
    """Регистр в названиях режимов HA не должен убивать функцию целиком.

    Много интеграций отдают ``["Auto", "Low", "High"]``. При падении этих
    тестов управление вентилятором/шторками просто исчезает из приложения
    Сбера, хотя в Home Assistant оно есть.
    """

    def test_capitalised_fan_modes_declare_and_publish_power(self):
        entity = ClimateEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(fan_modes=["Auto", "Low", "High"], fan_mode="Low"))
        self.assertIn("hvac_air_flow_power", entity.get_final_features_list())
        allowed = entity.create_allowed_values_list()["hvac_air_flow_power"]
        self.assertEqual(allowed["enum_values"]["values"], ["auto", "low", "high"])
        states = entity.to_sber_current_state()["climate.ac"]["states"]
        power = next(s for s in states if s["key"] == "hvac_air_flow_power")
        self.assertEqual(power["value"]["enum_value"], "low")

    def test_command_uses_the_devices_own_spelling(self):
        """set_fan_mode обязан нести строку ровно как её объявила интеграция."""
        entity = ClimateEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(fan_modes=["Auto", "Low", "High"], fan_mode="Low"))
        result = entity.process_cmd({"states": [{"key": "hvac_air_flow_power", "value": {"enum_value": "low"}}]})
        self.assertEqual(result[0]["url"]["service_data"], {"fan_mode": "Low"})

    def test_capitalised_swing_modes_declare_and_publish_direction(self):
        entity = ClimateEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(swing_modes=["Off", "Vertical"], swing_mode="Vertical"))
        self.assertIn("hvac_air_flow_direction", entity.get_final_features_list())
        states = entity.to_sber_current_state()["climate.ac"]["states"]
        direction = next(s for s in states if s["key"] == "hvac_air_flow_direction")
        self.assertEqual(direction["value"]["enum_value"], "vertical")
        result = entity.process_cmd(
            {"states": [{"key": "hvac_air_flow_direction", "value": {"enum_value": "vertical"}}]}
        )
        self.assertEqual(result[0]["url"]["service_data"], {"swing_mode": "Vertical"})

    def test_capitalised_hvac_modes_declare_and_publish_work_mode(self):
        entity = ClimateEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(state="Cool", hvac_modes=["Off", "Cool", "Heat"]))
        self.assertIn("hvac_work_mode", entity.get_final_features_list())
        states = entity.to_sber_current_state()["climate.ac"]["states"]
        work = next(s for s in states if s["key"] == "hvac_work_mode")
        self.assertEqual(work["value"]["enum_value"], "cooling")
        result = entity.process_cmd({"states": [{"key": "hvac_work_mode", "value": {"enum_value": "cooling"}}]})
        self.assertEqual(result[0]["url"]["service_data"], {"hvac_mode": "Cool"})

    def test_capitalised_off_still_means_off(self):
        """ "Off" — это тоже выключено: режим работы публиковать нельзя."""
        entity = ClimateEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(state="Off", hvac_modes=["Off", "Cool"]))
        keys = [str(s["key"]) for s in entity.to_sber_current_state()["climate.ac"]["states"]]
        self.assertNotIn("hvac_work_mode", keys)

    def test_capitalised_presets_still_drive_night_mode(self):
        entity = ClimateEntity(ENTITY_DATA)
        ha = _make_ha_state()
        ha["attributes"]["preset_modes"] = ["Boost", "Sleep"]
        ha["attributes"]["preset_mode"] = "Sleep"
        entity.fill_by_ha_state(ha)
        self.assertIn("hvac_night_mode", entity.get_final_features_list())
        states = entity.to_sber_current_state()["climate.ac"]["states"]
        night = next(s for s in states if s["key"] == "hvac_night_mode")
        self.assertTrue(night["value"]["bool_value"])


class TestThermostatModeDeclaredIsPublished(unittest.TestCase):
    """Объявленный hvac_thermostat_mode должен доезжать до состояния.

    Если тест падает, у котла/обогревателя в приложении Сбера появляется
    переключатель режима без значения — облако не может его отрисовать.
    """

    def _entity(self, state, hvac_modes):
        entity = HvacBoilerEntity(BOILER_DATA)
        entity.fill_by_ha_state(
            {
                "entity_id": "water_heater.boiler",
                "state": state,
                "attributes": {"current_temperature": 55, "temperature": 60, "hvac_modes": hvac_modes},
            }
        )
        return entity

    def test_plain_on_publishes_heating(self):
        """water_heater отдаёт state="on" — для нагревателя это и есть 'heating'."""
        entity = self._entity("on", ["off", "heat"])
        features = entity.get_final_features_list()
        states = entity.to_sber_current_state()["water_heater.boiler"]["states"]
        keys = [str(s["key"]) for s in states]
        self.assertIn("hvac_thermostat_mode", features)
        self.assertIn("hvac_thermostat_mode", keys)
        mode = next(s for s in states if s["key"] == "hvac_thermostat_mode")
        self.assertEqual(mode["value"]["enum_value"], "heating")

    def test_published_value_is_always_inside_allowed_values(self):
        """Публиковать значение вне allowed_values нельзя — облако его не примет."""
        entity = self._entity("on", ["off", "auto"])
        allowed = entity.create_allowed_values_list()["hvac_thermostat_mode"]["enum_values"]["values"]
        self.assertEqual(allowed, ["auto"])
        keys = [str(s["key"]) for s in entity.to_sber_current_state()["water_heater.boiler"]["states"]]
        self.assertNotIn("hvac_thermostat_mode", keys)

    def test_off_publishes_nothing(self):
        """Выключенное устройство — задокументированный компромисс: значения 'выключено' у Сбера нет."""
        entity = self._entity("off", ["off", "heat"])
        keys = [str(s["key"]) for s in entity.to_sber_current_state()["water_heater.boiler"]["states"]]
        self.assertNotIn("hvac_thermostat_mode", keys)


class TestDocumentedRangeClamping:
    """Числа и границы климата не выходят за документированный Sber диапазон.

    ``hvac_temp_set`` документирован как ``INTEGER(5, 50)``, а страница
    ``allowed_values`` разрешает диапазон только **сокращать**. HA о
    Сбере не знает: термостат бодро объявляет ``max_temp`` 75, а
    бойлер — ``min_temp`` 0.
    """

    @staticmethod
    def _states(entity, entity_id="climate.ac"):
        """Вернуть список публикуемых состояний сущности."""
        return entity.to_sber_current_state()[entity_id]["states"]

    @staticmethod
    def _value(states, key):
        """Достать ``integer_value`` нужной функции из публикации."""
        return next(s for s in states if s["key"] == key)["value"]["integer_value"]

    def test_setpoint_above_documented_ceiling_is_clamped(self):
        """Уставка 60 °C у обычного климата уезжает в облако как 50.

        Если тест упадёт: мост снова отправит Сберу ``hvac_temp_set`` вне
        документированных 5…50. Облако вправе обрезать такое значение или
        выбросить весь ответ — пользователь видит кондиционер, который «не
        принимает температуру», и ни одной ошибки в журнале.
        """
        entity = ClimateEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(temperature=60.0, min_temp=30.0, max_temp=75.0))
        assert self._value(self._states(entity), "hvac_temp_set") == "50"

    def test_allowed_values_never_widen_the_documented_range(self):
        """``allowed_values`` сужается до 30…50, а не копирует HA-шные 30…75.

        Если тест упадёт: модель объявит Сберу потолок, которого нет в
        документации. Облако вправе отвергнуть описание модели целиком —
        устройство просто не появится в приложении, и чинить пользователю
        нечего.
        """
        entity = ClimateEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(min_temp=30.0, max_temp=75.0))
        box = entity.create_allowed_values_list()["hvac_temp_set"]["integer_values"]
        assert (box["min"], box["max"]) == ("30", "50")

    def test_entity_without_setpoint_support_falls_back_inside_the_range(self):
        """HA без ``min_temp``/``max_temp`` (нули) не даёт диапазон 0…0.

        Если тест упадёт: обязательный ``hvac_temp_set`` уедет нулём при
        документированном минимуме 5, а ``allowed_values`` объявит
        схлопнутый диапазон — ползунок температуры в приложении
        невозможно сдвинуть.
        """
        entity = ClimateEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state(temperature=None, current_temperature=None, min_temp=0, max_temp=0))
        box = entity.create_allowed_values_list()["hvac_temp_set"]["integer_values"]
        assert (box["min"], box["max"]) == ("5", "50")
        assert self._value(self._states(entity), "hvac_temp_set") == "5"

    def test_boiler_keeps_the_ceiling_sber_sanctions_for_it(self):
        """У бойлера потолок 80 °C законен — сужать до 50 нельзя.

        Страница функции даёт 5…50, но собственный пример модели Sber на
        странице ``hvac_boiler`` объявляет 25…80, и валидатор судит бойлер
        по нему. Если тест упадёт: клампинг и валидатор разойдутся —
        бойлер, скопированный с эталона Sber, начнёт терять горячие
        уставки (75 °C станет 50 °C), а пользователь — горячую воду.
        """
        entity = HvacBoilerEntity(BOILER_DATA)
        entity.fill_by_ha_state(_make_ha_state(state="heat", temperature=75.0, min_temp=0, max_temp=80.0))
        box = entity.create_allowed_values_list()["hvac_temp_set"]["integer_values"]
        assert (box["min"], box["max"]) == ("5", "80")
        assert self._value(self._states(entity, "water_heater.boiler"), "hvac_temp_set") == "75"

    def test_boiler_without_ha_bounds_keeps_its_own_defaults(self):
        """Бойлер без ``min_temp``/``max_temp`` в HA остаётся при своих 25…80.

        Если тест упадёт: бойлер унаследует диапазон кондиционера
        (16…32), и реальная уставка 60 °C будет опубликована как 32 —
        приложение Сбера покажет чуть тёплую воду вместо горячей.
        """
        entity = HvacBoilerEntity(BOILER_DATA)
        entity.fill_by_ha_state(
            {"entity_id": "water_heater.boiler", "state": "heat", "attributes": {"temperature": 60.0}}
        )
        box = entity.create_allowed_values_list()["hvac_temp_set"]["integer_values"]
        assert (box["min"], box["max"]) == ("25", "80")
        assert self._value(self._states(entity, "water_heater.boiler"), "hvac_temp_set") == "60"

    def test_target_humidity_is_clamped_to_documented_floor(self):
        """Целевая влажность 0 % у климата уезжает как документированные 30 %.

        Если тест упадёт: ``hvac_humidity_set`` уйдёт нулём при
        документированных 30…90 — климат с формальным атрибутом
        ``humidity`` = 0 (обычное дело у сплитов без увлажнения) отдаёт
        Сберу значение, которого функция не допускает.
        """
        entity = ClimateEntity(ENTITY_DATA)
        state = _make_ha_state(temperature=22.0)
        state["attributes"]["humidity"] = 0
        entity.fill_by_ha_state(state)
        assert self._value(self._states(entity), "hvac_humidity_set") == "30"
