"""Sber Relay entity -- maps switches, actions, and selected boolean helpers."""

from __future__ import annotations

import logging
from collections.abc import Callable

from homeassistant.const import STATE_UNAVAILABLE

from ..sber_constants import (
    SERVICE_PRESS,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    SberFeature,
    SberValueType,
)
from .base_entity import ENERGY_LINK_ROLES, CommandResult
from .on_off_entity import OnOffEntity

_LOGGER = logging.getLogger(__name__)

RELAY_CATEGORY = "relay"
"""Sber device category for relay/switch entities."""


class RelayEntity(OnOffEntity):
    """Sber relay entity for on/off control devices.

    Maps HA switch, script, button, and explicitly selected helpers/actions
    to the Sber 'relay' category. input_button and scene are momentary:
    on activates them, off is inert, and their ready state is off.
    Supports basic on/off toggling via the ``on_off`` Sber feature.

    Accepts the three metering links (:data:`~.base_entity.ENERGY_LINK_ROLES`)
    because both categories served by this class — ``relay`` and, via
    :class:`~.socket_entity.SocketEntity`, ``socket`` — document
    ``power`` / ``voltage`` / ``current``.  Declared here rather than on
    :class:`~.on_off_entity.OnOffEntity` so that ``intercom``, whose Sber
    table has no metering functions, cannot be offered those links in the
    wizard.
    """

    LINKABLE_ROLES = ENERGY_LINK_ROLES
    """Metering sensors of a smart plug (power / voltage / current)."""

    def __init__(self, entity_data: dict, category: str = RELAY_CATEGORY) -> None:
        """Initialize relay entity.

        Args:
            entity_data: HA entity registry dict containing entity metadata.
            category: Sber device category (override in subclasses).
        """
        super().__init__(category, entity_data)

    @property
    def _cmd_handlers(self) -> dict[str, Callable[[dict], list[CommandResult]]]:
        """Return dispatch map for relay commands."""
        return {SberFeature.ON_OFF: self._cmd_on_off}

    @property
    def _is_momentary(self) -> bool:
        """Return whether this relay represents a one-shot HA action."""
        return self.category == RELAY_CATEGORY and self.get_entity_domain() in ("input_button", "scene")

    @property
    def _is_online(self) -> bool:
        """Treat never-activated actions as ready, while absent ones are offline."""
        if self._is_momentary:
            return self.state not in (STATE_UNAVAILABLE, None)
        return super()._is_online

    def _cmd_on_off(self, value: dict) -> list[CommandResult]:
        """Handle power control or one-shot activation for selected actions.

        Args:
            value: Sber value dict from the command payload.

        Returns:
            HA service calls; off is inert for momentary action domains.
        """
        if value.get("type") != SberValueType.BOOL:
            return []
        on = value.get("bool_value", False)
        domain = self.get_entity_domain()
        if self._is_momentary:
            if not on:
                return []
            service = SERVICE_PRESS if domain == "input_button" else SERVICE_TURN_ON
        else:
            service = SERVICE_PRESS if domain == "button" else SERVICE_TURN_ON if on else SERVICE_TURN_OFF
        return [self._build_service_call(domain, service, self.entity_id)]

    def sanitize_echo_states(self, states: list[dict], commanded: set[str]) -> list[dict]:
        """Ground helpers and one-shot responses in their actual representation.

        Boolean helpers reflect HA state. Momentary actions report off as
        readiness for another activation, even when an on request fails.
        Physical relays retain their existing optimistic echo.

        Args:
            states: Proposed echo with command values over the baseline.
            commanded: Feature keys supplied by the command.

        Returns:
            Publishable echo states without a latched-on action.
        """
        if self._is_momentary or (self.category == RELAY_CATEGORY and self.get_entity_domain() == "input_boolean"):
            states = self.to_sber_current_state()[self.entity_id]["states"]
            commanded = set()
        return super().sanitize_echo_states(states, commanded)
