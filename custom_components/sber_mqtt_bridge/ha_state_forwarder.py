"""HA state change → Sber publish forwarder.

Owns the HA state-change subscription, linked-entity routing, debouncing
of rapid updates, and the feature-change detection that triggers config
republish.  Extracted from :class:`SberBridge` to isolate the HA-facing
event loop from the MQTT transport (SRP).

Usage::

    forwarder = HaStateForwarder(
        hass=hass,
        debounce_delay=0.1,
        get_entities=lambda: bridge.entities,
        get_linked_reverse=lambda: bridge.linked_reverse_map,
        on_publish_states=bridge.async_publish_entity_ids,
        on_republish_config=bridge.async_republish_config,
        create_safe_task=bridge._create_safe_task,
    )
    forwarder.subscribe([...])
    ...
    forwarder.unsubscribe_all()
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event

if TYPE_CHECKING:
    from .devices.base_entity import BaseEntity

_LOGGER = logging.getLogger(__name__)


class HaStateForwarder:
    """Forward HA ``state_changed`` events to Sber via bridge callbacks.

    Responsibilities:
        - Subscribe / unsubscribe to HA state-change events for a set of
          entity IDs (primary + linked).
        - Route linked sensor updates to their primary entity.
        - Detect unfilled → filled transitions and feature-set changes,
          triggering a config republish via callback.
        - Debounce rapid state changes so multiple updates within
          ``debounce_delay`` seconds coalesce into a single publish.

    This class owns NO bridge state — it reads entities and linked
    mappings through callbacks so the bridge remains the single source
    of truth.
    """

    def __init__(
        self,
        *,
        hass: HomeAssistant,
        debounce_delay: float,
        get_entities: Callable[[], dict[str, BaseEntity]],
        get_linked_reverse: Callable[[], dict[str, tuple[str, str]]],
        on_publish_states: Callable[[list[str]], Awaitable[None]],
        on_republish_config: Callable[[], Awaitable[None]],
        create_safe_task: Callable[..., asyncio.Task],
    ) -> None:
        """Initialize the forwarder.

        Args:
            hass: Home Assistant core instance.
            debounce_delay: Seconds to coalesce rapid state changes.
            get_entities: Callable returning the current entities dict.
            get_linked_reverse: Callable returning linked-reverse mapping.
            on_publish_states: Async callback to publish a list of entity IDs.
            on_republish_config: Async callback to force a config republish.
            create_safe_task: Bridge helper wrapping ``hass.async_create_task``
                with error logging.
        """
        self._hass = hass
        self._debounce_delay = debounce_delay
        self._get_entities = get_entities
        self._get_linked_reverse = get_linked_reverse
        self._on_publish_states = on_publish_states
        self._on_republish_config = on_republish_config
        self._create_safe_task = create_safe_task

        self._unsub_listeners: list[Callable[[], None]] = []
        self._pending_publish_ids: set[str] = set()
        self._publish_timer: asyncio.TimerHandle | None = None

    def set_debounce_delay(self, delay: float) -> None:
        """Update the debounce delay at runtime."""
        self._debounce_delay = delay

    def subscribe(self, entity_ids: list[str]) -> None:
        """Replace the set of tracked entities and resubscribe.

        Unsubscribes any previous listeners first, so subsequent calls
        are idempotent.

        Args:
            entity_ids: Combined list of primary + linked entity IDs to
                track.  Empty list is allowed and results in a no-op.
        """
        self.unsubscribe_all()
        if not entity_ids:
            return
        unsub = async_track_state_change_event(
            self._hass,
            entity_ids,
            self._on_ha_state_changed,
        )
        self._unsub_listeners.append(unsub)

    def unsubscribe_all(self) -> None:
        """Unsubscribe from HA state-change events and cancel pending publish."""
        for unsub in self._unsub_listeners:
            unsub()
        self._unsub_listeners.clear()
        if self._publish_timer is not None:
            self._publish_timer.cancel()
            self._publish_timer = None
        self._pending_publish_ids.clear()

    @callback
    def _on_ha_state_changed(self, event: Event) -> None:
        """Handle HA state change → route to linked / primary handler."""
        entity_id = event.data["entity_id"]
        new_state = event.data.get("new_state")
        if new_state is None:
            return
        ha_state_dict = self._ha_state_to_dict(new_state)

        linked_reverse = self._get_linked_reverse()
        if entity_id in linked_reverse:
            self._handle_linked_state_change(entity_id, ha_state_dict, linked_reverse)
            return
        self._handle_primary_state_change(entity_id, event, ha_state_dict)

    @staticmethod
    def _ha_state_to_dict(state_obj: Any) -> dict:
        """Convert HA state object to the internal plain-dict representation."""
        return {
            "entity_id": state_obj.entity_id,
            "state": state_obj.state,
            "attributes": dict(state_obj.attributes),
        }

    @callback
    def _handle_linked_state_change(
        self,
        entity_id: str,
        ha_state_dict: dict,
        linked_reverse: dict[str, tuple[str, str]],
    ) -> None:
        """Forward linked sensor state change to its primary entity."""
        primary_id, role = linked_reverse[entity_id]
        entities = self._get_entities()
        primary_entity = entities.get(primary_id)
        if primary_entity is None or not hasattr(primary_entity, "update_linked_data"):
            return
        features_before = primary_entity.get_final_features_list()
        primary_entity.update_linked_data(role, ha_state_dict)
        features_after = primary_entity.get_final_features_list()
        _LOGGER.debug("Linked %s (%s) → primary %s", entity_id, role, primary_id)
        if features_before != features_after:
            _LOGGER.info(
                "Features changed for %s after linked update — republishing config",
                primary_id,
            )
            self._create_safe_task(
                self._on_republish_config(), name="republish_config_linked"
            )
        self._schedule_debounced_publish(primary_id)

    @callback
    def _handle_primary_state_change(
        self, entity_id: str, event: Event, ha_state_dict: dict
    ) -> None:
        """Process a state change for an entity directly registered in the bridge."""
        entities = self._get_entities()
        entity = entities.get(entity_id)
        if entity is None:
            return

        was_filled = entity.is_filled_by_state
        try:
            old_state_obj = event.data.get("old_state")
            old_state_dict = (
                self._ha_state_to_dict(old_state_obj) if old_state_obj else None
            )
            entity.process_state_change(old_state_dict, ha_state_dict)
        except (TypeError, ValueError, KeyError, AttributeError):
            _LOGGER.exception("Error processing state change for %s", entity_id)
            return

        if not was_filled and entity.is_filled_by_state:
            _LOGGER.info("Entity %s now available — republishing config", entity_id)
            self._create_safe_task(
                self._on_republish_config(), name="republish_config_new_entity"
            )

        _LOGGER.debug("HA → Sber state: %s = %s", entity_id, ha_state_dict.get("state"))
        self._schedule_debounced_publish(entity_id)

    @callback
    def _schedule_debounced_publish(self, entity_id: str) -> None:
        """Accumulate an entity ID and schedule a debounced flush."""
        self._pending_publish_ids.add(entity_id)
        if self._publish_timer is not None:
            self._publish_timer.cancel()
        self._publish_timer = self._hass.loop.call_later(
            self._debounce_delay, self._fire_debounced_publish
        )

    @callback
    def _fire_debounced_publish(self) -> None:
        """Flush accumulated IDs into a single publish task."""
        self._publish_timer = None
        ids = list(self._pending_publish_ids)
        self._pending_publish_ids.clear()
        if ids:
            self._create_safe_task(
                self._on_publish_states(ids), name="debounced_publish"
            )
