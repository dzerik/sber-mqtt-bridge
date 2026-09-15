"""Tests for RedefinitionsStore — extracted from SberBridge in v1.38.4."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.sber_mqtt_bridge.const import (
    CONF_SBER_BROKER,
    CONF_SBER_LOGIN,
    CONF_SBER_PASSWORD,
    CONF_SBER_PORT,
)
from custom_components.sber_mqtt_bridge.redefinitions_store import RedefinitionsStore
from custom_components.sber_mqtt_bridge.sber_bridge import SberBridge


def _make_entry() -> MagicMock:
    entry = MagicMock()
    entry.data = {
        CONF_SBER_LOGIN: "test",
        CONF_SBER_PASSWORD: "pass",
        CONF_SBER_BROKER: "broker.test",
        CONF_SBER_PORT: 8883,
    }
    entry.options = {}
    return entry


def _make_bridge() -> SberBridge:
    hass = MagicMock()
    hass.config.location_name = "My Home"
    bridge = SberBridge(hass, _make_entry())
    return bridge


class TestRedefinitionsStoreSkeleton:
    """Smoke tests — actual flush/persist behaviour moves in later tasks."""

    def test_bridge_owns_a_store(self) -> None:
        bridge = _make_bridge()
        assert isinstance(bridge._redef_store, RedefinitionsStore)

    def test_store_starts_empty(self) -> None:
        bridge = _make_bridge()
        assert bridge._redef_store.redefinitions == {}

    def test_redefinitions_property_returns_copy(self) -> None:
        bridge = _make_bridge()
        bridge._redef_store._redefinitions["foo"] = {"x": 1}
        snap = bridge._redef_store.redefinitions
        snap["bar"] = {"y": 2}
        assert "bar" not in bridge._redef_store._redefinitions


class TestUnsavedEdits:
    """``unsaved_edits`` keeps a rename the debounce has not persisted yet."""

    @staticmethod
    def _store(persisted: dict[str, dict]) -> tuple[RedefinitionsStore, MagicMock]:
        entry = _make_entry()
        entry.options = {"redefinitions": persisted}
        store = RedefinitionsStore(MagicMock(), entry)
        store.replace({entity_id: dict(fields) for entity_id, fields in persisted.items()})
        return store, entry

    async def test_unsaved_edit_is_reported_over_the_persisted_record(self) -> None:
        store, _ = self._store({"light.a": {"name": "Old", "room": "Hall"}})
        await store.async_update("light.a", {"name": "New"})
        assert store.unsaved_edits() == {"light.a": {"name": "New", "room": "Hall"}}

    async def test_cleared_field_stays_cleared(self) -> None:
        store, _ = self._store({"light.a": {"name": "Old", "room": "Hall"}})
        await store.async_update("light.a", {"room": None})
        assert store.unsaved_edits() == {"light.a": {"name": "Old"}}

    async def test_later_options_write_wins_for_the_field_it_changed(self) -> None:
        store, entry = self._store({"light.a": {"name": "Old"}})
        await store.async_update("light.a", {"name": "Mine", "room": "Hall"})
        entry.options = {"redefinitions": {"light.a": {"name": "Wizard"}}}
        assert store.unsaved_edits() == {"light.a": {"name": "Wizard", "room": "Hall"}}

    async def test_nothing_is_unsaved_after_a_flush_or_a_discard(self) -> None:
        store, _ = self._store({})
        await store.async_update("light.a", {"name": "New"})
        store.flush_now()
        assert store.unsaved_edits() == {}
        await store.async_update("light.a", {"name": "Newer"})
        store.discard_pending()
        assert store.unsaved_edits() == {}

    async def test_entity_dropped_from_the_store_is_skipped(self) -> None:
        store, _ = self._store({})
        await store.async_update("light.a", {"name": "New"})
        store.replace({})
        assert store.unsaved_edits() == {}
