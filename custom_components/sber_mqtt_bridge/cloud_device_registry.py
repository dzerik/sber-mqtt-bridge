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

The same knowledge answers a second question, which is why
:class:`ModelIdentityMigration` lives here: whether this installation has
devices in the cloud at all, and therefore whether a change in how we name
device *models* is something the user has to be told about.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from homeassistant.components import persistent_notification
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


MODEL_IDENTITY_REVISION = 2
"""Generation of the ``model.id`` formula this code publishes under.

Bumped whenever :meth:`~.devices.base_entity.BaseEntity._build_model_descriptor`
starts producing a different id for the same device.  Revision 1 is
everything up to and including 1.50.0; revision 2 adds the hardware name
to the capability digest and stops declaring functions Sber does not
document for the category, both of which move the digest.

It marks changes to the *formula*, not to the data Home Assistant feeds
it: a device whose ``manufacturer`` / ``model`` an integration rewrites
gets a new id without a revision bump and therefore without a notice —
see :meth:`~.devices.base_entity.BaseEntity._capability_digest`.
"""

OPTIONS_MODEL_REVISION_KEY = "model_identity_revision"
"""``ConfigEntry.options`` key holding the revision this entry last published under."""

MIGRATION_NOTIFICATION_ID = "sber_mqtt_bridge_model_identity"
"""Base persistent-notification id — see :func:`migration_notification_id`."""


def migration_notification_id(entry: ConfigEntry) -> str:
    """Return the notification id for one config entry.

    Two Sber accounts mean two config entries, each with its own device
    registry and its own device count.  A single shared id let the second
    entry's notice overwrite the first one's, leaving the user with a
    number that describes only half of their installation.

    Args:
        entry: Config entry the notice is about.

    Returns:
        Notification id unique to that entry.
    """
    return f"{MIGRATION_NOTIFICATION_ID}_{entry.entry_id}"


_MIGRATION_TITLE = "Sber Bridge: изменились описания моделей устройств"

_MIGRATION_MESSAGE = """\
Мост исправил описания устройств, которые отправляет в облако Сбера.

**Что изменилось**

* Из моделей убраны функции, которых нет в документации их категории. Это
  `on_off` у домофона; `tamper_alarm` (сигнал о вскрытии) у датчиков дыма,
  газа, движения и протечки; `alarm_mute` (отключение сирены) у датчика
  протечки; `sensor_sensitive` (чувствительность) у датчиков дыма и
  протечки; `hvac_humidity_set` (целевая влажность) у бойлера,
  обогревателя, радиатора и тёплого пола. Модель с чужой функцией облако
  вправе отбросить целиком, и устройство просто не появится в приложении.
  Если вы пользовались какой-то из этих функций через приложение Сбера, в
  Home Assistant она остаётся на месте.
* У ламп и светодиодных лент убрана пустая запись о допустимых значениях
  цвета: она ничего не задавала, а документация Сбера разрешает такие
  записи только для чисел и списков значений.
* В идентификатор модели теперь входят производитель и название железа, а
  в описание модели — они же вместо имени конкретного устройства. Раньше
  два разных датчика получали один идентификатор, и в приложении Сбера их
  описания смешивались.

**Что будет дальше**

При ближайшей публикации конфигурации Сбер заведёт для ваших устройств
({count} шт.) модели заново. Сами устройства, их имена и сценарии остаются
на месте, повторное сопряжение не требуется.

**Что может потребоваться от вас**

Если у части устройств в приложении Сбера сбросится назначенная комната,
назначьте её заново — это разовая операция. Уведомление можно закрыть.
"""


class ModelIdentityMigration:
    """Tell the user, once, that device models are re-registering.

    The bridge names a Sber *model* by a digest of what the device can
    do (see
    :meth:`~.devices.base_entity.BaseEntity._capability_digest`).  When
    that formula changes, every device gets a new ``model.id`` and the
    cloud registers new models for them on the next config publish.

    **Why the migration is a notice and not a compatibility shim.**
    Keeping the old id would keep the old model: the cloud caches a
    model by its id and does not pick up new content published under an
    unchanged one — the project has paid for that once already (1.39.6b3,
    where a stale cached dependency made every colour command bounce).
    Pinning the id would therefore preserve exactly the broken
    descriptors this release exists to fix, and it would need a frozen
    copy of the old feature logic to reproduce ids we never stored.  So
    the models are re-registered and the user is told what to expect.

    Whether re-registering a model also resets the room a user assigned
    to a device is **not established**: 1.44.0 moved every ``model.id``
    for everybody and no such regression was reported, and the protocol
    gives a vendor no way to set a room other than the ``room`` field we
    already send.  The notice says "if a room resets" rather than
    promising either outcome.

    A fresh installation is silent: it has nothing registered in the
    cloud, so there is nothing to re-register and nothing to warn about.
    An installation older than the cloud registry itself is neither
    warned nor stamped — see :attr:`registry_has_not_answered_yet`.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, registry: CloudDeviceRegistry) -> None:
        """Bind the migration to one config entry.

        Args:
            hass: Home Assistant instance (used to persist and to notify).
            entry: Config entry carrying the stored revision.
            registry: Registry that knows whether the cloud holds devices
                of ours.
        """
        self._hass = hass
        self._entry = entry
        self._registry = registry

    @property
    def stored_revision(self) -> int | None:
        """Revision this entry last published under, or ``None`` if never stamped."""
        stored = self._entry.options.get(OPTIONS_MODEL_REVISION_KEY)
        return stored if isinstance(stored, int) and not isinstance(stored, bool) else None

    @property
    def is_up_to_date(self) -> bool:
        """Whether the entry has already been stamped with the current revision."""
        return self.stored_revision == MODEL_IDENTITY_REVISION

    @property
    def affects_cloud_devices(self) -> bool:
        """Whether the cloud holds devices that will be re-registered.

        An entry with an empty registry is a fresh installation, a bridge
        that never managed to publish, or an installation that predates
        the registry itself; the first two have no model of ours
        cloud-side to replace, and the third is handled by
        :attr:`registry_has_not_answered_yet` instead of here.
        """
        return bool(self._registry.known)

    @property
    def registry_has_not_answered_yet(self) -> bool:
        """Whether this entry is too old for its empty registry to mean anything.

        The cloud device registry (``cloud_known_devices``) arrived in
        1.45 (#44 / #49).  An installation upgrading from anything older
        reaches the first ``async_setup_entry`` with devices in the cloud
        and an options mapping that has no such key at all — the registry
        reads as empty, :attr:`affects_cloud_devices` says "nothing to
        re-register", the entry is stamped, and by the time the first
        publish fills the registry there is nobody left to notify.

        Absence of the key together with a non-empty exposed-entity list
        separates that case from a fresh installation, which reaches its
        first setup straight out of the config flow with nothing exposed
        yet.  A bridge in this state is left unstamped, so the decision
        is retried on the next setup — the panel reloads the entry on
        every edit, and a restart does the same — by which point the
        registry can answer for itself.

        Returns:
            True while the verdict must be postponed.
        """
        if self._registry.known or OPTIONS_KEY in self._entry.options:
            return False
        return bool(self._entry.options.get(CONF_EXPOSED_ENTITIES))

    def async_run(self) -> bool:
        """Notify if needed, then stamp the entry with the current revision.

        Idempotent: once stamped, later calls do nothing, so the notice
        survives exactly one restart's worth of attention and does not
        come back on every reload.  The one case that is *not* stamped is
        :attr:`registry_has_not_answered_yet`, where stamping would spend
        the single notice on an installation that cannot yet say whether
        it needs one.

        Returns:
            True if the user was notified, False otherwise.
        """
        if self.is_up_to_date:
            return False
        if self.registry_has_not_answered_yet:
            _LOGGER.debug(
                "Model identity revision left unstamped: this entry predates the cloud device registry, "
                "so whether the cloud holds devices of ours is not known until the first config publish"
            )
            return False
        notified = self.affects_cloud_devices
        if notified:
            persistent_notification.async_create(
                self._hass,
                _MIGRATION_MESSAGE.format(count=len(self._registry.known)),
                title=_MIGRATION_TITLE,
                notification_id=migration_notification_id(self._entry),
            )
            _LOGGER.info(
                "Model identity revision %s → %s: %d cloud device(s) will re-register their models",
                self.stored_revision,
                MODEL_IDENTITY_REVISION,
                len(self._registry.known),
            )
        else:
            _LOGGER.debug(
                "Model identity revision stamped as %s without a notice: the cloud holds no devices of ours",
                MODEL_IDENTITY_REVISION,
            )
        self._stamp()
        return notified

    def _stamp(self) -> None:
        """Write the current revision into ``ConfigEntry.options``.

        Merges into the live options mapping for the same reason
        :meth:`CloudDeviceRegistry._persist` does: a concurrent writer
        must not lose its key, and must not drop ours.
        """
        new_options = {**self._entry.options, OPTIONS_MODEL_REVISION_KEY: MODEL_IDENTITY_REVISION}
        try:
            self._hass.config_entries.async_update_entry(self._entry, options=new_options)
        except UnknownEntry:
            _LOGGER.debug("Config entry gone — model identity revision not persisted")
