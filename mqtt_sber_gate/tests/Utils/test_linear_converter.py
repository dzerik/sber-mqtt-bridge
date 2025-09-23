import unittest
from devices.utils.linear_converter import LinearConverter

class TestLinearConverterLimits(unittest.TestCase):
    def setUp(self):
        """Создаём новый экземпляр конвертера перед каждым тестом"""
        self.converter = LinearConverter.create()

    def test_set_sber_limits_updates_values(self):
        """Проверка, что set_sber_limits обновляет внутренние значения"""
        self.converter.set_sber_limits(200, 800)
        self.assertEqual(self.converter.sber_side_min, 200)
        self.assertEqual(self.converter.sber_side_max, 800)

    def test_set_ha_limits_updates_values(self):
        """Проверка, что set_ha_limits обновляет внутренние значения"""
        self.converter.set_ha_limits(50, 200)
        self.assertEqual(self.converter.ha_side_min, 50)
        self.assertEqual(self.converter.ha_side_max, 200)

    def test_chained_limit_changes(self):
        """Проверка последовательной смены границ"""
        # Сначала установим SBER границы
        self.converter.set_sber_limits(100, 900)
        self.assertEqual(self.converter.sber_to_ha(500), 128)  # (500-100)/(900-100)*255=127
        
        # Затем изменим HA границы
        self.converter.set_ha_limits(50, 200)
        self.assertEqual(self.converter.sber_to_ha(500), 125)  # (500-100)/800*(200-50)+50=125
        
        # Изменим SBER границы снова
        self.converter.set_sber_limits(200, 700)
        self.assertEqual(self.converter.sber_to_ha(450), 125)  # (450-200)/500*150+50=137

    def test_negative_limits(self):
        """Проверка работы с отрицательными границами"""
        self.converter.set_sber_limits(-100, 100)
        self.converter.set_ha_limits(0, 100)
        
        # -100 SBER → 0 HA
        # 100 SBER → 100 HA
        self.assertEqual(self.converter.sber_to_ha(-100), 0)
        self.assertEqual(self.converter.sber_to_ha(100), 100)
        self.assertEqual(self.converter.sber_to_ha(0), 50)  # (0+100)/200*100=50

    def test_zero_ranges(self):
        """Проверка обработки нулевых диапазонов"""
        with self.assertRaises(ValueError):
            self.converter.set_sber_limits(100, 100)  # Минимум = максимум
        with self.assertRaises(ValueError):
            self.converter.set_ha_limits(200, 200)    # Минимум = максимум

    def test_fractional_conversion_with_custom_limits(self):
        """Проверка дробных значений с пользовательскими границами"""
        self.converter.set_sber_limits(150, 850)
        self.converter.set_ha_limits(20, 180)
        
        # Точное значение: (400-150)/(850-150)*(180-20)+20 = 250/700*160+20 ≈ 57.14 + 20 = 77.14
        self.assertEqual(self.converter.sber_to_ha(400), 77)
        
        # Обратное преобразование
        self.assertEqual(self.converter.ha_to_sber(77), 399)

    def test_multiple_limit_changes(self):
        """Проверка множественной смены границ"""
        # Начальные значения
        self.assertEqual(self.converter.sber_to_ha(500), 128)
        
        # Изменение SBER границ
        self.converter.set_sber_limits(200, 800)
        self.assertEqual(self.converter.sber_to_ha(500), 128)  # (500-200)/600*255=153
        
        # Изменение HA границ
        self.converter.set_ha_limits(50, 250)
        self.assertEqual(self.converter.sber_to_ha(500), 150)  # (500-200)/600*(250-50)+50=150
        
        # Возврат к дефолтным границам
        self.converter.set_sber_limits(0, 1000)
        self.converter.set_ha_limits(0, 255)
        self.assertEqual(self.converter.sber_to_ha(500), 128)

class TestLinearConverterReversed(unittest.TestCase):
    def setUp(self):
        """Создаём новый экземпляр конвертера перед каждым тестом"""
        self.converter = LinearConverter.create()

    def test_set_reversed_sets_flag(self):
        """Проверка установки флага is_reversed"""
        self.converter.set_reversed(True)
        self.assertTrue(self.converter.is_reversed)
        
        self.converter.set_reversed(False)
        self.assertFalse(self.converter.is_reversed)

    def test_sber_to_ha_with_reversed(self):
        """Проверка преобразования SBER → HA с инверсией"""
        self.converter.set_reversed(True)
        
        # Без инверсии: 0 → 0, с инверсией: 255
        self.assertEqual(self.converter.sber_to_ha(0), 255)
        
        # Без инверсии: 1000 → 255, с инверсией: 0
        self.assertEqual(self.converter.sber_to_ha(1000), 0)
        
        # Среднее значение: 500 → 127 → инверсия: 255-127=128
        self.assertEqual(self.converter.sber_to_ha(500), 128)

    def test_ha_to_sber_with_reversed(self):
        """Проверка преобразования HA → SBER с инверсией"""
        self.converter.set_reversed(True)
        
        # Без инверсии: 0 → 0, с инверсией: 1000
        self.assertEqual(self.converter.ha_to_sber(0), 1000)
        
        # Без инверсии: 255 → 1000, с инверсией: 0
        self.assertEqual(self.converter.ha_to_sber(255), 0)
        
        # Среднее значение: 128 → 500 → инверсия: 255-128=127 → 500
        self.assertEqual(self.converter.ha_to_sber(128), 498)

    def test_round_trip_with_reversed(self):
        """Проверка круговой конвертации с инверсией"""
        self.converter.set_reversed(True)
        
        # SBER → HA → SBER
        sber_value = 300
        ha_value = self.converter.sber_to_ha(sber_value)
        converted_back = self.converter.ha_to_sber(ha_value)
        self.assertLess(abs(converted_back-sber_value), 3)

    def test_custom_limits_with_reversed(self):
        """Проверка инверсии с пользовательскими границами"""
        self.converter.set_sber_limits(200, 800)
        self.converter.set_ha_limits(50, 200)
        self.converter.set_reversed(True)
        
        # Без инверсии: 200 → 50, с инверсией: 200 → 200
        self.assertEqual(self.converter.sber_to_ha(200), 200)
        
        # Без инверсии: 800 → 200, с инверсией: 50
        self.assertEqual(self.converter.sber_to_ha(800), 50)
        
        # Среднее значение: 500 → (500-200)/(800-200)*(200-50)+50 = 125 → инверсия: 200-125=75
        self.assertEqual(self.converter.sber_to_ha(500), 125)

    def test_reversed_does_not_affect_limits(self):
        """Проверка, что инверсия не влияет на установку границ"""
        self.converter.set_sber_limits(100, 900)
        self.converter.set_ha_limits(50, 200)
        self.converter.set_reversed(True)
        
        self.assertEqual(self.converter.sber_side_min, 100)
        self.assertEqual(self.converter.sber_side_max, 900)
        self.assertEqual(self.converter.ha_side_min, 50)
        self.assertEqual(self.converter.ha_side_max, 200)

if __name__ == '__main__':
    unittest.main()


if __name__ == '__main__':
    unittest.main()
