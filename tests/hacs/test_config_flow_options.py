"""Regression tests for the Options Flow and the UI-level registries.

The Options Flow (``SberMqttBridgeOptionsFlow``) is the fallback path for
users who do not use the sidebar panel.  It had zero test coverage, which
let three classes of defect through unnoticed:

* option keys wiped on save (``entity_type_overrides`` / ``entity_links`` /
  bridge settings) because every step called ``async_create_entry`` with
  only the key it edited;
* hand-written registries (``SUPPORTED_DOMAINS``, category labels,
  ``DOMAIN_PRIORITY``, ``DOMAIN_LABELS``) drifting away from
  ``CATEGORY_DOMAIN_MAP`` — the ``lock`` domain was missing everywhere, so
  intercoms could not be exported at all;
* category labels degrading to raw ids.

Every test here is written to fail if the corresponding behaviour is
reverted.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sber_mqtt_bridge import config_flow as cf
from custom_components.sber_mqtt_bridge.const import (
    CONF_CONFIG_MAX_WAIT,
    CONF_CONFIG_SETTLE_DELAY,
    CONF_DEBOUNCE_DELAY,
    CONF_ENTITY_LINKS,
    CONF_ENTITY_TYPE_OVERRIDES,
    CONF_EXPOSED_ENTITIES,
    CONF_SBER_BROKER,
    CONF_SBER_LOGIN,
    CONF_SBER_PASSWORD,
    CONF_SBER_PORT,
    DOMAIN,
)
from custom_components.sber_mqtt_bridge.sber_entity_map import (
    CATEGORY_DOMAIN_MAP,
    CATEGORY_UI_META,
    OVERRIDABLE_CATEGORIES,
    SUPPORTED_DOMAINS,
    UI_OVERRIDABLE_CATEGORIES,
    build_probe_entity,
    build_probe_entity_data,
    category_label,
)

MOCK_DATA = {
    CONF_SBER_LOGIN: "test_user",
    CONF_SBER_PASSWORD: "test_pass",
    CONF_SBER_BROKER: "mqtt-partners.iot.sberdevices.ru",
    CONF_SBER_PORT: 8883,
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations in all tests."""
    return


@pytest.fixture
def no_real_setup():
    """Neutralise the reload that ``OptionsFlowWithReload`` schedules on save.

    The options flow is exercised against an entry that was never set up,
    so the automatic reload must not start a real MQTT bridge.
    """
    with (
        patch("custom_components.sber_mqtt_bridge.async_setup_entry", return_value=True),
        patch("custom_components.sber_mqtt_bridge.async_unload_entry", return_value=True),
    ):
        yield


def _add_entry(hass: HomeAssistant, options: dict[str, Any]) -> MockConfigEntry:
    """Create and register a config entry carrying ``options``."""
    entry = MockConfigEntry(domain=DOMAIN, data=MOCK_DATA, options=options, unique_id="test_user")
    entry.add_to_hass(hass)
    return entry


# ---------------------------------------------------------------------------
# Registry derivation — the four lists that used to drift apart
# ---------------------------------------------------------------------------


def test_overridable_categories_covers_whole_category_registry() -> None:
    """Every category id must be a legal override value, sensors included.

    The former hand-written list held 21 entries and silently dropped the
    ``sensor_*`` families, so an override stored by the panel could not be
    re-submitted through the Options Flow.
    """
    assert sorted(CATEGORY_DOMAIN_MAP) == OVERRIDABLE_CATEGORIES
    assert "sensor_temp" in OVERRIDABLE_CATEGORIES
    assert "sensor_humidity" in OVERRIDABLE_CATEGORIES


def test_websocket_api_reuses_the_same_category_list() -> None:
    """WS schemas must validate against the very same object, not a copy."""
    from custom_components.sber_mqtt_bridge.websocket_api import _common

    assert _common.OVERRIDABLE_CATEGORIES is OVERRIDABLE_CATEGORIES


def test_ui_category_list_hides_internal_categories_only() -> None:
    """The UI picker drops ``user_selectable=False`` categories and nothing else."""
    hidden = {cat for cat, meta in CATEGORY_UI_META.items() if not meta.user_selectable}
    assert hidden, "fixture assumption: at least one category is UI-hidden"
    assert set(UI_OVERRIDABLE_CATEGORIES) == set(OVERRIDABLE_CATEGORIES) - hidden
    # ...and the hidden ones stay valid for the WebSocket API.
    assert hidden <= set(OVERRIDABLE_CATEGORIES)


def test_supported_domains_is_the_union_of_category_domains() -> None:
    """SUPPORTED_DOMAINS must be derived, not hand-maintained."""
    expected = {domain for spec in CATEGORY_DOMAIN_MAP.values() for domain in spec.domains}
    assert set(SUPPORTED_DOMAINS) == expected
    # The hand-written copy had lost ``lock`` — intercoms were unreachable.
    assert "lock" in SUPPORTED_DOMAINS
    assert "lock" in CATEGORY_DOMAIN_MAP["intercom"].domains


def test_domain_priority_covers_every_supported_domain() -> None:
    """Deduplication must rank every exportable domain.

    A domain missing from ``DOMAIN_PRIORITY`` falls back to 0 and loses to
    any sibling entity on the same device, so "add all" would silently
    drop it.
    """
    assert set(cf.DOMAIN_PRIORITY) == set(SUPPORTED_DOMAINS)


def test_domain_labels_cover_every_supported_domain() -> None:
    """Every selectable domain needs a human caption, not a raw id."""
    missing = [d for d in SUPPORTED_DOMAINS if d not in cf.DOMAIN_LABELS]
    assert not missing, f"domains without a label: {missing}"
    raw = [d for d in SUPPORTED_DOMAINS if cf.DOMAIN_LABELS[d] == d]
    assert not raw, f"domains whose label is the raw id: {raw}"


def test_controllable_domains_outrank_read_only_ones() -> None:
    """Read-only telemetry must never win deduplication over control."""
    for controllable in ("lock", "switch", "light", "fan", "media_player"):
        assert cf.DOMAIN_PRIORITY[controllable] > cf.DOMAIN_PRIORITY["sensor"]
        assert cf.DOMAIN_PRIORITY[controllable] > cf.DOMAIN_PRIORITY["binary_sensor"]
    # An intercom is a richer Sber device than a bare relay.
    assert cf.DOMAIN_PRIORITY["lock"] > cf.DOMAIN_PRIORITY["switch"]


def test_category_label_resolves_against_the_ui_registry() -> None:
    """Labels come from CATEGORY_UI_META; unknown ids degrade to themselves."""
    assert category_label("hvac_ac") == "Air conditioner"
    assert category_label("sensor_water_leak") == "Water leak"
    assert category_label("definitely_not_a_category") == "definitely_not_a_category"
    # Guard against a "return category" regression across the whole registry.
    assert [cat for cat in CATEGORY_DOMAIN_MAP if category_label(cat) == cat] == []


# ---------------------------------------------------------------------------
# Shared probe-entity builder
# ---------------------------------------------------------------------------


@pytest.mark.asyncio(loop_scope="function")
async def test_probe_entity_carries_registry_identity(hass: HomeAssistant) -> None:
    """The shared probe builder fills the identity fields every caller needs.

    The hand-rolled copies of this dict diverged (some omitted
    ``unique_id`` / ``device_id``), which silently degraded wizard link
    suggestions.  This pins the payload to observable entity attributes.
    """
    entry = _add_entry(hass, {})
    device = _make_device(hass, entry, "lamp_dev")
    reg_entry = er.async_get(hass).async_get_or_create(
        "light",
        "demo",
        "lr",
        suggested_object_id="living_room",
        original_name="Living Room",
        device_id=device.id,
    )

    probe = build_probe_entity(reg_entry)

    assert probe is not None
    assert probe.category == "light"
    assert probe.entity_id == "light.living_room"
    assert probe.name == "Living Room"
    assert probe.unique_id == "lr"
    assert probe.platform == "demo"
    assert probe.device_id == device.id
    assert build_probe_entity_data(reg_entry)["original_device_class"] == ""


@pytest.mark.asyncio(loop_scope="function")
async def test_probe_entity_honours_override_and_reports_no_match(hass: HomeAssistant) -> None:
    """Explicit category wins; an unmappable entity yields ``None``."""
    _add_entry(hass, {})
    ent_reg = er.async_get(hass)
    light = ent_reg.async_get_or_create("light", "demo", "lr", suggested_object_id="living_room")
    power = ent_reg.async_get_or_create(
        "sensor", "demo", "power", suggested_object_id="power", original_device_class="power"
    )

    assert build_probe_entity(light, "led_strip").category == "led_strip"
    assert build_probe_entity(power) is None


# ---------------------------------------------------------------------------
# Deduplication behaviour
# ---------------------------------------------------------------------------


def _make_device(hass: HomeAssistant, entry: MockConfigEntry, ident: str) -> dr.DeviceEntry:
    return dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, ident)},
    )


@pytest.mark.asyncio(loop_scope="function")
async def test_add_all_keeps_the_lock_not_its_battery_sensor(hass: HomeAssistant) -> None:
    """A lock + its battery sensor on one device must export as the lock.

    Regression: ``lock`` was absent from ``DOMAIN_PRIORITY`` (priority 0),
    so the battery sensor won — and a battery sensor maps to no Sber
    category at all, leaving the user with an empty export.
    """
    entry = _add_entry(hass, {})
    device = _make_device(hass, entry, "intercom_dev")
    ent_reg = er.async_get(hass)
    ent_reg.async_get_or_create("lock", "demo", "front_door", device_id=device.id, suggested_object_id="front_door")
    ent_reg.async_get_or_create(
        "sensor",
        "demo",
        "front_door_battery",
        device_id=device.id,
        suggested_object_id="front_door_battery",
        original_device_class="battery",
    )

    selected = cf._get_entities_by_domains(hass, SUPPORTED_DOMAINS)

    assert selected == ["lock.front_door"]


@pytest.mark.asyncio(loop_scope="function")
async def test_add_all_keeps_the_switch_not_its_power_sensor(hass: HomeAssistant) -> None:
    """Controllable entities beat telemetry siblings on the same device."""
    entry = _add_entry(hass, {})
    device = _make_device(hass, entry, "plug_dev")
    ent_reg = er.async_get(hass)
    ent_reg.async_get_or_create("switch", "demo", "plug", device_id=device.id, suggested_object_id="plug")
    ent_reg.async_get_or_create(
        "sensor",
        "demo",
        "plug_power",
        device_id=device.id,
        suggested_object_id="plug_power",
        original_device_class="power",
    )

    assert cf._get_entities_by_domains(hass, SUPPORTED_DOMAINS) == ["switch.plug"]


@pytest.mark.asyncio(loop_scope="function")
async def test_entities_without_device_are_never_deduplicated(hass: HomeAssistant) -> None:
    """Device-less entities (SmartIR & co) must all survive."""
    _add_entry(hass, {})
    ent_reg = er.async_get(hass)
    ent_reg.async_get_or_create("light", "demo", "a", suggested_object_id="a")
    ent_reg.async_get_or_create("light", "demo", "b", suggested_object_id="b")

    assert cf._get_entities_by_domains(hass, ["light"]) == ["light.a", "light.b"]


# ---------------------------------------------------------------------------
# Options Flow — option preservation
# ---------------------------------------------------------------------------

FULL_OPTIONS: dict[str, Any] = {
    CONF_EXPOSED_ENTITIES: ["light.living_room"],
    CONF_ENTITY_TYPE_OVERRIDES: {"light.living_room": "led_strip"},
    CONF_ENTITY_LINKS: {"light.living_room": {"battery": "sensor.living_room_battery"}},
    CONF_DEBOUNCE_DELAY: 0.7,
}


async def _open_entity_menu(hass: HomeAssistant, entry: MockConfigEntry) -> str:
    """Walk init → advanced menu → select_entities_menu, return the flow id."""
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(result["flow_id"], {"action": "advanced"})
    assert result["type"] is FlowResultType.MENU

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "select_entities_menu"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "select_entities_menu"
    return result["flow_id"]


@pytest.mark.asyncio(loop_scope="function")
async def test_clear_all_keeps_overrides_links_and_settings(hass: HomeAssistant, no_real_setup) -> None:
    """ "Remove ALL entities" must only clear the exposed list.

    Regression: every step used to call ``async_create_entry`` with just
    its own key, and ``async_create_entry`` replaces ``entry.options``
    wholesale — so clearing the entity list also destroyed the user's type
    overrides, entity links and bridge settings.
    """
    entry = _add_entry(hass, dict(FULL_OPTIONS))
    flow_id = await _open_entity_menu(hass, entry)

    result = await hass.config_entries.options.async_configure(flow_id, {"selection_mode": "clear_all"})
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_EXPOSED_ENTITIES] == []
    assert entry.options[CONF_ENTITY_TYPE_OVERRIDES] == FULL_OPTIONS[CONF_ENTITY_TYPE_OVERRIDES]
    assert entry.options[CONF_ENTITY_LINKS] == FULL_OPTIONS[CONF_ENTITY_LINKS]
    assert entry.options[CONF_DEBOUNCE_DELAY] == 0.7


@pytest.mark.asyncio(loop_scope="function")
async def test_manual_selection_keeps_overrides_links_and_settings(hass: HomeAssistant, no_real_setup) -> None:
    """Manual entity selection replaces only ``exposed_entities``."""
    entry = _add_entry(hass, dict(FULL_OPTIONS))
    flow_id = await _open_entity_menu(hass, entry)

    result = await hass.config_entries.options.async_configure(flow_id, {"selection_mode": "manual"})
    assert result["step_id"] == "select_entities"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_EXPOSED_ENTITIES: ["light.kitchen"]}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_EXPOSED_ENTITIES] == ["light.kitchen"]
    assert entry.options[CONF_ENTITY_TYPE_OVERRIDES] == FULL_OPTIONS[CONF_ENTITY_TYPE_OVERRIDES]
    assert entry.options[CONF_ENTITY_LINKS] == FULL_OPTIONS[CONF_ENTITY_LINKS]
    assert entry.options[CONF_DEBOUNCE_DELAY] == 0.7


@pytest.mark.asyncio(loop_scope="function")
async def test_add_all_merges_registry_entities_and_keeps_settings(hass: HomeAssistant, no_real_setup) -> None:
    """ "Add ALL" writes the deduplicated registry scan, settings untouched."""
    entry = _add_entry(hass, dict(FULL_OPTIONS))
    device = _make_device(hass, entry, "intercom_dev")
    ent_reg = er.async_get(hass)
    ent_reg.async_get_or_create("lock", "demo", "front_door", device_id=device.id, suggested_object_id="front_door")

    flow_id = await _open_entity_menu(hass, entry)
    result = await hass.config_entries.options.async_configure(flow_id, {"selection_mode": "add_all"})
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_EXPOSED_ENTITIES] == ["lock.front_door"]
    assert entry.options[CONF_ENTITY_LINKS] == FULL_OPTIONS[CONF_ENTITY_LINKS]
    assert entry.options[CONF_DEBOUNCE_DELAY] == 0.7


@pytest.mark.asyncio(loop_scope="function")
async def test_by_domain_selection_merges_and_keeps_settings(hass: HomeAssistant, no_real_setup) -> None:
    """Domain-based selection merges into the existing list, settings kept."""
    entry = _add_entry(hass, dict(FULL_OPTIONS))
    ent_reg = er.async_get(hass)
    ent_reg.async_get_or_create("lock", "demo", "front_door", suggested_object_id="front_door")

    flow_id = await _open_entity_menu(hass, entry)
    result = await hass.config_entries.options.async_configure(flow_id, {"selection_mode": "by_domain"})
    assert result["step_id"] == "select_domains"

    # The lock domain must be offered — with a human caption, not "lock".
    options = result["data_schema"].schema["domains"].config["options"]
    labels = {opt["value"]: opt["label"] for opt in options}
    assert "lock" in labels
    assert cf.DOMAIN_LABELS["lock"] != "lock"
    assert labels["lock"] == f"{cf.DOMAIN_LABELS['lock']} (1)"

    result = await hass.config_entries.options.async_configure(result["flow_id"], {"domains": ["lock"]})
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_EXPOSED_ENTITIES] == ["light.living_room", "lock.front_door"]
    assert entry.options[CONF_ENTITY_TYPE_OVERRIDES] == FULL_OPTIONS[CONF_ENTITY_TYPE_OVERRIDES]
    assert entry.options[CONF_DEBOUNCE_DELAY] == 0.7


@pytest.mark.asyncio(loop_scope="function")
async def test_by_label_selection_merges_and_keeps_settings(hass: HomeAssistant, no_real_setup) -> None:
    """Label-based selection merges into the existing list, settings kept."""
    entry = _add_entry(hass, dict(FULL_OPTIONS))
    ent_reg = er.async_get(hass)
    ent_reg.async_get_or_create("light", "demo", "hall", suggested_object_id="hall")
    ent_reg.async_update_entity("light.hall", labels={"sber"})

    flow_id = await _open_entity_menu(hass, entry)
    result = await hass.config_entries.options.async_configure(flow_id, {"selection_mode": "by_label"})
    assert result["step_id"] == "select_labels"

    result = await hass.config_entries.options.async_configure(result["flow_id"], {"labels": ["sber"]})
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_EXPOSED_ENTITIES] == ["light.hall", "light.living_room"]
    assert entry.options[CONF_ENTITY_LINKS] == FULL_OPTIONS[CONF_ENTITY_LINKS]
    assert entry.options[CONF_DEBOUNCE_DELAY] == 0.7


# ---------------------------------------------------------------------------
# Options Flow — type override step
# ---------------------------------------------------------------------------


def _override_options(result: dict, entity_id: str) -> dict[str, str]:
    """Return {value: label} of the category selector for ``entity_id``."""
    schema = result["data_schema"].schema
    key = next(k for k in schema if str(k) == f"override_{entity_id}")
    return {opt["value"]: opt["label"] for opt in schema[key].config["options"]}


async def _open_type_overrides(hass: HomeAssistant, entry: MockConfigEntry) -> dict:
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"action": "advanced"})
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "type_overrides"})
    assert result["step_id"] == "type_overrides"
    return result


@pytest.mark.asyncio(loop_scope="function")
async def test_type_override_dropdown_uses_human_labels(hass: HomeAssistant, no_real_setup) -> None:
    """The category dropdown shows registry labels, never raw category ids."""
    entry = _add_entry(hass, {CONF_EXPOSED_ENTITIES: ["light.living_room"]})
    er.async_get(hass).async_get_or_create("light", "demo", "lr", suggested_object_id="living_room")

    result = await _open_type_overrides(hass, entry)
    labels = _override_options(result, "light.living_room")

    assert labels["auto"] == "Auto (detect from domain)"
    assert labels["hvac_ac"] == "Air conditioner"
    assert labels["led_strip"] == "LED strip"
    assert [cat for cat in UI_OVERRIDABLE_CATEGORIES if labels[cat] == cat] == []


@pytest.mark.asyncio(loop_scope="function")
async def test_type_override_dropdown_hides_internal_categories(hass: HomeAssistant, no_real_setup) -> None:
    """``user_selectable=False`` categories are not offered to the user."""
    entry = _add_entry(hass, {CONF_EXPOSED_ENTITIES: ["light.living_room"]})
    er.async_get(hass).async_get_or_create("light", "demo", "lr", suggested_object_id="living_room")

    result = await _open_type_overrides(hass, entry)
    values = set(_override_options(result, "light.living_room")) - {"auto"}

    assert values == set(UI_OVERRIDABLE_CATEGORIES)
    assert "sensor_humidity" not in values


@pytest.mark.asyncio(loop_scope="function")
async def test_type_override_dropdown_offers_the_stored_internal_value(hass: HomeAssistant, no_real_setup) -> None:
    """An override stored by the panel must remain re-submittable.

    ``sensor_humidity`` is hidden from the picker, but the wizard can store
    it.  If the selector did not offer the current value, its own default
    would fail ``vol.In`` validation and the form could not be submitted at
    all.
    """
    entry = _add_entry(
        hass,
        {
            CONF_EXPOSED_ENTITIES: ["sensor.bath"],
            CONF_ENTITY_TYPE_OVERRIDES: {"sensor.bath": "sensor_humidity"},
        },
    )
    er.async_get(hass).async_get_or_create(
        "sensor", "demo", "bath", suggested_object_id="bath", original_device_class="humidity"
    )

    result = await _open_type_overrides(hass, entry)
    assert "sensor_humidity" in _override_options(result, "sensor.bath")

    # Re-submitting the untouched form must be accepted and preserve it.
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"override_sensor.bath": "sensor_humidity"}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_ENTITY_TYPE_OVERRIDES] == {"sensor.bath": "sensor_humidity"}


@pytest.mark.asyncio(loop_scope="function")
async def test_type_override_submit_keeps_links_and_settings(hass: HomeAssistant, no_real_setup) -> None:
    """Saving overrides must not wipe entity links or bridge settings."""
    entry = _add_entry(hass, dict(FULL_OPTIONS))
    er.async_get(hass).async_get_or_create("light", "demo", "lr", suggested_object_id="living_room")

    result = await _open_type_overrides(hass, entry)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"override_light.living_room": "auto"}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    # "auto" clears the override...
    assert entry.options[CONF_ENTITY_TYPE_OVERRIDES] == {}
    # ...and nothing else is touched.
    assert entry.options[CONF_EXPOSED_ENTITIES] == ["light.living_room"]
    assert entry.options[CONF_ENTITY_LINKS] == FULL_OPTIONS[CONF_ENTITY_LINKS]
    assert entry.options[CONF_DEBOUNCE_DELAY] == 0.7


# ---------------------------------------------------------------------------
# Options Flow — preview / summary rendering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio(loop_scope="function")
async def test_preview_renders_category_labels_per_entity(hass: HomeAssistant, no_real_setup) -> None:
    """The preview resolves each entity to its Sber category label.

    Covers ``_entity_category_label``: a regression returning a constant
    (e.g. ``"unknown"``) or the raw id would make the preview useless.
    """
    entry = _add_entry(
        hass,
        {
            CONF_EXPOSED_ENTITIES: ["light.living_room", "sensor.bath", "sensor.mystery", "light.ghost"],
            CONF_ENTITY_TYPE_OVERRIDES: {"light.living_room": "led_strip"},
        },
    )
    ent_reg = er.async_get(hass)
    ent_reg.async_get_or_create("light", "demo", "lr", suggested_object_id="living_room")
    ent_reg.async_get_or_create("sensor", "demo", "bath", suggested_object_id="bath", original_device_class="humidity")
    # No Sber category matches a "power" sensor → "unknown" bucket.
    ent_reg.async_get_or_create(
        "sensor", "demo", "mystery", suggested_object_id="mystery", original_device_class="power"
    )
    # light.ghost is not in the registry at all → "not found" bucket.

    result = await hass.config_entries.options.async_init(entry.entry_id)
    summary = result["description_placeholders"]["entity_summary"]
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"action": "preview"})
    preview = result["description_placeholders"]["preview"]

    assert result["step_id"] == "entity_preview"
    # Override honoured: living room is an LED strip, not a plain Light.
    assert "**LED strip** (1)" in preview
    assert "light.living_room" in preview
    # Humidity sensor resolves through the humidity → sensor_temp alias.
    assert "**Temperature** (1)" in preview
    assert "**unknown** (1)" in preview
    assert "Not found" in preview
    assert "LED strip: 1" in summary
    assert "**Exposed: 4 entities**" in summary


# ---------------------------------------------------------------------------
# Options Flow — every branch a user can reach
# ---------------------------------------------------------------------------


async def _open_advanced_step(hass: HomeAssistant, entry: MockConfigEntry, step: str) -> dict:
    """Walk init → advanced menu → ``step`` and return that step's result."""
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"action": "advanced"})
    return await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": step})


@pytest.mark.asyncio(loop_scope="function")
async def test_choosing_the_panel_closes_without_changing_options(hass: HomeAssistant, no_real_setup) -> None:
    """ "Open the panel" finishes the dialog and leaves every option as it was."""
    entry = _add_entry(hass, dict(FULL_OPTIONS))

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"action": "panel"})
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert dict(entry.options) == FULL_OPTIONS


@pytest.mark.asyncio(loop_scope="function")
async def test_summary_and_preview_explain_an_empty_export(hass: HomeAssistant, no_real_setup) -> None:
    """With nothing exposed the dialog says so instead of rendering empty text."""
    entry = _add_entry(hass, {})

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["description_placeholders"]["entity_summary"] == "No entities exposed yet"

    result = await hass.config_entries.options.async_configure(result["flow_id"], {"action": "preview"})
    assert result["step_id"] == "entity_preview"
    assert result["description_placeholders"]["preview"] == "No entities exposed yet. Add entities first."


@pytest.mark.asyncio(loop_scope="function")
async def test_preview_submit_returns_to_the_start(hass: HomeAssistant, no_real_setup) -> None:
    """Confirming the preview goes back to the action choice, nothing is saved."""
    entry = _add_entry(hass, dict(FULL_OPTIONS))

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"action": "preview"})
    result = await hass.config_entries.options.async_configure(result["flow_id"], {})

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"
    assert dict(entry.options) == FULL_OPTIONS


@pytest.mark.asyncio(loop_scope="function")
async def test_domain_choice_counts_only_entities_that_can_be_exported(hass: HomeAssistant, no_real_setup) -> None:
    """Disabled entities and the bridge's own entities are not offered or counted.

    Submitting without picking a domain closes the dialog unchanged.
    """
    entry = _add_entry(hass, dict(FULL_OPTIONS))
    ent_reg = er.async_get(hass)
    ent_reg.async_get_or_create("switch", "demo", "pump", suggested_object_id="pump")
    ent_reg.async_get_or_create(
        "switch", "demo", "old", suggested_object_id="old", disabled_by=er.RegistryEntryDisabler.USER
    )
    ent_reg.async_get_or_create("binary_sensor", DOMAIN, "connected", suggested_object_id="sber_connected")

    result = await _open_advanced_step(hass, entry, "select_entities_menu")
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"selection_mode": "by_domain"})

    options = {opt["value"]: opt["label"] for opt in result["data_schema"].schema["domains"].config["options"]}
    assert options == {"switch": f"{cf.DOMAIN_LABELS['switch']} (1)"}

    result = await hass.config_entries.options.async_configure(result["flow_id"], {"domains": []})
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert dict(entry.options) == FULL_OPTIONS


@pytest.mark.asyncio(loop_scope="function")
async def test_label_choice_offers_and_adds_only_exportable_entities(hass: HomeAssistant, no_real_setup) -> None:
    """A label shared by unexportable entities neither offers them nor adds them.

    Disabled entities, the bridge's own entities and domains Sber has no
    category for all carry the label, yet only the light is added.
    """
    entry = _add_entry(hass, {})
    ent_reg = er.async_get(hass)
    ent_reg.async_get_or_create("light", "demo", "hall", suggested_object_id="hall")
    ent_reg.async_get_or_create(
        "light", "demo", "old", suggested_object_id="old", disabled_by=er.RegistryEntryDisabler.USER
    )
    ent_reg.async_get_or_create("binary_sensor", DOMAIN, "connected", suggested_object_id="sber_connected")
    ent_reg.async_get_or_create("automation", "demo", "wake", suggested_object_id="wake")
    ent_reg.async_get_or_create("switch", DOMAIN, "own", suggested_object_id="own")
    for entity_id in ("light.hall", "light.old", "binary_sensor.sber_connected", "automation.wake"):
        ent_reg.async_update_entity(entity_id, labels={"sber"})
    # Labels of unexportable entities alone must not appear in the picker.
    ent_reg.async_update_entity("light.old", labels={"sber", "retired"})
    ent_reg.async_update_entity("switch.own", labels={"internal"})

    result = await _open_advanced_step(hass, entry, "select_entities_menu")
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"selection_mode": "by_label"})
    offered = [opt["value"] for opt in result["data_schema"].schema["labels"].config["options"]]
    assert offered == ["sber"]

    result = await hass.config_entries.options.async_configure(result["flow_id"], {"labels": ["sber"]})
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_EXPOSED_ENTITIES] == ["light.hall"]


@pytest.mark.asyncio(loop_scope="function")
async def test_label_choice_without_any_labels_closes_unchanged(hass: HomeAssistant, no_real_setup) -> None:
    """No labels in the registry: an optional, empty picker that saves nothing."""
    entry = _add_entry(hass, dict(FULL_OPTIONS))
    er.async_get(hass).async_get_or_create("light", "demo", "hall", suggested_object_id="hall")

    result = await _open_advanced_step(hass, entry, "select_entities_menu")
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"selection_mode": "by_label"})
    assert result["step_id"] == "select_labels"
    assert result["data_schema"].schema["labels"].config["options"] == []

    result = await hass.config_entries.options.async_configure(result["flow_id"], {})
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert dict(entry.options) == FULL_OPTIONS


@pytest.mark.asyncio(loop_scope="function")
async def test_add_all_keeps_the_richest_entity_whatever_the_registry_order(hass: HomeAssistant) -> None:
    """A switch registered before the light of the same device is replaced by the light."""
    entry = _add_entry(hass, {})
    device = _make_device(hass, entry, "kitchen_dev")
    ent_reg = er.async_get(hass)
    ent_reg.async_get_or_create("switch", "demo", "kitchen_sw", device_id=device.id, suggested_object_id="kitchen")
    ent_reg.async_get_or_create("light", "demo", "kitchen_light", device_id=device.id, suggested_object_id="kitchen")

    assert cf._get_entities_by_domains(hass, SUPPORTED_DOMAINS) == ["light.kitchen"]


@pytest.mark.asyncio(loop_scope="function")
async def test_type_overrides_without_exposed_entities_explains_and_stops(hass: HomeAssistant, no_real_setup) -> None:
    """Nothing exposed: the step aborts with a translated reason.

    Regression: it used to render an empty form whose explanation was
    never shown (the step text had no placeholder for it), and submitting
    that form rewrote the stored overrides to an empty mapping.
    """
    options = {CONF_EXPOSED_ENTITIES: [], CONF_ENTITY_TYPE_OVERRIDES: {"light.kept": "led_strip"}}
    entry = _add_entry(hass, options)

    result = await _open_advanced_step(hass, entry, "type_overrides")

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_exposed_entities"
    assert dict(entry.options) == options


@pytest.mark.asyncio(loop_scope="function")
async def test_type_overrides_keep_the_override_of_an_entity_missing_from_the_registry(
    hass: HomeAssistant, no_real_setup
) -> None:
    """An exposed entity the form cannot show keeps its stored override.

    Regression: an entity absent from the entity registry gets no
    selector, so its key is missing from the submission — and a missing
    key used to be read as "auto", deleting an override the user never
    saw, let alone changed.
    """
    entry = _add_entry(
        hass,
        {
            CONF_EXPOSED_ENTITIES: ["light.living_room", "light.ghost"],
            CONF_ENTITY_TYPE_OVERRIDES: {"light.ghost": "led_strip"},
        },
    )
    er.async_get(hass).async_get_or_create("light", "demo", "lr", suggested_object_id="living_room")

    result = await _open_type_overrides(hass, entry)
    assert [str(key) for key in result["data_schema"].schema] == ["override_light.living_room"]

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"override_light.living_room": "led_strip"}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_ENTITY_TYPE_OVERRIDES] == {
        "light.living_room": "led_strip",
        "light.ghost": "led_strip",
    }


@pytest.mark.asyncio(loop_scope="function")
async def test_device_sync_rejects_an_out_of_range_wait_and_accepts_the_fix(hass: HomeAssistant, no_real_setup) -> None:
    """An out-of-range value is refused without saving; the corrected form saves.

    The form starts from the stored values, and a save keeps every other
    option.
    """
    entry = _add_entry(hass, {**FULL_OPTIONS, CONF_CONFIG_SETTLE_DELAY: 7.0})

    result = await _open_advanced_step(hass, entry, "device_sync")
    assert result["step_id"] == "device_sync"
    defaults = {str(key): key.default() for key in result["data_schema"].schema}
    assert defaults[CONF_CONFIG_SETTLE_DELAY] == 7.0

    with pytest.raises(InvalidData):
        await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_CONFIG_SETTLE_DELAY: 7.0, CONF_CONFIG_MAX_WAIT: 5000}
        )
    assert CONF_CONFIG_MAX_WAIT not in entry.options

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_CONFIG_SETTLE_DELAY: 30, CONF_CONFIG_MAX_WAIT: 600}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_CONFIG_SETTLE_DELAY] == 30.0
    assert entry.options[CONF_CONFIG_MAX_WAIT] == 600.0
    assert entry.options[CONF_ENTITY_TYPE_OVERRIDES] == FULL_OPTIONS[CONF_ENTITY_TYPE_OVERRIDES]
