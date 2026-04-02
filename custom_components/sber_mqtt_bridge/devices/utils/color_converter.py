"""Color conversion utilities between Home Assistant and Sber HSV color spaces."""

from __future__ import annotations


class ColorConverter:
    """Bidirectional HSV color converter between HA and Sber color spaces.

    HA uses:
    - Hue: 0-360 degrees
    - Saturation: 0-100%
    - Brightness (Value): 0-255

    Sber uses:
    - Hue: 0-360 degrees
    - Saturation: 0-1000
    - Value: 100-1000
    """

    @staticmethod
    def ha_to_sber_hsv(
        ha_hue: float | None,
        ha_saturation: float | None,
        ha_brightness: float | None,
    ) -> tuple[int, int, int]:
        """Convert HA HSV color values to Sber HSV format.

        Conversion rules:
        - H: 0-360 -> 0-360 (no change)
        - S: 0-100% -> 0-1000 (multiply by 10)
        - V: 0-255 -> 100-1000 (linear mapping)

        Args:
            ha_hue: Hue in degrees (0-360), or None for default 0.
            ha_saturation: Saturation percentage (0-100), or None for default 0.
            ha_brightness: Brightness value (0-255), or None for default 0.

        Returns:
            Tuple of (sber_hue, sber_saturation, sber_value) as integers.
        """
        # Нормализация значений HA
        ha_hue = max(0, min(360, ha_hue if ha_hue is not None else 0))  # H: 0–360
        ha_saturation = max(0, min(100, ha_saturation if ha_saturation is not None else 0))  # S: 0–100%
        ha_brightness = int(max(0, min(255, ha_brightness if ha_brightness is not None else 0)))  # V: 0–255

        # Конвертация в Sber HSV
        sber_hue = ha_hue
        sber_saturation = ha_saturation * 10  # 0–100% → 0–1000
        sber_value = (ha_brightness / 255) * 900 + 100  # 0–255 → 100–1000

        return round(sber_hue), round(sber_saturation), round(sber_value)

    @staticmethod
    def sber_to_ha_hsv(
        sber_hue: float | None,
        sber_saturation: float | None,
        sber_value: float | None,
    ) -> tuple[int, int, int]:
        """Convert Sber HSV color values to HA HSV format.

        Conversion rules:
        - H: 0-360 -> 0-360 (no change)
        - S: 0-1000 -> 0-100% (divide by 10)
        - V: 100-1000 -> 0-255 (linear mapping)

        Args:
            sber_hue: Hue in degrees (0-360), or None for default 0.
            sber_saturation: Saturation (0-1000), or None for default 0.
            sber_value: Value/brightness (100-1000), or None for default 0.

        Returns:
            Tuple of (ha_hue, ha_saturation, ha_brightness) as integers.
        """
        # Нормализация значений Sber
        sber_hue = max(0, min(360, sber_hue if sber_hue is not None else 0))  # H: 0–360
        sber_saturation = max(0, min(1000, sber_saturation if sber_saturation is not None else 0))  # S: 0–1000
        if sber_value is None:
            sber_value = 0
        sber_value = max(0, min(1000, sber_value))  # V: 0–1000 (values <100 map to brightness 0)

        # Конвертация в HA HSV
        ha_hue = sber_hue
        ha_saturation = sber_saturation / 10  # 0–1000 → 0–100%
        ha_brightness = max(0.0, ((sber_value - 100) / 900) * 255)  # 100–1000 → 0–255; <100 → 0

        return round(ha_hue), round(ha_saturation), round(ha_brightness)
