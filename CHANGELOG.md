# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.11.1] - 2026-03-26

### Fixed
- **Entity links badges**: links now always visible in panel after HA restart — previously `_entity_links` was empty until any link was re-saved because `_load_exposed_entities` skipped links when linked entity state was not yet available
- **Panel callWS crash**: fixed `Cannot read properties of undefined (reading 'callWS')` in `sber-panel.js` and `sber-devtools.js` — `connectedCallback` called WS before HA set `hass` property; now deferred to `updated()` lifecycle

## [1.11.0] - 2026-03-26

### Added
- **Device Detail Dialog**: click entity name in device table to see full overview — Sber states table, linked entities with current values, model config (allowed_values, dependencies), HA attributes, device registry info, redefinitions
- **WS endpoint** `sber_mqtt_bridge/device_detail`: returns comprehensive data for a single entity

### Changed
- **Documentation**: full rewrite of README.md, README_ENG.md, and 7 docs files updated to v1.10.3+ — 28 categories, Sidebar Panel, DevTools, Entity Linking, typed constants, Pydantic helpers

## [1.10.3] - 2026-03-26

### Fixed
- **online status**: per-sensor-type `unknown` handling — event-based binary_sensors (motion, door, water_leak, smoke, gas) treat `unknown` as online (device reachable, no events yet); value-based sensors (temperature, humidity) and all other entities treat `unknown` as offline (prevents reporting fake 0°C/0% to Sber)

## [1.10.2] - 2026-03-26

### Fixed
- **online status**: `unknown` state now treated as online — event-based sensors (motion, water_leak, door) no longer falsely show "Offline" when they simply haven't triggered yet; only `unavailable` means truly offline

## [1.10.1] - 2026-03-26

### Fixed
- **entity linking**: links not displayed after HA restart — `EVENT_HOMEASSISTANT_STARTED` listener never fired on integration reload; now checks `hass.is_running` and reloads immediately
- **UI**: entities show yellow "Loading..." badge instead of grey "Offline" when state not yet received (prevents false alarm during startup/reload)
- **UI**: row dimming skipped for entities in loading state

## [1.10.0] - 2026-03-25

### Added
- **sber_constants.py**: new module with StrEnum typed constants — `SberValueType`, `SberFeature` (61 feature keys), `HAState`, `MqttTopicSuffix`; eliminates raw string literals, enables IDE autocomplete
- **HA Context propagation**: Sber commands now include HA `Context` in service calls — proper logbook attribution ("triggered by Sber Smart Home")
- **Echo loop prevention**: state changes caused by Sber commands detected via context ID and not re-published back (bounded set, max 200)
- **Value change diffing**: `BaseEntity.has_significant_change()` compares current Sber state with last published — skips unnecessary MQTT publishes when only irrelevant HA attributes changed; `force=True` for status_request responses

### Changed
- **All 20 device files**: migrated to Pydantic helpers (`make_state`, `make_bool_value`, `make_integer_value`, `make_enum_value`, `make_colour_value`) with `SberFeature` constants instead of inline dicts
- **sber_models.py**: `make_integer_value()` now outputs `str(value)` per Sber C2C specification
- **sber_bridge.py**: MQTT topic routing uses `MqttTopicSuffix` constants instead of hardcoded strings

## [1.9.1] - 2026-03-25

### Fixed
- **entity linking**: split battery link role — `sensor.battery` (%) → `battery` role, `binary_sensor.battery_low` (bool) → `battery_low` role; both can now be linked simultaneously
- **entity linking**: removed incorrect `moisture` → `humidity` mapping (moisture binary_sensor is a leak detector, not a humidity sensor)
- **entity linking**: added curtain, window_blind, gate, valve to linkable categories for battery/signal from separate HA entities

### Added
- **curtain**: `update_linked_data` for linked battery, battery_low, signal_strength entities; battery_percentage/battery_low_power features when battery data available
- **valve**: `update_linked_data` for linked battery, battery_low, signal_strength entities
- **simple_sensor**: `battery_low` linked role support — uses linked binary_sensor value for `battery_low_power` when available

## [1.9.0] - 2026-03-25

### Fixed
- **light**: fixed fallback color conversion in `process_cmd` — was using `ha_to_sber_hsv` instead of zero tuple, causing brightness=100 instead of 0 on malformed commands
- **light**: `light_mode` command now sends HA service call to actually switch lamp mode (was only updating local state, lamp stayed in previous mode)
- **light**: fixed docstring brightness range — was "50-1000", corrected to "100-900" per Sber spec
- **hvac_fan**: added missing `"quiet"` to `SBER_SPEED_VALUES` per Sber C2C specification; adjusted percentage thresholds for 5-speed mapping
- **climate**: fan modes now mapped through `HA_TO_SBER_FAN_MODE` dict instead of raw passthrough — ensures Sber-standard enum values (auto, low, medium, high, turbo, quiet) in `allowed_values` and state reports
- **climate**: reverse fan mode mapping in `process_cmd` — finds matching HA fan_mode for Sber enum values
- **curtain**: enforced open_state ↔ open_percentage consistency — if percentage > 0, state forced to "open"; if 0, forced to "close"

### Added
- **valve**: battery_percentage, battery_low_power, and signal_strength features — reads from HA attributes (battery, rssi, linkquality)
- **utils/signal.py**: shared `rssi_to_signal_strength()` function — extracted from duplicated code in simple_sensor.py and curtain.py
- **base_entity**: `create_allowed_values_list()` and `create_dependencies()` hook methods — unified pattern for all subclasses, eliminates `to_sber_state()` overrides
- **climate**: `HA_TO_SBER_FAN_MODE` mapping dict with 20+ HA fan mode names → Sber standard values
- **__init__**: `async_remove_entry()` — cleans up `hass.data[DOMAIN]` when last config entry is removed

### Changed
- **architecture**: all `to_sber_state()` overrides in subclasses removed — `allowed_values` and `dependencies` now injected via base class hooks
- **simple_sensor/curtain**: `_rssi_to_signal_strength` static method replaced with shared `utils.signal.rssi_to_signal_strength()`
- **linear_converter**: class-level attributes moved to `__init__` — prevents potential shared state between instances
- **config_flow**: removed emoji from Options Flow selector labels — follows HA style guide

## [1.8.1] - 2026-03-25

### Fixed
- **light**: `light_brightness` allowed_values now `min=100, max=900, step=1` per Sber spec (was `min=50, max=1000`, no step)
- **light**: dependencies key `"values"` renamed to `"value"` per Sber C2C specification
- **light**: brightness-only lamps (no color) now correctly report `light_brightness` feature
- **hvac_heater**: restored `hvac_air_flow_power` and `hvac_thermostat_mode` features per Sber spec (were incorrectly disabled)
- **hvac_radiator/boiler/underfloor**: temperature step now matches Sber spec (`step=5` instead of `step=1`)
- **kettle**: added missing `kitchen_water_level` feature per Sber spec
- **climate**: `temp_step` parameter added to `ClimateEntity.__init__` for per-category temperature step

## [1.8.0] - 2026-03-25

### Fixed
- **HVAC radiator/boiler/underfloor**: removed incorrect `hvac_work_mode` and `hvac_air_flow_power` features per Sber spec; boiler and underfloor now use `hvac_thermostat_mode` instead of `hvac_work_mode`
- **Entity linking**: `suggest_links` now returns candidates from ALL devices (not just same device), grouped by `same_device` flag; fixes linking battery/signal sensors from different HA devices
- **Link dialog**: error messages now shown instead of silent "No related entities" on WS failure
- **Type safety**: all `int()`/`float()` conversions in `process_cmd` wrapped with `_safe_int()`/`_safe_float()` — prevents crashes on malformed Sber payloads (light, curtain, climate, humidifier, tv, kettle)
- **None-safety**: `attrs.get("fan_modes", [])` → `or []` pattern across climate, light, humidifier — prevents crash when HA sends explicit `null`
- **Enum passthrough**: `hvac_work_mode`, `hvac_air_flow_direction` no longer pass unknown values to Sber/HA — only mapped enums accepted
- **sber_protocol.py**: `parse_sber_status_request` handles `devices: null` without crash
- **sber_bridge.py**: `_linked_entities` moved to BaseEntity — prevents AttributeError when linking non-sensor entities
- **sber_bridge.py**: `_handle_change_group` now merges redefinitions instead of overwriting (preserves device name)
- **Test fix**: `test_cmd_hvac_mode_valid` now sends Sber enum `"heating"` instead of HA value `"heat"`

### Added
- `BaseEntity._safe_float()` and `BaseEntity._safe_int()` static helper methods for defensive type conversion
- Class-level feature flags on ClimateEntity: `_supports_fan`, `_supports_swing`, `_supports_work_mode`, `_supports_thermostat_mode`
- `HA_TO_SBER_THERMOSTAT_MODE` / `SBER_TO_HA_THERMOSTAT_MODE` mapping dicts in climate.py
- `_create_media_player()` factory function in sber_entity_map.py (documents speaker/receiver → tv mapping)
- Link dialog: "Same device" / "Other devices" section grouping for candidates
- `docs/ENTITY_REGISTRY.md` — full entity reference
- `docs/AUDIT_REPORT.md` — Sber protocol compliance audit

## [1.7.0] - 2026-03-25

### Added
- **Entity type preview** wizard step in Options Flow — shows all exposed entities grouped by Sber device type before editing
- Entity count summary with type breakdown displayed on the init step (with `---` divider)
- Preview is the first (default) option in the settings menu
- Entities with manual type overrides marked with ✏️ in preview
- Pre-alpha warning banner in README.md and README_ENG.md

## [1.6.2] - 2026-03-24

### Changed
- **Atomic wizard endpoint** `add_device_wizard` — single WS call replaces triple add+override+links (one reload instead of three)
- **Shared utils** — `filterEntities()` and `DIALOG_STYLES_CSS` extracted to `utils.js`, used by wizard and add-dialog
- **`ws_bulk_add` deduplication** — now uses same device_id deduplication as Options Flow (light > switch priority)
- **`ws_clear_all` cleanup** — now also clears `entity_links`
- **Cleaned .gitignore** — removed duplicates, added egg-info exclusion

## [1.6.1] - 2026-03-24

### Added
- **Link Dialog** for existing devices — chain icon button in device table opens link management
- **Auto-Link All** button in toolbar dropdown — auto-links battery/signal/humidity for all exposed devices
- **Auto-republish** config when features list changes due to linked entity state update
- **Broken link detection** — HA Repairs issue for linked entities that no longer exist
- **Circular link validation** — prevents linking entity to itself or to another primary
- **Config migration v2→v3** — initializes `entity_links: {}` on upgrade
- **13 entity linking tests** — coverage for linked battery, humidity, temperature, signal, features change

### Fixed
- `suggest_links` now accepts explicit `category` from wizard (entity not yet in bridge)

## [1.6.0] - 2026-03-24

### Added
- **Entity Linking**: link auxiliary HA entities (battery, humidity, temperature, signal) to a primary Sber device
- **Auto-detection in Wizard**: Step 2 shows related entities from the same physical device with compatibility info
- **`suggest_links` WS command**: auto-detects linkable entities by shared `device_id` and `device_class`
- **`set_entity_links` WS command**: save/remove entity links with validation
- **Linked entity state tracking**: state changes from linked entities propagate to primary device
- **Device table linked badge**: shows link count (chain icon) next to device name
- **Export/import v2**: entity_links included in export payload

### Changed
- Available entities list now filters out linked entities (they won't appear in Add dialog or Wizard)
- Remove entities also cleans up associated entity links
- Sensor entities (`SimpleReadOnlySensor`) support `update_linked_data()` for battery/signal injection
- `SensorTempEntity` supports linked humidity feature
- `HumiditySensorEntity` supports linked temperature feature

## [1.5.3] - 2026-03-24

### Fixed
- **Humidifier uses `hvac_air_flow_power`** instead of `hvac_work_mode` — per Sber `hvac_humidifier` docs
- **Humidifier mode mapping**: HA modes (`Low`→`low`, `Mid`→`medium`, `High`→`high`, `Auto`→`auto`, `boost`→`turbo`, `sleep`→`quiet`)
- **Humidifier `hvac_humidity_set`** added to features — target humidity now settable from Sber
- **Humidifier `humidity` state** now sends `current_humidity` (reading), `hvac_humidity_set` sends target
- **Binary sensor `occupancy`/`presence`** mapped to `sensor_pir` (was unmapped → null)
- **Binary sensor `opening`** mapped to `sensor_door`
- **Binary sensor `water`** mapped to `sensor_water_leak`

### Changed
- Added critical Sber protocol rule to CLAUDE.md — always check docs before implementing device types

## [1.5.2] - 2026-03-24

### Fixed
- **Climate hvac_work_mode mapping**: HA modes now mapped to Sber values (`cool`→`cooling`, `heat`→`heating`, `fan_only`→`ventilation`, `dry`→`dehumidification`, `heat_cool`→`auto`). Mode `off` excluded from work modes (handled by `on_off`)
- **Climate swing_mode mapping**: HA swing modes mapped to Sber values (`off`→`no`, `both`→`rotation`)
- **Bidirectional mode mapping**: Sber commands correctly reverse-mapped back to HA modes
- **sber_name override for linked devices**: fixed name not applying when device has registry entry

## [1.5.1] - 2026-03-24

### Fixed
- **failed_unload crash**: replaced deprecated `hass.components.frontend.async_remove_panel` with proper import
- **repairs.py crash**: `bridge.stats` returns dict, not object — fixed attribute access
- **sber_name ignored for linked devices**: YAML name override now applies to devices with device registry entries
- **Disconnected status after reload**: fixed `failed_unload` state caused by panel removal error
- **DevTools clipboard crash**: fallback copy method for non-secure contexts (no `navigator.clipboard`)
- **Unacknowledged count mismatch**: acknowledged count now filters to current exposed entities only

### Changed
- **Removed `hass.data[DOMAIN]["bridge"]`**: WebSocket API now uses `entry.runtime_data` exclusively
- **WebSocket idempotent registration**: guard prevents duplicate command registration on reload
- **Public bridge API**: added `async_republish()` and `async_publish_entity_status()` — WebSocket API no longer calls private methods
- **Public feature attributes**: renamed `_extra_features`/`_removed_features` to public attributes
- **`device_class` → `original_device_class`**: fixed deprecated attribute usage in available entities list
- **Removed `hasattr(entry, "labels")`**: unnecessary compatibility guard for HA 2023.4+
- **Config flow**: added `ConfigEntry` type annotation to `async_get_options_flow`
- **DevTools payloads collapsible**: Raw Config/State sections now collapse/expand on click

## [1.5.0] - 2026-03-23

### Added
- **DevTools tab** in SPA panel for MQTT protocol debugging
- **Raw Config Payload** viewer: loads and displays the full JSON sent to Sber `up/config` topic
- **Raw State Payload** viewer: loads and displays the full JSON sent to Sber `up/status` topic
- **MQTT Message Log**: real-time ring buffer of last 50 MQTT messages (incoming/outgoing) with auto-refresh
- New WS commands: `sber_mqtt_bridge/raw_config`, `sber_mqtt_bridge/raw_states`, `sber_mqtt_bridge/message_log`, `sber_mqtt_bridge/clear_message_log`
- Copy-to-clipboard for JSON payloads
- Color-coded message direction (blue=incoming, green=outgoing)

## [1.4.1] - 2026-03-23

### Fixed
- **Light color mode mapping**: support hs/rgb/rgbw/rgbww color modes (not just xy) for Sber colour features
- **Climate turbo/quiet preset**: map Sber turbo/quiet air flow power to HA boost/sleep preset modes
- **Cover opening/closing states**: correctly map HA transitional states (opening/closing) to Sber open_state
- **Wizard "already added" badge**: entities already exposed to Sber are visually marked in the Add Device wizard

## [1.4.0] - 2026-03-23

### Added
- **Add Device Wizard** (`sber-wizard.js`): 3-step guided flow for adding devices (type selection with icon cards, entity picker with search, Salut name validation + auto-slug ID)
- **Related sensors auto-detection**: new WS command `sber_mqtt_bridge/related_sensors` finds power, current, voltage, battery, temperature sensors by shared device_id
- **Publish one device**: new WS command `sber_mqtt_bridge/publish_one_status` to sync a single entity to Sber cloud; sync button on each device row
- **Export / Import**: new WS commands `sber_mqtt_bridge/export` and `sber_mqtt_bridge/import` for backing up and restoring device configuration as JSON
- **Toast notifications** (`sber-toast.js`): lightweight popup for success/error/info feedback on all panel actions
- **Slugify utility** (`utils.js`): Cyrillic-to-Latin transliteration for generating Sber device IDs
- **Salut name validation**: regex check for 3-33 character Cyrillic device names
- **Row coloring**: device table rows tinted green (online) or red (offline)
- **Toolbar buttons**: Wizard, Export, Import added to the action bar

## [1.3.0] - 2026-03-23

### Added
- **SPA Panel decomposition**: split monolithic `sber-panel.js` into 6 component files (`sber-device-table`, `sber-status-card`, `sber-stats-grid`, `sber-add-dialog`, `sber-entity-row`, `sber-toolbar`)
- **WebSocket API — entity management**: 6 new WS commands for full device lifecycle from the panel
  - `sber_mqtt_bridge/available_entities` — list HA entities available for export
  - `sber_mqtt_bridge/add_entities` — add entities to exposed list
  - `sber_mqtt_bridge/remove_entities` — remove entities from exposed list
  - `sber_mqtt_bridge/set_override` — set/clear Sber category override per entity
  - `sber_mqtt_bridge/bulk_add` — bulk add entities by domain or all
  - `sber_mqtt_bridge/clear_all` — remove all entities and overrides
- **Device table**: sortable columns, text search/filter, bulk selection with checkboxes, inline delete and category override dropdown
- **Add dialog**: modal for selecting entities with domain grouping, search filter, multi-select, "Add All" / "Add Selected" actions
- **Toolbar**: action bar with Refresh, Re-publish, Add Devices, Bulk Actions dropdown, live connection indicator and device counter

## [1.1.0] - 2026-03-23

### Added
- **HA Repairs**: issue registry integration for missing entities, stateless entities, and persistent connection failures (`repairs.py`)
- **Feature overrides**: `sber_features_add` / `sber_features_remove` YAML options to customize Sber features per entity
- **Auto re-publish config**: bridge automatically re-publishes config when Sber asks about unknown entities
- **Persist redefinitions**: Sber room/name overrides now saved to config entry options and survive restarts
- **Features info in UI**: entity type overrides step now shows detected Sber features for each entity (read-only)
- `get_final_features_list()` method in `BaseEntity` for applying feature overrides
- `_persist_redefinitions()` in `SberBridge` for saving redefinitions to entry options
- Repair issue translations in English and Russian

## [1.0.0] - 2026-03-23

### Added
- **pydantic validation**: `build_devices_list_json()` and `build_states_list_json()` now validate output payloads via `validate_config_payload()` / `validate_status_payload()` (pydantic models from `sber_models.py`)
- **partner_meta**: new `sber_partner_meta` YAML option for arbitrary key-value metadata passed to Sber (`EntityCustomConfig.sber_partner_meta`, `BaseEntity.partner_meta`); included in `to_sber_state()` output and `SberDevice` pydantic model
- **CI/CD**: GitHub Actions workflows for HACS validation (`hacs.yml`), Hassfest (`hassfest.yml`), and full CI pipeline (`ci.yaml`) with lint, test (Python 3.13 + 3.14 matrix), hassfest, and HACS validation
- **multi-version testing**: CI test matrix runs on Python 3.13 and 3.14

## [0.9.2] - 2026-03-23

### Added
- **dependencies**: `LightEntity.to_sber_state()` now includes `dependencies` block when light supports colour mode (light_colour depends on light_mode == "colour")
- **allowed_values**: added `allowed_values` to `ValveEntity` (open_set ENUM), `CurtainEntity` (open_set ENUM + open_percentage INTEGER), `ScenarioButtonEntity` (button_event ENUM), `ClimateEntity` (hvac_temp_set INTEGER), and `HumidifierEntity` (hvac_humidity_set INTEGER)
- **nicknames**: new `sber_nicknames` YAML option for alternative voice names in Sber (`EntityCustomConfig.sber_nicknames`, `BaseEntity.nicknames`)
- **groups**: new `sber_groups` YAML option for device groups in Sber (`EntityCustomConfig.sber_groups`, `BaseEntity.groups`)
- **parent_id**: new `sber_parent_id` YAML option for hub-device hierarchy (`EntityCustomConfig.sber_parent_id`, `BaseEntity.parent_entity_id`)
- 30 new tests covering all P2 structural improvements

## [0.9.1] - 2026-03-23

### Added
- **air_pressure**: `SensorTempEntity` now reports `air_pressure` (INTEGER) when HA entity has `pressure` attribute
- **signal_strength**: `SimpleReadOnlySensor` and `CurtainEntity` now report `signal_strength` (ENUM: high/medium/low) from `rssi`, `signal_strength`, or `linkquality` HA attributes
- **tamper_alarm**: `DoorSensorEntity` and `MotionSensorEntity` now report `tamper_alarm` (BOOL) when HA entity has `tamper` attribute
- **battery_low_power**: `SimpleReadOnlySensor` now reports `battery_low_power` (BOOL, true when battery < 20%) alongside `battery_percentage`
- **child_lock**: `OnOffEntity` (relay/socket) now reports `child_lock` (BOOL) when HA entity has `child_lock` attribute
- **hvac_humidity_set**: `ClimateEntity` now supports `hvac_humidity_set` (INTEGER 0-100) for target humidity control
- **hvac_night_mode**: `ClimateEntity` and `HumidifierEntity` now support `hvac_night_mode` (BOOL) mapped to sleep/night preset modes
- 54 new tests covering all added features

## [0.9.0] - 2026-03-23

### Added
- **hvac_air_purifier**: new air purifier entity (Sber `hvac_air_purifier` category) mapped from HA `fan` with `purifier`/`air_purifier` device class
- **kettle**: new smart kettle entity (Sber `kettle` category) mapped from HA `water_heater`
- **tv**: new TV entity (Sber `tv` category) mapped from HA `media_player` — supports volume, mute, source selection
- **vacuum_cleaner**: new vacuum cleaner entity (Sber `vacuum_cleaner` category) mapped from HA `vacuum` — supports start/stop/pause/return_to_base, fan speed, battery
- **intercom**: new intercom entity (Sber `intercom` category) — available via type override only, supports on/off and read-only call features
- Added `media_player` and `vacuum` to `SUPPORTED_DOMAINS`
- Added all 5 new categories to `OVERRIDABLE_CATEGORIES` and `CATEGORY_CONSTRUCTORS`
- Fan device_class routing: `purifier`/`air_purifier` → `HvacAirPurifierEntity`, default → `HvacFanEntity`

## [0.8.0] - 2026-03-23

### Fixed
- **valve**: replaced incorrect `on_off` feature with `open_set`/`open_state` per Sber specification (ENUM open/close/stop)

### Added
- **led_strip**: new `LedStripEntity` for LED strip devices (same features as light, different category)
- **sensor_smoke**: new `SmokeSensorEntity` for smoke detector binary sensors (`smoke_state` BOOL)
- **sensor_gas**: new `GasSensorEntity` for gas leak detector binary sensors (`gas_leak_state` BOOL)
- **hvac_fan**: new `HvacFanEntity` for fan devices with `on_off` and `hvac_air_flow_power` features
- **hvac_heater**: new `HvacHeaterEntity` for space heaters (ClimateEntity subclass, 5-40 C)
- **hvac_boiler**: new `HvacBoilerEntity` for water heaters (ClimateEntity subclass, 25-80 C)
- **hvac_underfloor_heating**: new `HvacUnderfloorEntity` for underfloor heating (ClimateEntity subclass, 25-50 C)
- **battery_percentage**: optional battery level reporting for all `SimpleReadOnlySensor` subclasses
- **power/voltage/current**: optional energy monitoring features for `OnOffEntity` (relay, socket)
- **fan** and **water_heater** HA domains now supported in entity mapping
- Smoke (`device_class=smoke`) and gas (`device_class=gas`) binary sensors now supported

## [0.7.0] - 2026-03-23

### Fixed
- **pir sensor**: changed value type from BOOL to ENUM per Sber specification (`"pir"` event value)
- **doorcontact_state**: changed value type from ENUM (`"open"/"close"`) to BOOL (`true/false`) per Sber specification
- **water_leak_state**: fixed Sber key from `water_leak` to `water_leak_state` per Sber specification
- **hvac_temp_set**: removed incorrect x10 scaling — Sber sends/receives whole degrees, not tenths
- **integer_value serialization**: all `integer_value` fields now serialized as strings per Sber C2C API specification

## [0.6.0] - 2026-03-23

### Added
- **Pydantic models** for Sber protocol (`sber_models.py`): typed schemas for device config, states, commands
- Helper constructors (`make_bool_value`, `make_integer_value`, `make_enum_value`, `make_colour_value`, `make_state`)
- Optional payload validation functions (`validate_config_payload`, `validate_status_payload`)
- **Custom YAML capabilities** (`custom_capabilities.py`): per-entity overrides via `configuration.yaml`
  - `sber_type` — override Sber device category (UI Options Flow override takes precedence)
  - `sber_name` — override display name in Sber
  - `sber_room` — set room/area in Sber
- `async_setup()` in `__init__.py` for parsing YAML platform config
- `pydantic>=2.0,<3.0` added to manifest.json requirements

## [0.5.1] - 2026-03-23

### Added
- **Config entry migration v1 to v2**: adds `entity_type_overrides` to options on upgrade
- **Snapshot tests**: syrupy-based snapshot tests for Sber protocol JSON responses
- **Strict mypy config**: enabled `disallow_untyped_defs`, `warn_return_any` and other strict checks

## [0.5.0] - 2026-03-23

### Added
- **Entity type overrides**: override Sber device category per entity in Options Flow
  (e.g. expose `switch.kitchen` as `light` in Sber)
- **Options Flow menu**: reorganized as menu with "Entity selection" and "Entity type overrides"
- **Gate/garage door support**: new `GateEntity` for cover entities with `gate`/`garage_door` device class
- **Label-based entity filtering**: select entities by HA labels in Options Flow
- **Extended diagnostics**: per-entity details (sber_category, features, state, linked device)
- `CATEGORY_CONSTRUCTORS` mapping for direct Sber category to entity class resolution
- `OVERRIDABLE_CATEGORIES` list of categories available for user overrides
- `CONF_ENTITY_TYPE_OVERRIDES` option key for storing overrides

### Changed
- `create_sber_entity()` now accepts optional `sber_category` parameter for overrides
- `_create_cover()` now maps `gate`/`garage_door` device classes to `GateEntity`
- Options Flow `init` step is now a menu instead of a form
- Entity selection steps preserve `entity_type_overrides` across options changes

## [0.4.1] - 2026-03-23

### Added
- "Remove ALL entities" option in Options Flow — clear list in one click

### Fixed
- Device deduplication: bulk add now keeps only the richest entity per
  physical device (light > switch for same device_id)
- Warning logged when multiple entities share the same device_id
- Manifest.json stray characters removed
- Entity mapping debug logging (domain → Sber category with device_class)

## [0.4.0] - 2026-03-23

### Added
- Bulk entity selection in Options Flow: "Add ALL supported entities" one-click
- Domain-based selection: "Add all by domain" with entity counts per domain
- Three selection modes: manual, by domain, add all

### Fixed
- **CRITICAL**: Infinite loop — `change_group_device_request` no longer triggers config re-publish
- **CRITICAL**: Humidity sensor sent value x10 (550 instead of 55%) — now plain INTEGER(0-100) per Sber docs
- **CRITICAL**: Batch commands triggered N separate MQTT publishes — now batched into one
- Curtain `open_state` ENUM reverted to correct `"close"` (not `"closed"`) per Sber protocol
- TOCTOU race: `AttributeError` caught when `_mqtt_client` becomes None during publish
- `acknowledged_entities` and `_redefinitions` pruned on entity reload (memory leak fix)
- Humidifier docstring corrected: "plain percentage" not "divided by 10"
- HSV color values clamped to min 0 to prevent negative values from Sber

## [0.3.1] - 2026-03-23

### Fixed
- Debounce timer not cancelled on bridge teardown (orphaned task prevention)
- `_handle_change_group` / `_handle_rename_device` variable naming (`device_id` → `entity_id`)
- `humidifier.set_humidity` uses `round()` instead of `int()` for correct rounding
- LightEntity: removed optimistic state mutation from `process_cmd`
- LightEntity: added missing `online` key in `to_sber_current_state`
- LightEntity: `ha_state["attributes"]` → `.get("attributes", {})` (KeyError prevention)
- CurtainEntity: same `.get()` fix for attributes access
- SSL `create_default_context()` offloaded to executor (no longer blocks event loop)
- Startup ordering: `EVENT_HOMEASSISTANT_STARTED` listener for entity registry reload

### Added
- `BridgeStats` dataclass with connection health metrics (uptime, counters, reconnects)
- Device acknowledgment tracking (entities confirmed by Sber via status_request/command)
- State publish debounce (100ms coalescing for burst HA state changes)
- MQTT payload size guard (1MB max, prevents DoS)
- Enhanced debug logging: all MQTT messages, Sber commands, HA service calls, errors

### Changed
- `_unsub_listeners` split into `_unsub_state_listeners` + `_unsub_lifecycle_listeners`
- Diagnostics now shows `stats` and `unacknowledged_entities`

### Removed
- Dead code: `EntityContext` class, `device_data.py`, `CONF_SBER_HTTP_ENDPOINT`
- Redundant `to_sber_state` override in `CurtainEntity`

## [0.3.0] - 2026-03-23

### Added
- `OnOffEntity` base class for relay, valve, socket (eliminates duplication)
- `SimpleReadOnlySensor` base class for 5 sensor types (eliminates duplication)
- `_is_online` property in `BaseEntity` (replaces duplicated inline checks)
- Device registry linking in `_load_exposed_entities` — entities with device_id now appear in Sber
- HA state event subscription at startup (independent of MQTT connectivity)
- `category` parameter in `RelayEntity`, `ClimateEntity`, `CurtainEntity` for clean subclassing
- Acknowledgments and legal trademark notice in README
- Migrated to GitHub: `dzerik/sber-mqtt-bridge`

### Fixed
- **CRITICAL**: Entities with `device_id` silently skipped from Sber (link_device never called)
- **CRITICAL**: `CurtainEntity.to_sber_current_state` returned `None` instead of `dict` on unavailable
- **CRITICAL**: `LightEntity` `int(None)` crash on missing `integer_value` in color temp command
- **CRITICAL**: `LightEntity` state key `colour_temperature` mismatched registered feature `light_colour_temp`
- **CRITICAL**: `CurtainEntity` `elif open_set` silently dropped command when `cover_position` was present
- Curtain open_state ENUM value `"close"` corrected to `"closed"`
- ScenarioButton spurious `double_click` on `unavailable`/`unknown` states
- Climate hardcoded 22°C fallback on missing `integer_value` — now skips command
- Humidifier `set_mode` with `None` mode guard
- Race condition: `_connected` and `_mqtt_client` now reset atomically on disconnect
- Dead code `ConfigEntryNotReady` try/except removed (bridge uses background reconnect)
- HA events no longer lost during MQTT reconnect window

### Changed
- `process_state_change` default implementation moved to `BaseEntity` (removed from 6 subclasses)
- Logger convention: `logger` renamed to `_LOGGER` in all 17 device files
- `SocketEntity`, `WindowBlindEntity`, `HvacRadiatorEntity` use proper `super().__init__()` chain
- `HvacRadiatorEntity` no longer duplicates `ClimateEntity.__init__` body
- Removed dead code: `CONF_SBER_HTTP_ENDPOINT`, `SBER_HTTP_ENDPOINT_DEFAULT`
- `LightEntity` added `from __future__ import annotations`
- jscpd duplication reduced: 13 clones → 9 (4.34% → 3.38%)

### Removed
- Legacy addon `mqtt_sber_gate/` directory (fully superseded by HACS integration)
- Wrong-project audit file `docs/audit/audit-02-architecture.md` (described xiaomi_miio)

## [0.2.0] - 2026-03-23

### Added
- Reauthentication flow (`async_step_reauth`) for Silver quality scale
- 153 new unit tests (219 total), achieving 82% code coverage
- Exponential backoff for MQTT reconnection (5s → 300s max)
- Enum validation for climate commands (fan_mode, swing_mode, hvac_mode)
- Comprehensive docstrings for all public classes, methods, constants
- `from __future__ import annotations` in all modules
- README.md rewritten for HACS integration (installation, config, troubleshooting)
- CHANGELOG.md in Keep a Changelog format

### Fixed
- TLS verify configurable via Config Flow (was hardcoded CERT_NONE)
- JSON parse error handling in `parse_sber_command`
- LightEntity shared class-level converters causing cross-instance bugs
- BaseEntity mutable default `attributes: dict = {}` moved to `__init__`
- Deprecated entity_registry API updated to `er.async_get(hass)`
- LightEntity `process_cmd` returns `[]` instead of `None`
- LightEntity `process_cmd` UnboundLocalError on empty states
- Falsy value filter in `build_devices_list_json`
- `assert` replaced with `raise RuntimeError/ValueError`
- `callable` → `Callable` type hint
- Typo `unuque_id` → `unique_id` in device_data.py
- All 24 ruff lint issues resolved (0 remaining)
- ruff format applied to all files
- Swap-on-replace pattern for entity reload (race condition fix)
- .gitignore extended with .env, *.pem, secrets.yaml

### Changed
- HA Quality Scale: Bronze → **Silver** (all 28 rules done/exempt)
- aiomqtt dependency pinned to `>=2.0,<3.0`
- Command payload logging moved from INFO to DEBUG
- BaseEntity uses ABC with 3 `@abstractmethod`s

## [0.1.0] - 2026-03-23

### Added
- **HACS custom integration** `sber_mqtt_bridge` — native HA integration replacing standalone addon
- Config Flow UI for Sber MQTT credentials with SSL verification option
- Options Flow with EntitySelector for choosing which HA entities to expose to Sber
- SberBridge core: async MQTT via aiomqtt + HA event bus integration
- Sber protocol serialization (device config, state lists, command parsing)
- Entity factory mapping 11 HA domains to 15 Sber device types
- 15 device classes migrated to BaseEntity OOP system:
  - LightEntity (brightness, color, color_temp)
  - ClimateEntity, HvacRadiatorEntity (HVAC)
  - CurtainEntity, WindowBlindEntity (covers)
  - RelayEntity, SocketEntity (switches)
  - ScenarioButtonEntity (input_boolean)
  - SensorTempEntity, HumiditySensorEntity (sensors)
  - MotionSensorEntity, DoorSensorEntity, WaterLeakSensorEntity (binary sensors)
  - ValveEntity, HumidifierEntity (new Sber categories)
- Diagnostics support with credential redaction
- Translations: English and Russian
- quality_scale.yaml targeting Silver tier
- 66 unit tests (config flow, bridge, protocol, entity map)
- GitHub Actions CI/CD (ruff, pytest, hassfest, HACS validation, release)
- Pre-commit hooks (ruff, codespell)
- GitHub community files (CONTRIBUTING, CODE_OF_CONDUCT, SECURITY, issue templates)
- Comprehensive docstrings for all public classes, methods, and constants

### Fixed
- TLS certificate verification is now configurable (was hardcoded CERT_NONE)
- JSON parse error handling in Sber command parser (was crashing MQTT loop)
- LightEntity shared class-level converters (was causing cross-instance bugs)
- BaseEntity mutable default `attributes: dict = {}` moved to `__init__`
- Deprecated entity_registry API updated to modern `er.async_get(hass)`
- LightEntity `process_cmd` returns `[]` instead of `None`
- Falsy value filter in `build_devices_list_json` uses `is not None` instead of truthiness

### Changed
- BaseEntity now uses ABC with all 3 abstract methods (`process_cmd`, `to_sber_current_state`, `process_state_change`)
- `assert` statements replaced with proper `raise RuntimeError/ValueError`
- Command payload logging changed from INFO to DEBUG level

## [1.2.0] - 2026-03-23

### Changed
- **OOP migration complete**: All 15 device types migrated from old dict-based system to BaseEntity
- All old REST API command handlers removed (`ha_OnOff`, `ha_climate`, etc.)
- `handle_event_new` removed — all state changes go through `_process_event`
- DevicesConverter simplified to single `create_by_entities_store` method

### Added
- 6 new device types: SocketEntity, DoorSensorEntity, WaterLeakSensorEntity, WindowBlindEntity, ValveEntity, HumidifierEntity
- Factory functions with device_class routing for sensor, binary_sensor, switch, cover, climate domains
- 96 unit tests for all device classes

### Removed
- Old device system code from `sber-gate.py` and `web_socket_handler.py`
- `shutter.py`, `pressure_sensor.py` (replaced/unsupported)
- All `upd_*` methods from `DevicesConverter`

## [1.1.0] - 2025-09-23

### Changed
- Refactored service classes into separate modules
- New device management system based on BaseEntity OOP
- Light entity: added color and color temperature modes

### Added
- LightEntity and CurtainEntity with full OOP implementation

[Unreleased]: https://github.com/mberezovsky/MQTT-SberGate/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/mberezovsky/MQTT-SberGate/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/mberezovsky/MQTT-SberGate/releases/tag/v0.1.0
[1.2.0]: https://github.com/mberezovsky/MQTT-SberGate/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/mberezovsky/MQTT-SberGate/releases/tag/v1.1.0
