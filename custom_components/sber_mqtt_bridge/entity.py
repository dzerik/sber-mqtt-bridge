"""Base class of the bridge's own diagnostic entities.

They describe the bridge itself — connection, what Sber knows, errors — so
automations can react to a lost link.  They live on one service device and
are never offered for export to Sber (see the ``platform == DOMAIN`` filters
in the entity pickers).

They do not poll: the bridge pushes a notification whenever a value they
show may have changed (see :mod:`.status_notifier`, which throttles bursts),
and each entity writes its state only when what it shows really changed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.const import EntityCategory
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN
from .sber_protocol import VERSION

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

    from .sber_bridge import SberBridge


class SberBridgeDiagnosticEntity(Entity):
    """Diagnostic entity reading its value from the running bridge.

    Push-updated by the bridge; unavailable while the bridge is not running
    (before its start and after its stop), because its values are then no
    longer maintained.
    """

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_should_poll = False

    def __init__(self, bridge: SberBridge, entry: ConfigEntry, key: str) -> None:
        """Bind the entity to the bridge.

        Args:
            bridge: Running bridge the value is read from.
            entry: Config entry owning the bridge.
            key: Stable key; also the translation key of the entity name.
        """
        self._bridge = bridge
        self._attr_translation_key = key
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Sber MQTT Bridge",
            manufacturer="dzerik",
            model="HA → Sber Smart Home bridge",
            sw_version=VERSION,
            entry_type=DeviceEntryType.SERVICE,
        )
        self._shown: tuple[bool, object] | None = None
        """Availability and state last written, to skip writes that change nothing."""

    @property
    def available(self) -> bool:
        """Return whether the bridge is running and keeps the value current."""
        return self._bridge.is_running

    async def async_added_to_hass(self) -> None:
        """Subscribe to the bridge's status notifications."""
        self._shown = self._current()
        self.async_on_remove(self._bridge.add_status_listener(self._handle_bridge_status))

    def _current(self) -> tuple[bool, object]:
        """Return the availability and the state as they would be written now."""
        available = self.available
        return (available, self.state if available else None)

    @callback
    def _handle_bridge_status(self) -> None:
        """Write the state when the bridge reports a change that affects this entity."""
        current = self._current()
        if current == self._shown:
            return
        self._shown = current
        self.async_write_ha_state()
