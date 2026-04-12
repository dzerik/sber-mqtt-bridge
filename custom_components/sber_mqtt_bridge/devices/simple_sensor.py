"""Base class for read-only Sber sensors with a single value feature.

Provides shared implementations of ``process_cmd``,
``create_features_list``, and ``to_sber_current_state`` so that concrete
sensor subclasses only need to define how their value is extracted and
formatted for the Sber protocol.

Supports optional ``battery_percentage`` feature when the HA entity
reports battery level via attributes.
"""

from __future__ import annotations

import contextlib
import logging
from abc import abstractmethod
from typing import ClassVar

from ..sber_constants import SberFeature
from ..sber_models import make_bool_value, make_enum_value, make_integer_value, make_state
from .base_entity import SENSOR_LINK_ROLES, AttrSpec, BaseEntity, _safe_int_parser
from .utils.signal import rssi_to_signal_strength

_LOGGER = logging.getLogger(__name__)


class SimpleReadOnlySensor(BaseEntity):
    """Base class for read-only sensors that expose a single Sber feature.

    Subclasses must define the class-level attributes ``_sber_value_key``
    and ``_sber_value_type``, and implement ``_get_sber_value`` to return
    the current sensor value in the appropriate Sber format.

    Optionally reports ``battery_percentage`` when the HA entity has
    a ``battery`` or ``battery_level`` attribute.
    """

    LINKABLE_ROLES = SENSOR_LINK_ROLES

    ATTR_SPECS: ClassVar[tuple[AttrSpec, ...]] = (
        AttrSpec(
            field="_battery_level",
            attr_keys=("battery", "battery_level"),
            parser=_safe_int_parser,
            preserve_on_missing=True,
        ),
        AttrSpec(
            field="_signal_strength_raw",
            attr_keys=("signal_strength", "rssi", "linkquality"),
            parser=_safe_int_parser,
            preserve_on_missing=True,
        ),
    )

    _sber_value_key: str
    """Sber state key name (e.g., 'temperature', 'pir', 'water_leak')."""

    _sber_value_type: str
    """Sber value type string: 'INTEGER', 'BOOL', or 'ENUM'."""

    _unknown_is_online: bool = False
    """If True, HA ``unknown`` state is treated as online.

    Override to ``True`` in event-based sensors (binary_sensor) where
    ``unknown`` means "no event yet" rather than "device unreachable".
    """

    _TYPE_KEY_MAP: ClassVar[dict[str, str]] = {
        "INTEGER": "integer_value",
        "BOOL": "bool_value",
        "ENUM": "enum_value",
    }
    """Mapping from Sber value type to its JSON field name."""

    @property
    def _is_online(self) -> bool:
        """Check if sensor is online, respecting ``_unknown_is_online`` flag."""
        if self._unknown_is_online and self.state == "unknown":
            return True
        return super()._is_online

    @abstractmethod
    def _get_sber_value(self) -> int | bool | str:
        """Return the current sensor value formatted for the Sber protocol.

        Returns:
            The value matching ``_sber_value_type``:
            ``int`` for INTEGER, ``bool`` for BOOL, ``str`` for ENUM.
        """

    def __init__(self, category: str, entity_data: dict) -> None:
        """Initialize simple read-only sensor.

        Args:
            category: Sber device category string.
            entity_data: HA entity registry dict containing entity metadata.
        """
        super().__init__(category, entity_data)
        self._battery_level: int | None = None
        self._battery_low_linked: bool | None = None
        self._signal_strength_raw: int | None = None
        self._sensor_sensitive: str | None = None
        self._linked_entities: dict[str, str] = {}
        """Linked entity IDs by role: {role: entity_id}."""

    def update_linked_data(self, role: str, ha_state: dict) -> None:
        """Inject data from a linked entity into this sensor.

        Args:
            role: Link role name (battery, battery_low, signal_strength, humidity, temperature).
            ha_state: HA state dict with 'state' and 'attributes'.
        """
        state_val = ha_state.get("state")
        if state_val in (None, "unknown", "unavailable"):
            return
        if role == "battery":
            with contextlib.suppress(TypeError, ValueError):
                self._battery_level = int(float(state_val))
        elif role == "battery_low":
            self._battery_low_linked = state_val == "on"
        elif role == "signal_strength":
            with contextlib.suppress(TypeError, ValueError):
                self._signal_strength_raw = int(float(state_val))

    def fill_by_ha_state(self, ha_state: dict) -> None:
        """Parse HA state and update internal state including battery and signal.

        Battery (``battery`` / ``battery_level``) and signal strength
        (``signal_strength`` / ``rssi`` / ``linkquality``) are parsed via
        :class:`AttrSpec` with ``preserve_on_missing=True`` so that values
        injected by linked companion sensors via ``update_linked_data``
        are not clobbered on every primary state refresh.

        Sensor sensitivity (Aqara / Tuya) uses custom mapping logic that
        is not expressible through ``AttrSpec`` — kept imperative.

        Args:
            ha_state: HA state dict with 'state' and 'attributes' keys.
        """
        super().fill_by_ha_state(ha_state)
        attrs = ha_state.get("attributes", {})
        self._apply_attr_specs(attrs)
        self._sensor_sensitive = self._parse_sensitivity(attrs)

    @staticmethod
    def _parse_sensitivity(attrs: dict) -> str | None:
        """Parse sensor sensitivity with HA → Sber value mapping."""
        sensitivity = attrs.get("sensitivity") or attrs.get("motion_sensitivity")
        if sensitivity is None:
            return None
        s = str(sensitivity).lower()
        if s not in ("auto", "high", "low", "medium"):
            return None
        # Sber only accepts auto/high/low; map medium→auto
        return {"medium": "auto"}.get(s, s)

    def _build_sber_value_dict(self) -> dict:
        """Build the Sber value dict for the sensor's feature.

        Per Sber C2C specification, ``integer_value`` must be a string.

        Returns:
            Dict with 'type' and the corresponding value field.
        """
        value = self._get_sber_value()
        value_field = self._TYPE_KEY_MAP[self._sber_value_type]
        if self._sber_value_type == "INTEGER":
            value = str(value)
        return {"type": self._sber_value_type, value_field: value}

    def create_features_list(self) -> list[str]:
        """Return Sber feature list including the sensor's value key.

        Adds ``battery_percentage`` and ``battery_low_power`` if battery
        level is available. Adds ``signal_strength`` if signal data is present.

        Returns:
            List of Sber feature strings supported by this entity.
        """
        features = [*super().create_features_list(), self._sber_value_key]
        if self._battery_level is not None or self._battery_low_linked is not None:
            features.append("battery_percentage")
            features.append("battery_low_power")
        if self._signal_strength_raw is not None:
            features.append("signal_strength")
        if self._sensor_sensitive is not None:
            features.append("sensor_sensitive")
        return features

    def to_sber_current_state(self) -> dict[str, dict]:
        """Build Sber current state payload with online, value, battery, and signal keys.

        Returns:
            Dict mapping entity_id to its Sber state representation.
        """
        states = [
            make_state(SberFeature.ONLINE, make_bool_value(self._is_online)),
            {"key": self._sber_value_key, "value": self._build_sber_value_dict()},
        ]
        if self._battery_level is not None:
            states.append(make_state(SberFeature.BATTERY_PERCENTAGE, make_integer_value(self._battery_level)))
            # Use linked binary_sensor if available, otherwise derive from percentage
            battery_low = self._battery_low_linked if self._battery_low_linked is not None else self._battery_level < 20
            states.append(make_state(SberFeature.BATTERY_LOW_POWER, make_bool_value(battery_low)))
        elif self._battery_low_linked is not None:
            # Only linked battery_low binary_sensor, no percentage sensor
            states.append(make_state(SberFeature.BATTERY_LOW_POWER, make_bool_value(self._battery_low_linked)))
        if self._signal_strength_raw is not None:
            states.append(
                make_state(
                    SberFeature.SIGNAL_STRENGTH, make_enum_value(rssi_to_signal_strength(self._signal_strength_raw))
                )
            )
        if self._sensor_sensitive is not None:
            states.append(
                make_state(SberFeature.SENSOR_SENSITIVE, make_enum_value(self._sensor_sensitive))
            )
        return {self.entity_id: {"states": states}}

    def process_cmd(self, cmd_data: dict) -> list[dict]:
        """Process Sber command (no-op for read-only sensor).

        Args:
            cmd_data: Sber command dict (ignored).

        Returns:
            Empty list -- sensors do not accept commands.
        """
        return []
