# Entity Registry — Sber Smart Home MQTT Bridge

> Auto-generated reference for all Sber device types, their features, allowed values,
> and HA domain mappings. Used for quick lookup during development and audit.

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
| cover | curtain | `curtain` | CurtainEntity | curtain.py |
| cover | blind/shade | `window_blind` | WindowBlindEntity | window_blind.py |
| cover | gate/garage_door | `gate` | GateEntity | gate.py |
| climate | * (default) | `hvac_ac` | ClimateEntity | climate.py |
| climate | (radiator override) | `hvac_radiator` | HvacRadiatorEntity | hvac_radiator.py |
| climate | (heater override) | `hvac_heater` | HvacHeaterEntity | hvac_heater.py |
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

## Feature Registry by Category

### `light` (LightEntity)

| Feature | Type | Range/Values | Direction | Notes |
|---------|------|-------------|-----------|-------|
| `on_off` | BOOL | true/false | R/W | Power state |
| `light_brightness` | INT | 50-1000 | R/W | Mapped from HA 0-255 |
| `light_colour` | COLOUR | `{h,s,v}` | R/W | HSV; h=0-360, s=0-1000, v=0-1000 |
| `light_mode` | ENUM | `white`, `colour` | R/W | Color mode selector |
| `light_colour_temp` | INT | 0-1000 | R/W | Mapped from HA mireds (min_mireds..max_mireds) |

### `led_strip` (LedStripEntity)

Same as `light` (inherits LightEntity, only category differs).

### `relay` (RelayEntity, extends OnOffEntity)

| Feature | Type | Range/Values | Direction | Notes |
|---------|------|-------------|-----------|-------|
| `on_off` | BOOL | true/false | R/W | Power state |
| `power` | INT | watts | R | From `current_power_w` attr |
| `voltage` | INT | volts | R | From `voltage` attr |
| `current` | INT | milliamps | R | From `current` attr |
| `child_lock` | BOOL | true/false | R | From `child_lock` attr |

### `socket` (SocketEntity, extends RelayEntity)

Same features as `relay`, category = `socket`.

### `curtain` (CurtainEntity)

| Feature | Type | Range/Values | Direction | Notes |
|---------|------|-------------|-----------|-------|
| `open_percentage` | INT | 0-100 | R/W | 0=closed, 100=open |
| `open_state` | ENUM | `open`, `close` | R | Current state |
| `open_set` | ENUM | `open`, `close`, `stop` | W | Command |

### `window_blind` (WindowBlindEntity, extends CurtainEntity)

Same features as `curtain`, category = `window_blind`.

### `gate` (GateEntity, extends CurtainEntity)

Same features as `curtain`, category = `gate`.

### `hvac_ac` (ClimateEntity)

| Feature | Type | Range/Values | Direction | Notes |
|---------|------|-------------|-----------|-------|
| `on_off` | BOOL | true/false | R/W | Power state |
| `temperature` | INT | x10 (e.g. 225 = 22.5C) | R | Current temp |
| `hvac_temp_set` | INT | min_temp..max_temp (whole degrees) | R/W | Target temp |
| `hvac_work_mode` | ENUM | `cooling`, `heating`, `dehumidification`, `ventilation`, `auto` | R/W | Mode |
| `hvac_air_flow_power` | ENUM | `auto`, `low`, `medium`, `high`, `turbo`, `quiet` | R/W | Fan speed |
| `hvac_air_flow_direction` | ENUM | `auto`, `no`, `vertical`, `horizontal`, `rotation`, `swing` | R/W | Swing mode |
| `hvac_humidity_set` | INT | 0-100 | R/W | Target humidity (if supported) |
| `hvac_night_mode` | BOOL | true/false | R/W | From `preset_mode == sleep` |

### `hvac_radiator` (HvacRadiatorEntity, extends ClimateEntity)

| Feature | Type | Range/Values | Direction | Notes |
|---------|------|-------------|-----------|-------|
| `on_off` | BOOL | true/false | R/W | |
| `temperature` | INT | x10 | R | Current temp |
| `hvac_temp_set` | INT | 25-40 | R/W | Target temp |
| `hvac_work_mode` | ENUM | `heating` | R | Fixed mode |
| `hvac_air_flow_power` | ENUM | `auto`, `low`, `medium`, `high` | R/W | Fan speed |

### `hvac_heater` (HvacHeaterEntity, extends ClimateEntity)

| Feature | Type | Range/Values | Direction | Notes |
|---------|------|-------------|-----------|-------|
| `on_off` | BOOL | true/false | R/W | |
| `temperature` | INT | x10 | R | Current temp |
| `hvac_temp_set` | INT | 5-40 | R/W | Target temp |
| `hvac_work_mode` | ENUM | `heating` | R | Fixed mode |
| `hvac_air_flow_power` | ENUM | `auto`, `low`, `medium`, `high` | R/W | Fan speed |

### `hvac_boiler` (HvacBoilerEntity, extends ClimateEntity)

| Feature | Type | Range/Values | Direction | Notes |
|---------|------|-------------|-----------|-------|
| `on_off` | BOOL | true/false | R/W | |
| `temperature` | INT | x10 | R | Current temp |
| `hvac_temp_set` | INT | 25-80 | R/W | Target temp |
| `hvac_work_mode` | ENUM | `heating` | R | Fixed mode |

### `hvac_underfloor_heating` (HvacUnderfloorEntity, extends ClimateEntity)

| Feature | Type | Range/Values | Direction | Notes |
|---------|------|-------------|-----------|-------|
| `on_off` | BOOL | true/false | R/W | |
| `temperature` | INT | x10 | R | Current temp |
| `hvac_temp_set` | INT | 25-50 | R/W | Target temp |
| `hvac_work_mode` | ENUM | `heating` | R | Fixed mode |

### `hvac_humidifier` (HumidifierEntity)

| Feature | Type | Range/Values | Direction | Notes |
|---------|------|-------------|-----------|-------|
| `on_off` | BOOL | true/false | R/W | |
| `humidity` | INT | 0-100 | R | Current humidity |
| `hvac_humidity_set` | INT | 0-100 | R/W | Target humidity |
| `hvac_air_flow_power` | ENUM | `auto`, `low`, `medium`, `high`, `turbo`, `quiet` | R/W | Fan speed |
| `hvac_night_mode` | BOOL | true/false | R/W | |

### `hvac_fan` (HvacFanEntity)

| Feature | Type | Range/Values | Direction | Notes |
|---------|------|-------------|-----------|-------|
| `on_off` | BOOL | true/false | R/W | |
| `hvac_air_flow_power` | ENUM | `auto`, `high`, `low`, `medium`, `turbo` | R/W | Fan speed |

### `hvac_air_purifier` (HvacAirPurifierEntity)

| Feature | Type | Range/Values | Direction | Notes |
|---------|------|-------------|-----------|-------|
| `on_off` | BOOL | true/false | R/W | |
| `hvac_air_flow_power` | ENUM | `auto`, `low`, `medium`, `high`, `turbo`, `quiet` | R/W | Fan speed |
| `hvac_ionization` | BOOL | true/false | R/W | |
| `hvac_night_mode` | BOOL | true/false | R/W | |
| `hvac_aromatization` | BOOL | true/false | R | |
| `hvac_replace_filter` | BOOL | true/false | R | Filter replacement needed |
| `hvac_replace_ionizator` | BOOL | true/false | R | Ionizer replacement needed |

### `valve` (ValveEntity)

| Feature | Type | Range/Values | Direction | Notes |
|---------|------|-------------|-----------|-------|
| `open_state` | ENUM | `open`, `close` | R | Current state |
| `open_set` | ENUM | `open`, `close`, `stop` | W | Command |

### `sensor_temp` (SensorTempEntity)

| Feature | Type | Range/Values | Direction | Notes |
|---------|------|-------------|-----------|-------|
| `online` | BOOL | true/false | R | Always true when state exists |
| `temperature` | INT | x10 (e.g. 225 = 22.5C) | R | |
| `battery_percentage` | INT | 0-100 | R | Linked entity only |
| `battery_low_power` | BOOL | true/false | R | < 20% |
| `signal_strength` | ENUM | `high`, `medium`, `low` | R | Linked entity only |
| `humidity` | INT | 0-100 | R | Linked entity only |

### `sensor_temp` (HumiditySensorEntity, same category)

| Feature | Type | Range/Values | Direction | Notes |
|---------|------|-------------|-----------|-------|
| `online` | BOOL | true/false | R | |
| `humidity` | INT | 0-100 | R | |
| `battery_percentage` | INT | 0-100 | R | Linked entity only |
| `battery_low_power` | BOOL | true/false | R | < 20% |
| `signal_strength` | ENUM | `high`, `medium`, `low` | R | Linked entity only |
| `temperature` | INT | x10 | R | Linked entity only |

### `sensor_pir` (MotionSensorEntity)

| Feature | Type | Range/Values | Direction | Notes |
|---------|------|-------------|-----------|-------|
| `online` | BOOL | true/false | R | |
| `pir` | ENUM | `pir` | R | Always "pir" when motion detected |
| `battery_percentage` | INT | 0-100 | R | Linked |
| `battery_low_power` | BOOL | true/false | R | Linked |
| `signal_strength` | ENUM | `high`/`medium`/`low` | R | Linked |
| `tamper_alarm` | BOOL | true/false | R | From `tamper` attr |

### `sensor_door` (DoorSensorEntity)

| Feature | Type | Range/Values | Direction | Notes |
|---------|------|-------------|-----------|-------|
| `online` | BOOL | true/false | R | |
| `doorcontact_state` | BOOL | true/false | R | true = open |
| `battery_percentage` | INT | 0-100 | R | Linked |
| `battery_low_power` | BOOL | true/false | R | Linked |
| `signal_strength` | ENUM | `high`/`medium`/`low` | R | Linked |
| `tamper_alarm` | BOOL | true/false | R | From `tamper` attr |

### `sensor_water_leak` (WaterLeakSensorEntity)

| Feature | Type | Range/Values | Direction | Notes |
|---------|------|-------------|-----------|-------|
| `online` | BOOL | true/false | R | |
| `water_leak_state` | BOOL | true/false | R | true = leak detected |
| `battery_percentage` | INT | 0-100 | R | Linked |
| `battery_low_power` | BOOL | true/false | R | Linked |
| `signal_strength` | ENUM | `high`/`medium`/`low` | R | Linked |

### `sensor_smoke` (SmokeSensorEntity)

| Feature | Type | Range/Values | Direction | Notes |
|---------|------|-------------|-----------|-------|
| `online` | BOOL | true/false | R | |
| `smoke_state` | BOOL | true/false | R | true = smoke detected |
| `battery_percentage` | INT | 0-100 | R | Linked |
| `battery_low_power` | BOOL | true/false | R | Linked |
| `signal_strength` | ENUM | `high`/`medium`/`low` | R | Linked |

### `sensor_gas` (GasSensorEntity)

| Feature | Type | Range/Values | Direction | Notes |
|---------|------|-------------|-----------|-------|
| `online` | BOOL | true/false | R | |
| `gas_leak_state` | BOOL | true/false | R | true = gas detected |
| `battery_percentage` | INT | 0-100 | R | Linked |
| `battery_low_power` | BOOL | true/false | R | Linked |
| `signal_strength` | ENUM | `high`/`medium`/`low` | R | Linked |

### `scenario_button` (ScenarioButtonEntity)

| Feature | Type | Range/Values | Direction | Notes |
|---------|------|-------------|-----------|-------|
| `button_event` | ENUM | `click`, `double_click`, `long_press` | R/W | |

### `kettle` (KettleEntity)

| Feature | Type | Range/Values | Direction | Notes |
|---------|------|-------------|-----------|-------|
| `on_off` | BOOL | true/false | R/W | |
| `kitchen_water_temperature` | INT | degrees | R | Current temp |
| `kitchen_water_temperature_set` | INT | 60-100 | R/W | Target temp |
| `kitchen_water_low_level` | BOOL | true/false | R | Low water level |
| `child_lock` | BOOL | true/false | R/W | |

### `tv` (TvEntity)

| Feature | Type | Range/Values | Direction | Notes |
|---------|------|-------------|-----------|-------|
| `on_off` | BOOL | true/false | R/W | |
| `volume_int` | INT | 0-100 | R/W | |
| `mute` | BOOL | true/false | R/W | |
| `source` | ENUM | dynamic (from `source_list`) | R/W | Input source |

### `vacuum_cleaner` (VacuumCleanerEntity)

| Feature | Type | Range/Values | Direction | Notes |
|---------|------|-------------|-----------|-------|
| `vacuum_cleaner_status` | ENUM | `cleaning`, `charging`, `docked`, `returning`, `error`, `paused` | R | |
| `vacuum_cleaner_command` | ENUM | `start`, `stop`, `pause`, `return_to_dock` | W | |
| `vacuum_cleaner_program` | ENUM | dynamic (from `fan_speed_list`) | R/W | |
| `battery_percentage` | INT | 0-100 | R | |

### `intercom` (IntercomEntity, extends OnOffEntity)

| Feature | Type | Range/Values | Direction | Notes |
|---------|------|-------------|-----------|-------|
| `on_off` | BOOL | true/false | R/W | |
| `incoming_call` | BOOL | true/false | R | |
| `reject_call` | BOOL | true/false | W | |
| `unlock` | BOOL | true/false | W | |

---

## Entity Linking (Auxiliary Sensors)

### Allowed Link Roles by Category

| Primary Category | Allowed Roles |
|-----------------|---------------|
| `sensor_water_leak` | `battery`, `signal_strength` |
| `sensor_pir` | `battery`, `signal_strength` |
| `sensor_door` | `battery`, `signal_strength` |
| `sensor_smoke` | `battery`, `signal_strength` |
| `sensor_gas` | `battery`, `signal_strength` |
| `sensor_temp` | `battery`, `signal_strength`, `humidity` |
| `sensor_humidity` | `battery`, `signal_strength`, `temperature` |
| `hvac_ac` | `temperature` |
| `hvac_humidifier` | `humidity` |

### HA device_class -> Link Role

| HA device_class | Link Role |
|----------------|-----------|
| `battery` | `battery` |
| `temperature` | `temperature` |
| `humidity` | `humidity` |
| `moisture` | `humidity` |
| `signal_strength` | `signal_strength` |

---

## Inheritance Hierarchy

```
BaseEntity (abstract)
  +-- LightEntity (light)
  |     +-- LedStripEntity (led_strip)
  +-- CurtainEntity (curtain)
  |     +-- WindowBlindEntity (window_blind)
  |     +-- GateEntity (gate)
  +-- ClimateEntity (hvac_ac)
  |     +-- HvacRadiatorEntity (hvac_radiator, temp 25-40)
  |     +-- HvacHeaterEntity (hvac_heater, temp 5-40)
  |     +-- HvacBoilerEntity (hvac_boiler, temp 25-80)
  |     +-- HvacUnderfloorEntity (hvac_underfloor_heating, temp 25-50)
  +-- OnOffEntity (abstract)
  |     +-- RelayEntity (relay)
  |     |     +-- SocketEntity (socket)
  |     +-- IntercomEntity (intercom)
  |     +-- ValveEntity (valve)
  +-- SimpleReadOnlySensor (abstract)
  |     +-- SensorTempEntity (sensor_temp)
  |     +-- HumiditySensorEntity (sensor_temp)
  |     +-- MotionSensorEntity (sensor_pir)
  |     +-- DoorSensorEntity (sensor_door)
  |     +-- WaterLeakSensorEntity (sensor_water_leak)
  |     +-- SmokeSensorEntity (sensor_smoke)
  |     +-- GasSensorEntity (sensor_gas)
  +-- HumidifierEntity (hvac_humidifier)
  +-- HvacFanEntity (hvac_fan)
  +-- HvacAirPurifierEntity (hvac_air_purifier)
  +-- ScenarioButtonEntity (scenario_button)
  +-- KettleEntity (kettle)
  +-- TvEntity (tv)
  +-- VacuumCleanerEntity (vacuum_cleaner)
```
