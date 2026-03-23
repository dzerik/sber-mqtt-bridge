# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/mberezovsky/MQTT-SberGate/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/mberezovsky/MQTT-SberGate/releases/tag/v0.1.0
[1.2.0]: https://github.com/mberezovsky/MQTT-SberGate/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/mberezovsky/MQTT-SberGate/releases/tag/v1.1.0
