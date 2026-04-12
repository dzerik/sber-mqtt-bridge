"""HA Repairs integration for Sber Smart Home MQTT Bridge.

Uses ``homeassistant.helpers.issue_registry`` to surface problems such as
missing entities, entities without state, and persistent connection failures.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant
from homeassistant.helpers.issue_registry import (
    IssueSeverity,
    async_create_issue,
    async_delete_issue,
)

if TYPE_CHECKING:
    from .sber_bridge import SberBridge

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def check_and_create_issues(hass: HomeAssistant, bridge: SberBridge) -> None:
    """Inspect the bridge state and create/delete HA repair issues.

    Called after entity loading and on reconnect to keep the issue registry
    up to date with the current bridge health.

    Args:
        hass: Home Assistant core instance.
        bridge: The active SberBridge instance.
    """
    _check_entity_not_found(hass, bridge)
    _check_entities_without_state(hass, bridge)
    _check_connection_issues(hass, bridge)
    _check_broken_links(hass, bridge)
    _check_unacknowledged_entities(hass, bridge)
    _check_sber_errors(hass, bridge)


def _check_entity_not_found(hass: HomeAssistant, bridge: SberBridge) -> None:
    """Create/delete issues for entities in exposed list but not found in registry.

    Args:
        hass: Home Assistant core instance.
        bridge: The active SberBridge instance.
    """
    for eid in bridge.enabled_entity_ids:
        entity = bridge.entities.get(eid)
        if entity is None:
            async_create_issue(
                hass,
                DOMAIN,
                f"entity_not_found_{eid}",
                is_fixable=False,
                severity=IssueSeverity.WARNING,
                translation_key="entity_not_found",
                translation_placeholders={"entity_id": eid},
            )
        else:
            async_delete_issue(hass, DOMAIN, f"entity_not_found_{eid}")


def _check_entities_without_state(hass: HomeAssistant, bridge: SberBridge) -> None:
    """Create/delete issue for entities that have no HA state yet.

    Args:
        hass: Home Assistant core instance.
        bridge: The active SberBridge instance.
    """
    unfilled = [eid for eid, e in bridge.entities.items() if not e.is_filled_by_state]
    if unfilled:
        async_create_issue(
            hass,
            DOMAIN,
            "entities_without_state",
            is_fixable=False,
            severity=IssueSeverity.WARNING,
            translation_key="entities_without_state",
            translation_placeholders={
                "count": str(len(unfilled)),
                "entities": ", ".join(unfilled[:5]),
            },
        )
    else:
        async_delete_issue(hass, DOMAIN, "entities_without_state")


def _check_connection_issues(hass: HomeAssistant, bridge: SberBridge) -> None:
    """Create/delete issue for persistent MQTT connection problems.

    Args:
        hass: Home Assistant core instance.
        bridge: The active SberBridge instance.
    """
    stats = bridge.stats
    if not bridge.is_connected and stats.get("reconnect_count", 0) > 5:
        async_create_issue(
            hass,
            DOMAIN,
            "connection_issues",
            is_fixable=False,
            severity=IssueSeverity.ERROR,
            translation_key="connection_issues",
            translation_placeholders={
                "reconnect_count": str(stats.get("reconnect_count", 0)),
            },
        )
    else:
        async_delete_issue(hass, DOMAIN, "connection_issues")


def _check_broken_links(hass: HomeAssistant, bridge: SberBridge) -> None:
    """Create/delete issue for broken entity links.

    Args:
        hass: Home Assistant core instance.
        bridge: The active SberBridge instance.
    """
    broken: list[str] = []
    for primary_id, roles in bridge.entity_links.items():
        for role, linked_id in roles.items():
            state = hass.states.get(linked_id)
            if state is None:
                broken.append(f"{linked_id} ({role} → {primary_id})")

    if broken:
        async_create_issue(
            hass,
            DOMAIN,
            "broken_entity_links",
            is_fixable=False,
            severity=IssueSeverity.WARNING,
            translation_key="broken_entity_links",
            translation_placeholders={
                "count": str(len(broken)),
                "links": ", ".join(broken[:5]),
            },
        )
    else:
        async_delete_issue(hass, DOMAIN, "broken_entity_links")


def _check_unacknowledged_entities(hass: HomeAssistant, bridge: SberBridge) -> None:
    """Create/delete issue for entities silently rejected by Sber cloud.

    Sber cloud accepts the config payload without errors but may not send
    ``status_request`` for certain devices — a silent rejection.  This check
    creates a visible HA repair issue so the user doesn't have to discover
    the problem manually in the panel.

    Only fires when the bridge is connected (otherwise unack is expected).

    Args:
        hass: Home Assistant core instance.
        bridge: The active SberBridge instance.
    """
    unack = bridge.unacknowledged_entities
    if unack and bridge.is_connected:
        async_create_issue(
            hass,
            DOMAIN,
            "unacknowledged_entities",
            is_fixable=False,
            severity=IssueSeverity.WARNING,
            translation_key="unacknowledged_entities",
            translation_placeholders={
                "count": str(len(unack)),
                "entities": ", ".join(unack[:10]),
            },
        )
    else:
        async_delete_issue(hass, DOMAIN, "unacknowledged_entities")


def _check_sber_errors(hass: HomeAssistant, bridge: SberBridge) -> None:
    """Create/delete issue when Sber cloud sends error messages.

    Args:
        hass: Home Assistant core instance.
        bridge: The active SberBridge instance.
    """
    stats = bridge.stats
    error_count = stats.get("errors_from_sber", 0)
    last_error = stats.get("last_error_detail", "")
    if error_count > 0 and last_error:
        async_create_issue(
            hass,
            DOMAIN,
            "sber_errors",
            is_fixable=False,
            severity=IssueSeverity.WARNING,
            translation_key="sber_errors",
            translation_placeholders={
                "count": str(error_count),
                "detail": last_error[:200],
            },
        )
    else:
        async_delete_issue(hass, DOMAIN, "sber_errors")
