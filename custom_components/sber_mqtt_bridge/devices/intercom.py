"""Sber Intercom entity -- minimal implementation for intercom devices.

Available only via type override (sber_category: intercom).
Supports on/off control and read-only call/unlock features from HA attributes.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from ..sber_constants import SberFeature
from ..sber_models import make_bool_value, make_state
from .base_entity import CommandResult
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

    def fill_by_ha_state(self, ha_state: dict) -> None:
        """Parse HA state and update intercom attributes.

        Args:
            ha_state: HA state dict with 'state' and 'attributes' keys.
        """
        super().fill_by_ha_state(ha_state)
        attrs = ha_state.get("attributes", {})
        self._incoming_call = bool(attrs.get("incoming_call", False))

    def _create_features_list(self) -> list[str]:
        """Return Sber feature list for intercom capabilities.

        Returns:
            List of Sber feature strings supported by this entity.
        """
        return [
            *super()._create_features_list(),
            "incoming_call",
            "reject_call",
            "unlock",
        ]

    def to_sber_current_state(self) -> dict[str, dict]:
        """Build Sber current state payload with intercom attributes.

        Per the Sber spec, ``reject_call`` and ``unlock`` are command-only
        ENUM functions («не хранит состояние устройства») — they must NOT
        be published as states.  Publishing them as BOOL (pre-1.41.0
        behaviour) contradicted their declared ENUM type (issue #44 audit).

        Returns:
            Dict mapping entity_id to its Sber state representation.
        """
        base = super().to_sber_current_state()
        states = base[self.entity_id]["states"]
        states.append(make_state(SberFeature.INCOMING_CALL, make_bool_value(self._incoming_call)))
        return base

    @property
    def _cmd_handlers(self) -> dict[str, Callable[[dict], list[CommandResult]]]:
        """Return dispatch map from Sber feature key to handler method."""
        return {
            SberFeature.ON_OFF: self._cmd_on_off,
            SberFeature.UNLOCK: self._cmd_unlock,
            SberFeature.REJECT_CALL: self._cmd_reject_call,
        }

    def _cmd_unlock(self, value: dict) -> list[CommandResult]:
        """Handle the ``unlock`` ENUM command — open the intercom lock.

        Per Sber docs the command carries ``enum_value: "unlock"``.  For a
        HA ``lock`` entity this maps to ``lock.unlock``; for switch-like
        overrides it maps to ``turn_on``.

        Args:
            value: Sber value dict from the command payload.

        Returns:
            List with a single HA service call.
        """
        if value.get("type") != "ENUM":
            return []
        domain = self.get_entity_domain()
        if domain == "lock":
            return [self._build_service_call("lock", "unlock", self.entity_id)]
        return [self._build_on_off_service_call(self.entity_id, domain, True)]

    def _cmd_reject_call(self, value: dict) -> list[CommandResult]:
        """Handle the ``reject_call`` ENUM command.

        HA has no universal "reject intercom call" service — acknowledge
        the command with a state republish so Sber does not treat it as
        lost.

        Args:
            value: Sber value dict from the command payload.

        Returns:
            List with an update-state marker.
        """
        if value.get("type") != "ENUM":
            return []
        _LOGGER.debug("reject_call for %s: no HA service mapping, acknowledging", self.entity_id)
        return [{"update_state": True}]

    def _cmd_on_off(self, value: dict) -> list[CommandResult]:
        """Handle ``on_off`` for intercom (turn_on / turn_off).

        Args:
            value: Sber value dict from the command payload.

        Returns:
            List with a single HA service call, or empty list if type is wrong.
        """
        if value.get("type") != "BOOL":
            return []
        on = value.get("bool_value", False)
        domain = self.get_entity_domain()
        return [self._build_on_off_service_call(self.entity_id, domain, on)]
