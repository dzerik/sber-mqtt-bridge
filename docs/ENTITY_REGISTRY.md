# Entity Registry — Sber Smart Home MQTT Bridge

> Comprehensive reference for all Sber device types, features, allowed values,
> online status logic, entity linking, and HA domain mappings.
>
> Last updated: v1.10.3 (2026-03-26)

## HA Domain -> Sber Category Mapping

| HA Domain | device_class | Sber Category | Class | File |
|-----------|-------------|---------------|-------|------|
| light | * | `light` | LightEntity | light.py |
| light | (led_strip override) | `led_strip` | LedStripEntity | led_strip.py |
| switch | * (default) | `relay` | RelayEntity | relay.py |
| switch | outlet | `socket` | SocketEntity | socket_entity.py |
| script | * | `relay` | RelayEntity | relay.py |
| button | * | `relay` | RelayEntity | relay.py |
| input_boolean | * | `scenario_button` | ScenarioButtonEntity | scenario_button.py |
| cover | * (default) | `curtain` | CurtainEntity | curtain.py |
| cover | blind/shade/shutter | `window_blind` | WindowBlindEntity | window_blind.py |
| cover | gate/garage_door | `gate` | GateEntity | gate.py |
| climate | * (default) | `hvac_ac` | ClimateEntity | climate.py |
| climate | radiator | `hvac_radiator` | HvacRadiatorEntity | hvac_radiator.py |
| climate | heater | `hvac_heater` | HvacHeaterEntity | hvac_heater.py |
| climate | (underfloor override) | `hvac_underfloor_heating` | HvacUnderfloorEntity | hvac_underfloor_heating.py |
| water_heater | * | `hvac_boiler` | HvacBoilerEntity | hvac_boiler.py |
| valve | * | `valve` | ValveEntity | valve.py |
| humidifier | * | `hvac_humidifier` | HumidifierEntity | humidifier.py |
| fan | * (default) | `hvac_fan` | HvacFanEntity | hvac_fan.py |
| fan | purifier/air_purifier | `hvac_air_purifier` | HvacAirPurifierEntity | hvac_air_purifier.py |
| sensor | temperature | `sensor_temp` | SensorTempEntity | sensor_temp.py |
| sensor | humidity | `sensor_temp` | HumiditySensorEntity | humidity_sensor.py |
| binary_sensor | motion/occupancy/presence | `sensor_pir` | MotionSensorEntity | motion_sensor.py |
| binary_sensor | door/window/garage_door/opening | `sensor_door` | DoorSensorEntity | door_sensor.py |
| binary_sensor | moisture/water | `sensor_water_leak` | WaterLeakSensorEntity | water_leak_sensor.py |
| binary_sensor | smoke | `sensor_smoke` | SmokeSensorEntity | smoke_sensor.py |
| binary_sensor | gas | `sensor_gas` | GasSensorEntity | gas_sensor.py |
| media_player | * | `tv` | TvEntity | tv.py |
| vacuum | * | `vacuum_cleaner` | VacuumCleanerEntity | vacuum_cleaner.py |

## Overridable Categories (manual override in UI)

`light`, `led_strip`, `relay`, `socket`, `curtain`, `window_blind`, `gate`,
`hvac_ac`, `hvac_radiator`, `hvac_heater`, `hvac_boiler`, `hvac_underfloor_heating`,
`valve`, `hvac_humidifier`, `hvac_fan`, `hvac_air_purifier`, `scenario_button`,
`kettle`, `tv`, `vacuum_cleaner`, `intercom`

---

## Online Status Logic

The `online` feature is reported for every device. The logic varies by entity type:

| HA state | Default behavior | Event-based binary_sensors |
|----------|-----------------|---------------------------|
| `None` (not loaded) | **offline** (is_filled=false, UI: "Loading...") | **offline** |
| `"unavailable"` | **offline** | **offline** |
| `"unknown"` | **offline** | **online** (device reachable, no events yet) |
| `"on"/"off"/value/etc.` | **online** | **online** |

**Event-based sensors** with `_unknown_is_online = True`:
`MotionSensorEntity`, `DoorSensorEntity`, `WaterLeakSensorEntity`, `SmokeSensorEntity`, `GasSensorEntity`

**Value-based sensors** keep `unknown` = offline to avoid reporting fake 0 values:
`SensorTempEntity` (would report 0.0C), `HumiditySensorEntity` (would report 0%)

**UI badge states:**
- Green **"Online"** — entity is reachable and reporting state
- Grey **"Offline"** — entity state is `unavailable` (device unreachable)
- Yellow **"Loading..."** — state not yet received (`is_filled=false`)

---

## Feature Registry by Category

### `light` / `led_strip` (LightEntity / LedStripEntity)

| Feature | Type | Range/Values | Direction | Notes |
|---------|------|-------------|-----------|-------|
| `online` | BOOL | true/false | R | |
| `on_off` | BOOL | true/false | R/W | Power state |
| `light_brightness` | INTEGER | 100-900, step 1 | R/W | Mapped from HA 0-255 via LinearConverter |
| `light_colour` | COLOUR | `{h: 0-360, s: 0-1000, v: 0-1000}` | R/W | HSV; converted via ColorConverter |
| `light_mode` | ENUM | `white`, `colour` | R/W | Switching sends HA service call with current color/temp |
| `light_colour_temp` | ENUM | 0-1000, step 1 | R/W | Mapped from HA mireds (reversed) |

**Dependencies:** `light_colour` depends on `light_mode == "colour"`

### `relay` / `socket` (RelayEntity / SocketEntity, extends OnOffEntity)

| Feature | Type | Range/Values | Direction | Notes |
|---------|------|-------------|-----------|-------|
| `online` | BOOL | true/false | R | |
| `on_off` | BOOL | true/false | R/W | For button domain uses `press` service |
| `power` | INTEGER | watts | R | Optional, from HA attributes |
| `voltage` | INTEGER | volts | R | Optional |
| `current` | INTEGER | milliamps | R | Optional |
| `child_lock` | BOOL | true/false | R | Optional |

### `curtain` / `window_blind` / `gate` (CurtainEntity hierarchy)

| Feature | Type | Range/Values | Direction | Notes |
|---------|------|-------------|-----------|-------|
| `online` | BOOL | true/false | R | |
| `open_percentage` | INTEGER | 0-100, step 1 | R/W | 0=closed, 100=open |
| `open_state` | ENUM | `open`, `close` | R | Enforced consistent with percentage |
| `open_set` | ENUM | `open`, `close`, `stop` | W | Command |
| `battery_percentage` | INTEGER | 0-100 | R | From attributes or linked entity |
| `battery_low_power` | BOOL | true/false | R | From linked binary_sensor or <20% |
| `signal_strength` | ENUM | `high`, `medium`, `low` | R | From RSSI/linkquality attribute or linked |

**Consistency enforcement:** if percentage > 0 → open_state forced to "open"; if 0 → "close"

### `hvac_ac` (ClimateEntity)

| Feature | Type | Range/Values | Direction | Notes |
|---------|------|-------------|-----------|-------|
| `online` | BOOL | true/false | R | |
| `on_off` | BOOL | true/false | R/W | |
| `temperature` | INTEGER | x10 (e.g. 225 = 22.5C) | R | Current temp |
| `hvac_temp_set` | INTEGER | min_temp..max_temp, step configurable | R/W | Target temp (whole degrees) |
| `hvac_work_mode` | ENUM | `cooling`, `heating`, `dehumidification`, `ventilation`, `auto` | R/W | Mapped from HA hvac_mode |
| `hvac_air_flow_power` | ENUM | `auto`, `low`, `medium`, `high`, `turbo`, `quiet` | R/W | Mapped via HA_TO_SBER_FAN_MODE (20+ HA names) |
| `hvac_air_flow_direction` | ENUM | `auto`, `no`, `vertical`, `horizontal`, `rotation`, `swing` | R/W | Mapped from HA swing_mode |
| `hvac_humidity_set` | INTEGER | 0-100 | R/W | If HA entity supports target_humidity |
| `hvac_night_mode` | BOOL | true/false | R/W | From preset_mode sleep/night |
| `hvac_thermostat_mode` | ENUM | `heating`, `auto` | R/W | For boiler/heater/underfloor only |

**Fan mode mapping (HA_TO_SBER_FAN_MODE):**
auto, low, medium/mid, high, turbo/strong/boost/max, quiet/silent/sleep, 1-5 (numeric)

### `hvac_radiator` (HvacRadiatorEntity)

Inherits ClimateEntity. `_supports_fan=False`, `_supports_swing=False`, `_supports_work_mode=False`.
Temperature: 25-40C, step 5.

### `hvac_heater` (HvacHeaterEntity)

Inherits ClimateEntity. `_supports_fan=True`, `_supports_thermostat_mode=True`, `_supports_swing=False`, `_supports_work_mode=False`.
Temperature: 5-40C.

### `hvac_boiler` (HvacBoilerEntity)

Inherits ClimateEntity. `_supports_thermostat_mode=True`, no fan/swing/work_mode.
Temperature: 25-80C, step 5.

### `hvac_underfloor_heating` (HvacUnderfloorEntity)

Inherits ClimateEntity. `_supports_thermostat_mode=True`, no fan/swing/work_mode.
Temperature: 25-50C, step 5.

### `hvac_humidifier` (HumidifierEntity)

| Feature | Type | Range/Values | Direction | Notes |
|---------|------|-------------|-----------|-------|
| `online` | BOOL | true/false | R | |
| `on_off` | BOOL | true/false | R/W | |
| `humidity` | INTEGER | 0-100 | R | Current humidity |
| `hvac_humidity_set` | INTEGER | 0-100, step 1 | R/W | Target humidity |
| `hvac_air_flow_power` | ENUM | dynamic from HA modes | R/W | Mapped via HA_TO_SBER_HUMIDIFIER_MODE |
| `hvac_night_mode` | BOOL | true/false | R/W | If modes contain sleep/night |

### `hvac_fan` (HvacFanEntity)

| Feature | Type | Range/Values | Direction | Notes |
|---------|------|-------------|-----------|-------|
| `online` | BOOL | true/false | R | |
| `on_off` | BOOL | true/false | R/W | |
| `hvac_air_flow_power` | ENUM | `auto`, `high`, `low`, `medium`, `quiet`, `turbo` | R/W | From preset_mode or percentage |

**Percentage → Speed mapping:** 0-19%=quiet, 20-39%=low, 40-66%=medium, 67-89%=high, 90-100%=turbo

### `hvac_air_purifier` (HvacAirPurifierEntity)

| Feature | Type | Range/Values | Direction | Notes |
|---------|------|-------------|-----------|-------|
| `online` | BOOL | true/false | R | |
| `on_off` | BOOL | true/false | R/W | |
| `hvac_air_flow_power` | ENUM | `auto`, `high`, `low`, `medium`, `quiet`, `turbo` | R/W | Shared constants from hvac_fan |
| `hvac_ionization` | BOOL | true/false | R | From HA attributes |
| `hvac_night_mode` | BOOL | true/false | R | |
| `hvac_aromatization` | BOOL | true/false | R | |
| `hvac_replace_filter` | BOOL | true/false | R | Filter replacement needed |
| `hvac_replace_ionizator` | BOOL | true/false | R | Ionizer replacement needed |
| `hvac_decontaminate` | BOOL | true/false | R | Conditional |

### `valve` (ValveEntity)

| Feature | Type | Range/Values | Direction | Notes |
|---------|------|-------------|-----------|-------|
| `online` | BOOL | true/false | R | |
| `open_state` | ENUM | `open`, `close` | R | Current state |
| `open_set` | ENUM | `open`, `close`, `stop` | W | Command |
| `battery_percentage` | INTEGER | 0-100 | R | From attributes or linked entity |
| `battery_low_power` | BOOL | true/false | R | From linked binary_sensor or <20% |
| `signal_strength` | ENUM | `high`, `medium`, `low` | R | From attributes or linked entity |

### `sensor_temp` (SensorTempEntity)

| Feature | Type | Range/Values | Direction | Notes |
|---------|------|-------------|-----------|-------|
| `online` | BOOL | true/false | R | unknown = **offline** (prevents 0C report) |
| `temperature` | INTEGER | x10 (225 = 22.5C) | R | |
| `humidity` | INTEGER | 0-100 | R | From linked humidity entity |
| `air_pressure` | INTEGER | mmHg | R | From `pressure` attribute |
| `battery_percentage` | INTEGER | 0-100 | R | From attributes or linked |
| `battery_low_power` | BOOL | true/false | R | |
| `signal_strength` | ENUM | `high`/`medium`/`low` | R | |

### `sensor_temp` (HumiditySensorEntity, same category)

| Feature | Type | Range/Values | Direction | Notes |
|---------|------|-------------|-----------|-------|
| `online` | BOOL | true/false | R | unknown = **offline** |
| `humidity` | INTEGER | 0-100 | R | |
| `temperature` | INTEGER | x10 | R | From linked temperature entity |
| `battery_percentage` | INTEGER | 0-100 | R | |
| `battery_low_power` | BOOL | true/false | R | |
| `signal_strength` | ENUM | `high`/`medium`/`low` | R | |

### `sensor_pir` (MotionSensorEntity)

| Feature | Type | Range/Values | Direction | Notes |
|---------|------|-------------|-----------|-------|
| `online` | BOOL | true/false | R | unknown = **online** (_unknown_is_online=True) |
| `pir` | ENUM | `pir`, `no_pir` | R | Per Sber C2C spec |
| `battery_percentage` | INTEGER | 0-100 | R | |
| `battery_low_power` | BOOL | true/false | R | |
| `signal_strength` | ENUM | `high`/`medium`/`low` | R | |
| `tamper_alarm` | BOOL | true/false | R | From `tamper` attribute |

### `sensor_door` (DoorSensorEntity)

| Feature | Type | Range/Values | Direction | Notes |
|---------|------|-------------|-----------|-------|
| `online` | BOOL | true/false | R | unknown = **online** |
| `doorcontact_state` | BOOL | true/false | R | true = open |
| `battery_percentage` | INTEGER | 0-100 | R | |
| `battery_low_power` | BOOL | true/false | R | |
| `signal_strength` | ENUM | `high`/`medium`/`low` | R | |
| `tamper_alarm` | BOOL | true/false | R | |

### `sensor_water_leak` (WaterLeakSensorEntity)

| Feature | Type | Range/Values | Direction | Notes |
|---------|------|-------------|-----------|-------|
| `online` | BOOL | true/false | R | unknown = **online** |
| `water_leak_state` | BOOL | true/false | R | true = leak detected |
| `battery_percentage` | INTEGER | 0-100 | R | |
| `battery_low_power` | BOOL | true/false | R | |
| `signal_strength` | ENUM | `high`/`medium`/`low` | R | |

### `sensor_smoke` (SmokeSensorEntity)

| Feature | Type | Range/Values | Direction | Notes |
|---------|------|-------------|-----------|-------|
| `online` | BOOL | true/false | R | unknown = **online** |
| `smoke_state` | BOOL | true/false | R | true = smoke detected |
| `alarm_mute` | BOOL | true/false | R | From `alarm_mute` attribute |
| `battery_percentage` | INTEGER | 0-100 | R | |
| `battery_low_power` | BOOL | true/false | R | |
| `signal_strength` | ENUM | `high`/`medium`/`low` | R | |

### `sensor_gas` (GasSensorEntity)

| Feature | Type | Range/Values | Direction | Notes |
|---------|------|-------------|-----------|-------|
| `online` | BOOL | true/false | R | unknown = **online** |
| `gas_leak_state` | BOOL | true/false | R | true = gas detected |
| `alarm_mute` | BOOL | true/false | R | From `alarm_mute` attribute |
| `battery_percentage` | INTEGER | 0-100 | R | |
| `battery_low_power` | BOOL | true/false | R | |
| `signal_strength` | ENUM | `high`/`medium`/`low` | R | |

### `scenario_button` (ScenarioButtonEntity)

| Feature | Type | Range/Values | Direction | Notes |
|---------|------|-------------|-----------|-------|
| `online` | BOOL | true/false | R | |
| `button_event` | ENUM | `click`, `double_click`, `long_press` | R | on=click, off=double_click |

### `kettle` (KettleEntity)

| Feature | Type | Range/Values | Direction | Notes |
|---------|------|-------------|-----------|-------|
| `online` | BOOL | true/false | R | |
| `on_off` | BOOL | true/false | R/W | |
| `kitchen_water_temperature` | INTEGER | degrees (plain, NOT x10) | R | Current water temp |
| `kitchen_water_temperature_set` | INTEGER | 60-100, step 10 | R/W | Target temp |
| `kitchen_water_level` | INTEGER | | R | From `water_level` attribute |
| `kitchen_water_low_level` | BOOL | true/false | R | Heuristic: temp < 30 |
| `child_lock` | BOOL | true/false | R | |

### `tv` (TvEntity)

| Feature | Type | Range/Values | Direction | Notes |
|---------|------|-------------|-----------|-------|
| `online` | BOOL | true/false | R | |
| `on_off` | BOOL | true/false | R/W | |
| `volume_int` | INTEGER | 0-100, step 1 | R/W | HA 0.0-1.0 -> Sber 0-100 |
| `mute` | BOOL | true/false | R/W | |
| `source` | ENUM | dynamic (from `source_list`) | R/W | Input source |

### `vacuum_cleaner` (VacuumCleanerEntity)

| Feature | Type | Range/Values | Direction | Notes |
|---------|------|-------------|-----------|-------|
| `online` | BOOL | true/false | R | |
| `vacuum_cleaner_status` | ENUM | `cleaning`, `charging`, `docked`, `returning`, `error`, `paused` | R | |
| `vacuum_cleaner_command` | ENUM | `start`, `stop`, `pause`, `return_to_dock` | W | |
| `vacuum_cleaner_program` | ENUM | dynamic (from `fan_speed_list`) | R/W | Cleaning intensity |
| `battery_percentage` | INTEGER | 0-100 | R | |

### `intercom` (IntercomEntity, extends OnOffEntity)

| Feature | Type | Range/Values | Direction | Notes |
|---------|------|-------------|-----------|-------|
| `online` | BOOL | true/false | R | |
| `on_off` | BOOL | true/false | R/W | |
| `incoming_call` | BOOL | true/false | R | |
| `reject_call` | BOOL | true/false | R | |
| `unlock` | BOOL | true/false | R | |

---

## Entity Linking

### Allowed Link Roles by Category

| Primary Category | Allowed Roles |
|-----------------|---------------|
| `sensor_water_leak` | `battery`, `battery_low`, `signal_strength` |
| `sensor_pir` | `battery`, `battery_low`, `signal_strength` |
| `sensor_door` | `battery`, `battery_low`, `signal_strength` |
| `sensor_smoke` | `battery`, `battery_low`, `signal_strength` |
| `sensor_gas` | `battery`, `battery_low`, `signal_strength` |
| `sensor_temp` | `battery`, `battery_low`, `signal_strength`, `humidity` |
| `sensor_humidity` | `battery`, `battery_low`, `signal_strength`, `temperature` |
| `curtain` | `battery`, `battery_low`, `signal_strength` |
| `window_blind` | `battery`, `battery_low`, `signal_strength` |
| `gate` | `battery`, `battery_low`, `signal_strength` |
| `valve` | `battery`, `battery_low`, `signal_strength` |
| `hvac_ac` | `temperature` |
| `hvac_humidifier` | `humidity` |

### HA device_class -> Link Role

| HA device_class | HA domain | Link Role |
|----------------|-----------|-----------|
| `battery` | `sensor` | `battery` (percentage level) |
| `battery` | `binary_sensor` | `battery_low` (boolean low flag) |
| `temperature` | `sensor` | `temperature` |
| `humidity` | `sensor` | `humidity` |
| `signal_strength` | `sensor` | `signal_strength` |

> Note: `moisture` binary_sensor is **excluded** — it's a leak detector, not humidity.
> Both `battery` (sensor) and `battery_low` (binary_sensor) can be linked simultaneously.

### Wizard vs Link Dialog

- **Wizard** (Add Device step 2): shows only **same-device** candidates (`same_device_only=true`)
- **Link Dialog** (edit links): shows all candidates, grouped by same_device / other_devices

---

## Inheritance Hierarchy

```
BaseEntity (abstract)
  +-- LightEntity (light)
  |     +-- LedStripEntity (led_strip)
  +-- CurtainEntity (curtain)            [update_linked_data: battery, battery_low, signal]
  |     +-- WindowBlindEntity (window_blind)
  |     +-- GateEntity (gate)
  +-- ClimateEntity (hvac_ac)
  |     +-- HvacRadiatorEntity (hvac_radiator, temp 25-40, step 5)
  |     +-- HvacHeaterEntity (hvac_heater, temp 5-40, fan+thermostat)
  |     +-- HvacBoilerEntity (hvac_boiler, temp 25-80, step 5, thermostat)
  |     +-- HvacUnderfloorEntity (hvac_underfloor_heating, temp 25-50, step 5)
  +-- OnOffEntity (abstract)
  |     +-- RelayEntity (relay)
  |     |     +-- SocketEntity (socket)
  |     +-- IntercomEntity (intercom)
  +-- SimpleReadOnlySensor (abstract)    [_unknown_is_online flag, update_linked_data]
  |     +-- SensorTempEntity (sensor_temp)          [unknown=offline]
  |     +-- HumiditySensorEntity (sensor_temp)      [unknown=offline]
  |     +-- MotionSensorEntity (sensor_pir)         [unknown=ONLINE]
  |     +-- DoorSensorEntity (sensor_door)          [unknown=ONLINE]
  |     +-- WaterLeakSensorEntity (sensor_water_leak) [unknown=ONLINE]
  |     +-- SmokeSensorEntity (sensor_smoke)        [unknown=ONLINE]
  |     +-- GasSensorEntity (sensor_gas)            [unknown=ONLINE]
  +-- HumidifierEntity (hvac_humidifier)
  +-- HvacFanEntity (hvac_fan)
  +-- HvacAirPurifierEntity (hvac_air_purifier)     [imports speed constants from hvac_fan]
  +-- ScenarioButtonEntity (scenario_button)
  +-- KettleEntity (kettle)
  +-- TvEntity (tv)
  +-- VacuumCleanerEntity (vacuum_cleaner)
  +-- ValveEntity (valve)                [update_linked_data: battery, battery_low, signal]
```

---

## Architecture: Typed Constants & Pydantic Helpers (v1.10.0+)

### sber_constants.py

All string literals replaced with typed StrEnum constants:
- `SberFeature` — 61 feature key names
- `SberValueType` — BOOL, INTEGER, ENUM, COLOUR, FLOAT
- `HAState` — on, off, unavailable, unknown, open, closed, etc.
- `MqttTopicSuffix` — commands, status_request, config_request, etc.

### State Construction (sber_models.py helpers)

```python
# All device files use:
from ..sber_constants import SberFeature
from ..sber_models import make_state, make_bool_value, make_integer_value, make_enum_value

states = [
    make_state(SberFeature.ONLINE, make_bool_value(self._is_online)),
    make_state(SberFeature.ON_OFF, make_bool_value(self.current_state)),
    make_state(SberFeature.TEMPERATURE, make_integer_value(int(self.temperature * 10))),
]
```

`make_integer_value` outputs `str(value)` per Sber C2C spec.

### HA Context & Echo Loop Prevention (v1.10.0+)

- Sber commands include HA `Context` in service calls — logbook attribution
- State changes from Sber context IDs are not re-published (echo loop prevention)
- Bounded context ID set (max 200)

### Value Change Diffing (v1.10.0+)

- `BaseEntity.has_significant_change()` — compares current Sber state with last published
- `BaseEntity.mark_state_published()` — snapshots state after successful publish
- `_publish_states(force=True)` for Sber status_request responses (always respond)
