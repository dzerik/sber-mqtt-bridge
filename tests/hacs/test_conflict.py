"""Detection of other integrations that export HA devices to Sber too.

Issue #63 was debugged for days before it turned out a second bridge
(TohaRG2's ``sber_mqtt``) was installed next to this one.  On the same
Sber account the two are not merely redundant: each publishes its own
``up/config`` to the same topic and replaces the device list the other
one declared, so devices come and go in the Sber app.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sber_mqtt_bridge.conflict import (
    ISSUE_ID,
    async_track_conflicts,
    detect_conflicts,
)
from custom_components.sber_mqtt_bridge.const import CONF_SBER_LOGIN, DOMAIN


def _our_entry(hass: HomeAssistant, login: str = "acc-1") -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_SBER_LOGIN: login}, title="Sber Bridge")
    entry.add_to_hass(hass)
    return entry


def _other_bridge(hass: HomeAssistant, login: str) -> MockConfigEntry:
    entry = MockConfigEntry(domain="sber_mqtt", data={"mqtt_login": login}, title="Sber MQTT")
    entry.add_to_hass(hass)
    return entry


async def test_no_conflict_without_other_bridges(hass: HomeAssistant) -> None:
    assert detect_conflicts(hass, "acc-1") == []


async def test_same_account_is_flagged(hass: HomeAssistant) -> None:
    _other_bridge(hass, "acc-1")
    [conflict] = detect_conflicts(hass, "acc-1")
    assert conflict.domain == "sber_mqtt"
    assert conflict.same_account is True


async def test_other_account_is_flagged_as_such(hass: HomeAssistant) -> None:
    _other_bridge(hass, "acc-2")
    [conflict] = detect_conflicts(hass, "acc-1")
    assert conflict.same_account is False


async def test_issue_follows_entries_being_added_and_removed(hass: HomeAssistant) -> None:
    entry = _our_entry(hass)
    registry = ir.async_get(hass)
    unsub = async_track_conflicts(hass, entry)
    assert registry.async_get_issue(DOMAIN, ISSUE_ID) is None

    other = _other_bridge(hass, "acc-1")
    await hass.config_entries.async_remove(other.entry_id)
    # Removal alone must clear it; add again to check creation via the signal.
    assert registry.async_get_issue(DOMAIN, ISSUE_ID) is None

    other = MockConfigEntry(domain="sber_mqtt", data={"mqtt_login": "acc-1"}, title="Sber MQTT")
    other.add_to_hass(hass)
    hass.config_entries.async_update_entry(other, title="Sber MQTT renamed")
    await hass.async_block_till_done()
    issue = registry.async_get_issue(DOMAIN, ISSUE_ID)
    assert issue is not None
    assert issue.severity == ir.IssueSeverity.ERROR
    assert issue.translation_key == "conflicting_integration_same_account"

    unsub()
    assert registry.async_get_issue(DOMAIN, ISSUE_ID) is None, "unload must not leave a stale issue"


async def test_other_account_issue_is_a_warning(hass: HomeAssistant) -> None:
    entry = _our_entry(hass)
    _other_bridge(hass, "acc-2")
    unsub = async_track_conflicts(hass, entry)

    issue = ir.async_get(hass).async_get_issue(DOMAIN, ISSUE_ID)
    assert issue.severity == ir.IssueSeverity.WARNING
    assert issue.translation_key == "conflicting_integration"
    assert issue.translation_placeholders == {"integrations": "Sber MQTT (sber_mqtt)"}
    unsub()


async def test_translations_exist_for_both_issues() -> None:
    import json
    from pathlib import Path

    base = Path(__file__).resolve().parents[2] / "custom_components" / "sber_mqtt_bridge"
    for name in ("strings.json", "translations/en.json", "translations/ru.json"):
        issues = json.loads((base / name).read_text(encoding="utf-8"))["issues"]
        for key in ("conflicting_integration", "conflicting_integration_same_account"):
            assert "{integrations}" in issues[key]["description"], (name, key)
