"""Base class for Sber on/off entities (relay, socket).

Provides shared implementations of ``fill_by_ha_state``, ``_create_features_list``,
and ``_build_current_state`` for devices that expose a simple on/off state
via the Sber ``on_off`` feature.

Supports optional ``power``, ``voltage``, and ``current`` features from
two sources: attributes of the HA entity itself (already in Sber's
units), and companion ``sensor`` entities linked in the ``power`` /
``voltage`` / ``current`` roles (converted from their own
``unit_of_measurement``) — the latter being how Zigbee2MQTT, Tuya, Shelly
and ESPHome actually expose the metering of a smart plug.
"""

from __future__ import annotations

import logging
from typing import ClassVar

from ..sber_constants import SberFeature
from ..sber_models import make_bool_value, make_integer_value, make_state
from .base_entity import (
    AttrSpec,
    BaseEntity,
    _safe_bool_parser,
    _safe_float_parser,
)
from .utils.electrical import (
    ENERGY_FEATURES,
    to_sber_energy_attribute,
    to_sber_energy_value,
)

_LOGGER = logging.getLogger(__name__)

_CHILD_LOCK_CATEGORIES = frozenset({"socket"})
"""Sber categories (among OnOffEntity users) whose spec includes ``child_lock``.

Per the Sber functions catalog, ``child_lock`` exists only for
``socket`` / ``kettle`` / ``vacuum_cleaner`` — advertising it on
``relay`` risks silent device rejection (issue #44 audit).  Default data
for :attr:`OnOffEntity._supports_child_lock`; subclasses override the
flag instead of editing this set."""

_ENERGY_SBER_FEATURES: dict[str, str] = {
    "power": SberFeature.POWER,
    "voltage": SberFeature.VOLTAGE,
    "current": SberFeature.CURRENT,
}
"""Sber feature name → :class:`~..sber_constants.SberFeature` constant.

Keys are also the link-role names (:data:`ENERGY_LINK_ROLES`) and the
keys of :data:`~.utils.electrical.ENERGY_FEATURES`, so declaration,
ingestion and emission iterate one list instead of three hand-written
``if`` blocks that used to drift apart."""

_ENERGY_ATTR_FIELDS: dict[str, str] = {
    "power": "_power",
    "voltage": "_voltage",
    "current": "_current",
}
"""Sber feature name → field filled from the HA entity's own attributes."""

_ENERGY_LINKED_FIELDS: dict[str, str] = {
    "power": "_linked_power",
    "voltage": "_linked_voltage",
    "current": "_linked_current",
}
"""Sber feature name → field filled from a linked companion sensor.

Kept apart from :data:`_ENERGY_ATTR_FIELDS` on purpose: the attribute
fields are rewritten by every primary state change (an ``AttrSpec``
without ``preserve_on_missing`` resets to ``None``), so sharing one field
would blank the metering on each toggle of the socket."""

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

    Optionally reports ``power``, ``voltage``, and ``current``, taken
    either from attributes of the HA entity itself or from companion
    ``sensor`` entities linked in the matching role (see
    :data:`~.base_entity.ENERGY_LINK_ROLES`).  A linked sensor wins over
    an attribute of the same name: it is an explicit user choice and it
    carries a ``unit_of_measurement``, so it can be converted into the
    unit Sber documents, whereas an unitless attribute can only be taken
    at face value.
    """

    current_state: bool
    """Current on/off state of the entity."""

    _ha_on_state: str = "on"
    """HA state string that corresponds to 'on' (override in subclass if needed)."""

    _supports_on_off: ClassVar[bool] = True
    """Whether the Sber spec lists ``on_off`` for this subclass's category.

    True for every user of this base except ``intercom``: the
    "Доступные функции устройства" table on ``c2c/intercom`` names only
    ``online``, ``incoming_call``, ``reject_call`` and ``unlock``.  An
    intercom is an on/off entity in Home Assistant and reuses everything
    else here, so the one function it may not advertise is switched off
    by this flag rather than by forking the class.

    A model carrying a function outside its category's table can be
    rejected by the cloud as a whole, which the user sees as a device
    that never appears in the Sber app.
    """

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
        AttrSpec(field="_power", attr_keys=("power",), parser=_safe_float_parser),
        AttrSpec(field="_voltage", attr_keys=("voltage",), parser=_safe_float_parser),
        AttrSpec(field="_current", attr_keys=("current",), parser=_safe_float_parser),
        AttrSpec(field="_child_lock", attr_keys=("child_lock",), parser=_safe_bool_parser),
    )
    """Metering attributes are parsed as **floats**, not integers.

    ``_safe_int_parser`` truncated a fractional attribute (``0.65``) to
    ``0`` at parse time, i.e. before anything could round it.  The one
    rounding now happens in
    :func:`~.utils.electrical.to_sber_energy_attribute`, so a fractional
    reading survives as ``1`` instead of vanishing, and the linked-sensor
    path keeps full precision until its unit conversion is done."""

    def __init__(self, category: str, entity_data: dict) -> None:
        """Initialize on/off entity.

        Args:
            category: Sber device category string.
            entity_data: HA entity registry dict containing entity metadata.
        """
        super().__init__(category, entity_data)
        self.current_state = False
        self._power: float | None = None
        self._voltage: float | None = None
        self._current: float | None = None
        self._child_lock: bool | None = None
        self._linked_power: int | None = None
        self._linked_voltage: int | None = None
        self._linked_current: int | None = None

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

    def update_linked_data(self, role: str, ha_state: dict) -> None:
        """Ingest a metering reading from a linked companion sensor.

        Smart plugs expose their metering as separate HA ``sensor``
        entities (``sensor.plug_power`` and friends), so this is the path
        energy monitoring actually travels; the attribute path below is
        the rare case.  The reading is normalised to Sber's unit here —
        notably amperes → milliamperes — because the sensor's
        ``unit_of_measurement`` is available only at this point.

        Args:
            role: Link role name (``power`` / ``voltage`` / ``current``);
                anything else is left to other handlers.
            ha_state: HA state dict of the linked sensor, with ``state``
                and ``attributes``.
        """
        super().update_linked_data(role, ha_state)
        field = _ENERGY_LINKED_FIELDS.get(role)
        if field is None:
            return
        attributes = ha_state.get("attributes") or {}
        setattr(
            self,
            field,
            to_sber_energy_value(
                role,
                ha_state.get("state"),
                attributes.get("unit_of_measurement"),
                self.category,
            ),
        )

    def _energy_value(self, feature: str) -> int | None:
        """Return the value to publish for one metering feature.

        Args:
            feature: ``"power"``, ``"voltage"`` or ``"current"``.

        Returns:
            The linked sensor's value when one is linked, otherwise the
            HA attribute of the same name, or ``None`` when neither
            source has a usable reading — the feature must then not be
            declared either.

            A linked sensor wins because it is an explicit user choice
            and carries a ``unit_of_measurement``, so its reading can be
            converted into Sber's unit.  An attribute carries no unit and
            is published as-is (rounded and clamped) —
            :func:`~.utils.electrical.to_sber_energy_attribute` explains
            why re-interpreting it would break the integrations that
            actually fill those attributes.
        """
        linked = getattr(self, _ENERGY_LINKED_FIELDS[feature])
        if linked is not None:
            return linked
        return to_sber_energy_attribute(feature, getattr(self, _ENERGY_ATTR_FIELDS[feature]), self.category)

    def _create_features_list(self) -> list[str]:
        """Return Sber feature list including 'on_off' and optional features.

        ``on_off`` itself, energy and child_lock are gated by the
        overridable ``_supports_on_off`` / ``_supports_energy`` /
        ``_supports_child_lock`` flags: the Sber spec declares
        power/voltage/current only for relay/socket, ``child_lock`` only
        for socket-like categories (issue #44 audit), and ``on_off`` for
        every category using this base except ``intercom``.

        Returns:
            List of Sber feature strings supported by this entity.
        """
        features = list(super()._create_features_list())
        if self._supports_on_off:
            features.append("on_off")
        if self._supports_energy:
            features.extend(f for f in ENERGY_FEATURES if self._energy_value(f) is not None)
        if self._child_lock is not None and self._supports_child_lock:
            features.append("child_lock")
        return features

    def _build_current_state(self) -> dict[str, dict]:
        """Build Sber current state payload with online, on_off, energy, and child_lock.

        Returns:
            Dict mapping entity_id to its Sber state representation.
        """
        states = [make_state(SberFeature.ONLINE, make_bool_value(self._is_online))]
        if self._supports_on_off:
            states.append(make_state(SberFeature.ON_OFF, make_bool_value(self.current_state)))
        if self._supports_energy:
            for feature, sber_key in _ENERGY_SBER_FEATURES.items():
                value = self._energy_value(feature)
                if value is not None:
                    states.append(make_state(sber_key, make_integer_value(value)))
        if self._child_lock is not None and self._supports_child_lock:
            states.append(make_state(SberFeature.CHILD_LOCK, make_bool_value(self._child_lock)))
        return {self.entity_id: {"states": states}}
