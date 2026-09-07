"""Tests for SmokeSensorEntity -- Sber smoke sensor device mapping."""

import unittest

from custom_components.sber_mqtt_bridge.devices.smoke_sensor import SmokeSensorEntity

ENTITY_DATA = {"entity_id": "binary_sensor.smoke", "name": "Smoke Detector"}


def _make_ha_state(state="off", **attrs):
    return {
        "entity_id": "binary_sensor.smoke",
        "state": state,
        "attributes": attrs,
    }


class TestSmokeSensorCreate(unittest.TestCase):
    """Test SmokeSensorEntity initialization."""

    def test_category(self):
        entity = SmokeSensorEntity(ENTITY_DATA)
        self.assertEqual(entity.category, "sensor_smoke")

    def test_initial_state(self):
        entity = SmokeSensorEntity(ENTITY_DATA)
        self.assertFalse(entity.smoke_detected)

    def test_sber_value_key(self):
        entity = SmokeSensorEntity(ENTITY_DATA)
        self.assertEqual(entity._sber_value_key, "smoke_state")


class TestSmokeSensorToSberCurrentState(unittest.TestCase):
    """Test to_sber_current_state."""

    def test_smoke_detected(self):
        entity = SmokeSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("on"))
        result = entity.to_sber_current_state()
        states = result["binary_sensor.smoke"]["states"]
        smoke = next(s for s in states if s["key"] == "smoke_state")
        self.assertEqual(smoke["value"]["type"], "BOOL")
        self.assertTrue(smoke["value"]["bool_value"])

    def test_no_smoke(self):
        entity = SmokeSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("off"))
        result = entity.to_sber_current_state()
        states = result["binary_sensor.smoke"]["states"]
        smoke = next(s for s in states if s["key"] == "smoke_state")
        self.assertFalse(smoke["value"]["bool_value"])

    def test_online_status(self):
        entity = SmokeSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("unavailable"))
        result = entity.to_sber_current_state()
        states = result["binary_sensor.smoke"]["states"]
        online = next(s for s in states if s["key"] == "online")
        self.assertFalse(online["value"]["bool_value"])


class TestSmokeSensorProcessCmd(unittest.TestCase):
    """Test process_cmd (read-only)."""

    def test_cmd_is_noop(self):
        entity = SmokeSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("off"))
        result = entity.process_cmd({"states": [{"key": "smoke_state", "value": {}}]})
        self.assertEqual(result, [])


class TestSmokeSensorTamperAlarmIsForeign(unittest.TestCase):
    """``tamper_alarm`` категории ``sensor_smoke`` не положен.

    Таблица «Доступные функции устройства» на странице
    ``c2c/sensor_smoke`` его не содержит: Sber документирует
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
        entity = SmokeSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("off", tamper=True))
        self.assertNotIn("tamper_alarm", entity.get_final_features_list())

    def test_tamper_is_not_published(self):
        """Он не уходит и в публикуемое состояние."""
        entity = SmokeSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("on", tamper=True))
        states = entity.to_sber_current_state()["binary_sensor.smoke"]["states"]
        self.assertNotIn("tamper_alarm", {s["key"] for s in states})

    def test_documented_features_survive(self):
        """Документированное продолжает публиковаться рядом с отброшенным."""
        entity = SmokeSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("on", tamper=True))
        states = entity.to_sber_current_state()["binary_sensor.smoke"]["states"]
        keys = {s["key"] for s in states}
        self.assertIn("smoke_state", keys)
        self.assertIn("online", keys)


class TestSmokeSensorAlarmMute(unittest.TestCase):
    """Test alarm_mute feature in SmokeSensorEntity."""

    def test_alarm_mute_feature_present(self):
        """Entity with alarm_mute attribute must include alarm_mute in features."""
        entity = SmokeSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("off", alarm_mute=False))
        features = entity.get_final_features_list()
        self.assertIn("alarm_mute", features)

    def test_alarm_mute_feature_absent(self):
        """Entity without alarm_mute attribute must not include it."""
        entity = SmokeSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("off"))
        features = entity.get_final_features_list()
        self.assertNotIn("alarm_mute", features)

    def test_alarm_mute_true_in_state(self):
        """alarm_mute=True must produce alarm_mute=True in Sber state."""
        entity = SmokeSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("off", alarm_mute=True))
        result = entity.to_sber_current_state()
        states = result["binary_sensor.smoke"]["states"]
        am = next(s for s in states if s["key"] == "alarm_mute")
        self.assertTrue(am["value"]["bool_value"])

    def test_alarm_mute_false_in_state(self):
        """alarm_mute=False must produce alarm_mute=False in Sber state."""
        entity = SmokeSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("off", alarm_mute=False))
        result = entity.to_sber_current_state()
        states = result["binary_sensor.smoke"]["states"]
        am = next(s for s in states if s["key"] == "alarm_mute")
        self.assertFalse(am["value"]["bool_value"])

    def test_alarm_mute_survives_next_to_a_dropped_tamper(self):
        """Из пары ``tamper``/``alarm_mute`` остаётся только документированное.

        Оба атрибута приходят от одного и того же Zigbee-датчика, а
        Sber документирует для ``sensor_smoke`` только ``alarm_mute``.
        Если тест упадёт, фильтр категории либо пропустил чужой
        ``tamper_alarm``, либо заодно выкинул законный ``alarm_mute`` —
        во втором случае пользователь потеряет признак отключённой
        сирены.
        """
        entity = SmokeSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("on", tamper=True, alarm_mute=False))
        features = entity.get_final_features_list()
        self.assertNotIn("tamper_alarm", features)
        self.assertIn("alarm_mute", features)
        result = entity.to_sber_current_state()
        keys = [s["key"] for s in result["binary_sensor.smoke"]["states"]]
        self.assertNotIn("tamper_alarm", keys)
        self.assertIn("alarm_mute", keys)


class TestSmokeSensorBattery(unittest.TestCase):
    """Test battery feature support."""

    def test_battery_in_features(self):
        entity = SmokeSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("off", battery=85))
        features = entity.get_final_features_list()
        self.assertIn("battery_percentage", features)

    def test_battery_in_state(self):
        entity = SmokeSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("off", battery=85))
        result = entity.to_sber_current_state()
        states = result["binary_sensor.smoke"]["states"]
        batt = next(s for s in states if s["key"] == "battery_percentage")
        self.assertEqual(batt["value"]["integer_value"], "85")

    def test_no_battery(self):
        entity = SmokeSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("off"))
        features = entity.get_final_features_list()
        self.assertNotIn("battery_percentage", features)
