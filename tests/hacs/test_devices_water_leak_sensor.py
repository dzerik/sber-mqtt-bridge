"""Tests for WaterLeakSensorEntity -- tamper_alarm and alarm_mute features."""

import unittest

from custom_components.sber_mqtt_bridge.devices.water_leak_sensor import WaterLeakSensorEntity

ENTITY_DATA = {"entity_id": "binary_sensor.leak", "name": "Water Leak"}


def _make_ha_state(state="off", **attrs):
    return {
        "entity_id": "binary_sensor.leak",
        "state": state,
        "attributes": attrs,
    }


class TestWaterLeakSensorCreate(unittest.TestCase):
    """Test WaterLeakSensorEntity initialization."""

    def test_category(self):
        entity = WaterLeakSensorEntity(ENTITY_DATA)
        self.assertEqual(entity.category, "sensor_water_leak")

    def test_initial_state(self):
        entity = WaterLeakSensorEntity(ENTITY_DATA)
        self.assertFalse(entity.leak_detected)

    def test_sber_value_key(self):
        entity = WaterLeakSensorEntity(ENTITY_DATA)
        self.assertEqual(entity._sber_value_key, "water_leak_state")


class TestWaterLeakSensorBasicState(unittest.TestCase):
    """Test basic leak detection state."""

    def test_leak_detected(self):
        entity = WaterLeakSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("on"))
        result = entity.to_sber_current_state()
        states = result["binary_sensor.leak"]["states"]
        leak = next(s for s in states if s["key"] == "water_leak_state")
        self.assertTrue(leak["value"]["bool_value"])

    def test_no_leak(self):
        entity = WaterLeakSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("off"))
        result = entity.to_sber_current_state()
        states = result["binary_sensor.leak"]["states"]
        leak = next(s for s in states if s["key"] == "water_leak_state")
        self.assertFalse(leak["value"]["bool_value"])

    def test_online_status(self):
        entity = WaterLeakSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("unavailable"))
        result = entity.to_sber_current_state()
        states = result["binary_sensor.leak"]["states"]
        online = next(s for s in states if s["key"] == "online")
        self.assertFalse(online["value"]["bool_value"])


class TestWaterLeakUndocumentedFeatures(unittest.TestCase):
    """``tamper_alarm`` и ``alarm_mute`` датчику протечки не положены.

    Таблица «Доступные функции устройства» на странице
    ``c2c/sensor_water_leak`` перечисляет ровно пять функций:
    ``online``, ``water_leak_state``, ``battery_low_power``,
    ``battery_percentage``, ``signal_strength``.  ``tamper_alarm``
    документирован только для ``sensor_door``, ``alarm_mute`` — только
    для ``sensor_gas`` и ``sensor_smoke``.

    Zigbee-датчики протечки (Aqara и родня) отдают в HA атрибуты
    ``tamper`` и ``alarm_mute``, и до 1.51 мост честно перекладывал их
    в модель.  Если эти тесты упадут, чужая функция вернётся в
    объявление модели — а модель с функцией вне справочника категории
    облако вправе отбросить целиком, и пользователь увидит не «нет
    вскрытия», а исчезнувший датчик протечки.
    """

    def test_tamper_attribute_does_not_reach_the_model(self):
        """Атрибут ``tamper`` из HA не превращается в функцию модели."""
        entity = WaterLeakSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("off", tamper=True))
        self.assertNotIn("tamper_alarm", entity.get_final_features_list())

    def test_alarm_mute_attribute_does_not_reach_the_model(self):
        """Атрибут ``alarm_mute`` из HA не превращается в функцию модели."""
        entity = WaterLeakSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("off", alarm_mute=True))
        self.assertNotIn("alarm_mute", entity.get_final_features_list())

    def test_neither_is_published(self):
        """Ни одна из двух функций не уходит и в публикуемое состояние."""
        entity = WaterLeakSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("on", tamper=True, alarm_mute=False))
        states = entity.to_sber_current_state()["binary_sensor.leak"]["states"]
        keys = {s["key"] for s in states}
        self.assertNotIn("tamper_alarm", keys)
        self.assertNotIn("alarm_mute", keys)

    def test_documented_features_survive(self):
        """Документированное продолжает публиковаться рядом с отброшенным.

        Страховка от «починили фильтр — потеряли датчик»: обязательный
        ``water_leak_state`` обязан остаться на месте.
        """
        entity = WaterLeakSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("on", tamper=True, alarm_mute=False))
        states = entity.to_sber_current_state()["binary_sensor.leak"]["states"]
        keys = {s["key"] for s in states}
        self.assertIn("water_leak_state", keys)
        self.assertIn("online", keys)


class TestWaterLeakProcessCmd(unittest.TestCase):
    """Test process_cmd (read-only sensor)."""

    def test_cmd_is_noop(self):
        entity = WaterLeakSensorEntity(ENTITY_DATA)
        entity.fill_by_ha_state(_make_ha_state("off"))
        result = entity.process_cmd({"states": []})
        self.assertEqual(result, [])
