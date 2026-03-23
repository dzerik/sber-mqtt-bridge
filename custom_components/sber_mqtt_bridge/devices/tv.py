"""Sber TV entity -- maps HA media_player entities to Sber tv category.

Supports on/off, volume, mute, and source selection.
"""

from __future__ import annotations

import logging

from .base_entity import BaseEntity

_LOGGER = logging.getLogger(__name__)

TV_CATEGORY = "tv"
"""Sber device category for TV entities."""


class TvEntity(BaseEntity):
    """Sber TV entity for television and media player devices.

    Maps HA media_player entities to the Sber 'tv' category with support for:
    - On/off control
    - Volume level (Sber 0-100 integer, HA 0.0-1.0 float)
    - Mute toggle
    - Source (input) selection
    """

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

    def fill_by_ha_state(self, ha_state: dict) -> None:
        """Parse HA state and update TV attributes.

        Args:
            ha_state: HA state dict with 'state' and 'attributes' keys.
        """
        super().fill_by_ha_state(ha_state)
        self.current_state = ha_state.get("state") not in ("off", "standby", "unavailable", "unknown")
        attrs = ha_state.get("attributes", {})
        volume_level = attrs.get("volume_level")
        self._volume = int(volume_level * 100) if volume_level is not None else 0
        self._is_muted = bool(attrs.get("is_volume_muted", False))
        self._source = attrs.get("source")
        self._source_list = attrs.get("source_list") or []

    def create_features_list(self) -> list[str]:
        """Return Sber feature list for TV capabilities.

        Returns:
            List of Sber feature strings supported by this entity.
        """
        return [*super().create_features_list(), "on_off", "volume_int", "mute", "source"]

    def create_allowed_values_list(self) -> dict[str, dict]:
        """Build allowed values map for volume and source features.

        Returns:
            Dict mapping feature key to its allowed values descriptor.
        """
        allowed: dict[str, dict] = {
            "volume_int": {
                "type": "INTEGER",
                "integer_values": {"min": "0", "max": "100", "step": "1"},
            },
        }
        if self._source_list:
            allowed["source"] = {
                "type": "ENUM",
                "enum_values": {"values": self._source_list},
            }
        return allowed

    def to_sber_state(self) -> dict:
        """Build full Sber device descriptor including allowed values.

        Returns:
            Sber device descriptor dict with model, features, and allowed_values.
        """
        res = super().to_sber_state()
        res["model"]["allowed_values"] = self.create_allowed_values_list()
        return res

    def to_sber_current_state(self) -> dict[str, dict]:
        """Build Sber current state payload with TV attributes.

        Returns:
            Dict mapping entity_id to its Sber state representation.
        """
        states = [
            {"key": "online", "value": {"type": "BOOL", "bool_value": self._is_online}},
            {"key": "on_off", "value": {"type": "BOOL", "bool_value": self.current_state}},
            {"key": "volume_int", "value": {"type": "INTEGER", "integer_value": str(self._volume)}},
            {"key": "mute", "value": {"type": "BOOL", "bool_value": self._is_muted}},
        ]
        if self._source:
            states.append({"key": "source", "value": {"type": "ENUM", "enum_value": self._source}})
        return {self.entity_id: {"states": states}}

    def process_cmd(self, cmd_data: dict) -> list[dict]:
        """Process Sber TV commands and produce HA service calls.

        Handles the following Sber keys:
        - ``on_off``: media_player.turn_on / media_player.turn_off
        - ``volume_int``: media_player.volume_set (Sber 0-100 → HA 0.0-1.0)
        - ``mute``: media_player.volume_mute
        - ``source``: media_player.select_source

        Args:
            cmd_data: Sber command dict with 'states' list.

        Returns:
            List of HA service call dicts to execute.
        """
        results: list[dict] = []
        for item in cmd_data.get("states", []):
            key = item.get("key")
            value = item.get("value", {})

            if key == "on_off" and value.get("type") == "BOOL":
                on = value.get("bool_value", False)
                results.append(self._build_on_off_service_call(self.entity_id, "media_player", on))

            elif key == "volume_int" and value.get("type") == "INTEGER":
                raw = value.get("integer_value")
                if raw is None:
                    continue
                ha_volume = int(raw) / 100.0
                results.append(
                    {
                        "url": {
                            "type": "call_service",
                            "domain": "media_player",
                            "service": "volume_set",
                            "service_data": {"volume_level": ha_volume},
                            "target": {"entity_id": self.entity_id},
                        }
                    }
                )

            elif key == "mute" and value.get("type") == "BOOL":
                muted = value.get("bool_value", False)
                results.append(
                    {
                        "url": {
                            "type": "call_service",
                            "domain": "media_player",
                            "service": "volume_mute",
                            "service_data": {"is_volume_muted": muted},
                            "target": {"entity_id": self.entity_id},
                        }
                    }
                )

            elif key == "source" and value.get("type") == "ENUM":
                source = value.get("enum_value")
                if not source:
                    continue
                results.append(
                    {
                        "url": {
                            "type": "call_service",
                            "domain": "media_player",
                            "service": "select_source",
                            "service_data": {"source": source},
                            "target": {"entity_id": self.entity_id},
                        }
                    }
                )
        return results
