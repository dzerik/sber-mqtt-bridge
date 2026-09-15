"""Every field of every setup and options form is explained to the user.

Quality-scale rule ``config-flow`` asks for a ``data_description`` on each
field: the label alone ("Settle delay (seconds)") does not say what the
value changes.  The forms are rendered here through the real flow manager,
so a field added to a schema without its description — in any of the
string files Home Assistant reads — fails the suite instead of shipping as
an unexplained input.  Every error and abort reason a flow can end with is
checked the same way: a reason without a translation reaches the user as a
raw key.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sber_mqtt_bridge.const import (
    CONF_EXPOSED_ENTITIES,
    CONF_SBER_BROKER,
    CONF_SBER_LOGIN,
    CONF_SBER_PASSWORD,
    CONF_SBER_PORT,
    DOMAIN,
)

COMPONENT_ROOT = Path(__file__).resolve().parents[2] / "custom_components" / "sber_mqtt_bridge"
"""Root of the integration, where the string files live."""

STRING_FILES = ("strings.json", "translations/en.json", "translations/ru.json")
"""Every file Home Assistant reads flow texts from."""

ENTRY_DATA = {
    CONF_SBER_LOGIN: "test_user",
    CONF_SBER_PASSWORD: "test_pass",
    CONF_SBER_BROKER: "broker.test",
    CONF_SBER_PORT: 8883,
}
"""Credentials of the config entry the options and reauth flows run on."""


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: Any) -> None:
    """Enable custom integrations in all tests."""
    return


def _load(name: str) -> dict[str, Any]:
    """Read one string file of the integration."""
    return json.loads((COMPONENT_ROOT / name).read_text(encoding="utf-8"))


def _fields(result: dict[str, Any]) -> list[str]:
    """Return the field names of a rendered form."""
    return [str(key) for key in result["data_schema"].schema]


def _assert_described(section: str, result: dict[str, Any]) -> None:
    """Fail unless every field of ``result`` has a label and a description in every string file."""
    assert result["type"] is FlowResultType.FORM, result
    step = result["step_id"]
    fields = _fields(result)
    assert fields, f"{step} renders no fields"
    for name in STRING_FILES:
        texts = _load(name)[section]["step"][step]
        missing_label = [field for field in fields if field not in texts.get("data", {})]
        missing_description = [field for field in fields if field not in texts.get("data_description", {})]
        assert missing_label == [], f"{name}: {section}.step.{step} has no data for {missing_label}"
        assert missing_description == [], (
            f"{name}: {section}.step.{step} has no data_description for {missing_description}"
        )


def _assert_translated(section: str, kind: str, reason: str) -> None:
    """Fail unless ``reason`` has a text under ``section.kind`` in every string file."""
    for name in STRING_FILES:
        assert reason in _load(name)[section].get(kind, {}), f"{name}: {section}.{kind}.{reason} is missing"


@pytest.fixture
def no_real_setup():
    """Keep entry setup and reloads from starting a real bridge."""
    with (
        patch("custom_components.sber_mqtt_bridge.async_setup_entry", return_value=True),
        patch("custom_components.sber_mqtt_bridge.async_unload_entry", return_value=True),
    ):
        yield


@pytest.mark.asyncio(loop_scope="function")
async def test_user_and_reauth_forms_describe_every_field(hass: HomeAssistant, no_real_setup) -> None:
    """The setup form and the reauthentication form explain all their inputs."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    _assert_described("config", result)

    entry = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA, unique_id="test_user")
    entry.add_to_hass(hass)
    result = await entry.start_reauth_flow(hass)
    _assert_described("config", result)


@pytest.mark.asyncio(loop_scope="function")
async def test_options_forms_describe_every_field(hass: HomeAssistant, no_real_setup) -> None:
    """Each options step with inputs explains them — both label pickers included.

    ``type_overrides`` is the one exception by construction: its fields are
    named after the user's entities (``override_light.kitchen``), so no
    static string can describe them; each carries its detected category
    and features as a per-field suffix instead.
    """
    ent_reg = er.async_get(hass)
    ent_reg.async_get_or_create("light", "demo", "hall", suggested_object_id="hall")
    entry = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA, options={CONF_EXPOSED_ENTITIES: []}, unique_id="u")
    entry.add_to_hass(hass)
    options = hass.config_entries.options

    async def advanced(step: str) -> dict[str, Any]:
        result = await options.async_init(entry.entry_id)
        _assert_described("options", result)
        result = await options.async_configure(result["flow_id"], {"action": "advanced"})
        return await options.async_configure(result["flow_id"], {"next_step_id": step})

    _assert_described("options", await advanced("device_sync"))

    menu = await advanced("select_entities_menu")
    _assert_described("options", menu)
    for mode in ("manual", "by_domain", "by_label"):
        result = await advanced("select_entities_menu")
        _assert_described("options", await options.async_configure(result["flow_id"], {"selection_mode": mode}))

    # The label picker has a second shape once a label exists.
    ent_reg.async_update_entity("light.hall", labels={"sber"})
    result = await advanced("select_entities_menu")
    labelled = await options.async_configure(result["flow_id"], {"selection_mode": "by_label"})
    assert labelled["data_schema"].schema["labels"].config["options"] != []
    _assert_described("options", labelled)


@pytest.mark.asyncio(loop_scope="function")
async def test_every_reason_a_flow_ends_with_is_translated(hass: HomeAssistant, no_real_setup) -> None:
    """Errors and aborts the flows actually produce all have user-facing text."""
    flows = hass.config_entries.flow
    with patch(
        "custom_components.sber_mqtt_bridge.config_flow._validate_sber_connection",
        side_effect=["cannot_connect", "invalid_auth"],
    ):
        first = await flows.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
        second = await flows.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
        late = await flows.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
        errors = [
            (await flows.async_configure(first["flow_id"], ENTRY_DATA))["errors"]["base"],
            (await flows.async_configure(first["flow_id"], ENTRY_DATA))["errors"]["base"],
        ]
        in_progress = await flows.async_configure(second["flow_id"], ENTRY_DATA)
        flows.async_abort(first["flow_id"])

        entry = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA, unique_id="test_user")
        entry.add_to_hass(hass)
        configured = await flows.async_configure(late["flow_id"], ENTRY_DATA)

    with patch(
        "custom_components.sber_mqtt_bridge.config_flow._validate_sber_connection",
        return_value=None,
    ):
        reauth = await entry.start_reauth_flow(hass)
        reauth = await flows.async_configure(reauth["flow_id"], {CONF_SBER_PASSWORD: "new"})
    await hass.async_block_till_done()

    options = hass.config_entries.options
    no_entities = await options.async_init(entry.entry_id)
    no_entities = await options.async_configure(no_entities["flow_id"], {"action": "advanced"})
    no_entities = await options.async_configure(no_entities["flow_id"], {"next_step_id": "type_overrides"})

    assert errors == ["cannot_connect", "invalid_auth"]
    aborts = [
        ("config", in_progress["reason"]),
        ("config", configured["reason"]),
        ("config", reauth["reason"]),
        ("options", no_entities["reason"]),
    ]
    assert aborts == [
        ("config", "already_in_progress"),
        ("config", "already_configured"),
        ("config", "reauth_successful"),
        ("options", "no_exposed_entities"),
    ]
    for reason in errors:
        _assert_translated("config", "error", reason)
    for section, reason in aborts:
        _assert_translated(section, "abort", reason)
