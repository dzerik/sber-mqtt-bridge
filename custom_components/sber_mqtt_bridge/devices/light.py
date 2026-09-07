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
from .base_entity import SENSOR_LINK_ROLES, AttrSpec, BaseEntity, _safe_int_parser
from .utils.color_converter import ColorConverter
from .utils.linear_converter import LinearConverter

LIGHT_ENTITY_CATEGORY = "light"
"""Sber device category for light entities."""

COLOR_MODES = {"hs", "rgb", "rgbw", "rgbww", "xy"}
"""HA color modes that map to Sber colour features."""

NON_DIMMABLE_MODES = {"onoff", "unknown"}
"""HA color modes that do NOT imply brightness support.

Per HA light architecture, every color mode except ``onoff`` and
``unknown`` supports brightness — including ``color_temp`` and ``white``
(issue #44: CCT-only lamps must expose ``light_brightness``)."""

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

    Command handlers address the entity in **its own** HA domain
    (:meth:`get_entity_domain`) rather than a hard-coded ``light``, so an
    entity forced into ``light`` / ``led_strip`` by a user type override
    is driven through services that actually exist for it.  For a
    ``light.*`` entity — the only domain these categories map to — the
    emitted calls are unchanged.
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
        # NOTE: rgb_color / xy_color are intentionally NOT parsed — all
        # colour logic (including LedStripEntity) works exclusively with
        # hs_color, which HA always provides alongside rgb/xy for lights
        # in a colour mode.  Parsing them was dead per-state-change work
        # that falsely implied RGB/XY support.
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

        # Последние известные значения каналов.  HA обнуляет атрибуты
        # неактивного канала (в цветном режиме нет color_temp_kelvin, в
        # состоянии off нет ни hs_color, ни brightness), а Sber ждёт в
        # ответе на status_request все заявленные функции (issue #63).
        self._last_hs_color: list[float] | None = None
        self._last_ha_brightness: int = 0
        self._last_sber_color_temp: int | None = None
        self._last_light_mode: str | None = None

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

        # Update color_temp converter limits.  Modern HA (≥2026) publishes
        # only kelvin attributes; mireds are a legacy fallback (issue #44
        # audit — CCT state was silently unparsed on current HA).
        min_kelvin = _safe_int_parser(attrs.get("min_color_temp_kelvin"))
        max_kelvin = _safe_int_parser(attrs.get("max_color_temp_kelvin"))
        if min_kelvin and max_kelvin:
            # Kelvin and mireds are reciprocal: min_kelvin → max_mireds.
            self.min_mireds = round(1_000_000 / max_kelvin)
            self.max_mireds = round(1_000_000 / min_kelvin)
        else:
            self.max_mireds = attrs.get("max_mireds", 500)
            self.min_mireds = attrs.get("min_mireds", 153)
        if self.max_mireds is not None and self.min_mireds is not None:
            self.color_temp_converter.set_ha_limits(self.min_mireds, self.max_mireds)

        # Derive on/off state from HA state string
        self.current_state = ha_state.get("state", "off") == "on"

        # Apply LinearConverter to raw brightness → Sber scale
        self.current_sber_brightness = self.brightness_converter.ha_to_sber(self._ha_brightness_raw)

        # Apply LinearConverter to raw color_temp → Sber scale.  Prefer
        # kelvin (authoritative in modern HA) over legacy mireds.
        ha_kelvin = _safe_int_parser(attrs.get("color_temp_kelvin"))
        if ha_kelvin:
            self.current_sber_color_temp = self.color_temp_converter.ha_to_sber(round(1_000_000 / ha_kelvin))
        elif attrs.get("color_temp") is not None:
            self.current_sber_color_temp = self.color_temp_converter.ha_to_sber(attrs["color_temp"])
        else:
            self.current_sber_color_temp = None

        self._remember_last_known()

    def _remember_last_known(self) -> None:
        """Latch the last observed value of every light channel.

        HA publishes only the attributes of the *active* channel: a lamp
        in a colour mode reports no ``color_temp_kelvin``, and a lamp that
        is off reports neither ``hs_color`` nor ``brightness``.  Sber, on
        the contrary, requires a status_request answer to carry **all**
        declared features, and both ``light_colour`` / ``light_colour_temp``
        are documented as state-holding.  The latched values also give
        :meth:`_cmd_mode` a meaningful colour temperature to switch to
        while the lamp sits in a colour mode (issue #63).
        """
        if self.current_sber_color_temp is not None:
            self._last_sber_color_temp = self.current_sber_color_temp
        if isinstance(self.hs_color, (list, tuple)) and len(self.hs_color) >= 2:
            self._last_hs_color = [self.hs_color[0], self.hs_color[1]]
        if self._ha_brightness_raw:
            self._last_ha_brightness = self._ha_brightness_raw
        if self.current_color_mode is not None:
            self._last_light_mode = "colour" if self._is_current_color_mode_colored() else "white"

    def _create_features_list(self) -> list[str]:
        """Return Sber feature list based on available light capabilities.

        Dynamically includes color, brightness, and color temperature features
        only when the HA entity supports the corresponding color modes.

        Returns:
            List of Sber feature strings supported by this entity.
        """
        features = [*super()._create_features_list(), "on_off"]

        modes = set(self.supported_color_modes)
        if COLOR_MODES & modes:
            features += ["light_colour", "light_mode"]
        if modes - NON_DIMMABLE_MODES:
            # Any color mode except onoff/unknown implies brightness in HA.
            features.append("light_brightness")
        if "color_temp" in modes:
            features.append("light_colour_temp")

        return features

    def create_allowed_values_list(self) -> dict[str, dict]:
        """Build allowed values map for light features.

        Built from the **final** features list (with user overrides
        applied) rather than from capability heuristics, so a feature
        added via ``extra_features`` always gets its limits — without
        them Sber renders a dead slider (issue #44).

        Returns:
            Dict mapping feature key to its allowed values descriptor.
        """
        features = set(self.get_final_features_list())
        allowed_values: dict[str, dict] = {}

        if "light_brightness" in features:
            allowed_values["light_brightness"] = {
                "type": "INTEGER",
                "integer_values": {"min": "100", "max": "900", "step": "1"},
            }
        # ``light_colour`` deliberately gets no entry: Sber documents
        # ``allowed_values`` for FLOAT / INTEGER / ENUM only
        # (developers.sber.ru/docs/ru/smarthome/c2c/allowed_values), and a
        # bare ``{"type": "COLOUR"}`` carries no ``*_values`` box, so it
        # overrides nothing while making the model descriptor malformed.
        if "light_mode" in features:
            allowed_values["light_mode"] = {"type": "ENUM", "enum_values": {"values": ["white", "colour"]}}
        if "light_colour_temp" in features:
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

    def _last_known_colour_value(self) -> dict | None:
        """Build the ``light_colour`` value from the last observed HA colour.

        Uses the latched hue/saturation pair (see
        :meth:`_remember_last_known`) so the colour survives both a switch
        to the white channel and the lamp being off, where HA reports no
        ``hs_color`` at all.

        Returns:
            A Sber ``colour_value`` payload, or ``None`` if this lamp's
            colour has never been observed.
        """
        if self._last_hs_color is None:
            return None
        hue, saturation, value = ColorConverter.ha_to_sber_hsv(
            self._last_hs_color[0],
            self._last_hs_color[1],
            self._ha_brightness_raw or self._last_ha_brightness,
        )
        return make_colour_value(hue, saturation, value)

    def _build_current_state(self) -> dict[str, dict]:
        """Build Sber current state payload with all light attributes.

        Every state-holding feature the lamp declares is reported on every
        publish — ``light_colour``, ``light_colour_temp`` and ``light_mode``
        included, and in the off state too.  Sber answers a
        ``down/status_request`` with this very payload and requires it to
        carry all declared functions, while HA only ever exposes the
        currently active channel, so the latched values from
        :meth:`_remember_last_known` fill the gaps (issue #63).  Keys the
        lamp does not declare are dropped by
        :meth:`~.base_entity.BaseEntity._filter_undeclared_states`, so a
        CCT-only lamp still never publishes ``light_colour``.

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

        colour_value = self._last_known_colour_value()
        if colour_value is not None:
            states.append(make_state(SberFeature.LIGHT_COLOUR, colour_value))

        if self._last_sber_color_temp is not None:
            states.append(make_state(SberFeature.LIGHT_COLOUR_TEMP, make_integer_value(self._last_sber_color_temp)))

        mode = self._last_light_mode or ("colour" if self._is_current_color_mode_colored() else "white")
        states.append(make_state(SberFeature.LIGHT_MODE, make_enum_value(mode)))

        return {self.entity_id: {"states": states}}

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
        return [self._build_on_off_service_call(self.entity_id, self.get_entity_domain(), on)]

    def _cmd_brightness(self, value: dict) -> list[dict]:
        """Handle ``light_brightness``: set brightness via ``turn_on``."""
        sber_br_value = _safe_int_parser(value.get("integer_value"))
        if sber_br_value is None:
            return []
        ha_br_value = self.brightness_converter.sber_to_ha(sber_br_value)
        # brightness=0 в HA означает «выключить» (light/__init__.py), а
        # минимум слайдера Sber (100) конвертируется ровно в 0 — нижнее
        # положение гасило лампу и замыкало цикл (issue #63).  Как и в
        # _cmd_colour, держим не ниже 1.
        brightness = max(1, min(int(ha_br_value), 255))
        return [
            self._build_service_call(self.get_entity_domain(), "turn_on", self.entity_id, {"brightness": brightness})
        ]

    def _cmd_colour(self, value: dict) -> list[dict]:
        """Handle ``light_colour``: set HSV color via ``turn_on``."""
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
                self.get_entity_domain(),
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
        domain = self.get_entity_domain()
        if mode_value == "colour":
            if isinstance(self.hs_color, (list, tuple)) and len(self.hs_color) >= 2:
                return [
                    self._build_service_call(
                        domain,
                        "turn_on",
                        self.entity_id,
                        {"hs_color": [self.hs_color[0], self.hs_color[1]]},
                    )
                ]
            return [{"update_state": True}]
        # white mode
        if "color_temp" in self.supported_color_modes:
            # CCT-capable light — real colour temperature.  The branch is
            # chosen by *capability* only: HA blanks color_temp_kelvin
            # while the lamp sits in a colour mode, so also requiring a
            # live value dropped every two-mode lamp into the RGB-only
            # branch below and "white" arrived as a desaturated colour
            # (issue #63).
            sber_color_temp = self.current_sber_color_temp
            if sber_color_temp is None:
                # Prefer the white the user last chose; fall back to the
                # middle of the range for a lamp never seen in white.
                sber_color_temp = self._last_sber_color_temp
            if sber_color_temp is None:
                sber_color_temp = (
                    self.color_temp_converter.sber_side_min + self.color_temp_converter.sber_side_max
                ) // 2
            ha_mireds = self.color_temp_converter.sber_to_ha(sber_color_temp)
            ha_kelvin = int(1_000_000 / max(ha_mireds, 1))
            return [
                self._build_service_call(
                    domain,
                    "turn_on",
                    self.entity_id,
                    {"color_temp_kelvin": ha_kelvin},
                )
            ]
        # RGB-only light — "white" means desaturated RGB (hue 0, saturation 0).
        if COLOR_MODES & set(self.supported_color_modes):
            return [
                self._build_service_call(
                    domain,
                    "turn_on",
                    self.entity_id,
                    {"hs_color": [0, 0]},
                )
            ]
        return [{"update_state": True}]

    def _cmd_colour_temp(self, value: dict) -> list[dict]:
        """Handle ``light_colour_temp``: set colour temperature via turn_on."""
        sber_color_temp = _safe_int_parser(value.get("integer_value"))
        if sber_color_temp is None:
            return []
        ha_mireds = self.color_temp_converter.sber_to_ha(sber_color_temp)
        ha_kelvin = int(1_000_000 / max(ha_mireds, 1))
        return [
            self._build_service_call(
                self.get_entity_domain(), "turn_on", self.entity_id, {"color_temp_kelvin": ha_kelvin}
            )
        ]
