import unittest
from devices.utils.color_converter import ColorConverter

class TestColorConverter(unittest.TestCase):
    def test_ha_to_sber_min_values(self):
        ha_hue, ha_saturation, ha_brightness = 0, 0, 0
        sber_hue, sber_saturation, sber_value = ColorConverter.ha_to_sber_hsv(ha_hue, ha_saturation, ha_brightness)
        self.assertEqual((sber_hue, sber_saturation, sber_value), (0, 0, 100))

    def test_ha_to_sber_max_values(self):
        ha_hue, ha_saturation, ha_brightness = 360, 100, 255
        sber_hue, sber_saturation, sber_value = ColorConverter.ha_to_sber_hsv(ha_hue, ha_saturation, ha_brightness)
        self.assertEqual((sber_hue, sber_saturation, sber_value), (360, 1000, 1000))

    def test_ha_to_sber_middle_values(self):
        ha_hue, ha_saturation, ha_brightness = 180, 50, 128
        sber_hue, sber_saturation, sber_value = ColorConverter.ha_to_sber_hsv(ha_hue, ha_saturation, ha_brightness)
        # Expected S: 50*10=500, V: (128/255)*900 + 100 ≈ 597.619
        self.assertEqual((sber_hue, sber_saturation, sber_value), (180, 500, 552))

    def test_sber_to_ha_min_values(self):
        sber_hue, sber_saturation, sber_value = 0, 0, 100
        ha_hue, ha_saturation, ha_brightness = ColorConverter.sber_to_ha_hsv(sber_hue, sber_saturation, sber_value)
        self.assertEqual((ha_hue, ha_saturation, ha_brightness), (0, 0, 0))

    def test_sber_to_ha_max_values(self):
        sber_hue, sber_saturation, sber_value = 360, 1000, 1000
        ha_hue, ha_saturation, ha_brightness = ColorConverter.sber_to_ha_hsv(sber_hue, sber_saturation, sber_value)
        self.assertEqual((ha_hue, ha_saturation, ha_brightness), (360, 100, 255))

    def test_sber_to_ha_middle_values(self):
        sber_hue, sber_saturation, sber_value = 180, 500, 598
        ha_hue, ha_saturation, ha_brightness = ColorConverter.sber_to_ha_hsv(sber_hue, sber_saturation, sber_value)
        # Expected S: 500/10=50, V: (598-100)/900*255 ≈ 140.0
        self.assertEqual((ha_hue, ha_saturation, ha_brightness), (180, 50, 141))

    def test_round_trip_conversion(self):
        ha_hue, ha_saturation, ha_brightness = 180, 50, 128
        sber_hue, sber_saturation, sber_value = ColorConverter.ha_to_sber_hsv(ha_hue, ha_saturation, ha_brightness)
        ha_converted_back = ColorConverter.sber_to_ha_hsv(sber_hue, sber_saturation, sber_value)
        self.assertEqual(ha_converted_back, (ha_hue, ha_saturation, ha_brightness))

    def test_ha_to_sber_out_of_bounds(self):
        ha_hue, ha_saturation, ha_brightness = 400, 150, 300
        sber_hue, sber_saturation, sber_value = ColorConverter.ha_to_sber_hsv(ha_hue, ha_saturation, ha_brightness)
        self.assertEqual(sber_hue, 360)
        self.assertEqual(sber_saturation, 1000)
        self.assertEqual(sber_value, 1000)

    def test_sber_to_ha_out_of_bounds(self):
        sber_hue, sber_saturation, sber_value = 400, 1100, 50
        ha_hue, ha_saturation, ha_brightness = ColorConverter.sber_to_ha_hsv(sber_hue, sber_saturation, sber_value)
        self.assertEqual(ha_hue, 360)
        self.assertEqual(ha_saturation, 100)
        self.assertEqual(ha_brightness, 0)

if __name__ == '__main__':
    unittest.main()
