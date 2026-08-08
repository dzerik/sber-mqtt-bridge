"""Behaviour tests for HA repair issues raised by the bridge.

What matters to the user is what ends up in the HA *issue registry*: a
repair tile appears while a problem exists and disappears once it is
resolved.  These tests therefore run ``check_and_create_issues`` against
a real registry and inspect the resulting issues, instead of asserting
that a helper function was called.

Moved here from the former ``test_p4_tasks.py`` grab-bag so repair
behaviour lives in a file named after it.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from homeassistant.helpers import issue_registry as ir

from custom_components.sber_mqtt_bridge.const import DOMAIN
from custom_components.sber_mqtt_bridge.devices.base_entity import BaseEntity
from custom_components.sber_mqtt_bridge.repairs import check_and_create_issues
from custom_components.sber_mqtt_bridge.sber_bridge import SberBridge


class _ConcreteEntity(BaseEntity):
    """Minimal concrete entity: BaseEntity is abstract."""

    def _build_current_state(self) -> dict:
        """Return an empty Sber state payload (not exercised here)."""
        return {self.entity_id: {"states": []}}

    def process_cmd(self, cmd_data: dict) -> list[dict]:
        """Ignore commands (not exercised here)."""
        return []


def _make_entity(entity_id: str = "light.test", *, filled: bool = True) -> _ConcreteEntity:
    """Create a concrete test entity, optionally without an HA state yet."""
    entity = _ConcreteEntity("light", {"entity_id": entity_id, "name": "Test"})
    if filled:
        entity.fill_by_ha_state({"state": "on", "attributes": {}})
    return entity


def _make_bridge(
    *,
    enabled: list[str] | None = None,
    entities: dict[str, _ConcreteEntity] | None = None,
    is_connected: bool = True,
    reconnect_count: int = 0,
) -> MagicMock:
    """Build a bridge stand-in with every attribute ``repairs`` reads.

    All fields are set explicitly so a test's issue-set assertions are not
    polluted by auto-generated MagicMock attributes.
    """
    bridge = MagicMock(spec=SberBridge)
    bridge.enabled_entity_ids = enabled or []
    bridge.entities = entities or {}
    bridge.is_connected = is_connected
    bridge.stats = {
        "reconnect_count": reconnect_count,
        "errors_from_sber": 0,
        "last_error_detail": "",
        "validation_failures": [],
    }
    bridge.entity_links = {}
    bridge.unacknowledged_entities = []
    bridge.config_entry = MagicMock()
    bridge.config_entry.options = {}
    return bridge


def _issue_ids(registry: ir.IssueRegistry) -> set[str]:
    """Return the ids of all issues this integration currently owns."""
    return {issue_id for (domain, issue_id) in registry.issues if domain == DOMAIN}


class TestEntityNotFoundIssue:
    """An exposed entity that no longer exists must be surfaced to the user."""

    async def test_issue_created_for_missing_entity_only(self, hass, issue_registry):
        bridge = _make_bridge(
            enabled=["light.missing", "light.found"],
            entities={"light.found": _make_entity("light.found")},
        )

        await check_and_create_issues(hass, bridge)

        assert _issue_ids(issue_registry) == {"entity_not_found_light.missing"}
        issue = issue_registry.async_get_issue(DOMAIN, "entity_not_found_light.missing")
        assert issue.translation_key == "entity_not_found"
        assert issue.translation_placeholders == {"entity_id": "light.missing"}

    async def test_issue_removed_once_entity_is_back(self, hass, issue_registry):
        # Arrange: the entity was missing on a previous run.
        bridge = _make_bridge(enabled=["light.a"])
        await check_and_create_issues(hass, bridge)
        assert issue_registry.async_get_issue(DOMAIN, "entity_not_found_light.a") is not None

        # Act: it is loaded now.
        bridge.entities = {"light.a": _make_entity("light.a")}
        await check_and_create_issues(hass, bridge)

        assert issue_registry.async_get_issue(DOMAIN, "entity_not_found_light.a") is None


class TestEntitiesWithoutStateIssue:
    """Entities exposed to Sber but never filled by HA state."""

    async def test_issue_lists_unfilled_entities(self, hass, issue_registry):
        bridge = _make_bridge(
            enabled=["light.no_state", "light.ok"],
            entities={
                "light.no_state": _make_entity("light.no_state", filled=False),
                "light.ok": _make_entity("light.ok"),
            },
        )

        await check_and_create_issues(hass, bridge)

        issue = issue_registry.async_get_issue(DOMAIN, "entities_without_state")
        assert issue is not None
        assert issue.translation_placeholders == {"count": "1", "entities": "light.no_state"}

    async def test_issue_removed_when_all_entities_filled(self, hass, issue_registry):
        bridge = _make_bridge(
            enabled=["light.ok"],
            entities={"light.ok": _make_entity("light.ok", filled=False)},
        )
        await check_and_create_issues(hass, bridge)
        assert issue_registry.async_get_issue(DOMAIN, "entities_without_state") is not None

        bridge.entities = {"light.ok": _make_entity("light.ok")}
        await check_and_create_issues(hass, bridge)

        assert issue_registry.async_get_issue(DOMAIN, "entities_without_state") is None


class TestConnectionIssue:
    """Repeated reconnects while offline point at bad credentials/network."""

    async def test_issue_created_when_disconnected_after_many_retries(self, hass, issue_registry):
        bridge = _make_bridge(is_connected=False, reconnect_count=10)

        await check_and_create_issues(hass, bridge)

        issue = issue_registry.async_get_issue(DOMAIN, "connection_issues")
        assert issue is not None
        assert issue.severity == ir.IssueSeverity.ERROR
        assert issue.translation_placeholders == {"reconnect_count": "10"}

    async def test_no_issue_at_or_below_retry_threshold(self, hass, issue_registry):
        # 5 retries is still within the tolerated window; only >5 is a problem.
        bridge = _make_bridge(is_connected=False, reconnect_count=5)

        await check_and_create_issues(hass, bridge)

        assert issue_registry.async_get_issue(DOMAIN, "connection_issues") is None

    async def test_issue_removed_once_connected(self, hass, issue_registry):
        bridge = _make_bridge(is_connected=False, reconnect_count=10)
        await check_and_create_issues(hass, bridge)
        assert issue_registry.async_get_issue(DOMAIN, "connection_issues") is not None

        bridge.is_connected = True
        await check_and_create_issues(hass, bridge)

        assert issue_registry.async_get_issue(DOMAIN, "connection_issues") is None
