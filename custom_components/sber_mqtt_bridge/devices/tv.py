"""Sber TV entity -- maps HA media_player entities to Sber tv category.

Supports on/off, volume, mute, source selection, channel switching,
navigation direction, and custom key commands.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import ClassVar

from .._generated.reference_values import FEATURE_ENUM_VALUES
from ..sber_constants import SberFeature, SberValueType
from ..sber_models import make_bool_value, make_enum_value, make_integer_value, make_state
from .base_entity import AttrSpec, BaseEntity, _safe_bool_parser, _safe_int_parser
from .utils.enum_matcher import invert_value_map, map_ha_values

_LOGGER = logging.getLogger(__name__)

TV_CATEGORY = "tv"
"""Sber device category for TV entities."""

SOURCE_VALUES: frozenset[str] = FEATURE_ENUM_VALUES["source"]
"""Every input Sber's ``source`` function documents.

``hdmi1``…``hdmi3``, ``tv``, ``av``, ``content``, ``screencast`` plus the
relative ``+`` / ``-``.  Home Assistant names the same inputs in prose
(``"HDMI 1"``, ``"Станция"``), so the two are reconciled through
:mod:`.utils.enum_matcher` rather than published as-is."""

_CUSTOM_KEY_SERVICE_MAP: dict[str, str] = {
    "play": "media_play",
    "pause": "media_pause",
    "next": "media_next_track",
    "previous": "media_previous_track",
    "confirm": "media_play_pause",
    "stop": "media_stop",
    "rewind": "media_previous_track",
    "fast_forward": "media_next_track",
}
"""Mapping of Sber custom_key values to HA media_player service names.

The documented vocabulary is ``back, confirm, home, next, pause, play,
previous``; ``back`` and ``home`` have no ``media_player`` equivalent and
are logged as unsupported.  ``stop`` / ``rewind`` / ``fast_forward`` are
not in that vocabulary but are kept as tolerated aliases — accepting a
key the cloud is not documented to send costs nothing, while refusing one
it does send loses the button.
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
    - Source (input) selection, translated between HA's prose input
      names and Sber's closed ``source`` vocabulary (:data:`SOURCE_VALUES`)
    - Channel switching (+/-)
    - Navigation direction (up/down/left/right/ok)

    Command handlers address the entity in **its own** HA domain
    (:meth:`get_entity_domain`) rather than a hard-coded ``media_player``:
    ``tv`` is an overridable category, so a ``switch.tv_power`` promoted
    to ``tv`` by a user type override would otherwise be driven with
    ``media_player.turn_on`` — a call HA cannot route, silently dropping
    every Sber command.  For a ``media_player.*`` entity — the only domain
    the category maps to by itself — the emitted calls are unchanged.
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
            # ``None`` (not ``[]``) when the attribute is absent or empty,
            # so ``preserve_on_missing`` keeps the list we already had.
            # HA drops ``source_list`` from the attributes entirely when it
            # is empty (``MediaPlayerEntity.capability_attributes`` adds it
            # only ``if (source_list := self.source_list)``), and several
            # core integrations rebuild it asynchronously — braviatv clears
            # it at the top of every update and returns early while the TV
            # is off; apple_tv fills it only after a fetch that can fail.
            # Rebuilding the mapping from such a blank would silently drop
            # every ``source`` command the cloud sends (the app keeps
            # rendering the HDMI button, and it stops doing anything), and
            # would churn ``model.id`` by republishing narrower
            # ``allowed_values``.
            converter=lambda attrs: attrs.get("source_list") or None,
            default=[],
            preserve_on_missing=True,
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
        self._source_to_sber: dict[str, str] = {}
        self._source_to_ha: dict[str, str] = {}

    def fill_by_ha_state(self, ha_state: dict) -> None:
        """Parse HA state and update TV attributes.

        Args:
            ha_state: HA state dict with 'state' and 'attributes' keys.
        """
        super().fill_by_ha_state(ha_state)
        attrs = ha_state.get("attributes", {})
        self._apply_attr_specs(attrs)
        self._source_to_sber = map_ha_values(self._source_list, SOURCE_VALUES)
        self._source_to_ha = invert_value_map(self._source_to_sber)
        self.current_state = ha_state.get("state") not in ("off", "standby", "unavailable", "unknown")

    def _create_features_list(self) -> list[str]:
        """Return Sber feature list for TV capabilities.

        ``source`` is advertised only when at least one HA input name
        resolves to a documented Sber value.  A TV whose inputs are all
        unrecognisable (a Yandex station reporting a single ``"Станция"``
        source) gets no ``source`` control at all — Sber could not switch
        to a value it does not know, so an empty control is the honest
        answer.

        Returns:
            List of Sber feature strings supported by this entity.
        """
        features = [*super()._create_features_list(), "on_off", "volume_int", "volume", "mute"]
        if self._source_to_sber:
            features.append("source")
        features.extend(["channel", "channel_int", "direction", "custom_key", "number"])
        return features

    def create_allowed_values_list(self) -> dict[str, dict]:
        """Build allowed values map for TV features.

        Per Sber TV reference, only ``source`` needs explicit allowed_values
        (instance-specific source list).  All other TV features (volume_int,
        channel, direction, etc.) use Sber cloud defaults and MUST NOT be
        overridden — sending extra keys causes silent device rejection.

        The declared values are the *Sber* ones this TV can actually reach
        (``hdmi1``, ``tv``, …), never the HA input names: the app renders
        exactly what is declared and then sends it back as a command, so a
        label outside :data:`SOURCE_VALUES` would be a control that cannot
        work.

        Returns:
            Dict mapping feature key to its allowed values descriptor.
        """
        allowed: dict[str, dict] = {}
        if self._source_to_sber:
            allowed["source"] = {
                "type": "ENUM",
                "enum_values": {"values": list(self._source_to_sber.values())},
            }
        return allowed

    def _build_current_state(self) -> dict[str, dict]:
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
        # An input Sber has no word for (a streaming app, "HDMI 4") is
        # omitted rather than published raw.  Accepted consequence: the app
        # keeps showing the last input it *did* understand, because the
        # publisher sends the whole states list and Sber simply sees no new
        # value.  The alternative — publishing the HA label — is worse: it
        # is outside the documented vocabulary, so the cloud cannot route it
        # and the control dies altogether.
        sber_source = self._source_to_sber.get(self._source or "")
        if sber_source:
            states.append(make_state(SberFeature.SOURCE, make_enum_value(sber_source)))
        return {self.entity_id: {"states": states}}

    @property
    def _cmd_handlers(self) -> dict[str, Callable[[dict], list[dict]]]:
        """Return dispatch map from Sber feature key to handler method."""
        return {
            SberFeature.ON_OFF: self._cmd_on_off,
            SberFeature.VOLUME_INT: self._cmd_volume_int,
            SberFeature.MUTE: self._cmd_mute,
            SberFeature.SOURCE: self._cmd_source,
            SberFeature.CHANNEL_INT: self._cmd_channel_int,
            SberFeature.CHANNEL: lambda v: self._cmd_simple_enum(v, _CHANNEL_ENUM_SERVICE),
            SberFeature.DIRECTION: lambda v: self._cmd_simple_enum(v, _DIRECTION_SERVICE),
            SberFeature.VOLUME: lambda v: self._cmd_simple_enum(v, _VOLUME_ENUM_SERVICE),
            SberFeature.NUMBER: self._cmd_number,
            SberFeature.CUSTOM_KEY: self._cmd_custom_key,
        }

    def _cmd_on_off(self, value: dict) -> list[dict]:
        if value.get("type") != SberValueType.BOOL:
            return []
        on = value.get("bool_value", False)
        return [self._build_on_off_service_call(self.entity_id, self.get_entity_domain(), on)]

    def _cmd_volume_int(self, value: dict) -> list[dict]:
        vol = _safe_int_parser(value.get("integer_value"))
        if vol is None:
            return []
        return [
            self._build_service_call(
                self.get_entity_domain(),
                "volume_set",
                self.entity_id,
                {"volume_level": vol / 100.0},
            )
        ]

    def _cmd_mute(self, value: dict) -> list[dict]:
        muted = value.get("bool_value", False)
        return [
            self._build_service_call(
                self.get_entity_domain(),
                "volume_mute",
                self.entity_id,
                {"is_volume_muted": muted},
            )
        ]

    def _cmd_source(self, value: dict) -> list[dict]:
        """Translate a Sber ``source`` value back to the HA input name.

        Sber sends its own vocabulary (``hdmi1``), while
        ``media_player.select_source`` only accepts a name from
        ``source_list`` (``"HDMI 1"``).  Passing the Sber value straight
        through made HA reject the call, so an unmapped value is dropped
        instead — it can only reach us for an input this TV never
        advertised.

        Args:
            value: Sber value dict from the command payload.

        Returns:
            Single-element list with the ``select_source`` call, or empty.
        """
        source = value.get("enum_value")
        if not source:
            return []
        ha_source = self._source_to_ha.get(source)
        if ha_source is None:
            # Warning, not debug: the command is being dropped, and from
            # the user's seat that is a button in the Sber app that does
            # nothing.  Silence here made it unexplainable.
            _LOGGER.warning(
                "Sber asked %s for source '%s', which maps to no current HA input (known: %s) — ignoring",
                self.entity_id,
                source,
                sorted(self._source_to_ha),
            )
            return []
        return [
            self._build_service_call(self.get_entity_domain(), "select_source", self.entity_id, {"source": ha_source})
        ]

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
            self.get_entity_domain(),
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
        return [self._build_service_call(self.get_entity_domain(), service, self.entity_id)]

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
        return [self._build_service_call(self.get_entity_domain(), service, self.entity_id)]
