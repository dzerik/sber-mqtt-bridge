"""Sber Light entity — maps HA light to Sber light category.

Supports brightness, color temperature, RGB color (HSV), and light mode.
Uses LinearConverter for value range mapping and ColorConverter for HSV.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import ClassVar

from ..sber_constants import SberFeature, SberValueType
from ..sber_models import (
    make_bool_value,
    make_colour_value,
    make_enum_value,
    make_integer_value,
    make_state,
)
from .base_entity import SENSOR_LINK_ROLES, AttrSpec, BaseEntity, CommandResult, _safe_int_parser
from .utils.color_converter import ColorConverter
from .utils.linear_converter import LinearConverter

LIGHT_ENTITY_CATEGORY = "light"
"""Sber device category for light entities."""

COLOR_MODES = {"hs", "rgb", "rgbw", "rgbww", "xy"}
"""HA color modes that map to Sber colour features."""

_LOGGER = logging.getLogger(__name__)


class LightEntity(BaseEntity):
    """Sber light entity with brightness, color, and color temperature support.

    Maps HA light entities to the Sber 'light' category with support for:
    - On/off control
    - Brightness (scaled 0-255 HA ↔ 100-900 Sber)
    - Color temperature (mireds ↔ 0-1000 Sber, reversed)
    - RGB color via HSV conversion
    - Light mode (white / colour)

    Accepts battery / battery_low / signal_strength linked sensors via
    :attr:`LINKABLE_ROLES` (Zigbee lights commonly report these).
    """

    LINKABLE_ROLES = SENSOR_LINK_ROLES

    ATTR_SPECS: ClassVar[tuple[AttrSpec, ...]] = (
        AttrSpec(
            field="supported_features",
            attr_keys=("supported_features",),
            parser=_safe_int_parser,
            default=0,
        ),
        AttrSpec(
            field="supported_color_modes",
            converter=lambda attrs: attrs.get("supported_color_modes") or [],
            default=[],
        ),
        AttrSpec(
            field="current_color_mode",
            attr_keys=("color_mode",),
        ),
        AttrSpec(
            field="_ha_brightness_raw",
            attr_keys=("brightness",),
            parser=_safe_int_parser,
            default=0,
        ),
        AttrSpec(
            field="hs_color",
            attr_keys=("hs_color",),
        ),
        AttrSpec(
            field="rgb_color",
            attr_keys=("rgb_color",),
        ),
        AttrSpec(
            field="xy_color",
            attr_keys=("xy_color",),
        ),
    )

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
        self._ha_brightness_raw: int = 0
        self.current_sber_brightness: int = 0
        self.current_sber_color_temp: int | None = 0
        self.current_color_mode: str | None = None
        self.hs_color: list[float] | None = None
        self.rgb_color: list[int] | None = None
        self.xy_color: list[float] | None = None

        self.brightness_converter = LinearConverter()
        self.brightness_converter.set_ha_limits(0, 255)
        self.brightness_converter.set_sber_limits(100, 900)

        self.color_temp_converter = LinearConverter()
        self.color_temp_converter.set_reversed(True)
        self.color_temp_converter.set_ha_limits(153, 500)
        self.color_temp_converter.set_sber_limits(0, 1000)

    def fill_by_ha_state(self, ha_state: dict) -> None:
        """Parse HA state and update all light attributes.

        Simple attribute extraction is handled declaratively via
        :attr:`ATTR_SPECS`.  Instance-specific LinearConverter transforms
        and state derivation remain here.

        Args:
            ha_state: HA state dict with 'state' and 'attributes' keys.
        """
        super().fill_by_ha_state(ha_state)
        attrs = ha_state.get("attributes", {})
        self._apply_attr_specs(attrs)

        # Update color_temp converter limits from entity-specific mireds range
        self.max_mireds = attrs.get("max_mireds", 500)
        self.min_mireds = attrs.get("min_mireds", 153)
        if self.max_mireds is not None and self.min_mireds is not None:
            self.color_temp_converter.set_ha_limits(self.min_mireds, self.max_mireds)

        # Derive on/off state from HA state string
        self.current_state = ha_state.get("state", "off") == "on"

        # Apply LinearConverter to raw brightness → Sber scale
        self.current_sber_brightness = self.brightness_converter.ha_to_sber(self._ha_brightness_raw)

        # Apply LinearConverter to raw color_temp → Sber scale
        ha_color_temp = attrs.get("color_temp", 0)
        if ha_color_temp is not None:
            self.current_sber_color_temp = self.color_temp_converter.ha_to_sber(ha_color_temp)
        else:
            self.current_sber_color_temp = None

    def _create_features_list(self) -> list[str]:
        """Return Sber feature list based on available light capabilities.

        Dynamically includes color, brightness, and color temperature features
        only when the HA entity supports the corresponding color modes.

        Returns:
            List of Sber feature strings supported by this entity.
        """
        features = [*super()._create_features_list(), "on_off"]

        if COLOR_MODES & set(self.supported_color_modes):
            features += ["light_colour", "light_mode", "light_brightness"]
        elif "brightness" in self.supported_color_modes:
            features.append("light_brightness")
        if "color_temp" in self.supported_color_modes:
            features.append("light_colour_temp")

        return features

    def create_allowed_values_list(self) -> dict[str, dict]:
        """Build allowed values map for light features.

        Returns:
            Dict mapping feature key to its allowed values descriptor.
        """
        allowed_values: dict[str, dict] = {}

        if COLOR_MODES & set(self.supported_color_modes):
            allowed_values["light_brightness"] = {
                "type": "INTEGER",
                "integer_values": {"min": "100", "max": "900", "step": "1"},
            }
            allowed_values["light_colour"] = {"type": "COLOUR"}
            allowed_values["light_mode"] = {"type": "ENUM", "enum_values": {"values": ["white", "colour"]}}
        elif "brightness" in self.supported_color_modes:
            allowed_values["light_brightness"] = {
                "type": "INTEGER",
                "integer_values": {"min": "100", "max": "900", "step": "1"},
            }

        if "color_temp" in self.supported_color_modes:
            allowed_values["light_colour_temp"] = {
                "type": "INTEGER",
                "integer_values": {"min": "0", "max": "1000", "step": "1"},
            }

        return allowed_values

    def create_dependencies(self) -> dict[str, dict]:
        """Return light_colour → light_mode dependency when both features exist.

        Returns:
            Dependencies dict for Sber model descriptor.
        """
        features = self.get_final_features_list()
        if "light_colour" in features and "light_mode" in features:
            return {
                "light_colour": {
                    "key": "light_mode",
                    "values": [{"type": "ENUM", "enum_value": "colour"}],
                },
            }
        return {}

    def _is_current_color_mode_colored(self) -> bool:
        """Check if the current color mode is a colored (non-white) mode.

        Returns:
            True if the light is in a color mode (not white/color_temp).
        """
        return self.current_color_mode in ("hs", "rgb", "rgbw", "rgbww", "xy")

    def to_sber_current_state(self) -> dict[str, dict]:
        """Build Sber current state payload with all light attributes.

        Includes online, on_off, brightness, color/color_temp, and light_mode
        depending on the current state and color mode.

        Per Sber C2C specification, ``integer_value`` is serialized as a string.

        Returns:
            Dict mapping entity_id to its Sber state representation.
        """
        states = [
            make_state(SberFeature.ONLINE, make_bool_value(self._is_online)),
            make_state(SberFeature.ON_OFF, make_bool_value(self.current_state)),
        ]

        if self.current_sber_brightness != 0:
            states.append(make_state(SberFeature.LIGHT_BRIGHTNESS, make_integer_value(self.current_sber_brightness)))

        if self.current_state:
            if (
                self._is_current_color_mode_colored()
                and isinstance(self.hs_color, (list, tuple))
                and len(self.hs_color) >= 2
            ):
                current_color_sber = ColorConverter.ha_to_sber_hsv(
                    self.hs_color[0], self.hs_color[1], self._ha_brightness_raw
                )
                states.append(
                    make_state(
                        SberFeature.LIGHT_COLOUR,
                        make_colour_value(current_color_sber[0], current_color_sber[1], current_color_sber[2]),
                    )
                )
                states.append(make_state(SberFeature.LIGHT_MODE, make_enum_value("colour")))
            else:
                if self.current_sber_color_temp is not None:
                    states.append(
                        make_state(SberFeature.LIGHT_COLOUR_TEMP, make_integer_value(self.current_sber_color_temp))
                    )
                states.append(make_state(SberFeature.LIGHT_MODE, make_enum_value("white")))

        return {self.entity_id: {"states": states}}

    def process_cmd(self, cmd_data: dict) -> list[CommandResult]:
        """Process Sber light commands and produce HA service calls.

        Uses a command handler dispatch table (``_cmd_handlers``) instead
        of an inline ``if/elif`` chain.  Each handler returns a list of
        service calls (possibly empty) for its sber key.

        Args:
            cmd_data: Sber command dict with 'states' list.

        Returns:
            List of HA service call dicts to execute.
        """
        if cmd_data is None:
            return []

        handlers = self._cmd_handlers
        results: list[dict] = []
        for item in cmd_data.get("states", []):
            handler = handlers.get(item.get("key", ""))
            if handler is None:
                continue
            results.extend(handler(item.get("value", {})))

        _LOGGER.debug("(LightEntity.process_cmd) processing res: %s", results)
        return results

    @property
    def _cmd_handlers(self) -> dict[str, Callable[[dict], list[dict]]]:
        """Return dispatch map from Sber feature key to handler method."""
        return {
            SberFeature.ON_OFF: self._cmd_on_off,
            SberFeature.LIGHT_BRIGHTNESS: self._cmd_brightness,
            SberFeature.LIGHT_COLOUR: self._cmd_colour,
            SberFeature.LIGHT_MODE: self._cmd_mode,
            SberFeature.LIGHT_COLOUR_TEMP: self._cmd_colour_temp,
        }

    def _cmd_on_off(self, value: dict) -> list[dict]:
        """Handle ``on_off`` feature: produce turn_on / turn_off call."""
        if value.get("type") != SberValueType.BOOL:
            return []
        on = value.get("bool_value", False)
        return [self._build_on_off_service_call(self.entity_id, "light", on)]

    def _cmd_brightness(self, value: dict) -> list[dict]:
        """Handle ``light_brightness``: set brightness via ``light.turn_on``."""
        sber_br_value = self._safe_int(value.get("integer_value"))
        if sber_br_value is None:
            return []
        ha_br_value = self.brightness_converter.sber_to_ha(sber_br_value)
        brightness = max(0, min(int(ha_br_value), 255))
        return [self._build_service_call("light", "turn_on", self.entity_id, {"brightness": brightness})]

    def _cmd_colour(self, value: dict) -> list[dict]:
        """Handle ``light_colour``: set HSV color via ``light.turn_on``."""
        hsv_color = value.get("colour_value")
        if hsv_color is not None:
            color = ColorConverter.sber_to_ha_hsv(
                max(0, min(hsv_color.get("h", 0), 360)),
                max(0, min(hsv_color.get("s", 0), 1000)),
                max(0, min(hsv_color.get("v", 0), 1000)),
            )
        else:
            color = (0, 0, 0)
        # Ensure brightness >= 1 to avoid turning off the lamp
        brightness = max(color[2], 1)
        return [
            self._build_service_call(
                "light",
                "turn_on",
                self.entity_id,
                {
                    "hs_color": [color[0], color[1]],
                    "brightness": brightness,
                },
            )
        ]

    def _cmd_mode(self, value: dict) -> list[dict]:
        """Handle ``light_mode``: switch between white / colour.

        ``light_mode`` is a Sber-only concept — HA doesn't have it.  To
        actually switch the lamp's mode, we send the current colour or
        colour_temp to HA so it transitions into the requested mode.

        NOTE: Do NOT mutate ``self.current_color_mode`` here — the actual
        mode will be updated by ``fill_by_ha_state`` when HA confirms the
        state change.  Premature mutation creates a window where the
        debounced publish can send stale / wrong mode to Sber.
        """
        mode_value = value.get("enum_value")
        if mode_value == "colour":
            if isinstance(self.hs_color, (list, tuple)) and len(self.hs_color) >= 2:
                return [
                    self._build_service_call(
                        "light",
                        "turn_on",
                        self.entity_id,
                        {"hs_color": [self.hs_color[0], self.hs_color[1]]},
                    )
                ]
            return [{"update_state": True}]
        # white mode
        if self.current_sber_color_temp is not None:
            ha_mireds = self.color_temp_converter.sber_to_ha(self.current_sber_color_temp)
            ha_kelvin = int(1_000_000 / max(ha_mireds, 1))
            return [
                self._build_service_call(
                    "light",
                    "turn_on",
                    self.entity_id,
                    {"color_temp_kelvin": ha_kelvin},
                )
            ]
        return [{"update_state": True}]

    def _cmd_colour_temp(self, value: dict) -> list[dict]:
        """Handle ``light_colour_temp``: set colour temperature via turn_on."""
        sber_color_temp = self._safe_int(value.get("integer_value"))
        if sber_color_temp is None:
            return []
        ha_mireds = self.color_temp_converter.sber_to_ha(sber_color_temp)
        ha_kelvin = int(1_000_000 / max(ha_mireds, 1))
        return [self._build_service_call("light", "turn_on", self.entity_id, {"color_temp_kelvin": ha_kelvin})]
