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

Two properties of that persistence are deliberate and load-bearing (issue
#57, where the panel reported "known to Sber: 0" on a working bridge):

* every write **merges** into the live ``entry.options`` instead of a
  snapshot taken earlier, so a concurrent writer cannot drop the key — and,
  symmetrically, this registry cannot drop anybody else's;
* the in-memory set is the source of truth while the bridge runs, so even a
  foreign write that did lose the key is repaired by the next publish.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from homeassistant.config_entries import ConfigEntry, UnknownEntry
from homeassistant.core import HomeAssistant

from .const import CONF_EXPOSED_ENTITIES

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

        One case is *not* mirrored: a payload carrying no device at all
        while the registry holds some.  Cloud-side that means "the hub has
        nothing", but bridge-side it means the entity set failed to load —
        the very degradation this registry exists to survive.  Believing it
        would erase the floor that keeps the next publish from dropping
        devices the cloud holds (issue #44) and would blank the panel's
        "known to Sber" column on a bridge that is working (issue #57), so
        the memory is kept and the anomaly logged instead.
        """
        published = {entity_id for entity_id in entity_ids if entity_id != HUB_DEVICE_ID}
        if published == self._known:
            return
        if not published and self._known:
            _LOGGER.warning(
                "Ignoring a config publish with no devices: keeping the %d device(s) the cloud is known to hold. "
                "An empty device list means the exposed entities failed to load, not that Sber dropped them.",
                len(self._known),
            )
            return
        gone = self._known - published
        if gone:
            _LOGGER.debug("Cloud no longer holds %d device(s): %s", len(gone), ", ".join(sorted(gone)))
        self._known = published
        self._persist()

    def note_cloud_reported(self, entity_ids: Iterable[str]) -> None:
        """Merge ids the cloud named in a ``status_request`` or a command.

        The cloud only asks about — and only commands — devices it knows,
        so this is direct evidence: it can reveal devices this HA instance
        has not published in the current session (for example after a
        restart).
        """
        reported = {entity_id for entity_id in entity_ids if entity_id != HUB_DEVICE_ID}
        if not reported or reported <= self._known:
            return
        self._known |= reported
        self._persist()

    def note_cloud_active(self, entity_ids: Iterable[str]) -> None:
        """Seed the registry from a ``status_request`` that named no device.

        "Give me the state of everything" carries no per-device
        information, but it is still proof that the cloud has devices of
        ours — it does not poll a hub it holds nothing for.  Until now that
        proof was discarded: the session marked every entity acknowledged
        and the persistent registry learned nothing, so a bridge whose
        config publish had failed reported "known to Sber: 0" for its whole
        life with no way back short of a restart (issue #57).

        Used as a *seed*, never as an update: while the registry already
        holds ids the publish path put there, that record is per-device and
        strictly better, and overwriting it with "everything exposed" would
        quietly re-mark devices Sber silently rejected as accepted — the
        exact signal :attr:`~sber_bridge.SberBridge.never_confirmed_entities`
        raises the repair issue on.

        Args:
            entity_ids: Entities that would answer such a request — the
                exposed ones that have state, and therefore the only ones
                that can ever have reached the cloud.
        """
        if self._known:
            return
        self.note_cloud_reported(entity_ids)

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
        """Mark the owning bridge as being torn down.

        This does **not** stop persisting.  A config publish started before
        the unload can finish after it — every panel edit reloads the entry,
        so the window opens routinely — and dropping its result left the
        next start believing the cloud held nothing (issue #57).  Writes
        that arrive once the entry itself is gone are handled in
        :meth:`_persist`, which is the only case where there is genuinely
        nothing to write into.
        """
        self._stopped = True

    def _persist(self) -> None:
        """Write the set back into ``ConfigEntry.options``.

        Merges into the *live* options mapping rather than a snapshot, so
        concurrent writers keep their keys and keep ours.

        After :meth:`shutdown` the write is additionally filtered against
        the entity list the *live* options carry.  This registry object
        belongs to a bridge that is being torn down, and its set was
        captured before the edit that caused the teardown: a publish that
        was already in flight when the user un-exposed a device would
        otherwise write that device back in, resurrecting it behind the
        successor bridge's back.  The stale id then sits in the options
        for good — invisible until the user re-exposes that entity, at
        which point it is displayed as cloud-known on no evidence and
        becomes a floor the publish gate waits on.
        """
        to_persist = self._known
        if self._stopped:
            still_exposed = set(self._entry.options.get(CONF_EXPOSED_ENTITIES) or ())
            to_persist = {eid for eid in to_persist if eid in still_exposed}
        new_options = {**self._entry.options, OPTIONS_KEY: sorted(to_persist)}
        try:
            self._hass.config_entries.async_update_entry(self._entry, options=new_options)
        except UnknownEntry:
            # The config entry has been removed (integration deleted): there
            # is no store left to remember anything in, and that is fine.
            _LOGGER.debug("Config entry gone — cloud device registry not persisted")
            return
        if self._stopped:
            _LOGGER.debug("Persisted %d cloud-known device(s) after bridge shutdown", len(to_persist))
