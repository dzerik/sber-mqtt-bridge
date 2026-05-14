"""Regression tests for payload size limits on raw / replay WS commands."""

from __future__ import annotations

import pytest
import voluptuous as vol

from custom_components.sber_mqtt_bridge.const import (
    CONF_MAX_MQTT_PAYLOAD,
    SETTINGS_DEFAULTS,
)

_MAX = SETTINGS_DEFAULTS[CONF_MAX_MQTT_PAYLOAD]
_OVERSIZE = "x" * (_MAX + 1)
_OK = "x" * _MAX


# ---------------------------------------------------------------------------
# raw.py — send_raw_config
# ---------------------------------------------------------------------------


def test_raw_send_config_rejects_oversize_payload() -> None:
    """ws_send_raw_config schema must reject payloads above the cap."""
    from custom_components.sber_mqtt_bridge.websocket_api.raw import ws_send_raw_config

    schema = ws_send_raw_config._ws_schema  # type: ignore[attr-defined]
    with pytest.raises(vol.Invalid):
        schema({"id": 1, "type": "sber_mqtt_bridge/send_raw_config", "payload": _OVERSIZE})


def test_raw_send_config_accepts_payload_at_limit() -> None:
    """ws_send_raw_config schema must accept payloads exactly at the cap."""
    from custom_components.sber_mqtt_bridge.websocket_api.raw import ws_send_raw_config

    schema = ws_send_raw_config._ws_schema  # type: ignore[attr-defined]
    result = schema({"id": 1, "type": "sber_mqtt_bridge/send_raw_config", "payload": _OK})
    assert result["payload"] == _OK


# ---------------------------------------------------------------------------
# raw.py — send_raw_state
# ---------------------------------------------------------------------------


def test_raw_send_state_rejects_oversize_payload() -> None:
    """ws_send_raw_state schema must reject payloads above the cap."""
    from custom_components.sber_mqtt_bridge.websocket_api.raw import ws_send_raw_state

    schema = ws_send_raw_state._ws_schema  # type: ignore[attr-defined]
    with pytest.raises(vol.Invalid):
        schema({"id": 1, "type": "sber_mqtt_bridge/send_raw_state", "payload": _OVERSIZE})


def test_raw_send_state_accepts_payload_at_limit() -> None:
    """ws_send_raw_state schema must accept payloads exactly at the cap."""
    from custom_components.sber_mqtt_bridge.websocket_api.raw import ws_send_raw_state

    schema = ws_send_raw_state._ws_schema  # type: ignore[attr-defined]
    result = schema({"id": 1, "type": "sber_mqtt_bridge/send_raw_state", "payload": _OK})
    assert result["payload"] == _OK


# ---------------------------------------------------------------------------
# replay.py — inject_sber_message
# ---------------------------------------------------------------------------


def test_replay_inject_rejects_oversize_payload() -> None:
    """ws_inject_sber_message must reject oversize payloads."""
    from custom_components.sber_mqtt_bridge.websocket_api.replay import ws_inject_sber_message

    schema = ws_inject_sber_message._ws_schema  # type: ignore[attr-defined]
    with pytest.raises(vol.Invalid):
        schema(
            {
                "id": 1,
                "type": "sber_mqtt_bridge/inject_sber_message",
                "topic": "sberdevices/v1/test/down/commands",
                "payload": _OVERSIZE,
            }
        )


def test_replay_inject_accepts_payload_at_limit() -> None:
    """ws_inject_sber_message must accept payloads exactly at the cap."""
    from custom_components.sber_mqtt_bridge.websocket_api.replay import ws_inject_sber_message

    schema = ws_inject_sber_message._ws_schema  # type: ignore[attr-defined]
    result = schema(
        {
            "id": 1,
            "type": "sber_mqtt_bridge/inject_sber_message",
            "topic": "sberdevices/v1/test/down/commands",
            "payload": _OK,
        }
    )
    assert result["payload"] == _OK


# ---------------------------------------------------------------------------
# replay.py — replay_message
# ---------------------------------------------------------------------------


def test_replay_replay_rejects_oversize_payload() -> None:
    """ws_replay_message must reject oversize payloads."""
    from custom_components.sber_mqtt_bridge.websocket_api.replay import ws_replay_message

    schema = ws_replay_message._ws_schema  # type: ignore[attr-defined]
    with pytest.raises(vol.Invalid):
        schema(
            {
                "id": 1,
                "type": "sber_mqtt_bridge/replay_message",
                "topic": "sberdevices/v1/test/down/commands",
                "payload": _OVERSIZE,
            }
        )


def test_replay_replay_accepts_payload_at_limit() -> None:
    """ws_replay_message must accept payloads exactly at the cap."""
    from custom_components.sber_mqtt_bridge.websocket_api.replay import ws_replay_message

    schema = ws_replay_message._ws_schema  # type: ignore[attr-defined]
    result = schema(
        {
            "id": 1,
            "type": "sber_mqtt_bridge/replay_message",
            "topic": "sberdevices/v1/test/down/commands",
            "payload": _OK,
        }
    )
    assert result["payload"] == _OK
