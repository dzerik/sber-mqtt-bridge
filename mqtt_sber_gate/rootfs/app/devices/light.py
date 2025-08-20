# devices/light.py
from .base import BaseDevice


class LightDevice(BaseDevice):
    category = "light"
    _brightness: int = None
    _color: str = None
    _color_temperature: int = None
    _supported_features: int = 0
    _max_mireds: int = 500
    _min_mireds: int = 153
    _is_on: bool = False

    def __init__(self, ha_state):
        super().__init__(ha_state)
        self._is_on = ha_state["state"] == "on"
        self._supported_features = ha_state["attributes"].get("supported_features", 0)

        # Яркость
        if self._supported_features & 1:
            self._brightness = ha_state["attributes"].get("brightness", 255)
        else:
            self._brightness = None

        # Цвет
        if self._supported_features & 2:
            self._color = self._convert_color(ha_state["attributes"])
        else:
            self._color = None

        # Температура цвета
        if self._supported_features & 4:
            self._color_temperature = ha_state["attributes"].get("color_temp", 300)
        else:
            self._color_temperature = None

        # Дополнительные параметры
        self._max_mireds = ha_state["attributes"].get("max_mireds", 500)
        self._min_mireds = ha_state["attributes"].get("min_mireds", 153)

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
            "friendly_name": self.description,
            "supported_features": self._supported_features,
            "max_mireds": self.max_mireds,
            "min_mireds": self.min_mireds
        }

        if self._supported_features & 1:
            attrs["brightness"] = self._brightness
        if self._supported_features & 2:
            attrs["color"] = self.color
        if self._supported_features & 4:
            attrs["color_temp"] = self.color_temperature

        return res | {"attributes": attrs}

    def _create_features_list(self):
        """Формирует список возможных функций"""
        features = super()._create_features_list()

        if self._supported_features & 1:
            features += ["brightness"]
        if self._supported_features & 2:
            features += ["color"]
        if self._supported_features & 4:
            features += ["color_temperature"]

        return features

    def _create_allowed_values_list(self):
        """Формирует список допустимых значений"""
        allowed_values = {}

        if self._supported_features & 1:
            allowed_values["brightness"] = {
                "type": "RANGE",
                "range_values": {"min": 0, "max": 100}
            }
        if self._supported_features & 2:
            allowed_values["color"] = {
                "type": "STRING",
                "string_values": {"format": "hex"}
            }
        if self._supported_features & 4:
            allowed_values["color_temperature"] = {
                "type": "RANGE",
                "range_values": {
                    "min": self.min_mireds,
                    "max": self.max_mireds
                }
            }

        return allowed_values

    def to_sber_state(self):
        """Формирует состояние для Сбер"""
        res = super().to_sber_state()
        return res | {
            "features": self._create_features_list(),
            "allowed_values": self._create_allowed_values_list()
        }

    # --- Аксессоры ---
    @property
    def is_on(self) -> bool:
        return self._is_on

    @is_on.setter
    def is_on(self, value: bool):
        self._is_on = value

    @property
    def brightness(self) -> int:
        """Яркость (0-100% для Сбер)"""
        if not self._supported_features & 1:
            return 0
        return int(self._brightness * 100 / 255)

    @brightness.setter
    def brightness(self, value: int):
        if not self._supported_features & 1:
            raise ValueError("This device does not support brightness")
        if not 0 <= value <= 100:
            raise ValueError("Brightness must be between 0 and 100")
        self._brightness = int(value * 255 / 100)

    @property
    def color(self) -> str:
        """Цвет в формате HEX (#RRGGBB)"""
        if not self._supported_features & 2:
            return None
        return self._color

    @color.setter
    def color(self, value: str):
        if not self._supported_features & 2:
            raise ValueError("This device does not support color")
        if not value.startswith("#") or len(value) != 7:
            raise ValueError("Color must be a valid HEX string (e.g., #RRGGBB)")
        self._color = value

    @property
    def color_temperature(self) -> int:
        """Температура цвета (mireds)"""
        if not self._supported_features & 4:
            return None
        return self._color_temperature

    @color_temperature.setter
    def color_temperature(self, value: int):
        if not self._supported_features & 4:
            raise ValueError("This device does not support color temperature")
        if not self.min_mireds <= value <= self.max_mireds:
            raise ValueError(f"Color temperature must be between {self.min_mireds} and {self.max_mireds}")
        self._color_temperature = value

    @property
    def max_mireds(self) -> int:
        return self._max_mireds

    @property
    def min_mireds(self) -> int:
        return self._min_mireds

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

        if self._supported_features & 1 and "brightness" in cmd_data:
            return {
                "url": "/api/services/light/set_brightness",
                "data": {
                    "entity_id": self.id,
                    "brightness": int(cmd_data["brightness"] * 255 / 100)
                }
            }

        if self._supported_features & 2 and "color" in cmd_data:
            return {
                "url": "/api/services/light/turn_on",
                "data": {
                    "entity_id": self.id,
                    "rgb_color": self._hex_to_rgb(cmd_data["color"])
                }
            }

        if self._supported_features & 4 and "color_temperature" in cmd_data:
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
