"""HA Repairs integration for Sber Smart Home MQTT Bridge.

Uses ``homeassistant.helpers.issue_registry`` to surface problems such as
missing entities, entities without state, and persistent connection failures.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.issue_registry import (
    IssueSeverity,
    async_create_issue,
    async_delete_issue,
)
from homeassistant.helpers.issue_registry import async_get as async_get_issue_registry

if TYPE_CHECKING:
    from .sber_bridge import SberBridge

from .const import (
    CONF_EXPOSED_ENTITIES,
    CONF_SILENT_REJECTION_ALERTS,
    DOMAIN,
    SETTINGS_DEFAULTS,
)

_LOGGER = logging.getLogger(__name__)

ENTITY_NOT_FOUND_PREFIX = "entity_not_found_"
"""Prefix of the per-entity issue ids: ``entity_not_found_<entity_id>``."""


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
    _check_missing_required_links(hass, bridge)
    _check_unacknowledged_entities(hass, bridge)
    _check_validation_failures(hass, bridge)
    _check_sber_errors(hass, bridge)


def _check_entity_not_found(hass: HomeAssistant, bridge: SberBridge) -> None:
    """Create/delete issues for entities in exposed list but not found in registry.

    The exposed list is read from the config entry options, not from
    ``bridge.enabled_entity_ids``: the entity loader keeps only the entities
    it could build, so an id missing from the entity registry never reaches
    that list and the check against it could not fire.

    Every other ``entity_not_found`` issue is stale and deleted — the entity
    is back, or it is no longer exposed at all (the latter used to keep its
    tile forever, because only exposed entities were ever checked).

    Args:
        hass: Home Assistant core instance.
        bridge: The active SberBridge instance.
    """
    raw_exposed = bridge.config_entry.options.get(CONF_EXPOSED_ENTITIES, [])
    exposed = raw_exposed if isinstance(raw_exposed, list) else []
    registry = er.async_get(hass)
    missing: dict[str, str] = {
        f"{ENTITY_NOT_FOUND_PREFIX}{eid}": eid
        for eid in exposed
        if isinstance(eid, str) and registry.async_get(eid) is None
    }
    for issue_id, eid in missing.items():
        async_create_issue(
            hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            severity=IssueSeverity.WARNING,
            translation_key="entity_not_found",
            translation_placeholders={"entity_id": eid},
        )
    for issue_id in _own_issue_ids(hass):
        if issue_id.startswith(ENTITY_NOT_FOUND_PREFIX) and issue_id not in missing:
            async_delete_issue(hass, DOMAIN, issue_id)


def _own_issue_ids(hass: HomeAssistant) -> list[str]:
    """Return the ids of all issues currently registered for this integration.

    Args:
        hass: Home Assistant core instance.

    Returns:
        Issue ids owned by :data:`~.const.DOMAIN`, as a list (safe to delete
        from while iterating).
    """
    return [issue_id for domain, issue_id in async_get_issue_registry(hass).issues if domain == DOMAIN]


@callback
def async_delete_all_issues(hass: HomeAssistant) -> None:
    """Remove every repair issue registered under this integration's domain.

    Called when the bridge goes away for good — the config entry is removed
    or disabled, not merely reloaded (deleting an issue forgets that the
    user ignored it).
    Every issue the integration raises describes the running bridge — the
    per-entity ``entity_not_found_<entity_id>`` ones and the fixed ids of
    this module (``entities_without_state``, ``connection_issues``,
    ``broken_entity_links``, ``missing_required_links``,
    ``unacknowledged_entities``, ``validation_failures``, ``sber_errors``),
    plus ``conflicting_integration`` from :mod:`.conflict` — and none of
    them is re-checked, and so cleared, once the bridge is gone.  Deleting
    by domain rather than by that list keeps an issue added later from
    being forgotten here.  A bridge that starts again recreates whatever
    still applies on its next :func:`check_and_create_issues`.

    Args:
        hass: Home Assistant core instance.
    """
    for issue_id in _own_issue_ids(hass):
        async_delete_issue(hass, DOMAIN, issue_id)


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


def _check_missing_required_links(hass: HomeAssistant, bridge: SberBridge) -> None:
    """Create/delete issue for composite devices missing an obligatory link.

    An impulse gate without its reed contact publishes ``close`` forever
    and cannot be trusted by any automation.  The device wizard refuses
    to create one, but the "expose the entity, then set the category by
    hand" path (``set_override``) bypasses that check — and deliberately
    stays allowed, because assigning the category before linking the
    sensor is a legitimate order of operations.  The result must
    therefore be *visible* rather than forbidden; the issue clears itself
    on the next check once the link exists.

    Args:
        hass: Home Assistant core instance.
        bridge: The active SberBridge instance.
    """
    missing = bridge.entities_missing_required_links
    details = [f"{eid} ({', '.join(roles)})" for eid, roles in sorted(missing.items())]
    if details:
        async_create_issue(
            hass,
            DOMAIN,
            "missing_required_links",
            is_fixable=False,
            severity=IssueSeverity.WARNING,
            translation_key="missing_required_links",
            translation_placeholders={
                "count": str(len(details)),
                "entities": ", ".join(details[:5]),
            },
        )
    else:
        async_delete_issue(hass, DOMAIN, "missing_required_links")


def _check_unacknowledged_entities(hass: HomeAssistant, bridge: SberBridge) -> None:
    """Create/delete issue for entities silently rejected by Sber cloud.

    Sber cloud accepts the config payload without errors but may not send
    ``status_request`` for certain devices — a silent rejection.  When the
    user has opted into ``CONF_SILENT_REJECTION_ALERTS`` (off by default),
    a visible HA repair issue surfaces the problem.

    The default is off because the 60-second audit window does not match
    real Sber cadence: cloud may accept a device, dispatch commands, yet
    never trigger ``status_request`` until the user pulls to refresh the
    Sber app.  In those cases the warning is a false positive.  The
    underlying audit still runs (panel + WARN log) so the data is not
    lost — only the repair-tile noise is.

    Args:
        hass: Home Assistant core instance.
        bridge: The active SberBridge instance.
    """
    options = bridge.config_entry.options
    enabled = bool(options.get(CONF_SILENT_REJECTION_ALERTS, SETTINGS_DEFAULTS[CONF_SILENT_REJECTION_ALERTS]))
    # Deliberately NOT `unacknowledged_entities`: that mark is per-session
    # and holds everything for a while after every Home Assistant restart,
    # which turned this alert into a guaranteed false positive and is a
    # large part of why it ships disabled (issue #57).  An entity the
    # cloud has never once been seen to know is the real signal.
    unack = bridge.never_confirmed_entities
    if enabled and unack and bridge.is_connected:
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


def _check_validation_failures(hass: HomeAssistant, bridge: SberBridge) -> None:
    """Create/delete issue for devices that failed pydantic validation.

    These devices were excluded from the last config publish because
    their ``to_sber_state()`` output didn't pass strict schema validation.

    Args:
        hass: Home Assistant core instance.
        bridge: The active SberBridge instance.
    """
    stats = bridge.stats
    failures = stats.get("validation_failures", [])
    if failures:
        async_create_issue(
            hass,
            DOMAIN,
            "validation_failures",
            is_fixable=False,
            severity=IssueSeverity.ERROR,
            translation_key="validation_failures",
            translation_placeholders={
                "count": str(len(failures)),
                "entities": ", ".join(failures[:10]),
            },
        )
    else:
        async_delete_issue(hass, DOMAIN, "validation_failures")
