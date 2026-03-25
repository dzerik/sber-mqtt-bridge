"""Sber Intercom entity -- minimal implementation for intercom devices.

Available only via type override (sber_category: intercom).
Supports on/off control and read-only call/unlock features from HA attributes.
"""

from __future__ import annotations

import logging

from ..sber_constants import SberFeature
from ..sber_models import make_bool_value, make_state
from .on_off_entity import OnOffEntity

_LOGGER = logging.getLogger(__name__)

INTERCOM_CATEGORY = "intercom"
"""Sber device category for intercom entities."""


class IntercomEntity(OnOffEntity):
    """Sber intercom entity for door intercom devices.

    Maps to the Sber 'intercom' category. Available only via type override
    since there is no standard HA intercom domain.

    Supports:
    - On/off control (inherited from OnOffEntity)
    - Read-only features from HA attributes: incoming_call, reject_call, unlock
    """

    def __init__(self, entity_data: dict) -> None:
        """Initialize intercom entity.

        Args:
            entity_data: HA entity registry dict containing entity metadata.
        """
        super().__init__(INTERCOM_CATEGORY, entity_data)
        self._incoming_call: bool = False
        self._reject_call: bool = False
        self._unlock: bool = False

    def fill_by_ha_state(self, ha_state: dict) -> None:
        """Parse HA state and update intercom attributes.

        Args:
            ha_state: HA state dict with 'state' and 'attributes' keys.
        """
        super().fill_by_ha_state(ha_state)
        attrs = ha_state.get("attributes", {})
        self._incoming_call = bool(attrs.get("incoming_call", False))
        self._reject_call = bool(attrs.get("reject_call", False))
        self._unlock = bool(attrs.get("unlock", False))

    def create_features_list(self) -> list[str]:
        """Return Sber feature list for intercom capabilities.

        Returns:
            List of Sber feature strings supported by this entity.
        """
        return [
            *super().create_features_list(),
            "incoming_call",
            "reject_call",
            "unlock",
        ]

    def to_sber_current_state(self) -> dict[str, dict]:
        """Build Sber current state payload with intercom attributes.

        Returns:
            Dict mapping entity_id to its Sber state representation.
        """
        base = super().to_sber_current_state()
        states = base[self.entity_id]["states"]
        states.extend(
            [
                make_state(SberFeature.INCOMING_CALL, make_bool_value(self._incoming_call)),
                make_state(SberFeature.REJECT_CALL, make_bool_value(self._reject_call)),
                make_state(SberFeature.UNLOCK, make_bool_value(self._unlock)),
            ]
        )
        return base

    def process_cmd(self, cmd_data: dict) -> list[dict]:
        """Process Sber intercom commands and produce HA service calls.

        Handles ``on_off`` key for turn_on/turn_off. Other features
        (incoming_call, reject_call, unlock) are read-only.

        Args:
            cmd_data: Sber command dict with 'states' list.

        Returns:
            List of HA service call dicts to execute.
        """
        results: list[dict] = []
        domain = self.get_entity_domain()
        for item in cmd_data.get("states", []):
            key = item.get("key")
            value = item.get("value", {})
            if key == "on_off" and value.get("type") == "BOOL":
                on = value.get("bool_value", False)
                results.append(self._build_on_off_service_call(self.entity_id, domain, on))
        return results
