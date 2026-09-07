"""Sber reference vocabulary for the panel — human names of features.

The bridge speaks to the user in Sber's own identifiers
(``light_colour_temp``, ``hvac_air_flow_power``), because that is what
goes on the wire and what the documentation, the validator and the logs
all use.  Those identifiers are unreadable for anyone who has not read
the C2C reference — and the reference itself already carries a human
name for every single one of them, scraped into
:mod:`custom_components.sber_mqtt_bridge._generated.feature_labels`.

This module hands that vocabulary to the panel.

Why a command of its own, and not a field on ``status``:

* the table is **static** — it changes only when the spec snapshot is
  regenerated, so re-sending it with every status poll (the panel polls
  status continuously) would waste ~12 KB per poll forever;
* it is **large relative to its consumers** — three components need it,
  none of them needs it more than once per page load;
* it is **not per-entity** — folding it into ``devices`` would repeat
  the same strings once per device.

The panel fetches it once (``www/feature-labels.js``) and caches it for
the lifetime of the page.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from .._generated.feature_labels import FEATURE_ENUM_LABELS, FEATURE_TITLES_RU

_LOGGER = logging.getLogger(__name__)

LABEL_LANGUAGE = "ru"
"""Language the documented names are written in.

Sber publishes its C2C reference in Russian only, so every title here is
Russian and there is no English counterpart to ship.  The panel is told
the language explicitly instead of hard-coding ``"ru"`` on its side: a
future English reference would then start showing up without a frontend
change.
"""


@websocket_api.websocket_command(
    {
        vol.Required("type"): "sber_mqtt_bridge/feature_labels",
    }
)
@callback
def ws_feature_labels(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return the documented human names of Sber features and enum values.

    Needs no bridge: the tables are compiled from the spec snapshot at
    import time, so the panel can label a feature list even while the
    MQTT connection is down — which is exactly when a user is reading
    the validation tab.

    Args:
        hass: Home Assistant core instance (unused).
        connection: Active WebSocket connection.
        msg: Incoming command message.
    """
    connection.send_result(
        msg["id"],
        {
            "language": LABEL_LANGUAGE,
            "titles": FEATURE_TITLES_RU,
            "enum_labels": FEATURE_ENUM_LABELS,
        },
    )
