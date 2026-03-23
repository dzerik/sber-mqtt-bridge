"""Sber Light entity — maps HA light to Sber light category.

Supports brightness, color temperature, RGB color (HSV), and light mode.
Uses LinearConverter for value range mapping and ColorConverter for HSV.
"""

from __future__ import annotations

import logging

from .base_entity import BaseEntity
from .utils.color_converter import ColorConverter
from .utils.linear_converter import LinearConverter

LIGHT_ENTITY_CATEGORY = "light"
"""Sber device category for light entities."""

_LOGGER = logging.getLogger(__name__)


class LightEntity(BaseEntity):
    """Sber light entity with brightness, color, and color temperature support.

    Maps HA light entities to the Sber 'light' category with support for:
    - On/off control
    - Brightness (scaled 0-255 HA ↔ 50-1000 Sber)
    - Color temperature (mireds ↔ 0-1000 Sber, reversed)
    - RGB color via HSV conversion
    - Light mode (white / colour)
    """

    def __init__(self, ha_entity_data: dict) -> None:
        """Initialize light entity from HA entity data.

        Args:
            ha_entity_data: HA entity registry dict.
        """
        super().__init__(LIGHT_ENTITY_CATEGORY, ha_entity_data)
        self.supported_features: int = 0
        self.max_mireds: int = 500
        self.min_mireds: int = 153
        self.supported_color_modes: list[str] = []
        self.current_state: bool = False
        self.current_sber_brightness: int = 0
        self.current_sber_color_temp: int | None = 0
        self.current_color_mode: str | None = None
        self.hs_color: list[float] | None = None
        self.rgb_color: list[int] | None = None
        self.xy_color: list[float] | None = None

        self.brightness_converter = LinearConverter()
        self.brightness_converter.set_ha_limits(0, 255)
        self.brightness_converter.set_sber_limits(50, 1000)

        self.color_temp_converter = LinearConverter()
        self.color_temp_converter.set_reversed(True)
        self.color_temp_converter.set_ha_limits(153, 500)
        self.color_temp_converter.set_sber_limits(0, 1000)

    def fill_by_ha_state(self, ha_state: dict) -> None:
        """Parse HA state and update all light attributes.

        Args:
            ha_state: HA state dict with 'state' and 'attributes' keys.
        """
        super().fill_by_ha_state(ha_state)
        attrs = ha_state.get("attributes", {})

        self.max_mireds = attrs.get("max_mireds", 500)
        self.min_mireds = attrs.get("min_mireds", 153)
        if self.max_mireds is not None and self.min_mireds is not None:
            self.color_temp_converter.set_ha_limits(self.min_mireds, self.max_mireds)

        self.current_state = ha_state.get("state", "off") == "on"
        ha_brightness = attrs.get("brightness", 0)
        ha_brightness = int(ha_brightness) if ha_brightness is not None else 0

        self.current_sber_brightness = self.brightness_converter.ha_to_sber(ha_brightness)

        ha_color_temp = attrs.get("color_temp", 0)
        if ha_color_temp is not None:
            self.current_sber_color_temp = self.color_temp_converter.ha_to_sber(ha_color_temp)
        else:
            self.current_sber_color_temp = None

        self.current_color_mode = attrs.get("color_mode")
        self.supported_features = attrs.get("supported_features", 0)
        self.supported_color_modes = attrs.get("supported_color_modes", [])

        self.hs_color = attrs.get("hs_color")
        self.rgb_color = attrs.get("rgb_color")
        self.xy_color = attrs.get("xy_color")

    def create_features_list(self) -> list[str]:
        """Return Sber feature list based on available light capabilities.

        Dynamically includes color, brightness, and color temperature features
        only when the HA entity supports the corresponding color modes.

        Returns:
            List of Sber feature strings supported by this entity.
        """
        features = [*super().create_features_list(), "on_off"]

        if "xy" in self.supported_color_modes:
            features += ["light_colour", "light_mode", "light_brightness"]
        if "color_temp" in self.supported_color_modes:
            features.append("light_colour_temp")

        return features

    def create_allowed_values_list(self) -> dict[str, dict]:
        """Build allowed values map for light features.

        Returns:
            Dict mapping feature key to its allowed values descriptor.
        """
        allowed_values: dict[str, dict] = {}

        if "xy" in self.supported_color_modes:
            allowed_values["light_brightness"] = {"type": "INTEGER", "integer_values": {"min": 50, "max": 1000}}
            allowed_values["light_colour"] = {"type": "COLOUR"}
            allowed_values["light_mode"] = {"type": "ENUM", "enum_values": {"values": ["white", "colour"]}}

        if "color_temp" in self.supported_color_modes:
            allowed_values["light_colour_temp"] = {"type": "INTEGER", "integer_values": {"min": 0, "max": 1000}}

        return allowed_values

    def to_sber_state(self) -> dict:
        """Build full Sber device descriptor including allowed values.

        Features are already populated by ``super().to_sber_state()``.
        Only adds ``allowed_values`` on top.

        Returns:
            Sber device descriptor dict with model, features, and allowed_values.
        """
        res = super().to_sber_state()
        res["model"]["allowed_values"] = self.create_allowed_values_list()
        return res

    def _is_current_color_mode_colored(self) -> bool:
        """Check if the current color mode is a colored (non-white) mode.

        Returns:
            True if the light is in a color mode (not white/color_temp).
        """
        return self.current_color_mode not in ["white", "color_temp"]

    def to_sber_current_state(self) -> dict[str, dict]:
        """Build Sber current state payload with all light attributes.

        Includes online, on_off, brightness, color/color_temp, and light_mode
        depending on the current state and color mode.

        Returns:
            Dict mapping entity_id to its Sber state representation.
        """
        states = [
            {"key": "online", "value": {"type": "BOOL", "bool_value": self._is_online}},
            {"key": "on_off", "value": {"type": "BOOL", "bool_value": self.current_state}},
        ]

        if self.current_sber_brightness != 0:
            states.append(
                {"key": "light_brightness", "value": {"type": "INTEGER", "integer_value": self.current_sber_brightness}}
            )

        if self.current_state:
            if self._is_current_color_mode_colored() and isinstance(self.hs_color, list) and len(self.hs_color) >= 2:
                current_color_sber = ColorConverter.ha_to_sber_hsv(
                    self.hs_color[0], self.hs_color[1], self.current_sber_brightness
                )
                states.append(
                    {
                        "key": "light_colour",
                        "value": {
                            "type": "COLOUR",
                            "colour_value": {
                                "h": current_color_sber[0],
                                "s": current_color_sber[1],
                                "v": current_color_sber[2],
                            },
                        },
                    }
                )
                states.append({"key": "light_mode", "value": {"type": "ENUM", "enum_value": "colour"}})
            else:
                if self.current_sber_color_temp is not None:
                    states.append(
                        {
                            "key": "light_colour_temp",
                            "value": {"type": "INTEGER", "integer_value": self.current_sber_color_temp},
                        }
                    )
                states.append({"key": "light_mode", "value": {"type": "ENUM", "enum_value": "white"}})

        return {self.entity_id: {"states": states}}

    def process_cmd(self, cmd_data: dict) -> list[dict]:
        """Process Sber light commands and produce HA service calls.

        Handles the following Sber keys:
        - ``on_off``: turn_on / turn_off
        - ``light_brightness``: set brightness via turn_on
        - ``light_colour``: set HSV color via turn_on
        - ``light_mode``: switch between white/colour mode (local state only)
        - ``light_colour_temp``: set color temperature via turn_on

        Note: ``light_mode`` is tracked locally and triggers a state update
        to Sber without a HA service call (HA does not have a mode concept).

        State is NOT mutated here for on/off — it will be updated when HA fires
        a ``state_changed`` event. However, ``light_mode`` is a Sber-only concept
        and must be tracked locally.

        Args:
            cmd_data: Sber command dict with 'states' list.

        Returns:
            List of HA service call dicts to execute.
        """
        if cmd_data is None:
            return []

        processing_result: list[dict] = []

        for data_item in cmd_data.get("states", []):
            cmd_key = data_item.get("key", "")
            cmd_value = data_item.get("value", {})

            if cmd_key == "on_off" and cmd_value.get("type", "") == "BOOL":
                new_state = cmd_value.get("bool_value", False)
                processing_result.append(
                    {
                        "url": {
                            "type": "call_service",
                            "domain": "light",
                            "service": "turn_on" if new_state else "turn_off",
                            "target": {"entity_id": self.entity_id},
                        }
                    }
                )

            elif cmd_key == "light_brightness":
                sber_br_value = int(cmd_value.get("integer_value", 50))
                ha_br_value = self.brightness_converter.sber_to_ha(sber_br_value)
                brightness = max(0, min(int(ha_br_value), 255))
                processing_result.append(
                    {
                        "url": {
                            "type": "call_service",
                            "domain": "light",
                            "service": "turn_on",
                            "service_data": {"brightness": brightness},
                            "target": {"entity_id": self.entity_id},
                        }
                    }
                )

            elif cmd_key == "light_colour":
                hsv_color = cmd_value.get("colour_value")
                if hsv_color is not None:
                    color = ColorConverter.sber_to_ha_hsv(
                        min(hsv_color.get("h", 0), 360),
                        min(hsv_color.get("s", 0), 1000),
                        min(hsv_color.get("v", 0), 1000),
                    )
                else:
                    color = ColorConverter.ha_to_sber_hsv(0, 0, 0)

                processing_result.append(
                    {
                        "url": {
                            "type": "call_service",
                            "domain": "light",
                            "service": "turn_on",
                            "service_data": {
                                "hs_color": [color[0], color[1]],
                                "brightness": color[2],
                            },
                            "target": {"entity_id": self.entity_id},
                        }
                    }
                )

            elif cmd_key == "light_mode":
                # light_mode is a Sber-only concept — HA doesn't have it.
                # Must be tracked locally to report correct state back to Sber.
                mode_value = cmd_value.get("enum_value")
                self.current_color_mode = "xy" if mode_value == "colour" else "white"
                processing_result.append({"update_state": True})

            elif cmd_key == "light_colour_temp":
                sber_color_temp = int(cmd_value.get("integer_value") or 0)
                ha_color_temp = self.color_temp_converter.sber_to_ha(sber_color_temp)
                processing_result.append(
                    {
                        "url": {
                            "type": "call_service",
                            "domain": "light",
                            "service": "turn_on",
                            "service_data": {"color_temp": ha_color_temp},
                            "target": {"entity_id": self.entity_id},
                        }
                    }
                )

        _LOGGER.debug("(LightEntity.process_cmd) processing res: %s", processing_result)
        return processing_result
