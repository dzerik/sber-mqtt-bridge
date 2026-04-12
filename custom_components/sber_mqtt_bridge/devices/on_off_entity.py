"""Base class for Sber on/off entities (relay, socket).

Provides shared implementations of ``fill_by_ha_state``, ``create_features_list``,
and ``to_sber_current_state`` for devices that expose a simple on/off state
via the Sber ``on_off`` feature.

Supports optional ``power``, ``voltage``, and ``current`` features when the
HA entity reports those values via attributes.
"""

from __future__ import annotations

import logging
from typing import ClassVar

from ..sber_constants import SberFeature
from ..sber_models import make_bool_value, make_integer_value, make_state
from .base_entity import AttrSpec, BaseEntity, _safe_bool_parser, _safe_int_parser

_LOGGER = logging.getLogger(__name__)


class OnOffEntity(BaseEntity):
    """Base class for on/off entities that expose the Sber 'on_off' feature.

    Subclasses must implement ``process_cmd`` to map Sber on/off commands
    to the appropriate HA service calls (e.g., ``turn_on``/``turn_off``
    for relays).

    Subclasses may override ``_ha_on_state`` if the HA 'on' state string
    differs from the default ``"on"``.

    Optionally reports ``power``, ``voltage``, and ``current`` when
    the HA entity has those attributes.
    """

    current_state: bool
    """Current on/off state of the entity."""

    _ha_on_state: str = "on"
    """HA state string that corresponds to 'on' (override in subclass if needed)."""

    ATTR_SPECS: ClassVar[tuple[AttrSpec, ...]] = (
        AttrSpec(field="_power", attr_keys=("power",), parser=_safe_int_parser),
        AttrSpec(field="_voltage", attr_keys=("voltage",), parser=_safe_int_parser),
        AttrSpec(field="_current", attr_keys=("current",), parser=_safe_int_parser),
        AttrSpec(field="_child_lock", attr_keys=("child_lock",), parser=_safe_bool_parser),
    )

    def __init__(self, category: str, entity_data: dict) -> None:
        """Initialize on/off entity.

        Args:
            category: Sber device category string.
            entity_data: HA entity registry dict containing entity metadata.
        """
        super().__init__(category, entity_data)
        self.current_state = False
        self._power: int | None = None
        self._voltage: int | None = None
        self._current: int | None = None
        self._child_lock: bool | None = None

    def fill_by_ha_state(self, ha_state: dict) -> None:
        """Parse HA state and update on/off status, energy, and child_lock attributes.

        Uses :class:`BaseEntity.ATTR_SPECS` for the declarative
        attribute parsing of power / voltage / current / child_lock,
        falling back to the ``current_state`` check which depends on
        the subclass-overridable ``_ha_on_state``.

        Args:
            ha_state: HA state dict with 'state' and 'attributes' keys.
        """
        super().fill_by_ha_state(ha_state)
        self.current_state = ha_state.get("state") == self._ha_on_state
        self._apply_attr_specs(ha_state.get("attributes", {}))

    def create_features_list(self) -> list[str]:
        """Return Sber feature list including 'on_off' and optional features.

        Returns:
            List of Sber feature strings supported by this entity.
        """
        features = [*super().create_features_list(), "on_off"]
        if self._power is not None:
            features.append("power")
        if self._voltage is not None:
            features.append("voltage")
        if self._current is not None:
            features.append("current")
        if self._child_lock is not None:
            features.append("child_lock")
        return features

    def to_sber_current_state(self) -> dict[str, dict]:
        """Build Sber current state payload with online, on_off, energy, and child_lock.

        Returns:
            Dict mapping entity_id to its Sber state representation.
        """
        states = [
            make_state(SberFeature.ONLINE, make_bool_value(self._is_online)),
            make_state(SberFeature.ON_OFF, make_bool_value(self.current_state)),
        ]
        if self._power is not None:
            states.append(make_state(SberFeature.POWER, make_integer_value(self._power)))
        if self._voltage is not None:
            states.append(make_state(SberFeature.VOLTAGE, make_integer_value(self._voltage)))
        if self._current is not None:
            states.append(make_state(SberFeature.CURRENT, make_integer_value(self._current)))
        if self._child_lock is not None:
            states.append(make_state(SberFeature.CHILD_LOCK, make_bool_value(self._child_lock)))
        return {self.entity_id: {"states": states}}
