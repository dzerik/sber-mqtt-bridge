# Sber Spec 2026-05 Alignment — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Align the HACS integration with the 2026-05-21 Sber spec — regenerate obligatory-features artefacts, ship the new `sensor_air` device category via existing Entity Linking, add two lightweight passive-telemetry features (`hvac_water_percentage`, `kitchen_water_temperature`), and cut release v1.40.0.

**Architecture:** All changes stay inside `custom_components/sber_mqtt_bridge/`. The new category reuses the existing `LinkableRole` machinery (mirroring `SensorTempEntity` + linked `humidity` pattern), so no new wizard / factory infrastructure is needed. Conditional (`✔︎*`) features are deliberately NOT locally validated — Sber cloud arbitrates.

**Tech Stack:** Python 3.13+ · Home Assistant 2025.1+ · pytest · playwright (scraper only) · pydantic v2 · aiomqtt

## Global Constraints

- Version bump target: **1.40.0** (MINOR — new backward-compatible functionality). Values must match in all four locations (`pyproject.toml`, `manifest.json`, `sber_protocol.py::VERSION`, `CHANGELOG.md`) — enforced by release CI.
- `sensor_air` is a strict-obligatory-`online` only category. All measurement features (`co2`, `pm1_0`, `pm2_5`, `pm10`, `tvoc_float`, `hcho_float`, `temperature`, `humidity`) are `✔︎*` conditional per spec and must NOT appear in `CATEGORY_OBLIGATORY_FEATURES[sensor_air]`.
- No changes to `_generated/*.py` may be hand-edited — always via `python tools/codegen.py`.
- Every new SberFeature enum value must match Sber's exact wire-format spelling (`pm1_0` with underscore before 0, `tvoc_float` not `tvoc`, `hcho_float` not `hcho`).
- New locale strings live in `strings.json` (source of truth) and `translations/en.json` + `translations/ru.json` (mirrors).
- Follow the project's naming conventions in commits: `feat(devices/<component>): …`, `chore(generated): …`, `chore: release vX.Y.Z`.
- Preceding commit `a5becd8` (scraper fixes) already added `sensor_air` to `CATEGORIES` in `tools/fetch_sber_schemas.py`, so Task 2 (snapshot regen) will pick it up automatically.
- `hvac_water_low_level`, `channel/channel_int`, `open_left_set/open_right_state` are **explicitly deferred** — do not add them.

---

## File Structure

Files created or modified across the whole plan (touched once unless noted):

**Created**
- `custom_components/sber_mqtt_bridge/devices/sensor_air.py` — new `SensorAirEntity` class
- `tests/hacs/test_devices_sensor_air.py` — unit tests for `SensorAirEntity`

**Modified**
- `custom_components/sber_mqtt_bridge/sber_constants.py` — add 8 `SberFeature` enum entries
- `custom_components/sber_mqtt_bridge/devices/base_entity.py` — add 6 `LinkableRole` constants for air-quality measurements
- `custom_components/sber_mqtt_bridge/sber_entity_map.py` — register `sensor_air` in `CATEGORY_DOMAIN_MAP` + `CategoryUiMeta`
- `custom_components/sber_mqtt_bridge/devices/humidifier.py` — one `AttrSpec` + one emit line
- `custom_components/sber_mqtt_bridge/devices/kettle.py` — one `AttrSpec` + one emit line
- `custom_components/sber_mqtt_bridge/strings.json` — sensor_air category label + role labels
- `custom_components/sber_mqtt_bridge/translations/en.json` — mirror of strings.json
- `custom_components/sber_mqtt_bridge/translations/ru.json` — mirror of strings.json
- `custom_components/sber_mqtt_bridge/manifest.json` — version bump 1.39.8 → 1.40.0
- `custom_components/sber_mqtt_bridge/sber_protocol.py` — `VERSION` bump
- `pyproject.toml` — version bump
- `CHANGELOG.md` — new `[1.40.0]` section
- `tests/hacs/test_devices_humidifier.py` — add water_percentage test
- `tests/hacs/test_devices_kettle.py` — add water_temp test
- `tests/hacs/test_category_domain_map.py` — assert sensor_air presence
- `tests/hacs/test_sber_compliance_sensors_covers_tv.py` — assert sensor_air compliance
- `tests/hacs/test_codegen_safety.py` — assert relaxed obligatory
- `tests/hacs/__snapshots__/sber_full_spec.json` — regen with sensor_air data (Task 2)
- `tests/hacs/__snapshots__/sber_schemas.json` — regen with sensor_air data (Task 2)

**Regenerated (never hand-edited)**
- `custom_components/sber_mqtt_bridge/_generated/obligatory_features.py`
- `custom_components/sber_mqtt_bridge/_generated/category_features.py`
- `custom_components/sber_mqtt_bridge/_generated/feature_types.py`

---

## Task 1: Regen `_generated/` from committed snapshot (relaxes P0.3 + P0.4)

**Files:**
- Regen: `custom_components/sber_mqtt_bridge/_generated/obligatory_features.py`
- Regen: `custom_components/sber_mqtt_bridge/_generated/category_features.py`
- Regen: `custom_components/sber_mqtt_bridge/_generated/feature_types.py`
- Modify: `tests/hacs/test_codegen_safety.py` — assertions about relaxed obligatory sets

**Interfaces:**
- Consumes: existing `tests/hacs/__snapshots__/sber_full_spec.json` (committed in `a5becd8`) — already contains split `obligatory` vs `conditional` per category.
- Produces: `_generated.CATEGORY_OBLIGATORY_FEATURES` with `sensor_temp = {"online"}` and cover categories = `{"online", "open_state"}`.

- [ ] **Step 1: Verify pre-conditions**

Run:
```bash
git rev-parse HEAD  # expect a5becd8 or a descendant
grep '"obligatory"' tests/hacs/__snapshots__/sber_full_spec.json | head -5
```

Expected: file contains explicit `"obligatory"` and `"conditional"` fields per category (this was fixed in `a5becd8`).

- [ ] **Step 2: Run codegen**

Run:
```bash
source .venv/bin/activate
python tools/codegen.py
```

Expected output: `Wrote N files.` and no errors. Files under `_generated/` change.

- [ ] **Step 3: Verify the relax landed correctly**

Run:
```bash
grep '"sensor_temp"' custom_components/sber_mqtt_bridge/_generated/obligatory_features.py
grep '"curtain"' custom_components/sber_mqtt_bridge/_generated/obligatory_features.py
grep '"valve"' custom_components/sber_mqtt_bridge/_generated/obligatory_features.py
```

Expected:
```
"sensor_temp": frozenset({"online"}),
"curtain": frozenset({"online", "open_state"}),
"valve": frozenset({"online", "open_state"}),
```

If `sensor_temp` still contains `humidity` or `temperature`, or curtain still contains `open_percentage`/`open_set` — the snapshot regeneration in `a5becd8` was incomplete; abort and re-open the spec.

- [ ] **Step 4: Update `test_codegen_safety.py` to lock in the relaxed sets**

Open `tests/hacs/test_codegen_safety.py` and locate the block that asserts on `CATEGORY_OBLIGATORY_FEATURES`. Replace the stale sensor_temp / curtain expectations. Add this test at the end of `TestGeneratedContents` class (or its equivalent; grep for existing `CATEGORY_OBLIGATORY_FEATURES` assertions and slot alongside):

```python
def test_sensor_temp_obligatory_relaxed_after_2026_05(self):
    """After the 2026-05 Sber spec update humidity/temperature became
    ✔︎* conditional (at-least-one-of). Ensure our codegen no longer
    marks them strict-mandatory — otherwise chunk-temperature-only
    HA sensors get false-rejected locally by missing_obligatory_features().
    """
    assert CATEGORY_OBLIGATORY_FEATURES["sensor_temp"] == frozenset({"online"})

def test_cover_obligatory_relaxed_after_2026_05(self):
    """open_percentage/open_set became ✔︎* conditional for four cover
    categories; only online + open_state remain strict."""
    for cat in ("curtain", "gate", "valve", "window_blind"):
        assert CATEGORY_OBLIGATORY_FEATURES[cat] == frozenset({"online", "open_state"}), \
            f"{cat}: unexpected obligatory set — snapshot may need re-scraping"
```

- [ ] **Step 5: Run all codegen-safety tests**

Run:
```bash
python -m pytest tests/hacs/test_codegen_safety.py -o asyncio_mode=auto --no-cov -v
```

Expected: all tests PASS, including the two new ones.

- [ ] **Step 6: Run the wider test suite to catch downstream impact**

Run:
```bash
python -m pytest tests/hacs/ -o asyncio_mode=auto -n auto --no-cov -k "not test_config_flow" -q
```

Expected: 1900+ passing, 0 failures. If tests that previously depended on the strict obligatory contract fail (e.g. they expected `missing_obligatory_features()` to return `{humidity}` for a temp-only sensor), fix by updating expectations to the relaxed set.

- [ ] **Step 7: Commit**

```bash
git add \
  custom_components/sber_mqtt_bridge/_generated/obligatory_features.py \
  custom_components/sber_mqtt_bridge/_generated/category_features.py \
  custom_components/sber_mqtt_bridge/_generated/feature_types.py \
  tests/hacs/test_codegen_safety.py
git commit -m "chore(generated): regen _generated/ from 2026-05 spec (relax P0.3/P0.4)

- sensor_temp obligatory: {humidity, online, temperature} -> {online}
- curtain/gate/valve/window_blind obligatory:
    {online, open_percentage, open_set, open_state} -> {online, open_state}
- New function types (co2, pm1_0, pm2_5, pm10, tvoc_float, hcho_float)
  picked up in FEATURE_TYPES for sensor_air scaffolding.

Backward-compatible: strictly relaxes what missing_obligatory_features()
returns. Devices that previously validated still do."
```

---

## Task 2: Regen snapshot with `sensor_air` data + re-run codegen

**Files:**
- Regen: `tests/hacs/__snapshots__/sber_full_spec.json`
- Regen: `tests/hacs/__snapshots__/sber_schemas.json`
- Regen: `custom_components/sber_mqtt_bridge/_generated/category_features.py`
- Regen: `custom_components/sber_mqtt_bridge/_generated/obligatory_features.py`
- Regen: `custom_components/sber_mqtt_bridge/_generated/feature_types.py`

**Interfaces:**
- Consumes: `CATEGORIES` tuple in `tools/fetch_sber_schemas.py` (already includes `sensor_air` from `a5becd8`).
- Produces: `categories["sensor_air"]` populated in `sber_full_spec.json`; `obligatory_features.py::CATEGORY_OBLIGATORY_FEATURES["sensor_air"] = frozenset({"online"})`.

- [ ] **Step 1: Confirm playwright is installed**

Run:
```bash
source .venv/bin/activate
python -c "from playwright.sync_api import sync_playwright; print('ok')"
```

Expected: `ok`. If it errors, install via `uv pip install playwright`.

- [ ] **Step 2: Patch playwright for Ubuntu 26 (temporary)**

The Ubuntu-version gate at line 78 in `hostPlatform.js` doesn't know about Ubuntu 26. One-line patch (undone in Step 6 below):

Run:
```bash
sed -i.bak 's|if (major < 26)|if (major < 28)|' \
  .venv/lib/python3.14/site-packages/playwright/driver/package/lib/server/utils/hostPlatform.js
```

Expected: a `.bak` file appears next to the patched file. If Python version in path is different (e.g. python3.13), adjust accordingly.

- [ ] **Step 3: Ensure chromium is downloaded**

Run:
```bash
playwright install chromium 2>&1 | tail -3
```

Expected: `BEWARE: your OS is not officially supported by Playwright; downloading fallback build for ubuntu24.04-x64.` (or "already installed"). No `Error` line.

- [ ] **Step 4: Run the scraper**

Run:
```bash
python tools/fetch_sber_schemas.py 2>&1 | tee /tmp/scraper.log | tail -5
```

Expected last lines:
```
Wrote 29 category schemas to .../sber_schemas.json
Wrote unified spec (29 categories, 96+ functions) to .../sber_full_spec.json
```

If Phase 0 warns about a NEW category beyond `sensor_air` — pause and add it to `CATEGORIES`, then rerun. If a category page fails to fetch (transient), rerun the whole script.

- [ ] **Step 5: Verify sensor_air data is now in the snapshot**

Run:
```bash
python3 -c "
import json
s = json.load(open('tests/hacs/__snapshots__/sber_full_spec.json'))
sa = s['categories']['sensor_air']
print('all_features:', sa.get('all_features'))
print('obligatory:', sa.get('obligatory'))
print('conditional:', sa.get('conditional'))
"
```

Expected:
- `all_features`: contains `online, temperature, humidity, co2, pm1_0, pm2_5, pm10, tvoc_float, hcho_float` and a few battery/signal fields.
- `obligatory`: exactly `["online"]`.
- `conditional`: exactly `["co2", "hcho_float", "humidity", "pm10", "pm1_0", "pm2_5", "temperature", "tvoc_float"]` (in that sort order).

If obligatory is not just `["online"]` — the `✔︎ * ` split logic broke; investigate before committing.

- [ ] **Step 6: Restore vanilla playwright**

Run:
```bash
mv .venv/lib/python3.14/site-packages/playwright/driver/package/lib/server/utils/hostPlatform.js.bak \
   .venv/lib/python3.14/site-packages/playwright/driver/package/lib/server/utils/hostPlatform.js
```

Expected: no output. `.bak` file gone.

- [ ] **Step 7: Re-run codegen to pick up sensor_air in `_generated/`**

Run:
```bash
python tools/codegen.py
python tools/codegen.py --check   # must exit 0 — no residual drift
```

Expected: second command exits with code 0.

Verify:
```bash
grep '"sensor_air"' custom_components/sber_mqtt_bridge/_generated/obligatory_features.py
```

Expected: `"sensor_air": frozenset({"online"}),`

- [ ] **Step 8: Confirm scraper unit tests still pass**

Run:
```bash
python -m pytest tests/hacs/test_fetch_sber_schemas.py -o asyncio_mode=auto --no-cov -q
```

Expected: 9 passed.

- [ ] **Step 9: Commit**

```bash
git add \
  tests/hacs/__snapshots__/sber_full_spec.json \
  tests/hacs/__snapshots__/sber_schemas.json \
  custom_components/sber_mqtt_bridge/_generated/obligatory_features.py \
  custom_components/sber_mqtt_bridge/_generated/category_features.py \
  custom_components/sber_mqtt_bridge/_generated/feature_types.py
git commit -m "chore(snapshot): regen with sensor_air category

Phase 0b of the scraper flagged sensor_air as new upstream. Snapshot
now includes its 13-feature schema; obligatory reduces to {online},
the 8 measurement features (temperature/humidity/co2/pm*/tvoc/hcho)
are conditional (✔︎*). _generated/ regenerated to match."
```

---

## Task 3: Add `SberFeature` enum values for new features

**Files:**
- Modify: `custom_components/sber_mqtt_bridge/sber_constants.py`

**Interfaces:**
- Produces: `SberFeature.CO2`, `SberFeature.PM1_0`, `SberFeature.PM2_5`, `SberFeature.PM10`, `SberFeature.TVOC_FLOAT`, `SberFeature.HCHO_FLOAT`, `SberFeature.HVAC_WATER_PERCENTAGE`, `SberFeature.KITCHEN_WATER_TEMPERATURE` — consumed in Tasks 5, 8, 9.

- [ ] **Step 1: Write failing test for enum presence**

Add to `tests/hacs/test_devices_sensor_air.py` (create file if absent):

```python
"""Unit tests for SensorAirEntity + Sber air-quality features."""

from __future__ import annotations

import pytest

from custom_components.sber_mqtt_bridge.sber_constants import SberFeature


class TestNewAirFeatures:
    """The 2026-05 spec added six air-quality features + two P2 telemetry
    features. Confirm they exist with the exact spec wire spellings."""

    @pytest.mark.parametrize(
        "attr,expected",
        [
            ("CO2", "co2"),
            ("PM1_0", "pm1_0"),
            ("PM2_5", "pm2_5"),
            ("PM10", "pm10"),
            ("TVOC_FLOAT", "tvoc_float"),
            ("HCHO_FLOAT", "hcho_float"),
            ("HVAC_WATER_PERCENTAGE", "hvac_water_percentage"),
            ("KITCHEN_WATER_TEMPERATURE", "kitchen_water_temperature"),
        ],
    )
    def test_new_feature_enum_values(self, attr, expected):
        assert getattr(SberFeature, attr).value == expected
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
python -m pytest tests/hacs/test_devices_sensor_air.py::TestNewAirFeatures -o asyncio_mode=auto --no-cov -v
```

Expected: 8 failures with `AttributeError: type object 'SberFeature' has no attribute 'CO2'`.

- [ ] **Step 3: Add enum values**

Locate the alphabetically-sorted feature list in `custom_components/sber_mqtt_bridge/sber_constants.py::SberFeature` class. Insert the eight new lines in alphabetical order (mirror the existing style — value = wire spelling):

```python
    CO2 = "co2"
    HCHO_FLOAT = "hcho_float"
    HVAC_WATER_PERCENTAGE = "hvac_water_percentage"
    KITCHEN_WATER_TEMPERATURE = "kitchen_water_temperature"
    PM10 = "pm10"
    PM1_0 = "pm1_0"
    PM2_5 = "pm2_5"
    TVOC_FLOAT = "tvoc_float"
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
python -m pytest tests/hacs/test_devices_sensor_air.py::TestNewAirFeatures -o asyncio_mode=auto --no-cov -v
```

Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add custom_components/sber_mqtt_bridge/sber_constants.py tests/hacs/test_devices_sensor_air.py
git commit -m "feat(constants): add SberFeature values for 2026-05 spec

Six air-quality measurements (co2, pm1_0, pm2_5, pm10, tvoc_float,
hcho_float) for the new sensor_air category, plus two passive-telemetry
features (hvac_water_percentage, kitchen_water_temperature) for
existing humidifier/kettle classes."
```

---

## Task 4: Add `LinkableRole` constants for air-quality measurements

**Files:**
- Modify: `custom_components/sber_mqtt_bridge/devices/base_entity.py`

**Interfaces:**
- Consumes: existing `LinkableRole` dataclass (line ~180 in base_entity.py) and existing `ROLE_TEMPERATURE`, `ROLE_HUMIDITY` (lines 193, 196).
- Produces: `ROLE_CO2`, `ROLE_PM1`, `ROLE_PM25`, `ROLE_PM10`, `ROLE_TVOC`, `ROLE_HCHO` — consumed by `SensorAirEntity` in Task 5.

- [ ] **Step 1: Write failing test**

Append to `tests/hacs/test_devices_sensor_air.py`:

```python
from custom_components.sber_mqtt_bridge.devices.base_entity import (
    ROLE_CO2, ROLE_HCHO, ROLE_HUMIDITY, ROLE_PM1, ROLE_PM10, ROLE_PM25,
    ROLE_TEMPERATURE, ROLE_TVOC, LinkableRole,
)


class TestAirQualityRoles:
    """Each air-quality role must be a proper LinkableRole tied to
    the `sensor` HA domain and the correct HA device_class."""

    @pytest.mark.parametrize(
        "role,expected_role_name,expected_device_class",
        [
            (ROLE_CO2, "co2", "carbon_dioxide"),
            (ROLE_PM1, "pm1", "pm1"),
            (ROLE_PM25, "pm25", "pm25"),
            (ROLE_PM10, "pm10", "pm10"),
            (ROLE_TVOC, "tvoc", "volatile_organic_compounds"),
            (ROLE_HCHO, "hcho", "volatile_organic_compounds_parts"),
        ],
    )
    def test_role_shape(self, role, expected_role_name, expected_device_class):
        assert isinstance(role, LinkableRole)
        assert role.role == expected_role_name
        assert "sensor" in role.domains
        assert expected_device_class in role.device_classes
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
python -m pytest tests/hacs/test_devices_sensor_air.py::TestAirQualityRoles -o asyncio_mode=auto --no-cov -v
```

Expected: 6 collection errors (`ImportError`).

- [ ] **Step 3: Add role constants**

In `custom_components/sber_mqtt_bridge/devices/base_entity.py`, immediately **after** the existing `ROLE_HUMIDITY = ...` (line 196), add:

```python
ROLE_CO2 = LinkableRole("co2", frozenset({"sensor"}), frozenset({"carbon_dioxide"}))
"""Carbon-dioxide concentration link (Sber ``sensor_air.co2``, ppm)."""

ROLE_PM1 = LinkableRole("pm1", frozenset({"sensor"}), frozenset({"pm1"}))
"""PM1.0 particulate matter link (Sber ``sensor_air.pm1_0``, µg/m³)."""

ROLE_PM25 = LinkableRole("pm25", frozenset({"sensor"}), frozenset({"pm25"}))
"""PM2.5 particulate matter link (Sber ``sensor_air.pm2_5``, µg/m³)."""

ROLE_PM10 = LinkableRole("pm10", frozenset({"sensor"}), frozenset({"pm10"}))
"""PM10 particulate matter link (Sber ``sensor_air.pm10``, µg/m³)."""

ROLE_TVOC = LinkableRole("tvoc", frozenset({"sensor"}), frozenset({"volatile_organic_compounds"}))
"""TVOC concentration link (Sber ``sensor_air.tvoc_float``, mg/m³)."""

ROLE_HCHO = LinkableRole("hcho", frozenset({"sensor"}), frozenset({"volatile_organic_compounds_parts"}))
"""Formaldehyde link (Sber ``sensor_air.hcho_float``, mg/m³). HA has no
dedicated device_class for formaldehyde; the closest match is
``volatile_organic_compounds_parts``. Users with a distinct HCHO sensor
will link it manually via the wizard."""
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
python -m pytest tests/hacs/test_devices_sensor_air.py::TestAirQualityRoles -o asyncio_mode=auto --no-cov -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add \
  custom_components/sber_mqtt_bridge/devices/base_entity.py \
  tests/hacs/test_devices_sensor_air.py
git commit -m "feat(devices/base_entity): LinkableRole for air-quality measurements

Six new roles for sensor_air linked entities: co2, pm1, pm25, pm10,
tvoc, hcho. Each ties to the matching HA sensor device_class.
Consumed by SensorAirEntity in the next commit."
```

---

## Task 5: New `SensorAirEntity` class

**Files:**
- Create: `custom_components/sber_mqtt_bridge/devices/sensor_air.py`
- Modify: `tests/hacs/test_devices_sensor_air.py` — full behaviour suite

**Interfaces:**
- Consumes: `SberFeature.*` (Task 3), `ROLE_*` (Task 4), `BaseEntity` (existing), `SENSOR_LINK_ROLES` (existing tuple in base_entity.py at line 199), `make_state`, `make_integer_value`, `make_float_value` from `sber_models`.
- Produces: `SensorAirEntity` class with category `sensor_air`, exports as `SensorAirEntity` — consumed by `sber_entity_map.py` in Task 6.

- [ ] **Step 1: Write failing behaviour tests**

Append to `tests/hacs/test_devices_sensor_air.py`:

```python
from custom_components.sber_mqtt_bridge.devices.sensor_air import (
    SENSOR_AIR_CATEGORY,
    SensorAirEntity,
)


ENTITY_DATA = {
    "entity_id": "sensor.air_quality",
    "name": "Air Quality",
    "original_name": "Air Quality",
    "area_id": "living_room",
}


def _state(value, device_class):
    """Helper to build an HA state dict for a sensor entity."""
    return {
        "entity_id": "sensor.foo",
        "state": str(value),
        "attributes": {"device_class": device_class},
    }


class TestSensorAirBasics:
    def test_category_is_sensor_air(self):
        e = SensorAirEntity(ENTITY_DATA)
        assert e.category == SENSOR_AIR_CATEGORY
        assert SENSOR_AIR_CATEGORY == "sensor_air"

    def test_linkable_roles_include_all_measurements(self):
        role_names = {r.role for r in SensorAirEntity.LINKABLE_ROLES}
        # The eight sensor_air conditional measurements + standard sensor
        # links (battery, battery_low, signal_strength).
        assert {
            "co2", "pm1", "pm25", "pm10", "tvoc", "hcho",
            "temperature", "humidity",
            "battery", "battery_low", "signal_strength",
        }.issubset(role_names)


class TestPrimaryFill:
    """Primary HA sensor state routes into the field matching its
    device_class."""

    @pytest.mark.parametrize(
        "device_class,expected_field,input_state,expected_value",
        [
            ("carbon_dioxide", "_co2", "450", 450),
            ("pm25", "_pm25", "12.4", 12),   # INT truncation ok
            ("pm10", "_pm10", "22", 22),
            ("pm1", "_pm1", "4", 4),
            ("volatile_organic_compounds", "_tvoc", "0.35", pytest.approx(0.35)),
        ],
    )
    def test_primary_state_routes_to_matching_field(
        self, device_class, expected_field, input_state, expected_value
    ):
        e = SensorAirEntity(ENTITY_DATA)
        e.fill_by_ha_state(_state(input_state, device_class))
        assert getattr(e, expected_field) == expected_value

    def test_unknown_state_is_ignored(self):
        e = SensorAirEntity(ENTITY_DATA)
        e.fill_by_ha_state(_state("unknown", "carbon_dioxide"))
        assert e._co2 is None

    def test_unhandled_device_class_leaves_all_fields_none(self):
        e = SensorAirEntity(ENTITY_DATA)
        e.fill_by_ha_state(_state("42", "power"))
        # None of the measurement fields populated.
        for f in ("_co2", "_pm1", "_pm25", "_pm10", "_tvoc", "_hcho",
                  "_temperature", "_humidity"):
            assert getattr(e, f) is None


class TestLinkedFill:
    """Linked entities via update_linked_data fill their own field."""

    @pytest.mark.parametrize(
        "role_name,input_value,expected_field,expected_value",
        [
            ("co2", "600", "_co2", 600),
            ("pm25", "8", "_pm25", 8),
            ("pm10", "15", "_pm10", 15),
            ("pm1", "3", "_pm1", 3),
            ("tvoc", "0.12", "_tvoc", pytest.approx(0.12)),
            ("hcho", "0.04", "_hcho", pytest.approx(0.04)),
            ("humidity", "45", "_humidity", 45),
            ("temperature", "22.5", "_temperature", pytest.approx(22.5)),
        ],
    )
    def test_role_maps_to_field(self, role_name, input_value, expected_field, expected_value):
        e = SensorAirEntity(ENTITY_DATA)
        e.update_linked_data(role_name, _state(input_value, "irrelevant"))
        assert getattr(e, expected_field) == expected_value


class TestToSberCurrentState:
    def test_no_measurements_emits_only_online(self):
        e = SensorAirEntity(ENTITY_DATA)
        e.is_filled_by_state = True
        states = e.to_sber_current_state().get("states", [])
        keys = {s["key"] for s in states}
        assert "online" in keys
        # No measurement features when all fields are None.
        assert not (keys & {
            "co2", "pm1_0", "pm2_5", "pm10", "tvoc_float", "hcho_float",
            "temperature", "humidity",
        })

    def test_only_populated_measurements_emitted(self):
        e = SensorAirEntity(ENTITY_DATA)
        e.is_filled_by_state = True
        e._co2 = 500
        e._pm25 = 10
        keys = {s["key"] for s in e.to_sber_current_state()["states"]}
        assert "co2" in keys
        assert "pm2_5" in keys
        # None values not emitted:
        assert "pm10" not in keys
        assert "hcho_float" not in keys

    def test_temperature_scaled_by_ten(self):
        """Sber wire format for temperature is INTEGER = °C × 10."""
        e = SensorAirEntity(ENTITY_DATA)
        e.is_filled_by_state = True
        e._temperature = 22.5
        temp_entry = next(
            s for s in e.to_sber_current_state()["states"] if s["key"] == "temperature"
        )
        assert temp_entry["value"]["integer_value"] == "225"
```

- [ ] **Step 2: Run behaviour tests to verify they fail**

Run:
```bash
python -m pytest tests/hacs/test_devices_sensor_air.py::TestSensorAirBasics -o asyncio_mode=auto --no-cov -v
```

Expected: `ImportError: cannot import name 'SensorAirEntity'`.

- [ ] **Step 3: Implement `SensorAirEntity`**

Create `custom_components/sber_mqtt_bridge/devices/sensor_air.py`:

```python
"""Sber Air Quality Sensor entity — maps HA air-quality sensors to Sber sensor_air.

Sber category ``sensor_air`` accepts a bundle of measurements from one
physical device: temperature, humidity, CO2, PM1/2.5/10, TVOC, HCHO.
Any subset is valid — spec marks all 8 measurement features as
conditional (``✔︎*``, "at least one of these").

Naследует от BaseEntity напрямую (не от SimpleReadOnlySensor),
потому что у sensor_air нет одной primary-фичи — восемь measurement
полей равноправны и все conditional по спеку Sber. Primary HA entity —
просто «главный» sensor, который пользователь выбрал в wizard; его
device_class определяет, в какое поле пойдёт state.
"""

from __future__ import annotations

import logging
import math

from ..sber_constants import SberFeature
from ..sber_models import make_float_value, make_integer_value, make_state
from .base_entity import (
    BaseEntity,
    ROLE_CO2, ROLE_HCHO, ROLE_HUMIDITY, ROLE_PM1, ROLE_PM10, ROLE_PM25,
    ROLE_TEMPERATURE, ROLE_TVOC, SENSOR_LINK_ROLES,
)

_LOGGER = logging.getLogger(__name__)

SENSOR_AIR_CATEGORY = "sensor_air"
"""Sber device category for the air-quality sensor entity."""

# Map: HA device_class → (internal field, parser). Used both to route
# the primary HA state (fill_by_ha_state) AND to preserve alignment
# between roles and their target fields.
_DEVICE_CLASS_ROUTING: dict[str, tuple[str, type]] = {
    "carbon_dioxide": ("_co2", int),
    "pm1": ("_pm1", int),
    "pm25": ("_pm25", int),
    "pm10": ("_pm10", int),
    "volatile_organic_compounds": ("_tvoc", float),
    "volatile_organic_compounds_parts": ("_hcho", float),
    "temperature": ("_temperature", float),
    "humidity": ("_humidity", int),
}

# Map: linked role name → (internal field, parser).
_ROLE_ROUTING: dict[str, tuple[str, type]] = {
    "co2": ("_co2", int),
    "pm1": ("_pm1", int),
    "pm25": ("_pm25", int),
    "pm10": ("_pm10", int),
    "tvoc": ("_tvoc", float),
    "hcho": ("_hcho", float),
    "humidity": ("_humidity", int),
    "temperature": ("_temperature", float),
}


def _parse_state(raw: str | None, parser: type):
    """Return parser(raw), or None if raw is missing/unavailable/unparseable."""
    if raw in (None, "unknown", "unavailable", ""):
        return None
    try:
        value = parser(float(raw))
    except (TypeError, ValueError):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


class SensorAirEntity(BaseEntity):
    """Sber air-quality sensor: bundles up to eight measurements per device."""

    LINKABLE_ROLES = (
        *SENSOR_LINK_ROLES,
        ROLE_CO2, ROLE_PM1, ROLE_PM25, ROLE_PM10,
        ROLE_TVOC, ROLE_HCHO,
        ROLE_TEMPERATURE, ROLE_HUMIDITY,
    )

    def __init__(self, entity_data: dict) -> None:
        super().__init__(SENSOR_AIR_CATEGORY, entity_data)
        self._co2: int | None = None
        self._pm1: int | None = None
        self._pm25: int | None = None
        self._pm10: int | None = None
        self._tvoc: float | None = None
        self._hcho: float | None = None
        self._temperature: float | None = None
        self._humidity: int | None = None

    def fill_by_ha_state(self, ha_state: dict) -> None:
        """Route the primary HA sensor's state into the field matching its
        device_class. Sensors with an unknown device_class are ignored —
        the wizard should never wire such a sensor as primary, but if
        someone does we degrade gracefully instead of guessing."""
        super().fill_by_ha_state(ha_state)
        attrs = ha_state.get("attributes") or {}
        device_class = attrs.get("device_class")
        routing = _DEVICE_CLASS_ROUTING.get(device_class)
        if routing is None:
            _LOGGER.debug(
                "sensor_air %s: primary HA device_class %r has no measurement mapping",
                self.entity_id, device_class,
            )
            return
        field, parser = routing
        value = _parse_state(ha_state.get("state"), parser)
        setattr(self, field, value)

    def update_linked_data(self, role: str, ha_state: dict) -> None:
        """Fill a specific measurement from a linked HA sensor."""
        super().update_linked_data(role, ha_state)
        routing = _ROLE_ROUTING.get(role)
        if routing is None:
            return
        field, parser = routing
        value = _parse_state(ha_state.get("state"), parser)
        setattr(self, field, value)

    def to_sber_current_state(self) -> dict[str, dict]:
        """Emit ``online`` unconditionally + one state entry per populated
        measurement. Nothing else — the eight measurement features are
        conditional (``✔︎*``) per Sber spec, missing ones are fine."""
        result = super().to_sber_current_state()
        states = result.get("states", [])

        if self._co2 is not None:
            states.append(make_state(SberFeature.CO2, make_integer_value(self._co2)))
        if self._pm1 is not None:
            states.append(make_state(SberFeature.PM1_0, make_integer_value(self._pm1)))
        if self._pm25 is not None:
            states.append(make_state(SberFeature.PM2_5, make_integer_value(self._pm25)))
        if self._pm10 is not None:
            states.append(make_state(SberFeature.PM10, make_integer_value(self._pm10)))
        if self._tvoc is not None:
            states.append(make_state(SberFeature.TVOC_FLOAT, make_float_value(self._tvoc)))
        if self._hcho is not None:
            states.append(make_state(SberFeature.HCHO_FLOAT, make_float_value(self._hcho)))
        if self._temperature is not None:
            # Sber wire spec: temperature is INTEGER = °C × 10.
            states.append(make_state(
                SberFeature.TEMPERATURE,
                make_integer_value(round(self._temperature * 10)),
            ))
        if self._humidity is not None:
            states.append(make_state(SberFeature.HUMIDITY, make_integer_value(self._humidity)))

        result["states"] = states
        return result
```

- [ ] **Step 4: Run all sensor_air tests to verify pass**

Run:
```bash
python -m pytest tests/hacs/test_devices_sensor_air.py -o asyncio_mode=auto --no-cov -v
```

Expected: all tests PASS (~22 tests total).

If `make_float_value` is unresolved — verify signature in `sber_models.py`; adjust import.

If `super().to_sber_current_state()` returns a shape that doesn't include `states` — inspect a sibling class like `SensorTempEntity` for the exact shape and mirror.

- [ ] **Step 5: Commit**

```bash
git add \
  custom_components/sber_mqtt_bridge/devices/sensor_air.py \
  tests/hacs/test_devices_sensor_air.py
git commit -m "feat(devices/sensor_air): SensorAirEntity via Entity Linking

Bundles up to 8 measurements (co2, pm1_0, pm2_5, pm10, tvoc_float,
hcho_float, temperature, humidity) from one HA-side device into a
single Sber sensor_air device. Any subset is valid — spec marks all
eight as conditional (✔︎*)."
```

---

## Task 6: Register `sensor_air` in the factory map

**Files:**
- Modify: `custom_components/sber_mqtt_bridge/sber_entity_map.py`
- Modify: `tests/hacs/test_category_domain_map.py`

**Interfaces:**
- Consumes: `SensorAirEntity` (Task 5), existing `CategorySpec` dataclass (line 93 of sber_entity_map.py), `CategoryUiMeta` (existing).
- Produces: `CATEGORY_DOMAIN_MAP["sensor_air"]` — used by `create_sber_entity()` factory and wizard flow.

- [ ] **Step 1: Write failing test**

Add to `tests/hacs/test_category_domain_map.py` in the appropriate section (find where other sensor_* categories are asserted and slot alongside):

```python
def test_sensor_air_registered_in_category_domain_map():
    """sensor_air must be dispatchable from CATEGORY_DOMAIN_MAP.

    Wizard resolves category via matches(); air-quality HA device_classes
    (carbon_dioxide, pm25, pm10, pm1, volatile_organic_compounds) all
    route to sensor_air.
    """
    from custom_components.sber_mqtt_bridge.sber_entity_map import CATEGORY_DOMAIN_MAP
    from custom_components.sber_mqtt_bridge.devices.sensor_air import SensorAirEntity

    spec = CATEGORY_DOMAIN_MAP.get("sensor_air")
    assert spec is not None, "sensor_air category not registered"
    assert spec.cls is SensorAirEntity
    for dc in ("carbon_dioxide", "pm25", "pm10", "pm1", "volatile_organic_compounds"):
        assert spec.matches("sensor", dc), f"sensor_air should match device_class={dc}"
    # Should not steal ownership of pure temperature sensors from sensor_temp:
    assert not spec.matches("sensor", "temperature")


def test_sensor_air_ranks_above_sensor_temp_for_ambiguous_matches():
    """When a device_class shares nothing with sensor_temp, sensor_air
    should be picked without competition. But there's no ambiguity — this
    is just a sanity guard against a future refactor accidentally putting
    temperature into sensor_air's device_classes."""
    from custom_components.sber_mqtt_bridge.sber_entity_map import CATEGORY_DOMAIN_MAP
    assert "temperature" not in CATEGORY_DOMAIN_MAP["sensor_air"].device_classes
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
python -m pytest tests/hacs/test_category_domain_map.py::test_sensor_air_registered_in_category_domain_map -o asyncio_mode=auto --no-cov -v
```

Expected: FAIL with `AssertionError: sensor_air category not registered`.

- [ ] **Step 3: Register the category**

In `custom_components/sber_mqtt_bridge/sber_entity_map.py`, near the other `sensor_*` entries (around line 296), add:

```python
    "sensor_air": CategorySpec(
        cls=SensorAirEntity,
        domains=("sensor",),
        device_classes=(
            "carbon_dioxide",
            "pm1",
            "pm25",
            "pm10",
            "volatile_organic_compounds",
        ),
        # Lower rank than sensor_temp (30) so a truly ambiguous entity
        # (impossible today — no overlap in device_classes) would prefer
        # sensor_air. Room-quality devices are less common than plain
        # temp sensors, so we still put it below light/relay.
        preferred_rank=25,
    ),
```

Add the import at the top of `sber_entity_map.py`:

```python
from .devices.sensor_air import SensorAirEntity
```

And add the UI meta entry in the `CATEGORY_UI_META` dict (around line 362):

```python
    "sensor_air": CategoryUiMeta("🌫️", "sensors", "Air quality"),
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
python -m pytest tests/hacs/test_category_domain_map.py -o asyncio_mode=auto --no-cov -v
```

Expected: all tests PASS, including the two new ones.

- [ ] **Step 5: Commit**

```bash
git add \
  custom_components/sber_mqtt_bridge/sber_entity_map.py \
  tests/hacs/test_category_domain_map.py
git commit -m "feat(entity_map): register sensor_air category

Wizard now surfaces sensor_air for HA sensors with device_class in
{carbon_dioxide, pm1, pm25, pm10, volatile_organic_compounds}.
preferred_rank=25 (above sensor_temp=30) to remove any ambiguity
if device_classes ever overlap in the future."
```

---

## Task 7: Localization for `sensor_air`

**Files:**
- Modify: `custom_components/sber_mqtt_bridge/strings.json`
- Modify: `custom_components/sber_mqtt_bridge/translations/en.json`
- Modify: `custom_components/sber_mqtt_bridge/translations/ru.json`

**Interfaces:**
- Consumes: `CategoryUiMeta` entry (Task 6) — the string keys used here mirror how sibling categories name themselves.
- Produces: user-facing labels for `sensor_air` category in wizard + role labels for `co2/pm1/pm25/pm10/tvoc/hcho`.

- [ ] **Step 1: Locate existing sensor category strings**

Run:
```bash
grep -n "sensor_temp\|Temperature sensor" custom_components/sber_mqtt_bridge/strings.json custom_components/sber_mqtt_bridge/translations/en.json custom_components/sber_mqtt_bridge/translations/ru.json
```

Note the JSON path where sensor_temp is documented (usually under `options.step.<step>.data.<key>` or a `category_labels` block). Mirror the same structure for sensor_air.

- [ ] **Step 2: Add sensor_air strings to `strings.json`**

Locate the block that contains `"sensor_temp"` in `custom_components/sber_mqtt_bridge/strings.json`. Add an adjacent entry:

```json
"sensor_air": "Air quality sensor"
```

And, in the block that lists role labels (usually alongside `"humidity": "Humidity"`), add:

```json
"co2": "CO₂",
"pm1": "PM1.0",
"pm25": "PM2.5",
"pm10": "PM10",
"tvoc": "TVOC",
"hcho": "Formaldehyde"
```

- [ ] **Step 3: Mirror to `translations/en.json` verbatim**

Run:
```bash
diff custom_components/sber_mqtt_bridge/strings.json custom_components/sber_mqtt_bridge/translations/en.json
```

Add the same entries to `en.json` with identical English text.

- [ ] **Step 4: Add Russian labels to `translations/ru.json`**

Add mirrored entries with Russian values:

```json
"sensor_air": "Датчик качества воздуха",
"co2": "CO₂",
"pm1": "PM1.0",
"pm25": "PM2.5",
"pm10": "PM10",
"tvoc": "TVOC",
"hcho": "Формальдегид"
```

- [ ] **Step 5: Validate JSON files**

Run:
```bash
python -c "import json; [json.load(open(p)) for p in ['custom_components/sber_mqtt_bridge/strings.json','custom_components/sber_mqtt_bridge/translations/en.json','custom_components/sber_mqtt_bridge/translations/ru.json']]; print('OK')"
```

Expected: `OK`. If a JSON parse error appears, fix the syntax.

- [ ] **Step 6: Run hassfest via pytest to catch translation drift**

Run:
```bash
python -m pytest tests/hacs/ -o asyncio_mode=auto --no-cov -k "translations or hassfest" -q
```

Expected: PASS or "no tests ran". If a translation-mirror test fails (some projects have one asserting key parity), fix by ensuring the same keys appear in all three files.

- [ ] **Step 7: Commit**

```bash
git add custom_components/sber_mqtt_bridge/strings.json custom_components/sber_mqtt_bridge/translations/
git commit -m "i18n: sensor_air category + air-quality role labels

Ru: Датчик качества воздуха. En: Air quality sensor.
Roles: co2, pm1, pm25, pm10, tvoc, hcho (chemical symbols in both
locales; hcho localised to Formaldehyde / Формальдегид)."
```

---

## Task 8: P2.1 — `hvac_water_percentage` in `HumidifierEntity`

**Files:**
- Modify: `custom_components/sber_mqtt_bridge/devices/humidifier.py`
- Modify: `tests/hacs/test_devices_humidifier.py`

**Interfaces:**
- Consumes: `SberFeature.HVAC_WATER_PERCENTAGE` (Task 3), existing `AttrSpec` dataclass, existing `to_sber_current_state` structure in humidifier.py.
- Produces: `HumidifierEntity._water_percentage: int | None` — private field, read only within `to_sber_current_state`.

- [ ] **Step 1: Write failing test**

Locate `tests/hacs/test_devices_humidifier.py`. Add:

```python
class TestWaterPercentageTelemetry:
    """P2.1 — pass-through the humidifier's water_level attribute as
    Sber's hvac_water_percentage."""

    def test_water_level_attribute_parsed(self):
        from custom_components.sber_mqtt_bridge.devices.humidifier import HumidifierEntity
        e = HumidifierEntity({
            "entity_id": "humidifier.living_room",
            "name": "Living room",
            "original_name": "Living room",
            "area_id": "living_room",
        })
        e.fill_by_ha_state({
            "entity_id": "humidifier.living_room",
            "state": "on",
            "attributes": {"water_level": 75},
        })
        assert e._water_percentage == 75

    def test_water_level_clamped_to_0_100(self):
        from custom_components.sber_mqtt_bridge.devices.humidifier import HumidifierEntity
        e = HumidifierEntity({
            "entity_id": "humidifier.living_room",
            "name": "Living room",
            "original_name": "Living room",
            "area_id": "living_room",
        })
        e.fill_by_ha_state({
            "entity_id": "humidifier.living_room",
            "state": "on",
            "attributes": {"water_level": 150},
        })
        assert e._water_percentage == 100

    def test_water_level_emitted_in_current_state(self):
        from custom_components.sber_mqtt_bridge.devices.humidifier import HumidifierEntity
        e = HumidifierEntity({
            "entity_id": "humidifier.living_room",
            "name": "Living room",
            "original_name": "Living room",
            "area_id": "living_room",
        })
        e.fill_by_ha_state({
            "entity_id": "humidifier.living_room",
            "state": "on",
            "attributes": {"water_level": 42},
        })
        keys_and_values = {
            s["key"]: s["value"] for s in e.to_sber_current_state()["states"]
        }
        assert keys_and_values["hvac_water_percentage"]["integer_value"] == "42"

    def test_no_water_level_omits_feature(self):
        from custom_components.sber_mqtt_bridge.devices.humidifier import HumidifierEntity
        e = HumidifierEntity({
            "entity_id": "humidifier.living_room",
            "name": "Living room",
            "original_name": "Living room",
            "area_id": "living_room",
        })
        e.fill_by_ha_state({
            "entity_id": "humidifier.living_room",
            "state": "on",
            "attributes": {},
        })
        keys = {s["key"] for s in e.to_sber_current_state()["states"]}
        assert "hvac_water_percentage" not in keys
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
python -m pytest tests/hacs/test_devices_humidifier.py::TestWaterPercentageTelemetry -o asyncio_mode=auto --no-cov -v
```

Expected: FAIL — `assert None == 75`.

- [ ] **Step 3: Add `AttrSpec` for water_level in `humidifier.py`**

Locate `ATTR_SPECS` tuple (line 59 of `custom_components/sber_mqtt_bridge/devices/humidifier.py`). At the end of the tuple (before its closing `)`), add:

```python
        AttrSpec(
            field="_water_percentage",
            attr_keys=("water_level",),
            parser=lambda v: max(0, min(100, int(float(v)))),
            default=None,
        ),
```

Ensure `_water_percentage: int | None = None` is initialized in `HumidifierEntity.__init__` (mirror existing initialization for other AttrSpec-backed fields — see how the class initializes those fields).

- [ ] **Step 4: Emit `hvac_water_percentage` in `to_sber_current_state`**

Locate `HumidifierEntity.to_sber_current_state` method. Inside it (after the existing state entries, before `return`), add:

```python
        if self._water_percentage is not None:
            states.append(make_state(
                SberFeature.HVAC_WATER_PERCENTAGE,
                make_integer_value(self._water_percentage),
            ))
```

(Adjust the variable name if it's called something other than `states` — grep for `.append(make_state(` in the same method to confirm.)

Make sure `SberFeature` and `make_state`/`make_integer_value` are already imported at the top of humidifier.py. If not, add:

```python
from ..sber_constants import SberFeature
from ..sber_models import make_integer_value, make_state
```

- [ ] **Step 5: Run test to verify it passes**

Run:
```bash
python -m pytest tests/hacs/test_devices_humidifier.py::TestWaterPercentageTelemetry -o asyncio_mode=auto --no-cov -v
```

Expected: all 4 tests PASS.

- [ ] **Step 6: Full humidifier tests still pass**

Run:
```bash
python -m pytest tests/hacs/test_devices_humidifier.py -o asyncio_mode=auto --no-cov -q
```

Expected: 0 failures.

- [ ] **Step 7: Commit**

```bash
git add custom_components/sber_mqtt_bridge/devices/humidifier.py tests/hacs/test_devices_humidifier.py
git commit -m "feat(devices/humidifier): forward water_level as hvac_water_percentage

HA humidifiers with a water_level attribute now report tank fullness
to Sber via hvac_water_percentage (INT 0-100). Missing attribute =>
feature omitted (optional per spec). Values are clamped to [0, 100]
to survive quirky HA integrations that report out-of-range values."
```

---

## Task 9: P2.2 — `kitchen_water_temperature` in `KettleEntity`

**Files:**
- Modify: `custom_components/sber_mqtt_bridge/devices/kettle.py`
- Modify: `tests/hacs/test_devices_kettle.py`

**Interfaces:**
- Consumes: `SberFeature.KITCHEN_WATER_TEMPERATURE` (Task 3), existing `AttrSpec`.
- Produces: `KettleEntity._water_temp: float | None` — private field, read only within `to_sber_current_state`.

- [ ] **Step 1: Write failing test**

Locate `tests/hacs/test_devices_kettle.py`. Add:

```python
class TestKitchenWaterTemperatureTelemetry:
    """P2.2 — pass-through the kettle's current water temperature as
    Sber's kitchen_water_temperature (INTEGER = °C × 10)."""

    def test_current_temperature_attribute_parsed(self):
        from custom_components.sber_mqtt_bridge.devices.kettle import KettleEntity
        e = KettleEntity({
            "entity_id": "water_heater.kettle",
            "name": "Kettle",
            "original_name": "Kettle",
            "area_id": "kitchen",
        })
        e.fill_by_ha_state({
            "entity_id": "water_heater.kettle",
            "state": "on",
            "attributes": {"current_temperature": 85.0},
        })
        assert e._water_temp == 85.0

    def test_temperature_attribute_fallback(self):
        """Some HA integrations use `temperature` instead of `current_temperature`."""
        from custom_components.sber_mqtt_bridge.devices.kettle import KettleEntity
        e = KettleEntity({
            "entity_id": "water_heater.kettle",
            "name": "Kettle",
            "original_name": "Kettle",
            "area_id": "kitchen",
        })
        e.fill_by_ha_state({
            "entity_id": "water_heater.kettle",
            "state": "on",
            "attributes": {"temperature": 90.5},
        })
        assert e._water_temp == 90.5

    def test_temperature_emitted_as_int_times_ten(self):
        from custom_components.sber_mqtt_bridge.devices.kettle import KettleEntity
        e = KettleEntity({
            "entity_id": "water_heater.kettle",
            "name": "Kettle",
            "original_name": "Kettle",
            "area_id": "kitchen",
        })
        e.fill_by_ha_state({
            "entity_id": "water_heater.kettle",
            "state": "on",
            "attributes": {"current_temperature": 22.5},
        })
        entry = next(
            s for s in e.to_sber_current_state()["states"]
            if s["key"] == "kitchen_water_temperature"
        )
        assert entry["value"]["integer_value"] == "225"

    def test_missing_temperature_omits_feature(self):
        from custom_components.sber_mqtt_bridge.devices.kettle import KettleEntity
        e = KettleEntity({
            "entity_id": "water_heater.kettle",
            "name": "Kettle",
            "original_name": "Kettle",
            "area_id": "kitchen",
        })
        e.fill_by_ha_state({
            "entity_id": "water_heater.kettle",
            "state": "on",
            "attributes": {},
        })
        keys = {s["key"] for s in e.to_sber_current_state()["states"]}
        assert "kitchen_water_temperature" not in keys
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
python -m pytest tests/hacs/test_devices_kettle.py::TestKitchenWaterTemperatureTelemetry -o asyncio_mode=auto --no-cov -v
```

Expected: FAIL.

- [ ] **Step 3: Add `AttrSpec` for water_temp in `kettle.py`**

Locate `ATTR_SPECS` tuple (line 38 of `custom_components/sber_mqtt_bridge/devices/kettle.py`). At the end of the tuple (before its closing `)`), add:

```python
        AttrSpec(
            field="_water_temp",
            attr_keys=("current_temperature", "temperature"),
            parser=float,
            default=None,
        ),
```

Ensure `_water_temp: float | None = None` is initialized in `KettleEntity.__init__` (mirror existing initialization for other AttrSpec-backed fields).

- [ ] **Step 4: Emit `kitchen_water_temperature` in `to_sber_current_state`**

Locate `KettleEntity.to_sber_current_state` (line 114 of `custom_components/sber_mqtt_bridge/devices/kettle.py`). Add before the return:

```python
        if self._water_temp is not None and math.isfinite(self._water_temp):
            states.append(make_state(
                SberFeature.KITCHEN_WATER_TEMPERATURE,
                make_integer_value(round(self._water_temp * 10)),
            ))
```

Add `import math` at the top of kettle.py if not already present. Ensure `SberFeature`, `make_state`, `make_integer_value` are imported (add if missing).

- [ ] **Step 5: Run test to verify it passes**

Run:
```bash
python -m pytest tests/hacs/test_devices_kettle.py::TestKitchenWaterTemperatureTelemetry -o asyncio_mode=auto --no-cov -v
```

Expected: all 4 tests PASS.

- [ ] **Step 6: Full kettle tests still pass**

Run:
```bash
python -m pytest tests/hacs/test_devices_kettle.py -o asyncio_mode=auto --no-cov -q
```

Expected: 0 failures.

- [ ] **Step 7: Commit**

```bash
git add custom_components/sber_mqtt_bridge/devices/kettle.py tests/hacs/test_devices_kettle.py
git commit -m "feat(devices/kettle): forward water temperature as kitchen_water_temperature

HA kettles with a current_temperature (or temperature) attribute now
report water temperature to Sber via kitchen_water_temperature
(INTEGER = °C × 10). Missing attribute => feature omitted."
```

---

## Task 10: Compliance-test coverage for sensor_air payload

**Files:**
- Modify: `tests/hacs/test_sber_compliance_sensors_covers_tv.py`

**Interfaces:**
- Consumes: `SensorAirEntity` (Task 5), `sber_full_spec.json` (Task 2), existing validator entrypoints in the compliance-test module.
- Produces: assertion that a fully-populated `SensorAirEntity` produces a payload that satisfies Sber's schema constraints (features ⊂ all_features, obligatory ⊆ features).

- [ ] **Step 1: Locate the existing compliance test pattern**

Run:
```bash
grep -n "sensor_temp\|SensorTempEntity" tests/hacs/test_sber_compliance_sensors_covers_tv.py | head -20
```

Note the pattern used for sensor_temp. Mirror it for sensor_air.

- [ ] **Step 2: Add sensor_air compliance test**

Append the following method into the appropriate `TestClass` in `tests/hacs/test_sber_compliance_sensors_covers_tv.py` (find the class that groups sensor tests):

```python
def test_sensor_air_payload_matches_spec(self):
    """A SensorAirEntity with every measurement populated must produce
    a payload whose feature list is a subset of all_features and whose
    emitted features cover the strict-obligatory set."""
    import json
    from pathlib import Path

    from custom_components.sber_mqtt_bridge.devices.sensor_air import SensorAirEntity

    entity = SensorAirEntity({
        "entity_id": "sensor.air_quality",
        "name": "Air Quality",
        "original_name": "Air Quality",
        "area_id": "living_room",
    })
    entity.is_filled_by_state = True
    # Populate every measurement to test the maximal-payload case.
    entity._co2 = 500
    entity._pm1 = 3
    entity._pm25 = 8
    entity._pm10 = 15
    entity._tvoc = 0.12
    entity._hcho = 0.03
    entity._temperature = 22.5
    entity._humidity = 45

    payload = entity.to_sber_current_state()
    emitted = {s["key"] for s in payload["states"]}

    spec = json.loads(
        Path("tests/hacs/__snapshots__/sber_full_spec.json").read_text()
    )
    air = spec["categories"]["sensor_air"]
    all_features = set(air["all_features"])
    obligatory = set(air["obligatory"])

    # Every emitted key must be a known Sber feature for sensor_air.
    assert emitted <= all_features, (
        f"SensorAirEntity emitted unknown features: {emitted - all_features}"
    )
    # Strict obligatory ({online}) must be present.
    assert obligatory <= emitted, (
        f"Missing strict-obligatory features: {obligatory - emitted}"
    )
```

- [ ] **Step 3: Run test**

Run:
```bash
python -m pytest tests/hacs/test_sber_compliance_sensors_covers_tv.py -o asyncio_mode=auto --no-cov -v -k sensor_air
```

Expected: PASS.

- [ ] **Step 4: Full compliance suite still passes**

Run:
```bash
python -m pytest tests/hacs/test_sber_compliance_sensors_covers_tv.py -o asyncio_mode=auto --no-cov -q
```

Expected: 0 failures.

- [ ] **Step 5: Commit**

```bash
git add tests/hacs/test_sber_compliance_sensors_covers_tv.py
git commit -m "test(compliance): sensor_air payload matches 2026-05 Sber spec

Guards against future refactors that might silently drop features or
add ones Sber doesn't accept."
```

---

## Task 11: Release v1.40.0

**Files:**
- Modify: `custom_components/sber_mqtt_bridge/manifest.json`
- Modify: `custom_components/sber_mqtt_bridge/sber_protocol.py`
- Modify: `pyproject.toml`
- Modify: `CHANGELOG.md`

**Interfaces:** none new — this task closes the release.

- [ ] **Step 1: Draft release notes in `[Unreleased]` first**

Open `CHANGELOG.md` and populate `[Unreleased]` with the release-worthy bullets:

```markdown
## [Unreleased]

### Added
- **New Sber category `sensor_air`** — air-quality sensor with up to 8
  measurements per device (CO₂, PM1/2.5/10, TVOC, formaldehyde,
  temperature, humidity). Uses Entity Linking to bundle multiple HA
  `sensor.*` entities into one Sber device.
- **`hvac_water_percentage`** — humidifiers now report tank fullness
  via the HA `water_level` attribute.
- **`kitchen_water_temperature`** — kettles now report current water
  temperature via HA `current_temperature` / `temperature` attributes.

### Changed
- **Relaxed obligatory features** for `sensor_temp`, `curtain`, `gate`,
  `valve`, `window_blind`. The 2026-05 Sber spec reclassified
  `humidity`/`temperature` (for sensor_temp) and `open_percentage`/
  `open_set` (for covers) from strict-mandatory (`✔︎`) to conditional
  (`✔︎*`, "at least one of these"). Our local validator no longer
  false-rejects devices that only expose the other member of the
  conditional group — e.g. a temperature-only HA sensor without
  humidity is now accepted.
- **Scraper (`tools/fetch_sber_schemas.py`)** hardened: inverse-index
  for feature↔category links (replaces fragile text parsing), split
  ✔︎ vs ✔︎* marker, Phase 0b browserless discovery via Docusaurus
  webpack manifest. Snapshots regenerated with correct data.
```

- [ ] **Step 2: Bump versions using the helper script**

Run:
```bash
python tools/bump_version.py minor
```

Expected output:
```
current: 1.39.8
new:     1.40.0
  pyproject.toml: 1.39.8 -> 1.40.0
  custom_components/sber_mqtt_bridge/manifest.json: 1.39.8 -> 1.40.0
  custom_components/sber_mqtt_bridge/sber_protocol.py: 1.39.8 -> 1.40.0
  CHANGELOG.md: [Unreleased] -> [1.40.0] - <today>
```

- [ ] **Step 3: Verify all four locations agree**

Run:
```bash
python tools/bump_version.py --current
```

Expected: `1.40.0`.

- [ ] **Step 4: Full test suite**

Run:
```bash
python -m pytest tests/hacs/ -o asyncio_mode=auto -n auto --no-cov -k "not test_config_flow" -q
```

Expected: 0 failures.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml custom_components/sber_mqtt_bridge/manifest.json \
        custom_components/sber_mqtt_bridge/sber_protocol.py CHANGELOG.md
git commit -m "chore: release v1.40.0

Adds sensor_air category + hvac_water_percentage + kitchen_water_temperature.
Relaxes local obligatory-feature validation to match Sber's 2026-05
spec update. See CHANGELOG for full details."
```

- [ ] **Step 6: Push + tag + push tag**

Run:
```bash
git push github main
git tag v1.40.0
git push github v1.40.0
```

- [ ] **Step 7: Verify release CI succeeded**

Run:
```bash
gh run watch $(gh run list --workflow=release.yaml --limit 1 --json databaseId -q '.[0].databaseId') --exit-status
gh release view v1.40.0 --json assets -q '.assets[].name'
```

Expected: workflow success; `sber_mqtt_bridge.zip` and `sber_mqtt_bridge.zip.sigstore` present in the release.

---

## Post-release checklist

- [ ] HACS Downloads counter starts incrementing (see badge in README; may take ~5 min for shields.io cache).
- [ ] No new drift warnings from the weekly `sber-compliance` cron.
- [ ] `AckAudit` telemetry over the next week doesn't spike — if silent rejections cluster around conditional-only devices, revisit Decision D1 (add optional conditional-validation).

---

## Deferred (explicitly out of scope for this plan)

- `channel` / `channel_int` for `tv`
- `open_left_set` / `open_right_state` for two-panel curtain/gate
- `hvac_water_low_level` (BOOL) for humidifier
- Full pydantic-level conditional validation (variant B from spec D1)
