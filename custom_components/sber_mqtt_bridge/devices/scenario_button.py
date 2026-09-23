"""Sber Scenario Button entity -- maps HA input_boolean and event to Sber scenario_button."""

from __future__ import annotations

import logging

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN

from ..sber_constants import SberFeature
from ..sber_models import make_bool_value, make_enum_value, make_state
from .base_entity import NO_SNAPSHOT, BaseEntity, NoSnapshot

_LOGGER = logging.getLogger(__name__)

SCENARIO_BUTTON_CATEGORY = "scenario_button"
"""Sber device category for scenario button entities."""

EVENT_DOMAIN = "event"
"""HA domain whose entities report presses as ``event_type`` attribute changes."""

_IGNORED_EVENT_MARKERS: tuple[str, ...] = ("release", "triple", "quadruple", "many")
"""``event_type`` substrings with no Sber counterpart.

Releases follow a hold that was already reported as ``long_press``;
triple / multi presses have no value in the Sber ``button_event`` enum.
Checked first so ``remote_button_triple_press`` does not fall through
to the generic ``press`` → ``click`` rule.
"""

_EVENT_TYPE_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("hold", "long"), "long_press"),
    (("double",), "double_click"),
    (("single", "click", "short", "press", "toggle"), "click"),
)
"""Ordered ``(substrings, sber_value)`` rules; the first matching rule wins.

Covers the common naming schemes: Zigbee2MQTT (``single`` / ``double`` /
``hold``), ZHA (``remote_button_short_press``) and Hue (``initial_press``,
``long_press``).
"""


def map_event_type(event_type: str | None) -> str | None:
    """Map a HA ``event_type`` to a Sber ``button_event`` value.

    Args:
        event_type: Value of the HA event entity's ``event_type`` attribute.

    Returns:
        ``click``, ``double_click`` or ``long_press``, or ``None`` when the
        event has no Sber counterpart and must not be reported.
    """
    if not event_type:
        return None
    lowered = event_type.lower()
    if any(marker in lowered for marker in _IGNORED_EVENT_MARKERS):
        return None
    for markers, sber_value in _EVENT_TYPE_RULES:
        if any(marker in lowered for marker in markers):
            return sber_value
    return None


class ScenarioButtonEntity(BaseEntity):
    """Sber scenario button entity.

    Maps HA entities to the Sber 'scenario_button' category:

    * ``input_boolean`` -- turning on is a ``click``, turning off a
      ``double_click``.
    * ``event`` (Zigbee buttons from Z2M / ZHA) -- every new event is a
      press, its ``event_type`` mapped by :func:`map_event_type`.

    Only a *fresh* press is reported: ``button_event`` is included in the
    published state while a press is pending and dropped once it went out.
    Full republishes (startup, reconnect, status request) therefore carry
    only ``online`` and never replay the last press -- a replay would fire
    the user's Sber scenario on every HA restart.  A press is detected only
    in :meth:`process_state_change`; loading via :meth:`fill_by_ha_state`
    just records the baseline.
    """

    def __init__(self, entity_data: dict) -> None:
        """Initialize scenario button entity.

        Args:
            entity_data: HA entity registry dict containing entity metadata.
        """
        super().__init__(SCENARIO_BUTTON_CATEGORY, entity_data)
        self.button_event = "click"
        self._press_pending = False
        self._has_baseline = False
        self._last_trigger: str | None = None

    @property
    def _is_event_domain(self) -> bool:
        """Return True when the source HA entity is an ``event`` entity."""
        return self.entity_id.startswith(f"{EVENT_DOMAIN}.")

    @property
    def _is_online(self) -> bool:
        """Check if entity is online (reachable).

        For ``event`` entities ``unknown`` means "never pressed", not
        unreachable, so only ``unavailable`` counts as offline.

        Returns:
            True if the entity state indicates it is reachable.
        """
        if self._is_event_domain:
            return self.state not in (STATE_UNAVAILABLE, None)
        return super()._is_online

    def fill_by_ha_state(self, ha_state: dict) -> None:
        """Parse HA state and record it as the press-detection baseline.

        Never reports a press by itself -- see :meth:`process_state_change`.

        Args:
            ha_state: HA state dict with 'state' key.
        """
        super().fill_by_ha_state(ha_state)
        state = ha_state.get("state")
        if state in (STATE_UNAVAILABLE, None):
            return
        self._has_baseline = True
        self._last_trigger = None if state == STATE_UNKNOWN else state

    def process_state_change(self, old_state: dict | None, new_state: dict) -> None:
        """Detect a button press and refresh internal state.

        A press is a new trigger value (event timestamp or boolean state)
        that differs from the last one seen.  Without a baseline -- the
        entity was unavailable when loaded -- the first value is a restore,
        not a press.

        Args:
            old_state: Previous HA state dict (may be None).
            new_state: New HA state dict.
        """
        state = new_state.get("state")
        if self._has_baseline and state not in (STATE_UNAVAILABLE, STATE_UNKNOWN, None) and state != self._last_trigger:
            sber_value = self._resolve_press(new_state)
            if sber_value is not None:
                self.button_event = sber_value
                self._press_pending = True
            else:
                _LOGGER.debug(
                    "%s: event_type %r has no Sber button_event, ignored",
                    self.entity_id,
                    new_state.get("attributes", {}).get("event_type"),
                )
        super().process_state_change(old_state, new_state)

    def _resolve_press(self, ha_state: dict) -> str | None:
        """Return the Sber ``button_event`` value for a detected press.

        Args:
            ha_state: New HA state dict.

        Returns:
            Sber enum value, or ``None`` when the press must be ignored.
        """
        if self._is_event_domain:
            return map_event_type(ha_state.get("attributes", {}).get("event_type"))
        return "click" if ha_state.get("state") == "on" else "double_click"

    def mark_state_published(self, *, snapshot: dict | NoSnapshot | None = NO_SNAPSHOT) -> None:
        """Record the published state and consume the press it carried.

        The press is consumed only when the published snapshot actually
        contained ``button_event``: a snapshot taken before the press
        arrived must not swallow it.  The stored diff baseline drops
        ``button_event``, so a press-free state compares equal while any
        pending press -- even a repeat of the same value -- differs and
        :meth:`has_significant_change` reports it.

        Args:
            snapshot: The exact wire state that went out, see
                :meth:`BaseEntity.mark_state_published`.
        """
        super().mark_state_published(snapshot=snapshot)
        published = self._previous_sber_state
        if published is None:
            return
        entry = published.get(self.entity_id, {})
        states = entry.get("states", [])
        if any(s.get("key") == SberFeature.BUTTON_EVENT for s in states):
            self._press_pending = False
            self._previous_sber_state = {
                **published,
                self.entity_id: {
                    **entry,
                    "states": [s for s in states if s.get("key") != SberFeature.BUTTON_EVENT],
                },
            }

    def _create_features_list(self) -> list[str]:
        """Return Sber feature list including 'button_event'.

        Returns:
            List of Sber feature strings supported by this entity.
        """
        return [*super()._create_features_list(), "button_event"]

    def create_allowed_values_list(self) -> dict[str, dict]:
        """Return allowed values for button_event feature."""
        return {
            "button_event": {
                "type": "ENUM",
                "enum_values": {"values": ["click", "double_click", "long_press"]},
            },
        }

    def _build_current_state(self) -> dict[str, dict]:
        """Build Sber current state payload.

        ``button_event`` is included only while a press is pending.

        Returns:
            Dict mapping entity_id to its Sber state representation.
        """
        states = [make_state(SberFeature.ONLINE, make_bool_value(self._is_online))]
        if self._press_pending:
            states.append(make_state(SberFeature.BUTTON_EVENT, make_enum_value(self.button_event)))
        return {self.entity_id: {"states": states}}
