class ColorConverter:
    @staticmethod
    def ha_to_sber_hsv(ha_hue, ha_saturation, ha_brightness):
        """
        Конвертирует цвет из HA (HS/RGB) в HSV для Sber:
        - H: 0–360 → 0–360
        - S: 0–100% → 0–1000
        - V: 0–255 → 100–1000
        """
        # Нормализация значений HA
        ha_hue = max(0, min(360, ha_hue if ha_hue is not None else 0))         # H: 0–360
        ha_saturation = max(0, min(100, ha_saturation if ha_saturation is not None else 0))  # S: 0–100%
        ha_brightness = int(max(0, min(255, ha_brightness if ha_brightness is not None else 0))) # V: 0–255

        # Конвертация в Sber HSV
        sber_hue = ha_hue
        sber_saturation = ha_saturation * 10      # 0–100% → 0–1000
        sber_value = (ha_brightness / 255) * 900 + 100  # 0–255 → 100–1000

        return round(sber_hue), round(sber_saturation), round(sber_value)


    @staticmethod
    def sber_to_ha_hsv(sber_hue, sber_saturation, sber_value):
        """
        Конвертирует HSV от Sber (0–360, 0–1000, 100–1000) в HA (HS/RGB):
        - H: 0–360 → 0–360
        - S: 0–1000 → 0–100%
        - V: 100–1000 → 0–255
        """
        # Нормализация значений Sber
        sber_hue = max(0, min(360, sber_hue if sber_hue is not None else 0))          # H: 0–360
        sber_saturation = max(0, min(1000, sber_saturation if sber_saturation is not None else 0))  # S: 0–1000
        sber_value = max(100, min(1000, sber_value if sber_value is not None else 0))     # V: 100–1000

        # Конвертация в HA HSV
        ha_hue = sber_hue
        ha_saturation = sber_saturation / 10       # 0–1000 → 0–100%
        ha_brightness = ((sber_value - 100) / 900) * 255  # 100–1000 → 0–255

        return round(ha_hue), round(ha_saturation), round(ha_brightness)
        