"""Base class for Sber on/off entities (relay, socket).

Provides shared implementations of ``fill_by_ha_state``, ``_create_features_list``,
and ``_build_current_state`` for devices that expose a simple on/off state
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

_CHILD_LOCK_CATEGORIES = frozenset({"socket"})
"""Sber categories (among OnOffEntity users) whose spec includes ``child_lock``.

Per the Sber functions catalog, ``child_lock`` exists only for
``socket`` / ``kettle`` / ``vacuum_cleaner`` — advertising it on
``relay`` risks silent device rejection (issue #44 audit).  Default data
for :attr:`OnOffEntity._supports_child_lock`; subclasses override the
flag instead of editing this set."""

_ENERGY_CATEGORIES = frozenset({"relay", "socket"})
"""Sber categories whose spec includes power / voltage / current.

Default data for :attr:`OnOffEntity._supports_energy`; subclasses
override the flag instead of editing this set."""


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

    @property
    def _supports_child_lock(self) -> bool:
        """Whether this entity may advertise the Sber ``child_lock`` feature.

        Overridable capability flag (same pattern as ``_supports_*`` in
        ``ClimateEntity``): subclasses may shadow this property with a
        plain class attribute (``_supports_child_lock = True``) instead
        of the base class enumerating its subclasses' categories.  The
        default derives from the category per the Sber functions catalog.

        An override is a protocol-visible decision, not a free knob:
        ``child_lock`` must be present in
        ``CATEGORY_REFERENCE_FEATURES[self.category]`` or Sber silently
        rejects the whole device (issue #44).
        ``test_link_roles_registry.TestOnOffFlagsMatchSberSpec`` checks
        every registered ``OnOffEntity`` subclass against the generated
        spec table.

        Returns:
            True if the Sber spec includes ``child_lock`` for this entity.
        """
        return self.category in _CHILD_LOCK_CATEGORIES

    @property
    def _supports_energy(self) -> bool:
        """Whether this entity may advertise power / voltage / current.

        Overridable capability flag; subclasses may shadow it with a
        plain class attribute.  The default derives from the category
        per the Sber functions catalog.  Same protocol constraint as
        :attr:`_supports_child_lock`: ``power`` / ``voltage`` /
        ``current`` must exist in
        ``CATEGORY_REFERENCE_FEATURES[self.category]``.

        Returns:
            True if the Sber spec includes energy features for this entity.
        """
        return self.category in _ENERGY_CATEGORIES

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

    def _create_features_list(self) -> list[str]:
        """Return Sber feature list including 'on_off' and optional features.

        Energy and child_lock features are gated by the overridable
        ``_supports_energy`` / ``_supports_child_lock`` flags: the Sber
        spec declares power/voltage/current only for relay/socket and
        ``child_lock`` only for socket-like categories (issue #44 audit).

        Returns:
            List of Sber feature strings supported by this entity.
        """
        features = [*super()._create_features_list(), "on_off"]
        if self._supports_energy:
            if self._power is not None:
                features.append("power")
            if self._voltage is not None:
                features.append("voltage")
            if self._current is not None:
                features.append("current")
        if self._child_lock is not None and self._supports_child_lock:
            features.append("child_lock")
        return features

    def _build_current_state(self) -> dict[str, dict]:
        """Build Sber current state payload with online, on_off, energy, and child_lock.

        Returns:
            Dict mapping entity_id to its Sber state representation.
        """
        states = [
            make_state(SberFeature.ONLINE, make_bool_value(self._is_online)),
            make_state(SberFeature.ON_OFF, make_bool_value(self.current_state)),
        ]
        if self._supports_energy:
            if self._power is not None:
                states.append(make_state(SberFeature.POWER, make_integer_value(self._power)))
            if self._voltage is not None:
                states.append(make_state(SberFeature.VOLTAGE, make_integer_value(self._voltage)))
            if self._current is not None:
                states.append(make_state(SberFeature.CURRENT, make_integer_value(self._current)))
        if self._child_lock is not None and self._supports_child_lock:
            states.append(make_state(SberFeature.CHILD_LOCK, make_bool_value(self._child_lock)))
        return {self.entity_id: {"states": states}}
