# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
