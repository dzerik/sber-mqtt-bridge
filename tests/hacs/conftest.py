"""Shared fixtures for sber_mqtt_bridge tests."""

import pytest

from custom_components.sber_mqtt_bridge.const import (
    CONF_SBER_BROKER,
    CONF_SBER_LOGIN,
    CONF_SBER_PASSWORD,
    CONF_SBER_PORT,
    DOMAIN,
)

MOCK_CONFIG = {
    CONF_SBER_LOGIN: "test_user",
    CONF_SBER_PASSWORD: "test_pass",
    CONF_SBER_BROKER: "mqtt-partners.iot.sberdevices.ru",
    CONF_SBER_PORT: 8883,
}

MOCK_OPTIONS = {
    "exposed_entities": [
        "light.living_room",
        "switch.kitchen",
        "sensor.temperature",
    ],
}


@pytest.fixture
def mock_config():
    """Return mock config entry data."""
    return MOCK_CONFIG.copy()


@pytest.fixture
def mock_options():
    """Return mock options data."""
    return MOCK_OPTIONS.copy()
