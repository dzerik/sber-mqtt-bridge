"""Sber Humidifier entity -- maps HA humidifier entities to Sber hvac_humidifier."""

from __future__ import annotations

import logging

from .base_entity import BaseEntity

_LOGGER = logging.getLogger(__name__)

HUMIDIFIER_CATEGORY = "hvac_humidifier"
"""Sber device category for humidifier entities."""


class HumidifierEntity(BaseEntity):
    """Sber humidifier entity for humidity control devices.

    Maps HA humidifier entities to the Sber 'hvac_humidifier' category
    with support for:
    - On/off control
    - Target humidity setting
    - Work mode selection (when supported by the device)
    """

    def __init__(self, entity_data: dict) -> None:
        """Initialize humidifier entity.

        Args:
            entity_data: HA entity registry dict containing entity metadata.
        """
        super().__init__(HUMIDIFIER_CATEGORY, entity_data)
        self.current_state = False
        self.target_humidity = None
        self.current_humidity = None
        self.available_modes: list[str] = []
        self.mode: str | None = None

    def fill_by_ha_state(self, ha_state: dict) -> None:
        """Parse HA state and update all humidifier attributes.

        Args:
            ha_state: HA state dict with 'state' and 'attributes' keys.
                Attributes may include humidity, current_humidity,
                available_modes, and mode.
        """
        super().fill_by_ha_state(ha_state)
        self.current_state = ha_state.get("state") == "on"
        attrs = ha_state.get("attributes", {})
        self.target_humidity = attrs.get("humidity")
        self.current_humidity = attrs.get("current_humidity")
        self.available_modes = attrs.get("available_modes", [])
        self.mode = attrs.get("mode")

    def create_features_list(self) -> list[str]:
        """Return Sber feature list based on available humidifier capabilities.

        Dynamically includes work mode and night mode features only when
        the HA entity supports them.

        Returns:
            List of Sber feature strings supported by this entity.
        """
        features = [*super().create_features_list(), "on_off", "humidity"]
        if self.available_modes:
            features.append("hvac_work_mode")
        if self._has_night_mode:
            features.append("hvac_night_mode")
        return features

    @property
    def _has_night_mode(self) -> bool:
        """Check if the entity supports night/sleep mode.

        Returns:
            True if available_modes contains 'sleep' or 'night'.
        """
        return any(m in self.available_modes for m in ("sleep", "night"))

    def create_allowed_values_list(self) -> dict[str, dict]:
        """Build allowed values map for enum-based features.

        Returns:
            Dict mapping feature key to its allowed ENUM values descriptor.
        """
        allowed = {}
        if self.available_modes:
            allowed["hvac_work_mode"] = {"type": "ENUM", "enum_values": {"values": self.available_modes}}
        return allowed

    def to_sber_state(self) -> dict:
        """Build full Sber device descriptor including allowed values.

        Overrides base to inject allowed_values into the model.
        Features are already populated by ``super().to_sber_state()``.

        Returns:
            Sber device descriptor dict with model, features, and allowed_values.
        """
        res = super().to_sber_state()
        res["model"]["allowed_values"] = self.create_allowed_values_list()
        return res

    def to_sber_current_state(self) -> dict[str, dict]:
        """Build Sber current state payload with humidifier attributes.

        Includes online, on_off, target humidity, work mode, and night mode
        when values are available.

        Per Sber C2C specification, ``integer_value`` is serialized as a string.

        Returns:
            Dict mapping entity_id to its Sber state representation.
        """
        states = [
            {"key": "online", "value": {"type": "BOOL", "bool_value": self._is_online}},
            {"key": "on_off", "value": {"type": "BOOL", "bool_value": self.current_state}},
        ]
        if self.target_humidity is not None:
            states.append(
                {"key": "humidity", "value": {"type": "INTEGER", "integer_value": str(round(self.target_humidity))}}
            )
        if self.mode:
            states.append({"key": "hvac_work_mode", "value": {"type": "ENUM", "enum_value": self.mode}})
        if self._has_night_mode:
            is_night = self.mode in ("sleep", "night")
            states.append({"key": "hvac_night_mode", "value": {"type": "BOOL", "bool_value": is_night}})
        return {self.entity_id: {"states": states}}

    def process_cmd(self, cmd_data: dict) -> list[dict]:
        """Process Sber humidifier commands and produce HA service calls.

        Handles the following Sber keys:
        - ``on_off``: turn_on / turn_off
        - ``humidity``: set_humidity (INTEGER 0-100, plain percentage)
        - ``hvac_work_mode``: set_mode (ENUM)
        - ``hvac_night_mode``: set_mode to sleep/normal (BOOL)

        State is NOT mutated here -- it will be updated when HA fires a
        ``state_changed`` event that is handled by ``fill_by_ha_state``.

        Args:
            cmd_data: Sber command dict with 'states' list.

        Returns:
            List of HA service call dicts to execute.
        """
        results = []
        for item in cmd_data.get("states", []):
            key = item.get("key")
            value = item.get("value", {})

            if key == "on_off":
                on = value.get("bool_value", False)
                results.append(self._build_on_off_service_call(self.entity_id, "humidifier", on))
            elif key == "humidity":
                raw_humidity = value.get("integer_value")
                if raw_humidity is None:
                    continue
                # Sber sends humidity as plain integer 0-100 (no scaling)
                results.append(
                    {
                        "url": {
                            "type": "call_service",
                            "domain": "humidifier",
                            "service": "set_humidity",
                            "service_data": {"humidity": int(raw_humidity)},
                            "target": {"entity_id": self.entity_id},
                        }
                    }
                )
            elif key == "hvac_work_mode":
                mode = value.get("enum_value")
                if mode is None:
                    continue
                results.append(
                    {
                        "url": {
                            "type": "call_service",
                            "domain": "humidifier",
                            "service": "set_mode",
                            "service_data": {"mode": mode},
                            "target": {"entity_id": self.entity_id},
                        }
                    }
                )
            elif key == "hvac_night_mode":
                night_on = value.get("bool_value", False)
                if night_on:
                    # Find the night/sleep mode
                    mode = "sleep" if "sleep" in self.available_modes else "night"
                    results.append(
                        {
                            "url": {
                                "type": "call_service",
                                "domain": "humidifier",
                                "service": "set_mode",
                                "service_data": {"mode": mode},
                                "target": {"entity_id": self.entity_id},
                            }
                        }
                    )
                else:
                    # Find the first non-night mode to revert to
                    normal_modes = [m for m in self.available_modes if m not in ("sleep", "night")]
                    if normal_modes:
                        results.append(
                            {
                                "url": {
                                    "type": "call_service",
                                    "domain": "humidifier",
                                    "service": "set_mode",
                                    "service_data": {"mode": normal_modes[0]},
                                    "target": {"entity_id": self.entity_id},
                                }
                            }
                        )
        return results
