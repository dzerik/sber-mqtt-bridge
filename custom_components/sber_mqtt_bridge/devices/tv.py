"""Sber TV entity -- maps HA media_player entities to Sber tv category.

Supports on/off, volume, mute, source selection, channel switching,
navigation direction, and custom key commands.
"""

from __future__ import annotations

import logging
from typing import ClassVar

from ..sber_constants import SberFeature, SberValueType
from ..sber_models import make_bool_value, make_enum_value, make_integer_value, make_state
from .base_entity import AttrSpec, BaseEntity, CommandResult, _safe_bool_parser, _safe_int_parser

_LOGGER = logging.getLogger(__name__)

TV_CATEGORY = "tv"
"""Sber device category for TV entities."""

_MP_DOMAIN = "media_player"
"""HA domain for TV / media player entities."""

_CUSTOM_KEY_SERVICE_MAP: dict[str, str] = {
    "play": "media_play",
    "pause": "media_pause",
    "stop": "media_stop",
    "rewind": "media_previous_track",
    "fast_forward": "media_next_track",
}
"""Mapping of Sber custom_key values to HA media_player service names.

Keys like 'back', 'home', 'menu' have no direct media_player equivalent
and are logged as unsupported.
"""

_CHANNEL_ENUM_SERVICE: dict[str, str] = {
    "+": "media_next_track",
    "-": "media_previous_track",
}
"""Sber ``channel`` ENUM direction to HA media_player service."""

_VOLUME_ENUM_SERVICE: dict[str, str] = {
    "+": "volume_up",
    "-": "volume_down",
}
"""Sber ``volume`` ENUM direction to HA media_player service."""

_DIRECTION_SERVICE: dict[str, str] = {
    "up": "volume_up",
    "down": "volume_down",
    "left": "media_previous_track",
    "right": "media_next_track",
    "ok": "media_play_pause",
}
"""Sber ``direction`` ENUM to HA media_player service."""


def _volume_converter(attrs: dict) -> int:
    """Convert HA volume_level (0.0-1.0 float) to Sber integer (0-100).

    Args:
        attrs: HA attributes dict.

    Returns:
        Integer volume 0-100, or 0 if missing/invalid.
    """
    raw = attrs.get("volume_level")
    if raw is None:
        return 0
    return int(float(raw) * 100)


class TvEntity(BaseEntity):
    """Sber TV entity for television and media player devices.

    Maps HA media_player entities to the Sber 'tv' category with support for:
    - On/off control
    - Volume level (Sber 0-100 integer, HA 0.0-1.0 float)
    - Mute toggle
    - Source (input) selection
    - Channel switching (+/-)
    - Navigation direction (up/down/left/right/ok)
    """

    ATTR_SPECS: ClassVar[tuple[AttrSpec, ...]] = (
        AttrSpec(
            field="_volume",
            converter=_volume_converter,
            default=0,
        ),
        AttrSpec(
            field="_is_muted",
            attr_keys=("is_volume_muted",),
            parser=_safe_bool_parser,
            default=False,
        ),
        AttrSpec(
            field="_source",
            attr_keys=("source",),
        ),
        AttrSpec(
            field="_source_list",
            converter=lambda attrs: attrs.get("source_list") or [],
            default=[],
        ),
        AttrSpec(
            field="_media_content_id",
            attr_keys=("media_content_id",),
        ),
    )

    def __init__(self, entity_data: dict) -> None:
        """Initialize TV entity.

        Args:
            entity_data: HA entity registry dict containing entity metadata.
        """
        super().__init__(TV_CATEGORY, entity_data)
        self.current_state: bool = False
        self._volume: int = 0
        self._is_muted: bool = False
        self._source: str | None = None
        self._source_list: list[str] = []
        self._media_content_id: str | None = None

    def fill_by_ha_state(self, ha_state: dict) -> None:
        """Parse HA state and update TV attributes.

        Args:
            ha_state: HA state dict with 'state' and 'attributes' keys.
        """
        super().fill_by_ha_state(ha_state)
        attrs = ha_state.get("attributes", {})
        self._apply_attr_specs(attrs)
        self.current_state = ha_state.get("state") not in ("off", "standby", "unavailable", "unknown")

    def _has_instance_allowed_values(self) -> bool:
        """TV source_list varies per device — model_id must be unique."""
        return bool(self._source_list)

    def _create_features_list(self) -> list[str]:
        """Return Sber feature list for TV capabilities.

        Returns:
            List of Sber feature strings supported by this entity.
        """
        features = [*super()._create_features_list(), "on_off", "volume_int", "volume", "mute"]
        if self._source_list:
            features.append("source")
        features.extend(["channel", "channel_int", "direction", "custom_key", "number"])
        return features

    def create_allowed_values_list(self) -> dict[str, dict]:
        """Build allowed values map for TV features.

        Per Sber TV reference, only ``source`` needs explicit allowed_values
        (instance-specific source list).  All other TV features (volume_int,
        channel, direction, etc.) use Sber cloud defaults and MUST NOT be
        overridden — sending extra keys causes silent device rejection.

        Returns:
            Dict mapping feature key to its allowed values descriptor.
        """
        allowed: dict[str, dict] = {}
        if self._source_list:
            allowed["source"] = {
                "type": "ENUM",
                "enum_values": {"values": self._source_list},
            }
        return allowed

    def to_sber_current_state(self) -> dict[str, dict]:
        """Build Sber current state payload with TV attributes.

        Returns:
            Dict mapping entity_id to its Sber state representation.
        """
        states = [
            make_state(SberFeature.ONLINE, make_bool_value(self._is_online)),
            make_state(SberFeature.ON_OFF, make_bool_value(self.current_state)),
            make_state(SberFeature.VOLUME_INT, make_integer_value(self._volume)),
            make_state(SberFeature.MUTE, make_bool_value(self._is_muted)),
        ]
        if self._source:
            states.append(make_state(SberFeature.SOURCE, make_enum_value(self._source)))
        return {self.entity_id: {"states": states}}

    def process_cmd(self, cmd_data: dict) -> list[CommandResult]:
        """Process Sber TV commands and produce HA service calls.

        Handles the following Sber keys:
        - ``on_off``: media_player.turn_on / media_player.turn_off
        - ``volume_int``: media_player.volume_set (Sber 0-100 → HA 0.0-1.0)
        - ``volume``: media_player.volume_up / media_player.volume_down
        - ``mute``: media_player.volume_mute
        - ``source``: media_player.select_source
        - ``custom_key``: media_player.media_play / pause / stop / etc.
        - ``number``: media_player.play_media (channel digit)

        Args:
            cmd_data: Sber command dict with 'states' list.

        Returns:
            List of HA service call dicts to execute.
        """
        results: list[dict] = []
        for item in cmd_data.get("states", []):
            key = item.get("key", "")
            value = item.get("value", {})
            vtype = value.get("type", "")
            if key == SberFeature.ON_OFF and vtype == SberValueType.BOOL:
                results.extend(self._cmd_on_off(value))
            elif key == SberFeature.VOLUME_INT and vtype == SberValueType.INTEGER:
                results.extend(self._cmd_volume_int(value))
            elif key == SberFeature.MUTE and vtype == SberValueType.BOOL:
                results.extend(self._cmd_mute(value))
            elif key == SberFeature.SOURCE and vtype == SberValueType.ENUM:
                results.extend(self._cmd_source(value))
            elif key == SberFeature.CHANNEL_INT and vtype == SberValueType.INTEGER:
                results.extend(self._cmd_channel_int(value))
            elif key == SberFeature.CHANNEL and vtype == SberValueType.ENUM:
                results.extend(self._cmd_simple_enum(value, _CHANNEL_ENUM_SERVICE))
            elif key == SberFeature.DIRECTION and vtype == SberValueType.ENUM:
                results.extend(self._cmd_simple_enum(value, _DIRECTION_SERVICE))
            elif key == SberFeature.VOLUME and vtype == SberValueType.ENUM:
                results.extend(self._cmd_simple_enum(value, _VOLUME_ENUM_SERVICE))
            elif key == SberFeature.NUMBER and vtype == SberValueType.INTEGER:
                results.extend(self._cmd_number(value))
            elif key == SberFeature.CUSTOM_KEY and vtype == SberValueType.ENUM:
                results.extend(self._cmd_custom_key(value))
        return results

    def _cmd_on_off(self, value: dict) -> list[dict]:
        on = value.get("bool_value", False)
        return [self._build_on_off_service_call(self.entity_id, _MP_DOMAIN, on)]

    def _cmd_volume_int(self, value: dict) -> list[dict]:
        vol = _safe_int_parser(value.get("integer_value"))
        if vol is None:
            return []
        return [
            self._build_service_call(
                _MP_DOMAIN,
                "volume_set",
                self.entity_id,
                {"volume_level": vol / 100.0},
            )
        ]

    def _cmd_mute(self, value: dict) -> list[dict]:
        muted = value.get("bool_value", False)
        return [
            self._build_service_call(
                _MP_DOMAIN,
                "volume_mute",
                self.entity_id,
                {"is_volume_muted": muted},
            )
        ]

    def _cmd_source(self, value: dict) -> list[dict]:
        source = value.get("enum_value")
        if not source:
            return []
        return [self._build_service_call(_MP_DOMAIN, "select_source", self.entity_id, {"source": source})]

    def _cmd_channel_int(self, value: dict) -> list[dict]:
        ch = _safe_int_parser(value.get("integer_value"))
        if ch is None:
            return []
        return [self._build_play_channel_call(ch)]

    def _cmd_number(self, value: dict) -> list[dict]:
        digit = _safe_int_parser(value.get("integer_value"))
        if digit is None:
            return []
        return [self._build_play_channel_call(digit)]

    def _build_play_channel_call(self, channel: int) -> dict:
        return self._build_service_call(
            _MP_DOMAIN,
            "play_media",
            self.entity_id,
            {
                "media_content_type": "channel",
                "media_content_id": str(channel),
            },
        )

    def _cmd_simple_enum(self, value: dict, service_map: dict[str, str]) -> list[dict]:
        """Dispatch helper for ENUM features mapping to parameterless services."""
        enum_value = value.get("enum_value")
        service = service_map.get(enum_value or "")
        if service is None:
            return []
        return [self._build_service_call(_MP_DOMAIN, service, self.entity_id)]

    def _cmd_custom_key(self, value: dict) -> list[dict]:
        custom = value.get("enum_value")
        if not custom:
            return []
        service = _CUSTOM_KEY_SERVICE_MAP.get(custom)
        if not service:
            _LOGGER.debug(
                "Unsupported custom_key '%s' for %s (no media_player equivalent)",
                custom,
                self.entity_id,
            )
            return []
        return [self._build_service_call(_MP_DOMAIN, service, self.entity_id)]
