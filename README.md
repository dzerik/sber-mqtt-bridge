# Sber Smart Home MQTT Bridge

[![HACS](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz)
[![GitHub Release](https://img.shields.io/github/v/release/dzerik/sber-mqtt-bridge)](https://github.com/dzerik/sber-mqtt-bridge/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE.txt)

**[Документация на русском / Russian documentation](README_RU.md)**

Home Assistant custom integration for bridging HA entities to [Sber Smart Home](https://developers.sber.ru/docs/ru/smarthome) cloud via MQTT. Control your Home Assistant devices through Sber voice assistants (**Salut**) and the **Sber Smart Home** mobile app.

## How It Works

```
Home Assistant  ←→  This Integration  ←→  Sber MQTT Cloud  ←→  Sber App / Salut
     (your devices)      (bridge)          (mqtt-partners.iot)     (voice control)
```

The integration connects to the Sber MQTT broker, publishes your HA devices as Sber Smart Home devices, and translates commands back to HA service calls. State changes in HA are instantly reflected in the Sber app.

## Features

- Native HA integration — installs via HACS, no addons required
- Config Flow UI — set up entirely from the HA interface
- Bulk entity selection — add all entities, by domain, or pick individually
- Smart deduplication — when a device has both `light` and `switch` entities, only the richer one is exposed
- Real-time state sync — HA changes are instantly reflected in Sber (with 100ms debounce)
- Voice control through all Sber assistants (Salut, Athena, Joy)
- 15 device types with automatic mapping
- Connection health monitoring and diagnostics
- Device acknowledgment tracking — see which devices Sber has confirmed
- Automatic MQTT reconnection with exponential backoff (5s → 5min)
- SSL certificate verification (configurable)
- Translations: English and Russian

## Supported Device Types

| HA Domain | Sber Category | Capabilities |
|-----------|---------------|--------------|
| `light` | light | On/off, brightness, color (HSV), color temperature |
| `switch` | relay | On/off |
| `switch` (outlet) | socket | On/off (smart socket icon in Sber) |
| `script` | relay | Execute script |
| `button` | relay | Press button |
| `cover` | curtain | Open/close/stop, position 0-100% |
| `cover` (blind/shade) | window_blind | Open/close/stop, position 0-100% |
| `climate` | hvac_ac | On/off, temperature, fan mode, swing, HVAC mode |
| `climate` (radiator) | hvac_radiator | On/off, temperature (25-40C default) |
| `sensor` (temperature) | sensor_temp | Temperature reading (x10 precision) |
| `sensor` (humidity) | sensor_temp | Humidity reading (0-100%) |
| `binary_sensor` (motion) | sensor_pir | Motion detected (boolean) |
| `binary_sensor` (door) | sensor_door | Open/close state |
| `binary_sensor` (moisture) | sensor_water_leak | Leak detected (boolean) |
| `input_boolean` | scenario_button | Click / double click events |
| `valve` | valve | Open/close valve |
| `humidifier` | hvac_humidifier | On/off, target humidity, work mode |

## Prerequisites — Setting Up Sber Studio

Before installing the integration, you need MQTT credentials from Sber:

### Step 1: Register in Sber Studio

1. Go to [Sber Studio](https://developers.sber.ru/studio/workspaces/)
2. Sign in with your Sber ID (same account as Sber Smart Home app)
3. Create a new workspace if you don't have one

### Step 2: Create an Integration Project

1. In Sber Studio, go to **Smart Home** section
2. Click **Create Project** (or **Создать проект**)
3. Select **MQTT Integration** type
4. Give it a name (e.g. "Home Assistant Bridge")

### Step 3: Get MQTT Credentials

1. Open your project settings
2. Find the **MQTT Connection** section
3. Copy **Login** and **Password** — you will need these in HA
4. The broker address is `mqtt-partners.iot.sberdevices.ru`, port `8883`

For detailed instructions, see [Sber MQTT-to-Cloud documentation](https://developers.sber.ru/docs/ru/smarthome/mqtt-diy/mqtt-to-diy).

### Step 4: Link Sber App

1. Open the **Sber Smart Home** app on your phone
2. Go to **Settings** > **Connected Services** (or **Подключенные сервисы**)
3. Your MQTT integration should appear — enable it
4. Devices will appear in the app after the bridge connects

## Installation

### HACS (recommended)

1. Open **HACS** in Home Assistant
2. Click the three dots menu > **Custom repositories**
3. Add `https://github.com/dzerik/sber-mqtt-bridge` with category **Integration**
4. Search for **"Sber Smart Home MQTT Bridge"** and click **Install**
5. **Restart Home Assistant**

### Manual

1. Download the [latest release](https://github.com/dzerik/sber-mqtt-bridge/releases)
2. Copy `custom_components/sber_mqtt_bridge/` to your HA `config/custom_components/`
3. Restart Home Assistant

## Configuration

### Initial Setup

1. Go to **Settings** > **Devices & Services** > **Add Integration**
2. Search for **"Sber Smart Home MQTT Bridge"**
3. Enter your Sber MQTT credentials:

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| MQTT Login | Yes | — | Login from Sber Studio project |
| MQTT Password | Yes | — | Password from Sber Studio project |
| MQTT Broker | No | `mqtt-partners.iot.sberdevices.ru` | Broker address |
| MQTT Port | No | `8883` | Broker port (TLS) |
| Verify SSL | No | `true` | Verify broker certificate |

### Selecting Entities

After setup, go to integration options to choose which entities to expose to Sber. Four modes are available:

| Mode | Description |
|------|-------------|
| **Select manually** | Pick individual entities from a searchable list. You can also remove entities here. |
| **Add by domain** | Select domains (Lights, Switches, etc.) with entity counts. Adds all entities from chosen domains. Preserves existing selection. |
| **Add ALL** | One-click: add every supported entity to Sber. |
| **Remove ALL** | Clear the entire exposed list. |

**Smart deduplication**: When a Zigbee device registers both `light.kitchen` and `switch.kitchen`, only `light` is included (richer API with brightness/color). Priority: light > cover > climate > humidifier > valve > sensor > switch > script > button.

### Managing Devices in Sber App

After entities are exposed:

1. Open the **Sber Smart Home** app
2. Devices appear automatically (may take 10-30 seconds)
3. **Rename devices**: tap the device > settings icon > change name
4. **Assign rooms**: tap the device > settings icon > select room
5. **Voice control**: say *"Салют, включи свет на кухне"* (Salut, turn on kitchen light)

**Note**: Room assignments and renames made in the Sber app are stored locally in the integration and will be included in future config publishes.

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Cannot connect | Verify credentials in Sber Studio. Check that your project is active. |
| SSL errors | Try disabling "Verify SSL" in integration settings (for custom CA). |
| Entities not in Sber | Check Options > select entities. Check HA logs for mapping warnings. |
| Devices appear/disappear | Check HA logs for reconnection messages. Ensure stable internet. |
| Duplicate devices | Remove duplicates in Options > manual mode. Or use "Remove ALL" then "Add ALL" for clean reset. |
| Sensors show wrong values | Enable debug logging and check entity mapping in logs. |

### Debug Logging

Add to `configuration.yaml`:

```yaml
logger:
  logs:
    custom_components.sber_mqtt_bridge: debug
```

This will show:
- `MQTT <- topic (N bytes)` — every incoming message
- `Sber -> HA command: entity_id [keys]` — command details
- `HA -> Sber state: entity_id = state` — state publishes
- `Entity xxx -> Sber category (domain, device_class)` — mapping decisions
- `Sber error (#N): {...}` — errors from Sber cloud

### Diagnostics

Go to **Settings** > **Devices & Services** > **Sber Smart Home MQTT Bridge** > **three dots** > **Download diagnostics**. The file contains:
- Connection status and uptime
- Message counters (received, sent, errors)
- List of acknowledged/unacknowledged entities
- Entity configuration

## Acknowledgments

This project is a fork and evolution of [MQTT-SberGate](https://gitverse.ru/mberezovsky/MQTT-SberGate) by [@mberezovsky](https://gitverse.ru/mberezovsky). The original project provided the Sber Smart Home MQTT protocol implementation as a Home Assistant addon. This version has been rewritten as a native HACS custom integration with full async support, Config Flow UI, and comprehensive test coverage.

Thank you to the original author for the foundational work and Sber protocol reverse-engineering.

## Trademarks & Legal Notice

All product names, logos, and brands mentioned in this project are property of their respective owners:

- **Sber**, **SberDevices**, **Salut**, **Sber Smart Home** are trademarks of [Sber](https://www.sber.ru/) (PAO Sberbank).
- **Home Assistant** is a trademark of the [Home Assistant](https://www.home-assistant.io/) project.
- **HACS** (Home Assistant Community Store) is an independent community project.

This project is not affiliated with, endorsed by, or sponsored by Sber, SberDevices, or the Home Assistant project. It is an independent open-source community integration.

## Links

- [Sber Smart Home Developer Portal](https://developers.sber.ru/docs/ru/smarthome)
- [Register in Sber Studio](https://developers.sber.ru/docs/ru/smarthome/space/registration)
- [MQTT-to-Cloud Integration Guide](https://developers.sber.ru/docs/ru/smarthome/mqtt-diy/mqtt-to-diy)
- [Supported Device Categories](https://developers.sber.ru/docs/ru/smarthome/c2c/devices)
- [Telegram Community](https://t.me/+k_w9uO0h73FkNjJi)

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup and guidelines.

## License

[MIT](LICENSE.txt)
