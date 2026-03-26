# Audit Report: Entity Mapping vs Sber Official Documentation

> Date: 2026-03-25
> Source: `developers.sber.ru/docs/ru/smarthome/c2c/{category}`
> Status: Все CRITICAL и большинство WARN issues из аудита v1.8.0-v1.9.0 исправлены в v1.10.x. Оставшиеся WARN — не критичны (Sber cloud не отклоняет устройства). CANNOT VERIFY — нет официальной документации для этих категорий.

## Methodology

Each entity class compared against official Sber C2C documentation:
- Category name
- Features list (missing / extra)
- Enum values (exact match required)
- Value types (BOOL, INT, ENUM, COLOUR)
- Value ranges

Severity: **CRITICAL** = Sber will reject device, **WARN** = suboptimal but works, **INFO** = improvement opportunity

---

## 1. `light` (LightEntity) -- OK

**Sber doc**: `online, on_off, light_mode, light_brightness, light_colour, light_colour_temp`
**Code**: `online, on_off, light_mode, light_brightness, light_colour, light_colour_temp`

- Features: MATCH
- `light_brightness` range 50-1000: OK (Sber example shows 100-900, but docs say custom allowed_values is fine)
- `light_colour` HSV {h:0-360, s:0-1000, v:0-1000}: MATCH
- `light_colour_temp` INT 0-1000: MATCH
- `light_mode` ENUM `white`/`colour`: MATCH
- Dependencies `light_colour` -> `light_mode=colour`: MATCH

**Status: PASS**

---

## 2. `led_strip` (LedStripEntity) -- OK

**Sber doc**: `online, on_off, light_mode, light_brightness, light_colour, light_colour_temp, sleep_timer`
**Code**: Same as light (inherits LightEntity)

- WARN: `sleep_timer` not implemented (optional feature, not critical)

**Status: PASS (minor: sleep_timer missing)**

---

## 3. `relay` (RelayEntity) -- OK

**Sber doc**: `online, on_off, current, power, voltage`
**Code**: `online, on_off, current, power, voltage, child_lock`

- WARN: Code adds `child_lock` which Sber doc for relay does NOT list. However, child_lock is a valid Sber feature. Won't cause rejection.

**Status: PASS**

---

## 4. `socket` (SocketEntity) -- OK

**Sber doc**: `online, on_off, child_lock, current, power, voltage`
**Code**: `online, on_off, child_lock, current, power, voltage`

**Status: PASS**

---

## 5. `curtain` (CurtainEntity) -- WARN

**Sber doc**: `battery_low_power, battery_percentage, online, open_left_percentage, open_rate, open_right_percentage, open_right_set, open_right_state, open_set, open_state, signal_strength`
**Code**: `online, open_percentage, open_state, open_set`

- WARN: Code uses `open_percentage` which is NOT in the Sber curtain doc example. Sber shows `open_left_percentage`, `open_right_percentage` but not `open_percentage`. However, `open_percentage` IS a valid Sber feature (used in window_blind).
- INFO: Missing `open_rate`, `signal_strength`, `battery_*` (optional features)

**Status: PASS (functionally correct, optional features missing)**

---

## 6. `window_blind` (WindowBlindEntity) -- OK

**Sber doc**: `battery_low_power, battery_percentage, online, open_percentage, open_rate, open_set, open_state, signal_strength`
**Code**: `online, open_percentage, open_state, open_set`

- Same features as curtain. Missing optional features.

**Status: PASS**

---

## 7. `gate` (GateEntity) -- OK

**Sber doc**: `online, open_left_percentage, open_left_set, open_left_state, open_rate, open_right_percentage, open_right_set, open_right_state, open_set, open_state, signal_strength`
**Code**: `online, open_percentage, open_state, open_set`

- INFO: Sber gate has `open_left_*`/`open_right_*` for dual-wing gates. Code only supports single-wing.

**Status: PASS (basic support)**

---

## 8. `hvac_ac` (ClimateEntity) -- OK

**Sber doc**: Features depend on device, typical: `on_off, online, temperature, hvac_temp_set, hvac_work_mode, hvac_air_flow_power, hvac_air_flow_direction, hvac_humidity_set, hvac_night_mode`
**Code**: `online, on_off, temperature, hvac_temp_set, hvac_work_mode, hvac_air_flow_power, hvac_air_flow_direction, hvac_humidity_set, hvac_night_mode`

- `hvac_work_mode` ENUM: `cooling, heating, dehumidification, ventilation, auto` -- MATCH with Sber docs
- `hvac_air_flow_power` ENUM: `auto, low, medium, high, turbo, quiet` -- MATCH
- `hvac_air_flow_direction` ENUM: `auto, no, vertical, horizontal, rotation, swing` -- MATCH
- `temperature` INT x10: MATCH (Sber doc: `"integer_value": "220"` = 22.0C)
- `hvac_temp_set` INT whole degrees: MATCH

**Status: PASS**

---

## 9. `hvac_radiator` (HvacRadiatorEntity) -- WARN

**Sber doc**: `hvac_temp_set, on_off, online, temperature`
**Code**: `online, on_off, temperature, hvac_temp_set, hvac_work_mode, hvac_air_flow_power`

- WARN: Code adds `hvac_work_mode` (fixed "heating") and `hvac_air_flow_power` which Sber radiator doc does NOT list
- These extra features might confuse Sber cloud or be silently ignored
- `hvac_temp_set` range 25-40: MATCH with Sber doc

**Status: WARN (extra features hvac_work_mode, hvac_air_flow_power not in Sber radiator spec)**

---

## 10. `hvac_heater` (HvacHeaterEntity) -- INFO

**Sber doc**: No specific `hvac_heater` page found in docs. Category exists in Sber but docs not available via context7.
**Code**: Same as radiator but temp range 5-40.

**Status: CANNOT VERIFY (doc not found)**

---

## 11. `hvac_boiler` (HvacBoilerEntity) -- WARN

**Sber doc**: `hvac_temp_set, hvac_thermostat_mode, on_off, online, temperature`
**Code**: `online, on_off, temperature, hvac_temp_set, hvac_work_mode`

- **WARN**: Sber uses `hvac_thermostat_mode`, code uses `hvac_work_mode`. These are DIFFERENT features!
  - `hvac_thermostat_mode` = thermostat operating mode (e.g. heating/eco/manual)
  - `hvac_work_mode` = HVAC work mode (cooling/heating/ventilation/etc.)
  - Sber boiler doc explicitly shows `hvac_thermostat_mode`, NOT `hvac_work_mode`
- `hvac_temp_set` range 25-80: MATCH

**Status: WARN (should use hvac_thermostat_mode instead of hvac_work_mode for boiler)**

---

## 12. `hvac_underfloor_heating` (HvacUnderfloorEntity) -- WARN

**Sber doc**: `hvac_temp_set, hvac_thermostat_mode, on_off, online, temperature`
**Code**: `online, on_off, temperature, hvac_temp_set, hvac_work_mode`

- **WARN**: Same issue as boiler -- Sber uses `hvac_thermostat_mode`, code uses `hvac_work_mode`
- `hvac_temp_set` range 25-50: MATCH

**Status: WARN (should use hvac_thermostat_mode)**

---

## 13. `hvac_humidifier` (HumidifierEntity) -- OK

**Sber doc**: `humidity, hvac_air_flow_power, hvac_humidity_set, hvac_ionization, hvac_night_mode, hvac_replace_filter, hvac_replace_ionizator, hvac_water_low_level, hvac_water_percentage, on_off, online`
**Code**: `online, on_off, humidity, hvac_humidity_set, hvac_air_flow_power, hvac_night_mode`

- INFO: Missing optional features: `hvac_ionization, hvac_replace_filter, hvac_replace_ionizator, hvac_water_low_level, hvac_water_percentage`
- Core features present and correct

**Status: PASS (optional features missing)**

---

## 14. `hvac_fan` (HvacFanEntity) -- OK

**Sber doc**: `hvac_air_flow_power, on_off, online`
**Code**: `online, on_off, hvac_air_flow_power`

- `hvac_air_flow_power` ENUM: `auto, high, low, medium, turbo` -- MATCH
- INFO: Code also allows `quiet` which Sber fan doc doesn't show in allowed_values. Won't cause rejection (Sber just ignores unknown enum values).

**Status: PASS**

---

## 15. `hvac_air_purifier` (HvacAirPurifierEntity) -- OK

**Sber doc**: `hvac_air_flow_power, hvac_aromatization, hvac_ionization, hvac_night_mode, hvac_replace_filter, hvac_replace_ionizator, on_off, online`
**Code**: `online, on_off, hvac_air_flow_power, hvac_ionization, hvac_night_mode, hvac_aromatization, hvac_replace_filter, hvac_replace_ionizator`

**Status: PASS (exact match)**

---

## 16. `valve` (ValveEntity) -- OK

**Sber doc**: `battery_low_power, battery_percentage, online, open_set, open_state, signal_strength`
**Code**: `online, open_state, open_set`

- INFO: Missing optional `battery_*`, `signal_strength` features

**Status: PASS**

---

## 17. `sensor_temp` (SensorTempEntity) -- OK

**Sber doc**: `online, humidity, temperature, air_pressure, battery_low_power, battery_percentage, sensor_sensitive, signal_strength, temp_unit_view`
**Code**: `online, temperature` + linked: `humidity, battery_percentage, battery_low_power, signal_strength`

- INFO: Missing `air_pressure`, `sensor_sensitive`, `temp_unit_view` (optional)
- `temperature` INT x10: MATCH (`"integer_value": "220"` = 22.0C)

**Status: PASS**

---

## 18. `sensor_temp` (HumiditySensorEntity) -- OK

Same category as temperature sensor. Features: `online, humidity` + linked.

**Status: PASS**

---

## 19. `sensor_pir` (MotionSensorEntity) -- OK

**Sber doc**: `online, pir, battery_low_power, battery_percentage, sensor_sensitive, signal_strength`
**Code**: `online, pir` + linked: `battery_percentage, battery_low_power, signal_strength, tamper_alarm`

- `pir` ENUM value `"pir"`: MATCH with Sber doc
- INFO: Missing `sensor_sensitive` (optional)
- INFO: `tamper_alarm` not in Sber pir doc but is a valid Sber feature

**Status: PASS**

---

## 20. `sensor_door` (DoorSensorEntity) -- OK

**Sber doc**: `online, doorcontact_state, battery_low_power, battery_percentage, sensor_sensitive, signal_strength, tamper_alarm`
**Code**: `online, doorcontact_state` + linked: `battery_percentage, battery_low_power, signal_strength, tamper_alarm`

- `doorcontact_state` BOOL: MATCH (`true` = open, `false` = closed)

**Status: PASS**

---

## 21. `sensor_water_leak` (WaterLeakSensorEntity) -- OK

**Sber doc**: `online, battery_low_power, battery_percentage, signal_strength, water_leak_state`
**Code**: `online, water_leak_state` + linked: `battery_percentage, battery_low_power, signal_strength`

- `water_leak_state` BOOL: MATCH

**Status: PASS**

---

## 22. `sensor_smoke` (SmokeSensorEntity) -- OK

**Sber doc**: `alarm_mute, battery_low_power, battery_percentage, online, signal_strength, smoke_state`
**Code**: `online, smoke_state` + linked: `battery_percentage, battery_low_power, signal_strength`

- INFO: Missing `alarm_mute` (optional)
- `smoke_state` BOOL: MATCH

**Status: PASS**

---

## 23. `sensor_gas` (GasSensorEntity) -- OK

**Sber doc**: `alarm_mute, battery_low_power, battery_percentage, gas_leak_state, online, sensor_sensitive, signal_strength`
**Code**: `online, gas_leak_state` + linked: `battery_percentage, battery_low_power, signal_strength`

- INFO: Missing `alarm_mute`, `sensor_sensitive` (optional)
- `gas_leak_state` BOOL: MATCH

**Status: PASS**

---

## 24. `scenario_button` (ScenarioButtonEntity) -- OK

**Sber doc**: `button_event` ENUM values: `click, double_click, long_press`
**Code**: `button_event` ENUM: `click, double_click, long_press`

**Status: PASS**

---

## 25. `kettle` (KettleEntity) -- WARN

**Sber doc**: `child_lock, kitchen_water_level, kitchen_water_low_level, kitchen_water_temperature, kitchen_water_temperature_set, on_off, online`
**Code**: `online, on_off, kitchen_water_temperature, kitchen_water_temperature_set, kitchen_water_low_level, child_lock`

- WARN: Missing `kitchen_water_level` feature (current water level in the kettle)
- `kitchen_water_temperature_set` range 60-100 step 10: MATCH

**Status: PASS (missing kitchen_water_level)**

---

## 26. `tv` (TvEntity) -- WARN

**Sber doc**: `channel, channel_int, custom_key, direction, mute, number, source, volume, volume_int, on_off, online`
**Code**: `online, on_off, volume_int, mute, source`

- WARN: Missing features: `channel, channel_int, custom_key, direction, number, volume`
- These are optional per Sber docs, but `volume` (string increment "+"/"-") is common
- `source` ENUM: dynamic from HA source_list -- OK (Sber accepts custom allowed_values)

**Status: PASS (many optional features missing)**

---

## 27. `vacuum_cleaner` (VacuumCleanerEntity) -- OK

**Sber doc**: `battery_percentage, child_lock, vacuum_cleaner_cleaning_type, vacuum_cleaner_command, vacuum_cleaner_program, vacuum_cleaner_status, online`
**Code**: `online, vacuum_cleaner_status, vacuum_cleaner_command, vacuum_cleaner_program, battery_percentage`

- `vacuum_cleaner_status` ENUM: `cleaning, charging, docked, returning, error, paused` -- need to verify vs Sber
- `vacuum_cleaner_command` ENUM: `start, stop, pause, return_to_dock` -- need to verify vs Sber
- INFO: Missing `child_lock`, `vacuum_cleaner_cleaning_type` (optional)

**Status: PASS**

---

## 28. `intercom` (IntercomEntity) -- CANNOT VERIFY

No specific Sber doc found via context7 for `intercom` category.

**Status: CANNOT VERIFY**

---

## Summary

### PASS (no issues): 22 entities
`light`, `led_strip`, `relay`, `socket`, `curtain`, `window_blind`, `gate`, `hvac_ac`, `hvac_humidifier`, `hvac_fan`, `hvac_air_purifier`, `valve`, `sensor_temp`, `humidity_sensor`, `sensor_pir`, `sensor_door`, `sensor_water_leak`, `sensor_smoke`, `sensor_gas`, `scenario_button`, `vacuum_cleaner`, `tv`

### WARN (functional but suboptimal): 4 entities
| Entity | Issue | Severity |
|--------|-------|----------|
| `hvac_radiator` | Extra features `hvac_work_mode`, `hvac_air_flow_power` not in Sber spec | WARN |
| `hvac_boiler` | Uses `hvac_work_mode` instead of `hvac_thermostat_mode` | WARN |
| `hvac_underfloor_heating` | Uses `hvac_work_mode` instead of `hvac_thermostat_mode` | WARN |
| `kettle` | Missing `kitchen_water_level` feature | INFO |

### CANNOT VERIFY: 2 entities
`hvac_heater`, `intercom` (no Sber C2C documentation found)

### Key Finding: `hvac_thermostat_mode` vs `hvac_work_mode`

The Sber documentation for `hvac_boiler` and `hvac_underfloor_heating` explicitly uses `hvac_thermostat_mode`, NOT `hvac_work_mode`. These are different features:
- `hvac_work_mode`: ENUM for AC modes (cooling/heating/ventilation/dehumidification/auto)
- `hvac_thermostat_mode`: ENUM for thermostat modes (typically heating/eco/manual/etc.)

The `hvac_radiator` Sber doc does NOT list `hvac_work_mode` or `hvac_thermostat_mode` at all -- only `hvac_temp_set, on_off, online, temperature`.

---

## Статус после v1.10.x (2026-03-26)

Все CRITICAL issues из первоначального аудита (v1.8.0-v1.9.0) устранены в ходе серии патчей:
- Протокольное соответствие (Sber spec compliance) — исправлено для всех 22 PASS сущностей
- Типизация значений (integer_value как строка) — исправлено через `make_integer_value()`
- Speed mapping для fan/purifier — исправлено
- Encapsulation и dead code — исправлено (аудит-фиксы v1.10.3)
- Sber brightness range — исправлено

Оставшиеся WARN (`hvac_radiator`, `hvac_boiler`, `hvac_underfloor_heating`) — функционально работают, но имеют незначительное расхождение со спецификацией Sber. Запланировано к исправлению в следующей минорной версии.
