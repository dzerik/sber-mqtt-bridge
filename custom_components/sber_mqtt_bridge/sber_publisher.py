"""Sber Smart Home MQTT publish coordinator.

Owns the three Sber publish flows extracted from :class:`SberBridge`:

* :meth:`publish_states` — outbound state updates on ``up/status``.
* :meth:`publish_config` — outbound device descriptor on ``up/config``.
* :meth:`publish_command_echo` — fast ack echo for incoming Sber commands.

Each method retains the side-effects of its predecessor in
``sber_bridge.SberBridge`` (DevTools instrumentation, ack audit hook,
stats bump, dirty-flag bookkeeping) — the bridge keeps thin delegators
so existing call sites remain untouched.
"""

from __future__ import annotations

import json
import logging
import time
from typing import TYPE_CHECKING

import aiomqtt

from .const import CONF_HUB_AUTO_PARENT
from .sber_protocol import (
    build_devices_list_json,
    build_states_list_json,
)

if TYPE_CHECKING:
    from .sber_bridge import SberBridge

_LOGGER = logging.getLogger(__name__)


class SberPublisher:
    """Publish coordinator for the Sber MQTT bridge.

    Constructed with a reference to its parent :class:`SberBridge`; reads
    shared state directly (entities, settings, MQTT service, collectors).
    The coupling is deliberate and one-way — the bridge does not call
    back into the publisher except via the publish methods themselves.
    """

    def __init__(self, bridge: SberBridge) -> None:
        """Bind the publisher to its parent bridge.

        Args:
            bridge: The bridge instance whose state this publisher
                reads (entities, settings, MQTT service).
        """
        self._bridge = bridge
        self._last_config_publish_time: float | None = None
        """Monotonic timestamp of the most recent successful config publish."""

    @property
    def last_config_publish_time(self) -> float | None:
        """Return the monotonic timestamp of the last successful config publish."""
        return self._last_config_publish_time
