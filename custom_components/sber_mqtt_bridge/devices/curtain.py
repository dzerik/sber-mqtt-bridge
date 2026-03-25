"""Sber Curtain entity -- maps HA cover entities to Sber curtain category."""

from __future__ import annotations

import logging

from .base_entity import BaseEntity

CURTAIN_ENTITY_CATEGORY = "curtain"
"""Sber device category for curtain/cover entities."""

_LOGGER = logging.getLogger(__name__)


class CurtainEntity(BaseEntity):
    """Sber curtain entity for cover control with position support.

    Maps HA cover entities to the Sber 'curtain' category with support for:
    - Position control (0-100%)
    - Open/close/stop commands
    - Open state reporting
    """

    current_position: int = 0
    """Current cover position (0-100%)."""

    min_position: int = 0
    """Minimum allowed position (0-100%)."""

    max_position: int = 100
    """Maximum allowed position (0-100%)."""

    battery_level: int = 0
    """Battery level percentage (0-100%)."""

    # _supported_features = []

    def __init__(self, entity_data: dict, category: str = CURTAIN_ENTITY_CATEGORY) -> None:
        """Initialize curtain entity.

        Args:
            entity_data: HA entity registry dict containing entity metadata.
            category: Sber device category (override in subclasses).
        """
        super().__init__(category, entity_data)
        self.current_position = 0  # Текущая позиция (0-100%)
        self._battery_level = 100  # Уровень заряда (0-100%)
        self._signal_strength_raw: int | None = None

        # self._supported_features = entity_data.get("supported_features", 0)  # Уровень заряда (0-100%)

        # self._supported_features = entity_data.get("supported_features", 0)

    def fill_by_ha_state(self, ha_state: dict) -> None:
        """Update state from Home Assistant data.

        Reads ``current_position`` from attributes; falls back to 100
        if state is 'opened', otherwise 0. Also reads signal strength
        from ``signal_strength``, ``rssi``, or ``linkquality``.

        Args:
            ha_state: HA state dict with 'state' and 'attributes' keys.
        """
        super().fill_by_ha_state(ha_state)
        attrs = ha_state.get("attributes", {})

        position = attrs.get("current_position")
        if position is not None:
            self.current_position = position
        else:
            self.current_position = 100 if self.state == "opened" else 0

        rssi = attrs.get("signal_strength") or attrs.get("rssi") or attrs.get("linkquality")
        if rssi is not None:
            try:
                self._signal_strength_raw = int(rssi)
            except (TypeError, ValueError):
                self._signal_strength_raw = None
        else:
            self._signal_strength_raw = None

    def _convert_position(self, ha_position: int) -> int:
        """Convert HA position (0-100) to Sber position (0-100).

        Currently a 1:1 mapping; override in subclasses if needed.

        Args:
            ha_position: Position value from Home Assistant.

        Returns:
            Position value for Sber protocol.
        """
        return int(ha_position)

    def process_cmd(self, cmd_data: dict) -> list[dict]:
        """Process Sber curtain commands and produce HA service calls.

        Handles the following Sber keys:
        - ``open_percentage``: set_cover_position (INTEGER 0-100)
        - ``cover_position``: set_cover_position (INTEGER 0-100)
        - ``open_set``: open_cover / close_cover / stop_cover (ENUM)

        Args:
            cmd_data: Sber command dict with 'states' list.

        Returns:
            List of HA service call dicts to execute.
        """
        processing_result = []

        for data_item in cmd_data.get("states", []):
            key = data_item.get("key")
            value = data_item.get("value", {})

            if key is None:
                continue

            if key in ("open_percentage", "cover_position"):
                ha_position = self._safe_int(value.get("integer_value")) or 0
                ha_position = max(0, min(100, ha_position))
                processing_result.append(
                    {
                        "url": {
                            "type": "call_service",
                            "domain": "cover",
                            "service": "set_cover_position",
                            "service_data": {"position": ha_position},
                            "target": {"entity_id": self.entity_id},
                        }
                    }
                )

            if key == "open_set":
                # Команда открытия/закрытия
                action = value.get("enum_value", None)
                if action is None:
                    continue

                if action == "open":
                    processing_result.append(
                        {
                            "url": {
                                "type": "call_service",
                                "domain": "cover",
                                "service": "open_cover",
                                "target": {"entity_id": self.entity_id},
                            }
                        }
                    )

                elif action == "close":
                    processing_result.append(
                        {
                            "url": {
                                "type": "call_service",
                                "domain": "cover",
                                "service": "close_cover",
                                "target": {"entity_id": self.entity_id},
                            }
                        }
                    )

                elif action == "stop":
                    processing_result.append(
                        {
                            "url": {
                                "type": "call_service",
                                "domain": "cover",
                                "service": "stop_cover",
                                "target": {"entity_id": self.entity_id},
                            }
                        }
                    )

        return processing_result

    @staticmethod
    def _rssi_to_signal_strength(rssi: int) -> str:
        """Convert raw RSSI/linkquality value to Sber signal_strength enum.

        Args:
            rssi: Raw RSSI (dBm, typically negative) or linkquality value.

        Returns:
            Sber enum string: 'high', 'medium', or 'low'.
        """
        if rssi > -50:
            return "high"
        if rssi > -70:
            return "medium"
        return "low"

    def create_features_list(self) -> list[str]:
        """Return Sber feature list for curtain capabilities.

        Includes open_percentage, open_set, open_state, and optionally
        signal_strength features.

        Returns:
            List of Sber feature strings supported by this entity.
        """
        features = [
            *super().create_features_list(),
            "open_percentage",
            "open_set",
            "open_state",
        ]
        if self._signal_strength_raw is not None:
            features.append("signal_strength")
        return features

    def to_sber_state(self) -> dict:
        """Build full Sber device descriptor including allowed values.

        Adds ``allowed_values`` for ``open_set`` (ENUM) and ``open_percentage``
        (INTEGER 0-100) features.

        Returns:
            Sber device descriptor dict with model, features, and allowed_values.
        """
        res = super().to_sber_state()
        res["model"]["allowed_values"] = {
            "open_set": {
                "type": "ENUM",
                "enum_values": {"values": ["open", "close", "stop"]},
            },
            "open_percentage": {
                "type": "INTEGER",
                "integer_values": {"min": "0", "max": "100", "step": "1"},
            },
        }
        return res

    def to_sber_current_state(self) -> dict[str, dict]:
        """Build Sber current state payload with position, open state, and signal.

        Per Sber C2C specification, ``integer_value`` is serialized as a string.

        Returns:
            Dict mapping entity_id to its Sber state representation.
        """
        if not self._is_online:
            states = [
                {"key": "online", "value": {"type": "BOOL", "bool_value": False}},
            ]
            return {self.entity_id: {"states": states}}

        states = [
            {"key": "online", "value": {"type": "BOOL", "bool_value": True}},
        ]

        # # Добавление позиции
        states.append(
            {
                "key": "open_percentage",
                "value": {"type": "INTEGER", "integer_value": str(self._convert_position(self.current_position))},
            }
        )

        state_map = {"open": "open", "opening": "open", "closed": "close", "closing": "close"}
        open_state = state_map.get(self.state, "close" if self.current_position == 0 else "open")
        states.append(
            {
                "key": "open_state",
                "value": {"type": "ENUM", "enum_value": open_state},
            }
        )

        if self._signal_strength_raw is not None:
            states.append(
                {
                    "key": "signal_strength",
                    "value": {"type": "ENUM", "enum_value": self._rssi_to_signal_strength(self._signal_strength_raw)},
                }
            )

        return {self.entity_id: {"states": states}}
