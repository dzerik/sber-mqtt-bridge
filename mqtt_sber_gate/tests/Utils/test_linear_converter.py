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
        self.assertEqual(self.converter.sber_to_ha(500), 127)  # (500-100)/(900-100)*255=127
        
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
        self.assertEqual(self.converter.sber_to_ha(500), 127)
        
        # Изменение SBER границ
        self.converter.set_sber_limits(200, 800)
        self.assertEqual(self.converter.sber_to_ha(500), 127)  # (500-200)/600*255=153
        
        # Изменение HA границ
        self.converter.set_ha_limits(50, 250)
        self.assertEqual(self.converter.sber_to_ha(500), 150)  # (500-200)/600*(250-50)+50=150
        
        # Возврат к дефолтным границам
        self.converter.set_sber_limits(0, 1000)
        self.converter.set_ha_limits(0, 255)
        self.assertEqual(self.converter.sber_to_ha(500), 127)

if __name__ == '__main__':
    unittest.main()
