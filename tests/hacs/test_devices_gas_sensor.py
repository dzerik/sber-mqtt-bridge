"""Tests for GasSensorEntity -- Sber gas sensor device mapping."""

import unittest

from custom_components.sber_mqtt_bridge.devices.gas_sensor import GasSensorEntity

ENTITY_DATA = {"entity_id": "binary_sensor.gas", "name": "Gas Detector"}


def _make_ha_state(state="off", **attrs):
    return {
        "entity_id": "binary_sensor.gas",
        "state": state,
        "attributes": attrs,
    }


class TestGasSensorCreate(unittest.TestCase):
    """Test GasSensorEntity initialization."""

    def test_category(self):
        entity = GasSensorEntity(ENTITY_DATA)
        self.assertEqual(entity.category, "sensor_gas")

    def test_initial_state(self):
        entity = GasSensorEntity(ENTITY_DATA)
        self.assertFalse(entity.gas_detected)

    def test_sber_value_key(self):
        entity = GasSensorEntity(ENTITY_DATA)
        self.assertEqual(entity._sber_value_key, "gas_leak_state")


class TestGasSensorToSberCurrentState(unittest.TestCase):
    """Test to_sber_current_state."""

    def test_gas_detected(self):
        entity = GasSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("on"))
        result = entity.to_sber_current_state()
        states = result["binary_sensor.gas"]["states"]
        gas = next(s for s in states if s["key"] == "gas_leak_state")
        self.assertEqual(gas["value"]["type"], "BOOL")
        self.assertTrue(gas["value"]["bool_value"])

    def test_no_gas(self):
        entity = GasSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("off"))
        result = entity.to_sber_current_state()
        states = result["binary_sensor.gas"]["states"]
        gas = next(s for s in states if s["key"] == "gas_leak_state")
        self.assertFalse(gas["value"]["bool_value"])

    def test_online_status(self):
        entity = GasSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("unavailable"))
        result = entity.to_sber_current_state()
        states = result["binary_sensor.gas"]["states"]
        online = next(s for s in states if s["key"] == "online")
        self.assertFalse(online["value"]["bool_value"])


class TestGasSensorTamperAlarmIsForeign(unittest.TestCase):
    """``tamper_alarm`` категории ``sensor_gas`` не положен.

    Таблица «Доступные функции устройства» на странице
    ``c2c/sensor_gas`` его не содержит: Sber документирует
    ``tamper_alarm`` только для ``sensor_door``.  Атрибут ``tamper``
    у Zigbee-датчика при этом есть, и до 1.51 мост перекладывал его в
    модель.

    Если тест упадёт, чужая функция вернётся в объявление модели — а
    модель с функцией вне справочника категории облако вправе
    отбросить целиком: пользователь потеряет не «сигнал о вскрытии»,
    а сам датчик.
    """

    def test_tamper_attribute_does_not_reach_the_model(self):
        """Атрибут ``tamper`` из HA не превращается в функцию модели."""
        entity = GasSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("off", tamper=True))
        self.assertNotIn("tamper_alarm", entity.get_final_features_list())

    def test_tamper_is_not_published(self):
        """Он не уходит и в публикуемое состояние."""
        entity = GasSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("on", tamper=True))
        states = entity.to_sber_current_state()["binary_sensor.gas"]["states"]
        self.assertNotIn("tamper_alarm", {s["key"] for s in states})

    def test_documented_features_survive(self):
        """Документированное продолжает публиковаться рядом с отброшенным."""
        entity = GasSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("on", tamper=True))
        states = entity.to_sber_current_state()["binary_sensor.gas"]["states"]
        keys = {s["key"] for s in states}
        self.assertIn("gas_leak_state", keys)
        self.assertIn("online", keys)


class TestGasSensorAlarmMute(unittest.TestCase):
    """Test alarm_mute feature in GasSensorEntity."""

    def test_alarm_mute_feature_present(self):
        """Entity with alarm_mute attribute must include alarm_mute in features."""
        entity = GasSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("off", alarm_mute=False))
        features = entity.get_final_features_list()
        self.assertIn("alarm_mute", features)

    def test_alarm_mute_feature_absent(self):
        """Entity without alarm_mute must not include it."""
        entity = GasSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("off"))
        features = entity.get_final_features_list()
        self.assertNotIn("alarm_mute", features)

    def test_alarm_mute_in_state(self):
        """alarm_mute=True must appear in Sber state."""
        entity = GasSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("off", alarm_mute=True))
        result = entity.to_sber_current_state()
        states = result["binary_sensor.gas"]["states"]
        am = next(s for s in states if s["key"] == "alarm_mute")
        self.assertTrue(am["value"]["bool_value"])


class TestGasSensorProcessCmd(unittest.TestCase):
    """Test process_cmd (read-only)."""

    def test_cmd_is_noop(self):
        entity = GasSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("off"))
        result = entity.process_cmd({"states": []})
        self.assertEqual(result, [])
