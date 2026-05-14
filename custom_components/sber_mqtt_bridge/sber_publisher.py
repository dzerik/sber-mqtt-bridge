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

    async def publish_command_echo(self, devices: dict[str, dict]) -> None:
        """Publish immediate echo of a received Sber command as fast ack.

        Args:
            devices: ``devices`` dict from the incoming Sber command.

        Side effects mirror the original ``SberBridge._publish_command_echo``:
        bumps ``messages_sent`` on success, logs the outbound message in
        the DevTools ring buffer, and records into the trace / diff /
        validation collectors.
        """
        bridge = self._bridge
        if not bridge._connected or bridge._mqtt_service is None:
            return

        echo_devices: dict[str, dict] = {}
        for entity_id, cmd_data in devices.items():
            entity = bridge._entities.get(entity_id)
            if entity is None:
                continue
            try:
                current = entity.to_sber_current_state().get(entity_id, {"states": []})
            except (TypeError, ValueError, KeyError, AttributeError):
                _LOGGER.exception("Building command-echo baseline failed for %s", entity_id)
                continue
            baseline_states: list[dict] = list(current.get("states", []))
            cmd_states_by_key: dict[str, dict] = {
                s.get("key"): s for s in cmd_data.get("states", []) if s.get("key")
            }
            merged: list[dict] = []
            overridden: set[str] = set()
            for state in baseline_states:
                key = state.get("key")
                if key in cmd_states_by_key:
                    merged.append(cmd_states_by_key[key])
                    overridden.add(key)
                else:
                    merged.append(state)
            for key, state in cmd_states_by_key.items():
                if key not in overridden:
                    merged.append(state)
            echo_devices[entity_id] = {"states": merged}

        if not echo_devices:
            return

        payload = json.dumps({"devices": echo_devices})
        topic = f"{bridge._root_topic}/up/status"
        try:
            await bridge._mqtt_service.publish(topic, payload)
        except (aiomqtt.MqttError, RuntimeError):
            bridge._stats.publish_errors += 1
            _LOGGER.exception("Error publishing command echo to Sber")
            return
        bridge._stats.messages_sent += 1
        _LOGGER.debug("Published command echo for %s: %s", list(echo_devices), payload)
        bridge._log_message("out", topic, payload)

        for eid in echo_devices:
            bridge._trace_collector.record_publish(eid, topic, payload)
        try:
            bridge._diff_collector.record_publish_payload(payload, topic=topic)
        except Exception:  # pragma: no cover — must never break publish
            _LOGGER.exception("DiffCollector.record_publish_payload failed (echo)")
        try:
            categories = {eid: ent.category for eid, ent in bridge._entities.items()}
            declared = {eid: ent.get_final_features_list() for eid, ent in bridge._entities.items()}
            bridge._validation_collector.record_publish_payload(
                payload,
                categories=categories,
                declared_features=declared,
            )
        except Exception:  # pragma: no cover — must never break publish
            _LOGGER.exception("ValidationCollector.record_publish_payload failed (echo)")
