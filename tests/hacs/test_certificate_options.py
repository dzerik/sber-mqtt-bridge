"""Certificate recovery through Options Flow without a loaded integration."""

from dataclasses import replace
from unittest.mock import patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.data_entry_flow import FlowResultType
from test_config_flow_options import _add_entry, _open_advanced_step
from test_config_flow_options import no_real_setup as no_real_setup

from custom_components.sber_mqtt_bridge.ssl_utils import ServerCertificate

CERTIFICATE = ServerCertificate(
    pem="reviewed PEM",
    fingerprint="AA:BB",
    subject="broker subject",
    issuer="private CA",
    not_before="2026-01-01",
    not_after="2028-01-01",
    self_signed=False,
    valid_now=True,
    hostname_matches=True,
)
OPTIONS = {"exposed_entities": ["switch.lamp"], "entity_links": {"switch.lamp": {"sensor": "sensor.power"}}}
INSPECT = "custom_components.sber_mqtt_bridge.config_flow.inspect_server_certificate"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integration flows."""


async def test_review_then_trust_preserves_unloaded_entry_options(hass, no_real_setup):
    entry = _add_entry(hass, OPTIONS)
    assert entry.state is not ConfigEntryState.LOADED
    with patch(INSPECT, return_value=CERTIFICATE) as inspect:
        result = await _open_advanced_step(hass, entry, "broker_certificate")
        assert result["type"] is FlowResultType.FORM
        assert result["description_placeholders"]["fingerprint"] == "AA:BB"
        assert result["description_placeholders"]["subject"] == "broker subject"
        assert dict(entry.options) == OPTIONS
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"action": "trust", "confirm": True}
        )
        assert inspect.call_count == 2, "confirm must re-fetch the certificate"
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert dict(entry.options) == {**OPTIONS, "sber_trusted_certificate": CERTIFICATE.pem, "sber_verify_ssl": True}
    await hass.async_block_till_done()


async def test_trust_requires_explicit_confirmation(hass, no_real_setup):
    entry = _add_entry(hass, OPTIONS)
    with patch(INSPECT, return_value=CERTIFICATE):
        result = await _open_advanced_step(hass, entry, "broker_certificate")
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"action": "trust", "confirm": False}
        )
    assert result["errors"] == {"confirm": "certificate_confirmation_required"}
    assert dict(entry.options) == OPTIONS


async def test_rotation_requires_review_and_new_confirmation(hass, no_real_setup):
    entry = _add_entry(hass, OPTIONS)
    rotated = replace(CERTIFICATE, fingerprint="CC:DD", pem="rotated PEM")
    with patch(INSPECT, side_effect=[CERTIFICATE, rotated, rotated]):
        result = await _open_advanced_step(hass, entry, "broker_certificate")
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"action": "trust", "confirm": True}
        )
        assert result["errors"] == {"base": "certificate_changed"}
        assert result["description_placeholders"]["fingerprint"] == "CC:DD"
        assert dict(entry.options) == OPTIONS
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"action": "trust", "confirm": True}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["sber_trusted_certificate"] == "rotated PEM"
    await hass.async_block_till_done()


@pytest.mark.parametrize(
    "certificate", [replace(CERTIFICATE, valid_now=False), replace(CERTIFICATE, hostname_matches=False)]
)
async def test_invalid_certificate_cannot_be_trusted(hass, no_real_setup, certificate):
    entry = _add_entry(hass, OPTIONS)
    with patch(INSPECT, return_value=certificate):
        result = await _open_advanced_step(hass, entry, "broker_certificate")
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"action": "trust", "confirm": True}
        )
    assert result["errors"] == {"base": "certificate_invalid"}
    assert dict(entry.options) == OPTIONS


async def test_remove_trust_works_even_when_broker_is_unreachable(hass, no_real_setup):
    entry = _add_entry(hass, {**OPTIONS, "sber_trusted_certificate": CERTIFICATE.pem})
    with patch(INSPECT, side_effect=OSError("network down")) as inspect:
        result = await _open_advanced_step(hass, entry, "broker_certificate")
        assert result["errors"] == {"base": "certificate_unavailable"}
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"action": "remove", "confirm": True}
        )
        assert inspect.call_count == 1
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["sber_trusted_certificate"] is None
    assert entry.options["sber_verify_ssl"] is True
    assert all(entry.options[key] == value for key, value in OPTIONS.items())
    await hass.async_block_till_done()
