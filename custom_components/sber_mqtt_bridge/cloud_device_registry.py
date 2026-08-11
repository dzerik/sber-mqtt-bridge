"""Tracks which devices the Sber cloud currently knows about.

Sber reads every ``up/config`` as the complete device list, so publishing one
that omits a device the cloud already has makes it drop that device and
re-register it as new on the next payload — losing the room the user assigned
(issue #44).

There is no way to *ask* the cloud what it holds: the protocol is one-way for
device descriptors, and ``partner_meta`` — the vendor-specific field we write
into — is never echoed back.  What the cloud does tell us is the device id
list inside every ``down/status_request``.  Together with the ids of our own
successful publishes that is enough to maintain a reliable picture, which is
what this registry stores.

The set is persisted in ``ConfigEntry.options`` so it survives a restart —
precisely the moment it matters, since the whole failure mode is "HA restarted
and republished a shorter list".
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

OPTIONS_KEY = "cloud_known_devices"
"""``ConfigEntry.options`` key holding the sorted list of known device ids."""

HUB_DEVICE_ID = "root"
"""The hub is always present and is never a real entity — never tracked."""


class CloudDeviceRegistry:
    """Remember which device ids the Sber cloud is holding for us."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Load the persisted set from the config entry.

        Args:
            hass: Home Assistant instance (used to persist).
            entry: Config entry whose options carry the persisted set.
        """
        self._hass = hass
        self._entry = entry
        stored = entry.options.get(OPTIONS_KEY) or []
        self._known: set[str] = {item for item in stored if isinstance(item, str)}
        self._stopped = False

    @property
    def known(self) -> frozenset[str]:
        """Device ids the cloud is believed to hold right now."""
        return frozenset(self._known)

    def note_published(self, entity_ids: Iterable[str]) -> None:
        """Record the ids of a successfully published config.

        Everything in that payload is now registered cloud-side; everything
        previously known but absent from it has just been dropped by the
        cloud, so the registry mirrors the payload exactly.
        """
        published = {entity_id for entity_id in entity_ids if entity_id != HUB_DEVICE_ID}
        if published == self._known:
            return
        gone = self._known - published
        if gone:
            _LOGGER.debug("Cloud no longer holds %d device(s): %s", len(gone), ", ".join(sorted(gone)))
        self._known = published
        self._persist()

    def note_cloud_reported(self, entity_ids: Iterable[str]) -> None:
        """Merge ids the cloud named in a ``status_request``.

        The cloud only asks about devices it knows, so this is direct
        evidence — it can reveal devices this HA instance has not published
        in the current session (for example after a restart).
        """
        reported = {entity_id for entity_id in entity_ids if entity_id != HUB_DEVICE_ID}
        if not reported or reported <= self._known:
            return
        self._known |= reported
        self._persist()

    def forget(self, entity_ids: Iterable[str]) -> None:
        """Drop ids the user removed from the bridge configuration.

        Without this a device the user deliberately un-exposed would block
        every future publish, since it is known to the cloud but will never
        become ready again.
        """
        removed = set(entity_ids) & self._known
        if not removed:
            return
        self._known -= removed
        self._persist()

    def shutdown(self) -> None:
        """Stop persisting (bridge unload)."""
        self._stopped = True

    def _persist(self) -> None:
        """Write the set back into ``ConfigEntry.options``."""
        if self._stopped:
            return
        new_options = {**self._entry.options, OPTIONS_KEY: sorted(self._known)}
        self._hass.config_entries.async_update_entry(self._entry, options=new_options)
