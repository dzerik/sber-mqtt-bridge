"""Detection of other integrations that export Home Assistant devices to Sber.

Two bridges on one Sber account do not merely duplicate each other: each
publishes its own ``up/config`` to the same topic, and every publish
replaces the device list the other one declared — devices appear and
vanish in the Sber app depending on who published last.  On different
accounts they coexist, but the same HA entity may then show up twice in
the app.

The detector never touches the other integration.  It raises a Repairs
issue and feeds the panel banner, and re-evaluates whenever any config
entry is added, changed or removed.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.config_entries import SIGNAL_CONFIG_ENTRY_CHANGED, ConfigEntry, ConfigEntryChange
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .const import CONF_SBER_LOGIN, DOMAIN

_LOGGER = logging.getLogger(__name__)

CONFLICTING_INTEGRATIONS: dict[str, str | None] = {
    # TohaRG2/MQTT-Sber-HA — an independent HA → Sber MQTT bridge.
    "sber_mqtt": "mqtt_login",
}
"""Known HA → Sber bridges: domain → ``entry.data`` key holding the Sber login.

``None`` as the key means the login cannot be compared, and the conflict
is reported without claiming whether the account is shared."""

ISSUE_ID = "conflicting_integration"
"""Repairs issue id — one issue however many conflicting entries exist."""


@dataclass(frozen=True, slots=True)
class Conflict:
    """One config entry of another integration that exports devices to Sber."""

    domain: str
    """Domain of the other integration."""

    title: str
    """Title of its config entry, as the user sees it in HA."""

    same_account: bool | None
    """Whether it uses our Sber login; ``None`` when that cannot be told."""

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-serializable representation for the panel."""
        return {"domain": self.domain, "title": self.title, "same_account": self.same_account}


@callback
def detect_conflicts(hass: HomeAssistant, login: str | None) -> list[Conflict]:
    """List config entries of other integrations that export devices to Sber.

    Args:
        hass: Home Assistant core instance.
        login: Sber login of this bridge, to tell a shared account apart.

    Returns:
        One :class:`Conflict` per foreign config entry, in registry order.
    """
    conflicts: list[Conflict] = []
    for domain, login_key in CONFLICTING_INTEGRATIONS.items():
        for entry in hass.config_entries.async_entries(domain):
            same: bool | None = None
            if login_key is not None and login:
                same = entry.data.get(login_key) == login
            conflicts.append(Conflict(domain=domain, title=entry.title, same_account=same))
    return conflicts


@callback
def async_update_conflict_issue(hass: HomeAssistant, login: str | None) -> list[Conflict]:
    """Create, update or delete the Repairs issue to match the current state.

    Args:
        hass: Home Assistant core instance.
        login: Sber login of this bridge.

    Returns:
        The conflicts found (empty when there are none).
    """
    conflicts = detect_conflicts(hass, login)
    if not conflicts:
        ir.async_delete_issue(hass, DOMAIN, ISSUE_ID)
        return conflicts
    same_account = any(c.same_account for c in conflicts)
    ir.async_create_issue(
        hass,
        DOMAIN,
        ISSUE_ID,
        is_fixable=False,
        severity=ir.IssueSeverity.ERROR if same_account else ir.IssueSeverity.WARNING,
        translation_key="conflicting_integration_same_account" if same_account else "conflicting_integration",
        translation_placeholders={"integrations": ", ".join(f"{c.title} ({c.domain})" for c in conflicts)},
    )
    return conflicts


@callback
def async_track_conflicts(hass: HomeAssistant, entry: ConfigEntry) -> Callable[[], None]:
    """Keep the conflict issue current for the lifetime of ``entry``.

    Args:
        hass: Home Assistant core instance.
        entry: This bridge's config entry.

    Returns:
        Callback for ``entry.async_on_unload``: stops tracking and removes
        the issue, which describes a bridge that is no longer running.
    """
    login = entry.data.get(CONF_SBER_LOGIN)
    async_update_conflict_issue(hass, login)

    @callback
    def _on_entry_changed(_change: ConfigEntryChange, changed: ConfigEntry) -> None:
        if changed.domain in CONFLICTING_INTEGRATIONS:
            async_update_conflict_issue(hass, login)

    unsub = async_dispatcher_connect(hass, SIGNAL_CONFIG_ENTRY_CHANGED, _on_entry_changed)

    @callback
    def _stop() -> None:
        unsub()
        ir.async_delete_issue(hass, DOMAIN, ISSUE_ID)

    return _stop
