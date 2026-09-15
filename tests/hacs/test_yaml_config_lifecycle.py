"""The YAML section and the repair issues across the config entry's lifecycle.

Both are owned by the *component*, not by one config entry: HA parses
``configuration.yaml`` once per start, and the repair tiles outlive the
bridge that raised them unless somebody deletes them.  These tests set the
integration up through Home Assistant for real (``async_setup_component``,
real config entries, real issue registry) and only neutralise the MQTT
reconnect loop.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

import pytest
from homeassistant.config_entries import ConfigEntryDisabler, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sber_mqtt_bridge import ACTIVE_ENTRY_KEY
from custom_components.sber_mqtt_bridge.const import (
    CONF_EXPOSED_ENTITIES,
    CONF_SBER_BROKER,
    CONF_SBER_LOGIN,
    CONF_SBER_PASSWORD,
    CONF_SBER_PORT,
    CONF_SBER_VERIFY_SSL,
    DOMAIN,
)
from custom_components.sber_mqtt_bridge.sber_bridge import SberBridge

PUMP = "switch.pump"
GHOST = "switch.ghost"
"""Exposed but absent from the entity registry — raises ``entity_not_found``."""

YAML_NAME = "Насос из YAML"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: Any) -> None:
    """Let HA load ``custom_components/sber_mqtt_bridge`` in every test."""
    return


@pytest.fixture(autouse=True)
def _no_mqtt_reconnect_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    """Neutralise the endless MQTT reconnect task."""

    async def _noop(self: SberBridge) -> None:
        return

    monkeypatch.setattr(SberBridge, "_mqtt_connection_loop", _noop)


@pytest.fixture
async def ha(hass: HomeAssistant) -> AsyncGenerator[HomeAssistant]:
    """Frontend plus one switch known to the entity registry."""
    assert await async_setup_component(hass, "frontend", {})
    er.async_get(hass).async_get_or_create("switch", "test_devices", "pump-uid", suggested_object_id="pump")
    hass.states.async_set(PUMP, "off", {"friendly_name": "Pump"})
    yield hass
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is ConfigEntryState.LOADED:
            await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


def _add_entry(hass: HomeAssistant, exposed: list[str]) -> MockConfigEntry:
    """Register (without setting up) a config entry exposing ``exposed``."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_SBER_LOGIN: "test",
            CONF_SBER_PASSWORD: "pass",
            CONF_SBER_BROKER: "broker.test",
            CONF_SBER_PORT: 8883,
            CONF_SBER_VERIFY_SSL: False,
        },
        options={CONF_EXPOSED_ENTITIES: exposed},
        version=3,
    )
    entry.add_to_hass(hass)
    return entry


async def _setup_with_yaml(hass: HomeAssistant, section: Any, exposed: list[str]) -> MockConfigEntry:
    """Add an entry, then set the component up with ``section`` as its YAML."""
    entry = _add_entry(hass, exposed)
    assert await async_setup_component(hass, DOMAIN, {DOMAIN: section})
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    return entry


def _own_issues(hass: HomeAssistant) -> set[str]:
    """Return the ids of the issues registered under this integration."""
    return {issue_id for domain, issue_id in ir.async_get(hass).issues if domain == DOMAIN}


class TestYamlSurvivesEntryLifecycle:
    """YAML overrides are parsed once per HA start and must outlive any entry."""

    async def test_readded_entry_keeps_yaml_overrides(self, ha: HomeAssistant) -> None:
        hass = ha
        section = {"entity_config": {PUMP: {"sber_name": YAML_NAME}}}
        first = await _setup_with_yaml(hass, section, [PUMP])
        assert first.runtime_data.bridge.entities[PUMP].name == YAML_NAME

        await hass.config_entries.async_remove(first.entry_id)
        await hass.async_block_till_done()
        second = _add_entry(hass, [PUMP])
        assert await hass.config_entries.async_setup(second.entry_id)
        await hass.async_block_till_done()

        assert second.state is ConfigEntryState.LOADED
        assert second.runtime_data.bridge.entities[PUMP].name == YAML_NAME


class TestYamlSchema:
    """What the ``sber_mqtt_bridge:`` section accepts."""

    async def test_unknown_top_level_key_is_ignored_with_a_warning(
        self, ha: HomeAssistant, caplog: pytest.LogCaptureFixture
    ) -> None:
        section = {"entity_config": {PUMP: {"sber_name": YAML_NAME}}, "entity_configs": {}}

        entry = await _setup_with_yaml(ha, section, [PUMP])

        assert entry.runtime_data.bridge.entities[PUMP].name == YAML_NAME
        warnings = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
        assert any("entity_configs" in message and "entity_config" in message for message in warnings)

    async def test_empty_section_is_accepted(self, ha: HomeAssistant) -> None:
        entry = await _setup_with_yaml(ha, None, [PUMP])

        assert entry.runtime_data.bridge.entities[PUMP].name != YAML_NAME

    async def test_unknown_entity_key_fails_validation_clearly(
        self, ha: HomeAssistant, caplog: pytest.LogCaptureFixture
    ) -> None:
        _add_entry(ha, [PUMP])

        assert not await async_setup_component(ha, DOMAIN, {DOMAIN: {"entity_config": {PUMP: {"sber_nmae": "x"}}}})

        errors = [r.getMessage() for r in caplog.records if r.levelname == "ERROR"]
        assert any("Invalid config for 'sber_mqtt_bridge'" in message and "sber_nmae" in message for message in errors)

    async def test_section_of_wrong_type_fails_validation(self, ha: HomeAssistant) -> None:
        assert not await async_setup_component(ha, DOMAIN, {DOMAIN: ["entity_config"]})


class TestIssuesAreCleanedUp:
    """Repair tiles describe the running bridge and must not outlive it."""

    @staticmethod
    async def _entry_with_issues(hass: HomeAssistant) -> MockConfigEntry:
        entry = await _setup_with_yaml(hass, {}, [PUMP, GHOST])
        ir.async_create_issue(
            hass,
            DOMAIN,
            "sber_errors",
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="sber_errors",
        )
        ir.async_create_issue(
            hass,
            "other_domain",
            "sber_errors",
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="sber_errors",
        )
        assert f"entity_not_found_{GHOST}" in _own_issues(hass)
        return entry

    async def test_removing_the_entry_deletes_its_issues(self, ha: HomeAssistant) -> None:
        entry = await self._entry_with_issues(ha)

        await ha.config_entries.async_remove(entry.entry_id)
        await ha.async_block_till_done()

        assert _own_issues(ha) == set()
        assert ir.async_get(ha).async_get_issue("other_domain", "sber_errors") is not None

    async def test_disabling_the_entry_deletes_its_issues(self, ha: HomeAssistant) -> None:
        entry = await self._entry_with_issues(ha)

        await ha.config_entries.async_set_disabled_by(entry.entry_id, ConfigEntryDisabler.USER)
        await ha.async_block_till_done()

        assert entry.state is ConfigEntryState.NOT_LOADED
        assert _own_issues(ha) == set()
        assert ir.async_get(ha).async_get_issue("other_domain", "sber_errors") is not None

    async def test_reload_keeps_the_users_ignore_choice(self, ha: HomeAssistant) -> None:
        # Options saved, reauth and "Reload" all unload the entry first; a
        # deleted issue would come back as new, un-ignored.
        entry = await self._entry_with_issues(ha)
        issue_id = f"entity_not_found_{GHOST}"
        ir.async_get(ha).async_ignore(DOMAIN, issue_id, True)

        assert await ha.config_entries.async_reload(entry.entry_id)
        await ha.async_block_till_done()

        issue = ir.async_get(ha).async_get_issue(DOMAIN, issue_id)
        assert issue is not None
        assert issue.dismissed_version is not None

    async def test_reloaded_bridge_raises_what_still_applies(self, ha: HomeAssistant) -> None:
        entry = await self._entry_with_issues(ha)

        assert await ha.config_entries.async_reload(entry.entry_id)
        await ha.async_block_till_done()

        assert _own_issues(ha) == {f"entity_not_found_{GHOST}"}

    async def test_removing_a_never_loaded_entry_deletes_leftover_issues(self, ha: HomeAssistant) -> None:
        entry = _add_entry(ha, [PUMP])
        ir.async_create_issue(
            ha,
            DOMAIN,
            f"entity_not_found_{GHOST}",
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="sber_errors",
        )

        await ha.config_entries.async_remove(entry.entry_id)
        await ha.async_block_till_done()

        assert _own_issues(ha) == set()


class TestSingleEntryClaimOnRemoval:
    """Keeping ``hass.data[DOMAIN]`` must not keep a dead entry's claim on the bridge."""

    async def test_claim_of_a_removed_entry_does_not_block_the_next_one(self, ha: HomeAssistant) -> None:
        # A removed entry whose unload never released the claim (e.g. the
        # unload failed): it is not loaded, so HA does not unload it again.
        assert await async_setup_component(ha, DOMAIN, {})
        stale = _add_entry(ha, [PUMP])
        ha.data[DOMAIN][ACTIVE_ENTRY_KEY] = stale.entry_id
        assert stale.state is ConfigEntryState.NOT_LOADED
        await ha.config_entries.async_remove(stale.entry_id)
        await ha.async_block_till_done()

        fresh = _add_entry(ha, [PUMP])
        await ha.config_entries.async_setup(fresh.entry_id)
        await ha.async_block_till_done()

        assert fresh.state is ConfigEntryState.LOADED
