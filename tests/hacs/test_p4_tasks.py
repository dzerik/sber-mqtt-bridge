"""Tests for P4 tasks: repairs, custom features, auto re-publish, persist redefinitions."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.sber_mqtt_bridge.const import (
    CONF_EXPOSED_ENTITIES,
    CONF_SBER_BROKER,
    CONF_SBER_LOGIN,
    CONF_SBER_PASSWORD,
    CONF_SBER_PORT,
    DOMAIN,
)
from custom_components.sber_mqtt_bridge.custom_capabilities import (
    EntityCustomConfig,
    parse_yaml_config,
)
from custom_components.sber_mqtt_bridge.devices.base_entity import BaseEntity
from custom_components.sber_mqtt_bridge.repairs import (
    check_and_create_issues,
)
from custom_components.sber_mqtt_bridge.sber_bridge import SberBridge


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entry(config=None, options=None):
    """Create a mock config entry."""
    entry = MagicMock()
    entry.data = config or {
        CONF_SBER_LOGIN: "test",
        CONF_SBER_PASSWORD: "pass",
        CONF_SBER_BROKER: "broker.test",
        CONF_SBER_PORT: 8883,
    }
    entry.options = options or {}
    return entry


class _ConcreteEntity(BaseEntity):
    """Minimal concrete entity for testing."""

    def to_sber_current_state(self) -> dict:
        return {self.entity_id: {"states": []}}

    def process_cmd(self, cmd_data: dict) -> list[dict]:
        return []


def _make_entity(entity_id: str = "light.test", category: str = "light", filled: bool = True) -> _ConcreteEntity:
    """Create a concrete test entity."""
    entity = _ConcreteEntity(category, {"entity_id": entity_id, "name": "Test"})
    if filled:
        entity.fill_by_ha_state({"state": "on", "attributes": {}})
    return entity


# ===========================================================================
# Task 21: HA Repairs
# ===========================================================================


class TestRepairsEntityNotFound:
    """Tests for entity_not_found repair issue."""

    @pytest.mark.asyncio
    async def test_creates_issue_for_missing_entity(self):
        """Issue created when entity in exposed list is not in entities dict."""
        hass = MagicMock()
        bridge = MagicMock(spec=SberBridge)
        bridge.enabled_entity_ids = ["light.missing", "light.found"]
        bridge.entities = {"light.found": _make_entity("light.found")}
        bridge.is_connected = True
        bridge.stats = MagicMock(reconnect_count=0)

        with patch("custom_components.sber_mqtt_bridge.repairs.async_create_issue") as mock_create, \
             patch("custom_components.sber_mqtt_bridge.repairs.async_delete_issue") as mock_delete:
            await check_and_create_issues(hass, bridge)

        # Should create issue for light.missing
        create_calls = [c for c in mock_create.call_args_list if "entity_not_found_light.missing" in str(c)]
        assert len(create_calls) == 1

        # Should delete issue for light.found
        delete_calls = [c for c in mock_delete.call_args_list if "entity_not_found_light.found" in str(c)]
        assert len(delete_calls) == 1

    @pytest.mark.asyncio
    async def test_no_issues_when_all_found(self):
        """No entity_not_found issues when all entities exist."""
        hass = MagicMock()
        bridge = MagicMock(spec=SberBridge)
        bridge.enabled_entity_ids = ["light.a"]
        bridge.entities = {"light.a": _make_entity("light.a")}
        bridge.is_connected = True
        bridge.stats = MagicMock(reconnect_count=0)

        with patch("custom_components.sber_mqtt_bridge.repairs.async_create_issue") as mock_create, \
             patch("custom_components.sber_mqtt_bridge.repairs.async_delete_issue"):
            await check_and_create_issues(hass, bridge)

        # No entity_not_found creation calls
        not_found_creates = [c for c in mock_create.call_args_list if "entity_not_found" in str(c)]
        assert len(not_found_creates) == 0


class TestRepairsEntitiesWithoutState:
    """Tests for entities_without_state repair issue."""

    @pytest.mark.asyncio
    async def test_creates_issue_for_unfilled_entities(self):
        """Issue created when entities have no state yet."""
        hass = MagicMock()
        bridge = MagicMock(spec=SberBridge)
        unfilled = _make_entity("light.no_state", filled=False)
        bridge.enabled_entity_ids = ["light.no_state"]
        bridge.entities = {"light.no_state": unfilled}
        bridge.is_connected = True
        bridge.stats = MagicMock(reconnect_count=0)

        with patch("custom_components.sber_mqtt_bridge.repairs.async_create_issue") as mock_create, \
             patch("custom_components.sber_mqtt_bridge.repairs.async_delete_issue"):
            await check_and_create_issues(hass, bridge)

        state_creates = [c for c in mock_create.call_args_list if "entities_without_state" in str(c)]
        assert len(state_creates) == 1

    @pytest.mark.asyncio
    async def test_deletes_issue_when_all_filled(self):
        """Issue deleted when all entities have state."""
        hass = MagicMock()
        bridge = MagicMock(spec=SberBridge)
        bridge.enabled_entity_ids = ["light.ok"]
        bridge.entities = {"light.ok": _make_entity("light.ok", filled=True)}
        bridge.is_connected = True
        bridge.stats = MagicMock(reconnect_count=0)

        with patch("custom_components.sber_mqtt_bridge.repairs.async_create_issue"), \
             patch("custom_components.sber_mqtt_bridge.repairs.async_delete_issue") as mock_delete:
            await check_and_create_issues(hass, bridge)

        state_deletes = [c for c in mock_delete.call_args_list if "entities_without_state" in str(c)]
        assert len(state_deletes) == 1


class TestRepairsConnectionIssues:
    """Tests for connection_issues repair issue."""

    @pytest.mark.asyncio
    async def test_creates_issue_on_many_reconnects(self):
        """Issue created when disconnected with >5 reconnect attempts."""
        hass = MagicMock()
        bridge = MagicMock(spec=SberBridge)
        bridge.enabled_entity_ids = []
        bridge.entities = {}
        bridge.is_connected = False
        bridge.stats = MagicMock(reconnect_count=10)

        with patch("custom_components.sber_mqtt_bridge.repairs.async_create_issue") as mock_create, \
             patch("custom_components.sber_mqtt_bridge.repairs.async_delete_issue"):
            await check_and_create_issues(hass, bridge)

        conn_creates = [c for c in mock_create.call_args_list if "connection_issues" in str(c)]
        assert len(conn_creates) == 1

    @pytest.mark.asyncio
    async def test_deletes_issue_when_connected(self):
        """Issue deleted when connected."""
        hass = MagicMock()
        bridge = MagicMock(spec=SberBridge)
        bridge.enabled_entity_ids = []
        bridge.entities = {}
        bridge.is_connected = True
        bridge.stats = MagicMock(reconnect_count=10)

        with patch("custom_components.sber_mqtt_bridge.repairs.async_create_issue"), \
             patch("custom_components.sber_mqtt_bridge.repairs.async_delete_issue") as mock_delete:
            await check_and_create_issues(hass, bridge)

        conn_deletes = [c for c in mock_delete.call_args_list if "connection_issues" in str(c)]
        assert len(conn_deletes) == 1


# ===========================================================================
# Task 22: Custom capabilities - features override
# ===========================================================================


class TestFeaturesOverride:
    """Tests for sber_features_add / sber_features_remove."""

    def test_get_final_features_list_no_overrides(self):
        """Without overrides, returns create_features_list()."""
        entity = _make_entity()
        assert entity.get_final_features_list() == ["online"]

    def test_get_final_features_list_with_add(self):
        """Extra features are appended."""
        entity = _make_entity()
        entity._extra_features = ["light_brightness", "light_colour"]
        result = entity.get_final_features_list()
        assert result == ["online", "light_brightness", "light_colour"]

    def test_get_final_features_list_with_remove(self):
        """Removed features are excluded."""
        entity = _make_entity()
        entity._removed_features = ["online"]
        result = entity.get_final_features_list()
        assert result == []

    def test_get_final_features_list_add_and_remove(self):
        """Both add and remove work together."""
        entity = _make_entity()
        entity._extra_features = ["light_brightness"]
        entity._removed_features = ["online"]
        result = entity.get_final_features_list()
        assert result == ["light_brightness"]

    def test_get_final_features_no_duplicates(self):
        """Adding a feature that already exists does not duplicate."""
        entity = _make_entity()
        entity._extra_features = ["online", "light_brightness"]
        result = entity.get_final_features_list()
        assert result == ["online", "light_brightness"]

    def test_to_sber_state_uses_final_features(self):
        """to_sber_state uses get_final_features_list instead of create_features_list."""
        entity = _make_entity()
        entity._extra_features = ["light_brightness"]
        state = entity.to_sber_state()
        assert "light_brightness" in state["model"]["features"]
        assert "online" in state["model"]["features"]


class TestYamlFeaturesConfig:
    """Tests for YAML parsing of features_add/remove."""

    def test_entity_custom_config_features_fields(self):
        """EntityCustomConfig has features_add and features_remove fields."""
        cfg = EntityCustomConfig(
            sber_features_add=["light_brightness"],
            sber_features_remove=["online"],
        )
        assert cfg.sber_features_add == ["light_brightness"]
        assert cfg.sber_features_remove == ["online"]

    def test_parse_yaml_config_with_features(self):
        """parse_yaml_config handles sber_features_add/remove."""
        yaml_data = {
            "entity_config": {
                "light.test": {
                    "sber_features_add": ["light_brightness"],
                    "sber_features_remove": ["online"],
                }
            }
        }
        config = parse_yaml_config(yaml_data)
        cfg = config.get("light.test")
        assert cfg is not None
        assert cfg.sber_features_add == ["light_brightness"]
        assert cfg.sber_features_remove == ["online"]

    def test_parse_yaml_config_without_features(self):
        """parse_yaml_config works without features fields."""
        yaml_data = {
            "entity_config": {
                "light.test": {"sber_name": "Kitchen"}
            }
        }
        config = parse_yaml_config(yaml_data)
        cfg = config.get("light.test")
        assert cfg is not None
        assert cfg.sber_features_add is None
        assert cfg.sber_features_remove is None


# ===========================================================================
# Task 24: Auto re-publish config
# ===========================================================================


class TestAutoRepublishConfig:
    """Tests for auto re-publish config on unknown entity status request."""

    @pytest.fixture
    def bridge(self):
        """Create a bridge with mocked publish methods."""
        hass = MagicMock()
        entry = _make_entry()
        b = SberBridge(hass, entry)
        b._publish_config = AsyncMock()
        b._publish_states = AsyncMock()
        b._connected = True
        b._entities = {"light.known": _make_entity("light.known")}
        b._enabled_entity_ids = ["light.known"]
        return b

    @pytest.mark.asyncio
    async def test_republishes_config_for_unknown_entities(self, bridge):
        """Config re-published when Sber asks about unknown entities."""
        payload = json.dumps({"devices": ["light.unknown"]}).encode()
        await bridge._handle_sber_status_request(payload)

        bridge._publish_config.assert_called_once()
        bridge._publish_states.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_republish_for_known_entities(self, bridge):
        """Config NOT re-published when Sber asks about known entities."""
        payload = json.dumps({"devices": ["light.known"]}).encode()
        await bridge._handle_sber_status_request(payload)

        bridge._publish_config.assert_not_called()
        bridge._publish_states.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_republish_for_root(self, bridge):
        """Config NOT re-published when 'root' is in request (special ID)."""
        payload = json.dumps({"devices": ["root"]}).encode()
        await bridge._handle_sber_status_request(payload)

        bridge._publish_config.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_republish_for_all_entities_request(self, bridge):
        """Config NOT re-published for empty (=all) entity request."""
        payload = json.dumps({"devices": [""]}).encode()
        await bridge._handle_sber_status_request(payload)

        bridge._publish_config.assert_not_called()


# ===========================================================================
# Task 25: Persist redefinitions
# ===========================================================================


class TestPersistRedefinitions:
    """Tests for persisting redefinitions to entry options."""

    @pytest.fixture
    def bridge(self):
        """Create a bridge for redefinitions tests."""
        hass = MagicMock()
        entry = _make_entry()
        b = SberBridge(hass, entry)
        return b

    @pytest.mark.asyncio
    async def test_change_group_persists(self, bridge):
        """_handle_change_group calls _persist_redefinitions."""
        payload = json.dumps({
            "device_id": "light.living_room",
            "home": "Home",
            "room": "Living Room",
        }).encode()

        await bridge._handle_change_group(payload)

        assert bridge._redefinitions["light.living_room"]["room"] == "Living Room"
        bridge._hass.config_entries.async_update_entry.assert_called_once()

    @pytest.mark.asyncio
    async def test_rename_device_persists(self, bridge):
        """_handle_rename_device calls _persist_redefinitions."""
        payload = json.dumps({
            "device_id": "light.kitchen",
            "new_name": "Kitchen Light New",
        }).encode()

        await bridge._handle_rename_device(payload)

        assert bridge._redefinitions["light.kitchen"]["name"] == "Kitchen Light New"
        bridge._hass.config_entries.async_update_entry.assert_called_once()

    def test_persist_redefinitions_updates_entry(self, bridge):
        """_persist_redefinitions updates entry options with redefinitions."""
        bridge._redefinitions = {"light.a": {"room": "Room A"}}
        bridge._persist_redefinitions()

        call_args = bridge._hass.config_entries.async_update_entry.call_args
        new_options = call_args.kwargs.get("options") or call_args[1].get("options")
        assert new_options["redefinitions"] == {"light.a": {"room": "Room A"}}

    def test_load_persisted_redefinitions(self):
        """_load_exposed_entities loads saved redefinitions from options."""
        hass = MagicMock()
        hass.data = {}
        # Include light.saved in exposed list so it survives pruning
        entry = _make_entry(options={
            CONF_EXPOSED_ENTITIES: ["light.saved"],
            "redefinitions": {"light.saved": {"room": "Saved Room"}},
        })
        bridge = SberBridge(hass, entry)

        # Mock registries: entity registry returns a valid entry for light.saved
        mock_reg_entry = MagicMock()
        mock_reg_entry.entity_id = "light.saved"
        mock_reg_entry.area_id = ""
        mock_reg_entry.device_id = None
        mock_reg_entry.name = "Saved"
        mock_reg_entry.original_name = "Saved"
        mock_reg_entry.platform = "test"
        mock_reg_entry.unique_id = "saved_1"
        mock_reg_entry.original_device_class = None
        mock_reg_entry.entity_category = None
        mock_reg_entry.icon = None
        mock_reg_entry.disabled_by = None
        mock_reg_entry.hidden_by = None

        with patch("custom_components.sber_mqtt_bridge.sber_bridge.er") as mock_er, \
             patch("custom_components.sber_mqtt_bridge.sber_bridge.dr"), \
             patch("custom_components.sber_mqtt_bridge.sber_bridge.check_and_create_issues"):
            mock_entity_reg = MagicMock()
            mock_entity_reg.async_get.return_value = mock_reg_entry
            mock_er.async_get.return_value = mock_entity_reg

            # Mock states so entity gets filled
            mock_state = MagicMock()
            mock_state.entity_id = "light.saved"
            mock_state.state = "on"
            mock_state.attributes = {}
            hass.states.get.return_value = mock_state

            bridge._load_exposed_entities()

        assert bridge._redefinitions.get("light.saved") == {"room": "Saved Room"}
