# devices/light.py
from .base_entity import BaseEntity

# class LightEntityFeature(IntFlag):
#     """Supported features of the light entity."""

#     EFFECT = 4
#     FLASH = 8
#     TRANSITION = 32

# supported_features sber
# light_brightness		Яркость устройства
# light_colour		Цвет устройства
# light_colour_temp		Температура цвета устройства
# light_mode		Режим работы устройства: цветной или белый цвет
# on_off	✔︎	Удаленное включение и выключение устройства
# online	✔︎	Доступность устройства: офлайн или онлайн

LIGHT_ENTITY_CATEGORY = "light"

class LightEntity(BaseEntity):
    brightness: int = None
    color: str = None
    color_temperature: int = None
    supported_features: int = 0
    max_mireds: int = 500
    min_mireds: int = 153
    supported_color_modes: list[str] = []

    def __init__(self, ha_entity_data: dict):
        super().__init__(LIGHT_ENTITY_CATEGORY, ha_entity_data)

    def fill_by_ha_state(self, ha_state):
        super().fill_by_ha_state(ha_state)
        self.supported_features = ha_state["attributes"].get("supported_features", 0)
        self.supported_color_modes = ha_state["attributes"].get("supported_color_modes", [])

        # Яркость
        if self.supported_features & 1:
            self.brightness = ha_state["attributes"].get("brightness", 255)
        else:
            self.brightness = None

        # Цвет
        if self.supported_features & 2:
            self.color = self.convert_color(ha_state["attributes"])
        else:
            self.color = None

        # Температура цвета
        if self.supported_features & 4:
            self.color_temperature = ha_state["attributes"].get("color_temp", 300)
        else:
            self.color_temperature = None

        # Дополнительные параметры
        self.max_mireds = ha_state["attributes"].get("max_mireds", 500)
        self.min_mireds = ha_state["attributes"].get("min_mireds", 153)

    def _convert_color(self, attrs):
        """Конвертирует цвет из формата HA в HEX (Sber).
        
        Приоритет:
        1. 'color' — если указан, используется напрямую.
        2. 'rgb_color' — преобразуется в HEX.
        3. 'hs_color' — преобразуется в RGB, затем в HEX.
        """
        if "color" in attrs:
            color = attrs["color"]
            if isinstance(color, str) and color.startswith("#") and len(color) == 7:
                return color.lower()  # Убедимся, что HEX в нижнем регистре
            # Если 'color' указан, но в неверном формате — игнорируем
            return None

        if "rgb_color" in attrs:
            r, g, b = attrs["rgb_color"]
            return f"#{r:02x}{g:02x}{b:02x}"

        if "hs_color" in attrs:
            h, s = attrs["hs_color"]
            import colorsys
            r, g, b = [int(c * 255) for c in colorsys.hsv_to_rgb(h / 360, s / 100, 1)]
            return f"#{r:02x}{g:02x}{b:02x}"

        return None

    def get_device_category(self):
        return self.category

    def to_ha_state(self):
        """Формирует состояние для Home Assistant"""
        res = super().to_ha_state()
        attrs = {
            "supported_features": self.supported_features,
            "max_mireds": self.max_mireds,
            "min_mireds": self.min_mireds,
            "color_temp": self.color_temperature,
            "brightness": self.brightness,
        }

        return res | {"attributes": attrs}

    def create_features_list(self):
        """Формирует список возможных функций"""
        features = super().create_features_list()

        if "xy" in self.supported_color_modes:
            features += ["light_colour", "light_mode", "light_brightness"]
        if "color_temp" in self.supported_color_modes:
            features += ["light_colour_temp"]

        return features

    def create_allowed_values_list(self):
        """Формирует список допустимых значений"""
        allowed_values = {}
# Тут надо понять, почему не принимает такие ограничения
        # if "xy" in self.supported_color_modes:
        #     allowed_values["light_brightness"] = {
        #         "type": "INTEGER",
        #         "integer_values": {"min": 0, "max": 100}
        #     }
        #     # allowed_values["light_colour"] = {
        #     #     "type": "COLOUR",
        #     # }
        if "color_temp" in self.supported_color_modes:
            allowed_values["light_colour_temp"] = {
                "type": "INTEGER",
                "integer_values": {
                    "min": self.min_mireds,
                    "max": self.max_mireds
                }
            }

        return allowed_values

    def to_sber_state(self):
        """Формирует состояние для Сбер"""
        res = super().to_sber_state()
        if res is None:
            return None
        
        res["model"] |= {
            "features": self.create_features_list(),
            "allowed_values": self.create_allowed_values_list()
        }

        return res

    # --- Методы ---
    def process_cmd(self, source, cmd_data):
        """Обрабатывает команду от Sber или HA"""
        if cmd_data is None:
            return None

        if "on_off" in cmd_data:
            return {
                "url": "/api/services/light/turn_{}".format("on" if cmd_data["on_off"] else "off"),
                "data": {"entity_id": self.id}
            }

        if self.supported_features & 1 and "brightness" in cmd_data:
            return {
                "url": "/api/services/light/set_brightness",
                "data": {
                    "entity_id": self.id,
                    "brightness": int(cmd_data["brightness"] * 255 / 100)
                }
            }

        if self.supported_features & 2 and "color" in cmd_data:
            return {
                "url": "/api/services/light/turn_on",
                "data": {
                    "entity_id": self.id,
                    "rgb_color": self.hex_to_rgb(cmd_data["color"])
                }
            }

        if self.supported_features & 4 and "color_temperature" in cmd_data:
            return {
                "url": "/api/services/light/turn_on",
                "data": {
                    "entity_id": self.id,
                    "color_temp": cmd_data["color_temperature"]
                }
            }

        return None

    def _hex_to_rgb(self, hex_color: str):
        """Конвертирует HEX в RGB (для HA)"""
        hex_color = hex_color.lstrip("#")
        return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
